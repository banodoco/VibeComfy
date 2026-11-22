from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from vibecomfy.node_packs import compute_schema_hash, read_lockfile

REPO = Path(__file__).resolve().parents[1]
PINNED_COMMIT = "006a709848259ed3d69e2f9fcfd7a75f6c860ddd"
CAPTURE = REPO / "tests/fixtures/comfyui/whisper_object_info_006a709.json"
OBJECT_INFO = REPO / "vibecomfy/porting/cache/object_info"


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

    # Resolve the node through the maintained object_info index, as runtime
    # schema lookup does, rather than trusting the separately copied capture.
    index = json.loads((OBJECT_INFO / "index.json").read_text(encoding="utf-8"))
    indexed_file = index["Apply Whisper"]
    indexed_object_info = json.loads((OBJECT_INFO / indexed_file).read_text(encoding="utf-8"))
    assert "Apply Whisper" in indexed_object_info
    indexed_hash = compute_schema_hash({"Apply Whisper": indexed_object_info["Apply Whisper"]})
    assert entry.class_schema_sha256 == indexed_hash
    assert entry.schema_hash == indexed_hash

    # Exercise the repo's runtime identity lookup, which is backed by the same
    # index and selected object_info shard.
    from vibecomfy.schema.provider import ObjectInfoIndexSchemaProvider

    runtime_schema = ObjectInfoIndexSchemaProvider(OBJECT_INFO).get_schema("Apply Whisper")
    assert runtime_schema is not None
    assert runtime_schema.class_type == "Apply Whisper"


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


def test_transcription_lock_generator_check(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")

    # A stale lock makes --check prove that it validates instead of silently
    # succeeding (or rewriting the lock as normal generation would).
    miniature_repo = tmp_path / "miniature-repo"
    (miniature_repo / "tools").mkdir(parents=True)
    object_info = miniature_repo / "vibecomfy/porting/cache/object_info"
    object_info.mkdir(parents=True)
    shutil.copy2(REPO / "tools/lock_transcription_node.py", miniature_repo / "tools/lock_transcription_node.py")
    shutil.copy2(REPO / "custom_nodes.lock", miniature_repo / "custom_nodes.lock")
    index_source = REPO / "vibecomfy/porting/cache/object_info/index.json"
    index = json.loads(index_source.read_text(encoding="utf-8"))
    indexed_filename = index["Apply Whisper"]
    shutil.copy2(index_source, object_info / "index.json")
    shutil.copy2(REPO / "vibecomfy/porting/cache/object_info" / indexed_filename, object_info / indexed_filename)

    lock_path = miniature_repo / "custom_nodes.lock"
    fresh_lock = lock_path.read_text(encoding="utf-8")
    whisper_entry = next(
        item for item in read_lockfile(lock_path) if item.name == "ComfyUI-Whisper"
    )
    assert whisper_entry.class_schema_sha256 is not None
    assert whisper_entry.schema_hash is not None
    stale_hash = "0" * 64
    stale_lock = fresh_lock.replace(
        f'class_schema_sha256 = "{whisper_entry.class_schema_sha256}"',
        f'class_schema_sha256 = "{stale_hash}"',
        1,
    ).replace(
        f'schema_hash = "{whisper_entry.schema_hash}"',
        f'schema_hash = "{stale_hash}"',
        1,
    )
    assert stale_lock != fresh_lock
    assert f'class_schema_sha256 = "{stale_hash}"' in stale_lock
    assert f'schema_hash = "{stale_hash}"' in stale_lock
    lock_path.write_text(stale_lock, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(miniature_repo / "tools/lock_transcription_node.py"), "--check"],
        cwd=miniature_repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "stale" in (result.stdout + result.stderr).lower()
    assert lock_path.read_text(encoding="utf-8") == stale_lock

    # The checked-in lock should still pass against the current indexed schema.
    clean_result = subprocess.run(
        [sys.executable, str(REPO / "tools/lock_transcription_node.py"), "--check"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert clean_result.returncode == 0, clean_result.stdout + clean_result.stderr
