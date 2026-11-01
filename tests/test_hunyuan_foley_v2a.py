"""CPU round-trip checks for the Hunyuan-Foley V2A ready template.

Written without a run: no result is claimed until pytest is executed.
Asserts the built graph keeps the pinned model names, the seed and steps,
the video input reference, and the prompt text. Input names come from
BobRandomNumber/ComfyUI-HunyuanVideo_Foley @ b94f7aca877ff2be5bc264b057abee3dac682c1b.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "ready_templates" / "audio" / "hunyuan_foley_v2a.py"


def _load_template():
    spec = importlib.util.spec_from_file_location("hunyuan_foley_v2a", TEMPLATE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _nodes_by_class(workflow):
    nodes = {}
    for node in workflow.nodes.values():
        nodes.setdefault(node.class_type, []).append(node)
    return nodes


def test_template_is_marked_manual():
    head = TEMPLATE.read_text(encoding="utf-8").splitlines()[0]
    assert head == "# vibecomfy: manual"


def test_pinned_model_and_pack_identity_are_recorded():
    mod = _load_template()
    packs = mod.READY_METADATA.custom_node_packs if hasattr(mod.READY_METADATA, "custom_node_packs") else None
    text = TEMPLATE.read_text(encoding="utf-8")
    assert mod.PACK_COMMIT == "b94f7aca877ff2be5bc264b057abee3dac682c1b"
    assert "hunyuanvideo_foley_xl.pth" in text
    assert "vae_128d_48k.pth" in text
    assert "Tencent Hunyuan Community" in text
    assert packs is None or "ComfyUI-HunyuanVideo_Foley" in str(packs)


def test_public_bindings_carry_the_expected_defaults():
    # Sampler values come only from the InputSpec bindings, not from build().
    mod = _load_template()
    bindings = mod.PUBLIC_INPUT_METADATA
    assert bindings["seed"].node == "5" and bindings["seed"].field == "seed"
    assert bindings["seed"].default == mod.DEFAULT_SEED
    assert bindings["steps"].default == mod.DEFAULT_STEPS
    assert bindings["guidance_scale"].default == mod.DEFAULT_GUIDANCE
    assert bindings["prompt"].default == mod.DEFAULT_PROMPT
    assert bindings["negative_prompt"].default == mod.DEFAULT_NEGATIVE_PROMPT
    assert bindings["video"].node == "1" and bindings["video"].field == "file"


def test_graph_keeps_video_binding_and_model_names():
    # InputSpec registration needs the sampler fields present on node 5, so
    # build() sets them; this test checks the submitted graph values.
    mod = _load_template()
    workflow = mod.build()
    by_class = _nodes_by_class(workflow)

    samplers = by_class.get("HunyuanFoleySampler", [])
    assert len(samplers) == 1, "exactly one Foley sampler expected"
    inputs = samplers[0].inputs
    assert inputs["seed"] == mod.DEFAULT_SEED
    assert inputs["steps"] == mod.DEFAULT_STEPS
    assert inputs["guidance_scale"] == mod.DEFAULT_GUIDANCE
    assert inputs["prompt"] == mod.DEFAULT_PROMPT
    assert inputs["negative_prompt"] == mod.DEFAULT_NEGATIVE_PROMPT

    loaders = by_class.get("HunyuanFoleyModelLoader", [])
    assert len(loaders) == 1
    assert loaders[0].inputs["model_path_name"] == "hunyuan_foley"
    assert loaders[0].inputs["foley_checkpoint_name"] == "hunyuanvideo_foley_xl.pth"

    vae_loaders = by_class.get("LoadDACHunyuanVAE", [])
    assert len(vae_loaders) == 1
    assert vae_loaders[0].inputs["vae_name"] == "hunyuan_foley/vae_128d_48k.pth"

    load_videos = by_class.get("LoadVideo", [])
    assert len(load_videos) == 1
    assert load_videos[0].inputs["file"] == mod.DEFAULT_VIDEO
