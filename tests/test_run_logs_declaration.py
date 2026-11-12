from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from vibecomfy.registry.models_loader import ModelEntry, ModelSource, ModelTarget
from vibecomfy.schema import NodeSchema
from vibecomfy.runtime.run_context import RunContext
from vibecomfy.runtime.run_logs import DECLARATION_NAME, SCHEMA, declare_log
from vibecomfy.workflow import VibeNode, VibeWorkflow, WorkflowSource
from vibecomfy.workflow_bundle import load_bundle


def _read(run_dir: Path) -> dict:
    return json.loads((run_dir / DECLARATION_NAME).read_text(encoding="utf-8"))


def test_run_context_begin_declares_attempt(tmp_path: Path) -> None:
    context = RunContext("run-1", tmp_path / "run")
    context.begin("fixture")
    assert _read(context.run_dir) == {
        "schema": SCHEMA,
        "logs": [{"name": "run", "role": "run", "path": "attempt.json", "start": 0, "end": None}],
        "children": [],
    }


def test_declare_replaces_same_name_and_stores_external_path_absolute(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    external = tmp_path / "outside.log"
    declare_log(run_dir, "run", "run", run_dir / "attempt.json")
    declare_log(run_dir, "run", "run", external)
    payload = _read(run_dir)
    assert len(payload["logs"]) == 1
    assert payload["logs"][0]["path"] == str(external.resolve())


def test_declare_swallows_write_failure(tmp_path: Path) -> None:
    run_dir = tmp_path / "not-a-directory"
    run_dir.write_text("file", encoding="utf-8")
    declare_log(run_dir, "run", "run", run_dir / "attempt.json")


@pytest.mark.parametrize(
    ("server_url", "expected_engine"),
    [("http://runtime.test", False), (None, True)],
)
def test_run_declares_run_and_owned_engine_log(
    server_url: str | None, expected_engine: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    runtime_module = importlib.import_module("vibecomfy.runtime.run")

    @asynccontextmanager
    async def fake_server(*_args, **_kwargs):
        yield "http://runtime.test"

    async def stop_after_declaration(*_args, **_kwargs):
        raise RuntimeError("fixture stop")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runtime_module, "comfy_server", fake_server)
    monkeypatch.setattr(runtime_module, "_build_schema_provider", lambda _url: None)
    monkeypatch.setattr(runtime_module, "queue_server_prompt", stop_after_declaration)
    workflow = VibeWorkflow("runtime-test", WorkflowSource("runtime-test"))
    workflow.nodes["1"] = VibeNode(
        "1", "SaveImage", inputs={"filename_prefix": "test", "images": "fixture-image"},
        uid="runtime-1",
    )
    bundle = load_bundle(workflow)

    class FixtureProvider:
        def get_schema(self, class_type: str) -> NodeSchema:
            return NodeSchema(class_type, None, {}, [])

    entry = ModelEntry(
        "runtime-fixture-model", ModelSource("local"), 0,
        (ModelTarget("comfy_core", "checkpoints"),),
    )
    with (
        patch("vibecomfy.registry.models_loader.load_registry", return_value=(entry,)),
        patch("vibecomfy.registry.models_loader.resolve_model_entry", return_value=entry),
        patch("vibecomfy.fetch.is_present", return_value=True),
    ):
        record = bundle.compile(schema_provider=FixtureProvider())
    with pytest.raises(RuntimeError, match="fixture stop"):
        asyncio.run(runtime_module.run(record, bundle, server_url=server_url))

    declarations = list(tmp_path.glob("out/runs/*/logs.json"))
    assert len(declarations) == 1
    logs = _read(declarations[0].parent)["logs"]
    assert next(log for log in logs if log["name"] == "run")["path"] == "attempt.json"
    assert ("engine" in {log["name"] for log in logs}) is expected_engine
    if expected_engine:
        assert next(log for log in logs if log["name"] == "engine")["path"] == "comfy.log"


def test_declaration_format_has_only_contract_top_level_keys(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    declare_log(run_dir, "run", "run", run_dir / "attempt.json")
    payload = _read(run_dir)
    literal = json.loads(
        '{"schema": "run-logs.v1", "logs": '
        '[{"name": "run", "role": "run", "path": "attempt.json"}], "children": []}'
    )
    assert set(payload) == {"schema", "logs", "children"}
    assert {key: payload[key] for key in literal} | {
        "logs": [{key: payload["logs"][0][key] for key in literal["logs"][0]}]
    } == literal
