"""Explicit bundle reader state has one invocation's lifetime."""
import json
import pytest
from vibecomfy.porting.object_info import consume


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(consume, 'CACHE_DIR', tmp_path)
    consume.reset_cache()
    (tmp_path / 'index.json').write_text(json.dumps({'A': 'pack.json', 'B': 'pack.json'}))
    (tmp_path / 'pack.json').write_text(json.dumps({'A': {'outputs': []}, 'B': 7}))
    yield tmp_path
    consume.reset_cache()


def test_bundle_memo_preserves_raw_results_and_is_per_invocation(cache, monkeypatch):
    reads = []
    original = consume._read_pack_at_root
    def read(root, name):
        reads.append(name)
        return original(root, name)
    monkeypatch.setattr(consume, '_read_pack_at_root', read)
    for invocation in range(2):
        state = consume.BundleReadSet()
        raw = consume._resolve_class_type('A', read_set=state)
        assert consume._resolve_class_type('A', read_set=state) is raw
        assert consume._resolve_class_type('B', read_set=state) == 7
        assert consume._resolve_class_type('missing', read_set=state) is None
        assert consume._resolve_class_type('missing', read_set=state) is None
        state.verify()
        assert len(reads) == invocation + 1


def test_bundle_memo_does_not_cache_exceptions(cache, monkeypatch):
    original = consume._read_pack_at_root
    calls = []
    def fail(root, name):
        calls.append(name)
        if len(calls) < 3:
            raise ValueError('broken')
        return original(root, name)
    monkeypatch.setattr(consume, '_read_pack_at_root', fail)
    state = consume.BundleReadSet()
    for _ in range(2):
        with pytest.raises(ValueError, match='broken'):
            consume._resolve_class_type('A', read_set=state)
    assert consume._resolve_class_type('A', read_set=state) == {'outputs': []}
    assert len(calls) == 3


def test_memo_is_not_used_inside_existing_snapshot(cache, monkeypatch):
    reads = []
    monkeypatch.setattr(consume, '_load_index', lambda: reads.append(1) or {})
    token = consume._CLASS_ENTRY_SNAPSHOT.set(object())
    try:
        state = consume.BundleReadSet()
        consume._resolve_class_type('A', read_set=state)
        consume._resolve_class_type('A', read_set=state)
    finally:
        consume._CLASS_ENTRY_SNAPSHOT.reset(token)
    assert len(reads) == 2
    assert not state.witnesses
