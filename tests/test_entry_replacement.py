"""WS-0d: publish a complete imported replacement at one manifest commit point."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests._cli_helpers import _write_port_node_index, _write_port_workflow
from vibecomfy.entries import discover_entries, import_as_entry, load_entry


@pytest.fixture
def sources(tmp_path, monkeypatch):
    _write_port_node_index(tmp_path)
    monkeypatch.chdir(tmp_path)
    old = _write_port_workflow(tmp_path)
    raw = json.loads(old.read_text(encoding="utf-8"))
    raw["1"]["inputs"]["image"] = "replacement.png"
    new = tmp_path / "replacement.json"
    new.write_text(json.dumps(raw), encoding="utf-8")
    return old, new, tmp_path / "entries"


def test_replace_is_opt_in_and_switches_complete_bundle(sources, monkeypatch):
    old, new, root = sources
    first = import_as_entry(old, "sample", root)
    destination = root / "sample"
    sidecar = destination / "code-approvals.json"
    sidecar.write_bytes(b"[]")
    with pytest.raises(FileExistsError):
        import_as_entry(new, "sample", root)
    assert load_entry(destination) == first

    real_replace = os.replace
    commits = []

    def observe(src, dst, *args, **kwargs):
        if Path(dst) == destination / "entry.json":
            assert load_entry(destination) == first
            candidate = json.loads(Path(src).read_text(encoding="utf-8"))
            bundle = destination / candidate["bundle"]
            assert (bundle / "source.json").read_bytes() == new.read_bytes()
            assert (bundle / "workflow.py").is_file()
            assert (bundle / "workflow.vibe.json").is_file()
            commits.append(True)
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", observe)
    second = import_as_entry(new, "sample", root, replace=True)
    assert commits == [True]
    assert discover_entries(root) == [second]
    assert second["bundle"] != first["bundle"]
    assert (Path(second["bundle"]) / "source.json").read_bytes() == new.read_bytes()
    assert (Path(first["bundle"]) / "source.json").read_bytes() == old.read_bytes()
    assert sidecar.read_bytes() == b"[]"


def test_failed_publication_preserves_previous_manifest_and_bundle(sources, monkeypatch):
    old, new, root = sources
    first = import_as_entry(old, "sample", root)
    destination = root / "sample"
    manifest = (destination / "entry.json").read_bytes()
    paths = set(destination.iterdir())
    real_replace = os.replace

    def fail(src, dst, *args, **kwargs):
        if Path(dst) == destination / "entry.json":
            raise OSError("injected publication failure")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="injected publication failure"):
        import_as_entry(new, "sample", root, replace=True)
    assert (destination / "entry.json").read_bytes() == manifest
    assert load_entry(destination) == first
    assert set(destination.iterdir()) == paths
    assert (Path(first["bundle"]) / "source.json").read_bytes() == old.read_bytes()


def test_failed_draft_preserves_previous_entry(sources, monkeypatch):
    from vibecomfy import entries

    old, new, root = sources
    first = import_as_entry(old, "sample", root)
    destination = root / "sample"
    paths = set(destination.iterdir())

    def fail(*args, **kwargs):
        raise ValueError("injected draft failure")

    monkeypatch.setattr(entries, "draft_entry", fail)
    with pytest.raises(ValueError, match="injected draft failure"):
        import_as_entry(new, "sample", root, replace=True)
    assert load_entry(destination) == first
    assert set(destination.iterdir()) == paths


def test_replace_can_create_a_new_entry(sources):
    _, new, root = sources
    entry = import_as_entry(new, "sample", root, replace=True)
    assert discover_entries(root) == [entry]
    assert (Path(entry["bundle"]) / "source.json").read_bytes() == new.read_bytes()


def test_replace_refuses_foreign_directory(sources):
    _, new, root = sources
    destination = root / "sample"
    destination.mkdir(parents=True)
    marker = destination / "foreign.txt"
    marker.write_bytes(b"keep")
    with pytest.raises(FileExistsError, match="not a replaceable entry"):
        import_as_entry(new, "sample", root, replace=True)
    assert set(destination.iterdir()) == {marker}
    assert marker.read_bytes() == b"keep"
