"""Explicit identity lookups retain identity and fallback semantics."""
import json
import pytest
from vibecomfy.porting.object_info import consume


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(consume, 'CACHE_DIR', tmp_path)
    consume.reset_cache()
    key = json.dumps(['pack', 'git_commit', 'rev'], separators=(',', ':'))
    (tmp_path / 'index.json').write_text(json.dumps({'A': 'class.json', 'B': 'class.json', '__object_info_captures__': {key: ['identity.json']}}))
    (tmp_path / 'class.json').write_text(json.dumps({'A': {'outputs': ['class']}, 'B': {'outputs': ['other']}}))
    (tmp_path / 'identity.json').write_text(json.dumps({'A': {'pack_slug': 'pack', 'git_commit': 'rev', 'outputs': ['identity']}}))
    yield tmp_path
    consume.reset_cache()


def lookup(state, *, name='A', rev='rev', fallback=True):
    return consume.resolve_class_entry(name, {'pack_slug': 'pack', 'git_commit': rev}, allow_class_fallback=fallback, read_set=state)


def test_identity_hit_is_not_class_result(cache):
    state = consume.BundleReadSet()
    class_entry = consume._resolve_class_type('A', read_set=state)
    result = lookup(state, fallback=False)
    assert result.source == 'identity'
    assert result.entry['outputs'] == ['identity']
    assert result.entry != class_entry
    assert lookup(state, name='missing', fallback=False).source == 'identity_miss'


@pytest.mark.parametrize('warm', [None, 'A', 'B'])
@pytest.mark.parametrize('scenario', ['present', 'absent', 'corrupt'])
def test_identity_miss_fallback_matches_unmemoized_path(cache, warm, scenario):
    if scenario == 'absent':
        (cache / 'index.json').write_text('{}')
    elif scenario == 'corrupt':
        (cache / 'index.json').write_text('[]')
    def outcome(state):
        try:
            return ('result', lookup(state, rev='missing'))
        except Exception as exc:
            return ('error', type(exc), str(exc))
    expected = outcome(None)
    consume.reset_cache()
    state = consume.BundleReadSet()
    if warm:
        try:
            consume._resolve_class_type(warm, read_set=state)
        except Exception:
            assert scenario == 'corrupt'
    assert outcome(state) == expected
    if scenario == 'corrupt':
        assert outcome(state) == expected
