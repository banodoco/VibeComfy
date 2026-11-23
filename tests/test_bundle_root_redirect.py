"""A bundle must reject a configured cache directory redirected mid-emit."""
import shutil
import threading

import pytest

from vibecomfy.errors import ObjectInfoCacheCorruptError
from vibecomfy.porting.object_info import consume
from vibecomfy.workflow import VibeWorkflow, WorkflowSource
from vibecomfy.workflow_bundle import emit_bundle


def test_emit_refuses_redirected_configured_cache(tmp_path, monkeypatch):
    cache = tmp_path / 'cache'
    shutil.copytree(consume.CACHE_DIR, cache)
    replacement = tmp_path / 'replacement'
    shutil.copytree(cache, replacement)
    (replacement / 'index.json').write_text('[]')
    configured = tmp_path / 'configured'
    configured.symlink_to(cache, target_is_directory=True)
    monkeypatch.setattr(consume, 'CACHE_DIR', configured)
    original = consume._resolve_class_type
    hits = 0

    def resolve(class_type):
        nonlocal hits
        if class_type == 'Integer' and consume._CLASS_ENTRY_SNAPSHOT.get() is None:
            hits += 1
            if hits == 2:
                def redirect():
                    link = tmp_path / 'new-link'
                    link.symlink_to(replacement, target_is_directory=True)
                    link.replace(configured)
                thread = threading.Thread(target=redirect)
                thread.start()
                thread.join()
        return original(class_type)

    monkeypatch.setattr(consume, '_resolve_class_type', resolve)
    workflow = VibeWorkflow('sample', WorkflowSource('sample'))
    workflow.add_node('Integer', uid='integer-node', value=7)
    before = set(tmp_path.iterdir())
    with pytest.raises(ObjectInfoCacheCorruptError):
        emit_bundle(workflow, tmp_path / 'workflow.py', {'operation': 'authored'})
    assert hits >= 2
    assert set(tmp_path.iterdir()) == before
