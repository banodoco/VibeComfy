"""Identity-specific reads stay separate from the bundle's class-only memo."""

from types import SimpleNamespace

import pytest

from vibecomfy.porting.emit.identity import _identity_for_node, _use_object_info_identities
from vibecomfy.porting.object_info import consume


class CountingMemo(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reads = 0
        self.writes = 0

    def __contains__(self, key):
        self.reads += 1
        return super().__contains__(key)

    def __getitem__(self, key):
        self.reads += 1
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        self.writes += 1
        super().__setitem__(key, value)


def _bound_lookup(*, fallback):
    node = SimpleNamespace(id="1")
    with _use_object_info_identities({"1": {"pack_slug": "pack", "git_commit": "rev"}}):
        return consume.resolve_class_entry("A", _identity_for_node(node), allow_class_fallback=fallback)


def _assert_no_identity_memo_traffic(monkeypatch, *, hit, mutant=False):
    entry = {"pack_slug": "pack", "git_commit": "rev", "outputs": ["identity"]}
    memo = CountingMemo({"A": {"outputs": ["class"]}})
    def matches(class_type, **kwargs):
        if mutant:
            consume._resolve_class_type(class_type)
        return [("pack.json", entry)] if hit else []
    monkeypatch.setattr(consume, "_identity_lookup_matches", matches)
    token = consume._BUNDLE_CLASS_MEMO.set(memo)
    try:
        result = _bound_lookup(fallback=False)
        assert result.entry == (entry if hit else None)
        assert result.source == ("identity" if hit else "identity_miss")
        assert (memo.reads, memo.writes) == (0, 0)
    finally:
        consume._BUNDLE_CLASS_MEMO.reset(token)


@pytest.mark.parametrize("hit", [True, False], ids=["hit", "miss-no-fallback"])
def test_identity_path_does_not_touch_warm_class_memo(monkeypatch, hit):
    _assert_no_identity_memo_traffic(monkeypatch, hit=hit)


def test_identity_hit_memo_negative_control(monkeypatch):
    # A mutant routing identity hits through the class memo must be detected.
    with pytest.raises(AssertionError):
        _assert_no_identity_memo_traffic(monkeypatch, hit=True, mutant=True)


@pytest.mark.parametrize("warm", [None, "A", "B"], ids=["cold", "same-class", "other-class"])
@pytest.mark.parametrize("scenario", ["present", "absent", "corrupt"])
def test_identity_miss_fallback_matches_unmemoized_path(monkeypatch, warm, scenario):
    entry = {"outputs": ["class"]}
    monkeypatch.setattr(consume, "_identity_lookup_matches", lambda *args, **kwargs: [])
    def load_index():
        if scenario == "corrupt":
            raise ValueError("corrupt index")
        return {"A": "pack", "B": "pack"} if scenario == "present" else {"B": "pack"}
    monkeypatch.setattr(consume, "_load_index", load_index)
    monkeypatch.setattr(consume, "_load_pack", lambda filename: {"A": entry, "B": {"outputs": ["other"]}})

    def outcome():
        try:
            return ("result", _bound_lookup(fallback=True))
        except Exception as exc:
            return ("error", type(exc), str(exc))

    # No memo models the original class-only resolver path.
    expected = outcome()
    memo = CountingMemo()
    token = consume._BUNDLE_CLASS_MEMO.set(memo)
    try:
        if warm:
            try:
                consume._resolve_class_type(warm)
            except ValueError:
                assert scenario == "corrupt"
        assert outcome() == expected
        if scenario == "corrupt":
            assert "A" not in memo
            assert outcome() == expected
            assert "A" not in memo
    finally:
        consume._BUNDLE_CLASS_MEMO.reset(token)
