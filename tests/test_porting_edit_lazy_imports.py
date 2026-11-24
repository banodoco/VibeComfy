"""Ordinary bundle approval must not initialize the agent provider or node library."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_bundle_approval_does_not_import_agent_provider() -> None:
    # Use a new interpreter: test collection imports ComfyUI agent modules.
    # Record attempts, not just sys.modules, so a swallowed import cannot pass.
    probe = r"""
import json
import sys

forbidden = ("vibecomfy.comfy_nodes", "numpy", "torch")
before = set(sys.modules)
attempts = []

def is_forbidden(name):
    return any(name == root or name.startswith(root + ".") for root in forbidden)

class ImportRecorder:
    def find_spec(self, fullname, path=None, target=None):
        if is_forbidden(fullname):
            attempts.append(fullname)
        return None

sys.meta_path.insert(0, ImportRecorder())
from vibecomfy.workflow import VibeWorkflow, WorkflowSource
from vibecomfy.workflow_bundle import load_bundle

workflow = VibeWorkflow("lazy-import-probe", WorkflowSource("lazy-import-probe"))
workflow.add_node("Integer", uid="integer-node", value=7)
bundle = load_bundle(workflow)
record = bundle.compile()
assert record.api_projection["1"]["inputs"]["value"] == 7
assert record.ui_projection["nodes"]
assert "vibecomfy.porting.emit.ui" in sys.modules
assert "vibecomfy.porting.edit.ops" in sys.modules
after = set(sys.modules)
report = {
    "forbidden_roots": forbidden,
    "before_count": len(before),
    "after_count": len(after),
    "loaded_before": sorted(name for name in before if is_forbidden(name)),
    "loaded_after": sorted(name for name in after if is_forbidden(name)),
    "attempted": sorted(set(attempts)),
}
print(json.dumps(report), flush=True)
assert not report["loaded_before"], report
assert not report["loaded_after"], report
assert not report["attempted"], report
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(result.stdout)
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_provider_exception_aliases_load_on_request() -> None:
    probe = """
import sys
from vibecomfy.porting.edit import ops

name = "vibecomfy.comfy_nodes.agent.provider"
assert name not in sys.modules
assert {"MalformedModelJSON", "MissingRequiredField"} <= set(dir(ops))
assert name not in sys.modules
from vibecomfy.porting.edit.ops import MalformedModelJSON, MissingRequiredField
assert name in sys.modules
from vibecomfy.comfy_nodes.agent import provider
assert MalformedModelJSON is provider.MalformedModelJSON is ops.MalformedModelJSON
assert MissingRequiredField is provider.MissingRequiredField is ops.MissingRequiredField
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)


@pytest.mark.parametrize(
    ("response", "error_name", "message", "has_json_cause"),
    [
        ("not JSON", "MalformedModelJSON",
         "Agent response was not valid JSON with keys `delta` and `message`.", True),
        ("{bad JSON", "MalformedModelJSON",
         "Agent response was not valid JSON with keys `delta` and `message`.", True),
        ("[]", "MalformedModelJSON", "Agent response must be a JSON object.", False),
        (None, "MalformedModelJSON", "Agent response must be a JSON string or object.", False),
        ({"content": "not JSON"}, "MalformedModelJSON",
         "Agent response was not valid JSON with keys `delta` and `message`.", True),
        ({"message": "missing delta"}, "MissingRequiredField",
         "Agent JSON must include key `delta`.", False),
        ({"delta": []}, "MissingRequiredField",
         "Agent JSON must include string key `message`.", False),
    ],
)
def test_model_response_preserves_exact_provider_errors(
    response, error_name, message, has_json_cause,
) -> None:
    from vibecomfy.comfy_nodes.agent import provider
    from vibecomfy.porting.edit.ops import normalize_delta_agent_response

    error_type = getattr(provider, error_name)
    with pytest.raises(error_type) as raised:
        normalize_delta_agent_response(response, route="arnold", model="agent-edit-v2")
    assert type(raised.value) is error_type
    assert str(raised.value) == message
    if has_json_cause:
        assert isinstance(raised.value.__cause__, json.JSONDecodeError)
    else:
        assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ({}, "Agent JSON must include string key `message`."),
        ({"message": "missing delta"}, "Agent JSON must include key `delta`."),
    ],
)
def test_test_client_preserves_exact_provider_errors(response, message) -> None:
    from vibecomfy.comfy_nodes.agent.provider import MissingRequiredField
    from vibecomfy.porting.edit.ops import normalize_delta_test_client_response

    with pytest.raises(MissingRequiredField) as raised:
        normalize_delta_test_client_response(response)
    assert type(raised.value) is MissingRequiredField
    assert str(raised.value) == message
