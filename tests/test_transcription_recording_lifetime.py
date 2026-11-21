"""The Whisper replacement owns the WAV only while transcribing."""
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def whisper_patch(monkeypatch, tmp_path):
    comfy = ModuleType('comfy')
    comfy.model_management = ModuleType('comfy.model_management')
    comfy.model_patcher = ModuleType('comfy.model_patcher')
    comfy.model_patcher.ModelPatcher = object
    monkeypatch.setitem(sys.modules, 'comfy', comfy)
    monkeypatch.setitem(sys.modules, 'comfy.model_management', comfy.model_management)
    monkeypatch.setitem(sys.modules, 'comfy.model_patcher', comfy.model_patcher)
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(nn=SimpleNamespace(Module=object)))
    monkeypatch.setitem(sys.modules, 'whisper', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'soundfile', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'folder_paths', SimpleNamespace(get_temp_directory=lambda: str(tmp_path)))
    source = Path(__file__).resolve().parents[1] / 'vendor/patches/ComfyUI-Whisper/apply_whisper.py'
    spec = importlib.util.spec_from_file_location('transcription_patch', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('failure', [None, 'write', 'transcribe', 'model'])
def test_recording_lifetime(whisper_patch, tmp_path, failure):
    def load_model(patcher):
        assert list(tmp_path.iterdir()) == []
        if failure == 'model':
            raise RuntimeError('model failed')

    waveform = SimpleNamespace(ndim=1)

    def write(path, samples, sample_rate):
        assert samples is waveform
        assert sample_rate == 16000
        recording = Path(path)
        assert recording.parent.parent == tmp_path
        recording.write_bytes(b'waveform')
        if failure == 'write':
            raise RuntimeError('write failed')

    def transcribe(path, *, word_timestamps, initial_prompt):
        assert Path(path).read_bytes() == b'waveform'
        assert word_timestamps is True
        assert initial_prompt == 'prompt'
        if failure == 'transcribe':
            raise RuntimeError('transcribe failed')
        return {
            'text': ' hello ',
            'segments': [{'text': ' hello ', 'start': 0, 'end': 1,
                          'words': [{'word': ' hello ', 'start': 0, 'end': 1}]}],
        }

    whisper_patch.mm.load_model_gpu = load_model
    whisper_patch.soundfile.write = Mock(side_effect=write)
    model = SimpleNamespace(transcribe=Mock(side_effect=transcribe))
    whisper_patch.WHISPER_PATCHER_CACHE['small'] = SimpleNamespace(
        model=SimpleNamespace(whisper_model=model)
    )
    audio = {'waveform': Mock(), 'sample_rate': 16000}
    audio['waveform'].squeeze.return_value.cpu.return_value.numpy.return_value = waveform
    node = whisper_patch.ApplyWhisperNode()
    if failure:
        with pytest.raises(RuntimeError, match=f'{failure} failed'):
            node.apply_whisper(audio, 'small', 'auto', 'prompt')
    else:
        alignment = [{'value': 'hello', 'start': 0, 'end': 1}]
        assert node.apply_whisper(audio, 'small', 'auto', 'prompt') == ('hello', alignment, alignment)
    assert list(tmp_path.iterdir()) == []
    assert whisper_patch.soundfile.write.call_count == int(failure != 'model')
    assert model.transcribe.call_count == int(failure not in {'write', 'model'})
