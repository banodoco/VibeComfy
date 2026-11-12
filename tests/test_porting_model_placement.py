from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from vibecomfy.porting.assets import analyze_model_assets
from vibecomfy.porting.import_service import import_workflow_bytes
from vibecomfy.porting.workbench import analyze_source
from vibecomfy import fetch
from vibecomfy.runtime.prepared import PreparationError, _model_entries, _validate_model_destinations


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


def test_filename_only_requirement_keeps_placement_from_its_loader(tmp_path: Path) -> None:
    filename = "checkpoint.ckpt"
    candidate = analyze_model_assets(ready_requirements={"models": [filename]}).candidates[0]
    assert candidate.subdir is None
    assert candidate.placement_reason == "no loader class"

    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(_ui_workflow("CheckpointLoaderSimple", filename)))
    report = analyze_source(str(path))

    assert [(candidate.name, candidate.subdir) for candidate in report.asset_candidates] == [
        (filename, "checkpoints"),
    ]
    assert report.asset_candidates[0].metadata["sources"] == ["api_prompt", "ready_requirements"]


@pytest.mark.parametrize("class_type", ["SeedImage", ""])
@pytest.mark.parametrize("url", [None, "https://example.invalid/installed.safetensors"])
def test_unknown_placement_is_analysis_fact_until_file_placement(class_type, url, tmp_path) -> None:
    model = {"name": "installed.safetensors", "url": url}
    analysis = analyze_model_assets(raw_workflow={"nodes": [{
        "id": 1, "type": class_type, "properties": {"models": [model]},
    }]})
    candidate = analysis.candidates[0]
    assert candidate.subdir is None
    assert candidate.placement_reason == (
        "no known directory for loader class 'SeedImage'" if class_type else "no loader class"
    )
    assert analysis.to_json()["candidates"][0]["placement_reason"] == candidate.placement_reason
    record = candidate.to_json()
    message = f"unknown placement for {class_type!r}; declare subdir explicitly"
    with pytest.raises(ValueError, match=message):
        fetch.download(record, root=tmp_path)
    with pytest.raises(PreparationError, match=message):
        _validate_model_destinations((record,), tmp_path)
    with pytest.raises(PreparationError, match=message):
        _model_entries(SimpleNamespace(metadata={"model_assets": [record]}))
    from vibecomfy.runtime.dependencies import _discover_models
    from vibecomfy.commands.workflows import _asset_metadata

    with pytest.raises(ValueError, match=message):
        _discover_models(tmp_path, (record,))
    with pytest.raises(ValueError, match=message):
        _asset_metadata(record, models_root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_custom_node_with_installed_filename_converts_without_placement(tmp_path, monkeypatch) -> None:
    # A real schema makes this a known custom class, without inventing a
    # class-to-directory rule for it. No model download is requested.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "node_index.json").write_text(json.dumps([
        {"class_type": "SeedImage", "pack": "test", "inputs": {
            "seed": {"type": "INT", "required": True},
            "model": {"type": "STRING", "required": True, "choices": ["installed.safetensors"]},
        }, "outputs": [{"type": "IMAGE", "name": "IMAGE"}]},
        {"class_type": "SaveImage", "pack": "core", "inputs": {
            "images": {"type": "IMAGE", "required": True},
            "filename_prefix": {"type": "STRING", "required": True},
        }, "outputs": []},
    ]))
    workflow = {"nodes": [
        {"id": 1, "type": "SeedImage", "inputs": [], "widgets_values": [42, "installed.safetensors"]},
        {"id": 2, "type": "SaveImage", "inputs": [{"name": "images", "type": "IMAGE", "link": 1}],
         "widgets_values": ["placement"]},
    ], "links": [[1, 1, 0, 2, 0, "IMAGE"]]}
    artifacts = import_workflow_bytes(json.dumps(workflow).encode(), workflow_id="custom-placement")
    assert artifacts.report["validation"]["structural_and_parity"]["ok"] is True
    warning = next(issue for issue in artifacts.report["diagnostics"] if issue["code"] == "filename_only_asset_candidate")
    assert warning["detail"]["subdir"] is None
    assert warning["detail"]["placement_reason"] == "no known directory for loader class 'SeedImage'"
