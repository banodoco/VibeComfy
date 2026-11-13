"""The shipped music entry offers song controls and song-sized defaults."""
from __future__ import annotations

import json
from pathlib import Path

from vibecomfy.contracts import build_contract
from vibecomfy.registry.ready import workflow_from_ready
from vibecomfy.registry.static_contract import extract_ready_template_contract


ROOT = Path(__file__).resolve().parents[1]
ENTRY = "audio/ace_step_1_5_t2a_song"
SOURCE = ROOT / "ready_templates/sources/official/audio/ace_step_1_5_t2a_song.json"


def _nodes(api):
    return {node["class_type"]: node["inputs"] for node in api.values()}


def test_music_public_inputs_and_defaults():
    workflow = workflow_from_ready(ENTRY)
    assert set(workflow.inputs) == {"prompt", "lyrics", "duration", "seed"}
    source_nodes = {node["type"]: node for node in json.loads(SOURCE.read_text())["nodes"]}
    tags, lyrics = source_nodes["TextEncodeAceStepAudio1.5"]["widgets_values"][:2]
    expected = {"prompt": ("STRING", tags), "lyrics": ("STRING", lyrics),
                "duration": ("FLOAT", 30.0), "seed": ("INT", 561594583201063)}
    for name, (kind, default) in expected.items():
        port = workflow.inputs[name]
        assert port.type == kind
        assert port.default == default
        assert type(port.default) is {"STRING": str, "FLOAT": float, "INT": int}[kind]
    static = extract_ready_template_contract(ROOT / f"ready_templates/{ENTRY}.py")
    built = build_contract(workflow).to_dict()
    indexed = next(row for row in json.loads((ROOT / "template_index.json").read_text())["templates"]
                   if row["id"] == ENTRY)
    for contract in (static, built, indexed):
        assert {port["name"] for port in contract["public_inputs"]} == set(expected)


def test_music_default_api_is_a_song_and_preserves_required_fields():
    workflow = workflow_from_ready(ENTRY)
    api = workflow.compile("api")
    nodes = _nodes(api)
    text = nodes["TextEncodeAceStepAudio1.5"]
    assert text["duration"] == 30.0
    assert nodes["EmptyAceStep1.5LatentAudio"]["seconds"] == 30.0
    assert nodes["KSampler"]["steps"] == 8
    assert nodes["KSampler"]["cfg"] == 1
    assert nodes["SaveAudioMP3"]["filename_prefix"] == "audio/ace_step_song"
    assert workflow.outputs[0].filename_prefix == "audio/ace_step_song"
    assert nodes["KSampler"]["denoise"] == 1
    assert nodes["SaveAudioMP3"]["quality"] == "V0"
    assert {key: text[key] for key in ("bpm", "temperature", "top_k", "min_p", "top_p", "generate_audio_codes")} == {
        "bpm": 120, "temperature": 0.85, "top_k": 0, "min_p": 0,
        "top_p": 0.9, "generate_audio_codes": True,
    }
    assert text["cfg_scale"] == 1.5
    assert "smoke" not in json.dumps(api).lower()
    source_nodes = {node["type"]: node for node in json.loads(SOURCE.read_text())["nodes"]}
    assert source_nodes["PrimitiveFloat"]["widgets_values"] == [30.0]
    assert source_nodes["EmptyAceStep1.5LatentAudio"]["widgets_values"] == [30.0, 1]
    assert source_nodes["TextEncodeAceStepAudio1.5"]["widgets_values"][4] == 30.0
    assert source_nodes["KSampler"]["widgets_values"][2:4] == [8, 1]
    assert source_nodes["SaveAudioMP3"]["widgets_values"] == ["audio/ace_step_song", "V0"]


def test_music_overrides_reach_conditioning_and_audio_length():
    workflow = workflow_from_ready(ENTRY)
    for name, value in {"prompt": "acoustic folk, warm vocals", "lyrics": "[Verse]\nA new day begins",
                        "duration": 2.0, "seed": 7}.items():
        workflow.set_input(name, value)
    nodes = _nodes(workflow.compile("api"))
    text = nodes["TextEncodeAceStepAudio1.5"]
    assert text["tags"] == "acoustic folk, warm vocals"
    assert text["lyrics"] == "[Verse]\nA new day begins"
    assert text["duration"] == 2.0
    assert nodes["EmptyAceStep1.5LatentAudio"]["seconds"] == 2.0
    assert text["seed"] == nodes["KSampler"]["seed"] == 7
    assert nodes["KSampler"]["steps"] == 8


def test_catalog_defaults_do_not_use_smoke_output_prefixes():
    """Runtime smoke utilities are explicitly separate from media catalog entries."""
    rows = json.loads((ROOT / "template_index.json").read_text())["templates"]
    offenders = []
    for row in rows:
        if not row.get("indexed") or row.get("capability") == "runtime_smoke":
            continue
        for port in row["public_outputs"] + row["artifact_expectations"]:
            prefix = port.get("filename_prefix") or ""
            if "smoke" in prefix.lower():
                offenders.append((row["id"], prefix))
    assert not offenders
