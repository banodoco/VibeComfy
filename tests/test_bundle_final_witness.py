"""Corruption during emission must be rejected before publishing files."""
import collections
import shutil
import threading

import pytest

from vibecomfy.porting.object_info import consume
from vibecomfy.errors import ObjectInfoCacheCorruptError
from vibecomfy.workflow import VibeWorkflow, WorkflowSource
from vibecomfy.workflow_bundle import emit_bundle


def _workflow():
    workflow = VibeWorkflow('sample', WorkflowSource('sample'))
    workflow.add_node('Integer', uid='integer-node', value=7)
    return workflow


def test_public_emitter_rejects_replaced_index(tmp_path, monkeypatch):
    cache = tmp_path / 'cache'
    shutil.copytree(consume.CACHE_DIR, cache)
    monkeypatch.setattr(consume, 'CACHE_DIR', cache)
    original = consume._resolve_class_type
    calls = collections.Counter()
    def resolve(class_type):
        calls[class_type] += 1
        if calls[class_type] == 2 and consume._CLASS_ENTRY_SNAPSHOT.get() is None:
            def replace():
                replacement = cache / 'other'
                replacement.write_text('[]')
                replacement.replace(cache / 'index.json')
            thread = threading.Thread(target=replace)
            thread.start()
            thread.join()
        return original(class_type)
    monkeypatch.setattr(consume, '_resolve_class_type', resolve)
    with pytest.raises(ObjectInfoCacheCorruptError, match='index must be an object'):
        emit_bundle(_workflow(), tmp_path / 'workflow.py', {'operation': 'authored'})
    assert not (tmp_path / 'workflow.py').exists()
    assert not (tmp_path / 'workflow.vibe.json').exists()


def test_warm_identity_fallback_rejects_corrupt_pack(tmp_path, monkeypatch):
    cache = tmp_path / 'cache'
    shutil.copytree(consume.CACHE_DIR, cache)
    monkeypatch.setattr(consume, 'CACHE_DIR', cache)
    (cache / "index.json").write_text('{"Integer": "test-pack.json"}')
    (cache / "test-pack.json").write_text('{"Integer": {"outputs": []}}')
    original = consume._resolve_class_type
    calls = collections.Counter()
    def resolve(class_type):
        calls[class_type] += 1
        result = original(class_type)
        if calls[class_type] == 1 and result is not None:
            filename = consume._load_index()[class_type]
            (cache / filename).write_text('[]')
            identity = consume.ObjectInfoIdentity(pack_slug='missing', git_commit='missing')
            consume.resolve_class_entry(class_type, identity, allow_class_fallback=True)
        return result
    monkeypatch.setattr(consume, '_resolve_class_type', resolve)
    with pytest.raises(ObjectInfoCacheCorruptError, match='provider file must be an object'):
        emit_bundle(_workflow(), tmp_path / 'workflow.py', {'operation': 'authored'})
    assert not (tmp_path / 'workflow.py').exists()
    assert not (tmp_path / 'workflow.vibe.json').exists()
