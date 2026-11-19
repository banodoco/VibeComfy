"""A committed cache cannot use creation time as proof of unchanged bytes."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from vibecomfy.errors import ObjectInfoCacheCorruptError
from vibecomfy.porting.object_info import generation
from vibecomfy.porting.object_info.serialize import build_cache


def test_committed_generation_rechecks_content_when_ctime_is_unchanged(tmp_path, monkeypatch):
    source = tmp_path / "source.json"
    source.write_bytes(json.dumps({"LS12Witness": {
        "name": "LS12Witness", "python_module": "ls12_witness",
        "input": {"required": {}}, "output": [],
    }}).encode("utf-8"))
    cache = tmp_path / "cache"
    build_cache(str(source), version="ls12", cache_dir=str(cache), full_pack_refresh=True)
    # Simulate a filesystem whose ctime reports creation rather than content
    # change. Keep fresh dev/inode/size/mtime/mode and read real edited bytes.
    lstat = Path.lstat
    created = {}

    def creation_time(path):
        observed = lstat(path)
        if not path.is_relative_to(cache):
            return observed
        fields = {name: getattr(observed, name) for name in (
            "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_mode")}
        return SimpleNamespace(**fields, st_ctime_ns=created.setdefault(path, observed.st_ctime_ns))

    monkeypatch.setattr(Path, "lstat", creation_time)
    monkeypatch.setattr(generation, "_VALIDATED_GENERATIONS", {})
    root = generation.active_cache_root(cache)
    assert generation.active_cache_root(cache) == root
    artifact = root / "index.json"
    before = artifact.lstat()
    original = artifact.read_bytes()
    artifact.write_bytes(b"!" + original[1:])
    os.utime(artifact, ns=(artifact.stat().st_atime_ns, before.st_mtime_ns))
    assert vars(artifact.lstat()) == vars(before)
    assert artifact.read_bytes() != original
    with pytest.raises(ObjectInfoCacheCorruptError, match="hash check"):
        generation.active_cache_root(cache)
