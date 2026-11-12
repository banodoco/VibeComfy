"""Pack slug metadata at the object-info cache boundary."""

from __future__ import annotations

from typing import Any


def normalize_cache_identity(entry: dict[str, Any]) -> dict[str, Any]:
    """Fill the slug for older snapshots which only record pack."""
    result = dict(entry)
    if not result.get("pack_slug") and result.get("pack"):
        result["pack_slug"] = result["pack"]
    return result


def select_object_info_identity(
    cached: dict[str, Any],
    metadata: dict[str, Any],
    locked_identity: dict[str, Any] | None = None,
    *,
    pack_identity_commits: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Select an offline schema identity, optionally using engine recipe pins.

    ``pack_identity_commits`` maps canonical pack slugs (including
    ``comfy_core``) to exact commits. It takes precedence over workflow
    metadata, effective locks and the indexed class default, in that order.
    Omitting it preserves the historical selection.
    """
    identity = metadata.get("object_info_identity")
    source = metadata.get("schema_source")
    if identity is None and isinstance(source, dict) and (
        source.get("git_commit") or source.get("evidence_identity")
    ):
        identity = source
    slug = (identity or {}).get("pack_slug")
    slug = slug or (locked_identity or {}).get("pack_slug")
    slug = slug or cached.get("pack_slug") or cached.get("pack")
    if pack_identity_commits is not None and slug in pack_identity_commits:
        commit = pack_identity_commits[slug]
        if not isinstance(commit, str) or not commit:
            raise ValueError("pack_identity_commits requires nonempty commit strings")
        return {"pack_slug": slug, "git_commit": commit}
    if identity is not None:
        return identity
    if locked_identity is not None:
        return locked_identity
    pin = "git_commit" if cached.get("git_commit") else "evidence_identity"
    return {"pack_slug": slug, pin: cached.get(pin)}
