"""Socket type vocabulary used for comparisons, never for serialization."""

from __future__ import annotations

COMBO = "COMBO"

_ALIASES = {
    "CHOICE": COMBO,
    "ENUM": COMBO,
}


def canonical_socket_type(value: object) -> str:
    """Return a comparison name without changing the stored socket type."""
    token = "" if value is None else str(value).strip().upper()
    return _ALIASES.get(token, token)
