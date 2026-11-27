"""Read-only selected-target observations for the exact requirements plan.

These functions neither repair installer markers nor execute the selected
interpreter. An absent path is reported only after an actual absence read.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path, PureWindowsPath
from typing import Any


_PATH_FIELDS = ("root", "python", "comfyui_root", "models_root", "custom_nodes_root")
_TIMEOUT_SECONDS = 15.0
_READ_CHUNK = 1024 * 1024
_SENTINEL_LIMIT = 64 * 1024


def _json_value(value: Any) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _json_value(item)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _json_value(item)
        return
    raise ValueError("target must contain only finite JSON values")


def normalize_target(target: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Copy the selected identity; never discover paths or invent subroots.

    A venv's final Python symlink is intentionally retained. Remote paths are
    validated as absolute spellings without resolving them on this machine.
    Ownership and placement are supplied by the selecting authority, not
    inferred from an endpoint's hostname.
    """
    raw = target.as_dict() if hasattr(target, "as_dict") else target
    if not isinstance(raw, Mapping):
        raise ValueError("target must be a selected target object")
    result = copy.deepcopy(dict(raw))
    if result.get("placement_class") not in {"local", "attached", "runpod"}:
        raise ValueError("target requires an explicit resolved placement_class")
    local = result.get("location", "local") == "local" and result["placement_class"] != "runpod"
    for field in _PATH_FIELDS:
        if field not in result or result[field] is None:
            continue
        value = os.fspath(result[field]) if isinstance(result[field], os.PathLike) else result[field]
        if (not isinstance(value, str) or not value or value != value.strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError(f"target {field} must be a nonempty absolute path or null")
        path = Path(value).expanduser() if local else Path(value)
        if not path.is_absolute() and not (not local and PureWindowsPath(value).is_absolute()):
            raise ValueError(f"target {field} must be an absolute path")
        try:
            result[field] = (str(path.parent.resolve() / path.name) if field == "python"
                             else str(path.resolve())) if local else value
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"target {field} cannot be resolved") from exc
    _json_value(result)
    return result


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino, left.st_size, left.st_mtime_ns) == (
        right.st_dev, right.st_ino, right.st_size, right.st_mtime_ns)


def _read_file(path: Path, initial: os.stat_result, *, limit: int | None = None) -> tuple[str, bytes | None]:
    """Hash a regular file without following a replaced final symlink."""
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or not _same_file(initial, opened):
            raise ValueError("changed_during_observation")
        digest = hashlib.sha256()
        chunks: list[bytes] | None = [] if limit is not None else None
        total = 0
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("observation_timeout")
            chunk = os.read(fd, _READ_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
            if chunks is not None:
                if total <= limit:
                    chunks.append(chunk)
                else:
                    chunks = None
        if not _same_file(initial, os.fstat(fd)) or not _same_file(initial, path.lstat()):
            raise ValueError("changed_during_observation")
        return digest.hexdigest(), b"".join(chunks) if chunks is not None else None
    finally:
        os.close(fd)


def observe_model(destination: str | None, expected_sha256: str | None, size_bytes: int | None,
                  *, local: bool = True) -> dict[str, Any]:
    """Read actual model bytes, leaving unknown observations explicit.

    The caller authorizes the destination against the selected model root.
    A final symlink is refused, including if introduced during the read.
    """
    if expected_sha256 is not None and (not isinstance(expected_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None):
        raise ValueError("expected model sha256 must be 64 lowercase hex or null")
    if size_bytes is not None and (type(size_bytes) is not int or size_bytes < 0):
        raise ValueError("expected model size_bytes must be nonnegative or null")
    result: dict[str, Any] = {"state": "unknown", "size_bytes": None, "sha256": None}
    if destination is None or not local:
        return {**result, "reason": "destination_unknown" if destination is None else "remote_not_observed"}
    path = Path(destination)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {**result, "state": "missing"}
    except OSError:
        return {**result, "reason": "stat_failed"}
    if not stat.S_ISREG(info.st_mode):
        return {**result, "state": "conflict", "reason": "not_regular_file"}
    result["size_bytes"] = info.st_size
    try:
        result["sha256"], _ = _read_file(path, info)
    except TimeoutError:
        return {**result, "state": "timeout", "reason": "observation_timeout"}
    except (OSError, ValueError):
        return {**result, "reason": "read_failed_or_changed"}
    if size_bytes is not None and info.st_size != size_bytes:
        return {**result, "state": "conflict", "reason": "size_mismatch"}
    if expected_sha256 is not None and result["sha256"] != expected_sha256:
        return {**result, "state": "conflict", "reason": "hash_mismatch"}
    return {**result, "state": "present"}


def _sentinel(destination: Path) -> dict[str, Any]:
    from vibecomfy.node_packs._install import INSTALL_STATE_DIR, _safe_pack_slug

    path = destination.parent / INSTALL_STATE_DIR / f"{_safe_pack_slug(destination.name)}.json"
    result: dict[str, Any] = {"state": "unknown", "sha256": None, "size_bytes": None}
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {**result, "state": "absent"}
    except OSError:
        return {**result, "reason": "stat_failed"}
    result.update(state="present", size_bytes=info.st_size)
    if not stat.S_ISREG(info.st_mode):
        return {**result, "valid": False, "reason": "not_regular_file"}
    try:
        result["sha256"], content = _read_file(path, info, limit=_SENTINEL_LIMIT)
    except TimeoutError:
        return {**result, "reason": "observation_timeout"}
    except (OSError, ValueError):
        return {**result, "reason": "read_failed_or_changed"}
    if content is None:
        return {**result, "valid": False, "reason": "sentinel_too_large"}
    try:
        payload = json.loads(content)
        _json_value(payload)
        if not isinstance(payload, dict) or payload.get("complete") is not False:
            raise ValueError("invalid sentinel")
    except (ValueError, UnicodeError):
        return {**result, "valid": False, "reason": "malformed"}
    # The exact bytes are bound above, including owner metadata. Do not add a
    # current-time interpretation or an expiry that changes merely with time.
    result["valid"] = True
    for key in ("name", "repo_url", "git_commit_sha", "phase", "complete"):
        if key in payload:
            result[key] = copy.deepcopy(payload[key])
    return result


def _git_environment() -> dict[str, str]:
    # Ambient Git redirection must not select another checkout/index or add
    # configuration. These commands use only the explicit selected checkout.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_GLOBAL=os.devnull)
    return env


def observe_node(destination: str | None, *, repo: str | None, commit: str | None,
                 local: bool = True) -> dict[str, Any]:
    """Observe the selected checkout and sentinel without repairing either."""
    result: dict[str, Any] = {"state": "unknown", "repo": None, "commit": None, "dirty": None,
                              "sentinel": {"state": "unknown", "sha256": None, "size_bytes": None}}
    if destination is None or not local:
        return {**result, "reason": "destination_unknown" if destination is None else "remote_not_observed"}
    path = Path(destination)
    result["sentinel"] = _sentinel(path)
    if result["sentinel"]["state"] == "present":
        return {**result, "state": "incomplete", "reason": "install_sentinel_present"}
    if result["sentinel"]["state"] != "absent":
        return {**result, "reason": "sentinel_unknown"}
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {**result, "state": "missing"}
    except OSError:
        return {**result, "reason": "stat_failed"}
    if not stat.S_ISDIR(info.st_mode):
        return {**result, "state": "conflict", "reason": "not_plain_directory"}
    try:
        git_info = (path / ".git").lstat()
    except FileNotFoundError:
        return {**result, "state": "conflict", "reason": "not_git_checkout"}
    except OSError:
        return {**result, "reason": "git_metadata_unreadable"}
    if not stat.S_ISDIR(git_info.st_mode):
        return {**result, "state": "conflict", "reason": "not_plain_git_checkout"}
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    prefix = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
              "-c", "core.untrackedCache=false", "-c", f"core.hooksPath={os.devnull}",
              "-c", "status.submoduleSummary=false", "-C", str(path)]
    operations = (
        ("worktree", ["rev-parse", "--show-toplevel"]),
        ("filters", ["config", "--includes", "--get-regexp", r"^filter\..*\.(clean|process)$"]),
        ("repo", ["config", "--get", "remote.origin.url"]),
        ("commit", ["rev-parse", "HEAD"]),
        ("index_entries", ["ls-files", "--stage", "-z"]),
        ("head_entries", ["ls-tree", "-r", "-z", "HEAD"]),
        # Never enter a child's independently configured repository. The
        # gates above refuse gitlinks in either the index or HEAD; ignoring
        # recursion here also prevents a newly staged child from running code.
        ("changes", ["status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=all", "-z"]),
    )
    for field, arguments in operations:
        try:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise subprocess.TimeoutExpired(prefix, _TIMEOUT_SECONDS)
            completed = subprocess.run([*prefix, *arguments], capture_output=True, text=True,
                                       timeout=timeout, check=False, env=_git_environment())
        except subprocess.TimeoutExpired:
            return {**result, "state": "timeout", "reason": "git_timeout", "operation": field}
        except (OSError, UnicodeError):
            return {**result, "reason": "git_unavailable", "operation": field}
        if field == "filters" and completed.returncode == 1 and not completed.stdout and not completed.stderr:
            # Git config uses exit 1 for a successful lookup with no matching
            # keys. A failed/unavailable inspection cannot clear this gate.
            result["filters_configured"] = False
            continue
        if completed.returncode != 0:
            return {**result, "reason": "git_read_failed", "operation": field,
                    "exit_code": completed.returncode}
        if field == "worktree":
            result["worktree"] = completed.stdout.rstrip("\r\n")
            try:
                same_worktree = result["worktree"] == str(path.resolve(strict=True))
            except (OSError, RuntimeError):
                same_worktree = False
            if not same_worktree:
                return {**result, "reason": "worktree_redirected"}
        elif field == "filters":
            # Even read-only status can run repository-defined clean/process
            # filters. Inspect includes too and refuse before status; do not
            # print the configured command or run it to discover its behavior.
            result["filters_configured"] = True
            result["filter_config_sha256"] = hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest()
            return {**result, "reason": "git_filters_configured"}
        elif field in {"index_entries", "head_entries"}:
            # These plumbing reads do not inspect child worktrees or run
            # content filters. A parent's filter config says nothing about
            # its children. Even an unpopulated or staged/deleted gitlink is
            # unverified state, never evidence of a clean installed pack.
            if any(entry.startswith("160000 ") for entry in completed.stdout.split("\0")):
                return {**result, "reason": "git_submodules_unverified", "operation": field}
        elif field == "changes":
            result["dirty"] = bool(completed.stdout)
            result["changes"] = completed.stdout.split("\0")[:-1] if completed.stdout else []
        else:
            result[field] = completed.stdout.rstrip("\r\n")
    try:
        if (not _same_file(info, path.lstat()) or not _same_file(git_info, (path / ".git").lstat())
                or _sentinel(path) != result["sentinel"]):
            return {**result, "state": "unknown", "reason": "changed_during_observation"}
    except OSError:
        return {**result, "state": "unknown", "reason": "changed_during_observation"}
    if not repo or not commit:
        return {**result, "reason": "expected_identity_unknown"}
    from vibecomfy.node_packs._install import _normalize_git_remote

    if _normalize_git_remote(result["repo"]) != _normalize_git_remote(repo):
        return {**result, "state": "conflict", "reason": "repository_mismatch"}
    if result["commit"] != commit:
        return {**result, "state": "conflict", "reason": "commit_mismatch"}
    if result["dirty"]:
        return {**result, "state": "conflict", "reason": "dirty_checkout"}
    return {**result, "state": "present"}
