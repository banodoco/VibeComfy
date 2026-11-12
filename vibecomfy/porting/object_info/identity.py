"""Canonical identity metadata at the object-info cache boundary."""

from __future__ import annotations

from typing import Any


def normalize_cache_identity(entry: dict[str, Any]) -> dict[str, Any]:
    """Keep commits in git_commit, accepting historical cache representations.

    Full commit IDs in pack_version can be translated without rewriting old
    snapshots. Version labels and unpinned snapshots provide no commit witness.
    """
    result = dict(entry)
    if not result.get("pack_slug") and result.get("pack"):
        result["pack_slug"] = result["pack"]
    version = result.get("pack_version")
    if isinstance(version, str) and len(version) == 40 and all(
        char in "0123456789abcdefABCDEF" for char in version
    ):
        commit = result.get("git_commit")
        if not commit or commit == version:
            result["git_commit"] = version
            result.pop("pack_version", None)
    return result
