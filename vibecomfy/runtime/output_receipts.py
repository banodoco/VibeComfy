"""Digest/length observations from an attributed output's single collection.

The consumer Runtime verifies the actual output independently. A receipt is
producer evidence, never authorization to bypass that boundary.
"""
from __future__ import annotations

import hashlib
import re
import stat
from collections.abc import Mapping
from pathlib import Path


RECEIPT_OBSERVATIONS_FILENAME = "managed-generation-result.receipts.json"


def _identity(path: Path) -> list[int]:
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode):
        raise ValueError("output receipt requires a regular file")
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def _routing_descriptor(descriptor: Mapping | None) -> dict:
    descriptor = descriptor or {}
    return {"filename": descriptor.get("filename"),
            "subfolder": descriptor.get("subfolder") or "",
            "type": descriptor.get("type") or "output"}


def collect_receipt(path: Path, *, prompt_id: str | None, descriptor: Mapping | None,
                    receipt: object = None) -> dict:
    before = _identity(path)
    if isinstance(receipt, Mapping):
        digest = receipt.get("sha256")
        if (receipt.get("version") == 1 and receipt.get("prompt_id") == prompt_id
                and _routing_descriptor(receipt.get("descriptor")) == _routing_descriptor(descriptor)
                and receipt.get("file_identity") == before and receipt.get("bytes") == before[2]
                and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
            return dict(receipt)
        raise ValueError("attributed output receipt is stale or mismatched")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if _identity(path) != before:
        raise ValueError("artifact changed while hashing")
    return {"version": 1, "sha256": digest.hexdigest(), "bytes": before[2],
            "file_identity": before, "prompt_id": prompt_id,
            "descriptor": dict(descriptor or {}), "producer": "collection"}


def copied_receipt(path: Path, receipt: dict) -> dict:
    identity = _identity(path)
    if identity[2] != receipt["bytes"]:
        raise ValueError("copied output length differs from receipt")
    return {**receipt, "file_identity": identity}


def content_receipt(receipt: Mapping, *, logical_path: str) -> dict:
    """Keep local filesystem observations out of serialized result identity."""
    return {
        **receipt,
        "file_identity": {
            "sha256": receipt["sha256"],
            "bytes": receipt["bytes"],
            "path": logical_path,
        },
    }


def project_evidence_receipts(
    value: object,
    observations: Mapping[str, Mapping],
    *,
    source_observations: Mapping[str, Mapping] | None = None,
) -> object:
    """Project receipt copies in producer evidence without changing their inputs.

    Retrieval records, artifact records and attempt metadata can each contain
    the same receipt. They all name the final logical output; only the private
    observations sidecar retains the inode and timestamp checks used locally.
    Source observations bind receipts from before a custody copy to that same
    output path. Equal content alone does not identify a collected output.
    """
    source_observations = source_observations or {}

    def project(item: object, logical_path: str | None = None) -> object:
        if isinstance(item, Mapping):
            if (item.get("version") == 1 and "file_identity" in item
                    and "sha256" in item and "bytes" in item):
                matches = [
                    path for path, observed in observations.items()
                    if (logical_path is None or path == logical_path)
                    and all(item.get(key) == observed.get(key)
                            for key in ("version", "sha256", "bytes", "prompt_id", "producer"))
                    and _routing_descriptor(item.get("descriptor"))
                    == _routing_descriptor(observed.get("descriptor"))
                    and item.get("file_identity") in (
                        observed["file_identity"],
                        source_observations.get(path, observed)["file_identity"],
                    )
                ]
                if len(matches) != 1:
                    raise ValueError("evidence receipt does not identify one collected output")
                return content_receipt(item, logical_path=matches[0])
            return {key: project(child, key if key in observations else None)
                    for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [project(child) for child in item]
        return item

    return project(value)
