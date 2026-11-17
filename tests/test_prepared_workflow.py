"""Plan 55 LS-4: a preparation is authority; a serialized record is only data."""
from __future__ import annotations

import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import statistics
import time

import pytest

from vibecomfy.prepared import (
    PreparedProjectionRecord, PreparedWorkflowContext, PreparedWorkflowSession,
    PreparedWorkflowUnavailable,
)
from vibecomfy.runtime.execution import authorized_queue_payload, queue_server_prompt, queue_embedded_prompt
from vibecomfy.schema.provider import TargetSchemaProvider
from vibecomfy.security.provenance import Provenance
from vibecomfy.testing.canonical import canonical_bytes
from vibecomfy.workflow import VibeEdge, VibeNode, VibeOutput, VibeWorkflow, WorkflowSource
from vibecomfy.workflow_bundle import ApprovedProjectionRecord, WorkflowBundleError, emit_bundle, load_bundle


def context(**changes):
    values = dict(source_identity="admitted-pack-digest", capability_identity="capability-digest",
                  authority_scope="realm/project", settings_generation="settings-1",
                  installation_generation="installation-1", target_identity="http://127.0.0.1:8188",
                  target_generation="pair-1", schema_digest="schema-1", compiler_identity="pinned-vibe")
    values.update(changes)
    return PreparedWorkflowContext(**values)


def tiny():
    provider = TargetSchemaProvider.from_object_info({
        "SeedImage": {"input": {"required": {"seed": ["INT", {}], "text": ["STRING", {}]}},
                      "output": ["IMAGE"], "output_name": ["IMAGE"]},
        "SaveImage": {"input": {"required": {"images": ["IMAGE"], "filename_prefix": ["STRING", {}]}},
                      "output": [], "output_node": True},
    }, server_url="http://127.0.0.1:8188", model_availability="target")
    wf = VibeWorkflow("prepared-fixture", WorkflowSource("prepared-fixture"))
    wf.nodes = {
        "1": VibeNode("1", "SeedImage", inputs={"seed": 7, "text": "original"}, uid="seed-image",
                      native_input_names=["seed", "text"], native_input_types=["INT", "STRING"],
                      native_output_names=["IMAGE"], native_output_types=["IMAGE"]),
        "2": VibeNode("2", "SaveImage", inputs={"filename_prefix": "fixture"}, uid="save-image",
                      native_input_names=["images", "filename_prefix"], native_input_types=["IMAGE", "STRING"],
                      native_output_names=[], native_output_types=[]),
    }
    wf.edges = [VibeEdge("1", "0", "2", "images")]
    wf.outputs = [VibeOutput("2", "SaveImage")]
    for node in wf.nodes.values():
        node.metadata["schema"] = provider.get_schema(node.class_type)
    wf.register_input("seed", "1", "seed", 7, type="INT")
    wf.register_input("text", "1", "text", "original", type="STRING")
    wf.register_input("prefix", "2", "filename_prefix", "fixture", type="STRING")
    return load_bundle(wf), provider


def reference_api(bundle, values, output_identity):
    wf = bundle.workflow.copy()
    # This is the current full path's declared-output transform, including
    # rebinding a public filename prefix so compilation cannot undo it.
    for output in wf.outputs:
        node = wf.nodes[output.node_id]
        fields = node.inputs if "filename_prefix" in node.inputs else node.widgets
        prefix = fields["filename_prefix"]
        for name, value in values.items():
            spec = wf._resolve_input(name)
            if str(spec.node_id) == str(output.node_id) and spec.field == "filename_prefix":
                prefix = value
        fields["filename_prefix"] = f"{prefix}_astrid_{output_identity}"
        for spec in wf.inputs.values():
            if str(spec.node_id) == str(output.node_id) and spec.field == "filename_prefix":
                wf.set_input(spec.name, fields["filename_prefix"])
    bindings = dict(values)
    for name in list(bindings):
        spec = wf._resolve_input(name)
        if spec.field == "filename_prefix" and str(spec.node_id) in {str(o.node_id) for o in wf.outputs}:
            bindings[name] = spec.value
    return wf, bindings


def test_fill_equals_full_approval_and_does_not_share_prefix():
    bundle, provider = tiny()
    ctx = context()
    session = PreparedWorkflowSession(ctx)
    values = {"seed": 13, "text": "snow, café 🌨", "prefix": "user/image"}
    handle = session.prepare(bundle, inputs=values, schema_provider=provider)
    prefixes = set()
    for index in range(20):
        values = {**values, "seed": index, "text": "雪" * index}
        record, frozen = session.fill(handle, values, attempt_id="same-attempt", context=ctx)
        wf, bindings = reference_api(bundle, values, record.output_identity)
        full = load_bundle(wf).compile(run_inputs=bindings, schema_provider=provider)
        assert canonical_bytes(record.api_projection) == canonical_bytes(full.api_projection)
        prefix = record.api_projection["2"]["inputs"]["filename_prefix"]
        assert prefix not in prefixes
        prefixes.add(prefix)
        assert authorized_queue_payload(record, frozen) == full.to_dict()["api_projection"]
    assert bundle.workflow.nodes["2"].inputs["filename_prefix"] == "fixture"


def test_fill_and_queue_do_no_compile_source_read_emission_or_schema_validation(monkeypatch):
    bundle, provider = tiny()
    ctx = context()
    session = PreparedWorkflowSession(ctx)
    values = {"seed": 13, "text": "a"}
    handle = session.prepare(bundle, inputs=values, schema_provider=provider)
    def forbidden(*args, **kwargs):
        raise AssertionError("per-job source/compile/schema work")
    monkeypatch.setattr(VibeWorkflow, "compile", forbidden)
    monkeypatch.setattr(type(bundle), "compile", forbidden)
    monkeypatch.setattr(type(bundle), "materialize_ui", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(provider, "get_schema", forbidden)
    import vibecomfy.schema.validate as validation
    monkeypatch.setattr(validation, "validate_api_against_schema", forbidden)
    monkeypatch.setattr(validation, "validate_api_link_shapes", forbidden)
    record, frozen = session.fill(handle, values, attempt_id="attempt-1", context=ctx)
    payloads = []
    class Client:
        server_url = ctx.target_identity
        async def _post_prompt(self, payload):
            payloads.append(payload)
            return {"prompt_id": "our-prompt", "node_errors": {}}
    queued = asyncio.run(queue_server_prompt(record, frozen, client=Client()))
    assert queued.prompt_id == "our-prompt"
    assert payloads[0]["1"]["inputs"]["seed"] == 13
    assert record.api_digest == __import__("hashlib").sha256(canonical_bytes(payloads[0])).hexdigest()


def test_forged_copied_decoded_and_cross_session_records_never_gain_authority():
    bundle, provider = tiny()
    ctx = context()
    session = PreparedWorkflowSession(ctx)
    values = {"seed": 13}
    handle = session.prepare(bundle, inputs=values, schema_provider=provider)
    record, frozen = session.fill(handle, values, attempt_id="attempt-1", context=ctx)
    altered = record.to_dict()
    altered["api_projection"]["1"]["inputs"]["seed"] = 999
    from vibecomfy.testing.canonical import canonical_digest
    forged = replace(record, api_projection=altered["api_projection"], api_digest=canonical_digest(altered["api_projection"]))
    for candidate in [forged, copy.copy(record), replace(record)]:
        with pytest.raises(WorkflowBundleError, match="not issued"):
            authorized_queue_payload(candidate, frozen)
    decoded = PreparedProjectionRecord.from_canonical_bytes(record.to_canonical_bytes())
    assert type(decoded) is ApprovedProjectionRecord
    with pytest.raises(WorkflowBundleError, match="current bundle"):
        authorized_queue_payload(decoded, frozen)
    with pytest.raises(PreparedWorkflowUnavailable, match="cross-session"):
        PreparedWorkflowSession(ctx).fill(handle, values, attempt_id="attempt-2", context=ctx)
    with pytest.raises(WorkflowBundleError, match="not issued"):
        authorized_queue_payload(record, bundle)


def test_shape_variant_schema_and_context_are_keyed():
    bundle, provider = tiny()
    bundle.workflow.variants = {"first": {}, "second": {"seed-image.text": "variant"}}
    bundle = load_bundle(bundle.workflow)
    ctx = context()
    session = PreparedWorkflowSession(ctx)
    first = session.prepare(bundle, inputs={"seed": 1}, schema_provider=provider, variant="first")
    assert session.prepare(bundle, inputs={"seed": 2}, schema_provider=provider, variant="first") == first
    second = session.prepare(bundle, inputs={"seed": 1}, schema_provider=provider, variant="second")
    shaped = session.prepare(bundle, inputs={"seed": 1, "text": "present"}, schema_provider=provider, variant="first")
    assert len({session.key(first), session.key(second), session.key(shaped)}) == 3
    changed_provider = copy.deepcopy(provider)
    changed_provider._object_info["SeedImage"]["input"]["required"]["seed"][1]["max"] = 999
    changed_provider._schemas = None
    # A separate schema provider represents a fresh observed schema.
    changed_provider = TargetSchemaProvider.from_object_info(changed_provider._object_info,
        server_url=ctx.target_identity, model_availability="target")
    schema_changed = session.prepare(bundle, inputs={"seed": 1}, schema_provider=changed_provider, variant="first")
    assert session.key(schema_changed) != session.key(first)
    for field_name in ctx.__dataclass_fields__:
        with pytest.raises(PreparedWorkflowUnavailable, match="generation"):
            session.fill(first, {"seed": 1}, attempt_id="attempt", context=replace(ctx, **{field_name: "changed"}))
    record, frozen = session.fill(first, {"seed": 1}, attempt_id="attempt", context=ctx)
    session.invalidate()
    with pytest.raises(PreparedWorkflowUnavailable, match="generation"):
        authorized_queue_payload(record, frozen)


@pytest.mark.parametrize("values", [{"seed": True}, {"seed": "13"}, {"seed": float("nan")}])
def test_declared_slot_types_and_finite_transport_values(values):
    bundle, provider = tiny()
    with pytest.raises(WorkflowBundleError):
        PreparedWorkflowSession(context()).prepare(bundle, inputs=values, schema_provider=provider)


def test_concurrent_fills_are_isolated_and_inputs_cannot_mutate_the_prompt():
    bundle, provider = tiny()
    ctx = context()
    session = PreparedWorkflowSession(ctx)
    handle = session.prepare(bundle, inputs={"seed": 1, "text": "a"}, schema_provider=provider)
    def fill(index):
        values = {"seed": index, "text": f"text-{index}"}
        record, frozen = session.fill(handle, values, attempt_id="attempt", context=ctx)
        values["seed"] = 0
        return record, authorized_queue_payload(record, frozen)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fill, range(32)))
    assert [api["1"]["inputs"]["seed"] for _, api in results] == list(range(32))
    assert len({api["2"]["inputs"]["filename_prefix"] for _, api in results}) == 32
    with pytest.raises(TypeError):
        results[0][0].api_projection["1"]["inputs"]["seed"] = 42


def test_prefix_containment_is_separate_from_comfy_schema_authority():
    bundle, provider = tiny()
    session = PreparedWorkflowSession(context())
    handle = session.prepare(bundle, inputs={"prefix": "safe"}, schema_provider=provider)
    for prefix in ("../escape", "/absolute", "C:\\outside", "sub/../../outside", "bad\x00name"):
        with pytest.raises(WorkflowBundleError, match="output directory"):
            session.fill(handle, {"prefix": prefix}, attempt_id="attempt", context=context())


def test_fill_latency_under_five_milliseconds(capsys):
    bundle, provider = tiny()
    ctx = context()
    session = PreparedWorkflowSession(ctx)
    handle = session.prepare(bundle, inputs={"seed": 1, "text": "a"}, schema_provider=provider)
    elapsed = []
    for index in range(1000):
        start = time.perf_counter_ns()
        record, frozen = session.fill(handle, {"seed": index, "text": f"text-{index}"}, attempt_id="attempt", context=ctx)
        elapsed.append((time.perf_counter_ns() - start) / 1e6)
        assert record.api_projection["1"]["inputs"]["seed"] == index
    assert max(elapsed) < 5, {"median_ms": statistics.median(elapsed), "max_ms": max(elapsed)}
    print({"samples": len(elapsed), "median_ms": statistics.median(elapsed), "max_ms": max(elapsed)})


def test_source_and_companion_bytes_change_the_key_and_stale_ir_cannot_admit(tmp_path):
    bundle, provider = tiny()
    path = tmp_path / "workflow.py"
    bundle = emit_bundle(bundle.workflow, path, Provenance.USER_CONFIRMED)
    session = PreparedWorkflowSession(context())
    first = session.prepare(bundle, inputs={"seed": 1}, schema_provider=provider)
    # Whitespace leaves the decoded companion semantics identical but changes
    # the admitted source closure. Its raw bytes are part of the key too.
    companion = path.with_suffix(".vibe.json")
    companion.write_text(companion.read_text() + "\n")
    second = session.prepare(load_bundle(path, trust=Provenance.USER_CONFIRMED),
                             inputs={"seed": 1}, schema_provider=provider)
    assert session.key(first) != session.key(second)
    path.write_text(path.read_text() + "\n# another admitted source revision\n")
    third = session.prepare(load_bundle(path, trust=Provenance.USER_CONFIRMED),
                            inputs={"seed": 1}, schema_provider=provider)
    assert len({session.key(first), session.key(second), session.key(third)}) == 3
    memory, provider = tiny()
    memory.workflow.nodes["1"].inputs["text"] = "unsealed edit"
    with pytest.raises(PreparedWorkflowUnavailable, match="source changed"):
        session.prepare(memory, inputs={"seed": 1}, schema_provider=provider)


@pytest.mark.parametrize("extra", [
    "from time import time\n",
    "from pathlib import Path\n",
    "import os\n",
    "def after_outputs():\n    return None\n",
    "if True:\n    pass\n",
])
def test_untracked_executable_builders_fall_back_before_reexecution(tmp_path, monkeypatch, extra):
    bundle, provider = tiny()
    bundle = emit_bundle(bundle.workflow, tmp_path / "workflow.py", Provenance.USER_CONFIRMED)
    bundle.python_path.write_text(bundle.python_path.read_text() + "\n" + extra)
    def forbidden(*args, **kwargs):
        raise AssertionError("unsupported code must not be reexecuted by preparation")
    import vibecomfy.prepared as prepared
    monkeypatch.setattr(prepared, "_rebind_current_bundle", forbidden)
    with pytest.raises(PreparedWorkflowUnavailable):
        PreparedWorkflowSession(context()).prepare(bundle, inputs={"seed": 1}, schema_provider=provider)


def test_target_and_embedded_routes_cannot_reuse_server_authority():
    bundle, provider = tiny()
    ctx = context()
    session = PreparedWorkflowSession(ctx)
    handle = session.prepare(bundle, inputs={"seed": 1}, schema_provider=provider)
    record, frozen = session.fill(handle, {"seed": 2}, attempt_id="attempt", context=ctx)
    class WrongTarget:
        server_url = "http://127.0.0.1:9999"
        async def _post_prompt(self, payload):
            raise AssertionError("wrong target received a prepared prompt")
        async def queue_prompt_api(self, payload):
            raise AssertionError("embedded target received a server authority")
    with pytest.raises(PreparedWorkflowUnavailable, match="another target"):
        asyncio.run(queue_server_prompt(record, frozen, client=WrongTarget()))
    with pytest.raises(PreparedWorkflowUnavailable, match="server target"):
        asyncio.run(queue_embedded_prompt(WrongTarget(), record, frozen))


def test_alias_precedence_matches_full_compilation_for_conflicting_values():
    bundle, provider = tiny()
    workflow = bundle.workflow
    workflow.inputs["seed"].aliases = ("random_seed",)
    workflow.register_input("other_seed", "1", "seed", 7, type="INT")
    bundle = load_bundle(workflow)
    ctx = context()
    session = PreparedWorkflowSession(ctx)
    values = {"random_seed": 1, "other_seed": 7}
    handle = session.prepare(bundle, inputs=values, schema_provider=provider)
    for first, second in ((1, 7), (7, 2), (3, 4), (7, 7)):
        values = {"random_seed": first, "other_seed": second}
        record, _ = session.fill(handle, values, attempt_id="attempt", context=ctx)
        reference, bindings = reference_api(bundle, values, record.output_identity)
        assert canonical_bytes(record.api_projection) == canonical_bytes(reference.compile("api", run_inputs=bindings))


def test_model_spelling_is_retained_but_presence_and_ranges_belong_to_comfy(caplog):
    bundle, _ = tiny()
    workflow = bundle.workflow
    workflow.nodes["3"] = VibeNode("3", "UNETLoader", inputs={"unet_name": "folder/model.safetensors", "weight_dtype": "default"},
                                  uid="model", native_input_names=["unet_name", "weight_dtype"],
                                  native_input_types=["STRING", "STRING"],
                                  native_output_names=["MODEL"], native_output_types=["MODEL"])
    workflow.register_input("model", "3", "unet_name", "folder/model.safetensors", type="STRING")
    bundle = load_bundle(workflow)
    provider = TargetSchemaProvider.from_object_info({
        "UNETLoader": {"input": {"required": {
            "unet_name": [["folder\\model.safetensors"]], "weight_dtype": [["default"]]}}, "output": ["MODEL"]},
        "SeedImage": {"input": {"required": {"seed": ["INT", {"min": 0, "max": 10}], "text": ["STRING", {}]}}, "output": ["IMAGE"]},
        "SaveImage": {"input": {"required": {"images": ["IMAGE"], "filename_prefix": ["STRING", {}]}}, "output": []},
    }, server_url=context().target_identity, model_availability="target")
    ctx = context()
    session = PreparedWorkflowSession(ctx)
    handle = session.prepare(bundle, inputs={"model": "folder/model.safetensors", "seed": -1}, schema_provider=provider)
    mapped, _ = session.fill(handle, {"model": "folder/model.safetensors", "seed": -999}, attempt_id="attempt", context=ctx)
    assert mapped.api_projection["3"]["inputs"]["unet_name"] == "folder\\model.safetensors"
    unknown, _ = session.fill(handle, {"model": "not-present.safetensors", "seed": 10**20}, attempt_id="attempt", context=ctx)
    assert unknown.api_projection["3"]["inputs"]["unet_name"] == "not-present.safetensors"
    assert unknown.api_projection["1"]["inputs"]["seed"] == 10**20


def test_transport_bound_and_process_generation_remain_enforced(monkeypatch):
    import os

    bundle, provider = tiny()
    ctx = context()
    session = PreparedWorkflowSession(ctx)
    handle = session.prepare(bundle, inputs={"text": "small"}, schema_provider=provider)
    with pytest.raises(WorkflowBundleError, match="transport byte bound"):
        session.fill(handle, {"text": "x" * (9 * 1024 * 1024)}, attempt_id="attempt", context=ctx)
    pid = os.getpid()
    monkeypatch.setattr(os, "getpid", lambda: pid + 1)
    with pytest.raises(PreparedWorkflowUnavailable, match="generation"):
        session.fill(handle, {"text": "small"}, attempt_id="attempt", context=ctx)


def test_structural_schema_diagnostics_warn_once_and_do_not_gate_fills(caplog):
    bundle, provider = tiny()
    observed = copy.deepcopy(provider._object_info)
    observed["SeedImage"]["output"] = ["MASK"]
    provider = TargetSchemaProvider.from_object_info(observed, server_url=context().target_identity)
    session = PreparedWorkflowSession(context())
    handle = session.prepare(bundle, inputs={"seed": 1}, schema_provider=provider)
    record, frozen = session.fill(handle, {"seed": 2}, attempt_id="attempt", context=context())
    provenance = record.preparation_provenance()
    assert provenance["structural_diagnostics"]
    assert all(item["severity"] == "warning" for item in provenance["structural_diagnostics"])
    assert any("structural check" in message for message in caplog.messages)
    assert authorized_queue_payload(record, frozen)["2"]["inputs"]["images"] == ["1", 0]


def test_media_paths_have_finite_containment_bounds():
    bundle, provider = tiny()
    bundle.workflow.inputs["text"].media_semantics = "image"
    bundle = load_bundle(bundle.workflow)
    session = PreparedWorkflowSession(context())
    handle = session.prepare(bundle, inputs={"text": "astrid/input.png"}, schema_provider=provider)
    for value in ("../escape.png", "/absolute.png", "C:\\outside.png", "x" * 256):
        with pytest.raises(WorkflowBundleError, match="filename"):
            session.fill(handle, {"text": value}, attempt_id="attempt", context=context())
