"""Process-local prepared workflow authority.

Preparation is deliberately separate from decoded ApprovedProjectionRecord values.
The session owner supplies identities from admitted, immutable source and target
snapshots. A new source, authority, installation or target generation has a new
context; a serialized handle never recreates a session's authority.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import logging
import math
import os
import re
import threading
import uuid
import weakref
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from vibecomfy._compile._slots import LiteralSlot
from vibecomfy.testing.canonical import canonical_bytes, canonical_digest
from vibecomfy.workflow import VibeWorkflow, _is_ui_only_prompt_input, _node_input_socket_type
from vibecomfy.workflow_bundle import (
    ApprovedProjectionRecord, WorkflowBundle, WorkflowBundleError,
    _freeze_json, _rebind_current_bundle, _thaw_json,
)


class PreparedWorkflowUnavailable(WorkflowBundleError):
    """This workflow needs the ordinary full preparation path."""


@dataclass(frozen=True, slots=True)
class PreparedWorkflowContext:
    """Identities supplied by the trusted pack/session admission owner."""

    source_identity: str
    capability_identity: str
    authority_scope: str
    settings_generation: str
    installation_generation: str
    target_identity: str
    target_generation: str
    schema_digest: str
    compiler_identity: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if type(value) is not str or not value.strip():
                raise WorkflowBundleError(f"prepared workflow {name} must be nonblank")

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))


def _value_shape(value: Any, *, depth: int = 0) -> Any:
    """A bounded JSON type/shape, with no schema, range or model preflight."""
    if depth > 32:
        raise WorkflowBundleError("prepared input exceeds the transport nesting bound")
    if value is None:
        return "null"
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is float:
        if not math.isfinite(value):
            raise WorkflowBundleError("prepared input must be finite")
        return "float"
    if type(value) is str:
        return "str"
    if type(value) in (list, tuple):
        if len(value) > 4096:
            raise WorkflowBundleError("prepared input exceeds the transport collection bound")
        return ("array", tuple(_value_shape(item, depth=depth + 1) for item in value))
    if isinstance(value, Mapping):
        if len(value) > 4096 or any(type(key) is not str for key in value):
            raise WorkflowBundleError("prepared input requires bounded string object keys")
        return (
            "object",
            tuple((key, _value_shape(value[key], depth=depth + 1)) for key in sorted(value)),
        )
    raise WorkflowBundleError(f"prepared input is not JSON-safe: {type(value).__name__}")

_FORMAT = "vibecomfy.prepared.v1"
_MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")
_LOG = logging.getLogger(__name__)


def _source_closure(bundle: WorkflowBundle) -> str:
    """Read once at admission; only closed, declarative builders can be held."""
    if bundle.python_path is None:
        # An in-memory IR is already the admitted snapshot. The caller owns
        # its source identity; executable entry hooks are never admitted here.
        return canonical_digest([bundle.semantic_digest, bundle.ui_digest])
    path = Path(bundle.python_path)
    source = path.read_bytes()
    try:
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeError) as exc:
        raise PreparedWorkflowUnavailable("workflow source cannot be frozen") from exc
    allowed_imports = {
        "__future__": {"annotations"},
        "vibecomfy.templates": {"InputSpec", "ModelAsset", "OutputSpec", "ReadyMetadata",
                                "new_workflow", "ref", "node", "authored_channel"},
        "vibecomfy.workflow": {"VibeWorkflow"},
        "vibecomfy.patches.ltx_lowvram": {"apply"},
        "vibecomfy.patches.requirements": {"ensure_custom_nodes"},
        "vibecomfy.patches.resolution": {"resolution"},
    }
    constructors: set[str] = set()
    imported: dict[str, tuple[str, str]] = {}
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    if "build" not in functions:
        raise PreparedWorkflowUnavailable("workflow has no declarative build function")
    forbidden = (
        ast.Import, ast.ClassDef, ast.AsyncFunctionDef, ast.Lambda, ast.For, ast.While,
        ast.If, ast.IfExp, ast.Try, ast.Raise, ast.Await, ast.Yield, ast.YieldFrom,
        ast.Global, ast.Nonlocal, ast.Delete, ast.ListComp, ast.SetComp, ast.DictComp,
        ast.GeneratorExp, ast.NamedExpr, ast.AugAssign,
    )
    workflow_names: set[str] = set()
    node_names: set[str] = set()
    metadata_names: set[str] = set()

    def assigned_names(target: ast.AST) -> set[str]:
        if isinstance(target, ast.Name):
            return {target.id}
        if isinstance(target, (ast.Tuple, ast.List)):
            return set().union(*(assigned_names(item) for item in target.elts))
        raise PreparedWorkflowUnavailable("workflow mutates an external object")

    for node in ast.walk(tree):
        if isinstance(node, forbidden):
            raise PreparedWorkflowUnavailable("workflow has executable or untracked builder behavior")
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level or (module not in allowed_imports and not module.startswith("vibecomfy.nodes.")):
                raise PreparedWorkflowUnavailable(f"workflow imports untracked dependency {module!r}")
            for alias in node.names:
                if (alias.name == "*" or
                        (module in allowed_imports and alias.name not in allowed_imports[module]) or
                        (module.startswith("vibecomfy.nodes.") and not alias.name[:1].isupper())):
                    raise PreparedWorkflowUnavailable("workflow imports an untracked callable")
                name = alias.asname or alias.name
                constructors.add(name)
                imported[name] = (module, alias.name)
        if isinstance(node, ast.FunctionDef) and (node.decorator_list or node.name not in functions):
            raise PreparedWorkflowUnavailable("workflow has mutable or nested hooks")
        if isinstance(node, ast.Assign):
            for target in node.targets:
                assigned_names(target)
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise PreparedWorkflowUnavailable("workflow uses dynamic Python attributes")
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = set().union(*(assigned_names(target) for target in node.targets))
            if names & (constructors | functions):
                raise PreparedWorkflowUnavailable("workflow rebinds an imported constructor or helper")
            value = node.value
            if isinstance(value, ast.Dict) or (isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute) and value.func.attr == "build"):
                metadata_names.update(names)
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                origin = imported.get(value.func.id)
                if origin == ("vibecomfy.templates", "new_workflow"):
                    workflow_names.update(names)
                elif value.func.id in functions or (origin and (origin[0].startswith("vibecomfy.nodes.")
                                                             or origin == ("vibecomfy.templates", "node"))):
                    node_names.update(names)
        if isinstance(node, ast.With):
            for item in node.items:
                call = item.context_expr
                if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name)
                        or imported.get(call.func.id) != ("vibecomfy.templates", "new_workflow")
                        or not isinstance(item.optional_vars, ast.Name)):
                    raise PreparedWorkflowUnavailable("workflow has an untracked context manager")
                workflow_names.add(item.optional_vars.id)
        if isinstance(node, ast.FunctionDef):
            # A graph helper's parameters are handles/literals supplied by
            # the same closed builder, never a caller-provided callable.
            node_names.update(arg.arg for arg in (*node.args.args, *node.args.kwonlyargs))

    def metadata_receiver(value: ast.AST) -> bool:
        return ((isinstance(value, ast.Name) and value.id in metadata_names)
                or (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                    and value.func.attr == "get" and metadata_receiver(value.func.value)))

    graph_calls = {name: set() for name in functions}
    for function in (item for item in tree.body if isinstance(item, ast.FunctionDef)):
        graph_calls[function.name] = {node.func.id for node in ast.walk(function)
                                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                                     and node.func.id in functions}
    reached: set[str] = set()

    def visit(name: str, active: frozenset[str]) -> None:
        if name in active:
            raise PreparedWorkflowUnavailable("recursive graph builders require full preparation")
        reached.add(name)
        for child in graph_calls[name]:
            visit(child, active | {name})

    visit("build", frozenset())
    if reached != functions:
        raise PreparedWorkflowUnavailable("workflow declares per-job or untracked hooks")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name) and target.id in constructors | functions:
            continue
        if isinstance(target, ast.Attribute):
            receiver = target.value
            name = receiver.id if isinstance(receiver, ast.Name) else None
            if target.attr == "build" and imported.get(name) == ("vibecomfy.templates", "ReadyMetadata"):
                continue
            if target.attr == "out" and name in node_names:
                continue
            if target.attr in {"finalize", "bind", "register_input", "set_input", "add_node", "connect"} and name in workflow_names:
                continue
            if target.attr == "get" and metadata_receiver(receiver):
                continue
            if (target.attr == "apply" and isinstance(receiver, ast.Call)
                    and isinstance(receiver.func, ast.Name)
                    and imported.get(receiver.func.id) == ("vibecomfy.patches.resolution", "resolution")):
                continue
        raise PreparedWorkflowUnavailable("workflow calls an untracked builder function")
    members = {path.name: hashlib.sha256(source).hexdigest()}
    companion = path.with_suffix(".vibe.json")
    if companion.is_file():
        members[companion.name] = hashlib.sha256(companion.read_bytes()).hexdigest()
    return canonical_digest(members)


def _freeze_template(value: Any) -> Any:
    if type(value) is LiteralSlot:
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_template(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_template(item) for item in value)
    return _freeze_json(value)


def _render(value: Any, slots: tuple[Any, ...]) -> Any:
    if type(value) is LiteralSlot:
        return slots[value.index]
    if isinstance(value, Mapping):
        return {key: _render(item, slots) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_render(item, slots) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class _Input:
    name: str
    value: Any
    default: Any
    required: bool


@dataclass(frozen=True, slots=True)
class _Binding:
    node: str
    field: str
    inputs: tuple[_Input, ...]
    fallback: Any
    output_prefix: bool
    omitted: bool

    def value(self, supplied: Mapping[str, Any]) -> Any:
        chosen = self.fallback
        has_explicit = False
        for spec in self.inputs:
            value = supplied.get(spec.name, spec.value)
            explicit = value is not None and value != spec.default
            if value is None:
                value = spec.default
            if value is None and spec.required:
                raise PreparedWorkflowUnavailable(f"required input {spec.name!r} is absent")
            if has_explicit and not explicit:
                continue
            chosen = value
            has_explicit = has_explicit or explicit
        return chosen


def _private_prefix(value: Any, identity: str) -> str:
    if type(value) is not str:
        raise PreparedWorkflowUnavailable("a final output has no string filename prefix")
    normal = value.replace("\\", "/")
    if (normal.startswith("/") or "\x00" in normal or ":" in normal
            or any(part == ".." for part in normal.split("/"))):
        raise WorkflowBundleError("prepared output prefix must stay inside the output directory")
    return f"{value}_astrid_{identity}"


@dataclass(frozen=True, slots=True)
class _Template:
    key: str
    bundle: WorkflowBundle
    variant: str | None
    shape: Any
    aliases: Mapping[str, str]
    bindings: tuple[_Binding, ...]
    graph: Mapping[str, Any]
    ui: Mapping[str, Any]
    model_spellings: Mapping[tuple[str, str], Mapping[str, str]]
    diagnostics: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False)
class PreparedProjectionRecord(ApprovedProjectionRecord):
    """One issued fill; decoding its six-field value loses this authority."""

    _session: "PreparedWorkflowSession" = field(repr=False)
    _handle: str = field(repr=False)
    output_identity: str

    def assert_matches(self, bundle, variant=None, run_inputs=None,
                       api_projection=None, ui_projection=None) -> None:
        self._session.authorize(self, bundle)
        if variant != self.selected_variant:
            raise WorkflowBundleError("prepared projection variant does not match")
        if canonical_bytes(run_inputs or {}) != canonical_bytes(self.input_binding):
            raise WorkflowBundleError("prepared projection input binding does not match")
        if (api_projection is not None and canonical_bytes(api_projection) != canonical_bytes(self.api_projection)):
            raise WorkflowBundleError("prepared projection API projection does not match")
        if (ui_projection is not None and canonical_bytes(ui_projection) != canonical_bytes(self.ui_projection)):
            raise WorkflowBundleError("prepared projection UI projection does not match")

    @classmethod
    def from_dict(cls, value: Any) -> ApprovedProjectionRecord:
        return ApprovedProjectionRecord.from_dict(value)

    @classmethod
    def from_canonical_bytes(cls, value: bytes) -> ApprovedProjectionRecord:
        return ApprovedProjectionRecord.from_canonical_bytes(value)


class PreparedWorkflowSession:
    """Trusted, bounded owner of immutable templates and issued queue records.

    Only the admitted pack process calls prepare. Requests may supply a handle,
    values and current admission context, never graph bytes or slot locations.
    The owner invalidates this object when its source/target generation ends.
    """

    def __init__(self, context: PreparedWorkflowContext, *, capacity: int = 64) -> None:
        if type(context) is not PreparedWorkflowContext:
            raise WorkflowBundleError("prepared session requires an admitted context")
        if type(capacity) is not int or not 1 <= capacity <= 1024:
            raise ValueError("prepared session capacity must be between 1 and 1024")
        self.context = context
        self._capacity = capacity
        self._pid = os.getpid()
        self._nonce = uuid.uuid4().hex
        self._active = True
        self._lock = threading.RLock()
        self._templates: dict[str, _Template] = {}
        self._keys: dict[str, str] = {}
        self._issued: weakref.WeakValueDictionary[int, PreparedProjectionRecord] = weakref.WeakValueDictionary()

    def _check(self, context: PreparedWorkflowContext) -> None:
        if not self._active or self._pid != os.getpid() or context != self.context:
            raise PreparedWorkflowUnavailable("prepared workflow admission generation is no longer current")

    def invalidate(self) -> None:
        with self._lock:
            self._active = False
            self._templates.clear()
            self._keys.clear()
            self._issued.clear()

    def prepare(self, bundle: WorkflowBundle, *, inputs: Mapping[str, Any],
                schema_provider: Any = None, variant: str | None = None) -> str:
        """Compile an admitted static graph once and return an opaque handle."""
        with self._lock:
            self._check(self.context)
            if type(bundle) is not WorkflowBundle or type(bundle.workflow) is not VibeWorkflow:
                raise PreparedWorkflowUnavailable("prepared workflow requires a canonical static IR")
            bundle.require_canonical_authority("prepared workflow admission")
            _rebind_current_bundle(bundle)
            source = _source_closure(bundle)
            shape = _value_shape(inputs)
            selected_variant = bundle.workflow.default_variant if variant is None else variant
            schemas = {
                kind: schema_provider.get_schema(kind)
                for kind in sorted({node.class_type for node in bundle.workflow.nodes.values()})
            } if schema_provider is not None else {}
            key = canonical_digest([
                _FORMAT, asdict(self.context), source, bundle.revision_id,
                selected_variant, shape, schemas,
            ])
            if key in self._keys:
                return self._keys[key]
            if len(self._templates) >= self._capacity:
                raise PreparedWorkflowUnavailable("prepared workflow session is full; use full preparation")
            # Keep a detached source snapshot. The caller cannot change the
            # template by editing the original IR or companion dictionaries.
            snapshot = replace(bundle, workflow=bundle.workflow.copy(),
                               ui_sidecar=copy.deepcopy(bundle.ui_sidecar),
                               provenance=copy.deepcopy(bundle.provenance))
            workflow = snapshot.workflow
            supplied: dict[str, Any] = {}
            aliases: dict[str, str] = {}
            targets: set[tuple[str, str]] = set()
            for name, value in inputs.items():
                spec = workflow._resolve_input(name)
                if spec is None:
                    raise PreparedWorkflowUnavailable(workflow._unknown_input_message(name))
                node = workflow.nodes.get(str(spec.node_id))
                declared = str(spec.type or (_node_input_socket_type(node, spec.field) if node else "") or "").upper()
                allowed = {"INT": (int,), "INTEGER": (int,), "FLOAT": (int, float),
                           "NUMBER": (int, float), "BOOLEAN": (bool,), "BOOL": (bool,),
                           "STRING": (str,)}.get(declared)
                if getattr(spec, "media_semantics", None) in {"image", "mask", "video", "audio"}:
                    allowed = (str,)
                if value is not None and allowed is not None and type(value) not in allowed:
                    raise WorkflowBundleError(f"prepared input {name!r} must have declared type {declared}")
                aliases[name] = spec.name
                supplied[spec.name] = _thaw_json(_freeze_json(value))
                targets.add((str(spec.node_id), spec.field))
            outputs = {str(output.node_id) for output in workflow.outputs}
            if not outputs:
                raise PreparedWorkflowUnavailable("prepared workflow needs declared final outputs")
            for node_id in outputs:
                node = workflow.nodes.get(node_id)
                if node is None or node.class_type.startswith("vibecomfy."):
                    raise PreparedWorkflowUnavailable("prepared final output is not a static node")
                prefix = node.inputs.get("filename_prefix", node.widgets.get("filename_prefix"))
                if type(prefix) is not str:
                    raise PreparedWorkflowUnavailable("final output has no private filename-prefix slot")
                targets.add((node_id, "filename_prefix"))
            selected = workflow._with_selection(variant, dict(inputs)).copy()
            for node in selected.nodes.values():
                if node.class_type in schemas and schemas[node.class_type] is not None:
                    node.metadata["schema"] = copy.deepcopy(schemas[node.class_type])
            bindings: list[_Binding] = []
            for node_id, field_name in sorted(targets):
                node = selected.nodes.get(node_id)
                if node is None or node.class_type in {"GetNode", "SetNode", "Reroute"}:
                    raise PreparedWorkflowUnavailable("binding changes helper topology")
                specs = tuple(_Input(spec.name, _freeze_json(spec.value), _freeze_json(spec.default), spec.required)
                              for spec in workflow.inputs.values()
                              if str(spec.node_id) == node_id and spec.field == field_name)
                fallback = node.inputs.get(field_name, node.widgets.get(field_name))
                binding = _Binding(node_id, field_name, specs, _freeze_json(fallback),
                                   node_id in outputs and field_name == "filename_prefix", False)
                sample = binding.value(supplied)
                if type(sample) not in {str, int, float, bool, type(None)}:
                    raise PreparedWorkflowUnavailable("collection-valued inputs require full preparation")
                _value_shape(sample)
                if binding.output_prefix:
                    _private_prefix(sample, "admission")
                binding = replace(binding, omitted=_is_ui_only_prompt_input(field_name, sample))
                marker = LiteralSlot(len(bindings), sample)
                bindings.append(binding)
                fields = node.inputs if field_name in node.inputs else node.widgets
                fields[field_name] = marker
                # Preserve the compiler's ordinary public-input pass. Every
                # alias for the same target carries the same origin token;
                # the per-job selection rule above retains its precedence.
                for spec in selected.inputs.values():
                    if str(spec.node_id) == node_id and spec.field == field_name:
                        spec.value = marker
                        spec.default = sample
            graph = selected.compile("api")
            template_graph = _freeze_template(graph)
            samples = tuple(binding.value(supplied) for binding in bindings)
            sample_api = _render(template_graph, samples)
            spellings: dict[tuple[str, str], Mapping[str, str]] = {}
            diagnostics: list[Mapping[str, Any]] = []
            if schema_provider is not None:
                from vibecomfy.model_assets import _subdir_for_model_reference
                from vibecomfy.schema.validate import validate_api_against_schema, validate_api_link_shapes
                for node_id, row in sample_api.items():
                    schema = schema_provider.get_schema(row["class_type"])
                    if schema is None or getattr(schema_provider, "model_availability", None) != "target":
                        continue
                    for field_name in row["inputs"]:
                        if _subdir_for_model_reference(row["class_type"], field_name) is None:
                            continue
                        spec = schema.inputs.get(field_name)
                        choices = getattr(spec, "choices", None)
                        if choices is not None:
                            spellings[(node_id, field_name)] = MappingProxyType({
                                choice.replace("\\", "/"): choice for choice in choices if type(choice) is str
                            })
                _bind_model_spellings(sample_api, spellings)
                issues = [*validate_api_against_schema(sample_api, schema_provider, require_explicit_required=True),
                          *validate_api_link_shapes(sample_api, schema_provider)]
                for issue in issues:
                    diagnostic = {"code": str(issue.code), "message": str(issue.message), "severity": "warning"}
                    diagnostics.append(_freeze_json(diagnostic))
                    _LOG.warning("prepared workflow structural check: %s", issue.message)
            # No UI emitter is needed per fill. The admitted source's UI is
            # retained once for the same evidence shape as ordinary records.
            ui = _freeze_json(snapshot.materialize_ui(schema_provider=schema_provider))
            handle = f"{self._nonce}.{uuid.uuid4().hex}"
            self._templates[handle] = _Template(
                key, snapshot, selected_variant, shape, MappingProxyType(aliases),
                tuple(bindings), template_graph, ui, MappingProxyType(spellings), tuple(diagnostics),
            )
            self._keys[key] = handle
            return handle

    def fill(self, handle: str, inputs: Mapping[str, Any], *, attempt_id: str,
             context: PreparedWorkflowContext) -> tuple[PreparedProjectionRecord, WorkflowBundle]:
        """Bind typed values, private names, and a digest; no code or schema IO."""
        with self._lock:
            self._check(context)
            template = self._templates.get(handle) if type(handle) is str else None
            if template is None:
                raise PreparedWorkflowUnavailable("unknown or cross-session prepared workflow handle")
            if not _IDENTITY.fullmatch(attempt_id) or attempt_id.endswith(("-", ".", ":")):
                raise WorkflowBundleError("prepared attempt identity is invalid")
            if _value_shape(inputs) != template.shape:
                raise PreparedWorkflowUnavailable("prepared input type or shape changed; prepare a new template")
            supplied = {template.aliases[name]: value for name, value in inputs.items()}
            identity = f"{attempt_id}_{uuid.uuid4().hex}"
            values = []
            for binding in template.bindings:
                value = binding.value(supplied)
                if _is_ui_only_prompt_input(binding.field, value) != binding.omitted:
                    raise PreparedWorkflowUnavailable("prepared input presence changed; prepare a new template")
                if binding.output_prefix:
                    value = _private_prefix(value, identity)
                values.append(value)
            api = _render(template.graph, tuple(values))
            _bind_model_spellings(api, template.model_spellings)
            raw = canonical_bytes(api)
            if len(raw) > _MAX_PAYLOAD_BYTES:
                raise WorkflowBundleError("prepared prompt exceeds the transport byte bound")
            record = PreparedProjectionRecord(
                template.bundle.revision_id, template.variant, inputs, api, template.ui,
                hashlib.sha256(raw).hexdigest(), self, handle, identity,
            )
            self._issued[id(record)] = record
            return record, template.bundle

    def authorize(self, record: PreparedProjectionRecord, bundle: WorkflowBundle) -> dict[str, Any]:
        """Identity membership, not a digest-consistent value, grants authority."""
        with self._lock:
            self._check(self.context)
            template = self._templates.get(record._handle)
            if (type(record) is not PreparedProjectionRecord or self._issued.get(id(record)) is not record
                    or record._session is not self or template is None or bundle is not template.bundle):
                raise WorkflowBundleError("prepared projection was not issued by this live admission")
            return _thaw_json(record.api_projection)

    def key(self, handle: str) -> str:
        with self._lock:
            self._check(self.context)
            if handle not in self._templates:
                raise PreparedWorkflowUnavailable("unknown prepared workflow handle")
            return self._templates[handle].key


def _bind_model_spellings(api: dict[str, Any], spellings: Mapping[tuple[str, str], Mapping[str, str]]) -> None:
    for (node_id, field_name), choices in spellings.items():
        value = api[node_id]["inputs"].get(field_name)
        if type(value) is str:
            # A captured mapping only selects the target spelling. Presence
            # and validity are ComfyUI's decision, not a per-job local gate.
            api[node_id]["inputs"][field_name] = choices.get(value.replace("\\", "/"), value)


def prepared_queue_payload(record: PreparedProjectionRecord, bundle: WorkflowBundle) -> dict[str, Any]:
    if type(record) is not PreparedProjectionRecord:
        raise WorkflowBundleError("prepared queue requires an issued prepared projection")
    return record._session.authorize(record, bundle)
