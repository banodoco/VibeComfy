"""WS-0b: the owner's SAM API fixture (astrid-dev 13895ffe source blob)."""
from __future__ import annotations

import json

from vibecomfy.entries import import_as_entry
from vibecomfy.model_assets import _referenced_model_values, _subdir_for_model_reference
from vibecomfy.security.provenance import Provenance
from vibecomfy.workflow_bundle import load_bundle

# Exact graph and values from plans/56-workflow-setup/evidence/sam-test-files/
# sam-audio-separation.api.json, source blob 13895ffee92f7bd50e04ff5973253d961f18c87e.
SAM_API = {
    "1": {"class_type": "SAMAudioPipelineLoader", "_meta": {"title": "SAM-Audio Model Loader"},
          "inputs": {"model_name": "facebook/sam-audio-large", "attention_backend": "pytorch",
                     "precision": "auto", "initial_device": "cpu"}},
    "2": {"class_type": "LoadAudio", "_meta": {"title": "Load Audio (set to the clip's audio file)"},
          "inputs": {"audio": "input.wav"}},
    "3": {"class_type": "SAMAudioTextSeparator", "_meta": {"title": "SAM-Audio Text Separate (set description)"},
          "inputs": {"pipeline": ["1", 0], "audio": ["2", 0], "description": "man speaking",
                     "predict_spans": False, "seed": 0, "inference_steps": 32, "chunk_duration": 10.0,
                     "chunk_overlap": 1.0, "reranking_candidates": 1}},
    "4": {"class_type": "SaveAudio", "_meta": {"title": "Save target (the described sound)"},
          "inputs": {"audio": ["3", 0], "filename_prefix": "audio/sam_target"}},
    "5": {"class_type": "SaveAudio", "_meta": {"title": "Save residual (everything else)"},
          "inputs": {"audio": ["3", 1], "filename_prefix": "audio/sam_residual"}},
}


def test_sam_generic_model_name_is_unresolved_not_an_asset_or_ambiguity(tmp_path):
    source = tmp_path / "sam.json"
    source.write_text(json.dumps(SAM_API), encoding="utf-8")
    entry = import_as_entry(source, "sam", tmp_path / "entries")
    unresolved = [need for need in entry["needs"] if need.get("unresolved")]
    assert len(unresolved) == 1
    assert unresolved[0] == {
        "node_id": "1", "class_type": "SAMAudioPipelineLoader", "field": "model_name",
        "value": "facebook/sam-audio-large", "role": None, "unresolved": True,
    }
    # WS-0a's audio mode advisory is distinct from a model/binding ambiguity.
    assert [n.get("code") for n in entry["needs"] if n.get("ambiguity")] == ["audio_mode_unknown"]
    assert _subdir_for_model_reference("SAMAudioPipelineLoader", "model_name") is None
    workflow = load_bundle(entry["bundle"], trust=Provenance.USER_CONFIRMED).workflow
    assert not _referenced_model_values(workflow)
    assert len(_referenced_model_values(workflow, include_unresolved=True)) == 1


def test_explicit_class_specific_model_name_directories_are_preserved():
    expected = {
        "LatentUpscaleModelLoader": "latent_upscale_models",
        "LoadWanVideoT5TextEncoder": "text_encoders",
        "WanVideoTextEncodeCached": "text_encoders",
        "WanVideoVAELoader": "vae",
        "WanVideoModelLoader": "diffusion_models",
    }
    assert {cls: _subdir_for_model_reference(cls, "model_name") for cls in expected} == expected
    assert _subdir_for_model_reference("CustomMysteryLoader", "model_name") is None
