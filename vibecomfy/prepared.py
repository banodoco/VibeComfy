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
import subprocess
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
    _freeze_json, _picker_refusal_from_spec, _raise_approval_schema_errors, _rebind_current_bundle, _thaw_json,
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
        if isinstance(node, ast.stmt) and not isinstance(node, (
                ast.ImportFrom, ast.Assign, ast.Expr, ast.FunctionDef, ast.Return, ast.With)):
            raise PreparedWorkflowUnavailable("workflow contains an untracked Python statement")
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


@dataclass(frozen=True, slots=True)
class _ObjectTemplate:
    items: tuple[tuple[str, Any], ...]


@dataclass(frozen=True, slots=True)
class _ArrayTemplate:
    items: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class _ModelSpellings:
    exact: Mapping[str, str]
    portable: Mapping[str, str | None]
    refusal: tuple[str, str, Any] | None = None


@dataclass(frozen=True, slots=True)
class _ModelSlot:
    index: int
    spellings: _ModelSpellings


def _model_spellings(choices: Any, folder: str, *, refusal: tuple[str, str, Any] | None = None) -> _ModelSpellings:
    """Capture exact witnesses and only unambiguous separator aliases."""
    from vibecomfy.model_assets import model_picker_reference

    grouped: dict[str, set[str]] = {}
    exact: dict[str, str] = {}
    for choice in choices:
        if not isinstance(choice, str):
            continue
        try:
            reference = model_picker_reference(choice, folder, allow_backslash=True)
        except ValueError:
            continue
        exact[choice] = choice
        grouped.setdefault(reference.key, set()).add(choice)
    spellings: dict[str, str | None] = {
        key: next(iter(matches)) if len(matches) == 1 else None
        for key, matches in grouped.items()
    }
    # Keep exact witnesses separate: a canonical slash spelling must not
    # overwrite an ambiguous portable key used by a third, mixed spelling.
    return _ModelSpellings(MappingProxyType(exact), MappingProxyType(spellings), refusal)


def _model_value(value: Any, spellings: _ModelSpellings) -> Any:
    if type(value) is not str:
        return value
    if value in spellings.exact:
        return spellings.exact[value]
    key = value.replace("\\", "/")
    if key not in spellings.portable and spellings.refusal is not None and value not in {"none", "None"}:
        class_type, field_name, spec = spellings.refusal
        raise WorkflowBundleError(_picker_refusal_from_spec(class_type, field_name, value, _thaw_json(spec)))
    bound = spellings.portable.get(key, value)
    if bound is None:
        raise PreparedWorkflowUnavailable("prepared model spelling is ambiguous; use full preparation")
    return bound


_DYNAMIC = (LiteralSlot, _ModelSlot, _ObjectTemplate, _ArrayTemplate)


def _freeze_template(value: Any) -> Any:
    if type(value) in (LiteralSlot, _ModelSlot):
        return value
    if isinstance(value, Mapping):
        items = tuple((key, _freeze_template(item)) for key, item in value.items())
        if any(type(item) in _DYNAMIC for _, item in items):
            return _ObjectTemplate(items)
        return MappingProxyType(dict(items))
    if isinstance(value, (list, tuple)):
        items = tuple(_freeze_template(item) for item in value)
        return _ArrayTemplate(items) if any(type(item) in _DYNAMIC for item in items) else items
    return _freeze_json(value)


def _render(value: Any, slots: tuple[Any, ...]) -> Any:
    if type(value) is LiteralSlot:
        return slots[value.index]
    if type(value) is _ModelSlot:
        return _model_value(slots[value.index], value.spellings)
    if type(value) is _ObjectTemplate:
        return MappingProxyType({key: _render(item, slots) for key, item in value.items})
    if type(value) is _ArrayTemplate:
        return tuple(_render(item, slots) for item in value.items)
    # Containers without slots were recursively frozen at admission. Sharing
    # them is safe; every path containing a job value gets a new frozen parent.
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
    media: bool

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
        raise PreparedWorkflowUnavailable("prepared output prefix must stay inside the output directory")
    result = f"{value}_astrid_{identity}"
    try:
        _filename_bound(result)
    except WorkflowBundleError as exc:
        # These are prepared transport bounds. The ordinary path retains its
        # own filename policy and must decide whether the job is admissible.
        raise PreparedWorkflowUnavailable(str(exc)) from exc
    return result


def _filename_bound(value: Any) -> None:
    """Contain a staged input/output name without inspecting the filesystem."""
    if type(value) is not str:
        raise WorkflowBundleError("prepared filename must be a string")
    normal = value.replace("\\", "/")
    if (normal.startswith("/") or "\x00" in normal or ":" in normal
            or any(part == ".." for part in normal.split("/"))):
        raise WorkflowBundleError("prepared filename must stay inside its directory")
    if len(normal.encode("utf-8")) > 4096 or any(
            len(part.encode("utf-8")) > 255 for part in normal.split("/")):
        raise WorkflowBundleError("prepared filename exceeds the finite path bound")


@dataclass(frozen=True, slots=True)
class _LiteralConstraint:
    node_id: str
    class_type: str
    name: str
    slot: Any
    spec: Any
    strict_target_choices: bool


@dataclass(frozen=True, slots=True)
class _Template:
    key: str
    bundle: WorkflowBundle
    variant: str | None
    shape: Any
    aliases: Mapping[str, str]
    bindings: tuple[_Binding, ...]
    graph: Any
    ui: Mapping[str, Any]
    model_spellings: Mapping[tuple[str, str], _ModelSpellings]
    model_slots: tuple[_ModelSlot, ...]
    literal_constraints: tuple[_LiteralConstraint, ...]
    diagnostics: tuple[Mapping[str, Any], ...]
    provenance: Mapping[str, Any]


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False)
class PreparedProjectionRecord(ApprovedProjectionRecord):
    """One issued fill; decoding its six-field value loses this authority."""

    _session: "PreparedWorkflowSession" = field(repr=False)
    _handle: str = field(repr=False)
    output_identity: str

    def __post_init__(self) -> None:
        raise WorkflowBundleError("prepared projection was not issued; use a live session fill")

    @classmethod
    def _issue(cls, template: _Template, inputs: Mapping[str, Any],
               api: Mapping[str, Any], digest: str, session: "PreparedWorkflowSession",
               handle: str, output_identity: str) -> "PreparedProjectionRecord":
        # All static data was frozen at admission. The session has rendered,
        # bounded and digested this payload; do not freeze the unchanged UI or
        # digest the same API a second time. Public construction is refused;
        # only the private registry can retain this record's issued authority.
        if cls is not PreparedProjectionRecord:
            raise WorkflowBundleError("prepared projection must have its concrete issued type")
        record = object.__new__(cls)
        for name, value in (
            ("revision_id", template.bundle.revision_id),
            ("selected_variant", template.variant),
            ("input_binding", _freeze_json(inputs)),
            ("api_projection", api),
            ("ui_projection", template.ui),
            ("api_digest", digest), ("_session", session), ("_handle", handle),
            ("output_identity", output_identity),
        ):
            object.__setattr__(record, name, value)
        return record

    def assert_matches(self, bundle, variant=None, run_inputs=None,
                       api_projection=None, ui_projection=None) -> None:
        prepared_queue_payload(self, bundle)
        if variant != self.selected_variant:
            raise WorkflowBundleError("prepared projection variant does not match")
        if canonical_bytes(run_inputs or {}) != canonical_bytes(self.input_binding):
            raise WorkflowBundleError("prepared projection input binding does not match")
        if (api_projection is not None and canonical_bytes(api_projection) != canonical_bytes(self.api_projection)):
            raise WorkflowBundleError("prepared projection API projection does not match")
        if (ui_projection is not None and canonical_bytes(ui_projection) != canonical_bytes(self.ui_projection)):
            raise WorkflowBundleError("prepared projection UI projection does not match")

    def preparation_provenance(self) -> dict[str, Any]:
        return PreparedWorkflowSession.provenance(_record_session(self), self._handle)

    @classmethod
    def from_dict(cls, value: Any) -> ApprovedProjectionRecord:
        return ApprovedProjectionRecord.from_dict(value)

    @classmethod
    def from_canonical_bytes(cls, value: bytes) -> ApprovedProjectionRecord:
        return ApprovedProjectionRecord.from_canonical_bytes(value)


@dataclass(frozen=True, slots=True)
class _IssuedRecord:
    record: weakref.ReferenceType[PreparedProjectionRecord]
    handle: str
    bundle: WorkflowBundle
    digest: str
    revision: str
    variant: str | None
    inputs: Mapping[str, Any]
    ui: Mapping[str, Any]
    output_identity: str


@dataclass(slots=True)
class _SessionAuthority:
    context: PreparedWorkflowContext
    pid: int
    compiler_identity: str
    issued: dict[int, _IssuedRecord] = field(default_factory=dict)


# Neither a record's fields nor a session-shaped object's attributes can
# recreate membership here. Weak keys/references release idle authority without
# retaining every filled graph for the lifetime of the session.
_SESSION_REGISTRY: weakref.WeakKeyDictionary[PreparedWorkflowSession, _SessionAuthority] = weakref.WeakKeyDictionary()
_SESSION_REGISTRY_LOCK = threading.RLock()


def _session_authority(session: Any) -> _SessionAuthority:
    if type(session) is not PreparedWorkflowSession:
        raise WorkflowBundleError("prepared authority requires a concrete live session")
    with _SESSION_REGISTRY_LOCK:
        authority = _SESSION_REGISTRY.get(session)
    if authority is None:
        raise PreparedWorkflowUnavailable("prepared workflow admission generation is no longer current")
    return authority


def _record_session(record: PreparedProjectionRecord) -> PreparedWorkflowSession:
    if type(record) is not PreparedProjectionRecord:
        raise WorkflowBundleError("prepared queue requires an issued prepared projection")
    session = record._session
    _session_authority(session)
    return session


def _compiler_worktree_dirty() -> bool | None:
    """Observe checkout edits once, using the same isolated Git environment."""
    from vibecomfy.runtime.session import _checkout_git_environment

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", "vibecomfy"],
            cwd=Path(__file__).parent.parent, check=False, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, timeout=5,
            env=_checkout_git_environment(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(result.stdout.strip()) if result.returncode == 0 else None


def _compiler_identity() -> str:
    """Resolve this installed compiler, never a job's claimed version."""
    from vibecomfy.runtime.session import current_source_revision

    revision = current_source_revision()
    if revision:
        dirty = _compiler_worktree_dirty()
        if dirty is not None:
            return "git:" + revision + (":dirty" if dirty else "")
    # Installed wheels have no checkout. Their own Python bytes still identify
    # the compiler, independently of the caller's contextual compiler label.
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return ("git:" + revision + ":" if revision else "") + "sha256:" + digest.hexdigest()


class PreparedWorkflowSession:
    """Trusted, bounded owner of immutable templates and issued queue records.

    Only the admitted pack process calls prepare. Requests may supply a handle,
    values and current admission context, never graph bytes or slot locations.
    The owner invalidates this object when its source/target generation ends.
    """

    def __init__(self, context: PreparedWorkflowContext, *, capacity: int = 64) -> None:
        if type(self) is not PreparedWorkflowSession:
            raise WorkflowBundleError("prepared authority requires a concrete live session")
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
        authority = _SessionAuthority(replace(context), self._pid, _compiler_identity())
        with _SESSION_REGISTRY_LOCK:
            _SESSION_REGISTRY[self] = authority

    def _check(self, context: PreparedWorkflowContext) -> None:
        authority = _session_authority(self)
        if (not self._active or authority.pid != os.getpid()
                or context != authority.context or self.context != authority.context):
            raise PreparedWorkflowUnavailable("prepared workflow admission generation is no longer current")

    def invalidate(self) -> None:
        with self._lock:
            self._active = False
            self._templates.clear()
            self._keys.clear()
            with _SESSION_REGISTRY_LOCK:
                _SESSION_REGISTRY.pop(self, None)

    def prepare(self, bundle: WorkflowBundle, *, inputs: Mapping[str, Any],
                schema_provider: Any = None, variant: str | None = None) -> str:
        """Compile an admitted static graph once and return an opaque handle."""
        with self._lock:
            PreparedWorkflowSession._check(self, self.context)
            if type(bundle) is not WorkflowBundle or type(bundle.workflow) is not VibeWorkflow:
                raise PreparedWorkflowUnavailable("prepared workflow requires a canonical static IR")
            bundle.require_canonical_authority("prepared workflow admission")
            source = _source_closure(bundle)
            try:
                current = _rebind_current_bundle(bundle)
            except WorkflowBundleError as exc:
                raise PreparedWorkflowUnavailable("prepared workflow source changed; reload before admission") from exc
            if current.revision_id != bundle.revision_id or _source_closure(bundle) != source:
                raise PreparedWorkflowUnavailable("prepared workflow source changed; reload before admission")
            shape = _value_shape(inputs)
            selected_variant = bundle.workflow.default_variant if variant is None else variant
            schemas = {
                kind: schema_provider.get_schema(kind)
                for kind in sorted({node.class_type for node in bundle.workflow.nodes.values()})
            } if schema_provider is not None else {}
            key = canonical_digest([
                _FORMAT, _session_authority(self).compiler_identity,
                asdict(self.context), source, bundle.revision_id,
                selected_variant, shape, schemas,
            ])
            if key in self._keys:
                handle = self._keys[key]
                _fill_values(self._templates[handle], inputs, "admission", scope_outputs=False)
                return handle
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
                schema = schemas.get(node.class_type) if node is not None else None
                constraint = schema.inputs.get(spec.field) if schema is not None else None
                # These values select a different payload field set. Keep
                # such controllers on the ordinary full path; a fixed graph
                # cannot promise literal-only validation for their changes.
                if (getattr(constraint, "dynamic_fields", None)
                        or (node is not None and (node.class_type, spec.field) in {
                            ("LTXVImgToVideoInplaceKJ", "num_images"),
                            ("ImageConcatMulti", "inputcount"),
                            ("SimpleCalculator", "variables"),
                            ("SimpleCalculatorKJ", "variables"),
                        })):
                    raise PreparedWorkflowUnavailable("dynamic schema controller requires full preparation")
                declared = str(spec.type or (_node_input_socket_type(node, spec.field) if node else "") or "").upper()
                allowed = {"INT": (int,), "INTEGER": (int,), "FLOAT": (int, float),
                           "NUMBER": (int, float), "BOOLEAN": (bool,), "BOOL": (bool,),
                           "STRING": (str,)}.get(declared)
                if getattr(spec, "media_semantics", None) in {"image", "mask", "video", "audio"}:
                    allowed = (str,)
                if value is not None and allowed is not None and type(value) not in allowed:
                    raise PreparedWorkflowUnavailable(f"prepared input {name!r} must have declared type {declared}")
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
            try:
                selected = workflow._with_selection(variant, dict(inputs)).copy()
            except Exception as exc:
                raise WorkflowBundleError(
                    f"workflow API projection failed: {type(exc).__name__}: {exc}"
                ) from exc
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
                media = any(str(spec.node_id) == node_id and spec.field == field_name
                            and spec.media_semantics in {"image", "mask", "video", "audio"}
                            for spec in workflow.inputs.values())
                binding = _Binding(node_id, field_name, specs, _freeze_json(fallback),
                                   node_id in outputs and field_name == "filename_prefix", False, media)
                sample = binding.value(supplied)
                if type(sample) not in {str, int, float, bool, type(None)}:
                    raise PreparedWorkflowUnavailable("collection-valued inputs require full preparation")
                _value_shape(sample)
                if binding.output_prefix:
                    _private_prefix(sample, "admission")
                if binding.media:
                    _filename_bound(sample)
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
            try:
                graph = selected.compile("api")
            except Exception as exc:
                raise WorkflowBundleError(
                    f"workflow API projection failed: {type(exc).__name__}: {exc}"
                ) from exc
            for output in workflow.outputs:
                row = graph.get(str(output.node_id))
                if row is None or row["class_type"] != output.output_type:
                    raise PreparedWorkflowUnavailable("prepared graph does not preserve its declared final sink")
            template_graph = _freeze_template(graph)
            samples = tuple(binding.value(supplied) for binding in bindings)
            sample_api = _thaw_json(_render(template_graph, samples))
            spellings: dict[tuple[str, str], _ModelSpellings] = {}
            api_schemas: dict[str, Any] = {}
            diagnostics: list[Mapping[str, Any]] = []
            if schema_provider is not None:
                from vibecomfy.model_assets import _subdir_for_model_reference
                from vibecomfy.schema.provider import TargetSchemaProvider
                from vibecomfy.schema.validate import validate_api_against_schema, validate_api_link_shapes
                for node_id, row in sample_api.items():
                    schema = schema_provider.get_schema(row["class_type"])
                    api_schemas[node_id] = schema
                    if schema is None or getattr(schema_provider, "model_availability", None) != "target":
                        continue
                    for field_name in row["inputs"]:
                        folder = _subdir_for_model_reference(row["class_type"], field_name)
                        if folder is None:
                            continue
                        spec = schema.inputs.get(field_name)
                        choices = getattr(spec, "choices", None)
                        if choices is not None:
                            refusal = None
                            if isinstance(schema_provider, TargetSchemaProvider):
                                refusal = (row["class_type"], field_name, _freeze_json(
                                    schema_provider.advertised_input_spec(row["class_type"], field_name),
                                ))
                            spellings[(node_id, field_name)] = _model_spellings(choices, folder, refusal=refusal)
                _bind_model_spellings(sample_api, spellings)
                try:
                    issues = [*validate_api_against_schema(sample_api, schema_provider, require_explicit_required=True),
                              *validate_api_link_shapes(sample_api, schema_provider)]
                except Exception as exc:
                    raise WorkflowBundleError(
                        f"local schema validation failed: {type(exc).__name__}: {exc}"
                    ) from exc
                # Full approval's errors also block admission. Its warnings
                # remain diagnostics; only mutable literal constraints need
                # to be checked again when filling the fixed graph.
                _raise_approval_schema_errors(issues)
                for issue in issues:
                    diagnostic = {"code": str(issue.code), "message": str(issue.message), "severity": "warning"}
                    diagnostics.append(_freeze_json(diagnostic))
                    _LOG.warning("prepared workflow structural check: %s", issue.message)
            model_slots = []
            for (node_id, field_name), choices in spellings.items():
                value = graph[node_id]["inputs"].get(field_name)
                if type(value) is LiteralSlot:
                    slot = _ModelSlot(value.index, choices)
                    model_slots.append(slot)
                    graph[node_id]["inputs"][field_name] = slot
                elif type(value) is str:
                    graph[node_id]["inputs"][field_name] = _model_value(value, choices)
            template_graph = _freeze_template(graph)
            constraints = []
            for node_id, row in graph.items():
                schema = api_schemas.get(node_id)
                if schema is None:
                    continue
                for name in sorted(row["inputs"]):
                    slot = row["inputs"][name]
                    spec = schema.inputs.get(name)
                    if type(slot) in (LiteralSlot, _ModelSlot) and spec is not None:
                        constraints.append(_LiteralConstraint(
                            str(node_id), row["class_type"], name, slot, copy.deepcopy(spec),
                            bool(getattr(schema_provider, "requires_fresh_target", False)),
                        ))
            # No UI emitter is needed per fill. The admitted source's UI is
            # retained once for the same evidence shape as ordinary records.
            ui = _freeze_json(snapshot.materialize_ui(schema_provider=schema_provider))
            handle = f"{self._nonce}.{uuid.uuid4().hex}"
            self._templates[handle] = _Template(
                key, snapshot, selected_variant, shape, MappingProxyType(aliases),
                tuple(bindings), template_graph, ui, MappingProxyType(spellings), tuple(model_slots),
                tuple(constraints), tuple(diagnostics),
                _freeze_json({
                    "validation": "prepared-at-admission", "authority": "ComfyUI",
                    "format": _FORMAT, "template_key": key, "context_digest": self.context.digest,
                    "compiler_identity": _session_authority(self).compiler_identity,
                    "source_closure_digest": source, "schema_digest": self.context.schema_digest,
                    "target_identity": self.context.target_identity,
                    "target_generation": self.context.target_generation,
                    "structural_diagnostics": diagnostics,
                }),
            )
            self._keys[key] = handle
            return handle

    def accepts(self, handle: str, inputs: Mapping[str, Any], *, attempt_id: str = "admission") -> bool:
        """Check fill compatibility before media upload; no source/schema IO.

        A changed shape, value presence, ambiguous captured model spelling or
        prepared-only prefix bound requires the full path. Stale authority
        and full-compiler schema errors still refuse before any upload.
        """
        with self._lock:
            PreparedWorkflowSession._check(self, self.context)
            template = self._templates.get(handle) if type(handle) is str else None
            if template is None:
                return False
            try:
                _fill_values(template, inputs, attempt_id + "_" + "0" * 32)
            except PreparedWorkflowUnavailable:
                return False
            return True

    def fill(self, handle: str, inputs: Mapping[str, Any], *, attempt_id: str,
             context: PreparedWorkflowContext) -> tuple[PreparedProjectionRecord, WorkflowBundle]:
        """Bind typed values, private names, and a digest; no code or schema IO."""
        with self._lock:
            PreparedWorkflowSession._check(self, context)
            template = self._templates.get(handle) if type(handle) is str else None
            if template is None:
                raise PreparedWorkflowUnavailable("unknown or cross-session prepared workflow handle")
            if (type(attempt_id) is not str or not _IDENTITY.fullmatch(attempt_id)
                    or attempt_id.endswith(("-", ".", ":"))):
                raise WorkflowBundleError("prepared attempt identity is invalid")
            identity = f"{attempt_id}_{uuid.uuid4().hex}"
            api = _render(template.graph, _fill_values(template, inputs, identity))
            raw = canonical_bytes(api)
            if len(raw) > _MAX_PAYLOAD_BYTES:
                raise WorkflowBundleError("prepared prompt exceeds the transport byte bound")
            record = PreparedProjectionRecord._issue(
                template, inputs, api, hashlib.sha256(raw).hexdigest(), self, handle, identity,
            )
            authority = _session_authority(self)
            record_id = id(record)

            def forget(reference: weakref.ReferenceType[PreparedProjectionRecord]) -> None:
                with _SESSION_REGISTRY_LOCK:
                    issued = authority.issued.get(record_id)
                    if issued is not None and issued.record is reference:
                        authority.issued.pop(record_id)

            issued = _IssuedRecord(
                weakref.ref(record, forget), handle, template.bundle, record.api_digest,
                record.revision_id, record.selected_variant, record.input_binding,
                record.ui_projection, identity,
            )
            with _SESSION_REGISTRY_LOCK:
                authority.issued[record_id] = issued
            return record, template.bundle

    def authorize(self, record: PreparedProjectionRecord, bundle: WorkflowBundle) -> dict[str, Any]:
        """Recheck issued identity and digest on the exact detached payload."""
        authority = _session_authority(self)
        with self._lock:
            PreparedWorkflowSession._check(self, self.context)
            with _SESSION_REGISTRY_LOCK:
                issued = authority.issued.get(id(record))
            if (type(record) is not PreparedProjectionRecord or issued is None
                    or issued.record() is not record or record._session is not self
                    or record._handle != issued.handle or bundle is not issued.bundle
                    or issued.handle not in self._templates):
                raise WorkflowBundleError("prepared projection was not issued by this live admission")
            if (record.api_digest != issued.digest or record.revision_id != issued.revision
                    or record.selected_variant != issued.variant or record.input_binding is not issued.inputs
                    or record.ui_projection is not issued.ui or record.output_identity != issued.output_identity):
                raise WorkflowBundleError("prepared projection differs from its issued record")
            # Detach first and hash exactly the object returned to the transport.
            # This also prevents a mutable or stateful replacement Mapping from
            # providing one graph for the digest and another for submission.
            payload = _thaw_json(record.api_projection)
            if not isinstance(payload, dict) or canonical_digest(payload) != issued.digest:
                raise WorkflowBundleError("prepared projection digest does not match its issued digest")
            return payload

    def key(self, handle: str) -> str:
        with self._lock:
            PreparedWorkflowSession._check(self, self.context)
            if handle not in self._templates:
                raise PreparedWorkflowUnavailable("unknown prepared workflow handle")
            return self._templates[handle].key

    def require_target(self, target_identity: str | None) -> None:
        _session_authority(self)
        with self._lock:
            PreparedWorkflowSession._check(self, self.context)
            if (type(target_identity) is not str or
                    target_identity.rstrip("/") != self.context.target_identity.rstrip("/")):
                raise PreparedWorkflowUnavailable("prepared workflow belongs to another target")

    def provenance(self, handle: str) -> dict[str, Any]:
        with self._lock:
            PreparedWorkflowSession._check(self, self.context)
            template = self._templates.get(handle)
            if template is None:
                raise PreparedWorkflowUnavailable("unknown prepared workflow handle")
            return _thaw_json(template.provenance)


def _fill_values(template: _Template, inputs: Mapping[str, Any], identity: str, *,
                 scope_outputs: bool = True) -> tuple[Any, ...]:
    if _value_shape(inputs) != template.shape:
        raise PreparedWorkflowUnavailable("prepared input type or shape changed; prepare a new template")
    supplied = {template.aliases[name]: value for name, value in inputs.items()}
    values = []
    for binding in template.bindings:
        value = binding.value(supplied)
        if _is_ui_only_prompt_input(binding.field, value) != binding.omitted:
            raise PreparedWorkflowUnavailable("prepared input presence changed; prepare a new template")
        if binding.output_prefix:
            scoped = _private_prefix(value, identity)
            if scope_outputs:
                value = scoped
        if binding.media:
            _filename_bound(value)
        values.append(value)
    for slot in template.model_slots:
        _model_value(values[slot.index], slot.spellings)
    filled = tuple(values)
    from vibecomfy.schema.validate import validate_literal_against_schema

    issues = []
    try:
        for constraint in template.literal_constraints:
            issues.extend(validate_literal_against_schema(
                node_id=constraint.node_id, class_type=constraint.class_type,
                name=constraint.name, value=_render(constraint.slot, filled), spec=constraint.spec,
                strict_target_choices=constraint.strict_target_choices,
            ))
    except Exception as exc:
        raise WorkflowBundleError(
            f"local schema validation failed: {type(exc).__name__}: {exc}"
        ) from exc
    _raise_approval_schema_errors(issues)
    return filled


def _bind_model_spellings(api: dict[str, Any], spellings: Mapping[tuple[str, str], _ModelSpellings]) -> None:
    for (node_id, field_name), choices in spellings.items():
        value = api[node_id]["inputs"].get(field_name)
        if type(value) is str:
            # A captured mapping only selects the target spelling. Literal
            # validity is handled separately by the shared approval rules.
            api[node_id]["inputs"][field_name] = _model_value(value, choices)


def prepared_queue_payload(record: PreparedProjectionRecord, bundle: WorkflowBundle) -> dict[str, Any]:
    return PreparedWorkflowSession.authorize(_record_session(record), record, bundle)


def require_prepared_target(record: PreparedProjectionRecord, target_identity: str | None) -> None:
    PreparedWorkflowSession.require_target(_record_session(record), target_identity)
