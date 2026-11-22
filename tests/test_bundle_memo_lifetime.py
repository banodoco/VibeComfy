import contextvars
import json

import pytest

from vibecomfy.porting.object_info import consume
from vibecomfy.workflow_bundle import _with_bundle_class_memo


def test_copied_context_cannot_read_revoked_memo_after_corruption(tmp_path, monkeypatch):
    monkeypatch.setattr(consume, "CACHE_DIR", tmp_path)
    (tmp_path / "index.json").write_text(json.dumps({"A": "pack.json"}))
    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps({"A": {"value": "old"}}))

    @_with_bundle_class_memo
    def capture():
        assert consume.get_class("A") == {"value": "old"}
        return contextvars.copy_context(), consume._BUNDLE_CLASS_MEMO.get()

    context, owner = capture()
    assert not owner.active and owner.entries == {}
    pack.write_text("[]")
    with pytest.raises(consume.ObjectInfoCacheCorruptError):
        context.run(consume.get_class, "A")
    with pytest.raises(consume.ObjectInfoCacheCorruptError):
        consume.get_class("A")


def test_expired_context_reentry_gets_fresh_owner_each_time(monkeypatch):
    reads = []
    monkeypatch.setattr(consume, "_load_index", lambda: reads.append(1) or {"A": "pack"})
    monkeypatch.setattr(consume, "_load_pack", lambda _: {"A": len(reads)})

    @_with_bundle_class_memo
    def run():
        owner = consume._BUNDLE_CLASS_MEMO.get()
        value = consume._resolve_class_type("A")
        assert consume._resolve_class_type("A") == value
        return contextvars.copy_context(), owner, value

    expired, first, _ = run()
    _, second, value2 = expired.run(run)
    _, third, value3 = expired.run(run)
    assert len({id(first), id(second), id(third)}) == 3
    assert (value2, value3) == (2, 3)
    assert all(not owner.active and owner.entries == {} for owner in (first, second, third))


def test_live_nested_scope_shares_owner_until_outer_exit(monkeypatch):
    reads = []
    monkeypatch.setattr(consume, "_load_index", lambda: reads.append(1) or {"A": "pack"})
    monkeypatch.setattr(consume, "_load_pack", lambda _: {"A": 7})

    @_with_bundle_class_memo
    def inner():
        assert consume._resolve_class_type("A") == 7
        return consume._BUNDLE_CLASS_MEMO.get()

    @_with_bundle_class_memo
    def outer():
        owner = consume._BUNDLE_CLASS_MEMO.get()
        assert consume._resolve_class_type("A") == 7
        assert inner() is owner
        assert owner.active and owner.entries == {"A": 7}
        assert consume._resolve_class_type("A") == 7
        return owner

    owner = outer()
    assert reads == [1]
    assert not owner.active and owner.entries == {}
