import os

import pytest

from vibecomfy.errors import ObjectInfoCacheCorruptError
from vibecomfy.porting.object_info import consume


def test_pack_change_during_first_read_refuses_without_memoizing(tmp_path, monkeypatch):
    pack = tmp_path / "pack.json"
    old = '{"RaceNode": {"value": 7}}'
    new = '{"RaceNode": {"value": 8}}'
    assert len(old) == len(new)
    pack.write_text(old)
    (tmp_path / "index.json").write_text('{"RaceNode": "pack.json"}')
    original_stat = pack.stat()
    monkeypatch.setattr(consume, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(consume, "_reader_state", None)
    monkeypatch.setattr(consume, "_index", None)
    monkeypatch.setattr(consume, "_pack_cache", {})
    original_read = consume.read_json
    changed = False

    def replace_after_read(root, filename, **kwargs):
        nonlocal changed
        result = original_read(root, filename, **kwargs)
        if filename == "pack.json" and not changed:
            pack.write_text(new)
            os.utime(pack, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            changed = True
        return result

    monkeypatch.setattr(consume, "read_json", replace_after_read)
    owner = consume._BundleClassMemo()
    token = consume._BUNDLE_CLASS_MEMO.set(owner)
    try:
        with pytest.raises(ObjectInfoCacheCorruptError, match="changed during pack"):
            consume._resolve_class_type("RaceNode")
        assert "RaceNode" not in owner.entries
        assert consume._resolve_class_type("RaceNode")["value"] == 8
    finally:
        consume._BUNDLE_CLASS_MEMO.reset(token)
