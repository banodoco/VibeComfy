"""Equal content at distinct output paths retains independent attribution."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from vibecomfy.runtime import output_receipts
from vibecomfy.runtime import session


_CONTENT = b"identical image bytes at two independently attributed output paths"


def _fixture(tmp_path: Path, *, external: bool, fetched: bool):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    source_dir = tmp_path / "downloads" if external else run_dir / "images"
    source_dir.mkdir()
    artifacts = []
    for name in ("right", "left"):
        source = source_dir / f"{name}.png"
        source.write_bytes(_CONTENT)
        artifact = {"path": str(source), "reported_path": f"{name}.png"}
        if fetched:
            receipt = output_receipts.collect_receipt(source, prompt_id="prompt-1", descriptor=None)
            receipt["producer"] = "fetch"
            artifact["output_receipt"] = receipt
        artifacts.append(artifact)
    metadata = {
        "run_id": "producer-1", "task_id": "task-1", "attempt_id": "attempt-1",
        "created": "2026-11-19T00:00:00Z", "prompt_id": "prompt-1",
        "artifacts": artifacts,
        "declared_outputs": [
            {"name": "left", "mime_type": "image/png", "declaration_ordinal": 0},
            {"name": "right", "mime_type": "image/png", "declaration_ordinal": 1},
        ],
        "artifact_manifest": {"attribution": [
            {"path": "left.png", "output": "left"},
            {"path": "right.png", "output": "right"},
        ]},
        "media_validation": {"status": "verified"},
    }
    attempt = {
        "run_id": "producer-1", "prompt_id": "prompt-1",
        "artifacts": deepcopy(artifacts),
    }
    evidence = {"queue_acceptance": {"status": "accepted", "prompt_id": "prompt-1"}}
    if fetched:
        attempt["artifact_retrieval"] = {"output_receipts": {
            f"output/{artifact['reported_path']}": deepcopy(artifact["output_receipt"])
            for artifact in artifacts
        }}
        evidence["artifacts"] = [
            {"output_receipt": deepcopy(artifact["output_receipt"])}
            for artifact in artifacts
        ]
    return run_dir, metadata, attempt, evidence


def _build(run_dir, metadata, attempt, evidence):
    return session._build_managed_generation_result(
        run_dir=run_dir, metadata=metadata, attempt_bundle=attempt, evidence=evidence,
    )


def _identities(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "file_identity":
                yield item
            yield from _identities(item)
    elif isinstance(value, list):
        for item in value:
            yield from _identities(item)


@pytest.mark.parametrize("external", [False, True], ids=["custody", "copied"])
@pytest.mark.parametrize("fetched", [False, True], ids=["collection", "fetch"])
def test_identical_descriptorless_outputs_keep_distinct_paths_and_evidence(
    tmp_path, monkeypatch, external, fetched,
):
    run_dir, metadata, attempt, evidence = _fixture(tmp_path, external=external, fetched=fetched)
    original_inputs = deepcopy((metadata, attempt, evidence))
    digest = hashlib.sha256(_CONTENT).hexdigest()
    real_sha256 = hashlib.sha256
    hashes = 0

    def counted_hash(*args, **kwargs):
        nonlocal hashes
        hashes += 1
        return real_sha256(*args, **kwargs)

    real_copy = session.shutil.copyfile
    copies = 0

    def copy_with_changed_stat(source, destination):
        nonlocal copies
        result = real_copy(source, destination)
        copies += 1
        os.utime(destination, ns=(1_000_000_000, copies * 1_000_000_000))
        return result

    monkeypatch.setattr(output_receipts.hashlib, "sha256", counted_hash)
    monkeypatch.setattr(session.shutil, "copyfile", copy_with_changed_stat)
    payload, unavailable = _build(run_dir, metadata, attempt, evidence)
    assert unavailable == {}, unavailable
    assert payload is not None
    assert hashes == (0 if fetched else 2)
    paths = {
        name: f"outputs/{ordinal:04d}-{name}.png" if external else f"images/{name}.png"
        for ordinal, name in enumerate(("left", "right"))
    }
    assert payload["outputs"] == [
        {
            "producer_output_id": f"vibecomfy:{name}:{ordinal}",
            "output_port": name, "ordinal": ordinal, "path": paths[name],
            "media_type": "image/png", "bytes": len(_CONTENT), "sha256": digest,
        }
        for ordinal, name in enumerate(("left", "right"))
    ]
    expected_identities = {
        name: {"sha256": digest, "bytes": len(_CONTENT), "path": path}
        for name, path in paths.items()
    }
    producer = payload["evidence"]["producer"]
    public_receipts = producer["output_receipts"]
    assert set(public_receipts) == set(paths.values())
    for name, path in paths.items():
        assert public_receipts[path] == {
            "version": 1, "sha256": digest, "bytes": len(_CONTENT),
            "file_identity": expected_identities[name], "prompt_id": "prompt-1",
            "descriptor": {}, "producer": "fetch" if fetched else "collection",
        }
        assert (run_dir / path).read_bytes() == _CONTENT
    identities = list(_identities(producer))
    assert len(identities) == (12 if fetched else 2)
    assert all(identity in expected_identities.values() for identity in identities)
    if fetched:
        for artifact_group in (
            producer["artifacts"], producer["metadata"]["record"]["artifacts"],
            producer["attempt"]["record"]["artifacts"],
        ):
            for artifact in artifact_group:
                name = Path(artifact["reported_path"]).stem
                assert artifact["output_receipt"]["file_identity"] == expected_identities[name]
        retrieval = producer["attempt"]["record"]["artifact_retrieval"]["output_receipts"]
        assert set(retrieval) == {"output/left.png", "output/right.png"}
        for name in paths:
            assert retrieval[f"output/{name}.png"]["file_identity"] == expected_identities[name]
        assert [item["output_receipt"]["file_identity"] for item in producer["runtime"]["artifacts"]] == [
            expected_identities["right"], expected_identities["left"],
        ]
    sidecar_path = run_dir / output_receipts.RECEIPT_OBSERVATIONS_FILENAME
    first_observation = json.loads(sidecar_path.read_text())
    assert set(first_observation["output_receipts"]) == set(paths.values())
    for path in paths.values():
        observed = first_observation["output_receipts"][path]
        assert observed["file_identity"] == output_receipts._identity(run_dir / path)
        assert observed["sha256"] == digest
        assert observed["bytes"] == len(_CONTENT)
        assert observed["prompt_id"] == "prompt-1"
    rebuilt, unavailable = _build(run_dir, metadata, attempt, evidence)
    assert unavailable == {} and rebuilt is not None
    assert rebuilt == payload
    assert hashes == (0 if fetched else 4)
    second_observation = json.loads(sidecar_path.read_text())
    for path in paths.values():
        second_identity = second_observation["output_receipts"][path]["file_identity"]
        assert second_identity == output_receipts._identity(run_dir / path)
        if external:
            assert second_identity != first_observation["output_receipts"][path]["file_identity"]
    assert (metadata, attempt, evidence) == original_inputs


def test_identical_content_does_not_attribute_a_foreign_nested_receipt(tmp_path):
    run_dir, metadata, attempt, evidence = _fixture(tmp_path, external=True, fetched=True)
    foreign = tmp_path / "uncollected.png"
    foreign.write_bytes(_CONTENT)
    receipt = output_receipts.collect_receipt(foreign, prompt_id="prompt-1", descriptor=None)
    receipt["producer"] = "fetch"
    evidence["artifacts"].append({"output_receipt": receipt})
    payload, unavailable = _build(run_dir, metadata, attempt, evidence)
    assert payload is None
    assert unavailable == {"reason": "evidence receipt does not identify one collected output"}
    assert not (run_dir / output_receipts.RECEIPT_OBSERVATIONS_FILENAME).exists()
