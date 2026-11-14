"""Local picker overrides must preserve the admitted Foley prompt by default."""
import pytest

from vibecomfy.registry.ready import workflow_from_ready
from vibecomfy.testing.canonical import canonical_digest


@pytest.mark.parametrize("name,node_id,class_type,field,default,override", [
    ("diffusion_model", "11", "HunyuanFoleyModelLoader", "foley_checkpoint_name",
     "hunyuanvideo_foley_xl.pth", "attached-foley.pth"),
    ("vae", "12", "LoadDACHunyuanVAE", "vae_name",
     "hunyuan_foley/vae_128d_48k.pth", "attached/vae.pth"),
])
def test_optional_foley_picker_updates_only_its_loader(
    name, node_id, class_type, field, default, override,
):
    workflow = workflow_from_ready("audio/hunyuan_video_foley")
    original = workflow.compile("api")
    assert canonical_digest(original) == "feceed6a8cb6da87af3f9a0303f9c35ec1ff37994dbd7d3000a40fe60d947d80"
    binding = workflow.inputs[name]
    assert (binding.node_id, binding.field, binding.type, binding.required) == (
        node_id, field, "COMBO", False,
    )
    assert binding.value == default
    assert original[node_id]["class_type"] == class_type
    assert original[node_id]["inputs"][field] == default
    workflow.set_input(name, override)
    expected = {key: {**node, "inputs": dict(node["inputs"])} for key, node in original.items()}
    expected[node_id]["inputs"][field] = override
    assert workflow.compile("api") == expected
