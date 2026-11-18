"""Lead LS-4 rework: cached fills preserve full approval's local refusals."""
from __future__ import annotations

import copy
from pathlib import Path
import subprocess

import pytest

from tests.test_prepared_workflow import context, tiny
from vibecomfy.prepared import PreparedWorkflowSession
from vibecomfy.prepared import PreparedWorkflowUnavailable
from vibecomfy.schema.provider import TargetSchemaProvider
from vibecomfy.testing.canonical import canonical_bytes
from vibecomfy.workflow import VibeEdge, VibeNode, VibeWorkflow, WorkflowCompileError
from vibecomfy.workflow_bundle import WorkflowBundle, WorkflowBundleError, load_bundle


def constrained():
    bundle, provider = tiny()
    observed = copy.deepcopy(provider._object_info)
    observed["SeedImage"]["input"]["required"]["seed"] = ["INT", {"min": 0, "max": 10}]
    observed["SeedImage"]["input"]["required"]["text"] = [["a", "b"]]
    provider = TargetSchemaProvider.from_object_info(observed, server_url=context().target_identity)
    bundle.workflow.nodes["1"].inputs.update(seed=7, text="a")
    bundle.workflow.set_input("text", "a")
    for node in bundle.workflow.nodes.values():
        node.metadata["schema"] = provider.get_schema(node.class_type)
    return load_bundle(bundle.workflow), provider


INVALID = [
    pytest.param({"seed": -1, "text": "a"}, id="below-minimum"),
    pytest.param({"seed": 999, "text": "a"}, id="above-maximum"),
    pytest.param({"seed": 7, "text": "zzz"}, id="undeclared-choice"),
    pytest.param({"seed": 999, "text": "zzz"}, id="range-and-choice-order"),
]


@pytest.mark.parametrize("values", INVALID)
def test_admission_refuses_same_schema_error_as_full_compile(values):
    bundle, provider = constrained()
    with pytest.raises(WorkflowBundleError) as full:
        bundle.compile(run_inputs=values, schema_provider=provider)
    session = PreparedWorkflowSession(context())
    with pytest.raises(WorkflowBundleError) as prepared:
        session.prepare(bundle, inputs=values, schema_provider=provider)
    assert type(prepared.value) is type(full.value)
    assert str(prepared.value) == str(full.value)


@pytest.mark.parametrize("values", INVALID)
def test_cached_admission_rechecks_new_values_against_full_compile(values):
    bundle, provider = constrained()
    session = PreparedWorkflowSession(context())
    session.prepare(bundle, inputs={"seed": 7, "text": "a"}, schema_provider=provider)
    with pytest.raises(WorkflowBundleError) as full:
        bundle.compile(run_inputs=values, schema_provider=provider)
    with pytest.raises(WorkflowBundleError) as prepared:
        session.prepare(bundle, inputs=values, schema_provider=provider)
    assert type(prepared.value) is type(full.value)
    assert str(prepared.value) == str(full.value)


@pytest.mark.parametrize("values", INVALID)
@pytest.mark.parametrize("entry", ["accepts", "fill"])
def test_cached_values_refuse_same_schema_error_without_reentering_compiler(values, entry, monkeypatch):
    bundle, provider = constrained()
    with pytest.raises(WorkflowBundleError) as full:
        bundle.compile(run_inputs=values, schema_provider=provider)
    session = PreparedWorkflowSession(context())
    handle = session.prepare(bundle, inputs={"seed": 7, "text": "a"}, schema_provider=provider)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("fill reentered source, compiler or schema provider")

    monkeypatch.setattr(VibeWorkflow, "compile", forbidden)
    monkeypatch.setattr(WorkflowBundle, "compile", forbidden)
    monkeypatch.setattr(WorkflowBundle, "materialize_ui", forbidden)
    monkeypatch.setattr(provider, "get_schema", forbidden)
    monkeypatch.setattr(provider, "object_info", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    with pytest.raises(WorkflowBundleError) as prepared:
        if entry == "accepts":
            session.accepts(handle, values)
        else:
            session.fill(handle, values, attempt_id="attempt", context=context())
    assert type(prepared.value) is type(full.value)
    assert str(prepared.value) == str(full.value)


@pytest.mark.parametrize("values", [{"seed": 0, "text": "a"}, {"seed": 10, "text": "b"}])
def test_cached_constraints_preserve_inclusive_boundaries_and_approved_bytes(values):
    from tests.test_prepared_workflow import reference_api

    bundle, provider = constrained()
    session = PreparedWorkflowSession(context())
    handle = session.prepare(bundle, inputs={"seed": 7, "text": "a"}, schema_provider=provider)
    assert session.accepts(handle, values)
    record, _ = session.fill(handle, values, attempt_id="attempt", context=context())
    workflow, bindings = reference_api(bundle, values, record.output_identity)
    full = load_bundle(workflow).compile(run_inputs=bindings, schema_provider=provider)
    assert canonical_bytes(record.api_projection) == canonical_bytes(full.api_projection)
    assert record.api_digest == full.api_digest


def test_admission_wraps_public_input_compile_error_exactly_like_full_compile():
    bundle, provider = tiny()
    bundle.workflow.inputs["seed"].type = "STRING"
    bundle = load_bundle(bundle.workflow)
    values = {"seed": "seven"}
    with pytest.raises(WorkflowBundleError) as full:
        bundle.compile(run_inputs=values, schema_provider=provider)
    assert isinstance(full.value.__cause__, WorkflowCompileError)
    with pytest.raises(WorkflowBundleError) as prepared:
        PreparedWorkflowSession(context()).prepare(bundle, inputs=values, schema_provider=provider)
    assert type(prepared.value) is type(full.value)
    assert str(prepared.value) == str(full.value)
    assert type(prepared.value.__cause__) is type(full.value.__cause__)


@pytest.mark.parametrize("prefix", [pytest.param("run:1", id="colon"), pytest.param("x" * 300, id="long-component")])
def test_prepared_only_prefix_bounds_choose_full_path(prefix):
    bundle, provider = tiny()
    session = PreparedWorkflowSession(context())
    handle = session.prepare(bundle, inputs={"prefix": "safe"}, schema_provider=provider)
    full = bundle.compile(run_inputs={"prefix": prefix}, schema_provider=provider)
    assert full.api_projection["2"]["inputs"]["filename_prefix"] == prefix
    assert not session.accepts(handle, {"prefix": prefix})
    with pytest.raises(WorkflowBundleError):
        session.fill(handle, {"prefix": prefix}, attempt_id="attempt", context=context())


def test_compiler_identity_distinguishes_dirty_source_at_the_same_commit(tmp_path, monkeypatch):
    from vibecomfy import prepared
    from vibecomfy.runtime import session as runtime_session

    root = tmp_path / "checkout"
    source = root / "vibecomfy" / "prepared.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 'committed'\n")

    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, text=True, capture_output=True).stdout.strip()

    git("init")
    git("add", "vibecomfy/prepared.py")
    git("-c", "user.name=LS4 proof", "-c", "user.email=ls4-proof@example.invalid", "commit", "-m", "fixture")
    revision = git("rev-parse", "HEAD")
    monkeypatch.setattr(prepared, "__file__", str(source))
    monkeypatch.setattr(runtime_session, "current_source_revision", lambda: revision)
    clean = prepared._compiler_identity()
    source.write_text("value = 'uncommitted'\n")
    assert git("rev-parse", "HEAD") == revision
    dirty = prepared._compiler_identity()
    assert dirty != clean
    assert revision in clean and revision in dirty


def test_dynamic_count_controller_keeps_full_preparation():
    bundle, provider = tiny()
    observed = copy.deepcopy(provider._object_info)
    observed["ImageConcatMulti"] = {
        "input": {"required": {"inputcount": ["INT", {"min": 2, "max": 4}], "image_1": ["IMAGE"], "image_2": ["IMAGE"]}},
        "output": ["IMAGE"],
    }
    provider = TargetSchemaProvider.from_object_info(observed, server_url=context().target_identity)
    workflow = bundle.workflow
    workflow.nodes["3"] = VibeNode(
        "3", "ImageConcatMulti", uid="concat", inputs={"inputcount": 2},
        native_input_names=["inputcount", "image_1", "image_2"], native_input_types=["INT", "IMAGE", "IMAGE"],
        native_output_names=["IMAGE"], native_output_types=["IMAGE"],
    )
    workflow.edges = [VibeEdge("1", "0", "3", "image_1"), VibeEdge("1", "0", "3", "image_2"), VibeEdge("3", "0", "2", "images")]
    workflow.register_input("count", "3", "inputcount", 2, type="INT")
    for node in workflow.nodes.values():
        node.metadata["schema"] = provider.get_schema(node.class_type)
    bundle = load_bundle(workflow)
    assert bundle.compile(run_inputs={"count": 2}, schema_provider=provider)
    with pytest.raises(WorkflowBundleError, match="missing dynamic input image_3"):
        bundle.compile(run_inputs={"count": 3}, schema_provider=provider)
    with pytest.raises(PreparedWorkflowUnavailable, match="dynamic schema controller"):
        PreparedWorkflowSession(context()).prepare(bundle, inputs={"count": 2}, schema_provider=provider)


def test_observed_dynamic_choice_controller_keeps_full_preparation():
    from dataclasses import replace

    bundle, provider = tiny()
    schema = provider.get_schema("SeedImage")
    spec = replace(schema.inputs["text"], choices=["original", "compact"],
                   dynamic_fields={"original": ("detail",), "compact": ()})
    schema = replace(schema, inputs={**schema.inputs, "text": spec})
    provider._schemas["SeedImage"] = schema
    bundle.workflow.nodes["1"].metadata["schema"] = schema
    bundle.workflow.nodes["1"].inputs["detail"] = "kept"
    bundle.workflow.nodes["1"].native_input_names.append("detail")
    bundle.workflow.nodes["1"].native_input_types.append("STRING")
    bundle = load_bundle(bundle.workflow)
    assert bundle.compile(run_inputs={"text": "original"}, schema_provider=provider)
    with pytest.raises(WorkflowBundleError, match="unknown input detail"):
        bundle.compile(run_inputs={"text": "compact"}, schema_provider=provider)
    with pytest.raises(PreparedWorkflowUnavailable, match="dynamic schema controller"):
        PreparedWorkflowSession(context()).prepare(bundle, inputs={"text": "original"}, schema_provider=provider)
