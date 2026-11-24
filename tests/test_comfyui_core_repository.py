"""The shipped core provider identity is owned by VibeComfy, not consumers."""
import pytest

from vibecomfy.node_packs import get_known_node_packs, is_comfyui_core_repo


@pytest.mark.parametrize("repo", [
    "https://github.com/Comfy-Org/ComfyUI",
    "https://github.com/Comfy-Org/ComfyUI.git",
    "https://github.com/comfyanonymous/ComfyUI.git/",
    "https://GITHUB.COM/COMFY-ORG/COMFYUI.git",
])
def test_upstream_comfyui_repository_names(repo):
    assert is_comfyui_core_repo(repo)


@pytest.mark.parametrize("repo", [
    "https://github.com/example/ComfyUI.git",
    "https://github.com/Comfy-Org/ComfyUI-Manager",
    "https://github.com/Comfy-Org/ComfyUI/tree/master",
    "https://github.com.example.invalid/Comfy-Org/ComfyUI",
    "https://user@github.com/Comfy-Org/ComfyUI",
    "https://github.com:444/Comfy-Org/ComfyUI",
    "https://github.com/Comfy-Org/ComfyUI?ref=main",
    "https://github.com/Comfy-Org/ComfyUI#main",
    "https://[bad",
    "git@github.com:Comfy-Org/ComfyUI.git",
    "",
])
def test_other_sources_are_not_core(repo):
    assert not is_comfyui_core_repo(repo)


def test_shipped_core_pack_rows_use_the_same_identity():
    packs = {pack.name: pack for pack in get_known_node_packs()}
    assert is_comfyui_core_repo(packs["comfy-core-fallback"].repo)
    assert is_comfyui_core_repo(packs["comfy_extras"].repo)
    assert not is_comfyui_core_repo(packs["ComfyUI-SAM-Audio"].repo)
