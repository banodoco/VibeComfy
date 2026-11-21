"""Temporary audio files used by the Whisper node are private to each call."""
import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


SOURCE = Path(__file__).parents[1] / "vendor/patches/ComfyUI-Whisper/apply_whisper.py"


def _node(tmp_path, monkeypatch, *, load_error=None, transcribe_error=None):
    """Compile only the node method with small, controlled dependency doubles."""
    tree = ast.parse(SOURCE.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ApplyWhisperNode")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "apply_whisper")
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), "exec"), namespace)

    paths = []
    transcribe_paths = []

    class AudioModel:
        def transcribe(self, path, **kwargs):
            transcribe_paths.append(path)
            if transcribe_error:
                raise transcribe_error
            return {"text": "done", "segments": []}

    class PatchModel:
        model = SimpleNamespace(whisper_model=AudioModel())

    class FakeTorch:
        class nn:
            class Module:
                pass

    def write(path, waveform, sample_rate):
        paths.append(path)
        Path(path).write_bytes(b"private audio")

    def load_model_gpu(_patcher):
        if load_error:
            raise load_error

    globals_ = namespace["apply_whisper"].__globals__
    globals_.update({
        "os": __import__("os"),
        "tempfile": __import__("tempfile"),
        "uuid": SimpleNamespace(uuid1=lambda: "same-id"),
        "folder_paths": SimpleNamespace(get_temp_directory=lambda: str(tmp_path)),
        "soundfile": SimpleNamespace(write=write),
        "mm": SimpleNamespace(load_model_gpu=load_model_gpu),
        "WHISPER_PATCHER_CACHE": {"tiny": PatchModel()},
        "ApplyWhisperNode": SimpleNamespace(languages_by_name=None),
    })
    node = SimpleNamespace()
    node.apply_whisper = namespace["apply_whisper"].__get__(node)
    class Waveform:
        def squeeze(self, axis):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return np.zeros((1, 4))

    audio = {"waveform": Waveform(), "sample_rate": 16000}
    return node, audio, paths, transcribe_paths


def test_whisper_temp_audio_is_unique_and_removed_after_success(tmp_path, monkeypatch):
    node, audio, paths, transcribe_paths = _node(tmp_path, monkeypatch)

    node.apply_whisper(audio, "tiny", "auto", "")
    node.apply_whisper(audio, "tiny", "auto", "")

    assert len(paths) == 2
    assert paths[0] != paths[1]
    assert transcribe_paths == paths
    assert all(not Path(path).exists() for path in paths)


@pytest.mark.parametrize("failure", ["load", "transcribe"])
def test_whisper_temp_audio_is_removed_after_failures(tmp_path, monkeypatch, failure):
    kwargs = {"load_error": RuntimeError("load failed")} if failure == "load" else {
        "transcribe_error": RuntimeError("transcribe failed")
    }
    node, audio, paths, _ = _node(tmp_path, monkeypatch, **kwargs)

    with pytest.raises(RuntimeError, match=f"{failure} failed"):
        node.apply_whisper(audio, "tiny", "auto", "")

    assert len(paths) == 1
    assert not Path(paths[0]).exists()
