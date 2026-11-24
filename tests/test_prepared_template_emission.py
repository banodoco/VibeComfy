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
    return _retain_fixture_native_rosters(workflow)


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


def _pair_bytes(path: Path) -> tuple[bytes, bytes]:
    return path.read_bytes(), path.with_suffix(".vibe.json").read_bytes()


def _remove_pair(path: Path) -> None:
    # Both oracle emissions start with an empty publication destination.  Keep
    # the logical path identical because it is evidence in the UI receipt.
    path.unlink()
    path.with_suffix(".vibe.json").unlink()


def _different_json_paths(left, right, path=()) -> list[tuple]:
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict) and left.keys() == right.keys():
        return [item for key in sorted(left) for item in _different_json_paths(left[key], right[key], (*path, key))]
    if isinstance(left, list) and len(left) == len(right):
        return [item for i, (a, b) in enumerate(zip(left, right)) for item in _different_json_paths(a, b, (*path, i))]
    return [] if left == right else [path]


def _assert_pair_equal(left, right, *, left_bytes: tuple[bytes, bytes] | None = None) -> None:
    if left.python_path == right.python_path:
        assert left_bytes is not None, "capture the full-build bytes before rewriting the same publication path"
    expected = _pair_bytes(left.python_path) if left_bytes is None else left_bytes
    actual = _pair_bytes(right.python_path)
    assert expected[0] == actual[0], "workflow.py bytes differ"
    assert expected[1] == actual[1], "companion bytes differ"
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


def _target_row(class_type):
    from vibecomfy.porting.object_info import get_class
    # Integer's curated fallback contains only outputs. Its explicit fixture
    # contract supplies the real scalar input as well as that output roster.
    if class_type == "Integer":
        return {
            "input": {"required": {"value": ["INT", {"default": 0}]}},
            "input_order": {"required": ["value"]}, "output": ["INT"],
            "output_name": ["INT"], "output_is_list": [False], "output_node": False,
        }
    entry = get_class(class_type)
    assert entry is not None, class_type
    assert {"inputs", "input_order", "outputs"} <= entry.keys(), (
        f"incomplete target fixture schema for {class_type}: {sorted(entry)}"
    )
    return {
        "input": copy.deepcopy(entry["inputs"]),
        "input_order": copy.deepcopy(entry["input_order"]),
        "output": [item["type"] for item in entry["outputs"]],
        "output_name": [item["name"] for item in entry["outputs"]],
        "output_is_list": [item["is_list"] for item in entry["outputs"]],
        "output_node": class_type == "SaveImage",
    }


def _target(workflow):
    from vibecomfy.schema.provider import TargetSchemaProvider
    info = {node.class_type: _target_row(node.class_type) for node in workflow.runtime_nodes().values()}
    return TargetSchemaProvider.from_object_info(info, server_url="http://current-target.invalid:8188", model_availability="target")


def _retain_fixture_native_rosters(workflow):
    # Match the shipped ready-template carrier contract for EVERY fixture node,
    # including literal-only inputs and an empty output roster on terminal nodes.
    # The exact same get_class/Integer declarations also back approval below.
    provider = _target(workflow)
    for node in workflow.nodes.values():
        schema = provider.get_schema(node.class_type)
        assert schema is not None, f"missing native fixture schema: {node.class_type}"
        node.native_input_names = list(schema.inputs)
        node.native_input_types = [spec.type for spec in schema.inputs.values()]
        node.native_input_optional = [not spec.required for spec in schema.inputs.values()]
        assets = [spec.asset_kind for spec in schema.inputs.values()]
        node.native_input_asset_kinds = assets if any(assets) else None
        node.native_output_names = [spec.name for spec in schema.outputs]
        node.native_output_types = [spec.type for spec in schema.outputs]
        node.__post_init__()
    for edge in workflow.edges:
        source = workflow.nodes[edge.from_node]
        target = workflow.nodes[edge.to_node]
        assert source.native_output_names, f"missing source roster: {source.id}"
        if str(edge.from_output).isdigit():
            assert 0 <= int(edge.from_output) < len(source.native_output_names), edge
        else:
            assert edge.from_output in source.native_output_names, edge
        assert edge.to_input in target.native_input_names, edge
    return workflow


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
    destination = tmp_path / "published" / "workflow.py"
    full = _emit(_bind_request(_request_workflow(), values), destination, mode)
    full_record = full.compile(schema_provider=_target(full.workflow))
    full_bytes = _pair_bytes(destination)
    _remove_pair(destination)
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
    published = _emit(warm.workflow, destination, mode, session=warm.emission)
    _assert_pair_equal(full, published, left_bytes=full_bytes)
    record = published.compile(schema_provider=_target(published.workflow))
    assert published.workflow.source.path == full.workflow.source.path == str(destination.resolve())
    assert record.to_canonical_bytes() == full_record.to_canonical_bytes(), (
        _different_json_paths(full_record.to_dict(), record.to_dict())
    )
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
    old = _emit(first.workflow, tmp_path / "old" / "workflow.py", "bundle", session=first.emission)
    template = first.snapshot()
    current_value = next(draws)
    warm = fill_template(template, {"seed": current_value}, current_key_inputs=_current(template))
    full_workflow = _workflow(current_value)
    for workflow in (full_workflow, warm.workflow):
        workflow.metadata["revision_evidence"] = [
            {"revision_id": old.revision_id, "workflow_identity": old.workflow.id},
        ]
    destination = tmp_path / "published" / "workflow.py"
    full = _emit(full_workflow, destination, "bundle", parent_revision=old.revision_id)
    full_record = full.compile()
    full_bytes = _pair_bytes(destination)
    _remove_pair(destination)
    published = _emit(warm.workflow, destination, "bundle", session=warm.emission, parent_revision=old.revision_id)
    _assert_pair_equal(full, published, left_bytes=full_bytes)
    assert old.parent_revision == ""
    assert published.parent_revision == full.parent_revision == old.revision_id
    assert published.revision_id != old.revision_id
    assert published.ui_sidecar["bind"]["generation_id"] != old.ui_sidecar["bind"]["generation_id"]
    assert warm.workflow.inputs["seed"].value == 202
    assert template.key == warm.snapshot().key
    record = published.compile()
    assert record.to_canonical_bytes() == full_record.to_canonical_bytes(), (
        _different_json_paths(full_record.to_dict(), record.to_dict())
    )


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
    expected = emit_scratchpad_python(changed, preserve_node_ids=True)
    original = emit_prepare._prepare_workflow_for_emit
    seen = []
    def observe(current, *args, **kwargs):
        seen.append(current.nodes["p"].inputs["value"])
        return original(current, *args, **kwargs)
    monkeypatch.setattr(emit_prepare, "_prepare_workflow_for_emit", observe)
    session = EmissionSession([])
    emit_scratchpad_python(workflow, preserve_node_ids=True, emission_session=session)
    warm = EmissionSession(session.records())
    actual = emit_scratchpad_python(changed, preserve_node_ids=True, emission_session=warm)
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


@pytest.mark.parametrize("field", ["node_order", "sections"])
def test_resealed_valid_roster_permutation_is_rederived_before_emission(
    tmp_path: Path, field: str,
) -> None:
    workflow = _workflow()
    workflow.add_node("Integer", _id="2", uid="second-independent-integer", value=9)
    template = prepare_template(workflow, _slots(), key_context=_context())
    cold = fill_template(template, {"seed": 7}, current_key_inputs=_current(template))
    _emit(cold.workflow, tmp_path / "populate" / "workflow.py", "bundle", session=cold.emission)
    record = cold.snapshot().to_record()
    changed = 0
    for row in record["payload"]["layouts"]:
        layout = row["layout"]
        if field == "node_order" and len(layout[field]) > 1:
            layout[field].reverse()  # Independent nodes: still topologically valid.
            changed += 1
        elif field == "sections":
            for _, members in layout[field]:
                if len(members) > 1:
                    members.reverse()  # Same groups/membership, different byte order.
                    changed += 1
    assert changed > 0
    resealed = PreparedTemplate.from_bytes(_seal(record))
    warm = fill_template(resealed, {"seed": 7}, current_key_inputs=_current(resealed))
    full = _emit(workflow, tmp_path / "full" / "workflow.py", "bundle")
    published = _emit(warm.workflow, tmp_path / "warm" / "workflow.py", "bundle", session=warm.emission)
    _assert_pair_equal(full, published)
    assert any((event.outcome, event.reason) == ("recompute", "entry_invalid")
               for event in warm.emission.events)


def test_warm_template_is_not_an_approval_and_does_not_admit_stale_companion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import vibecomfy.porting.emit.emit_ready as renderer

    template = prepare_template(_workflow(), _slots(), key_context=_context())
    cold = fill_template(template, {"seed": 7}, current_key_inputs=_current(template))
    _emit(cold.workflow, tmp_path / "populate" / "workflow.py", "bundle", session=cold.emission)
    filled = fill_template(cold.snapshot(), {"seed": 7}, current_key_inputs=_current(template))

    def bypassed(*args, **kwargs):
        pytest.fail("approval guard must be exercised after an actual cached-layout hit")

    monkeypatch.setattr(renderer, "_prepare_source_layout", bypassed)
    bundle = _emit(filled.workflow, tmp_path / "workflow.py", "bundle", session=filled.emission)
    assert filled.emission.events and all(event.outcome == "hit" for event in filled.emission.events)
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
if mode == "full":
    bundle = emit_bundle(_workflow().set_input("seed", 91), destination, {"operation": "authored"})
    events = []
else:
    if mode == "cold":
        template = prepare_template(_workflow(), _slots(), key_context=_context())
    else:
        template = PreparedTemplate.from_bytes(entry.read_bytes())
    filled = fill_template(template, {"seed": 91}, current_key_inputs=_current(template))
    bundle = emit_bundle(filled.workflow, destination, {"operation": "authored"}, emission_session=filled.emission)
    if mode == "cold":
        entry.write_bytes(filled.snapshot().to_bytes())
    events = [[event.outcome, event.reason] for event in filled.emission.events]
record = bundle.compile()
print(json.dumps({
    "source": hashlib.sha256(destination.read_bytes()).hexdigest(),
    "companion": hashlib.sha256(destination.with_suffix(".vibe.json").read_bytes()).hexdigest(),
    "receipt": hashlib.sha256(record.to_canonical_bytes()).hexdigest(),
    "api": record.api_digest,
    "source_path": bundle.workflow.source.path,
    "receipt_fields": record.to_dict(),
    "events": events,
}))
'''


def test_emission_layouts_and_receipts_survive_a_fresh_process(tmp_path: Path) -> None:
    entry = tmp_path / "entry.json"
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    def run(mode, destination):
        result = subprocess.run([sys.executable, "-c", _EMISSION_PROCESS, mode, str(entry), str(destination)],
                                cwd=root, env=env, check=False, text=True, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout.strip().splitlines()[-1])
    # Publication path is an input to the receipt's UI breadcrumb. Use the
    # same current destination in both processes, snapshotting the old pair
    # before removing it so both publications start from an empty destination.
    destination = tmp_path / "published" / "workflow.py"
    cold = run("cold", destination)
    cold_bytes = _pair_bytes(destination)
    _remove_pair(destination)
    warm = run("warm", destination)
    warm_bytes = _pair_bytes(destination)
    for field in ("source", "companion", "receipt", "api"):
        assert warm[field] == cold[field], (
            f"{field} digest differs: cold={cold[field]}, warm={warm[field]}; "
            f"receipt differences={_different_json_paths(cold['receipt_fields'], warm['receipt_fields'])}; "
            f"source paths: cold={cold['source_path']!r}, warm={warm['source_path']!r}"
        )
    for index, field in enumerate(("source", "companion")):
        assert warm_bytes[index] == cold_bytes[index], f"{field} bytes differ across processes"
    assert warm["receipt_fields"] == cold["receipt_fields"]
    for result in (cold, warm):
        assert result["source_path"] == str(destination.resolve())
        assert result["receipt_fields"]["ui_projection"]["extra"]["vibecomfy"]["prior_path"] == str(destination.resolve())
    assert any(outcome == "recompute" for outcome, _ in cold["events"])
    assert warm["events"] and all(outcome == "hit" for outcome, _ in warm["events"])

    # Reproduce the original differing input with the ordinary full builder,
    # independently of the prepared record: only the publication path changes.
    # Compare its complete receipt; do not strip/normalize source evidence.
    other_destination = tmp_path / "different-publication" / "workflow.py"
    full = run("full", other_destination)
    for field in ("source", "companion", "api"):
        assert full[field] == cold[field], f"full-build path control changed {field}"
    assert full["source_path"] == str(other_destination.resolve())
    assert full["receipt_fields"]["ui_projection"]["extra"]["vibecomfy"]["prior_path"] == str(other_destination.resolve())
    assert full["receipt"] != cold["receipt"], "different publication paths must remain visible in receipts"
    assert _different_json_paths(cold["receipt_fields"], full["receipt_fields"]) == [
        ("ui_projection", "extra", "vibecomfy", "prior_path"),
    ]
