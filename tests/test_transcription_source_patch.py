"""The recipe replacement refuses missing or corrupt local model bytes."""
import ast
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


def _loader(model_name, root, calls):
    source = (Path(__file__).parents[1] / 'vendor/patches/ComfyUI-Whisper/apply_whisper.py').read_text()
    module = ast.parse(source)
    cls = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == 'WhisperModelWrapper')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'load_model')
    tree = ast.Module(body=[method], type_ignores=[])
    namespace = {'os': os, 'hashlib': hashlib, 'whisper': SimpleNamespace(
        _MODELS={'large-v3-turbo': 'https://example.invalid/aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a/large-v3-turbo.pt',
                 'small': 'https://example.invalid/' + hashlib.sha256(b'ok').hexdigest() + '/small.pt'},
        load_model=lambda path, **kwargs: calls.append((path, kwargs)) or SimpleNamespace(parameters=lambda: []))}
    exec(compile(tree, '<patched loader>', 'exec'), namespace)
    obj = SimpleNamespace(model_name=model_name, download_root=str(root), whisper_model=None)
    return lambda: namespace['load_model'](obj, 'cpu')


def test_patch_never_downloads_and_checks_bytes(tmp_path, monkeypatch):
    calls = []
    load = _loader('large-v3-turbo', tmp_path, calls)
    with pytest.raises(RuntimeError, match='not provisioned'):
        load()
    (tmp_path / 'large-v3-turbo.pt').write_bytes(b'wrong')
    with pytest.raises(RuntimeError, match='size mismatch'):
        load()
    with monkeypatch.context() as patch:
        patch.setattr(os.path, 'getsize', lambda path: 1617941637)
        with pytest.raises(RuntimeError, match='SHA-256 mismatch'):
            load()
    small = tmp_path / 'small.pt'
    small.write_bytes(b'wrong')
    with pytest.raises(RuntimeError, match='SHA-256 mismatch'):
        _loader('small', tmp_path, calls)()
    assert calls == []
    small.write_bytes(b'ok')
    _loader('small', tmp_path, calls)()
    assert calls == [(str(small), {'device': 'cpu'})]
