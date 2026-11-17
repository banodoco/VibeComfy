"""Every default crosses the real selected-target bundle approval boundary.

These are recorded schema / synthetic inventory cells, not GPU execution or
installed-pack commit proof. The original 13,000 raw compiler comparisons stay
separate and unchanged. No validator, custody check or compiler is replaced.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from vibecomfy.model_assets import _subdir_for_model_reference
from vibecomfy.schema.provider import TargetSchemaProvider
from vibecomfy.security.provenance import Provenance
from vibecomfy.testing.canonical import canonical_bytes
from vibecomfy.workflow_bundle import load_bundle


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "tests/fixtures/prepared_default_target_inventory.json"
DEFAULTS = tuple(json.loads(INVENTORY_PATH.read_text())["defaults"])
TARGET_URL = "http://ls4-fixture-target.invalid:8188"
SCHEMA_CAPTURES = (
    "comfy_core@cpu-runtime.json",
    "ComfyUI-QwenTTS@cpu-runtime.json",
    "ComfyUI-KJNodes@cpu-runtime.json",
    "ComfyUI-VideoHelperSuite@cpu-runtime.json",
    "rgthree-comfy@cpu-runtime.json",
    "ComfyUI-HunyuanVideo_Foley@source-b94f7ac.json",
    # This historical capture has no installed-commit witness. The test does
    # not manufacture one from the workflow's lock declaration.
    "ComfyUI-LTXVideo@runpod-snapshot.json",
)


@pytest.fixture(scope="module")
def recorded_target():
    inventory = json.loads(INVENTORY_PATH.read_text())
    rows = {}
    for filename in SCHEMA_CAPTURES:
        capture = json.loads((ROOT / "vibecomfy/porting/cache/object_info" / filename).read_text())
        for name, row in capture.items():
            # Preserve the current CPU core schema when an older custom
            # snapshot also contains the same class.
            rows.setdefault(name, row)
    return rows, inventory


def selected_target(bundle, recorded_target):
    rows, inventory = recorded_target
    object_info = {}
    for node in bundle.workflow.nodes.values():
        if node.class_type not in rows:
            # UI-only helpers need not be executable target classes. The
            # real compiler and requirement checks decide that distinction.
            continue
        row = copy.deepcopy(rows[node.class_type])
        for fields in row.get("inputs", {}).values():
            if not isinstance(fields, dict):
                continue
            for name, declaration in fields.items():
                folder = _subdir_for_model_reference(node.class_type, name)
                override = inventory["picker_overrides"].get(f"{node.class_type}.{name}")
                if override is not None:
                    declaration[0] = list(override)
                elif folder in inventory["picker_choices"] and isinstance(declaration, list):
                    # Only file availability is synthetic. Keep required
                    # flags, ranges, options, dynamic fields and all other
                    # recorded structural/schema provenance intact.
                    declaration[0] = list(inventory["picker_choices"][folder])
                elif (node.class_type, name) == ("LoadImage", "image"):
                    declaration[0] = [inventory["input_files"]["image"]]
        object_info[node.class_type] = row
    provider = TargetSchemaProvider.from_object_info(
        object_info, server_url=TARGET_URL,
        model_availability="target", auxiliary_model_custody="target",
        target_model_assets=inventory["target_model_assets"],
    )
    # Both paths use this same selected target, including graph compilation's
    # schema lookup (which otherwise defaults to authoring metadata).
    for node in bundle.workflow.nodes.values():
        schema = provider.get_schema(node.class_type)
        if schema is not None:
            node.metadata["schema"] = schema
    return provider


def target_case(template_id, recorded_target):
    bundle = load_bundle(template_id, trust=Provenance.USER_CONFIRMED)
    provider = selected_target(bundle, recorded_target)
    _, inventory = recorded_target
    values = {}
    for name, spec in bundle.workflow.inputs.items():
        value = spec.value if spec.value is not None else spec.default
        if spec.media_semantics in inventory["input_files"]:
            value = inventory["input_files"][spec.media_semantics]
        if value is not None:
            values[name] = value
    return bundle, provider, values


@pytest.mark.parametrize("template_id", DEFAULTS)
def test_default_full_bundle_compile(template_id, recorded_target, tmp_path, record_property):
    """Also runnable unchanged against the packet base, which has no prepared API."""
    bundle, provider, values = target_case(template_id, recorded_target)
    record_property("target_schema_digest", provider._object_info_digest)
    record_property("inventory_source_revision", recorded_target[1]["source_revision"])
    full_default = bundle.compile(run_inputs=values, schema_provider=provider, models_root=tmp_path)
    record_property("default_full_compile_digest", full_default.api_digest)
    assert full_default.api_projection
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("template_id", DEFAULTS)
def test_default_matches_real_bundle_compile_with_selected_target(
    template_id, recorded_target, tmp_path, record_property,
):
    from tests.test_prepared_default_workflows import DEFAULTS as VARIED_DEFAULTS
    from tests.test_prepared_workflow import context, reference_api
    from vibecomfy.prepared import PreparedWorkflowSession

    assert DEFAULTS == VARIED_DEFAULTS
    bundle, provider, values = target_case(template_id, recorded_target)
    record_property("target_schema_digest", provider._object_info_digest)
    record_property("inventory_source_revision", recorded_target[1]["source_revision"])

    ctx = context(target_identity=TARGET_URL, schema_digest=provider._object_info_digest)
    session = PreparedWorkflowSession(ctx)
    handle = session.prepare(bundle, inputs=values, schema_provider=provider)
    record, _ = session.fill(handle, values, attempt_id="target-proof", context=ctx)
    record_property("prepared_compile_digest", record.api_digest)
    reference, bindings = reference_api(bundle, values, record.output_identity)
    full_job = load_bundle(reference).compile(
        run_inputs=bindings, schema_provider=provider, models_root=tmp_path,
    )
    record_property("job_full_compile_digest", full_job.api_digest)
    assert canonical_bytes(record.api_projection) == canonical_bytes(full_job.api_projection)
    assert record.api_digest == full_job.api_digest
    assert not list(tmp_path.iterdir())  # No local model download or model-byte stand-in.

