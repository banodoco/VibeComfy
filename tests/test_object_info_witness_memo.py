"""Count content reads across node resolution without wall-clock thresholds."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import pytest

from vibecomfy.porting.object_info import consume, generation


@pytest.mark.parametrize("mutation", ["touch", "rewrite", "replace"])
def test_multinode_resolve_hashes_each_file_once_per_stat(tmp_path, monkeypatch, mutation):
    provider = tmp_path / "witness_memo_multinode_provider.json"
    index = tmp_path / "index.json"
    entries = {f"WitnessNode{i}": {"name": f"WitnessNode{i}", "description": "before"}
               for i in range(32)}
    provider.write_text(json.dumps(entries), encoding="utf-8")
    index.write_text(json.dumps({name: provider.name for name in entries}), encoding="utf-8")
    monkeypatch.setattr(consume, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(consume, "_reader_state", None)
    monkeypatch.setattr(consume, "_index", None)
    monkeypatch.setattr(consume, "_pack_cache", {})
    reads = Counter()
    original = Path.read_bytes

    def counted_read(path):
        if path in (provider, index):
            reads[path] += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counted_read)
    for _ in range(3):
        for name in entries:
            assert consume.get_class(name)["description"] == "before"
    assert reads == {provider: 1, index: 1}

    before = provider.stat()
    expected = "before"
    if mutation == "touch":
        os.utime(provider, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
    else:
        expected = "after!"  # Same byte length, including when mtime is restored.
        updated = json.dumps({name: {**entry, "description": expected}
                              for name, entry in entries.items()})
        if mutation == "replace":
            replacement = tmp_path / "witness_memo_replacement.json"
            replacement.write_text(updated, encoding="utf-8")
            os.replace(replacement, provider)
            assert provider.stat().st_ino != before.st_ino
        else:
            provider.write_text(updated, encoding="utf-8")
        assert provider.stat().st_size == before.st_size
        os.utime(provider, ns=(before.st_atime_ns, before.st_mtime_ns))
    for name in entries:
        assert consume.get_class(name)["description"] == expected
    assert reads == {provider: 2, index: 1}


def test_witness_memo_keeps_paths_distinct_and_forgets_missing_file(tmp_path):
    first = tmp_path / "first" / "witness_memo_path_identity.json"
    second = tmp_path / "second" / first.name
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"first")
    second.write_bytes(b"other")
    stamp = first.stat()
    os.utime(second, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    one = generation.cache_file_witness(first)
    two = generation.cache_file_witness(second)
    assert one[5] != two[5]
    first.unlink()
    assert generation.cache_file_witness(first) is None
    first.write_bytes(b"third")
    assert generation.cache_file_witness(first)[5] != one[5]
