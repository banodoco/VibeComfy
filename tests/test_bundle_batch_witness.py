"""A batch lookup must witness a provider already in the reader cache."""
import json

import pytest

from vibecomfy.errors import ObjectInfoCacheCorruptError
from vibecomfy.porting.object_info import consume
from vibecomfy.workflow_bundle import _validate_bundle_cache_witness, _with_bundle_class_memo


def test_batch_records_already_cached_provider(tmp_path, monkeypatch):
    (tmp_path / 'index.json').write_text(json.dumps({'Example': 'pack.json'}))
    pack = tmp_path / 'pack.json'
    pack.write_text(json.dumps({'Example': {'value': 7}}))
    monkeypatch.setattr(consume, 'CACHE_DIR', tmp_path)
    assert consume.get_class('Example')['value'] == 7

    @_with_bundle_class_memo
    def bundle():
        assert consume.get_classes(['Example'])['Example']['value'] == 7
        pack.write_text(json.dumps({'Example': {'value': 8}}))
        _validate_bundle_cache_witness()

    with pytest.raises(ObjectInfoCacheCorruptError, match='changed during bundle emission'):
        bundle()
