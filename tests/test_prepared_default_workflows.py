"""Exact API-byte equivalence for every shipped default/catalog workflow.

H3's executable hooks are covered by the Agent fallback test. This roster is
pinned to the union of generation.defaults/builtin.yaml and the local model
catalog at Agent 19103ea6. It deliberately includes the four audio defaults.
"""
from __future__ import annotations

import statistics
import time

import pytest

from vibecomfy.prepared import PreparedWorkflowSession
from vibecomfy.security.provenance import Provenance
from vibecomfy.testing.canonical import canonical_bytes
from vibecomfy.workflow_bundle import load_bundle
from tests.test_prepared_workflow import context, reference_api

DEFAULTS = (
    "audio/ace_step_1_5_t2a_song",
    "audio/hunyuan_video_foley",
    "audio/minimax_music_3",
    "audio/qwen3_tts_custom_voice",
    "edit/qwen_image_2_1_turbo_edit",
    "edit/qwen_image_edit",
    "image/qwen_image_2512",
    "image/qwen_image_2_1_turbo",
    "image/z_image_img2img",
    "image/z_image_turbo",
    "video/ltx2_3_i2v",
    "video/ltx2_3_runexx_first_last_frame",
    "video/ltx2_3_t2v",
)


def values_for(workflow, index):
    values = {}
    for name, spec in workflow.inputs.items():
        value = spec.value if spec.value is not None else spec.default
        if value is None:
            continue
        if type(value) is bool:
            value = bool(index % 2)
        elif type(value) is int:
            if "seed" in name:
                value = index * 982451653 + 13
            elif name in {"width", "height"}:
                value = (512, 768, 1024)[index % 3]
            elif name == "frames":
                value = 9 + 8 * (index % 5)
            elif name == "steps":
                value = 4 + 2 * (index % 4)
            elif name == "fps":
                value = 24 + index % 7
            else:
                value = value + index % 3
        elif type(value) is float:
            value = float(value) + (index % 4) * 0.03125
        elif type(value) is str:
            if spec.field == "filename_prefix":
                value = f"proof/output-{index}"
            elif getattr(spec, "media_semantics", None) in {"image", "mask", "video", "audio"}:
                value = f"astrid/input-{index}.png"
            elif name in {"prompt", "text", "negative", "negative_prompt", "lyrics"}:
                value = f"snow, café, 雪 🌨 {index}\nline two" if index % 3 else ""
            elif any(part in name for part in ("model", "encoder", "vae")):
                value = value if index % 2 else f"proof/model-{index}.safetensors"
            # Enumerated runtime switches/voices retain an advertised spelling.
        else:
            raise AssertionError(f"default {workflow.id} has unsupported public value {name}: {type(value)}")
        values[name] = value
    return values


@pytest.mark.parametrize("template_id", DEFAULTS)
def test_every_default_admits_a_typed_template(template_id):
    bundle = load_bundle(template_id, trust=Provenance.USER_CONFIRMED)
    session = PreparedWorkflowSession(context())
    handle = session.prepare(bundle, inputs=values_for(bundle.workflow, 1))
    assert session.key(handle)


@pytest.mark.parametrize("template_id", DEFAULTS)
def test_thousand_values_match_full_compile_byte_for_byte(template_id, record_property):
    bundle = load_bundle(template_id, trust=Provenance.USER_CONFIRMED)
    ctx = context()
    session = PreparedWorkflowSession(ctx)
    handle = session.prepare(bundle, inputs=values_for(bundle.workflow, 1))
    samples = []
    prefixes = set()
    for index in range(1000):
        values = values_for(bundle.workflow, index)
        started = time.perf_counter_ns()
        record, frozen = session.fill(handle, values, attempt_id=f"attempt-{index}", context=ctx)
        samples.append((time.perf_counter_ns() - started) / 1e6)
        reference, bindings = reference_api(bundle, values, record.output_identity)
        expected = reference.compile("api", run_inputs=bindings)
        assert canonical_bytes(record.api_projection) == canonical_bytes(expected), (template_id, index)
        assert frozen.workflow.id == bundle.workflow.id
        for output in bundle.workflow.outputs:
            prefix = record.api_projection[str(output.node_id)]["inputs"]["filename_prefix"]
            assert prefix not in prefixes, (template_id, index, prefix)
            prefixes.add(prefix)
    median, worst = statistics.median(samples), max(samples)
    record_property("prepared_samples", 1000)
    record_property("prepared_fill_median_ms", median)
    record_property("prepared_fill_max_ms", worst)
    assert worst < 5, {"template": template_id, "median_ms": median, "max_ms": worst}
    print({"template": template_id, "samples": 1000, "median_ms": median, "max_ms": worst})
