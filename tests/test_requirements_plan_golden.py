"""Canonical P90 CPU cases: exact SAM evidence and an observed local model.

These cases call the public producer and existing ref normalizer. Recorded
transport returns actual pinned source evidence; no installer or model runs.
"""
from __future__ import annotations

import copy
import hashlib
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from vibecomfy.requirements import plan


FIXTURES = Path(__file__).parent / "fixtures" / "requirements"
SAM_REPO = "https://github.com/ethanfel/ComfyUI-SAM-Audio.git"
SAM_COMMIT = "3cfbd03da3019c7252ba13efd5694b1b2ff487e5"
SAM_WORKFLOW_SHA256 = "c230cd0f9c799d4c82f9a397d606da3c6e5b4b8f20554de87fe4cddcbf59199a"
INSTALL_SHA256 = "0d6bde99599072f88704abb123f67bccd12017786843bea24da2496c5241b2d9"
REQUIREMENTS_SHA256 = "9fbdb9b9fc38b81c181b12d0dd098fdc385d03b1fc3a229b4539ffdf8942bd83"
LOCAL_MODEL_SHA256 = "5da61e801c90cac519be51b5f581475ea8f5d387ebe719936ca2bd882be87daa"
DECLARED_PACKAGES = {
    "einops", "ftfy", "huggingface-hub", "regex", "safetensors", "timm",
    "torchdiffeq", "tqdm", "transformers>=4.54.0",
}
NO_DEPS_COMMITS = [
    "414c20785fc3a28373073ea8ef7a1316eeeaca6e",
    "e72b6810b1133e1c879f2cc965d276eb73803f1f",
    "bb4c6999d2677c7402360e426afc01ddfad6dce0",
]


def _json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _digest(value):
    body = {key: item for key, item in value.items() if key != "digest"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(b"vibecomfy.requirements-plan.v1\0" + encoded).hexdigest()


def _normalized_output(value, target):
    """Name the real target/interpreter binding after verifying its bytes."""
    executable = Path(target["python"]).resolve()
    payload = executable.read_bytes()
    assert value["target"]["python"] == target["python"]
    assert value["target_observed"]["python"] == {
        "state": "present", "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(), "executable": str(executable),
    }

    def normalize(item):
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        if isinstance(item, list):
            return [normalize(child) for child in item]
        if isinstance(item, str):
            if item == target["python"]:
                return "${PYTHON}"
            if item == target["root"] or item.startswith(target["root"] + "/"):
                return "${TARGET}" + item[len(target["root"]):]
        return item

    result = normalize(copy.deepcopy(value))
    result["target_observed"]["python"].update(
        size_bytes="${PYTHON_SIZE}", sha256="${PYTHON_SHA256}", executable="${PYTHON_EXECUTABLE}",
    )
    result["digest"] = _digest(result)
    return result


def _snapshot(root):
    """Reads may update access times; publication/content/mtime changes may not."""
    paths = [root, *sorted(root.rglob("*"))]
    return {
        path.relative_to(root).as_posix(): (
            stat.S_IFMT(path.lstat().st_mode), path.lstat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
        )
        for path in paths
    }


def _target(tmp_path):
    root = tmp_path / "selected-target"
    root.mkdir()
    return {
        "root": str(root), "python": str(Path(sys.executable).parent.resolve() / Path(sys.executable).name),
        "comfyui_root": str(root / "ComfyUI"),
        "models_root": str(root / "ComfyUI" / "models"),
        "custom_nodes_root": str(root / "ComfyUI" / "custom_nodes"),
        "placement_class": "local", "location": "local", "owner": "astrid",
        "capacity_bytes": None,
    }


@pytest.fixture
def offline(monkeypatch):
    import httpx
    from vibecomfy.node_packs import _install

    def no_network(*args, **kwargs):
        pytest.fail("requirements golden preview must not access HTTP")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    # The accepted base knows SAM's name in its static catalog, but the golden
    # case explicitly proves an unlisted source. Keep every list empty.
    monkeypatch.setattr(_install, "get_known_node_packs", lambda **kwargs: [])
    monkeypatch.setattr(_install, "resolve_node_packs", lambda *args, **kwargs: [])


def _sam_inspector(repo, commit, **kwargs):
    assert (repo, commit) == (SAM_REPO, SAM_COMMIT)
    assert kwargs == {"requirements_txt": "requirements.txt"}
    return _json("sam.source-inspection.json")


def _recorded_resolver(monkeypatch):
    from vibecomfy import custom_node_refs

    calls = []

    def run(argv, **kwargs):
        expected = [
            "git", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
            "ls-remote", "--exit-code", "--", SAM_REPO,
            "refs/heads/main", "refs/tags/main", "refs/tags/main^{}",
        ]
        assert argv == expected, "no clone, pip, install.py or target process is allowed"
        assert kwargs["check"] is True and kwargs["timeout"] == 30
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, (FIXTURES / "sam.ref.txt").read_text(), "")

    monkeypatch.setattr(custom_node_refs.subprocess, "run", run)
    return calls


def test_sam_source_fixture_matches_recorded_git_blobs_and_recipe():
    evidence = _sam_inspector(SAM_REPO, SAM_COMMIT, requirements_txt="requirements.txt")
    assert evidence["repo"] == SAM_REPO and evidence["commit"] == SAM_COMMIT
    source_files = {record["path"]: record for record in evidence["files"]}
    for record in source_files.values():
        raw = record["content"].encode("utf-8")
        assert hashlib.sha256(raw).hexdigest() == record["sha256"]
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == record["git_blob"]
    assert source_files["requirements.txt"]["git_blob"] == "5e0d28c0c870c7914c1c6891984e421eb2765ee8"
    assert source_files["requirements.txt"]["sha256"] == REQUIREMENTS_SHA256
    assert evidence["tree"] == "49d98d76d13a010914bbe1c127ae290753b0ecd3"
    assert evidence["checkout_bytes"] == 154189
    assert evidence["install_py"] == {
        "present": True, "git_blob": "311f36373bf12eab7fee7ec3441a6959cf8be697",
        "sha256": INSTALL_SHA256, "run": False,
    }
    assert set(evidence["packages"]) == DECLARED_PACKAGES
    assert len(evidence["packages"]) == 9
    assert set(evidence["pyproject_packages"]) == DECLARED_PACKAGES
    assert len(evidence["pyproject_packages"]) == 9
    assert evidence["recipe"] == {"requirements_txt": "requirements.txt", "pip_no_deps": []}
    declared = _json("sam.recipe.json")
    assert declared["commit"] == SAM_COMMIT
    assert [value.rsplit("@", 1)[1] for value in declared["pip_no_deps"]] == NO_DEPS_COMMITS
    assert {"SAMAudioPipelineLoader", "SAMAudioTextSeparator"} <= set(evidence["class_names"])


def test_unlisted_sam_file_plan_is_exact_unapproved_and_read_only(tmp_path, monkeypatch, offline):
    target = _target(tmp_path)
    source = tmp_path / "sam.api.json"
    source.write_bytes((FIXTURES / "sam.workflow.api.json").read_bytes())
    before = _snapshot(tmp_path)
    calls = _recorded_resolver(monkeypatch)
    kwargs = {
        "target": target, "add": [SAM_REPO + "@main"],
        "added_node_refs": [_json("sam.recipe.json")], "source_inspector": _sam_inspector,
    }
    result = plan(source, **kwargs)
    assert plan(source, **kwargs) == result
    assert len(calls) == 2
    assert _snapshot(tmp_path) == before
    assert result["digest"] == _digest(result)
    assert result["workflow"]["kind"] == "file"
    assert result["workflow"]["members"] == [
        {"name": "workflow.json", "sha256": SAM_WORKFLOW_SHA256, "size_bytes": 1392}
    ]
    nodes = [item for item in result["requirements"] if item["kind"] == "node"]
    assert len(nodes) == 1
    node = nodes[0]
    assert node["id"] == "node:ComfyUI-SAM-Audio"
    assert node["source"] == {"repo": SAM_REPO, "commit": SAM_COMMIT}
    assert node["recipe"] == {key: _json("sam.recipe.json")[key] for key in ("requirements_txt", "pip_no_deps")}
    assert node["source_tree"] == _sam_inspector(SAM_REPO, SAM_COMMIT, requirements_txt="requirements.txt")
    assert node["restore_entry"] is None
    assert node["observed"]["state"] == "missing"
    assert node["destination"] == str(Path(target["custom_nodes_root"]) / "ComfyUI-SAM-Audio")
    assert node["action"]["kind"] == "restore_node"
    assert node["action"]["install_py"] == "never"
    assert node["action"]["python"] == target["python"]
    assert node["approval"]["state"] == "needs_approval"
    assert node["approval"]["runtime_grant"] == "not_observed"
    assert node["approval"]["token"]
    assert node["approval"]["record"]["recipe_sha256"] == node["recipe_sha256"]
    assert node["recipe_sha256"] == "1d6c9c543fe0c5c9eda6154ab7c4ca324f4ead54be6868a87791e7d5b5d29894"
    assert node["approval"]["token"] == "07a48e72110d"
    assert node["approval"]["record"]["approval_sha256"] == "07a48e72110debd82a07edd2872de1c80ee2f20b3418e59413cf75efb8fe495d"
    packages = node["packages"]
    assert len(packages) == 12  # Nine selected file requirements plus three explicit no-deps packages.
    assert {item["requirement"] for item in packages if item["origin"] == "requirements"} == DECLARED_PACKAGES
    assert all(not item["immutable"] for item in packages if item["origin"] == "requirements")
    declared_packages = [item for item in packages if item["origin"] == "pip_no_deps"]
    assert [item["commit"] for item in declared_packages] == NO_DEPS_COMMITS
    assert all(item["immutable"] for item in declared_packages)
    assert all(item["size_bytes"] is None and item["observed"] == "unknown" for item in packages)
    gap_codes = {item["code"] for item in result["gaps"]}
    assert {"node_code_unapproved", "package_resolution_unknown", "package_observation_unknown",
            "target_capacity_unknown", "required_disk_unknown"} <= gap_codes
    assert not any(item["code"] == "node_class_unresolved" and
                   item["requirement"] in {"SAMAudioPipelineLoader", "SAMAudioTextSeparator"}
                   for item in result["gaps"])
    consent = next(item for item in result["gaps"] if item["code"] == "node_code_unapproved")
    assert consent["detail"] == {"consent": "code=" + node["approval"]["token"]}
    assert consent["state"] == "unapproved" and consent["who"] == "human"
    assert node["size_bytes"] is None
    assert result["bytes"]["download"] is None
    assert result["bytes"]["capacity"] is None
    assert result["bytes"]["additional_disk"] is None
    assert _normalized_output(result, target) == _json("sam.expected-plan.json")


def test_local_model_only_file_observes_bytes_and_preserves_source_target(tmp_path, offline):
    target = _target(tmp_path)
    model = _json("local.model.json")
    assert "target_path" not in model  # That field selects custom-node assets in VibeComfy.
    payload = (FIXTURES / "local-model-only-payload.bin").read_bytes()
    assert len(payload) == 36
    assert hashlib.sha256(payload).hexdigest() == LOCAL_MODEL_SHA256
    destination = Path(target["models_root"]) / "checkpoints" / "local-fixture.safetensors"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(payload)
    source = tmp_path / "local.api.json"
    source.write_bytes((FIXTURES / "local.workflow.api.json").read_bytes())
    before = _snapshot(tmp_path)
    result = plan(source, target=target, add_models=[model])
    assert plan(source, target=target, add_models=[model]) == result
    assert _snapshot(tmp_path) == before
    assert result["digest"] == _digest(result)
    assert not result["gaps"]
    assert not result["actions"]
    assert result["bytes"] == {
        "download": 0, "known_download": 0, "unknown": [], "additional_disk": 0, "capacity": None,
    }
    assert len(result["requirements"]) == 1
    requirement = result["requirements"][0]
    assert requirement["kind"] == "model"
    assert requirement["model"] == model
    assert requirement["source"] == {"url": model["url"], "sha256": LOCAL_MODEL_SHA256, "revision": None}
    assert requirement["destination"] == str(destination)
    assert requirement["observed"] == {"state": "present", "size_bytes": 36, "sha256": LOCAL_MODEL_SHA256}
    assert requirement["action"]["kind"] == "none"
    assert requirement["approval"] == {"state": "not_required", "runtime_grant": "not_observed"}
    assert _normalized_output(result, target) == _json("local.expected-plan.json")


def test_local_model_observed_change_invalidates_same_input_plan(tmp_path, offline):
    target = _target(tmp_path)
    model = _json("local.model.json")
    destination = Path(target["models_root"]) / "checkpoints" / "local-fixture.safetensors"
    destination.parent.mkdir(parents=True)
    destination.write_bytes((FIXTURES / "local-model-only-payload.bin").read_bytes())
    source = FIXTURES / "local.workflow.api.json"
    initial = plan(source, target=target, add_models=[model])
    changed_bytes = b"X" + destination.read_bytes()[1:]
    destination.write_bytes(changed_bytes)
    before = _snapshot(tmp_path)
    changed = plan(source, target=target, add_models=[model])
    assert _snapshot(tmp_path) == before
    assert changed["digest"] != initial["digest"]
    assert changed["requirements"][0]["observed"]["state"] == "conflict"
    assert changed["requirements"][0]["observed"]["reason"] == "hash_mismatch"
    assert any(row["code"] == "model_destination_conflict" for row in changed["gaps"])
