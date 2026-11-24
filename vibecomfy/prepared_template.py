"""Private, disposable prepare/key/fill contract for ComfyUI source generation.

This is not an approval or an executable-source cache.  The caller must witness
the current source/compiler/role/target inputs *before* calling ``fill_template``.
It must retain its normal source admission, input binding, target preflight,
canonical publication and approval checks.  In particular a locator or a stored
key is not a current source witness.

``prepare_template`` detaches a typed workflow recipe and masks explicit value
slots.  ``fill_template`` supplies every value afresh without running its builder.
The sole canonical emitter records value-independent layouts in the returned
fill's ``emission`` session.  Persist ``fill.snapshot()`` only after successful
publication; this captures layouts from both staged and final emission without
doing an extra cold render.  A subsequent fill reuses those layouts through the
same emitter.  Value-dependent projection, constants, defaults, formatting,
recursive constructors, markers and all validation still run every time.

The Agent owns filesystem storage, locking, current witnesses and cache/timing
events.  There is no filesystem cache, process registry, approval, provider,
pickle or callable in this record.  Retained source bindings are verified against
the current wrapper registry before use; they cannot authorize imports.  Its ordered tagged recipe keeps
dict order, tuples, explicit None and authored defaults, unlike sorted envelope
JSON.  Unknown types and unmodelled state refuse preparation with a reason; the
caller must report it and take its ordinary full-preparation path.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass, fields, is_dataclass
from functools import lru_cache
from typing import Any, Callable, Mapping, Sequence, TYPE_CHECKING

from vibecomfy.testing.canonical import canonical_bytes, canonical_digest

if TYPE_CHECKING:
    from vibecomfy.workflow import VibeWorkflow


FORMAT = "astrid.prepared-template/v1"
BACKEND = "comfyui"
KEY_FIELDS = (
    "format", "backend", "structure", "compiler_identity", "source_provenance",
    "vibecomfy_version", "role_plan", "node_list_digest",
)
_CONTEXT_FIELDS = frozenset(KEY_FIELDS[3:])
_RECORD_FIELDS = frozenset({"format", "backend", "key", "key_inputs", "payload", "content_digest"})
_PAYLOAD_FIELDS = frozenset({"recipe", "slots", "layouts"})
_MAX_BYTES = 32 * 1024 * 1024
_MAX_DEPTH = 160
_MAX_ITEMS = 500_000
_MAX_LAYOUTS = 32
_SLOT_KINDS = frozenset({"string", "integer", "number", "boolean", "json"})
_SPENT_WORKFLOW_STATE = frozenset({"_canonical_v2_recursive_custody", "_recursive_definition_captures"})


class TemplateNotReusable(ValueError):
    """A recipe cannot safely be persisted; full preparation remains required."""

    def __init__(self, detail: str, *, reason: str = "entry_invalid") -> None:
        self.reason = reason
        super().__init__(detail)


class TemplateKeyChanged(TemplateNotReusable):
    """The caller's freshly witnessed key differs from the cached key."""

    def __init__(self, name: str) -> None:
        self.input = name
        super().__init__(f"prepared template input changed: {name}", reason=f"key_changed:{name}")


@dataclass(frozen=True, slots=True)
class ValueSlot:
    """One current value and every explicit recipe occurrence it replaces.

    Paths address workflow dataclass fields, dict keys and list/tuple indices.
    Only literal channels are allowed, never identities, edges, node classes or
    mode/variant selectors.  All paths must already exist.  Adding an omitted
    field requires a newly prepared recipe; omission is not confused with None.
    ``default`` is a separate channel: do not mask an authored default unless
    the existing per-request binder actually replaces it (e.g. attempt prefix).
    """

    name: str
    paths: tuple[tuple[str | int, ...], ...]
    kind: str = "json"
    allow_none: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or not isinstance(self.kind, str) or self.kind not in _SLOT_KINDS:
            raise TemplateNotReusable("invalid value-slot name or kind")
        if type(self.allow_none) is not bool or not isinstance(self.paths, tuple) or not self.paths:
            raise TemplateNotReusable("value-slot paths must be a nonempty tuple")
        for path in self.paths:
            if not isinstance(path, tuple) or not path or any(type(p) not in (str, int) for p in path):
                raise TemplateNotReusable("invalid value-slot path")
            if not _literal_path(path):
                raise TemplateNotReusable(f"slot {self.name!r} is not a literal channel: {path!r}")

    def record(self) -> dict[str, Any]:
        return {"name": self.name, "paths": [list(p) for p in self.paths],
                "kind": self.kind, "allow_none": self.allow_none}


def _literal_path(path: tuple[str | int, ...]) -> bool:
    if len(path) == 4 and path[0] == "nodes" and path[2] in {"inputs", "widgets"}:
        return isinstance(path[1], str) and isinstance(path[3], str)
    if len(path) == 3 and path[0] == "inputs" and path[2] in {"value", "default"}:
        return isinstance(path[1], str)
    if len(path) == 3 and path[0] == "outputs" and path[2] == "filename_prefix":
        return type(path[1]) is int and path[1] >= 0
    if path == ("metadata", "output_prefix"):
        return True
    # Nested definitions have their own authored JSON nodes.  Only an actual
    # inputs/widgets value is replaceable; their type/id/ports remain structural.
    if path[0] == "definitions" and "nodes" in path:
        node_at = max(i for i, part in enumerate(path) if part == "nodes")
        tail = path[node_at + 2:]
        return (len(tail) == 2 and tail[0] in {"inputs", "widgets"} and isinstance(tail[1], str)
                or len(tail) == 3 and tail[0] == "inputs" and type(tail[1]) is int and tail[2] == "value")
    return False


def node_list_digest(raw_response: bytes) -> str:
    """Hash the already-held response bytes; never canonicalize object-info."""
    if not isinstance(raw_response, bytes):
        raise TypeError("node-list witness requires the current raw response bytes")
    return "sha256:" + hashlib.sha256(raw_response).hexdigest()


def key_record(*, structure: str, compiler_identity: Any, source_provenance: Any,
               vibecomfy_version: str, role_plan: Any, node_list_digest: str) -> list[list[Any]]:
    """The one ordered canonical key record (all arguments are current inputs).

    Compiler/source identities are content witnesses, not version labels or a
    shared ':dirty' tag.  The caller times their collection as a separate key
    stage, along with the role plan and hash of the current raw node response.
    A managed-install stamp may stand for the closure only under its own valid
    custody contract; editable/dirty sources must still be hashed.
    """
    result = [["format", FORMAT], ["backend", BACKEND], ["structure", structure],
              ["compiler_identity", compiler_identity], ["source_provenance", source_provenance],
              ["vibecomfy_version", vibecomfy_version], ["role_plan", role_plan],
              ["node_list_digest", node_list_digest]]
    _check_key_record(result)
    return _json_copy(result)


def template_key(inputs: Sequence[Sequence[Any]]) -> str:
    _check_key_record(inputs)
    return "sha256:" + canonical_digest(inputs)


def _check_key_record(inputs: Any) -> None:
    if not isinstance(inputs, (list, tuple)) or len(inputs) != len(KEY_FIELDS):
        raise TemplateNotReusable("invalid prepared-template key record")
    if any(not isinstance(p, (list, tuple)) or len(p) != 2 or p[0] != name
           for p, name in zip(inputs, KEY_FIELDS)):
        raise TemplateNotReusable("prepared-template key fields are not in canonical order")
    values = dict(inputs)
    if values["format"] != FORMAT or values["backend"] != BACKEND:
        raise TemplateNotReusable("foreign prepared-template key format/backend")
    if not _digest_string(values["structure"]) or not _digest_string(values["node_list_digest"]):
        raise TemplateNotReusable("structure and node list must have SHA-256 content witnesses")
    if not isinstance(values["vibecomfy_version"], str) or not values["vibecomfy_version"]:
        raise TemplateNotReusable("missing VibeComfy version witness")
    for name in ("compiler_identity", "source_provenance", "role_plan"):
        if values[name] is None or values[name] == "" or values[name] == {}:
            raise TemplateNotReusable(f"missing current {name} witness")
    canonical_bytes(inputs)  # refuses non-JSON / non-finite identity inputs


def _digest_string(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 71 and value.startswith("sha256:")
            and all(c in "0123456789abcdef" for c in value[7:]))


def _json_copy(value: Any) -> Any:
    return json.loads(canonical_bytes(value))


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TemplateNotReusable(f"duplicate prepared-template JSON key: {key}")
        result[key] = value
    return result


def _no_json_constant(value: str) -> None:
    raise TemplateNotReusable(f"non-finite prepared-template JSON value: {value}")


@lru_cache(maxsize=1)
def _record_types() -> dict[str, type]:
    from vibecomfy.contracts.runtime import RuntimeRequirements
    from vibecomfy.workflow import (
        RawWidgetPayload, VibeEdge, VibeInput, VibeNode, VibeOutput, VibeWorkflow,
        WorkflowRequirements, WorkflowSource,
    )
    return {cls.__name__: cls for cls in (
        VibeWorkflow, WorkflowSource, WorkflowRequirements, RuntimeRequirements,
        VibeNode, VibeEdge, VibeInput, VibeOutput, RawWidgetPayload,
    )}


def _recipe_fields(cls: type) -> tuple[Any, ...]:
    # The context token is a live process object, never part of a recipe.
    return tuple(f for f in fields(cls) if f.name != "_workflow_context_token")


def _encode_recipe(value: Any, slots: dict[tuple[Any, ...], ValueSlot],
                   seen_slots: set[tuple[Any, ...]], *, path: tuple[Any, ...] = (),
                   active: set[int] | None = None, depth: int = 0) -> Any:
    from vibecomfy.workflow import NodeMode
    from vibecomfy.security.provenance import Provenance
    if depth > _MAX_DEPTH:
        raise TemplateNotReusable("prepared recipe exceeds nesting bound")
    if path in slots:
        slot = slots[path]
        _check_value(slot, value)
        seen_slots.add(path)
        return ["slot", slot.name]
    if isinstance(value, NodeMode):
        return ["mode", value.value]
    if isinstance(value, Provenance):
        return ["provenance", value.value]
    if value is None or type(value) in (str, bool, int):
        return ["atom", value]
    if type(value) is float:
        if not math.isfinite(value):
            raise TemplateNotReusable("non-finite recipe literal")
        return ["atom", value]
    active = set() if active is None else active
    if id(value) in active:
        raise TemplateNotReusable("cyclic prepared recipe")
    active.add(id(value))
    try:
        def encode(item: Any, key: Any) -> Any:
            return _encode_recipe(item, slots, seen_slots, path=(*path, key), active=active, depth=depth + 1)
        if type(value) is dict:
            if any(type(k) is not str for k in value):
                raise TemplateNotReusable("recipe mappings require string keys")
            return ["map", [[k, encode(v, k)] for k, v in value.items()]]
        if type(value) in (list, tuple):
            return ["list" if type(value) is list else "tuple",
                    [encode(v, i) for i, v in enumerate(value)]]
        if type(value) is set and all(type(v) is str for v in value):
            return ["set", sorted(value)]
        if is_dataclass(value) and _record_types().get(type(value).__name__) is type(value):
            fs = _recipe_fields(type(value))
            if getattr(value, "_workflow_context_token", None) is not None:
                raise TemplateNotReusable("active workflow context cannot be prepared")
            extra = set(getattr(value, "__dict__", {})) - {f.name for f in fields(value)}
            if extra and (type(value).__name__ != "VibeWorkflow"
                          or not extra <= _SPENT_WORKFLOW_STATE
                          or any(getattr(value, name) is not None for name in extra)):
                raise TemplateNotReusable(f"unmodelled {type(value).__name__} state: {sorted(extra)!r}")
            # Finalize leaves these known spent one-build witnesses as None.
            # Keep their presence without persisting live construction state.
            return ["record", type(value).__name__, [[f.name, encode(getattr(value, f.name), f.name)] for f in fs], sorted(extra)]
        raise TemplateNotReusable(f"unsupported recipe type: {type(value).__name__}")
    finally:
        active.remove(id(value))


def _walk_recipe(value: Any, slots: Mapping[str, ValueSlot], values: Mapping[str, Any] | None,
                 *, path: tuple[Any, ...] = (), occurrences: dict[str, list[tuple[Any, ...]]] | None = None,
                 budget: list[int] | None = None, depth: int = 0) -> Any:
    """Validate the closed tagged tree; construct only locally named IR types."""
    budget = [_MAX_ITEMS] if budget is None else budget
    budget[0] -= 1
    if depth > _MAX_DEPTH or budget[0] < 0 or not isinstance(value, list) or len(value) < 2:
        raise TemplateNotReusable("invalid or oversized prepared recipe")
    tag = value[0]
    if not isinstance(tag, str):
        raise TemplateNotReusable("invalid prepared recipe tag")
    if tag == "slot" and len(value) == 2 and isinstance(value[1], str) and value[1] in slots:
        if occurrences is not None:
            occurrences.setdefault(value[1], []).append(path)
        return None if values is None else _clone_literal(values[value[1]])
    if tag == "atom" and len(value) == 2:
        atom = value[1]
        if atom is None or type(atom) in (str, bool, int) or type(atom) is float and math.isfinite(atom):
            return atom
        raise TemplateNotReusable("invalid recipe atom")
    if tag in {"mode", "provenance"} and len(value) == 2:
        from vibecomfy.workflow import NodeMode
        from vibecomfy.security.provenance import Provenance
        enum = NodeMode if tag == "mode" else Provenance
        if not isinstance(value[1], str) or value[1] not in {item.value for item in enum}:
            raise TemplateNotReusable(f"unknown recipe {tag}")
        return None if values is None else enum(value[1])
    if tag == "set" and len(value) == 2 and isinstance(value[1], list):
        members = value[1]
        if any(type(v) is not str for v in members) or members != sorted(set(members)):
            raise TemplateNotReusable("invalid recipe set")
        return None if values is None else set(members)

    def walk(item: Any, key: Any) -> Any:
        return _walk_recipe(item, slots, values, path=(*path, key), occurrences=occurrences,
                            budget=budget, depth=depth + 1)

    if tag in {"list", "tuple"} and len(value) == 2 and isinstance(value[1], list):
        children = [walk(item, i) for i, item in enumerate(value[1])]
        return children if tag == "list" else tuple(children)
    if tag == "map" and len(value) == 2:
        pairs = value[1]
        cls = None
        extras = []
    elif tag == "record" and len(value) == 4 and isinstance(value[1], str):
        cls = _record_types().get(value[1])
        if cls is None:
            raise TemplateNotReusable("unknown prepared recipe record")
        pairs = value[2]
        extras = value[3]
        if (not isinstance(extras, list) or any(type(name) is not str for name in extras)
                or extras != sorted(set(extras))
                or extras and (value[1] != "VibeWorkflow" or not set(extras) <= _SPENT_WORKFLOW_STATE)):
            raise TemplateNotReusable("invalid spent recipe state")
    else:
        raise TemplateNotReusable("unknown prepared recipe tag")
    if not isinstance(pairs, list):
        raise TemplateNotReusable("invalid ordered recipe mapping")
    result = {}
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2 or type(pair[0]) is not str or pair[0] in result:
            raise TemplateNotReusable("invalid/duplicate ordered recipe member")
        result[pair[0]] = walk(pair[1], pair[0])
    if cls is None:
        return result
    fs = _recipe_fields(cls)
    if list(result) != [f.name for f in fs]:
        raise TemplateNotReusable(f"prepared {cls.__name__} fields differ from the loaded compiler")
    _check_record_shape(cls.__name__, dict(pairs))
    if values is None:
        return None
    instance = cls(**{f.name: result[f.name] for f in fs if f.init})
    for f in fs:
        if not f.init:
            setattr(instance, f.name, result[f.name])
    for name in extras:
        setattr(instance, name, None)
    return instance


def _check_record_shape(name: str, encoded: Mapping[str, Any]) -> None:
    """Reject malformed container/IR substitutions before any construction."""
    def tag(field: str, allowed: set[str]) -> None:
        if encoded[field][0] not in allowed:
            raise TemplateNotReusable(f"invalid prepared {name}.{field} shape")

    def record(field: str, expected: str) -> None:
        if encoded[field][:2] != ["record", expected]:
            raise TemplateNotReusable(f"invalid prepared {name}.{field} record")

    def members(field: str, kind: str, expected: str) -> None:
        tag(field, {kind})
        rows = encoded[field][1]
        children = [pair[1] for pair in rows] if kind == "map" else rows
        if any(child[:2] != ["record", expected] for child in children):
            raise TemplateNotReusable(f"invalid prepared {name}.{field} members")

    if name == "VibeWorkflow":
        record("source", "WorkflowSource")
        record("requirements", "WorkflowRequirements")
        members("nodes", "map", "VibeNode")
        members("edges", "list", "VibeEdge")
        members("inputs", "map", "VibeInput")
        members("outputs", "list", "VibeOutput")
        for field in ("metadata", "interfaces", "virtual_wires", "variants", "_id_map"):
            tag(field, {"map"})
        for field in ("groups", "boundary_ports"):
            tag(field, {"list"})
        tag("definitions", {"map", "list"})
        tag("_manual_input_names", {"set"})
    elif name == "VibeNode":
        for field in ("inputs", "widgets", "metadata"):
            tag(field, {"map"})
        for field in ("id", "uid", "class_type"):
            if encoded[field][0] != "atom" or type(encoded[field][1]) is not str:
                raise TemplateNotReusable(f"invalid prepared node {field}")
    elif name == "WorkflowSource":
        tag("provenance", {"map"})
    elif name == "WorkflowRequirements":
        for field in ("models", "custom_nodes", "missing_models", "missing_nodes", "unsupported", "custom_node_refs"):
            tag(field, {"list"})
        if encoded["runtime"] != ["atom", None]:
            record("runtime", "RuntimeRequirements")


def _clone_literal(value: Any) -> Any:
    # JSON is the slot contract.  A new tree per occurrence prevents one slot
    # binding from aliasing another node or a later request.
    return copy.deepcopy(value)


def _check_value(slot: ValueSlot, value: Any) -> None:
    if value is None and slot.allow_none:
        return
    good = {"string": type(value) is str, "integer": type(value) is int,
            "number": type(value) in (int, float), "boolean": type(value) is bool,
            "json": value is not None}[slot.kind]
    if not good:
        raise ValueError(f"value for prepared slot {slot.name!r} must be {slot.kind}")
    _check_literal(value)
    if (isinstance(value, list) and len(value) == 2 and isinstance(value[1], int)
            and re.fullmatch(r"\d+(?::\d+|::\d+)*", str(value[0]))):
        # The existing Comfy emitter can interpret this top-level shape as a
        # graph reference.  It has no unambiguous literal witness here, so even
        # a JSON socket with this shape takes the ordinary full-preparation path.
        raise TemplateNotReusable(f"slot {slot.name!r} has an unwitnessed graph-link shape")


def _check_literal(value: Any, depth: int = 0) -> None:
    if depth > _MAX_DEPTH:
        raise ValueError("prepared slot value exceeds nesting bound")
    if value is None or type(value) in (str, int, bool):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _check_literal(item, depth + 1)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _check_literal(item, depth + 1)
        return
    raise ValueError("prepared slot values must be finite plain JSON")


def _slots_from_records(records: Any) -> tuple[ValueSlot, ...]:
    if not isinstance(records, list):
        raise TemplateNotReusable("invalid prepared slot table")
    result = []
    names: set[str] = set()
    paths: set[tuple[Any, ...]] = set()
    for raw in records:
        if not isinstance(raw, dict) or set(raw) != {"name", "paths", "kind", "allow_none"}:
            raise TemplateNotReusable("invalid prepared slot record")
        if not isinstance(raw["paths"], list) or any(not isinstance(p, list) for p in raw["paths"]):
            raise TemplateNotReusable("invalid prepared slot paths")
        slot = ValueSlot(raw["name"], tuple(tuple(p) for p in raw["paths"]), raw["kind"], raw["allow_none"])
        if slot.name in names:
            raise TemplateNotReusable("duplicate prepared slot name")
        names.add(slot.name)
        for path in slot.paths:
            if any(path[:len(old)] == old or old[:len(path)] == path for old in paths):
                raise TemplateNotReusable("overlapping prepared slot paths")
            paths.add(path)
        result.append(slot)
    return tuple(result)


def _structure_digest(recipe: Any, slots: Any) -> str:
    return "sha256:" + canonical_digest([FORMAT, BACKEND, recipe, slots])


def _seal(inputs: Any, payload: Any) -> bytes:
    body = {"format": FORMAT, "backend": BACKEND, "key": template_key(inputs),
            "key_inputs": inputs, "payload": payload}
    return canonical_bytes({**body, "content_digest": "sha256:" + canonical_digest(body)})


@dataclass(frozen=True, slots=True)
class PreparedTemplate:
    """Immutable canonical JSON, safe to transfer to another process."""

    _data: bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> "PreparedTemplate":
        if not isinstance(data, bytes) or len(data) > _MAX_BYTES:
            raise TemplateNotReusable("prepared entry exceeds byte bound")
        try:
            record = json.loads(data, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_json_constant)
        except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise TemplateNotReusable("invalid prepared entry JSON") from exc
        try:
            return cls._from_record(record)
        except TemplateNotReusable:
            raise
        except (TypeError, ValueError, KeyError, IndexError, OverflowError, RecursionError) as exc:
            # This boundary only decodes cache data.  No builder, renderer or
            # approval runs here; their errors are never converted to misses.
            raise TemplateNotReusable("invalid prepared entry encoding") from exc

    @classmethod
    def _from_record(cls, record: Any) -> "PreparedTemplate":
        if not isinstance(record, dict) or set(record) != _RECORD_FIELDS:
            raise TemplateNotReusable("prepared entry is not a closed record")
        if record["format"] != FORMAT or record["backend"] != BACKEND:
            raise TemplateNotReusable("foreign prepared entry")
        body = {key: value for key, value in record.items() if key != "content_digest"}
        if record["content_digest"] != "sha256:" + canonical_digest(body):
            raise TemplateNotReusable("prepared entry content digest mismatch")
        if record["key"] != template_key(record["key_inputs"]):
            raise TemplateNotReusable("prepared entry key mismatch")
        payload = record["payload"]
        if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
            raise TemplateNotReusable("prepared payload is not a closed record")
        slots = _slots_from_records(payload["slots"])
        occurrences: dict[str, list[tuple[Any, ...]]] = {}
        recipe = payload["recipe"]
        if not isinstance(recipe, list) or recipe[:2] != ["record", "VibeWorkflow"]:
            raise TemplateNotReusable("prepared recipe must describe a VibeWorkflow")
        _walk_recipe(recipe, {s.name: s for s in slots}, None, occurrences=occurrences)
        if {s.name: set(s.paths) for s in slots} != {k: set(v) for k, v in occurrences.items()}:
            raise TemplateNotReusable("prepared slot table differs from recipe occurrences")
        if dict(record["key_inputs"])["structure"] != _structure_digest(recipe, payload["slots"]):
            raise TemplateNotReusable("prepared structure digest mismatch")
        _check_layouts(payload["layouts"])
        return cls(canonical_bytes(record))

    def to_bytes(self) -> bytes:
        return self._data

    def to_record(self) -> dict[str, Any]:
        return json.loads(self._data)

    @property
    def key_inputs(self) -> list[list[Any]]:
        return self.to_record()["key_inputs"]

    @property
    def key(self) -> str:
        return self.to_record()["key"]

    @property
    def structure_digest(self) -> str:
        return dict(self.key_inputs)["structure"]


@dataclass(frozen=True, slots=True)
class LayoutEvent:
    outcome: str
    reason: str | None


def _check_layouts(layouts: Any) -> None:
    if not isinstance(layouts, list) or len(layouts) > _MAX_LAYOUTS:
        raise TemplateNotReusable("invalid prepared emission layout table")
    signatures: set[str] = set()
    for row in layouts:
        if not isinstance(row, dict) or set(row) != {"signature", "layout"}:
            raise TemplateNotReusable("invalid prepared emission layout")
        signature = canonical_digest(row["signature"])
        if signature in signatures:
            raise TemplateNotReusable("duplicate prepared emission layout")
        signatures.add(signature)
        layout = row["layout"]
        if not isinstance(layout, dict) or set(layout) != {"node_order", "sections", "imports", "constructors"}:
            raise TemplateNotReusable("invalid prepared emission layout fields")
        if not isinstance(layout["node_order"], list) or any(type(n) is not str for n in layout["node_order"]):
            raise TemplateNotReusable("invalid prepared constructor order")
        for name in ("sections", "imports", "constructors"):
            rows = layout[name]
            if not isinstance(rows, list) or any(not isinstance(p, list) or len(p) != 2 or type(p[0]) is not str for p in rows):
                raise TemplateNotReusable(f"invalid ordered layout {name}")
            if len({p[0] for p in rows}) != len(rows):
                raise TemplateNotReusable(f"duplicate ordered layout {name}")
            for _, members in rows:
                if not isinstance(members, list) or any(type(v) is not str and not (name == "constructors" and v is None) for v in members):
                    raise TemplateNotReusable(f"invalid layout {name} members")
                if name == "constructors" and len(members) != 2:
                    raise TemplateNotReusable("constructor layout requires module and symbol")


class EmissionSession:
    """Per-fill structural layouts and explicit uses; never persisted as an object.

    Each staged/final emitter request selects its layout by its *current*
    projected structure/options.  An unseen layout is a recorded miss and
    recompute, never a guessed reuse.  The Agent translates these events into
    its cache counters.  Only a cached-layout validation refusal is converted
    into a miss; fresh preparation and product errors keep their normal path.
    """

    def __init__(self, layouts: list[dict[str, Any]],
                 on_event: Callable[[LayoutEvent], None] | None = None) -> None:
        _check_layouts(layouts)
        self._layouts = {canonical_digest(row["signature"]): _json_copy(row) for row in layouts}
        self.events: list[LayoutEvent] = []
        self._on_event = on_event

    def _event(self, outcome: str, reason: str | None = None) -> None:
        event = LayoutEvent(outcome, reason)
        self.events.append(event)
        if self._on_event is not None:
            self._on_event(event)

    def resolve(self, signature: Any, prepare: Callable[[], dict[str, Any]], *,
                validate: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        key = canonical_digest(signature)
        row = self._layouts.get(key)
        reason = "key_changed:structure" if self._layouts else "absent"
        if row is not None:
            layout = _json_copy(row["layout"])
            try:
                if validate is not None:
                    validate(layout)
            except TemplateNotReusable:
                # No cached names are used or reported as a hit before the
                # current emitter's registry/roster checks have succeeded.
                reason = "entry_invalid"
                del self._layouts[key]
            else:
                self._event("hit")
                return layout
        self._event("miss", reason)
        self._event("recompute", reason)
        layout = prepare()
        if validate is not None:
            validate(layout)
        row = {"signature": signature, "layout": layout}
        _check_layouts([row])
        if len(self._layouts) >= _MAX_LAYOUTS:
            raise TemplateNotReusable("too many structural emission layouts for one template")
        self._layouts[key] = _json_copy(row)
        return layout

    def records(self) -> list[dict[str, Any]]:
        return [_json_copy(row) for row in self._layouts.values()]


@dataclass(slots=True)
class FilledTemplate:
    workflow: "VibeWorkflow"
    emission: EmissionSession
    _template: PreparedTemplate

    def snapshot(self) -> PreparedTemplate:
        """Capture learned layouts after successful emission, never current values."""
        record = self._template.to_record()
        record["payload"]["layouts"] = self.emission.records()
        return PreparedTemplate.from_bytes(_seal(record["key_inputs"], record["payload"]))


def prepare_template(workflow: "VibeWorkflow", slots: Sequence[ValueSlot], *,
                     key_context: Mapping[str, Any]) -> PreparedTemplate:
    """Detach one witnessed source build; layouts are learned by the same renderer.

    ``key_context`` contains exactly compiler_identity, source_provenance,
    vibecomfy_version, role_plan and node_list_digest.  This function deliberately
    does not fetch a target, hash a model root, execute a builder or grant source
    authority.  The Agent must reject unwitnessed/executable builders before
    skipping them.  Existing request binders run on the filled workflow too.
    """
    from vibecomfy.workflow import VibeWorkflow
    if type(workflow) is not VibeWorkflow:
        raise TemplateNotReusable("prepared recipe requires the canonical VibeWorkflow type")
    if set(key_context) != _CONTEXT_FIELDS:
        raise TemplateNotReusable("incomplete prepared-template current key context")
    slot_records = [s.record() for s in slots]
    checked_slots = _slots_from_records(slot_records)
    slot_paths = {path: s for s in checked_slots for path in s.paths}
    found: set[tuple[Any, ...]] = set()
    recipe = _encode_recipe(workflow, slot_paths, found)
    if found != set(slot_paths):
        raise TemplateNotReusable(f"missing prepared literal paths: {sorted(set(slot_paths) - found, key=repr)!r}")
    inputs = key_record(structure=_structure_digest(recipe, slot_records), **key_context)
    payload = {"recipe": recipe, "slots": slot_records, "layouts": []}
    return PreparedTemplate.from_bytes(_seal(inputs, payload))


def fill_template(template: PreparedTemplate, values: Mapping[str, Any], *,
                  current_key_inputs: Sequence[Sequence[Any]],
                  on_layout_event: Callable[[LayoutEvent], None] | None = None) -> FilledTemplate:
    """Check the current key and bind a fresh, detached workflow on every call.

    The caller recomputes the structure from the decoded recipe under its
    freshly verified source/slot witness.  Copying stored key_inputs without
    observing the current compiler/source/role/target is not a valid use.
    Cache-boundary decoding errors are TemplateNotReusable; invalid current
    values and workflow refusals keep their normal errors and must not be
    swallowed as a cache failure.
    """
    template = PreparedTemplate.from_bytes(template.to_bytes())
    _check_key_record(current_key_inputs)
    for old, current in zip(template.key_inputs, current_key_inputs):
        if canonical_bytes(old[1]) != canonical_bytes(current[1]):
            raise TemplateKeyChanged(old[0])
    record = template.to_record()
    payload = record["payload"]
    slots = _slots_from_records(payload["slots"])
    if set(values) != {s.name for s in slots}:
        raise ValueError("every prepared slot requires exactly one current value")
    for slot in slots:
        _check_value(slot, values[slot.name])
    try:
        workflow = _walk_recipe(payload["recipe"], {s.name: s for s in slots}, values)
    except TemplateNotReusable:
        raise
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, OverflowError) as exc:
        raise TemplateNotReusable("prepared IR could not be reconstructed") from exc
    # Identity admission remains current; this is not schema/approval compile.
    report = workflow.validate_identity()
    if not report.ok:
        raise ValueError(report.issues[0].message)
    return FilledTemplate(workflow, EmissionSession(payload["layouts"], on_layout_event), template)
