"""RS1.3/.5/.11: offline lock trust and complete admission witnesses."""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from vibecomfy import resources
from vibecomfy.commands import nodes
from vibecomfy.node_approvals import approval_record
from vibecomfy.node_packs import CustomNodePack, LockEntry, read_lockfile, write_lockfile
from vibecomfy.node_packs import _install as install
from vibecomfy.node_packs._lockfile import DeclaredPatch


URL = "https://example.test/lock-trust.git"


def _approval(entry):
    return approval_record(
        {"repo": entry.url, "commit": entry.commit,
         "requirements_txt": entry.requirements_txt, "pip_no_deps": list(entry.pip_no_deps)},
        placement_class="local",
    )


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    root = tmp_path / "engine"
    root.mkdir()
    path = root / "custom_nodes.lock"
    path.write_text("# empty trusted catalog\n", encoding="utf-8")
    monkeypatch.setattr(resources, "_selected_layout", lambda: ("checkout", root))
    return path


def _git_checkout(tmp_path):
    pack = tmp_path / "custom_nodes" / "LockTrust"
    pack.mkdir(parents=True)

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(pack), *args], check=True, capture_output=True, text=True,
        ).stdout.strip()

    git("init")
    git("config", "user.name", "Lock trust test")
    git("config", "user.email", "lock-trust@example.test")
    git("config", "commit.gpgsign", "false")
    git("remote", "add", "origin", URL)
    tracked = pack / "node.py"
    tracked.write_bytes(b"original\n")
    git("add", "node.py")
    git("commit", "-m", "initial")
    entry = LockEntry("LockTrust", git("rev-parse", "HEAD"), URL, class_set=("LockTrustNode",))
    tracked.write_bytes(b"patched\n")
    return pack, tracked, entry


@pytest.mark.parametrize("reviewed", [False, True], ids=["unreviewed", "different-digest"])
def test_target_patch_hash_cannot_authorize_dirty_checkout(tmp_path, catalog, reviewed):
    pack, tracked, entry = _git_checkout(tmp_path)
    if reviewed:
        write_lockfile([replace(entry, patches=(DeclaredPatch("node.py", "0" * 64),))], catalog)
    forged = replace(entry, patches=(DeclaredPatch("node.py", hashlib.sha256(tracked.read_bytes()).hexdigest()),))
    lock = tmp_path / "target.lock"
    write_lockfile([forged], lock)
    before = lock.read_bytes()
    calls = []

    def runner(*args, **kwargs):
        calls.append(args[0])
        return subprocess.run(*args, **kwargs)

    result = install.restore_pack(forged, install_root=pack.parent, lockfile_path=lock,
                                  approvals=[_approval(entry)], runner=runner)
    assert result.status == "failed"
    assert "patch" in result.error and "needs_consent:" in result.error
    assert calls == []
    assert lock.read_bytes() == before and tracked.read_bytes() == b"patched\n"
    assert install.inspect_pack_install_state(
        entry.name, install_roots=[pack.parent], expected_head=entry.commit, entry=forged,
    ).state == "dirty"


def test_exact_shipped_patch_still_verifies(tmp_path, catalog):
    pack, tracked, entry = _git_checkout(tmp_path)
    trusted = replace(entry, patches=(DeclaredPatch("node.py", hashlib.sha256(tracked.read_bytes()).hexdigest()),))
    write_lockfile([trusted], catalog)
    lock = tmp_path / "target.lock"
    write_lockfile([trusted], lock)
    before = lock.read_bytes()
    result = install.restore_pack(trusted, install_root=pack.parent, lockfile_path=lock)
    assert result.status == "refreshed" and result.verified_patches == 1
    assert tracked.read_bytes() == b"patched\n" and lock.read_bytes() == before


@pytest.mark.parametrize("alias", [False, True], ids=["direct", "resolved-alias"])
def test_restore_refuses_shipped_catalog_before_install(tmp_path, catalog, alias):
    entry = LockEntry("LockTrust", "a" * 40, URL, class_set=("LockTrustNode",))
    target = catalog
    if alias:
        (catalog.parent / "child").mkdir()
        target = catalog.parent / "child" / ".." / catalog.name
    before = catalog.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("subprocess called before refusing shipped catalog")

    root = tmp_path / "custom_nodes"
    result = install.restore_pack(entry, install_root=root, lockfile_path=target,
                                  approvals=[_approval(entry)], runner=forbidden)
    assert result.status == "failed" and "shipped catalog" in result.error
    assert not root.exists() and catalog.read_bytes() == before


def test_cli_refuses_shipped_catalog_before_restore(tmp_path, catalog, monkeypatch, capsys):
    entry = LockEntry("LockTrust", "a" * 40, URL, class_set=("LockTrustNode",))
    write_lockfile([entry], catalog)
    before = catalog.read_bytes()
    monkeypatch.chdir(catalog.parent)
    monkeypatch.setattr(nodes.node_packs_install, "restore_pack",
                        lambda *a, **kw: pytest.fail("restore called on shipped catalog"))
    assert nodes._cmd_nodes_restore(SimpleNamespace(lockfile="custom_nodes.lock")) == 1
    assert "shipped catalog" in capsys.readouterr().err
    assert catalog.read_bytes() == before


def test_batch_refuses_shipped_catalog_before_preflight(tmp_path, catalog, monkeypatch):
    entry = LockEntry("LockTrust", "a" * 40, URL, class_set=("LockTrustNode",), pip_packages=("example==1",))
    write_lockfile([entry], catalog)
    before = catalog.read_bytes()
    pack = CustomNodePack(entry.name, entry.url, frozenset(entry.class_set), entry.pip_packages)
    monkeypatch.setattr(install, "preflight_pip_requirements",
                        lambda *a, **kw: pytest.fail("pip preflight called for shipped catalog"))
    root = tmp_path / "custom_nodes"
    result = install.install_required_packs([pack], restore_entries=[entry],
                                            install_root=root, lockfile_path=catalog)
    assert not result.ok and "shipped catalog" in result.preflight.error
    assert not root.exists() and catalog.read_bytes() == before


_VALID = '{name = "LockTrust", git_commit_sha = "' + "a" * 40 + '", url = "' + URL + '"}'
_BAD_LAYOUTS = [
    pytest.param("entries = [" + _VALID + ", 17]\n", "entries[1]", id="array-non-table"),
    pytest.param("nodepacks = {LockTrust = " + _VALID + ", Bad = 17}\n", "Bad", id="map-non-table"),
    pytest.param("unknown = 17\n", "unknown", id="unknown-layout"),
    pytest.param("entries = [" + _VALID + "]\nunknown = 17\n", "unknown", id="mixed-layout"),
    pytest.param("[Unknown]\nvalue = 17\n", "Unknown", id="unknown-table"),
    pytest.param("entries = {LockTrust = " + _VALID + "}\n", "entries", id="wrong-array-type"),
    pytest.param("nodepacks = [" + _VALID + "]\n", "nodepacks", id="wrong-map-type"),
]


@pytest.mark.parametrize("body,row", _BAD_LAYOUTS)
def test_malformed_lock_refuses_entire_restore_before_side_effects(tmp_path, catalog, monkeypatch, capsys, body, row):
    lock = tmp_path / "target.lock"
    lock.write_text(body, encoding="utf-8")
    entry = LockEntry("LockTrust", "a" * 40, URL)
    approval = tmp_path / "approvals.json"
    approval.write_text(json.dumps([_approval(entry)]), encoding="utf-8")
    before = lock.read_bytes()
    monkeypatch.setattr(nodes.node_packs_install, "restore_pack",
                        lambda *a, **kw: pytest.fail("partial restore after malformed lock"))
    assert nodes._cmd_nodes_restore(SimpleNamespace(lockfile=str(lock), approvals=str(approval))) == 1
    assert row in capsys.readouterr().err
    with pytest.raises(ValueError) as failure:
        read_lockfile(lock)
    assert row in str(failure.value)
    assert lock.read_bytes() == before
