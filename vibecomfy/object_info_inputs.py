"""Read ComfyUI input declarations at the object_info boundary.

Both live V1/V3 specs and recorded/normalized specs use this reader. Values
and enum spellings are preserved; missing choices never grant enum authority.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ObjectInfoInput:
    type: str | None
    choices: list[Any] | None
    metadata: Mapping[str, Any]
    raw: Any
    required: bool = False
    hidden: bool = False
    legacy_combo: bool = False

    @property
    def default(self) -> Any:
        return self.metadata.get("default")

    @property
    def has_default(self) -> bool:
        return "default" in self.metadata


def read_object_info_input(
    raw: Any, *, required: bool = False, hidden: bool = False,
) -> ObjectInfoInput:
    """Read type, choices and widget metadata from one input spec.

    V1: ``[["a", "b"], {"default": "a"}]``.
    V3: ``["COMBO", {"options": ["a", "b"], "default": "a"}]``.
    Typed inputs: ``["INT", {...}]``; normalized rows: ``{"type": ...}``.
    An empty enum is distinct from an input with no declared choices.
    """
    typ = None
    metadata: Mapping[str, Any] = {}
    choices = None
    legacy_combo = False
    if isinstance(raw, Mapping):
        typ = raw.get("type")
        metadata = raw
        choices = raw.get("choices")
        if choices is None and typ == "COMBO":
            choices = raw.get("options")
    elif isinstance(raw, (list, tuple)) and raw:
        typ = raw[0]
        if len(raw) > 1 and isinstance(raw[1], Mapping):
            metadata = raw[1]
        if isinstance(typ, (list, tuple)):
            choices = typ
            typ = "COMBO"
            legacy_combo = True
        elif typ == "COMBO":
            choices = metadata.get("options")
    elif isinstance(raw, str):
        typ = raw
    return ObjectInfoInput(
        type=str(typ) if typ is not None else None,
        choices=list(choices) if isinstance(choices, (list, tuple)) else None,
        metadata=metadata,
        raw=raw,
        required=required,
        hidden=hidden,
        legacy_combo=legacy_combo,
    )


def object_info_input_order(info: Mapping[str, Any]) -> list[str]:
    """Read the declared order, retaining any unlisted fields in source order."""
    # Preserve recorded widget ordering: it is also used to bind native
    # input rosters and therefore contributes to workflow semantic digests.
    for key in ("object_info_widget_order", "input_order_all"):
        order = info.get(key)
        if isinstance(order, (list, tuple)):
            return [name for name in order if isinstance(name, str) and name]
    order = info.get("input_order")
    if isinstance(order, Mapping):
        return [name for group in ("required", "optional", "hidden")
                for name in order.get(group, ()) if isinstance(name, str) and name]
    return []


def read_object_info_inputs(info: Mapping[str, Any]) -> dict[str, ObjectInfoInput]:
    """Read required/optional declarations in their advertised order."""
    groups = info.get("input")
    if not isinstance(groups, Mapping):
        groups = info.get("inputs")
    fields = {}
    if isinstance(groups, Mapping):
        for group, rows in groups.items():
            if group in {"required", "optional", "hidden"} and isinstance(rows, Mapping):
                for name, raw in rows.items():
                    fields[str(name)] = read_object_info_input(
                        raw, required=group == "required", hidden=group == "hidden",
                    )
    names = dict.fromkeys([*object_info_input_order(info), *fields])
    return {name: fields[name] for name in names if name in fields}
