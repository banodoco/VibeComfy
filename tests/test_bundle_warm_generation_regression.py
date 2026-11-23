"""A warm, otherwise unused generation pack remains an emission dependency."""
import collections
import json
import threading

import pytest

from vibecomfy.errors import ObjectInfoCacheCorruptError
from vibecomfy.porting.object_info import consume
from vibecomfy.porting.object_info.serialize import build_cache
from vibecomfy.workflow import VibeWorkflow, WorkflowSource
from vibecomfy.workflow_bundle import emit_bundle


def test_warm_unused_pack_corruption_refuses_before_publication(tmp_path, monkeypatch):
    source = tmp_path / "one.json"
    source.write_text(json.dumps({"Spare": {"python_module": "custom_nodes.Spare.nodes", "input": {"required": {"value": ["INT"]}}, "output": ["INT"]}}))
    cache = tmp_path / "cache"
    build_cache(source, version="v1", cache_dir=cache)
    monkeypatch.setattr(consume, "CACHE_DIR", cache)
    generation = cache / "generations" / (cache / "CURRENT").read_text().strip()
    pack = next(generation.glob("custom_nodes*.json"))
    assert consume.get_class("Spare")

    workflow = VibeWorkflow("sample", WorkflowSource("sample"))
    workflow.add_node("Integer", uid="integer-node", value=7)
    original = consume._resolve_class_type
    hits = collections.Counter()
    replaced = threading.Event()

    def resolve(class_type):
        hits[class_type] += 1
        if hits[class_type] == 2 and consume._CLASS_ENTRY_SNAPSHOT.get() is None:
            def replace():
                pack.write_text("[]")
                replaced.set()
            thread = threading.Thread(target=replace)
            thread.start()
            thread.join()
        return original(class_type)

    monkeypatch.setattr(consume, "_resolve_class_type", resolve)
    output = tmp_path / "workflow.py"
    with pytest.raises(ObjectInfoCacheCorruptError, match="failed its hash check"):
        emit_bundle(workflow, output, {"operation": "authored"})
    assert replaced.is_set()
    assert not output.exists()
    assert not (tmp_path / "workflow.vibe.json").exists()
