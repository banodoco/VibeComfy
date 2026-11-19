"""LS-12 admission requires the writer to publish the bytes it hashes."""
import json
from pathlib import Path

from vibecomfy.porting.object_info.generation import active_cache_root, validate_generation
from vibecomfy.porting.object_info.serialize import build_cache


def test_generation_manifest_matches_bytes_with_windows_text_newlines(tmp_path, monkeypatch):
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"LS12Fixture": {
        "name": "LS12Fixture", "python_module": "ls12_fixture", "category": "",
        "input": {"required": {"value": ["STRING", {"default": "a"}]}},
        "input_order": {"required": ["value"]}, "output": ["IMAGE"],
        "output_name": ["IMAGE"], "output_is_list": [False],
    }}), encoding="utf-8")
    original = Path.write_text

    def windows_text_write(path, data, *args, **kwargs):
        # Reproduce text-mode newline translation, independently of this host.
        kwargs.setdefault("newline", "\r\n")
        return original(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", windows_text_write)
    root = tmp_path / "cache"
    build_cache(str(source), version="ls12", cache_dir=str(root), full_pack_refresh=True)
    committed = active_cache_root(root)
    manifest = validate_generation(committed)
    assert "index.json" in manifest["files"]
    assert "ls12_fixture@ls12.json" in manifest["files"]
