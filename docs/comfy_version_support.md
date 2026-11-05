# ComfyUI version support

CPU qualification of the Phase 2 default graphs uses the exact core node
schemas in official ComfyUI **v0.43.0**, commit
`426f5eea52a7ece1dd599fff4cb6cd1f352ddd24` (release 2026-10-27).
`vibecomfy/comfy_metadata.json` owns that upstream source qualification tuple.
The source-derived schema shard retains immutable URLs, source hashes and
unresolved dynamic expressions. It is not a live `/object_info` capture.

The optional `vibecomfy[comfy]` dependency remains the **HiddenSwitch/AppMana
packaged fork**, now `comfyui==0.43.0.2`, at fork source commit
`ff7644a70dba1707f4caee52576496ce848792f8`. Its runtime compatibility tuple is
in `vibecomfy/registry/comfy_version_matrix.json`; `uv.lock` owns package
artifacts and dependency resolution. This is not a direct official upstream
installation. The fork's whole-tree ancestry/equivalence to the official
release is unproven. Music 3's node source matches upstream; Qwen's source has
fork import changes. A version match does not prove installed ABI or inference.

`tests/test_comfy_version_compat.py` checks the five scoped graphs against
those exact source schemas using the existing schema provider and node-call
validator. Dynamic model/file choices are not proof of target asset custody.
Qwen3-TTS and Foley custom node schemas/pins remain separately recorded by
their existing template and custom-node lock machinery.

The selected defaults are Qwen3-TTS CustomVoice 0.6B, MiniMax Music 3,
HunyuanVideo-Foley, Qwen-Image-2.1 Turbo, and its edit adapter. Qwen3-TTS
`voice` selects a named speaker; it does not promise 1.7B instruction control.
TTS's complete inference file paths are pinned to one model repository
revision with byte sizes and SHA-256 from retained source metadata (weights)
and the prior read-only file audit (configs/tokenizers). Installed auto-download
behavior remains unqualified. Prestage and verify assets before runtime use.

H3_AV remains deferred pending the owner's Ref2VA/FL2V LoRA and capacity
decision. Previous-release, ahead-candidate and upstream-main execution,
installed node imports, model loads, GPU generation, VRAM, quality and
completed target delivery are not established by these CPU checks.

Run the focused compatibility checks from the selected checkout:

```sh
pytest -q tests/test_comfy_version_compat.py
```
