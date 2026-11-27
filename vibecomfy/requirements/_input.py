"""Read a workflow or the selected entry revision without publication."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from vibecomfy.workflow import VibeWorkflow


class WorkflowNotAdmitted(ValueError):
    def __init__(self, binding):
        super().__init__("Python workflow preview requires its already-admitted canonical workflow")
        self.binding = binding


def read_workflow(source: str | Path | VibeWorkflow, *, workflow: VibeWorkflow | None = None):
    """Return a detached workflow and exact source member digests.

    Python is never executed here: a confirmation gate grants permission but
    cannot make arbitrary build() code read-only. A consumer which already
    admitted a bundle through the existing authority supplies its workflow;
    both that semantic projection and the actual source bytes are then bound.
    """
    members: list[dict[str, Any]] = []
    entry = None
    if isinstance(source, VibeWorkflow):
        if workflow is not None:
            raise ValueError("supply one workflow, not two")
        selected = source
        kind = "workflow"
    else:
        path = Path(source).expanduser()
        if not path.exists() and path.name == str(source):
            from vibecomfy.entries import entries_dir
            candidate = entries_dir() / path / "entry.json"
            if candidate.is_file():
                path = candidate
        if path.is_dir() and (path / "entry.json").is_file():
            path = path / "entry.json"
        if path.name == "entry.json":
            from vibecomfy.entries import load_entry
            entry = load_entry(path)
            manifest_bytes = path.read_bytes()
            members.append(_member("entry.json", manifest_bytes))
            path = Path(entry["bundle"]) / "workflow.py"
            kind = "entry"
        else:
            kind = "file"
        if path.is_dir():
            path = path / "workflow.py"
        payload = path.read_bytes()
        members.append(_member("workflow" + path.suffix.lower(), payload))
        if path.suffix.lower() == ".py":
            companion = path.with_suffix(".vibe.json")
            if companion.is_file():
                members.append(_member("workflow.vibe.json", companion.read_bytes()))
        if workflow is not None:
            selected = workflow
        elif path.suffix.lower() == ".json":
            from vibecomfy.ingest.normalize import _named_import
            from vibecomfy.porting.import_service import _conversion_provider
            raw = json.loads(payload)
            if not isinstance(raw, dict):
                raise ValueError("workflow file must contain a JSON object")
            selected = _named_import(raw, workflow_id="requirements-" + hashlib.sha256(payload).hexdigest(),
                                     schema_provider=_conversion_provider(), use_comfy_converter=False)
        else:
            binding = {"kind": kind, "members": members, "semantic": None}
            if entry is not None:
                binding["entry"] = entry
            raise WorkflowNotAdmitted(binding)
    if not isinstance(selected, VibeWorkflow):
        raise TypeError("workflow must be a VibeWorkflow")
    detached = copy.deepcopy(selected)
    # Canonical semantics bind inputs/outputs and ordered recipe declarations;
    # source bytes additionally bind edits which leave those semantics intact.
    binding = {"kind": kind, "members": members, "semantic": detached.semantic_projection()}
    if entry is not None:
        binding["entry"] = entry
    return detached, binding


def _member(name: str, payload: bytes) -> dict[str, Any]:
    return {"name": name, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)}
