"""LE-12: replacement retains explicit, immutable additions and approvals."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests._cli_helpers import _write_port_node_index, _write_port_workflow
from vibecomfy.custom_node_refs import CustomNodeRefConflict
from vibecomfy.entries import entry_added_node_refs, import_as_entry, load_entry
from vibecomfy.security.provenance import Provenance
from vibecomfy.workflow_bundle import load_bundle

FIRST = "https://github.com/ethanfel/ComfyUI-SAM-Audio"
FIRST_PIN = "3cfbd03da3019c7252ba13efd5694b1b2ff487e5"
SECOND = "https://github.com/example/other-pack"
SECOND_PIN = "a" * 40


def test_replace_keeps_additions_and_sidecar_bytes(tmp_path, monkeypatch):
    _write_port_node_index(tmp_path)
    monkeypatch.chdir(tmp_path)
    source = _write_port_workflow(tmp_path)
    root = tmp_path / "entries"
    first = import_as_entry(source, "sample", root, add=[FIRST + "@" + FIRST_PIN])
    # The sidecar belongs to the Agent. Its exact bytes, whatever the valid
    # approval set, must not be rewritten by VibeComfy's manifest transaction.
    approval_bytes = b'[{"identity":{"repo":"example","commit":"fixture"},"fixture":"opaque"}]\n'
    approval = root / "sample" / "code-approvals.json"
    approval.write_bytes(approval_bytes)
    original = Path(first["bundle"], "workflow.py").read_bytes()

    replaced = import_as_entry(source, "sample", root, replace=True,
                               add=[SECOND + "@" + SECOND_PIN])
    assert {(ref["url"], ref["commit"]) for ref in entry_added_node_refs(replaced)} == {
        (FIRST, FIRST_PIN), (SECOND, SECOND_PIN),
    }
    restored = load_bundle(Path(replaced["bundle"]) / "workflow.py",
                           trust=Provenance.USER_CONFIRMED).workflow
    assert {(ref["url"], ref["commit"]) for ref in restored.requirements.custom_node_refs
            if ref.get("entry_add") is True} == {(FIRST, FIRST_PIN), (SECOND, SECOND_PIN)}
    assert approval.read_bytes() == approval_bytes
    assert Path(first["bundle"], "workflow.py").read_bytes() == original

    replay = import_as_entry(source, "sample", root, replace=True)
    assert entry_added_node_refs(replay) == entry_added_node_refs(replaced)
    assert approval.read_bytes() == approval_bytes


@pytest.mark.parametrize("new_url", [
    FIRST, FIRST + ".git", "https://github.com/example/ComfyUI-SAM-Audio",
])
def test_explicit_replacement_pin_supersedes_only_matching_retained_row(tmp_path, monkeypatch, new_url):
    _write_port_node_index(tmp_path)
    monkeypatch.chdir(tmp_path)
    source = _write_port_workflow(tmp_path)
    root = tmp_path / "entries"
    first = import_as_entry(source, "sample", root, add=[
        FIRST + "@" + FIRST_PIN, SECOND + "@" + SECOND_PIN,
    ])
    approval = root / "sample" / "code-approvals.json"
    approval_bytes = b'[{"old":"record"}]\n'
    approval.write_bytes(approval_bytes)
    original = Path(first["bundle"], "workflow.py").read_bytes()

    replaced = import_as_entry(source, "sample", root, replace=True,
                               add=[new_url + "@" + SECOND_PIN])
    assert {(ref["url"], ref["commit"]) for ref in entry_added_node_refs(replaced)} == {
        (new_url, SECOND_PIN), (SECOND, SECOND_PIN),
    }
    assert approval.read_bytes() == approval_bytes
    assert Path(first["bundle"], "workflow.py").read_bytes() == original
    assert load_entry(root / "sample") == replaced


def test_conflicting_new_replacement_pins_keep_previous_entry(tmp_path, monkeypatch):
    _write_port_node_index(tmp_path)
    monkeypatch.chdir(tmp_path)
    source = _write_port_workflow(tmp_path)
    root = tmp_path / "entries"
    first = import_as_entry(source, "sample", root, add=[FIRST + "@" + FIRST_PIN])
    destination = root / "sample"
    previous = (destination / "entry.json").read_bytes()
    children = set(destination.iterdir())
    with pytest.raises(CustomNodeRefConflict):
        import_as_entry(source, "sample", root, replace=True,
                        add=[FIRST + "@" + FIRST_PIN, FIRST + "@" + SECOND_PIN])
    assert load_entry(destination) == first
    assert (destination / "entry.json").read_bytes() == previous
    assert set(destination.iterdir()) == children


def test_replacement_add_cannot_override_source_bundle_pin(tmp_path, monkeypatch):
    _write_port_node_index(tmp_path)
    monkeypatch.chdir(tmp_path)
    source = _write_port_workflow(tmp_path)
    root = tmp_path / "entries"
    first = import_as_entry(source, "sample", root, add=[FIRST + "@" + FIRST_PIN])
    authored = import_as_entry(source, "authored", root, add=[FIRST + "@" + FIRST_PIN])
    destination = root / "sample"
    previous = (destination / "entry.json").read_bytes()
    children = set(destination.iterdir())

    # Unlike the retained entry's row, the incoming source bundle's own
    # canonical requirements are not superseded by replacement selection.
    with pytest.raises(CustomNodeRefConflict):
        import_as_entry(authored["bundle"], "sample", root, replace=True,
                        add=[FIRST + "@" + SECOND_PIN])
    assert load_entry(destination) == first
    assert (destination / "entry.json").read_bytes() == previous
    assert set(destination.iterdir()) == children


def test_preflight_selection_preserves_conflicts_for_canonical_validation():
    from vibecomfy.custom_node_refs import apply_added_node_refs, resolve_added_node_refs
    from vibecomfy.entries import merge_entry_added_node_refs
    from vibecomfy.workflow import VibeWorkflow, WorkflowSource

    retained = resolve_added_node_refs([FIRST + "@" + FIRST_PIN, SECOND + "@" + SECOND_PIN])
    new = resolve_added_node_refs([FIRST + "@" + SECOND_PIN])
    selected = merge_entry_added_node_refs(retained, new)
    assert {(ref["url"], ref["commit"]) for ref in selected} == {
        (FIRST, SECOND_PIN), (SECOND, SECOND_PIN),
    }
    wf = VibeWorkflow("test", WorkflowSource("test"))
    apply_added_node_refs(wf, selected)
    assert {(ref["url"], ref["commit"]) for ref in wf.requirements.custom_node_refs} == {
        (FIRST, SECOND_PIN), (SECOND, SECOND_PIN),
    }

    conflicting = merge_entry_added_node_refs(retained, [
        *new, *resolve_added_node_refs([FIRST + "@" + FIRST_PIN]),
    ])
    with pytest.raises(CustomNodeRefConflict):
        apply_added_node_refs(VibeWorkflow("conflict", WorkflowSource("conflict")), conflicting)
