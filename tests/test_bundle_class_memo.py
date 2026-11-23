import pytest

from vibecomfy.porting.object_info import consume
from vibecomfy.workflow_bundle import _with_bundle_class_memo


def test_bundle_memo_preserves_raw_results_and_resets(monkeypatch):
    raw = {"outputs": []}
    reads = []
    monkeypatch.setattr(consume, "_load_index", lambda: reads.append("index") or {"A": "pack", "B": "pack"})
    monkeypatch.setattr(consume, "_load_pack", lambda name: reads.append(name) or {"A": raw, "B": 7})

    @_with_bundle_class_memo
    def run():
        assert consume._resolve_class_type("A") is raw
        assert consume._resolve_class_type("A") is raw
        assert consume._resolve_class_type("B") == 7
        assert consume._resolve_class_type("missing") is None
        assert consume._resolve_class_type("missing") is None

    run()
    assert reads == ["index", "pack", "index", "pack", "index"]
    run()
    assert len(reads) == 10
    assert consume._BUNDLE_CLASS_MEMO.get() is None


def test_bundle_memo_does_not_cache_exceptions_and_resets(monkeypatch):
    calls = []
    def fail():
        calls.append(1)
        raise ValueError("broken")
    monkeypatch.setattr(consume, "_load_index", fail)

    @_with_bundle_class_memo
    def run():
        for _ in range(2):
            with pytest.raises(ValueError, match="broken"):
                consume._resolve_class_type("A")
        raise RuntimeError("exit")

    with pytest.raises(RuntimeError, match="exit"):
        run()
    assert len(calls) == 2
    assert consume._BUNDLE_CLASS_MEMO.get() is None


def test_memo_is_not_used_inside_existing_snapshot(monkeypatch):
    reads = []
    monkeypatch.setattr(consume, "_load_index", lambda: reads.append(1) or {})
    token = consume._CLASS_ENTRY_SNAPSHOT.set(object())
    try:
        @_with_bundle_class_memo
        def run():
            consume._resolve_class_type("A")
            consume._resolve_class_type("A")
        run()
    finally:
        consume._CLASS_ENTRY_SNAPSHOT.reset(token)
    assert len(reads) == 2
