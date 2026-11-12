from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from vibecomfy.commands.fetch import _cmd_fetch

from tests._cli_helpers import _write_fetch_scratchpad


def test_fetch_cli_dry_run_lists_entries_without_downloading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scratchpad = _write_fetch_scratchpad(tmp_path)
    present = tmp_path / "models" / "checkpoints" / "present.safetensors"
    present.parent.mkdir(parents=True)
    present.write_bytes(b"present")
    monkeypatch.setenv("VIBECOMFY_MODELS_ROOT", str(tmp_path / "models"))
    calls = 0

    def download_many(_entries, *, force=False):
        nonlocal calls
        calls += 1
        raise AssertionError("download_many must not be called during dry-run")

    import vibecomfy.fetch as fetch_assets

    monkeypatch.setattr(fetch_assets, "download_many", download_many)

    assert _cmd_fetch(argparse.Namespace(workflow=str(scratchpad), force=False, dry_run=True)) == 0

    captured = capsys.readouterr()
    assert "present present.safetensors" in captured.out
    assert f"would fetch missing.safetensors -> {tmp_path / 'models' / 'checkpoints' / 'missing.safetensors'}" in captured.out
    assert calls == 0


def test_fetch_cli_invokes_download_many(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scratchpad = _write_fetch_scratchpad(tmp_path)
    calls: list[tuple[list[dict], bool]] = []

    def download_many(entries, *, force=False):
        calls.append((entries, force))
        return []

    import vibecomfy.fetch as fetch_assets

    monkeypatch.setattr(fetch_assets, "download_many", download_many)

    assert _cmd_fetch(argparse.Namespace(workflow=str(scratchpad), force=True, dry_run=False)) == 0

    assert calls == [
        (
            [
                {
                    "name": "present.safetensors",
                    "url": "https://example.test/present.safetensors",
                    "subdir": "checkpoints",
                    "sha256": None,
                    "size_bytes": None,
                },
                {
                    "name": "missing.safetensors",
                    "url": "https://example.test/missing.safetensors",
                    "subdir": "checkpoints",
                    "sha256": None,
                    "size_bytes": None,
                },
            ],
            True,
        )
    ]


def test_fetch_cli_rejects_model_field_alias_before_downloading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratchpad = _write_fetch_scratchpad(tmp_path)
    source = scratchpad.read_text(encoding="utf-8")
    scratchpad.write_text(source.replace('"subdir": "checkpoints"', '"directory": "checkpoints"'), encoding="utf-8")

    def unexpected_download(*_args, **_kwargs):
        raise AssertionError("legacy alias reached downloader")

    import vibecomfy.fetch as fetch_assets

    monkeypatch.setattr(fetch_assets, "download_many", unexpected_download)

    with pytest.raises(ValueError, match="filename/directory aliases"):
        _cmd_fetch(argparse.Namespace(workflow=str(scratchpad), force=False, dry_run=False))


def test_fetch_reads_structured_requirements_without_metadata() -> None:
    from types import SimpleNamespace
    from vibecomfy.commands._model_entries import model_entries_for_workflow

    record = {"name": "weights.bin", "subdir": "vae", "url": None,
              "sha256": None, "size_bytes": None}
    workflow = SimpleNamespace(metadata={}, requirements=SimpleNamespace(models=[record]))
    assert model_entries_for_workflow(workflow, "unmaterialized.py") == [{**record, "unresolved": True}]


@pytest.mark.parametrize("record", ["weights.bin", {"name": "weights.bin"}])
def test_fetch_refuses_undeclared_requirements_instead_of_omitting_them(record) -> None:
    from types import SimpleNamespace
    from vibecomfy.commands._model_entries import model_entries_for_workflow

    workflow = SimpleNamespace(metadata={}, requirements=SimpleNamespace(models=[record]))
    with pytest.raises(ValueError, match="explicit.*(name and subdir|subdir)"):
        model_entries_for_workflow(workflow, "unmaterialized.py")
