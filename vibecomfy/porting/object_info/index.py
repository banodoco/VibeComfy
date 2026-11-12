"""The single object_info index: class defaults and held capture identities.

The reserved member extends the historical flat class-to-provider mapping.
Readers never discover captures by scanning the filesystem. Legacy indexes have
only defaults; ``republish_cache_root`` registers their providers once on write.
"""
from __future__ import annotations

import json
from typing import Any

from vibecomfy.errors import ObjectInfoCacheCorruptError

CAPTURES = "__object_info_captures__"


def split_index(data: Any) -> tuple[dict[str, str], dict[str, list[str]]]:
    from .generation import safe_cache_filename

    if not isinstance(data, dict):
        raise ObjectInfoCacheCorruptError("object_info index must be an object")
    defaults = {key: value for key, value in data.items() if key != CAPTURES}
    held = data.get(CAPTURES, {})
    if any(not isinstance(k, str) or not safe_cache_filename(v) for k, v in defaults.items()):
        raise ObjectInfoCacheCorruptError("unsafe object_info index row")
    if not isinstance(held, dict):
        raise ObjectInfoCacheCorruptError("object_info capture catalogue must be an object")
    for key, filenames in held.items():
        try:
            identity = json.loads(key)
        except (TypeError, ValueError) as exc:
            raise ObjectInfoCacheCorruptError("invalid object_info capture identity") from exc
        if (not isinstance(identity, list) or len(identity) != 3
                or not all(isinstance(item, str) and item for item in identity)
                or identity[1] not in {"git_commit", "evidence_identity", "legacy"}
                or not isinstance(filenames, list) or not filenames
                or any(not safe_cache_filename(f) for f in filenames)
                or len(set(filenames)) != len(filenames)):
            raise ObjectInfoCacheCorruptError("invalid object_info capture catalogue row")
    return defaults, held


def capture_key(entry: dict[str, Any], filename: str) -> str:
    pack = entry.get("pack_slug") or entry.get("pack") or filename.split("@")[0]
    kind = "git_commit" if entry.get("git_commit") else "evidence_identity"
    value = entry.get(kind)
    if not value:
        kind, value = "legacy", filename
    return json.dumps([pack, kind, value], separators=(",", ":"))


def indexed_captures(pack_files: dict[str, dict]) -> dict[str, list[str]]:
    held: dict[str, list[str]] = {}
    for filename, entries in sorted(pack_files.items()):
        for key in {capture_key(entry, filename) for entry in entries.values() if isinstance(entry, dict)}:
            held.setdefault(key, []).append(filename)
    return dict(sorted(held.items()))
