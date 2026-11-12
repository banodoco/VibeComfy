from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import vibecomfy.fetch as fetch
from vibecomfy.runtime.prepared import PreparationError, prepare_workflow


class _Response:
    status_code = 200

    def iter_bytes(self):
        yield b"model-bytes"


@contextmanager
def _stream(*_args: Any, **_kwargs: Any):
    yield _Response()


def _workflow(entry: dict[str, Any]) -> Any:
    return SimpleNamespace(
        metadata={"model_assets": [entry]},
        nodes={},
        runtime_nodes=lambda: {},
        requirements=SimpleNamespace(models=[], custom_nodes=[]),
    )


def _prepare(entry: dict[str, Any], runtime: Path) -> Any:
    return prepare_workflow(
        _workflow(entry),
        reference=runtime / "workflow.json",
        runtime_root=runtime,
        ensure_packs=False,
        quiet=True,
    )


def test_preparation_resolves_configured_root_through_runtime_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    configured = tmp_path / "shared"
    (configured / "TTS").mkdir(parents=True)
    runtime_models = runtime / "ComfyUI" / "models"
    runtime_models.mkdir(parents=True)
    (runtime_models / "TTS").symlink_to(configured / "TTS", target_is_directory=True)
    monkeypatch.setenv("VIBECOMFY_MODELS_ROOT", str(configured))
    monkeypatch.setattr(fetch.httpx, "stream", _stream)
    entry = {"name": "voice.bin", "subdir": "TTS", "url": "https://example.test/voice"}

    result = _prepare(entry, runtime)

    expected = configured / "TTS" / "voice.bin"
    assert result.model_paths == (str(expected),)
    assert fetch.local_path(entry) == expected
    assert (runtime_models / "TTS").resolve() == expected.parent
    assert expected.read_bytes() == b"model-bytes"


def test_preparation_without_configured_root_uses_runtime_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VIBECOMFY_MODELS_ROOT", raising=False)
    monkeypatch.delenv("COMFY_MODELS_ROOT", raising=False)
    monkeypatch.delenv("COMFYUI_EXTRA_MODEL_PATHS_PATH", raising=False)
    monkeypatch.setattr(fetch.httpx, "stream", _stream)
    runtime = tmp_path / "runtime"
    entry = {"name": "voice.bin", "subdir": "TTS", "url": "https://example.test/voice"}

    result = _prepare(entry, runtime)

    expected = runtime / "ComfyUI" / "models" / "TTS" / "voice.bin"
    assert result.model_paths == (str(expected),)
    assert expected == runtime / "ComfyUI" / "models" / "TTS" / "voice.bin"


@pytest.mark.parametrize(
    "entry_factory",
    [
        lambda outside: {"name": "../escape.bin", "subdir": "TTS", "url": "https://example.test/x"},
        lambda outside: {"name": "voice.bin", "target_path": str(outside / "absolute.bin"), "url": "https://example.test/x"},
        lambda outside: {"name": "voice.bin", "subdir": "TTS", "url": "https://example.test/x"},
    ],
    ids=["traversal", "absolute-target", "symlink-escape"],
)
def test_preparation_rejects_paths_escaping_configured_model_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry_factory: Any
) -> None:
    configured = tmp_path / "shared"
    configured.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (configured / "TTS").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("VIBECOMFY_MODELS_ROOT", str(configured))
    entry = entry_factory(outside)

    with pytest.raises(PreparationError, match="invalid model declaration|model preparation failed"):
        _prepare(entry, tmp_path / "runtime")


def test_fetch_and_preparation_agree_on_configured_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "shared"
    configured.mkdir()
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("VIBECOMFY_MODELS_ROOT", str(configured))
    monkeypatch.setattr(fetch.httpx, "stream", _stream)
    entry = {"name": "voice.bin", "subdir": "TTS", "url": "https://example.test/voice"}

    result = _prepare(entry, runtime)
    fetched_path = fetch.local_path(entry)

    assert result.model_paths == (str(fetched_path),)
    assert fetched_path == configured / "TTS" / "voice.bin"


def test_target_path_uses_runtime_comfyui_root_with_configured_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "shared"
    configured.mkdir()
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("VIBECOMFY_MODELS_ROOT", str(configured))
    monkeypatch.setattr(fetch.httpx, "stream", _stream)
    entry = {"name": "voice.bin", "target_path": "models/TTS/voice.bin", "url": "https://example.test/voice"}

    result = _prepare(entry, runtime)

    expected = runtime / "ComfyUI" / "models" / "TTS" / "voice.bin"
    assert result.model_paths == (str(expected),)
    assert expected.read_bytes() == b"model-bytes"


def test_target_path_cannot_escape_runtime_comfyui_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIBECOMFY_MODELS_ROOT", str(tmp_path / "shared"))
    entry = {"name": "voice.bin", "target_path": "../outside/voice.bin", "url": "https://example.test/voice"}

    with pytest.raises(PreparationError, match="invalid model declaration"):
        _prepare(entry, tmp_path / "runtime")


def test_target_path_symlink_cannot_escape_runtime_comfyui_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    comfyui = runtime / "ComfyUI"
    comfyui.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (comfyui / "models").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("VIBECOMFY_MODELS_ROOT", str(tmp_path / "shared"))
    entry = {"name": "voice.bin", "target_path": "models/voice.bin", "url": "https://example.test/voice"}

    with pytest.raises(PreparationError, match="invalid model declaration"):
        _prepare(entry, runtime)


def test_fetch_target_path_uses_comfyui_path_with_configured_model_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "shared-models"
    comfyui = tmp_path / "comfy-install"
    configured.mkdir()
    comfyui.mkdir()
    monkeypatch.setenv("VIBECOMFY_MODELS_ROOT", str(configured))
    monkeypatch.setenv("COMFYUI_PATH", str(comfyui))
    monkeypatch.setattr(fetch.httpx, "stream", _stream)
    entry = {
        "name": "custom.py",
        "target_path": "custom_nodes/sample/custom.py",
        "url": "https://example.test/custom",
    }

    path = fetch.download(entry, quiet=True)

    assert path == comfyui / "custom_nodes" / "sample" / "custom.py"
    assert path.read_bytes() == b"model-bytes"


def test_fetch_target_path_symlink_escape_is_refused_with_comfyui_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "shared-models"
    comfyui = tmp_path / "comfy-install"
    outside = tmp_path / "outside"
    configured.mkdir()
    outside.mkdir()
    comfyui.mkdir()
    (comfyui / "custom_nodes").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("VIBECOMFY_MODELS_ROOT", str(configured))
    monkeypatch.setenv("COMFYUI_PATH", str(comfyui))
    entry = {
        "name": "custom.py",
        "target_path": "custom_nodes/sample/custom.py",
        "url": "https://example.test/custom",
    }

    with pytest.raises(ValueError, match="resolves outside its authorized root"):
        fetch.local_path(entry)


def test_fetch_target_path_without_comfyui_path_uses_configured_root_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "shared-models"
    configured.mkdir()
    monkeypatch.setenv("VIBECOMFY_MODELS_ROOT", str(configured))
    monkeypatch.delenv("COMFYUI_PATH", raising=False)
    entry = {"name": "custom.py", "target_path": "custom_nodes/sample/custom.py"}

    assert fetch.local_path(entry) == tmp_path / "custom_nodes" / "sample" / "custom.py"
