"""Pack slug metadata at the object-info cache boundary."""

from __future__ import annotations

from typing import Any


def normalize_cache_identity(entry: dict[str, Any]) -> dict[str, Any]:
    """Fill the slug for older snapshots which only record pack."""
    result = dict(entry)
    if not result.get("pack_slug") and result.get("pack"):
        result["pack_slug"] = result["pack"]
    return result
