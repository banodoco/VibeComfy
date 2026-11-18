"""LS-12: content-verified class evidence is held for one canonical emission."""
import json
import os

import pytest

from vibecomfy.errors import ObjectInfoCacheCorruptError
from vibecomfy.porting.object_info import consume
from vibecomfy.porting.object_info.serialize import build_cache
from vibecomfy.security.provenance import Provenance
from vibecomfy.workflow import VibeWorkflow, WorkflowSource
from vibecomfy.workflow_bundle import emit_bundle, load_bundle


@pytest.mark.parametrize("helper,expected", [
    ("object_info_widget_value_order", ["value"]),
    ("output_names", ["IMAGE"]),
    ("output_types", ["IMAGE"]),
])
def test_scalar_helper_holds_snapshot_then_detects_same_size_edit(tmp_path, monkeypatch, helper, expected):
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"LS12Fixture": {
        "name": "LS12Fixture", "python_module": "ls12_fixture", "category": "",
        "input": {"required": {"value": ["STRING", {"default": "a"}]}},
        "input_order": {"required": ["value"]},
        "output": ["IMAGE"], "output_name": ["IMAGE"], "output_is_list": [False],
    }}))
    root = tmp_path / "cache"
    build_cache(str(source), version="ls12", cache_dir=str(root), full_pack_refresh=True)
    monkeypatch.setattr(consume, "CACHE_DIR", root)
    monkeypatch.setattr(consume, "_reader_state", None)
    monkeypatch.setattr(consume, "_index", None)
    monkeypatch.setattr(consume, "_pack_cache", {})
    call = getattr(consume, helper)
    assert call("LS12Fixture") == expected
    with consume.class_entry_snapshot(["LS12Fixture"]):
        active = consume._reader_state["active"]
        pack = active / json.loads((active / "index.json").read_text())["LS12Fixture"]
        original = pack.read_text()
        stamp = pack.stat()
        edited = original.replace('"value"', '"other"').replace('"IMAGE"', '"VIDEO"')
        assert edited != original and len(edited.encode()) == stamp.st_size
        pack.write_text(edited)
        os.utime(pack, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert call("LS12Fixture") == expected
        with pytest.raises(ObjectInfoCacheCorruptError, match="not captured"):
            call("UnrequestedClass")
    with pytest.raises(ObjectInfoCacheCorruptError, match="hash check"):
        call("LS12Fixture")


def test_canonical_emission_reader_passes_do_not_scale_with_node_count(tmp_path, monkeypatch):
    calls = []
    original = consume._sync_reader

    def observe():
        calls.append(None)
        return original()

    monkeypatch.setattr(consume, "_sync_reader", observe)
    passes = []
    for count in (1, 6):
        workflow = VibeWorkflow("ls12-emission", WorkflowSource("ls12-emission"))
        for index in range(count):
            workflow.add_node("Integer", uid=f"integer-{index}", value=index)
        calls.clear()
        path = tmp_path / str(count) / "workflow.py"
        bundle = emit_bundle(workflow, path, {"operation": "authored"})
        passes.append(len(calls))
        reopened = load_bundle(path, trust=Provenance.USER_CONFIRMED)
        assert reopened.semantic_digest == bundle.semantic_digest
        assert len(reopened.workflow.nodes) == count
    assert passes[0] == passes[1]
    assert 0 < passes[0] <= 4
