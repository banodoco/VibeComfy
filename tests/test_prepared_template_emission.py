"""Cold/full vs warm canonical bytes, current receipts and unchanged checks."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_prepared_template import _context, _current, _seal, _slots, _workflow
from vibecomfy.prepared_template import (
    EmissionSession, PreparedTemplate, ValueSlot, fill_template, prepare_template,
)
from vibecomfy.security.provenance import Provenance
from vibecomfy.workflow import VibeEdge, VibeInput, VibeNode, VibeOutput, VibeWorkflow, WorkflowSource
from vibecomfy.workflow_bundle import (
    WorkflowBundleError, emit_bundle, emit_bundle_with_candidate, load_bundle,
)


AUTHORED_PROMPT = "An authored default."
CURRENT = {
    "prompt": 'A "quoted" apostrophe \' and backslash \\\nUnicode: café 雪 🙂',
    "seed": 314159265,
    "width": 768,
    "height": 640,
    "prefix": "user/folder_astrid_attempt-2",
}


def _request_workflow() -> VibeWorkflow:
    workflow = VibeWorkflow("prepared-values", WorkflowSource("prepared-values"))
    workflow.add_node("StringConcatenate", _id="1", uid="prompt-node",
                      string_a=AUTHORED_PROMPT, string_b="", delimiter="")
    workflow.add_node("Integer", _id="2", uid="seed-node", value=7)
    workflow.add_node("EmptyImage", _id="3", uid="image-node",
                      width=512, height=512, batch_size=1, color=0)
    workflow.add_node("SaveImage", _id="4", uid="save-node", filename_prefix="authored")
    workflow.edges.append(VibeEdge("3", "0", "4", "images"))
    for name, node_id, field, value, kind in (
        ("prompt", "1", "string_a", AUTHORED_PROMPT, "STRING"),
        ("seed", "2", "value", 7, "INT"),
        ("width", "3", "width", 512, "INT"),
        ("height", "3", "height", 512, "INT"),
        ("output_prefix", "4", "filename_prefix", "authored", "STRING"),
    ):
        workflow.register_input(name, node_id, field, value, type=kind, default=value)
    workflow.outputs = [VibeOutput(
        "4", "SaveImage", name="image", artifact_kind="image", mime_type="image/png",
        filename_prefix="authored", expected_cardinality="one",
    )]
    workflow.metadata["output_prefix"] = "authored"
    return workflow


def _request_slots() -> tuple[ValueSlot, ...]:
    result = []
    for name, public, node, field, kind in (
        ("prompt", "prompt", "1", "string_a", "string"),
        ("seed", "seed", "2", "value", "integer"),
        ("width", "width", "3", "width", "integer"),
        ("height", "height", "3", "height", "integer"),
        ("prefix", "output_prefix", "4", "filename_prefix", "string"),
    ):
        paths = (("nodes", node, "inputs", field), ("inputs", public, "value"))
        if name == "prefix":
            paths += (("inputs", public, "default"), ("outputs", 0, "filename_prefix"),
                      ("metadata", "output_prefix"))
        result.append(ValueSlot(name, paths, kind))
    return tuple(result)


def _bind_request(workflow: VibeWorkflow, values: dict) -> VibeWorkflow:
    for name in ("prompt", "seed", "width", "height"):
        workflow.set_input(name, values[name])
    workflow.set_input("output_prefix", values["prefix"])
    workflow.inputs["output_prefix"].default = values["prefix"]
    workflow.outputs[0].filename_prefix = values["prefix"]
    workflow.metadata["output_prefix"] = values["prefix"]
    return workflow


def _emit(workflow, path, mode, *, session=None, parent_revision=""):
    kwargs = {} if session is None else {"emission_session": session}
    if mode == "bundle":
        return emit_bundle(workflow, path, {"operation": "authored"}, parent_revision, **kwargs)
    return emit_bundle_with_candidate(
        workflow, path, {"operation": "authored"}, None, source_format=mode,
        parent_revision=parent_revision, **kwargs,
    )


def _assert_pair_equal(left, right) -> None:
    assert left.python_path.read_bytes() == right.python_path.read_bytes()
    assert left.python_path.with_suffix(".vibe.json").read_bytes() == right.python_path.with_suffix(".vibe.json").read_bytes()
    assert left.workflow.compile("api") == right.workflow.compile("api")
    assert left.workflow.semantic_projection() == right.workflow.semantic_projection()
    assert left.semantic_digest == right.semantic_digest
    assert left.ui_digest == right.ui_digest
    assert left.revision_id == right.revision_id
    assert left.parent_revision == right.parent_revision
    assert left.provenance == right.provenance
    assert left.ui_sidecar == right.ui_sidecar
    assert left.workflow.source.id == right.workflow.source.id
    assert left.workflow.source.source_type == right.workflow.source.source_type
    # The complete companion above includes source custody and the newly
    # generated marker, not just a graph-isomorphism comparison.
    assert left.ui_sidecar["bind"]["generation_id"] == right.ui_sidecar["bind"]["generation_id"]
    assert left.ui_sidecar["bind"]["custody_digest"] == right.ui_sidecar["bind"]["custody_digest"]


def _target(workflow):
    from vibecomfy.porting.object_info import get_class
    from vibecomfy.schema.provider import TargetSchemaProvider

    info = {}
    for node in workflow.runtime_nodes().values():
        entry = get_class(node.class_type)
        # Integer is the same schema-less scalar used throughout the existing
        # bundle tests; explicitly advertise its target contract here.
        if entry is None and node.class_type == "Integer":
            info["Integer"] = {
                "input": {"required": {"value": ["INT", {"default": 0}]}},
                "input_order": {"required": ["value"]}, "output": ["INT"],
                "output_name": ["value"], "output_is_list": [False], "output_node": False,
            }
        else:
            assert entry is not None, node.class_type
            info[node.class_type] = {
                "input": copy.deepcopy(entry["inputs"]),
                "input_order": copy.deepcopy(entry["input_order"]),
                "output": [item["type"] for item in entry["outputs"]],
                "output_name": [item["name"] for item in entry["outputs"]],
                "output_is_list": [item["is_list"] for item in entry["outputs"]],
                "output_node": node.class_type == "SaveImage",
            }
    return TargetSchemaProvider.from_object_info(info, server_url="http://current-target.invalid:8188", model_availability="target")


@pytest.mark.parametrize("mode", ["bundle", "scratchpad", "ready_template"])
@pytest.mark.parametrize("prompt,prefix", [
    (AUTHORED_PROMPT, "same_default_astrid_attempt-1"),
    (CURRENT["prompt"], CURRENT["prefix"]),
    ("An intentionally long new prompt. " * 8, ""),
])
def test_cold_and_warm_match_python_companion_graph_evidence_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, prompt: str, prefix: str,
) -> None:
    import vibecomfy.porting.emit.emit_ready as renderer
    import vibecomfy.workflow_bundle as bundles

    template = prepare_template(_request_workflow(), _request_slots(), key_context=_context())
    initial = {**CURRENT, "prompt": AUTHORED_PROMPT, "seed": 7, "width": 512, "height": 512, "prefix": "authored"}
    cold = fill_template(template, initial, current_key_inputs=_current(template))
    _emit(cold.workflow, tmp_path / "populate" / "workflow.py", mode, session=cold.emission)
    template = PreparedTemplate.from_bytes(cold.snapshot().to_bytes())
    assert any(event.outcome == "recompute" for event in cold.emission.events)

    values = {**CURRENT, "prompt": prompt, "prefix": prefix}
    # Independent empty preparation: original builder + current binder + the
    # normal full canonical path, with no cache-bypass flag in production.
    full = _emit(_bind_request(_request_workflow(), values), tmp_path / "full" / "workflow.py", mode)
    full_record = full.compile(schema_provider=_target(full.workflow))
    checks = {name: 0 for name in ("_canonicalize_for_v2_pair", "_build_v2_sidecar", "_atomic_publish_pair")}
    for name in checks:
        original = getattr(bundles, name)
        def observe(*args, _name=name, _original=original, **kwargs):
            checks[_name] += 1
            return _original(*args, **kwargs)
        monkeypatch.setattr(bundles, name, observe)

    def no_new_layout(*args, **kwargs):
        raise AssertionError("warm emission repeated structural plan extraction")
    monkeypatch.setattr(renderer, "_prepare_source_layout", no_new_layout)
    # The original workflow constructor is unavailable during the warm fill.
    monkeypatch.setattr(sys.modules[__name__], "_request_workflow", lambda: pytest.fail("warm fill called source builder"))
    warm = fill_template(template, values, current_key_inputs=_current(template))
    published = _emit(warm.workflow, tmp_path / "warm" / "workflow.py", mode, session=warm.emission)
    _assert_pair_equal(full, published)
    record = published.compile(schema_provider=_target(published.workflow))
    assert record.to_canonical_bytes() == full_record.to_canonical_bytes()
    record.assert_matches(published, api_projection=record.api_projection, ui_projection=record.ui_projection)
    assert warm.emission.events and all(event.outcome == "hit" for event in warm.emission.events)
    assert all(count >= 1 for count in checks.values())
    assert warm.workflow.inputs["prompt"].default == AUTHORED_PROMPT
    assert warm.workflow.inputs["prompt"].value == prompt
    if prompt != AUTHORED_PROMPT:
        assert prompt.encode("utf-8") not in warm.snapshot().to_bytes()


@pytest.mark.parametrize("mode", ["bundle", "scratchpad", "ready_template"])
def test_load_image_value_is_filled_each_time(tmp_path: Path, mode: str) -> None:
    workflow = VibeWorkflow("prepared-load-image", WorkflowSource("prepared-load-image"))
    workflow.add_node("LoadImage", _id="1", uid="load-image", image="authored.png")
    workflow.inputs["image"] = VibeInput("image", "1", "image", "authored.png", type="CHOICE", default="authored.png", media_semantics="image")
    workflow._manual_input_names.add("image")
    slots = (ValueSlot("image", (("nodes", "1", "inputs", "image"), ("inputs", "image", "value")), "string"),)
    template = prepare_template(workflow, slots, key_context=_context())
    cold = fill_template(template, {"image": "first-upload.png"}, current_key_inputs=_current(template))
    _emit(cold.workflow, tmp_path / "populate" / "workflow.py", mode, session=cold.emission)
    template = cold.snapshot()
    warm = fill_template(template, {"image": "second-upload.png"}, current_key_inputs=_current(template))
    full_workflow = workflow.copy().set_input("image", "second-upload.png")
    full = _emit(full_workflow, tmp_path / "full" / "workflow.py", mode)
    published = _emit(warm.workflow, tmp_path / "warm" / "workflow.py", mode, session=warm.emission)
    _assert_pair_equal(full, published)
    assert all(event.outcome == "hit" for event in warm.emission.events)
    assert b"first-upload.png" not in template.to_bytes()
    assert b"second-upload.png" not in warm.snapshot().to_bytes()


@pytest.mark.parametrize("state", ["omitted", "none", "empty", "specified"])
def test_omitted_none_empty_prefix_are_not_conflated(tmp_path: Path, state: str) -> None:
    prefix = {"omitted": None, "none": None, "empty": "", "specified": "folder/frame"}[state]
    workflow = _request_workflow()
    del workflow.inputs["output_prefix"]
    workflow._manual_input_names.discard("output_prefix")
    del workflow.metadata["output_prefix"]
    if state == "omitted":
        del workflow.nodes["4"].inputs["filename_prefix"]
    else:
        workflow.nodes["4"].inputs["filename_prefix"] = prefix
    # Keep the real terminal SaveImage and its typed output declaration: this
    # exercises OutputSpec rendering as well as literal omission vs None.
    workflow.outputs[0].filename_prefix = prefix
    template = prepare_template(workflow, (), key_context=_context())
    cold = fill_template(template, {}, current_key_inputs=_current(template))
    _emit(cold.workflow, tmp_path / "populate" / "workflow.py", "bundle", session=cold.emission)
    warm = fill_template(cold.snapshot(), {}, current_key_inputs=_current(template))
    full = _emit(workflow.copy(), tmp_path / "full" / "workflow.py", "bundle")
    published = _emit(warm.workflow, tmp_path / "warm" / "workflow.py", "bundle", session=warm.emission)
    _assert_pair_equal(full, published)
    assert ("filename_prefix" in warm.workflow.nodes["4"].inputs) == (state != "omitted")
    if state != "omitted":
        assert warm.workflow.nodes["4"].inputs["filename_prefix"] == prefix
    assert warm.workflow.outputs[0].filename_prefix == prefix
    assert all(event.outcome == "hit" for event in warm.emission.events)


def test_nested_definitions_remain_lossless_across_cold_and_warm(tmp_path: Path) -> None:
    from tests.test_b11b_execution_projection import _depth_two_sibling_workflow

    workflow, inner_key, outer_key = _depth_two_sibling_workflow()
    template = prepare_template(workflow, (), key_context=_context())
    cold = fill_template(template, {}, current_key_inputs=_current(template))
    _emit(cold.workflow, tmp_path / "populate" / "workflow.py", "bundle", session=cold.emission)
    warm = fill_template(cold.snapshot(), {}, current_key_inputs=_current(template))
    full = _emit(workflow.copy(), tmp_path / "full" / "workflow.py", "bundle")
    published = _emit(warm.workflow, tmp_path / "warm" / "workflow.py", "bundle", session=warm.emission)
    _assert_pair_equal(full, published)
    assert warm.workflow.definitions == workflow.definitions
    assert warm.workflow.interfaces == workflow.interfaces
    assert warm.workflow.boundary_ports == workflow.boundary_ports
    scopes = {item["scope_path"] for item in published.ui_sidecar["custody"]["scopes"]}
    assert {outer_key, f"{outer_key}/{inner_key}"} <= scopes
    assert all(event.outcome == "hit" for event in warm.emission.events)


def test_seed_draw_and_parent_revision_remain_current(tmp_path: Path) -> None:
    template = prepare_template(_workflow(), _slots(), key_context=_context())
    # Only this new oracle controls draws. The Agent still owns real seedless
    # randomness and its unchanged integration witness when wiring is cleared.
    draws = iter((101, 202))
    first_value = next(draws)
    first = fill_template(template, {"seed": first_value}, current_key_inputs=_current(template))
    old = _emit(first.workflow, tmp_path / "old" / "workflow.py", "bundle", session=first.emission, parent_revision="a" * 64)
    template = first.snapshot()
    current_value = next(draws)
    warm = fill_template(template, {"seed": current_value}, current_key_inputs=_current(template))
    full = _emit(_workflow(current_value), tmp_path / "full" / "workflow.py", "bundle", parent_revision="b" * 64)
    published = _emit(warm.workflow, tmp_path / "warm" / "workflow.py", "bundle", session=warm.emission, parent_revision="b" * 64)
    _assert_pair_equal(full, published)
    assert published.revision_id != old.revision_id
    assert published.ui_sidecar["bind"]["generation_id"] != old.ui_sidecar["bind"]["generation_id"]
    assert warm.workflow.inputs["seed"].value == 202
    assert template.key == warm.snapshot().key
    assert published.compile().to_canonical_bytes() == full.compile().to_canonical_bytes()


def test_unseen_projected_structure_recomputes_and_reports_reason(tmp_path: Path) -> None:
    from vibecomfy.porting.emit.entrypoints import emit_scratchpad_python

    workflow = _workflow()
    session = EmissionSession([])
    emit_scratchpad_python(workflow, emission_session=session)
    changed = workflow.copy()
    changed.add_node("Integer", _id="2", uid="second", value=9)
    events = []
    warm = EmissionSession(session.records(), events.append)
    actual = emit_scratchpad_python(changed, emission_session=warm)
    expected = emit_scratchpad_python(changed)
    assert actual == expected
    assert [(event.outcome, event.reason) for event in events] == [
        ("miss", "key_changed:structure"), ("recompute", "key_changed:structure"),
    ]


def test_value_dependent_helper_projection_is_not_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    from vibecomfy.porting.emit import emit_prepare
    from vibecomfy.porting.emit.entrypoints import emit_scratchpad_python

    # This is the established primitive-lowering shape from the execution
    # projection suite.  Its literal must reach the sink on each emission,
    # although the projected node roster and structural layout stay the same.
    workflow = VibeWorkflow("prepared-helper", WorkflowSource("prepared-helper"))
    workflow.nodes["p"] = VibeNode("p", "PrimitiveInt", inputs={"value": 7})
    workflow.nodes["s"] = VibeNode("s", "Sink", inputs={"x": 1})
    workflow.edges = [VibeEdge("p", "0", "s", "x")]
    changed = workflow.copy()
    changed.nodes["p"].inputs["value"] = 19
    expected = emit_scratchpad_python(changed)
    original = emit_prepare._prepare_workflow_for_emit
    seen = []
    def observe(current, *args, **kwargs):
        seen.append(current.nodes["p"].inputs["value"])
        return original(current, *args, **kwargs)
    monkeypatch.setattr(emit_prepare, "_prepare_workflow_for_emit", observe)
    session = EmissionSession([])
    emit_scratchpad_python(workflow, emission_session=session)
    warm = EmissionSession(session.records())
    actual = emit_scratchpad_python(changed, emission_session=warm)
    assert actual == expected
    namespace = {"__file__": "prepared_helper.py"}
    exec(compile(actual, "prepared helper", "exec"), namespace)  # noqa: S102
    assert namespace["build"]().compile("api") == changed.compile("api")
    assert seen == [7, 19]
    assert all(event.outcome == "hit" for event in warm.events)


def test_warm_layout_keeps_first_build_semantic_drift_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import vibecomfy.scratchpad_loader as loader

    template = prepare_template(_workflow(), _slots(), key_context=_context())
    cold = fill_template(template, {"seed": 7}, current_key_inputs=_current(template))
    _emit(cold.workflow, tmp_path / "populate" / "workflow.py", "bundle", session=cold.emission)
    warm = fill_template(cold.snapshot(), {"seed": 7}, current_key_inputs=_current(template))
    real_load = loader.load_scratchpad
    def drift(*args, **kwargs):
        loaded = real_load(*args, **kwargs)
        loaded.nodes["1"].inputs["value"] = 999
        return loaded
    monkeypatch.setattr(loader, "load_scratchpad", drift)
    destination = tmp_path / "refused" / "workflow.py"
    with pytest.raises(WorkflowBundleError, match="first-build semantic digest"):
        _emit(warm.workflow, destination, "bundle", session=warm.emission)
    assert not destination.exists()
    assert not destination.with_suffix(".vibe.json").exists()


@pytest.mark.parametrize("field", ["imports", "constructors"])
def test_cached_bindings_cannot_authorize_imports_before_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str,
) -> None:
    import vibecomfy.scratchpad_loader as loader

    template = prepare_template(_workflow(), _slots(), key_context=_context())
    cold = fill_template(template, {"seed": 7}, current_key_inputs=_current(template))
    _emit(cold.workflow, tmp_path / "populate" / "workflow.py", "bundle", session=cold.emission)
    record = cold.snapshot().to_record()
    for row in record["payload"]["layouts"]:
        if field == "imports":
            row["layout"][field] = [["foreign_module", ["ForeignConstructor"]]]
        else:
            for pair in row["layout"][field]:
                pair[1] = ["foreign_module", "ForeignConstructor"]
    # Even a correctly re-checksummed entry has no import/constructor authority.
    foreign = PreparedTemplate.from_bytes(_seal(record))
    warm = fill_template(foreign, {"seed": 7}, current_key_inputs=_current(foreign))
    full = _emit(_workflow(), tmp_path / "full" / "workflow.py", "bundle")
    real_load = loader.load_scratchpad
    inspected = []
    def inspect_staged(path, *args, **kwargs):
        source = Path(path).read_bytes()
        assert b"foreign_module" not in source
        assert b"ForeignConstructor" not in source
        inspected.append(path)
        return real_load(path, *args, **kwargs)
    monkeypatch.setattr(loader, "load_scratchpad", inspect_staged)
    published = _emit(warm.workflow, tmp_path / "warm" / "workflow.py", "bundle", session=warm.emission)
    _assert_pair_equal(full, published)
    assert inspected
    assert (warm.emission.events[0].outcome, warm.emission.events[0].reason) == ("miss", "entry_invalid")
    assert any((event.outcome, event.reason) == ("recompute", "entry_invalid") for event in warm.emission.events)
    assert b"foreign_module" not in warm.snapshot().to_bytes()


def test_warm_template_is_not_an_approval_and_does_not_admit_stale_companion(tmp_path: Path) -> None:
    template = prepare_template(_workflow(), _slots(), key_context=_context())
    filled = fill_template(template, {"seed": 7}, current_key_inputs=_current(template))
    bundle = _emit(filled.workflow, tmp_path / "workflow.py", "bundle", session=filled.emission)
    receipt = bundle.compile()
    bundle.workflow.set_input("seed", 8)
    with pytest.raises(WorkflowBundleError, match="revision is stale"):
        bundle.compile()
    with pytest.raises(WorkflowBundleError):
        receipt.assert_matches(bundle, api_projection=receipt.api_projection, ui_projection=receipt.ui_projection)
    bundle.python_path.with_suffix(".vibe.json").write_text("{}", encoding="utf-8")
    with pytest.raises(WorkflowBundleError):
        load_bundle(bundle.python_path, trust=Provenance.USER_CONFIRMED)


_EMISSION_PROCESS = r'''
import hashlib
import json
import sys
from pathlib import Path
from tests.test_prepared_template import _context, _current, _slots, _workflow
from vibecomfy.prepared_template import PreparedTemplate, fill_template, prepare_template
from vibecomfy.workflow_bundle import emit_bundle
mode, entry, destination = sys.argv[1:]
entry, destination = Path(entry), Path(destination)
if mode == "cold":
    template = prepare_template(_workflow(), _slots(), key_context=_context())
else:
    template = PreparedTemplate.from_bytes(entry.read_bytes())
filled = fill_template(template, {"seed": 91}, current_key_inputs=_current(template))
bundle = emit_bundle(filled.workflow, destination, {"operation": "authored"}, emission_session=filled.emission)
if mode == "cold":
    entry.write_bytes(filled.snapshot().to_bytes())
record = bundle.compile()
print(json.dumps({
    "source": hashlib.sha256(destination.read_bytes()).hexdigest(),
    "companion": hashlib.sha256(destination.with_suffix(".vibe.json").read_bytes()).hexdigest(),
    "receipt": hashlib.sha256(record.to_canonical_bytes()).hexdigest(),
    "api": record.api_digest,
    "events": [[event.outcome, event.reason] for event in filled.emission.events],
}))
'''


def test_emission_layouts_and_receipts_survive_a_fresh_process(tmp_path: Path) -> None:
    entry = tmp_path / "entry.json"
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    def run(mode):
        destination = tmp_path / mode / "workflow.py"
        result = subprocess.run([sys.executable, "-c", _EMISSION_PROCESS, mode, str(entry), str(destination)],
                                cwd=root, env=env, check=False, text=True, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout.strip().splitlines()[-1])
    cold = run("cold")
    warm = run("warm")
    for field in ("source", "companion", "receipt", "api"):
        assert warm[field] == cold[field]
    assert any(outcome == "recompute" for outcome, _ in cold["events"])
    assert warm["events"] and all(outcome == "hit" for outcome, _ in warm["events"])
