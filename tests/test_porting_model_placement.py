from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibecomfy.porting.assets import analyze_model_assets
from vibecomfy.porting.import_service import import_workflow_bytes
from vibecomfy.porting.workbench import analyze_source


def _ui_workflow(class_type: str, filename: str) -> dict:
    vae_slot = 2 if class_type == "CheckpointLoaderSimple" else 0
    return {
        "nodes": [
            {"id": 1, "type": class_type, "inputs": [], "widgets_values": [filename]},
            {"id": 2, "type": "EmptyLatentImage", "inputs": [], "widgets_values": [64, 64, 1]},
            {"id": 3, "type": "VAEDecode", "inputs": [
                {"name": "samples", "type": "LATENT", "link": 1},
                {"name": "vae", "type": "VAE", "link": 2},
            ], "widgets_values": []},
            {"id": 4, "type": "SaveImage", "inputs": [
                {"name": "images", "type": "IMAGE", "link": 3},
            ], "widgets_values": ["placement-test"]},
        ],
        "links": [
            [1, 2, 0, 3, 0, "LATENT"],
            [2, 1, vae_slot, 3, 1, "VAE"],
            [3, 3, 0, 4, 0, "IMAGE"],
        ],
    }


@pytest.mark.parametrize(
    ("class_type", "filename", "subdir"),
    [
        ("CheckpointLoaderSimple", "checkpoint.ckpt", "checkpoints"),
        ("VAELoader", "decoder.safetensors", "vae"),
    ],
)
def test_ui_import_keeps_filename_only_loader_placement(class_type, filename, subdir) -> None:
    artifacts = import_workflow_bytes(
        json.dumps(_ui_workflow(class_type, filename)).encode(),
        workflow_id="filename-only-placement",
        infer_inputs=True,
    )

    assert artifacts.report["validation"]["structural_and_parity"]["ok"] is True
    warnings = [
        issue for issue in artifacts.report["diagnostics"]
        if issue["code"] == "filename_only_asset_candidate"
    ]
    assert len(warnings) == 1
    assert warnings[0]["detail"]["name"] == filename
    assert warnings[0]["detail"]["subdir"] == subdir
    assert warnings[0]["class_type"] == class_type


def test_filename_only_requirement_needs_placement_from_its_loader(tmp_path: Path) -> None:
    filename = "checkpoint.ckpt"
    with pytest.raises(ValueError, match="unknown placement for ''; declare subdir explicitly"):
        analyze_model_assets(ready_requirements={"models": [filename]})

    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(_ui_workflow("CheckpointLoaderSimple", filename)))
    report = analyze_source(str(path))

    assert [(candidate.name, candidate.subdir) for candidate in report.asset_candidates] == [
        (filename, "checkpoints"),
    ]
    assert report.asset_candidates[0].metadata["sources"] == ["api_prompt", "ready_requirements"]
