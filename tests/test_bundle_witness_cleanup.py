"""Final witness refusals leave destination and private staging clean."""
import collections
import json
import shutil
import tempfile
import threading

import pytest

from vibecomfy.errors import ObjectInfoCacheCorruptError
from vibecomfy.porting.object_info import consume
from vibecomfy.workflow import VibeWorkflow, WorkflowSource
from vibecomfy.workflow_bundle import emit_bundle


@pytest.mark.parametrize('mutation', ['invalid_index', 'valid_provider'])
def test_refusal_leaves_destination_and_staging_untouched(tmp_path, monkeypatch, mutation):
    cache = tmp_path / 'cache'
    shutil.copytree(consume.CACHE_DIR, cache)
    monkeypatch.setattr(consume, 'CACHE_DIR', cache)
    if mutation == 'valid_provider':
        (cache / 'index.json').write_text(json.dumps({'Integer': 'test-pack.json'}))
        (cache / 'test-pack.json').write_text(json.dumps({'Integer': {'outputs': [], 'value': 7}}))
    destination = tmp_path / 'destination'
    destination.mkdir()
    (destination / 'unrelated').write_bytes(b'keep')
    staging = tmp_path / 'private-staging'
    staging.mkdir()
    monkeypatch.setattr(tempfile, 'tempdir', str(staging))
    before = {p.name: p.read_bytes() for p in destination.iterdir()}
    original = consume._resolve_class_type
    calls = collections.Counter()

    def resolve(class_type):
        calls[class_type] += 1
        result = original(class_type)
        if calls[class_type] == 2 and consume._CLASS_ENTRY_SNAPSHOT.get() is None:
            def replace():
                if mutation == 'invalid_index':
                    replacement = cache / 'replacement'
                    replacement.write_text('[]')
                    replacement.replace(cache / 'index.json')
                else:
                    (cache / 'test-pack.json').write_text(
                        json.dumps({'Integer': {'outputs': [], 'value': 8}})
                    )
            thread = threading.Thread(target=replace)
            thread.start()
            thread.join()
        return result

    monkeypatch.setattr(consume, '_resolve_class_type', resolve)
    workflow = VibeWorkflow('sample', WorkflowSource('sample'))
    workflow.add_node('Integer', uid='integer-node', value=7)
    with pytest.raises(ObjectInfoCacheCorruptError):
        emit_bundle(workflow, destination / 'workflow.py', {'operation': 'authored'})
    assert {p.name: p.read_bytes() for p in destination.iterdir()} == before
    assert list(staging.iterdir()) == []
