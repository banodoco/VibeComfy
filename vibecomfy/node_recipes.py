"""Canonical, data-only custom-node recipes shared with generation approval.

The requirements file is relative to the pinned repository. ``pip_no_deps``
is an ordered list of individual pip requirements, never command-line options.
Neither validating nor hashing a recipe reads files, fetches code or installs it.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


RECIPE_FIELDS = frozenset({"requirements_txt", "pip_no_deps"})


def _has_control(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def canonical_recipe(recipe: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy the two recipe fields into one canonical JSON shape.

    Omission and explicit defaults have the same meaning. Package order and
    duplicates are preserved: the controlled installer executes them in order.
    Identity is deliberately separate; approval binds this hash to repo/commit.
    """
    if not isinstance(recipe, Mapping) or set(recipe) - RECIPE_FIELDS:
        raise ValueError("node recipe accepts only requirements_txt and pip_no_deps")
    path = recipe.get("requirements_txt")
    if path is not None and (
        not isinstance(path, str) or not path or path != path.strip()
        or _has_control(path) or "\\" in path or ":" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise ValueError("requirements_txt must be a relative POSIX file path without '..'")
    packages = recipe.get("pip_no_deps", ())
    if not isinstance(packages, (list, tuple)) or any(
        not isinstance(item, str) or not item.strip() or item != item.strip()
        or item.startswith("-") or _has_control(item) for item in packages
    ):
        raise ValueError("pip_no_deps must be an ordered array of nonempty requirements, not pip options")
    return {"requirements_txt": path, "pip_no_deps": list(packages)}


def recipe_sha256(recipe: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical UTF-8 JSON recipe (sorted keys, no whitespace)."""
    payload = json.dumps(canonical_recipe(recipe), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
