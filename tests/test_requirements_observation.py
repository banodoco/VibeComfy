"""Requirements observations use actual files and Git without repairing targets."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

import pytest

from vibecomfy.requirements import _observe as observe


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


def git(directory: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={os.devnull}",
                           "-C", str(directory), *arguments], check=True, capture_output=True,
                          text=True, timeout=15, env=observe._git_environment()).stdout.strip()


@pytest.fixture
def checkout(tmp_path):
    path = tmp_path / "custom_nodes" / "Fixture.Pack"
    path.mkdir(parents=True)
    git(path, "init", "-q")
    git(path, "config", "user.email", "fixture@example.test")
    git(path, "config", "user.name", "Fixture")
    git(path, "remote", "add", "origin", "https://example.test/Fixture.Pack.git")
    (path / "node.py").write_text("# data-only fixture, never imported\n", encoding="utf-8")
    git(path, "add", "node.py")
    git(path, "commit", "-qm", "fixture source")
    return path, "https://example.test/Fixture.Pack.git", git(path, "rev-parse", "HEAD")


def test_target_copy_preserves_selected_fields_and_does_not_invent_subroots(tmp_path):
    root = tmp_path / "engine"
    target = {"placement_class": "local", "owner": "astrid", "root": str(root),
              "python": None, "facts": {"receipt": "exact-receipt"},
              "recipe": {"packages": ["a==1", "b==2"]}, "capacity_bytes": None}
    before = copy.deepcopy(target)
    normalized = observe.normalize_target(target)
    assert normalized == before
    assert not root.exists()
    assert all(key not in normalized for key in ("comfyui_root", "models_root", "custom_nodes_root"))
    normalized["recipe"]["packages"].reverse()
    assert target == before


def test_target_as_dict_and_explicit_null_roots_are_retained():
    class Selected:
        def as_dict(self):
            return {"placement_class": "attached", "root": None, "python": None,
                    "comfyui_root": None, "models_root": None, "custom_nodes_root": None}
    assert observe.normalize_target(Selected()) == Selected().as_dict()


def test_python_final_symlink_keeps_the_selected_environment(tmp_path):
    real_python = tmp_path / "system-python"
    real_python.write_bytes(b"not executed")
    environment = tmp_path / "venv" / "bin"
    environment.mkdir(parents=True)
    python = environment / "python"
    python.symlink_to(real_python)
    alias = tmp_path / "bin-alias"
    alias.symlink_to(environment, target_is_directory=True)
    normalized = observe.normalize_target({"placement_class": "local", "root": str(alias),
                                          "python": str(alias / "python")})
    assert normalized["root"] == str(environment)
    assert normalized["python"] == str(python)
    assert normalized["python"] != str(real_python)
    assert python.is_symlink()


@pytest.mark.parametrize("field", ["root", "python", "comfyui_root", "models_root", "custom_nodes_root"])
@pytest.mark.parametrize("value", ["relative", " /absolute", "/absolute\n", "", 123])
def test_target_refuses_invalid_explicit_paths(field, value):
    with pytest.raises(ValueError, match="absolute path"):
        observe.normalize_target({"placement_class": "local", field: value})


@pytest.mark.parametrize("target", [{}, {"placement_class": "managed"},
                                  {"placement_class": "local", "capacity": float("nan")}])
def test_target_needs_explicit_placement_and_finite_json(target):
    with pytest.raises(ValueError):
        observe.normalize_target(target)


def test_remote_paths_are_not_resolved_against_this_machine():
    target = {"placement_class": "runpod", "location": "remote", "root": "/remote/engine",
              "python": "/remote/engine/venv/bin/python", "models_root": None}
    assert observe.normalize_target(target) == target
    windows = {"placement_class": "attached", "location": "remote", "root": "C:\\ComfyUI"}
    assert observe.normalize_target(windows) == windows


def test_actual_model_bytes_match_or_conflict_without_writes(tmp_path):
    path = tmp_path / "model.bin"
    body = b"actual model fixture\0\xff"
    path.write_bytes(body)
    before = tree_bytes(tmp_path)
    first = observe.observe_model(str(path), digest(body), len(body))
    assert first == {"state": "present", "size_bytes": len(body), "sha256": digest(body)}
    assert observe.observe_model(str(path), None, None) == first
    assert observe.observe_model(str(path), "0" * 64, len(body))["reason"] == "hash_mismatch"
    assert observe.observe_model(str(path), digest(body), len(body) + 1)["reason"] == "size_mismatch"
    assert tree_bytes(tmp_path) == before


def test_missing_unknown_and_zero_byte_models_are_distinct(tmp_path):
    assert observe.observe_model(str(tmp_path / "absent"), None, None)["state"] == "missing"
    assert observe.observe_model(None, None, None)["state"] == "unknown"
    assert observe.observe_model(str(tmp_path / "remote"), None, None, local=False)["state"] == "unknown"
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    assert observe.observe_model(str(empty), digest(b""), 0) == {
        "state": "present", "size_bytes": 0, "sha256": digest(b"")}


def test_model_permission_failure_is_unknown_not_missing(tmp_path, monkeypatch):
    path = tmp_path / "unreadable.bin"
    path.write_bytes(b"unchanged")
    original = os.open
    def denied(file, *args, **kwargs):
        if Path(file) == path:
            raise PermissionError("fixture denied")
        return original(file, *args, **kwargs)
    monkeypatch.setattr(observe.os, "open", denied)
    result = observe.observe_model(str(path), None, None)
    assert result["state"] == "unknown" and result["sha256"] is None
    assert path.read_bytes() == b"unchanged"


def test_model_final_symlink_is_not_read(tmp_path, monkeypatch):
    actual = tmp_path / "outside.bin"
    actual.write_bytes(b"do not read through alias")
    alias = tmp_path / "model.bin"
    alias.symlink_to(actual)
    monkeypatch.setattr(observe, "_read_file", lambda *a, **k: pytest.fail("read a symlink"))
    assert observe.observe_model(str(alias), None, None)["state"] == "conflict"


def test_model_hashing_has_a_bounded_timeout(tmp_path, monkeypatch):
    path = tmp_path / "model.bin"
    path.write_bytes(b"untouched")
    monkeypatch.setattr(observe, "_TIMEOUT_SECONDS", 0)
    assert observe.observe_model(str(path), None, None)["state"] == "timeout"
    assert path.read_bytes() == b"untouched"


def test_actual_git_checkout_observation_is_stable_without_index_writes(checkout):
    path, repo, commit = checkout
    before = tree_bytes(path.parent)
    index_mtime = (path / ".git" / "index").stat().st_mtime_ns
    first = observe.observe_node(str(path), repo=repo, commit=commit)
    assert first["state"] == "present"
    assert (first["repo"], first["commit"], first["dirty"]) == (repo, commit, False)
    assert first["changes"] == [] and first["sentinel"]["state"] == "absent"
    assert observe.observe_node(str(path), repo=repo, commit=commit) == first
    assert tree_bytes(path.parent) == before
    assert (path / ".git" / "index").stat().st_mtime_ns == index_mtime


def test_actual_dirty_or_different_source_checkout_is_a_conflict(checkout):
    path, repo, commit = checkout
    assert observe.observe_node(str(path), repo=repo, commit="0" * 40)["reason"] == "commit_mismatch"
    git(path, "remote", "set-url", "origin", "https://example.test/other.git")
    assert observe.observe_node(str(path), repo=repo, commit=commit)["reason"] == "repository_mismatch"
    git(path, "remote", "set-url", "origin", repo)
    (path / "node.py").write_text("# changed local work\n", encoding="utf-8")
    result = observe.observe_node(str(path), repo=repo, commit=commit)
    assert result["reason"] == "dirty_checkout" and result["dirty"] is True
    assert result["changes"] == [" M node.py"]


@pytest.mark.parametrize("payload", [b"{malformed", json.dumps({"complete": False, "pid": 999999999,
    "hostname": "old-host", "timestamp": 0, "phase": "clone"}).encode(),
    json.dumps({"complete": True}).encode()])
def test_stale_malformed_and_complete_sentinels_are_retained(checkout, payload, monkeypatch):
    path, repo, commit = checkout
    marker = path.parent / ".vibecomfy-install-state" / "Fixture.Pack.json"
    marker.parent.mkdir()
    marker.write_bytes(payload)
    before = tree_bytes(path.parent)
    monkeypatch.setattr(observe.subprocess, "run", lambda *a, **k: pytest.fail("sentinel reached Git"))
    result = observe.observe_node(str(path), repo=repo, commit=commit)
    assert result["state"] == "incomplete"
    assert result["sentinel"]["state"] == "present"
    assert result["sentinel"]["sha256"] == digest(payload)
    assert "timestamp" not in result["sentinel"]
    assert tree_bytes(path.parent) == before


def test_node_absence_and_permission_failure_are_distinct(tmp_path, monkeypatch):
    path = tmp_path / "pack"
    assert observe.observe_node(str(path), repo="https://example.test/pack", commit="a" * 40)["state"] == "missing"
    path.mkdir()
    original = Path.lstat
    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError("fixture denied")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "lstat", denied)
    assert observe.observe_node(str(path), repo="https://example.test/pack", commit="a" * 40)["state"] == "unknown"


def test_node_git_timeout_is_explicit_and_never_repaired(checkout, monkeypatch):
    path, repo, commit = checkout
    before = tree_bytes(path.parent)
    def timeout(args, **kwargs):
        assert "--no-optional-locks" in args and kwargs["timeout"] <= 15
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])
    monkeypatch.setattr(observe.subprocess, "run", timeout)
    assert observe.observe_node(str(path), repo=repo, commit=commit)["state"] == "timeout"
    assert tree_bytes(path.parent) == before


def test_ambient_git_worktree_cannot_redirect_observation(checkout, tmp_path, monkeypatch):
    path, repo, commit = checkout
    other = tmp_path / "unrelated"
    other.mkdir()
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_DIR", str(other))
    assert observe.observe_node(str(path), repo=repo, commit=commit)["state"] == "present"


@pytest.mark.parametrize("filter_kind,included", [("clean", False), ("process", True)])
def test_configured_git_filters_are_never_executed(checkout, tmp_path, filter_kind, included):
    path, repo, _ = checkout
    # Track the attribute before configuring a filter so fixture preparation
    # cannot execute it either. Only status on the changed file could run it.
    (path / ".gitattributes").write_text("node.py filter=fixture\n", encoding="utf-8")
    git(path, "add", ".gitattributes")
    git(path, "commit", "-qm", "declare tracked filter attribute")
    commit = git(path, "rev-parse", "HEAD")
    marker = tmp_path / "FILTER_EXECUTED"
    command = f"printf invoked > {shlex.quote(str(marker))}; " + ("cat" if filter_kind == "clean" else "exit 1")
    if included:
        config = path / ".git" / "filters.conf"
        git(path, "config", "--file", str(config), f"filter.fixture.{filter_kind}", command)
        git(path, "config", "include.path", "filters.conf")
    else:
        git(path, "config", f"filter.fixture.{filter_kind}", command)
    tracked = path / "node.py"
    previous = tracked.stat()
    body = tracked.read_bytes()
    tracked.write_bytes(b"!" + body[1:])
    os.utime(tracked, ns=(previous.st_atime_ns, previous.st_mtime_ns + 2_000_000_000))
    before = tree_bytes(tmp_path)
    result = observe.observe_node(str(path), repo=repo, commit=commit)
    assert result["state"] == "unknown" and result["reason"] == "git_filters_configured"
    assert result["filters_configured"] is True and len(result["filter_config_sha256"]) == 64
    assert result["dirty"] is None
    assert not marker.exists()
    assert tree_bytes(tmp_path) == before


def test_repository_worktree_redirection_is_refused(checkout, tmp_path):
    path, repo, commit = checkout
    other = tmp_path / "other-worktree"
    other.mkdir()
    (other / "node.py").write_text("# unrelated local work\n", encoding="utf-8")
    git(path, "config", "core.worktree", str(other))
    assert git(path, "rev-parse", "--show-toplevel") == str(other.resolve())
    before = tree_bytes(tmp_path)
    result = observe.observe_node(str(path), repo=repo, commit=commit)
    assert result["state"] == "unknown" and result["reason"] == "worktree_redirected"
    assert result["worktree"] == str(other.resolve()) and result["dirty"] is None
    assert tree_bytes(tmp_path) == before
