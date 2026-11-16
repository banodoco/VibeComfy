import json
import sys
from types import SimpleNamespace

from vibecomfy.comfy_nodes.transcript_output import VibeComfySaveTranscript


def test_output_preserves_complete_alignment_and_declares_file(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "folder_paths", SimpleNamespace(
        get_output_directory=lambda: str(tmp_path),
        get_save_image_path=lambda prefix, directory: (directory, prefix, 1, "", prefix),
    ))
    segments = [{"value": "hello", "start": 0.123456789, "end": 1.234567891}]
    words = [{"value": "hello", "start": 0.123456789, "end": 1.234567891}]
    node = VibeComfySaveTranscript()
    result = node.save("hello", segments, words)
    descriptor = result["ui"]["images"][0]
    assert descriptor == {"filename": "transcript_00001_.json", "subfolder": "", "type": "output"}
    assert json.loads((tmp_path / descriptor["filename"]).read_text()) == ["hello", segments, words]
    assert node.OUTPUT_NODE
