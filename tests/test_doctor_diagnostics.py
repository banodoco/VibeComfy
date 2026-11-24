from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import vibecomfy.commands.doctor as doctor_cmd
from vibecomfy.security.provenance import Provenance
import vibecomfy.node_packs as node_packs
from vibecomfy.node_packs import LockEntry
from vibecomfy.workflow import VibeEdge, VibeNode, VibeWorkflow, WorkflowSource


def _write_scratchpad(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _valid_scratchpad(path: Path) -> Path:
    return _write_scratchpad(
        path,
        """
from vibecomfy.workflow import VibeNode, VibeWorkflow, WorkflowSource


def build():
    workflow = VibeWorkflow(id="doctor-valid", source=WorkflowSource(id="doctor-valid"))
    workflow.nodes["1"] = VibeNode(id="1", class_type="SaveImage", inputs={"images": "image", "filename_prefix": "ok"}, uid="1")
    return workflow
""",
    )


def _video_audio_scratchpad(path: Path) -> Path:
    return _write_scratchpad(
        path,
        """
from vibecomfy.workflow import VibeEdge, VibeNode, VibeWorkflow, WorkflowSource


def build():
    workflow = VibeWorkflow(id="doctor-video", source=WorkflowSource(id="doctor-video"))
    workflow.nodes["1"] = VibeNode(id="1", class_type="LTXVAudioVAEDecode", uid="1", inputs={"audio_vae": "vae", "samples": "latent"}, native_output_names=["Audio"], native_output_types=["AUDIO"], metadata={"object_info_identity": {"pack_slug": "comfy_core", "evidence_identity": "object_info_comfyui_0.24.0.1"}})
    workflow.nodes["2"] = VibeNode(id="2", class_type="CreateVideo", uid="2", inputs={"images": "image", "fps": 30.0}, native_input_names=["images", "fps", "audio"], native_input_types=["IMAGE", "FLOAT", "AUDIO"])
    workflow.edges.append(VibeEdge("1", "0", "2", "audio"))
    return workflow
""",
    )


def _missing_model_scratchpad(path: Path) -> Path:
    return _write_scratchpad(
        path,
        """
from vibecomfy.registry.ready_template import build_api_ready_workflow

API_WORKFLOW = {
    "1": {"class_type": "SaveImage", "inputs": {}},
}
READY_METADATA = {"ready_template": "test/model-missing"}
READY_REQUIREMENTS = {
    "models": [{
        "name": "missing.safetensors",
        "url": "https://example.test/models/missing.safetensors",
        "subdir": "checkpoints",
    }],
    "custom_nodes": [],
}

def build():
    return build_api_ready_workflow(
        API_WORKFLOW,
        READY_METADATA,
        source_path=__file__,
        workflow_id="test/model-missing",
        requirements=READY_REQUIREMENTS,
    )
""",
    )


def _run_doctor(path: Path, *, json_output: bool = False, allow_drift: bool = False) -> int:
    return doctor_cmd._cmd_doctor(
        argparse.Namespace(path=str(path), json=json_output, allow_drift=allow_drift, lint=False)
    )


@pytest.fixture
def doctor_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(doctor_cmd, "get_schema_provider", lambda _mode: None)
    monkeypatch.setattr(node_packs, "read_lockfile", lambda *args, **kwargs: [])
    real_load_bundle = doctor_cmd.load_bundle
    monkeypatch.setattr(
        doctor_cmd,
        "load_bundle",
        lambda path: real_load_bundle(path, trust=Provenance.USER_CONFIRMED),
    )
    monkeypatch.setattr(doctor_cmd, "_read_doctor_lockfile", lambda: [])
    monkeypatch.delenv("VIBECOMFY_COMFY_CONFIGURATION", raising=False)
    return tmp_path


def test_nodepack_lockfile_drift_is_structured_internally(monkeypatch) -> None:
    monkeypatch.setattr(
        doctor_cmd,
        "_read_doctor_lockfile",
        lambda: [LockEntry(name="DriftPack", git_commit_sha="expected", url="https://example.test/drift.git")],
    )
    monkeypatch.setattr(doctor_cmd, "_doctor_nodepack_dir", lambda _name: SimpleNamespace(is_file=lambda: False))
    monkeypatch.setattr(doctor_cmd, "git_head", lambda *args, **kwargs: "actual")

    warnings, errors = doctor_cmd._nodepack_lockfile_drift()

    assert warnings == []
    assert errors[0].code == "nodepack_lockfile_git_head_mismatch"
    assert errors[0].severity == "error"
    assert errors[0].message == "DriftPack git HEAD actual does not match lockfile git_commit_sha expected"
    assert errors[0].detail == {"pack": "DriftPack", "actual": "actual", "expected": "expected"}


def test_workflow_validation_issues_are_structured_with_rendered_messages() -> None:
    workflow = VibeWorkflow("invalid", WorkflowSource("invalid"))
    report = workflow.validate(schema_provider=None)

    findings = doctor_cmd._validation_findings(report)

    assert findings[0].code == "empty_workflow"
    assert findings[0].severity == "error"
    assert findings[0].message.startswith("[empty_workflow]")


def test_doctor_warning_findings_keep_compatibility_wrapper() -> None:
    workflow = VibeWorkflow("video", WorkflowSource("video"))
    workflow.nodes["1"] = VibeNode("1", "LTXVAudioVAEDecode", uid="1", inputs={"audio_vae": "vae", "samples": "latent"}, native_output_names=["Audio"], native_output_types=["AUDIO"], metadata={"object_info_identity": {"pack_slug": "comfy_core", "evidence_identity": "object_info_comfyui_0.24.0.1"}})
    workflow.nodes["2"] = VibeNode("2", "CreateVideo", uid="2", inputs={"images": "image", "fps": 30.0}, native_input_names=["images", "fps", "audio"], native_input_types=["IMAGE", "FLOAT", "AUDIO"])
    workflow.edges.append(VibeEdge("1", "0", "2", "audio"))

    findings = doctor_cmd._doctor_warning_findings(workflow)
    warnings = doctor_cmd._doctor_warnings(workflow)

    assert findings[0].code == "optional_video_audio"
    assert findings[0].severity == "warning"
    assert findings[0].node_id == "2"
    assert warnings == [findings[0].message]


def test_doctor_validation_error_preserves_json_keys_and_text_header(
    doctor_env: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scratchpad = _write_scratchpad(
        doctor_env / "invalid.py",
        """
from vibecomfy.workflow import VibeWorkflow, WorkflowSource


def build():
    return VibeWorkflow(id="invalid", source=WorkflowSource(id="invalid"))
""",
    )

    assert _run_doctor(scratchpad, json_output=True) == 1
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"status", "layer", "errors", "nodepack_warnings", "suggested_patches"}
    assert payload["status"] == "error"
    assert payload["layer"] == "VibeWorkflow validation"
    assert payload["errors"][0].startswith("[empty_workflow]")

    assert _run_doctor(scratchpad) == 1
    captured = capsys.readouterr()
    assert "Layer: VibeWorkflow validation" in captured.out
    assert "[empty_workflow]" in captured.out


def test_doctor_missing_model_preserves_json_keys_and_text_header(
    doctor_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scratchpad = _missing_model_scratchpad(doctor_env / "missing_model.py")
    monkeypatch.setenv("VIBECOMFY_MODELS_ROOT", str(doctor_env / "models"))

    assert _run_doctor(scratchpad, json_output=True) == 1
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"status", "missing_models", "nodepack_warnings", "suggested_patches"}
    assert payload["status"] == "error"
    assert "missing model missing.safetensors" in payload["missing_models"][0]

    assert _run_doctor(scratchpad) == 1
    captured = capsys.readouterr()
    assert "Missing models:" in captured.out
    assert "missing model missing.safetensors" in captured.out


def test_doctor_runtime_warnings_preserve_json_keys_and_text_header(
    doctor_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scratchpad = _valid_scratchpad(doctor_env / "valid.py")
    monkeypatch.setenv("VIBECOMFY_COMFY_CONFIGURATION", "{not-json")

    assert _run_doctor(scratchpad, json_output=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"status", "warnings", "nodepack_warnings", "suggested_patches"}
    assert payload["status"] == "warning"
    assert "VIBECOMFY_COMFY_CONFIGURATION is not valid JSON" in payload["warnings"][0]

    assert _run_doctor(scratchpad) == 0
    captured = capsys.readouterr()
    assert "Local checks passed with runtime warnings:" in captured.out


def test_doctor_optional_video_audio_warning_preserves_payload_shape(
    doctor_env: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scratchpad = _video_audio_scratchpad(doctor_env / "video.py")

    assert _run_doctor(scratchpad, json_output=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"status", "warnings", "nodepack_warnings", "suggested_patches"}
    assert payload["status"] == "warning"
    assert "CreateVideo node 2 has optional audio input connected" in payload["warnings"][0]

    assert _run_doctor(scratchpad) == 0
    captured = capsys.readouterr()
    assert "Local checks passed with runtime warnings:" in captured.out


def test_doctor_nodepack_drift_json_payload_keys(
    doctor_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scratchpad = _valid_scratchpad(doctor_env / "valid.py")
    (doctor_env / "vendor" / "DriftPack").mkdir(parents=True)
    monkeypatch.setattr(
        doctor_cmd,
        "_read_doctor_lockfile",
        lambda: [LockEntry(name="DriftPack", git_commit_sha="expected", url="https://example.test/drift.git")],
    )
    monkeypatch.setattr(doctor_cmd.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="actual\n"))

    assert _run_doctor(scratchpad, json_output=True) == 1
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"status", "layer", "errors", "suggested_patches"}
    assert payload["status"] == "error"
    assert payload["layer"] == "nodepack lockfile drift"
    assert "does not match lockfile git_commit_sha expected" in payload["errors"][0]

    assert _run_doctor(scratchpad, json_output=True, allow_drift=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"status", "nodepack_drift", "suggested_patches"}
    assert payload["status"] == "warning"
    assert "does not match lockfile git_commit_sha expected" in payload["nodepack_drift"][0]


def test_doctor_suggested_patches_preserve_json_shape(
    doctor_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scratchpad = _valid_scratchpad(doctor_env / "valid.py")

    class FakePatch:
        name = "fake_patch"

        @staticmethod
        def rationale(_workflow):
            return "fake rationale"

    monkeypatch.setattr(doctor_cmd, "find_applicable", lambda _workflow: [FakePatch()])

    assert _run_doctor(scratchpad, json_output=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["suggested_patches"] == [{"name": "fake_patch", "rationale": "fake rationale"}]


@pytest.mark.parametrize("matching,expected", [(True, 0), (False, 1)])
def test_doctor_explicit_managed_lock_is_used_for_both_gates(tmp_path, monkeypatch, capsys, matching, expected):
    from vibecomfy.node_packs import write_lockfile

    monkeypatch.chdir(tmp_path)
    approved = "a" * 40
    repo = "https://example.test/ApprovedPack.git"
    lock = tmp_path / "managed-custom-nodes.lock"
    write_lockfile([LockEntry(name="ApprovedPack", url=repo, git_commit_sha=approved)], lock)
    (tmp_path / "custom_nodes" / "ApprovedPack").mkdir(parents=True)
    workflow = VibeWorkflow(id="managed", source=WorkflowSource(id="managed"))
    workflow.nodes["1"] = VibeNode(id="1", class_type="SaveImage", uid="1", inputs={"images": "image", "filename_prefix": "ok"})
    # Use the actual pin checker with a ref absent from the packaged lock.
    from vibecomfy.workflow import WorkflowRequirements
    workflow.requirements = WorkflowRequirements(custom_node_refs=[{
        "name": "ApprovedPack", "slug": "ApprovedPack", "url": repo,
        "commit": approved, "source": "git",
    }])
    monkeypatch.setattr(doctor_cmd, "get_schema_provider", lambda _mode: None)
    monkeypatch.setattr(doctor_cmd, "load_bundle", lambda _path: SimpleNamespace(
        workflow=workflow, require_canonical_authority=lambda _what: None,
        compile=lambda **kwargs: object(),
    ))
    monkeypatch.setattr(doctor_cmd, "_patch_suggestions", lambda _wf: [])
    monkeypatch.setattr(doctor_cmd, "_missing_model_findings", lambda *_args: [])
    monkeypatch.setattr(doctor_cmd, "_doctor_warnings", lambda _wf: [])
    monkeypatch.setattr(doctor_cmd, "git_head", lambda *_args, **_kwargs: approved if matching else "b" * 40)
    real_read = doctor_cmd.read_lockfile
    reads = []

    def target_only(path=None):
        reads.append(path)
        assert path == lock, "must never read shipped lock for explicit managed target"
        return real_read(path)

    monkeypatch.setattr(doctor_cmd, "read_lockfile", target_only)
    assert doctor_cmd._cmd_doctor(argparse.Namespace(path="unused", lockfile=str(lock))) == expected
    assert reads == [lock]
    out = capsys.readouterr().out
    if not matching:
        assert "does not match lockfile" in out


def test_doctor_explicit_missing_lock_fails_closed(tmp_path):
    with pytest.raises(FileNotFoundError, match="Explicit doctor lockfile"):
        doctor_cmd._read_doctor_lockfile(tmp_path / "missing.lock")


def test_doctor_json_preserves_real_compile_unknown_input_findings(
    doctor_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from copy import deepcopy

    from vibecomfy.nodes.core import EmptyImage, SaveImage
    from vibecomfy.porting.object_info import get_class
    from vibecomfy.schema.provider import TargetSchemaProvider
    from vibecomfy.templates import OutputSpec, ReadyMetadata, new_workflow
    from vibecomfy.workflow_bundle import emit_bundle_with_candidate

    with new_workflow(ReadyMetadata.build(template_id="doctor-removed-input", capability="image")) as workflow:
        image = EmptyImage(width=16, height=16, batch_size=1, color=0)
        saved = SaveImage(images=image.out("IMAGE"), filename_prefix="doctor")
        workflow.finalize({}, outputs=[OutputSpec(node=saved)])
    path = emit_bundle_with_candidate(
        workflow, doctor_env / "workflow.py", Provenance.USER_CONFIRMED, None
    ).python_path
    api = workflow.compile("api")
    node_id = next(str(key) for key, node in api.items() if node["class_type"] == "EmptyImage")

    info = {}
    for cls in ("EmptyImage", "SaveImage"):
        definition = get_class(cls)
        assert definition is not None
        info[cls] = {
            "input": deepcopy(definition["inputs"]),
            "input_order": deepcopy(definition["input_order"]),
            "output": [out["type"] for out in definition["outputs"]],
            "output_name": [out["name"] for out in definition["outputs"]],
            "output_is_list": [out["is_list"] for out in definition["outputs"]],
            "output_node": cls == "SaveImage",
        }
    del info["EmptyImage"]["input"]["required"]["width"]
    if "width" in info["EmptyImage"]["input_order"].get("required", []):
        info["EmptyImage"]["input_order"]["required"].remove("width")
    target = TargetSchemaProvider.from_object_info(info, server_url="http://target.test:8188")
    monkeypatch.setattr(doctor_cmd, "get_schema_provider", lambda _mode: target)

    assert _run_doctor(path, json_output=True) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["layer"] == "VibeWorkflow validation"
    group = next(row for row in payload["validation_errors"]
                 if row["node_id"] == node_id and row["class_type"] == "EmptyImage")
    assert any(error["code"] == "unknown_input" and error["input"] == "width"
               for error in group["errors"])

    # The same failure still renders a useful human diagnostic.
    assert _run_doctor(path) == 1
    assert "Layer: VibeWorkflow validation" in capsys.readouterr().out
