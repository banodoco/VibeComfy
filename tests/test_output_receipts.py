"""Stable producer evidence with separate, checked local file observations."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from vibecomfy.runtime import output_receipts
from vibecomfy.runtime import session


def _fixture(tmp_path: Path, *, with_receipt: bool = True):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    source = tmp_path / "shared" / "final.mp4"
    source.parent.mkdir()
    source.write_bytes(b"verified video output")
    descriptor = {"filename": "final.mp4", "subfolder": "", "type": "output", "animated": True}
    artifact = {"path": str(source), "reported_path": "final.mp4", "descriptor": descriptor}
    metadata = {
        "run_id": "producer-1", "task_id": "task-1", "attempt_id": "attempt-1",
        "created": "2026-11-18T00:00:00Z", "prompt_id": "prompt-1",
        "artifacts": [artifact], "media_validation": {"status": "verified"},
        "declared_outputs": [{"name": "video", "mime_type": "video/mp4"}],
    }
    attempt = {"run_id": "producer-1", "prompt_id": "prompt-1"}
    evidence = {"queue_acceptance": {"status": "accepted", "prompt_id": "prompt-1"}}
    if with_receipt:
        receipt = output_receipts.collect_receipt(source, prompt_id="prompt-1", descriptor=descriptor)
        receipt["producer"] = "fetch"
        artifact["output_receipt"] = receipt
        attempt["artifacts"] = [deepcopy(artifact)]
        attempt["artifact_retrieval"] = {"output_receipts": {"output/final.mp4": deepcopy(receipt)}}
        evidence["artifacts"] = [{"output_receipt": deepcopy(receipt)}]
    return run_dir, source, metadata, attempt, evidence


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


def _no_hash(*_args, **_kwargs):
    raise AssertionError("an observed output must not be hashed again")


def test_rebuilt_result_keeps_stat_changes_outside_all_producer_evidence(tmp_path, monkeypatch):
    run_dir, source, metadata, attempt, evidence = _fixture(tmp_path)
    original_inputs = deepcopy((metadata, attempt, evidence))
    receipt = metadata["artifacts"][0]["output_receipt"]
    expected_identity = {"sha256": receipt["sha256"], "bytes": receipt["bytes"], "path": "outputs/final.mp4"}
    real_copy = session.shutil.copyfile
    copies = 0

    def copy_with_changed_stat(source, destination):
        nonlocal copies
        result = real_copy(source, destination)
        copies += 1
        os.utime(destination, ns=(1_000_000_000, copies * 1_000_000_000))
        return result

    monkeypatch.setattr(session.shutil, "copyfile", copy_with_changed_stat)
    monkeypatch.setattr(output_receipts.hashlib, "sha256", _no_hash)
    first, unavailable = _build(run_dir, metadata, attempt, evidence)
    assert unavailable == {} and first is not None
    sidecar_path = run_dir / output_receipts.RECEIPT_OBSERVATIONS_FILENAME
    first_observation = json.loads(sidecar_path.read_text())
    first_receipt = first_observation["output_receipts"]["outputs/final.mp4"]
    assert first_receipt["file_identity"] == output_receipts._identity(run_dir / "outputs/final.mp4")

    second, unavailable = _build(run_dir, metadata, attempt, evidence)
    assert unavailable == {} and second is not None
    second_observation = json.loads(sidecar_path.read_text())
    second_receipt = second_observation["output_receipts"]["outputs/final.mp4"]
    assert first_receipt["file_identity"] != second_receipt["file_identity"]
    assert second_receipt["file_identity"] == output_receipts._identity(run_dir / "outputs/final.mp4")
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    identities = list(_identities(second["evidence"]["producer"]))
    assert len(identities) == 6
    assert all(identity == expected_identity for identity in identities)
    assert second["evidence"]["transport"] == {}
    assert second["evidence"]["producer"]["output_receipts"]["outputs/final.mp4"]["producer"] == "fetch"
    assert second_observation == {
        "schema_version": 1, "task_id": "task-1", "attempt_id": "attempt-1",
        "producer_run_id": "producer-1", "output_receipts": {"outputs/final.mp4": second_receipt},
    }
    assert second_receipt["sha256"] == receipt["sha256"]
    assert second_receipt["bytes"] == source.stat().st_size
    assert (metadata, attempt, evidence) == original_inputs


@pytest.mark.parametrize("change", ["same_length_bytes", "replacement", "prompt", "descriptor"])
def test_stale_or_misattributed_receipt_is_rejected_without_rehash(tmp_path, monkeypatch, change):
    run_dir, source, metadata, attempt, evidence = _fixture(tmp_path)
    original_stat = source.stat()
    if change == "same_length_bytes":
        source.write_bytes(b"x" * original_stat.st_size)
        os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    elif change == "replacement":
        replacement = source.with_suffix(".replacement")
        replacement.write_bytes(source.read_bytes())
        os.utime(replacement, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        replacement.replace(source)
    elif change == "prompt":
        metadata["prompt_id"] = "another-prompt"
    else:
        metadata["artifacts"][0]["descriptor"] = {"filename": "another.mp4"}
    monkeypatch.setattr(output_receipts.hashlib, "sha256", _no_hash)
    payload, unavailable = _build(run_dir, metadata, attempt, evidence)
    assert payload is None
    assert unavailable["artifacts"][0]["reason"] == "attributed output receipt is stale or mismatched"
    assert not (run_dir / output_receipts.RECEIPT_OBSERVATIONS_FILENAME).exists()


def test_collection_hash_is_reused_for_content_receipt_and_copy(tmp_path, monkeypatch):
    run_dir, source, metadata, attempt, evidence = _fixture(tmp_path, with_receipt=False)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    real_sha256 = hashlib.sha256
    calls = 0

    def counted_hash(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_sha256(*args, **kwargs)

    monkeypatch.setattr(output_receipts.hashlib, "sha256", counted_hash)
    payload, unavailable = _build(run_dir, metadata, attempt, evidence)
    assert unavailable == {} and payload is not None
    assert calls == 1
    assert payload["outputs"][0]["sha256"] == digest
    receipt = payload["evidence"]["producer"]["output_receipts"]["outputs/final.mp4"]
    assert receipt["file_identity"] == {"sha256": digest, "bytes": source.stat().st_size, "path": "outputs/final.mp4"}


def test_change_between_receipt_check_and_copy_is_rejected(tmp_path, monkeypatch):
    run_dir, source, metadata, attempt, evidence = _fixture(tmp_path)
    real_identity = output_receipts._identity
    source_checks = 0

    def identity_after_mutation(path):
        nonlocal source_checks
        if path == source:
            source_checks += 1
            if source_checks == 2:
                source.write_bytes(b"x" * source.stat().st_size)
        return real_identity(path)

    monkeypatch.setattr(output_receipts, "_identity", identity_after_mutation)
    monkeypatch.setattr(output_receipts.hashlib, "sha256", _no_hash)
    payload, unavailable = _build(run_dir, metadata, attempt, evidence)
    assert payload is None
    assert unavailable["artifacts"][0]["reason"] == "artifact changed before copying"
    assert not (run_dir / output_receipts.RECEIPT_OBSERVATIONS_FILENAME).exists()


def test_missing_optional_observations_do_not_prevent_result_emission(tmp_path, monkeypatch):
    run_dir, _source, metadata, attempt, evidence = _fixture(tmp_path)

    def unavailable_sidecar(*_args, **_kwargs):
        raise OSError("receipt observations unavailable")

    monkeypatch.setattr(session, "atomic_write_json", unavailable_sidecar)
    monkeypatch.setattr(output_receipts.hashlib, "sha256", _no_hash)
    payload, unavailable = _build(run_dir, metadata, attempt, evidence)
    assert unavailable == {} and payload is not None
    assert payload["outputs"][0]["path"] == "outputs/final.mp4"
    assert not (run_dir / output_receipts.RECEIPT_OBSERVATIONS_FILENAME).exists()
