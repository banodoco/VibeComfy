"""F1 RS1.2/RS1.4: exercise real Git, with every non-file protocol forbidden."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.fixtures.node_recipe_runner import RecipeRunner
from tests.fixtures.node_restore_checkout import assert_staged_restore
from vibecomfy.node_approvals import approval_record
from vibecomfy.node_packs import LockEntry, read_lockfile, restore_pack
from vibecomfy.node_packs import _install as install

APPROVED = "https://example.test/Owner/Pack.git"
OTHER_CASE = "https://example.test/Owner/pack.git"


class OfflineGit:
    def __init__(self, upstream):
        self.upstream = upstream
        self.calls = []

    def __call__(self, args, **kwargs):
        call = list(args)
        assert call[0] == "git", f"unexpected subprocess: {call}"
        self.calls.append(call)
        # Git records the authored URL in remote.origin.url. Only the test
        # transport is redirected, and GIT_ALLOW_PROTOCOL blocks network.
        prefix = [
            "git",
            "-c", f"url.{self.upstream.as_uri()}.insteadOf={APPROVED}",
            "-c", f"url.{self.upstream.as_uri()}.insteadOf={OTHER_CASE}",
        ]
        return subprocess.run([*prefix, *call[1:]], **kwargs)

    def git(self, *args):
        return self(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    runner = OfflineGit(upstream)
    runner.git("-C", str(upstream), "init", "-b", "main")
    runner.git("-C", str(upstream), "config", "user.name", "Offline fixture")
    runner.git("-C", str(upstream), "config", "user.email", "offline@example.test")
    (upstream / "nodes.py").write_text("APPROVED = True\n", encoding="utf-8")
    runner.git("-C", str(upstream), "add", "nodes.py")
    runner.git("-C", str(upstream), "commit", "-m", "approved")
    pin = runner.git("-C", str(upstream), "rev-parse", "HEAD")
    (upstream / "nodes.py").write_text("UNAPPROVED_DEFAULT = True\n", encoding="utf-8")
    runner.git("-C", str(upstream), "add", "nodes.py")
    runner.git("-C", str(upstream), "commit", "-m", "unapproved default")
    default = runner.git("-C", str(upstream), "rev-parse", "HEAD")
    runner.calls.clear()
    return runner, pin, default


def _restore(root, lock, pin, runner, **changes):
    entry = LockEntry("Pack", pin, APPROVED, **changes)
    approval = approval_record(
        {"repo": entry.url, "commit": entry.git_commit_sha,
         "requirements_txt": entry.requirements_txt, "pip_no_deps": list(entry.pip_no_deps)},
        placement_class="local",
    )
    return restore_pack(entry, install_root=root, lockfile_path=lock,
                        approvals=[approval], runner=runner)


def _existing(root, runner, url=APPROVED):
    root.mkdir()
    live = root / "Pack"
    runner.git("clone", "--", url, str(live))
    runner.calls.clear()
    return live


def test_rs1_2_missing_pin_never_leaves_default_branch_loadable(tmp_path, source):
    runner, _, _ = source
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"
    result = _restore(root, lock, "0" * 40, runner)
    assert result.status == "failed"
    # Baseline clones the remote default into the live directory, then fails
    # checkout. This is the actual regression witness, not a command mock.
    assert not (root / "Pack").exists()
    assert not lock.exists()
    assert not list(tmp_path.glob(".vibecomfy-restore-*"))


def test_rs1_4_case_distinct_repository_refused_before_fetch(tmp_path, source):
    runner, pin, default = source
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"
    live = _existing(root, runner, OTHER_CASE)
    original = (live / "nodes.py").read_bytes()
    result = _restore(root, lock, pin, runner)
    # Baseline case-folds the whole URL, fetches the existing origin and
    # succeeds. Candidate must refuse before any fetch/checkout or lock write.
    assert result.status == "failed"
    assert "repository differs" in result.error
    assert runner.calls == [["git", "-C", str(live), "config", "--get", "remote.origin.url"]]
    assert runner.git("-C", str(live), "rev-parse", "HEAD") == default
    assert (live / "nodes.py").read_bytes() == original
    assert not lock.exists()


@pytest.mark.parametrize("existing", [False, True], ids=["fresh", "changed-pin"])
def test_restore_publishes_only_verified_pin_from_approved_url(tmp_path, source, existing):
    runner, pin, default = source
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"
    live = root / "Pack"
    if existing:
        _existing(root, runner)
    staged_paths = []

    def observe(args, **kwargs):
        call = list(args)
        result = runner(call, **kwargs)
        if call[:2] == ["git", "clone"]:
            staged = Path(call[-1])
            staged_paths.append(staged)
            assert not live.exists()
            assert not staged.is_relative_to(root)
            assert not (staged / "nodes.py").exists(), "default branch must never be checked out"
        elif call[:2] == ["git", "-C"] and Path(call[2]) in staged_paths:
            assert not live.exists(), "staged Git operations must precede publication"
            if call[3] == "checkout":
                assert (Path(call[2]) / "nodes.py").read_text() == "APPROVED = True\n"
        return result

    result = _restore(root, lock, pin, observe)
    assert result.status == ("refreshed" if existing else "installed")
    assert result.git_commit_sha == pin
    assert_staged_restore(runner.calls, root, "Pack", APPROVED, pin)
    assert [call for call in runner.calls if call[3:4] == ["fetch"]] == [
        ["git", "-C", str(staged_paths[0]), "fetch", "--", APPROVED, pin]
    ]
    assert runner.git("-C", str(live), "rev-parse", "HEAD") == pin != default
    assert runner.git("-C", str(live), "config", "--get", "remote.origin.url") == APPROVED
    assert (live / "nodes.py").read_text() == "APPROVED = True\n"
    assert read_lockfile(lock) == [LockEntry("Pack", pin, APPROVED)]
    assert not list(tmp_path.glob(".vibecomfy-restore-*"))


def test_failed_changed_pin_quarantines_previous_checkout_outside_root(tmp_path, source):
    runner, _, default = source
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"
    live = _existing(root, runner)
    result = _restore(root, lock, "0" * 40, runner)
    assert result.status == "failed"
    assert not live.exists()
    assert not lock.exists()
    [previous] = tmp_path.glob(".vibecomfy-restore-*/previous")
    assert str(previous) in result.error
    assert runner.git("-C", str(previous), "rev-parse", "HEAD") == default
    assert (previous / "nodes.py").read_text() == "UNAPPROVED_DEFAULT = True\n"
    assert not (previous.parent / "checkout").exists()


@pytest.mark.parametrize("tamper", ["origin", "head"], ids=["origin", "head"])
def test_staged_verification_failure_never_publishes(tmp_path, source, tamper):
    runner, pin, default = source
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"

    def wrong_checkout(args, **kwargs):
        call = list(args)
        if tamper == "head" and call[:2] == ["git", "-C"] and call[3] == "checkout":
            return runner([*call[:4], default], **kwargs)
        result = runner(call, **kwargs)
        if tamper == "origin" and call[:2] == ["git", "clone"]:
            runner.git("-C", call[-1], "config", "remote.origin.url", OTHER_CASE)
        return result

    result = _restore(root, lock, pin, wrong_checkout)
    assert result.status == "failed"
    assert ("repository differs" if tamper == "origin" else "expected git HEAD") in result.error
    assert not (root / "Pack").exists()
    assert not lock.exists()
    assert not list(tmp_path.glob(".vibecomfy-restore-*"))


def test_exact_pin_accepts_scheme_and_host_case_only(tmp_path, source):
    runner, _, default = source
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"
    live = _existing(root, runner)
    runner.git("-C", str(live), "config", "remote.origin.url", "HTTPS://EXAMPLE.TEST/Owner/Pack.git")
    runner.calls.clear()
    result = _restore(root, lock, default, runner)
    assert result.status == "refreshed"
    assert result.git_commit_sha == default
    assert not any(call[:2] == ["git", "clone"] or call[3:4] == ["fetch"] for call in runner.calls)
    assert not lock.exists()


def test_lock_write_failure_withdraws_published_candidate(tmp_path, source, monkeypatch):
    runner, pin, _ = source
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"

    def fail_lock(*args, **kwargs):
        raise OSError("recorded lock write failure")

    monkeypatch.setattr(install, "upsert_lockfile_entry", fail_lock)
    result = _restore(root, lock, pin, runner)
    assert result.status == "failed"
    assert "recorded lock write failure" in result.error
    assert not (root / "Pack").exists()
    assert not lock.exists()


def test_failed_dependency_install_withdraws_published_candidate(tmp_path):
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"
    runner = RecipeRunner()
    runner.fail_install = True
    result = _restore(root, lock, "a" * 40, runner, requirements_txt="deps/requirements.txt")
    assert result.status == "failed"
    assert "recorded install failure" in result.error
    assert not (root / "Pack").exists()
    assert not lock.exists()
    assert (root / install.INSTALL_STATE_DIR / "Pack.json").exists()
