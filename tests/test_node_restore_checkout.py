"""F1 RS1.2/RS1.4: exercise real Git, with every non-file protocol forbidden."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.fixtures.node_recipe_runner import RecipeRunner
from tests.fixtures.node_restore_checkout import assert_staged_restore
from vibecomfy.node_approvals import approval_record
from vibecomfy.node_packs import LockEntry, install_pack, read_lockfile, restore_pack
from vibecomfy.node_packs import _install as install

APPROVED = "https://example.test/Owner/Pack.git"
OTHER_CASE = "https://example.test/Owner/pack.git"


class OfflineGit:
    def __init__(self, upstream):
        self.upstream = upstream
        self.calls = []
        self.head_reads = []

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
        result = subprocess.run([*prefix, *call[1:]], **kwargs)
        if call[:2] == ["git", "-C"] and call[3:] == ["rev-parse", "HEAD"]:
            self.head_reads.append((call, result.stdout.strip()))
        return result

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
            assert live.exists() is existing
            if existing:
                assert (live / "nodes.py").read_text() == "UNAPPROVED_DEFAULT = True\n"
            assert not staged.is_relative_to(root)
            assert not (staged / "nodes.py").exists(), "default branch must never be checked out"
        elif call[:2] == ["git", "-C"] and Path(call[2]) in staged_paths:
            assert live.exists() is existing, "staged Git operations must precede publication"
            if existing:
                assert (live / "nodes.py").read_text() == "UNAPPROVED_DEFAULT = True\n"
            if call[3] == "rev-parse":
                assert result.stdout.strip() == pin
            if call[3] == "checkout":
                assert (Path(call[2]) / "nodes.py").read_text() == "APPROVED = True\n"
        return result

    result = _restore(root, lock, pin, observe)
    assert result.status == ("refreshed" if existing else "installed")
    assert result.git_commit_sha == pin
    assert_staged_restore(runner, root, "Pack", APPROVED, pin)
    assert [call for call in runner.calls if call[3:4] == ["fetch"]] == [
        ["git", "-C", str(staged_paths[0]), "fetch", "--", APPROVED, pin]
    ]
    assert runner.git("-C", str(live), "rev-parse", "HEAD") == pin != default
    assert runner.git("-C", str(live), "config", "--get", "remote.origin.url") == APPROVED
    assert (live / "nodes.py").read_text() == "APPROVED = True\n"
    assert read_lockfile(lock) == [LockEntry("Pack", pin, APPROVED)]
    assert not list(tmp_path.glob(".vibecomfy-restore-*"))


def test_failed_changed_pin_keeps_previous_checkout_live_and_untouched(tmp_path, source):
    runner, _, default = source
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"
    live = _existing(root, runner)
    original = {p.relative_to(live): p.read_bytes() for p in live.rglob("*") if p.is_file()}
    result = _restore(root, lock, "0" * 40, runner)
    assert result.status == "failed"
    assert live.is_dir()
    assert not lock.exists()
    assert runner.git("-C", str(live), "rev-parse", "HEAD") == default
    assert original == {p.relative_to(live): p.read_bytes() for p in live.rglob("*") if p.is_file()}
    assert not list(tmp_path.glob(".vibecomfy-restore-*"))


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


@pytest.mark.parametrize("origin", [
    "HTTPS://EXAMPLE.TEST/Owner/Pack.git",
    "git@EXAMPLE.TEST:Owner/Pack.git/",
    "https://example.test/Owner/Pack/",
], ids=["scheme-host-case", "ssh", "suffix-slash"])
def test_exact_pin_accepts_scheme_and_host_case_only(tmp_path, source, origin):
    runner, _, default = source
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"
    live = _existing(root, runner)
    runner.git("-C", str(live), "config", "remote.origin.url", origin)
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


def test_ssh_checkout_with_different_path_case_is_refused(tmp_path, source):
    runner, pin, default = source
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"
    live = _existing(root, runner)
    runner.git("-C", str(live), "config", "remote.origin.url", "git@example.test:Owner/pack.git")
    runner.calls.clear()
    result = _restore(root, lock, pin, runner)
    assert result.status == "failed" and "repository differs" in result.error
    assert runner.calls == [["git", "-C", str(live), "config", "--get", "remote.origin.url"]]
    assert runner.git("-C", str(live), "rev-parse", "HEAD") == default
    assert not lock.exists()


def test_tag_only_pin_fetch_uses_approved_url_and_verifies_head(tmp_path, source):
    runner, _, default = source
    upstream = str(runner.upstream)
    # Make the requested commit reachable from a tag but no branch.
    runner.git("-C", upstream, "checkout", "--orphan", "tag-only-branch")
    (runner.upstream / "nodes.py").write_text("TAG_ONLY = True\n", encoding="utf-8")
    runner.git("-C", upstream, "add", "nodes.py")
    runner.git("-C", upstream, "commit", "-m", "tag only")
    pin = runner.git("-C", upstream, "rev-parse", "HEAD")
    runner.git("-C", upstream, "tag", "only-tag", pin)
    runner.git("-C", upstream, "checkout", "main")
    runner.git("-C", upstream, "branch", "-D", "tag-only-branch")
    assert runner.git("-C", upstream, "branch", "--contains", pin) == ""
    runner.calls.clear()
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"
    live = root / "Pack"
    attempts = []

    def server_refuses_sha_want(args, **kwargs):
        call = list(args)
        if call[:2] == ["git", "clone"]:
            # Suppress the initial tag transfer so the fallback has to
            # retrieve an object that is genuinely absent from the clone.
            result = runner([*call[:3], "--no-tags", *call[3:]], **kwargs)
            with pytest.raises(subprocess.CalledProcessError):
                runner.git("-C", call[-1], "cat-file", "-e", f"{pin}^{{commit}}")
            return result
        if call[3:4] == ["fetch"]:
            attempts.append(call)
            assert call[4:6] == ["--", APPROVED]
            assert not live.exists()
            if call[-1] == pin:
                raise subprocess.CalledProcessError(1, call, stderr="server refuses SHA want")
        return runner(call, **kwargs)

    result = _restore(root, lock, pin, server_refuses_sha_want)
    assert result.status == "installed"
    assert result.git_commit_sha == pin != default
    [clone] = [call for call in runner.calls if call[:2] == ["git", "clone"]]
    staged = Path(clone[-1])
    assert not staged.is_relative_to(root)
    assert attempts == [
        ["git", "-C", str(staged), "fetch", "--", APPROVED, pin],
        ["git", "-C", str(staged), "fetch", "--", APPROVED, "+refs/tags/*:refs/tags/*"],
    ]
    assert (["git", "-C", str(staged), "rev-parse", "HEAD"], pin) in runner.head_reads
    assert runner.git("-C", str(live), "rev-parse", "HEAD") == pin
    assert (live / "nodes.py").read_text() == "TAG_ONLY = True\n"
    assert read_lockfile(lock) == [LockEntry("Pack", pin, APPROVED)]


@pytest.mark.parametrize("pinned", [False, True], ids=["explicit-default", "explicit-pin"])
def test_explicit_install_uses_same_verified_staging_path(tmp_path, source, pinned):
    runner, pin, default = source
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"
    live = root / "Pack"
    stage = []

    def observe(args, **kwargs):
        call = list(args)
        result = runner(call, **kwargs)
        if call[:2] == ["git", "clone"]:
            stage.append(Path(call[-1]))
            assert not live.exists()
            assert not stage[0].is_relative_to(root)
            assert not (stage[0] / "nodes.py").exists()
        elif stage and call[:2] == ["git", "-C"] and Path(call[2]) == stage[0]:
            assert not live.exists()
        return result

    result = install_pack(repo=APPROVED, install_root=root, lockfile_path=lock, runner=observe,
                          cm_cli_resolver=lambda *_: None,
                          checkout_ref=pin if pinned else None, expected_commit=pin if pinned else None)
    assert result.status == "installed"
    expected = pin if pinned else default
    assert result.git_commit_sha == expected
    assert_staged_restore(runner, root, "Pack", APPROVED, expected, fetch=pinned)
    assert runner.git("-C", str(live), "rev-parse", "HEAD") == expected
    assert read_lockfile(lock)[0].git_commit_sha == expected


def test_explicit_missing_pin_never_publishes_default_branch(tmp_path, source):
    runner, _, _ = source
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"
    result = install_pack(repo=APPROVED, install_root=root, lockfile_path=lock, runner=runner,
                          cm_cli_resolver=lambda *_: ["cm-cli"],
                          checkout_ref="0" * 40, expected_commit="0" * 40)
    assert result.status == "failed"
    assert not (root / "Pack").exists()
    assert not lock.exists()
    assert not list(tmp_path.glob(".vibecomfy-restore-*"))


def test_failed_replacement_lock_write_rolls_back_previous_checkout(tmp_path, source, monkeypatch):
    runner, pin, default = source
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"
    live = _existing(root, runner)
    original = (live / "nodes.py").read_bytes()

    def fail_lock(*args, **kwargs):
        raise OSError("recorded lock write failure")

    monkeypatch.setattr(install, "upsert_lockfile_entry", fail_lock)
    result = _restore(root, lock, pin, runner)
    assert result.status == "failed"
    assert "recorded lock write failure" in result.error
    assert runner.git("-C", str(live), "rev-parse", "HEAD") == default
    assert (live / "nodes.py").read_bytes() == original
    assert not lock.exists()
    assert not list(tmp_path.glob(".vibecomfy-restore-*"))


@pytest.fixture
def ignored_checkout(tmp_path, source):
    runner, _, _ = source
    upstream = runner.upstream
    (upstream / ".gitignore").write_text("cache/\nconfig.local.json\n", encoding="utf-8")
    runner.git("-C", str(upstream), "add", ".gitignore")
    runner.git("-C", str(upstream), "commit", "-m", "ignore local user data")
    old = runner.git("-C", str(upstream), "rev-parse", "HEAD")
    (upstream / "nodes.py").write_text("NEW_PIN = True\n", encoding="utf-8")
    runner.git("-C", str(upstream), "add", "nodes.py")
    runner.git("-C", str(upstream), "commit", "-m", "new pin")
    new = runner.git("-C", str(upstream), "rev-parse", "HEAD")
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"
    assert _restore(root, lock, old, runner).status == "installed"
    live = root / "Pack"
    (live / "cache").mkdir()
    (live / "cache/model.bin").write_bytes(b"\x00\xfflocal model")
    (live / "config.local.json").write_bytes(b'{"local":true}\n')
    assert runner.git("-C", str(live), "status", "--porcelain") == ""
    assert "!! cache/" in runner.git("-C", str(live), "status", "--porcelain", "--ignored")
    runner.calls.clear()
    return runner, root, lock, live, old, new


def _assert_ignored_data_live(runner, root, lock, live, old):
    assert runner.git("-C", str(live), "rev-parse", "HEAD") == old
    assert (live / "cache/model.bin").read_bytes() == b"\x00\xfflocal model"
    assert (live / "config.local.json").read_bytes() == b'{"local":true}\n'
    assert read_lockfile(lock) == [LockEntry("Pack", old, APPROVED)]
    assert not list(root.parent.glob(".vibecomfy-restore-*"))


def test_rs1b_3_pin_change_refuses_without_losing_ignored_data(ignored_checkout):
    runner, root, lock, live, old, new = ignored_checkout
    result = _restore(root, lock, new, runner)
    assert result.status == "skipped_dirty"
    assert result.git_commit_sha == old
    assert "cache/model.bin" in result.error
    assert "config.local.json" in result.error
    assert not any(call[:2] == ["git", "clone"] for call in runner.calls)
    _assert_ignored_data_live(runner, root, lock, live, old)


def test_rs1b_3_explicit_force_cannot_discard_ignored_data(ignored_checkout):
    runner, root, lock, live, old, new = ignored_checkout
    result = install_pack(repo=APPROVED, install_root=root, lockfile_path=lock,
                          force=True, runner=runner, checkout_ref=new, expected_commit=new)
    assert result.status == "skipped_dirty"
    assert result.git_commit_sha == old
    assert "cache/model.bin" in result.error
    assert "config.local.json" in result.error
    _assert_ignored_data_live(runner, root, lock, live, old)


def test_rs1b_3_same_pin_restore_keeps_ignored_data(ignored_checkout):
    runner, root, lock, live, old, _ = ignored_checkout
    result = _restore(root, lock, old, runner)
    assert result.status == "refreshed"
    assert result.git_commit_sha == old
    _assert_ignored_data_live(runner, root, lock, live, old)


def test_rs1b_3_failed_restore_keeps_ignored_data_live(ignored_checkout):
    runner, root, lock, live, old, _ = ignored_checkout
    result = _restore(root, lock, "0" * 40, runner)
    assert result.status == "skipped_dirty"
    assert "cache/model.bin" in result.error
    assert "config.local.json" in result.error
    _assert_ignored_data_live(runner, root, lock, live, old)


def test_rs1b_3_ignored_data_created_during_staging_refuses_swap(ignored_checkout):
    runner, root, lock, live, old, new = ignored_checkout
    # Start clean, then simulate the running pack writing its data while the
    # verified replacement is being cloned outside the live directory.
    (live / "cache/model.bin").unlink()
    (live / "cache").rmdir()
    (live / "config.local.json").unlink()

    def write_during_clone(args, **kwargs):
        result = runner(args, **kwargs)
        if list(args)[:2] == ["git", "clone"]:
            (live / "cache").mkdir()
            (live / "cache/model.bin").write_bytes(b"\x00\xfflocal model")
            (live / "config.local.json").write_bytes(b'{"local":true}\n')
        return result

    result = _restore(root, lock, new, write_during_clone)
    assert result.status == "skipped_dirty"
    assert result.git_commit_sha == old
    assert "cache/model.bin" in result.error
    assert "config.local.json" in result.error
    _assert_ignored_data_live(runner, root, lock, live, old)


def test_rs1b_3_refused_pin_change_can_retry_after_moving_data(ignored_checkout):
    runner, root, lock, live, old, new = ignored_checkout
    assert _restore(root, lock, new, runner).status == "skipped_dirty"
    saved = root.parent / "saved-user-data"
    saved.mkdir()
    (live / "cache").rename(saved / "cache")
    (live / "config.local.json").rename(saved / "config.local.json")

    result = _restore(root, lock, new, runner)
    assert result.status == "refreshed"
    assert runner.git("-C", str(live), "rev-parse", "HEAD") == new != old
    assert read_lockfile(lock) == [LockEntry("Pack", new, APPROVED)]
    assert (saved / "cache/model.bin").read_bytes() == b"\x00\xfflocal model"
    assert (saved / "config.local.json").read_bytes() == b'{"local":true}\n'
    assert not list(root.parent.glob(".vibecomfy-restore-*"))


def test_rs1b_3_unreadable_ignored_status_refuses_replacement(ignored_checkout):
    runner, root, lock, live, old, new = ignored_checkout

    def fail_ignored_status(args, **kwargs):
        if "--ignored" in args:
            raise subprocess.CalledProcessError(1, args, stderr="cannot inspect ignored files")
        return runner(args, **kwargs)

    result = _restore(root, lock, new, fail_ignored_status)
    assert result.status == "failed"
    assert "failed to inspect" in result.error
    _assert_ignored_data_live(runner, root, lock, live, old)


def test_rs1b_3_late_write_to_previous_tree_keeps_recoverable_backup(ignored_checkout, monkeypatch, caplog):
    runner, root, lock, live, old, new = ignored_checkout
    (live / "cache/model.bin").unlink()
    (live / "cache").rmdir()
    (live / "config.local.json").unlink()
    write_lock = install.upsert_lockfile_entry

    def write_during_finalize(*args, **kwargs):
        # Simulate a process with an existing handle into the displaced tree.
        [previous] = root.parent.glob(".vibecomfy-restore-*/previous")
        (previous / "cache").mkdir()
        (previous / "cache/model.bin").write_bytes(b"\x00\xfflocal model")
        (previous / "config.local.json").write_bytes(b'{"local":true}\n')
        return write_lock(*args, **kwargs)

    monkeypatch.setattr(install, "upsert_lockfile_entry", write_during_finalize)
    result = _restore(root, lock, new, runner)
    assert result.status == "refreshed"
    assert runner.git("-C", str(live), "rev-parse", "HEAD") == new
    assert read_lockfile(lock) == [LockEntry("Pack", new, APPROVED)]
    [previous] = root.parent.glob(".vibecomfy-restore-*/previous")
    assert not previous.is_relative_to(root)
    assert runner.git("-C", str(previous), "rev-parse", "HEAD") == old
    assert (previous / "cache/model.bin").read_bytes() == b"\x00\xfflocal model"
    assert (previous / "config.local.json").read_bytes() == b'{"local":true}\n'
    assert str(previous) in caplog.text


@pytest.fixture
def bytecode_checkout(tmp_path, source):
    runner, _, _ = source
    upstream = runner.upstream
    (upstream / ".gitignore").write_text("__pycache__/\n*.pyc\n*.pyo\ncache/\n", encoding="utf-8")
    runner.git("-C", str(upstream), "add", ".gitignore")
    runner.git("-C", str(upstream), "commit", "-m", "ignore Python bytecode")
    old = runner.git("-C", str(upstream), "rev-parse", "HEAD")
    (upstream / "nodes.py").write_text("NEW_PIN = True\n", encoding="utf-8")
    runner.git("-C", str(upstream), "add", "nodes.py")
    runner.git("-C", str(upstream), "commit", "-m", "new pin")
    new = runner.git("-C", str(upstream), "rev-parse", "HEAD")
    root, lock = tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock"
    assert _restore(root, lock, old, runner).status == "installed"
    return runner, root, lock, root / "Pack", old, new


def _write_bytecode(live):
    for relative in ("__pycache__/x.cpython-312.pyc",
                     "nested folder/__pycache__/x.cpython-312.pyc",
                     "loose.pyc", "loose.pyo"):
        path = live / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"regenerable bytecode")


@pytest.mark.parametrize("during_staging", [False, True], ids=["existing", "during-staging"])
def test_rs1b_3_bytecode_only_allows_pin_update(bytecode_checkout, during_staging):
    runner, root, lock, live, old, new = bytecode_checkout

    def write_during_clone(args, **kwargs):
        result = runner(args, **kwargs)
        if list(args)[:2] == ["git", "clone"]:
            _write_bytecode(live)
        return result

    if not during_staging:
        _write_bytecode(live)
        assert runner.git("-C", str(live), "status", "--porcelain") == ""
        assert "!! __pycache__/" in runner.git("-C", str(live), "status", "--porcelain", "--ignored")
    result = _restore(root, lock, new, write_during_clone if during_staging else runner)
    assert result.status == "refreshed"
    assert result.git_commit_sha == new != old
    assert runner.git("-C", str(live), "rev-parse", "HEAD") == new
    assert read_lockfile(lock) == [LockEntry("Pack", new, APPROVED)]
    assert result.error is None
    assert not list(root.parent.glob(".vibecomfy-restore-*"))


def test_rs1b_3_bytecode_mixed_with_model_names_only_user_data(bytecode_checkout):
    runner, root, lock, live, old, new = bytecode_checkout
    _write_bytecode(live)
    (live / "cache").mkdir()
    (live / "cache/model.bin").write_bytes(b"local model")
    result = _restore(root, lock, new, runner)
    assert result.status == "skipped_dirty"
    assert result.git_commit_sha == old
    assert "cache/model.bin" in result.error
    assert "__pycache__" not in result.error
    assert "loose.pyc" not in result.error
    assert "loose.pyo" not in result.error
    assert (live / "cache/model.bin").read_bytes() == b"local model"
    assert (live / "__pycache__/x.cpython-312.pyc").read_bytes() == b"regenerable bytecode"
    assert runner.git("-C", str(live), "rev-parse", "HEAD") == old
    assert read_lockfile(lock) == [LockEntry("Pack", old, APPROVED)]
    assert not list(root.parent.glob(".vibecomfy-restore-*"))


def test_rs1b_3_retained_backup_path_visible_in_result(bytecode_checkout, monkeypatch):
    runner, root, lock, live, old, new = bytecode_checkout
    _write_bytecode(live)
    write_lock = install.upsert_lockfile_entry

    def write_during_finalize(*args, **kwargs):
        [previous] = root.parent.glob(".vibecomfy-restore-*/previous")
        (previous / "cache").mkdir()
        (previous / "cache/model.bin").write_bytes(b"late model")
        return write_lock(*args, **kwargs)

    monkeypatch.setattr(install, "upsert_lockfile_entry", write_during_finalize)
    result = _restore(root, lock, new, runner)
    assert result.status == "refreshed"
    assert result.git_commit_sha == new
    [previous] = root.parent.glob(".vibecomfy-restore-*/previous")
    assert str(previous) in result.error
    assert "not" in result.error and "automatically" in result.error
    assert (previous / "cache/model.bin").read_bytes() == b"late model"
    assert runner.git("-C", str(previous), "rev-parse", "HEAD") == old
    assert runner.git("-C", str(live), "rev-parse", "HEAD") == new
    assert read_lockfile(lock) == [LockEntry("Pack", new, APPROVED)]

