"""A committed provider must match admission even before its first lookup."""
import hashlib
import json
import os

import pytest

from vibecomfy.errors import ObjectInfoCacheCorruptError
from vibecomfy.porting.object_info import consume
from vibecomfy.porting.object_info.serialize import build_cache
from vibecomfy.workflow import VibeWorkflow, WorkflowSource
from vibecomfy.workflow_bundle import emit_bundle


@pytest.mark.parametrize("lookup", ["batch", "scalar", "identity", "emission"])
@pytest.mark.parametrize("edited", [False, True])
def test_first_use_of_committed_provider_matches_admitted_bytes(
    tmp_path, monkeypatch, lookup, edited,
):
    # Build the IR before installing the fixture reader, so authoring cannot
    # accidentally prime pack B in the reader whose first use is under test.
    workflow = VibeWorkflow("ls12-first-provider", WorkflowSource("ls12-first-provider"))
    workflow.add_node("Float", uid="value", value=1.0)
    cache = tmp_path / "cache"
    for name, kind, slug, commit in (
        ("Integer", "INT", "ls12-a", "a" * 40),
        ("Float", "FLOAT", "ls12-b", "b" * 40),
    ):
        source = tmp_path / (slug + ".json")
        source.write_bytes(json.dumps({name: {
            "name": name, "python_module": slug, "description": "admitted",
            "input": {"required": {"value": [kind, {"default": 1}]}},
            "input_order": {"required": ["value"]},
            "output": [kind], "output_name": [kind], "output_is_list": [False],
        }}).encode("utf-8"))
        build_cache(source, version="ls12", cache_dir=cache, pack_slug=slug,
                    pack_version="ls12", git_commit=commit,
                    source_kind="executed_object_info", full_pack_refresh=True)
    monkeypatch.setattr(consume, "CACHE_DIR", cache)
    monkeypatch.setattr(consume, "_reader_state", None)
    monkeypatch.setattr(consume, "_index", None)
    monkeypatch.setattr(consume, "_pack_cache", {})

    # Admission validates the generation containing A and B, while this first
    # bounded operation loads only A into the consumer's retained pack cache.
    with consume.class_entry_snapshot(["Integer"]):
        assert consume.output_types("Integer") == ["INT"]
    active = consume._reader_state["active"]
    filename = json.loads((active / "index.json").read_bytes())["Float"]
    assert filename not in consume._pack_cache
    path = active / filename
    original = path.read_bytes()
    expected = json.loads((active / "manifest.json").read_bytes())["files"][filename]
    assert hashlib.sha256(original).hexdigest() == expected
    if edited:
        stamp = path.stat()
        changed = original.replace(b'"admitted"', b'"tampered"')
        assert changed != original and len(changed) == stamp.st_size
        path.write_bytes(changed)
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert path.stat().st_size == stamp.st_size
        assert path.stat().st_mtime_ns == stamp.st_mtime_ns
        assert hashlib.sha256(path.read_bytes()).hexdigest() != expected

    def first_use():
        if lookup == "batch":
            return consume.get_classes(["Float"])["Float"]
        if lookup == "scalar":
            return consume.get_class("Float")
        if lookup == "identity":
            return consume.get_class_by_identity("Float", pack_slug="ls12-b", git_commit="b" * 40)
        return emit_bundle(workflow, tmp_path / "emitted" / "workflow.py", {"operation": "authored"})

    if edited:
        with pytest.raises(ObjectInfoCacheCorruptError, match="failed its hash check"):
            first_use()
    else:
        assert first_use() is not None
