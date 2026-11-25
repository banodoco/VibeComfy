"""RS1.10: a caller refusal must not publish an entry revision."""
from pathlib import Path

import pytest

from tests._cli_helpers import _write_port_node_index, _write_port_workflow
from vibecomfy.entries import discover_entries, import_as_entry, load_entry


def _tree(root):
    return {path.relative_to(root): path.read_bytes() if path.is_file() else None
            for path in root.rglob("*")}


@pytest.mark.parametrize("replace", [False, True], ids=["new", "replacement"])
def test_refused_staged_revision_never_publishes(tmp_path, monkeypatch, replace):
    _write_port_node_index(tmp_path)
    monkeypatch.chdir(tmp_path)
    source = _write_port_workflow(tmp_path)
    root = tmp_path / "entries"
    destination = root / "sample"
    original = import_as_entry(source, "sample", root) if replace else None
    if replace:
        (destination / "code-approvals.json").write_bytes(b'["previous-sidecar"]\n')
    else:
        root.mkdir()
    before = _tree(root)

    def refuse(staged, revision):
        assert Path(staged["bundle"]).is_relative_to(revision)
        assert Path(staged["bundle"], "workflow.py").is_file()
        assert load_entry(revision) == staged
        assert discover_entries(root) == ([original] if replace else [])
        (revision / "code-approvals.json").write_bytes(b'["unpublished"]\n')
        raise ValueError("staged actual nodes refused")

    with pytest.raises(ValueError, match="staged actual nodes refused"):
        import_as_entry(source, "sample", root, replace=replace, before_publish=refuse)
    assert _tree(root) == before
    assert discover_entries(root) == ([original] if replace else [])


@pytest.mark.parametrize("replace", [False, True], ids=["new", "replacement"])
def test_staged_attachments_are_published_with_selected_bundle(tmp_path, monkeypatch, replace):
    _write_port_node_index(tmp_path)
    monkeypatch.chdir(tmp_path)
    source = _write_port_workflow(tmp_path)
    root = tmp_path / "entries"
    destination = root / "sample"
    original = import_as_entry(source, "sample", root) if replace else None
    previous = None
    if replace:
        (destination / "code-approvals.json").write_bytes(b'["previous"]\n')
        previous = _tree(destination)
    seen = []

    def attach(staged, revision):
        assert load_entry(revision) == staged
        assert discover_entries(root) == ([original] if replace else [])
        seen.append(Path(staged["bundle"], "workflow.py").read_bytes())
        (revision / "code-approvals.json").write_bytes(b'["approved"]\n')

    published = import_as_entry(source, "sample", root, replace=replace, before_publish=attach)
    revision = Path(published["bundle"]).parent
    assert len(seen) == 1
    assert Path(published["bundle"], "workflow.py").read_bytes() == seen[0]
    assert (revision / "code-approvals.json").read_bytes() == b'["approved"]\n'
    assert load_entry(revision) == published
    assert discover_entries(root) == [published]
    if replace:
        for path, value in previous.items():
            if path != Path("entry.json") and value is not None:
                assert (destination / path).read_bytes() == value


def test_direct_replacement_has_versioned_anchor_but_no_approval_inheritance(tmp_path, monkeypatch):
    _write_port_node_index(tmp_path)
    monkeypatch.chdir(tmp_path)
    source = _write_port_workflow(tmp_path)
    root = tmp_path / "entries"
    first = import_as_entry(source, "sample", root)
    entry = root / "sample"
    root_sidecar = entry / "code-approvals.json"
    root_sidecar.write_bytes(b'["initial"]\n')

    def attach(staged, revision):
        assert load_entry(revision) == staged
        (revision / "code-approvals.json").write_bytes(b'["previous-revision"]\n')

    approved = import_as_entry(source, "sample", root, replace=True, before_publish=attach)
    old_revision = Path(approved["bundle"]).parent
    before = _tree(entry)
    direct = import_as_entry(source, "sample", root, replace=True)
    revision = Path(direct["bundle"]).parent
    assert revision != old_revision
    assert revision.name.startswith("revision-v2-")
    assert old_revision.name.startswith("revision-v2-")
    assert load_entry(revision) == direct
    assert load_entry(old_revision) == approved
    assert not (revision / "code-approvals.json").exists()
    assert discover_entries(root) == [direct]
    assert root_sidecar.read_bytes() == b'["initial"]\n'
    assert Path(first["bundle"], "workflow.py").is_file()
    for path, value in before.items():
        if path != Path("entry.json") and value is not None:
            assert (entry / path).read_bytes() == value

