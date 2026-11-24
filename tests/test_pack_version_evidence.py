"""LE-10: source version evidence is not executable pin authority."""
from __future__ import annotations

import json

from vibecomfy.custom_node_refs import lock_entry_to_ref
from vibecomfy.node_packs import LockEntry
from vibecomfy.porting.import_service import import_workflow_bytes, pack_version_evidence
from vibecomfy.porting.provenance import extract_provenance
from vibecomfy.security.provenance import Provenance
from vibecomfy.workflow_bundle import load_bundle

REPO = "https://github.com/example/fixture-pack"
PIN = "a" * 40
OLD_PIN = "b" * 40


def _ui(version: str) -> dict:
    # Same minimal convertible UI graph used by the import-service tests.
    return {
        "nodes": [
            {"id": 1, "type": "KSampler", "inputs": [], "widgets_values": [],
             "properties": {"cnr_id": "fixture-pack", "ver": version}}
        ]
    }


def _ref(commit=PIN, **extra):
    return {"slug": "fixture-pack", "source": "git", "url": REPO,
            "commit": commit, **extra}


def test_ui_version_and_selected_lock_commit_are_distinct():
    report = extract_provenance(_ui("1.0.0")).to_json()
    selected = lock_entry_to_ref(LockEntry(
        name="fixture-pack", url=REPO, commit=PIN, version="2.0.0",
    ))
    rows = pack_version_evidence(report, [selected])
    assert rows == [{
        "pack": "fixture-pack", "repository": REPO,
        "recorded_versions": ["1.0.0"], "selected_commit": PIN,
        "selected_version_label": "2.0.0", "user_selected": False,
        "relation": "different_version_label",
    }]
    # The selection and authored evidence must remain independent and unchanged.
    assert selected["commit"] == PIN
    assert report["version_pins"][0]["version"] == "1.0.0"


def test_two_exact_commits_differ_and_equal_commit_is_not_drift():
    report = extract_provenance(_ui(OLD_PIN)).to_json()
    assert pack_version_evidence(report, [_ref()])[0]["relation"] == "different_commit"
    assert pack_version_evidence(report, [_ref(OLD_PIN)])[0]["relation"] == "same_commit"


def test_ambiguous_and_unpinned_refs_do_not_claim_a_selected_version():
    report = extract_provenance(_ui("1.0.0")).to_json()
    assert pack_version_evidence(report, [_ref("main")]) == []
    assert pack_version_evidence(report, [
        _ref(), _ref(OLD_PIN, url="https://github.com/other/fixture-pack"),
    ]) == []


def test_import_reports_authored_ui_version_without_rewriting_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = json.dumps(_ui("1.0.0")).encode()
    artifacts = import_workflow_bytes(
        source, workflow_id="version-evidence", added_node_refs=[_ref()],
    )
    assert artifacts.source_bytes == source
    row = artifacts.report["pack_version_evidence"][0]
    assert row["recorded_versions"] == ["1.0.0"]
    assert row["selected_commit"] == PIN
    assert row["relation"] == "unverified"
    (tmp_path / "workflow.py").write_bytes(artifacts.python_bytes)
    (tmp_path / "workflow.vibe.json").write_bytes(artifacts.companion_bytes)
    bundle = load_bundle(tmp_path / "workflow.py", trust=Provenance.USER_CONFIRMED)
    assert pack_version_evidence(
        bundle.provenance["source_provenance"],
        bundle.workflow.requirements.custom_node_refs,
    ) == artifacts.report["pack_version_evidence"]


def test_api_explicit_pin_does_not_invent_recorded_version(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = json.dumps({"1": {"class_type": "LoadImage", "inputs": {"image": "input.png"}},
                         "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0],
                                                                    "filename_prefix": "out/test"}}}).encode()
    artifacts = import_workflow_bytes(source, workflow_id="api-pin", added_node_refs=[_ref()])
    assert artifacts.report["pack_version_evidence"] == [{
        "pack": "fixture-pack", "repository": REPO,
        "recorded_versions": [], "selected_commit": PIN,
        "selected_version_label": None, "user_selected": True,
        "relation": "not_recorded",
    }]
