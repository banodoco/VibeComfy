"""RA-2a's portable recipe/key contract; no Agent store or approval cache."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from vibecomfy.prepared_template import (
    BACKEND, FORMAT, KEY_FIELDS, PreparedTemplate, TemplateKeyChanged,
    TemplateNotReusable, ValueSlot, fill_template, key_record, node_list_digest,
    prepare_template, template_key,
)
from vibecomfy.security.provenance import Provenance
from vibecomfy.testing.canonical import canonical_bytes, canonical_digest
from vibecomfy.workflow import VibeInput, VibeWorkflow, WorkflowSource


def _context() -> dict:
    # Explicit current witnesses for this deterministic fixture, not a claim
    # that arbitrary executable builders or a locator establish source custody.
    return {
        "compiler_identity": {"content": "sha256:" + "1" * 64, "python": "fixture"},
        "source_provenance": {"content": "sha256:" + "2" * 64, "source.json": "absent"},
        "vibecomfy_version": "2.8.0",
        "role_plan": {"backend": "comfyui", "roles": []},
        "node_list_digest": node_list_digest(b'{"Integer":{"input":{"required":{"value":["INT"]}}}}'),
    }


def _workflow(value: int = 7) -> VibeWorkflow:
    workflow = VibeWorkflow("prepared-contract", WorkflowSource("prepared-contract"))
    workflow.add_node("Integer", _id="1", uid="integer-node", value=value)
    workflow.inputs["seed"] = VibeInput("seed", "1", "value", value, type="INT", default=7)
    workflow._manual_input_names.add("seed")
    return workflow


def _slots() -> tuple[ValueSlot, ...]:
    return (ValueSlot("seed", (("nodes", "1", "inputs", "value"), ("inputs", "seed", "value")), "integer"),)


def _current(template: PreparedTemplate, **changed) -> list:
    context = _context()
    context.update(changed)
    return key_record(structure=template.structure_digest, **context)


def _seal(record: dict) -> bytes:
    record = copy.deepcopy(record)
    record.pop("content_digest", None)
    record["content_digest"] = "sha256:" + canonical_digest(record)
    return canonical_bytes(record)


def test_key_has_one_ordered_record_and_masks_only_declared_values() -> None:
    first = prepare_template(_workflow(7), _slots(), key_context=_context())
    changed = prepare_template(_workflow(123456789), _slots(), key_context=_context())
    assert [pair[0] for pair in first.key_inputs] == list(KEY_FIELDS)
    assert first.key_inputs[:2] == [["format", FORMAT], ["backend", BACKEND]]
    assert first.key == template_key(first.key_inputs) == changed.key
    assert first.to_bytes() == changed.to_bytes()
    assert b"123456789" not in changed.to_bytes()
    assert dict(first.key_inputs)["structure"] == first.structure_digest


@pytest.mark.parametrize("name", KEY_FIELDS[2:])
def test_each_current_key_input_invalidates_before_fill(name: str) -> None:
    template = prepare_template(_workflow(), _slots(), key_context=_context())
    current = _current(template)
    for pair in current:
        if pair[0] == name:
            pair[1] = (
                "sha256:" + "f" * 64 if name in {"structure", "node_list_digest"}
                else "2.8.1" if name == "vibecomfy_version"
                else {"changed": "current content witness"}
            )
    assert template_key(current) != template.key
    with pytest.raises(TemplateKeyChanged) as error:
        fill_template(template, {"seed": 19}, current_key_inputs=current)
    assert error.value.input == name
    assert error.value.reason == f"key_changed:{name}"


@pytest.mark.parametrize("change", ["authored_default", "node_class", "edge_roster", "source_metadata", "requirements"])
def test_unmasked_source_or_structure_edits_change_key(change: str) -> None:
    original = _workflow()
    changed = original.copy()
    if change == "authored_default":
        changed.inputs["seed"].default = 42
    elif change == "node_class":
        changed.nodes["1"].class_type = "AnotherInteger"
    elif change == "edge_roster":
        from vibecomfy.workflow import VibeEdge
        changed.add_node("Integer", _id="2", uid="other-integer", value=9)
        changed.edges.append(VibeEdge("1", "0", "2", "value"))
    elif change == "source_metadata":
        changed.source.provenance["source_digest"] = "sha256:" + "a" * 64
    else:
        changed.requirements.unsupported.append("explicit source requirement")
    first = prepare_template(original, _slots(), key_context=_context())
    second = prepare_template(changed, _slots(), key_context=_context())
    assert first.key != second.key
    assert first.structure_digest != second.structure_digest


def test_raw_node_list_digest_does_not_canonicalize_or_fetch() -> None:
    compact = b'{"nodes":["Integer"]}'
    spaced = b'{ "nodes": ["Integer"] }\n'
    assert json.loads(compact) == json.loads(spaced)
    assert node_list_digest(compact) != node_list_digest(spaced)
    with pytest.raises(TypeError, match="raw response bytes"):
        node_list_digest(json.loads(compact))  # type: ignore[arg-type]


def test_fill_preserves_order_types_defaults_and_detaches_each_request() -> None:
    workflow = _workflow()
    workflow.metadata["ordered"] = {"z": [1], "a": (2, 3)}
    workflow.metadata["tag-shaped-literal"] = ["slot", "seed"]
    workflow._canonical_v2_recursive_custody = None
    workflow._recursive_definition_captures = None
    template = prepare_template(workflow, _slots(), key_context=_context())
    cold = fill_template(template, {"seed": 19}, current_key_inputs=_current(template))
    warm = fill_template(PreparedTemplate.from_bytes(template.to_bytes()), {"seed": 23}, current_key_inputs=_current(template))
    assert list(warm.workflow.metadata["ordered"]) == ["z", "a"]
    assert warm.workflow.metadata["ordered"]["a"] == (2, 3)
    assert warm.workflow.metadata["tag-shaped-literal"] == ["slot", "seed"]
    assert warm.workflow.nodes["1"].metadata["provenance"] is Provenance.AGENT_AUTHORED
    assert warm.workflow.inputs["seed"].default == 7
    assert warm.workflow._manual_input_names == {"seed"}
    assert warm.workflow._canonical_v2_recursive_custody is None
    assert warm.workflow._recursive_definition_captures is None
    cold.workflow.metadata["ordered"]["z"].append(999)
    cold.workflow.nodes["1"].inputs["value"] = -1
    assert warm.workflow.metadata["ordered"]["z"] == [1]
    assert warm.workflow.nodes["1"].inputs["value"] == 23
    assert warm.workflow.inputs["seed"].value == 23
    assert workflow.nodes["1"].inputs["value"] == 7
    assert cold.snapshot().to_bytes() == template.to_bytes()


def test_json_slot_keeps_request_order_and_never_aliases_occurrences() -> None:
    workflow = _workflow()
    workflow.nodes["1"].inputs["value"] = {"authored": True}
    workflow.inputs["seed"].value = {"authored": True}
    slots = (ValueSlot("value", _slots()[0].paths),)
    template = prepare_template(workflow, slots, key_context=_context())
    request = {"z": [1], "a": ["slot", "value"]}
    filled = fill_template(template, {"value": request}, current_key_inputs=_current(template))
    assert list(filled.workflow.nodes["1"].inputs["value"]) == ["z", "a"]
    filled.workflow.nodes["1"].inputs["value"]["z"].append(2)
    assert filled.workflow.inputs["seed"].value["z"] == [1]
    assert request["z"] == [1]


@pytest.mark.parametrize("value", [["1", 0], ["105::6", 2], [7, 0]])
def test_link_shaped_json_slot_requires_full_preparation(value) -> None:
    slots = (ValueSlot("seed", _slots()[0].paths),)
    template = prepare_template(_workflow(), slots, key_context=_context())
    with pytest.raises(TemplateNotReusable, match="unwitnessed graph-link shape") as error:
        fill_template(template, {"seed": value}, current_key_inputs=_current(template))
    assert error.value.reason == "entry_invalid"
    changed = _workflow()
    changed.nodes["1"].inputs["value"] = value
    changed.inputs["seed"].value = value
    with pytest.raises(TemplateNotReusable, match="unwitnessed graph-link shape"):
        prepare_template(changed, slots, key_context=_context())


@pytest.mark.parametrize("value", [True, "19", None, 1.5, float("nan")])
def test_slot_type_errors_are_current_input_refusals(value) -> None:
    template = prepare_template(_workflow(), _slots(), key_context=_context())
    with pytest.raises(ValueError) as error:
        fill_template(template, {"seed": value}, current_key_inputs=_current(template))
    assert not isinstance(error.value, TemplateNotReusable)


@pytest.mark.parametrize("values", [{}, {"seed": 1, "extra": 2}])
def test_every_fill_requires_exactly_the_current_slot_set(values) -> None:
    template = prepare_template(_workflow(), _slots(), key_context=_context())
    with pytest.raises(ValueError, match="exactly one current value"):
        fill_template(template, values, current_key_inputs=_current(template))


@pytest.mark.parametrize("path", [
    ("id",), ("nodes", "1", "class_type"), ("nodes", "1", "mode"),
    ("edges", 0, "to_node"), ("inputs", "seed", "node_id"), ("default_variant",),
])
def test_structural_fields_cannot_be_value_slots(path) -> None:
    with pytest.raises(TemplateNotReusable, match="not a literal channel"):
        ValueSlot("selector", (path,))


def test_missing_overlapping_and_unknown_state_refuse_with_a_reason() -> None:
    workflow = _workflow()
    with pytest.raises(TemplateNotReusable, match="missing prepared literal"):
        prepare_template(workflow, (ValueSlot("missing", (("nodes", "1", "inputs", "missing"),)),), key_context=_context())
    with pytest.raises(TemplateNotReusable, match="overlapping"):
        prepare_template(workflow, (*_slots(), ValueSlot("other", (_slots()[0].paths[0],))), key_context=_context())
    workflow.unwitnessed_builder_state = object()
    with pytest.raises(TemplateNotReusable, match="unmodelled") as error:
        prepare_template(workflow, _slots(), key_context=_context())
    assert error.value.reason == "entry_invalid"


@pytest.mark.parametrize("damage", [
    "truncated", "duplicate_json", "foreign_format", "foreign_backend", "checksum",
    "unknown_field", "wrong_key", "wrong_structure", "unknown_record", "duplicate_map",
    "wrong_ir_shape", "unknown_slot", "invalid_layout",
])
def test_corrupt_or_foreign_records_are_explicit_misses(damage: str) -> None:
    template = prepare_template(_workflow(), _slots(), key_context=_context())
    record = template.to_record()
    if damage == "truncated":
        data = template.to_bytes()[:len(template.to_bytes()) // 2]
    elif damage == "duplicate_json":
        data = b'{"format":1,"format":2}'
    else:
        recipe_fields = dict(record["payload"]["recipe"][2])
        if damage == "foreign_format":
            record["format"] = "foreign/v1"
        elif damage == "foreign_backend":
            record["backend"] = "another-backend"
        elif damage == "checksum":
            record["content_digest"] = "sha256:" + "0" * 64
        elif damage == "unknown_field":
            record["surprise"] = True
        elif damage == "wrong_key":
            record["key"] = "sha256:" + "0" * 64
        elif damage == "wrong_structure":
            recipe_fields["id"][1] = "modified-source"
        elif damage == "unknown_record":
            record["payload"]["recipe"][1] = "ArbitraryPythonClass"
        elif damage == "duplicate_map":
            record["payload"]["recipe"][2].append(record["payload"]["recipe"][2][0])
        elif damage == "wrong_ir_shape":
            recipe_fields["nodes"][:] = ["atom", 5]
        elif damage == "unknown_slot":
            record["payload"]["slots"][0]["name"] = "not-in-recipe"
        else:
            record["payload"]["layouts"] = [{"signature": {}, "layout": {"unknown": True}}]
        data = canonical_bytes(record) if damage == "checksum" else _seal(record)
    with pytest.raises(TemplateNotReusable) as error:
        PreparedTemplate.from_bytes(data)
    assert error.value.reason == "entry_invalid"


def test_live_process_objects_are_not_serialized() -> None:
    workflow = _workflow()
    workflow._workflow_context_token = object()
    with pytest.raises(TemplateNotReusable, match="active workflow context"):
        prepare_template(workflow, _slots(), key_context=_context())
    workflow._workflow_context_token = None
    workflow.metadata["provider"] = object()
    with pytest.raises(TemplateNotReusable, match="unsupported recipe type"):
        prepare_template(workflow, _slots(), key_context=_context())


_PROCESS_SCRIPT = r'''
import json
import sys
from pathlib import Path
from tests.test_prepared_template import _context, _current, _slots, _workflow
from vibecomfy.prepared_template import PreparedTemplate, TemplateKeyChanged, fill_template, prepare_template
mode, filename, change = sys.argv[1:]
path = Path(filename)
if mode == "write":
    template = prepare_template(_workflow(), _slots(), key_context=_context())
    path.write_bytes(template.to_bytes())
    print(json.dumps({"key": template.key}))
else:
    template = PreparedTemplate.from_bytes(path.read_bytes())
    current = _current(template)
    if change != "none":
        for pair in current:
            if pair[0] == change:
                pair[1] = ("sha256:" + "d" * 64 if change in {"structure", "node_list_digest"}
                           else "3.0.0" if change == "vibecomfy_version" else {"current": "changed"})
    try:
        filled = fill_template(template, {"seed": 987654321}, current_key_inputs=current)
    except TemplateKeyChanged as exc:
        print(json.dumps({"miss": exc.reason}))
    else:
        print(json.dumps({"key": template.key, "value": filled.workflow.inputs["seed"].value}))
'''


@pytest.mark.parametrize("change", ["none", *KEY_FIELDS[2:]])
def test_two_processes_share_recipe_and_reject_stale_current_key(tmp_path: Path, change: str) -> None:
    path = tmp_path / "entry.json"
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    def run(mode):
        result = subprocess.run([sys.executable, "-c", _PROCESS_SCRIPT, mode, str(path), change],
                                cwd=root, env=env, check=False, text=True, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout.strip().splitlines()[-1])
    written = run("write")
    read = run("read")
    if change == "none":
        assert read == {"key": written["key"], "value": 987654321}
    else:
        assert read == {"miss": f"key_changed:{change}"}
    # No process/session issuance token has to accompany the data file.
    assert b"987654321" not in path.read_bytes()
