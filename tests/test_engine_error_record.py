import json

import pytest

from vibecomfy.errors import RuntimeNodeError
from vibecomfy.runtime import session


MESSAGE = "CUDA error: device-side assert triggered at /x/y.py"
TRACEBACK = ["line a\n", "line b\n"]


def _error(payload):
    status = {"messages": [["execution_error", payload]]}
    expected = session._comfy_execution_diagnostic(status)
    with pytest.raises(RuntimeNodeError) as caught:
        session._raise_terminal_execution_error(status, "prompt-1")
    actual = dict(caught.value.comfy_diagnostic)
    actual.pop("correlation")
    expected.pop("correlation")
    assert actual == expected
    return caught.value


def _persist(tmp_path, monkeypatch, error, *, use_exc=False):
    monkeypatch.setattr(session, "_terminal_event_already_written", lambda *args: False)
    monkeypatch.setattr(session, "_persist_runtime_evidence", lambda *args: None)
    monkeypatch.setattr(session, "_journal_terminal", lambda *args, **kwargs: None)
    session._persist_runtime_failure(
        run_dir=tmp_path, attempt_bundle={}, state={}, run_id="run-1", record=None,
        generation=1, evidence={"terminal": {}},
        **({"exc": error} if use_exc else {"original_error": error}),
    )


def test_full_engine_error_and_unchanged_diagnostic(tmp_path, monkeypatch):
    payload = {"node_id": "1", "node_type": "SomeCustomNode", "exception_type": "RuntimeError",
               "exception_message": MESSAGE, "traceback": TRACEBACK}
    error = _error(payload)
    assert error.engine_error == {"prompt_id": "prompt-1", "error": payload}
    _persist(tmp_path, monkeypatch, error)
    saved = json.loads((tmp_path / "engine-error.json").read_text())
    assert saved == {"schema": "engine-error.v1", "engine": "comfyui",
                     "prompt_id": "prompt-1", "error": payload}
    logs = json.loads((tmp_path / "logs.json").read_text())["logs"]
    assert any(log["name"] == "engine-error" and log["role"] == "engine" for log in logs)


def test_no_engine_error_writes_no_file(tmp_path, monkeypatch):
    _persist(tmp_path, monkeypatch, RuntimeError("failure"))
    assert not (tmp_path / "engine-error.json").exists()


def test_non_json_value_is_written(tmp_path, monkeypatch):
    error = _error({"exception_message": MESSAGE, "traceback": TRACEBACK, "extra": b"bytes"})
    _persist(tmp_path, monkeypatch, error, use_exc=True)
    saved = json.loads((tmp_path / "engine-error.json").read_text())
    assert saved["error"]["extra"] == "b'bytes'"


def test_payload_selection_and_fallback():
    status = {"error_details": {"source": "fallback"}, "messages": [
        ["execution_error", {"source": "older"}],
        ["execution_error", {"source": "latest"}],
    ]}
    assert session._engine_error_payload(status) == {"source": "latest"}
    assert session._engine_error_payload({"error_details": {"source": "fallback"}}) == {
        "source": "fallback"
    }
    assert session._engine_error_payload({}) is None


def test_record_write_failure_does_not_replace_failure(tmp_path, monkeypatch):
    error = _error({"exception_message": MESSAGE})
    def fail_write(*args, **kwargs):
        raise OSError("write failed")
    monkeypatch.setattr(session, "atomic_write_json", fail_write)
    _persist(tmp_path, monkeypatch, error)
