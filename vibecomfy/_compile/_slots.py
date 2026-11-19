"""Private, compile-time literal provenance; never a transport value."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class LiteralSlot:
    index: int
    sample: Any

    def __deepcopy__(self, memo: dict[int, Any]) -> "LiteralSlot":
        return self


def literal_sample(value: Any) -> Any:
    return value.sample if type(value) is LiteralSlot else value
