"""Exercise both internal end-check strategies and their stated limits."""
import os

import pytest

from vibecomfy.errors import ObjectInfoCacheCorruptError
from vibecomfy.porting.object_info import consume


@pytest.mark.parametrize('stat_only', [False, True])
def test_end_check_detects_configured_root_repoint(tmp_path, monkeypatch, stat_only):
    first, second, link = tmp_path / 'first', tmp_path / 'second', tmp_path / 'cache'
    first.mkdir()
    second.mkdir()
    (first / 'index.json').write_text('{}')
    (second / 'index.json').write_text('{}')
    link.symlink_to(first, target_is_directory=True)
    monkeypatch.setattr(consume, 'CACHE_DIR', link)
    monkeypatch.setattr(consume, '_index', None)
    monkeypatch.setattr(consume, '_pack_cache', {})
    monkeypatch.setattr(consume, '_reader_state', None)
    if stat_only:
        monkeypatch.setattr(consume, '_bundle_end_witness', consume._bundle_end_stat_witness)
    owner = consume._BundleClassMemo()
    owner.observe_root(first.resolve())
    owner.observe(first / 'index.json', consume._cache_file_witness(first / 'index.json'))
    link.unlink()
    link.symlink_to(second, target_is_directory=True)
    with pytest.raises(ObjectInfoCacheCorruptError):
        owner.validate()


@pytest.mark.parametrize('stat_only', [False, True])
def test_end_check_same_size_restored_mtime_limit(tmp_path, monkeypatch, stat_only):
    cache = tmp_path / 'cache'
    cache.mkdir()
    path = cache / 'index.json'
    path.write_text('{"A": 1}')
    monkeypatch.setattr(consume, 'CACHE_DIR', cache)
    monkeypatch.setattr(consume, '_index', None)
    monkeypatch.setattr(consume, '_pack_cache', {})
    monkeypatch.setattr(consume, '_reader_state', None)
    if stat_only:
        monkeypatch.setattr(consume, '_bundle_end_witness', consume._bundle_end_stat_witness)
    owner = consume._BundleClassMemo()
    owner.observe_root(cache.resolve())
    owner.observe(path, consume._cache_file_witness(path))
    before = path.stat()
    path.write_text('{"A": 2}')
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_ino == before.st_ino and path.stat().st_size == before.st_size
    if stat_only:
        owner.validate()  # The approved stat-only limitation is observable.
    else:
        with pytest.raises(ObjectInfoCacheCorruptError):
            owner.validate()
