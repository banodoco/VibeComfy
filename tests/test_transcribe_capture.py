from __future__ import annotations

import json
from pathlib import Path

from vibecomfy.node_packs import compute_schema_hash, read_lockfile

REPO = Path(__file__).resolve().parents[1]
PINNED_COMMIT = "006a709848259ed3d69e2f9fcfd7a75f6c860ddd"
CAPTURE = REPO / "tests/fixtures/comfyui/whisper_object_info_006a709.json"


def test_pinned_whisper_object_info_capture_and_lock_schema_match() -> None:
    captured = json.loads(CAPTURE.read_text(encoding="utf-8"))
    assert captured["provenance"]["kind"] == "source-derived stub execution"
    assert "Not captured from a live ComfyUI server" in captured["provenance"]["limitation"]
    schema = captured["Apply Whisper"]
    languages = schema["inputs"]["optional"]["language"][0]

    assert len(languages) == 101
    assert languages[0] == "auto"
    assert "English" in languages
    assert "Cantonese" in languages
    assert [output["type"] for output in schema["outputs"]] == ["STRING", "whisper_alignment", "whisper_alignment"]

    entry = next(item for item in read_lockfile(REPO / "custom_nodes.lock") if item.name == "ComfyUI-Whisper")
    expected_hash = compute_schema_hash({"Apply Whisper": schema})
    assert entry.git_commit_sha == PINNED_COMMIT
    assert entry.class_set == ("Apply Whisper",)
    assert entry.class_schema_sha256 == expected_hash
    assert entry.schema_hash == expected_hash


def test_transcribe_template_and_index_declare_the_locked_whisper_capture() -> None:
    template = (REPO / "ready_templates/audio/transcribe.py").read_text(encoding="utf-8")
    index = json.loads((REPO / "template_index.json").read_text(encoding="utf-8"))
    row = next(item for item in index["templates"] if item["id"] == "audio/transcribe")

    expected_hash = compute_schema_hash({"Apply Whisper": json.loads(CAPTURE.read_text(encoding="utf-8"))["Apply Whisper"]})
    assert expected_hash in template
    assert row["id"] == "audio/transcribe"
    assert row["path"] == "ready_templates/audio/transcribe.py"
    assert row["capability"] == "audio"
    assert row["custom_nodes"] == ["ComfyUI-Whisper"]
    assert row["model_count"] == 1
    assert row["model_assets"][0]["name"] == "large-v3-turbo"
    assert row["model_assets"][0]["filename"] == "large-v3-turbo.pt"
    assert row["public_inputs"] == [
        {
            "name": "audio_ref",
            "target": {"node_id": "1", "field": "audio"},
            "node_id": "1",
            "field": "audio",
            "value": "input.wav",
            "type": "COMBO",
            "default": "input.wav",
            "required": True,
            "range": None,
            "aliases": [],
            "media_semantics": "audio",
            "status": "static",
            "source": "InputSpec",
        }
    ]
    assert row["public_outputs"][0]["name"] == "transcript_json"
    assert row["public_output_status"] == "declared"
    assert row["public_input_status"] == "declared"
    assert row["custom_node_refs"][0]["class_schema_sha256"] == expected_hash
