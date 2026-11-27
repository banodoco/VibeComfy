"""Bound desired-state and read-only refusal contract for P90 WS-2."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from vibecomfy.requirements import plan, plan_digest
from vibecomfy.node_approvals import approval_record


PAYLOAD = b"local model fixture\n"
SHA = hashlib.sha256(PAYLOAD).hexdigest()
REPO = "https://example.test/owner/NodePack.git"
COMMIT = "a" * 40


def _snapshot(root):
    return {str(path.relative_to(root)): ("directory" if path.is_dir() else path.read_bytes())
            for path in root.rglob("*")}


@pytest.fixture
def world(tmp_path):
    root = tmp_path / "engine"
    root.mkdir()
    source = tmp_path / "workflow.json"
    source.write_text(json.dumps({"1": {"class_type": "CheckpointLoaderSimple",
                                       "inputs": {"ckpt_name": "fixture.safetensors"}}}))
    target = {"root": str(root), "python": sys.executable, "placement_class": "local",
              "location": "local", "owner": "astrid", "layout": "managed",
              "comfyui_root": str(root / "runtime/ComfyUI"),
              "models_root": str(root / "shared-models"),
              "custom_nodes_root": str(root / "runtime/ComfyUI/custom_nodes")}
    model = {"name": "fixture.safetensors", "subdir": "checkpoints", "url": "https://example.test/model",
             "sha256": SHA, "size_bytes": len(PAYLOAD)}
    return source, target, model


def _model(result):
    rows = [row for row in result["requirements"] if row["kind"] == "model"]
    assert len(rows) == 1
    return rows[0]


def test_file_preview_binds_exact_bytes_and_does_not_create_target_paths(world, tmp_path):
    source, target, model = world
    before = _snapshot(tmp_path)
    result = plan(source, target=target, add_models=[model])
    assert _snapshot(tmp_path) == before
    assert result == plan(source, target=target, add_models=[model])
    assert plan_digest(result) == result["digest"]
    item = _model(result)
    assert item["destination"] == str(Path(target["models_root"]) / "checkpoints/fixture.safetensors")
    assert item["observed"]["state"] == "missing"
    assert item["action"]["kind"] == "download_model"
    assert result["bytes"] == {"download": len(PAYLOAD), "known_download": len(PAYLOAD), "unknown": [],
                               "additional_disk": None, "capacity": None}
    assert {gap["code"] for gap in result["gaps"]} == {"target_capacity_unknown", "required_disk_unknown"}
    source.write_text(source.read_text() + "\n")
    assert plan(source, target=target, add_models=[model])["digest"] != result["digest"]


def test_existing_local_model_is_observed_without_receipt_or_capacity_probe(world, tmp_path, monkeypatch):
    source, target, model = world
    destination = Path(target["models_root"]) / "checkpoints/fixture.safetensors"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(PAYLOAD)
    monkeypatch.setattr("vibecomfy.fetch.verify", lambda *a, **k: pytest.fail("verify writes receipts"))
    monkeypatch.setattr("shutil.disk_usage", lambda *a, **k: pytest.fail("no inherited capacity"))
    before = _snapshot(tmp_path)
    result = plan(source, target=target, add_models=[{**model, "url": None}])
    assert result["gaps"] == []
    assert result["actions"] == []
    assert _model(result)["observed"] == {"state": "present", "size_bytes": len(PAYLOAD), "sha256": SHA}
    assert result["bytes"]["download"] == result["bytes"]["additional_disk"] == 0
    assert _snapshot(tmp_path) == before
    destination.write_bytes(b"changed same target")
    changed = plan(source, target=target, add_models=[{**model, "url": None}])
    assert changed["digest"] != result["digest"]
    assert _model(changed)["observed"]["state"] == "conflict"
    assert _model(changed)["action"]["kind"] == "manual"


@pytest.mark.parametrize("field,value", [
    ("root", "different-engine"), ("python", "different-python"),
    ("comfyui_root", "different-comfy"), ("models_root", "different-models"),
    ("custom_nodes_root", "different-nodes"),
    ("capacity_bytes", 100), ("required_disk_bytes", 50),
    ("recipe", {"source": {"commit": "b" * 40}}),
    ("facts", {"selected_device": "cuda:1"}),
    ("owner", "human"), ("placement_class", "attached"),
])
def test_each_selected_target_binding_invalidates_digest(world, tmp_path, field, value):
    source, target, model = world
    first = plan(source, target=target, add_models=[model])
    if field.endswith("root") or field == "python":
        value = str(tmp_path / value)
    changed = plan(source, target={**target, field: value}, add_models=[model])
    assert changed["digest"] != first["digest"]


@pytest.mark.parametrize("field,value", [
    ("url", "https://example.test/new-source"), ("sha256", "b" * 64),
    ("size_bytes", 123), ("subdir", "other-models"), ("name", "renamed.safetensors"),
    ("revision", "c" * 40),
])
def test_each_model_binding_invalidates_digest(world, field, value):
    source, target, model = world
    first = plan(source, target=target, add_models=[model])
    second = plan(source, target=target, add_models=[{**model, field: value}])
    assert second["digest"] != first["digest"]


def test_dictionary_order_is_not_a_plan_change(world):
    source, target, model = world
    left = plan(source, target=target, add_models=[model])
    right = plan(source, target=dict(reversed(list(target.items()))),
                 add_models=[dict(reversed(list(model.items())))])
    assert left == right


def test_known_model_size_never_fills_unknown_capacity_or_total(world):
    source, target, model = world
    second = {**model, "name": "extra.safetensors", "size_bytes": None}
    result = plan(source, target=target, add_models=[model, second])
    assert result["bytes"]["known_download"] == len(PAYLOAD)
    assert result["bytes"]["download"] is None
    assert result["bytes"]["capacity"] is None
    assert result["bytes"]["additional_disk"] is None
    assert len(result["bytes"]["unknown"]) == 1


def test_explicit_disk_shortage_and_missing_selected_interpreter_are_blocked(world, tmp_path):
    source, target, model = world
    result = plan(source, target={**target, "capacity_bytes": 1, "required_disk_bytes": len(PAYLOAD),
                                  "python": str(tmp_path / "absent/python")}, add_models=[model])
    gaps = {gap["code"]: gap for gap in result["gaps"]}
    assert gaps["insufficient_capacity"]["state"] == "blocked"
    assert gaps["target_python_missing"]["state"] == "blocked"


def test_models_and_custom_node_model_paths_use_their_separate_explicit_roots(world, monkeypatch, tmp_path):
    source, target, model = world
    monkeypatch.setenv("COMFYUI_PATH", str(tmp_path / "wrong-host"))
    ordinary = plan(source, target={**target, "comfyui_root": None}, add_models=[model])
    assert _model(ordinary)["destination"].startswith(target["models_root"])
    custom = {**model, "subdir": None, "target_path": "custom_nodes/Example/weights/data.bin"}
    result = plan(source, target={**target, "models_root": None}, add_models=[custom])
    selected = next(row for row in result["requirements"] if row.get("model", {}).get("target_path"))
    assert selected["destination"] == str(Path(target["comfyui_root"]) / custom["target_path"])
    assert "wrong-host" not in json.dumps(result)


@pytest.mark.parametrize("overrides", [
    {"subdir": "../outside"}, {"name": "../../outside"},
    {"target_path": "models/checkpoints/bypass"}, {"target_path": None},
    {"target_path": "custom_nodes/Example/../../outside"},
])
def test_bad_model_destination_is_never_repaired_or_advertised_as_download(world, overrides):
    source, target, model = world
    result = plan(source, target=target, add_models=[{**model, **overrides}])
    invalid = [row for row in result["requirements"] if row.get("model", {}).items() >= overrides.items()]
    assert invalid
    assert all(row["destination"] is None and row["action"]["kind"] == "manual" for row in invalid)
    assert "model_destination_invalid" in {gap["code"] for gap in result["gaps"]}


def test_model_destination_collision_keeps_both_source_identities(world):
    source, target, model = world
    result = plan(source, target=target, add_models=[model, {**model, "url": "https://example.test/other"}])
    assert len(result["requirements"]) == 2
    assert "conflicting_destination" in {gap["code"] for gap in result["gaps"]}


def _source_evidence(repo=REPO, commit=COMMIT, **kwargs):
    text = "example==1\n"
    return {"repo": repo, "commit": commit, "tree": "b" * 40,
            "files": [{"path": "requirements.txt", "git_blob": "c" * 40,
                       "sha256": hashlib.sha256(text.encode()).hexdigest(), "content": text}],
            "recipe": {"requirements_txt": "requirements.txt", "pip_no_deps": []},
            "packages": ["example==1"], "class_names": ["FixtureNode"],
            "install_py": {"present": True, "git_blob": "d" * 40, "sha256": "e" * 64, "run": False},
            "checkout_bytes": 30, "submodules": [], "dynamic_dependencies": []}


@pytest.fixture
def node_world(tmp_path, world, monkeypatch):
    _, target, _ = world
    source = tmp_path / "node.json"
    source.write_text(json.dumps({"1": {"class_type": "FixtureNode", "inputs": {}}}))
    from vibecomfy.node_packs import _install
    monkeypatch.setattr(_install, "resolve_node_packs", lambda *a, **k: [])
    monkeypatch.setattr(_install, "get_known_node_packs", lambda *a, **k: [])
    ref = {"slug": "NodePack", "url": REPO, "commit": COMMIT, "source": "git",
           "requirements_txt": "requirements.txt", "pip_no_deps": ["alpha @ git+https://example.test/a.git@" + "f" * 40]}
    return source, target, ref


def test_exact_node_tree_recipe_and_existing_p56_approval_shape(node_world, tmp_path):
    source, target, ref = node_world
    before = _snapshot(tmp_path)
    result = plan(source, target=target, added_node_refs=[ref], source_inspector=_source_evidence)
    item = result["requirements"][0]
    assert item["kind"] == "node"
    assert item["node"] == {"repo": REPO, "commit": COMMIT, "requirements_txt": "requirements.txt", "pip_no_deps": ref["pip_no_deps"]}
    assert item["approval"]["record"] == approval_record(item["node"], placement_class="local")
    assert item["approval"]["state"] == "needs_approval"
    assert item["source_tree"]["install_py"]["run"] is False
    assert item["action"]["install_py"] == "never"
    assert item["packages"][0]["immutable"] is False
    assert item["packages"][1]["immutable"] is True
    assert "node_class_unresolved" not in {gap["code"] for gap in result["gaps"]}
    assert _snapshot(tmp_path) == before
    accepted = plan(source, target=target, added_node_refs=[ref], source_inspector=_source_evidence,
                    approvals=[item["approval"]["record"]])
    assert accepted["digest"] != result["digest"]
    assert accepted["requirements"][0]["approval"]["state"] == "record_matches"
    assert accepted["requirements"][0]["approval"]["runtime_grant"] == "not_observed"


@pytest.mark.parametrize("field", ["repo", "commit", "recipe", "packages", "tree", "file_bytes", "install_py", "observed"])
def test_node_binding_changes_invalidate_and_stale_consent_does_not_match(node_world, field):
    source, target, ref = node_world
    initial = plan(source, target=target, added_node_refs=[ref], source_inspector=_source_evidence)
    approval = initial["requirements"][0]["approval"]["record"]
    original = plan(source, target=target, added_node_refs=[ref], source_inspector=_source_evidence, approvals=[approval])
    evidence = _source_evidence()
    changed_ref = copy.deepcopy(ref)
    if field == "repo":
        changed_ref["url"] = evidence["repo"] = "https://other.test/owner/NodePack.git"
    elif field == "commit":
        changed_ref["commit"] = evidence["commit"] = "f" * 40
    elif field == "recipe":
        changed_ref["requirements_txt"] = None
    elif field == "packages":
        changed_ref["pip_no_deps"].append("second @ git+https://example.test/b.git@" + "e" * 40)
    elif field == "tree":
        evidence["tree"] = "f" * 40
    elif field == "file_bytes":
        evidence["files"][0]["content"] += "new-package\n"
        evidence["files"][0]["sha256"] = hashlib.sha256(evidence["files"][0]["content"].encode()).hexdigest()
    elif field == "install_py":
        evidence["install_py"]["sha256"] = "f" * 64
    else:
        destination = Path(target["custom_nodes_root"]) / "NodePack"
        destination.mkdir(parents=True)
        (destination / "human.txt").write_text("human checkout")
    changed = plan(source, target=target, added_node_refs=[changed_ref], source_inspector=lambda *a, **k: evidence, approvals=[approval])
    assert changed["digest"] != original["digest"]
    if field in {"repo", "commit", "recipe", "packages"}:
        assert changed["requirements"][0]["approval"]["state"] == "needs_approval"


def test_source_timeout_is_a_typed_gap_with_no_install(node_world):
    source, target, ref = node_world
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 1)
    result = plan(source, target=target, added_node_refs=[ref], source_inspector=timeout)
    assert any(gap["code"] == "source_tree_unavailable" and gap["state"] == "timeout" for gap in result["gaps"])
    assert result["requirements"][0]["source_tree"] is None


def test_changed_or_conflicting_source_pins_remain_blocked(node_world):
    source, target, ref = node_world
    result = plan(source, target=target, added_node_refs=[ref, {**ref, "commit": "e" * 40}], source_inspector=_source_evidence)
    assert any(gap["code"] == "conflicting_node_refs" and gap["state"] == "blocked" for gap in result["gaps"])


def test_unknown_root_does_not_use_host_defaults(world, monkeypatch, tmp_path):
    source, target, model = world
    monkeypatch.setenv("VIBECOMFY_MODELS_DIR", str(tmp_path / "host-models"))
    result = plan(source, target={**target, "models_root": None, "root": None, "python": None}, add_models=[model])
    assert _model(result)["destination"] is None
    assert {"model_destination_unknown", "target_root_unknown", "target_python_unknown"} <= {g["code"] for g in result["gaps"]}


def test_model_add_cli_form_is_bound_without_size_guess(world):
    source, target, _ = world
    arg = "checkpoints/fixture.safetensors=https://example.test/model#" + SHA
    result = plan(source, target=target, add_models=[arg])
    item = _model(result)
    assert item["source"] == {"url": "https://example.test/model", "sha256": SHA, "revision": None}
    assert item["size_bytes"] is None
    assert result["bytes"]["download"] is None
    assert result["inputs"]["add_models"] == [arg]


def test_unknown_model_name_never_invents_a_destination(tmp_path, world):
    _, target, _ = world
    source = tmp_path / "unknown-model.json"
    source.write_text(json.dumps({"1": {"class_type": "UnknownLoader", "inputs": {"model_name": "org/repo"}}}))
    result = plan(source, target=target)
    item = _model(result)
    assert item["model"]["subdir"] is None
    assert item["destination"] is None


def test_entry_plan_binds_manifest_and_actual_bundle_without_publishing(world, tmp_path, monkeypatch):
    source, target, model = world
    from vibecomfy.requirements._input import read_workflow
    built, _ = read_workflow(source)
    entry = tmp_path / "entry"
    bundle = entry / "revision/bundle"
    bundle.mkdir(parents=True)
    (bundle / "workflow.py").write_text("raise AssertionError('preview must use already admitted workflow')\n")
    manifest = {"id": "example", "kind": "image", "modes": ["t2i"], "bundle": "revision/bundle",
                "needs": [], "binds": {}, "defaults": {}}
    (entry / "entry.json").write_text(json.dumps(manifest))
    monkeypatch.setattr("vibecomfy.entries.import_as_entry", lambda *a, **k: pytest.fail("preview publication"))
    before = _snapshot(tmp_path)
    first = plan(entry, workflow=built, target=target, add_models=[model])
    assert first["workflow"]["kind"] == "entry"
    assert _snapshot(tmp_path) == before
    manifest["defaults"]["width"] = 256
    (entry / "entry.json").write_text(json.dumps(manifest))
    assert plan(entry, workflow=built, target=target, add_models=[model])["digest"] != first["digest"]


def test_python_and_entry_preview_never_executes_a_confirmed_workflow(world, tmp_path, monkeypatch):
    _, target, _ = world
    source = tmp_path / "workflow.py"
    marker = tmp_path / "SIDE_EFFECT"
    source.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('changed')\n")
    monkeypatch.setattr("vibecomfy.workflow_bundle.load_bundle", lambda *a, **k: pytest.fail("Python execution in preview"))
    before = _snapshot(tmp_path)
    result = plan(source, target=target)
    assert result["requirements"] == result["actions"] == []
    assert result["bytes"]["download"] is None
    assert any(gap["code"] == "workflow_code_not_admitted" and gap["state"] == "unapproved" for gap in result["gaps"])
    assert _snapshot(tmp_path) == before
    assert not marker.exists()


def test_shipped_restore_name_and_legacy_dependencies_are_bound(world, tmp_path, monkeypatch):
    source, target, _ = world
    source.write_text(json.dumps({"1": {"class_type": "FixtureNode", "inputs": {}}}))
    from vibecomfy.node_packs import CustomNodePack, LockEntry, _install
    from vibecomfy.node_packs._lockfile import DeclaredPatch
    locked = LockEntry(name="RegistryAlias", url=REPO, commit=COMMIT,
                       pip_packages=("legacy==1",), patches=(DeclaredPatch("patched.py", "d" * 64),))
    monkeypatch.setattr(_install, "resolve_node_packs", lambda *a, **k: [CustomNodePack("RegistryAlias", REPO, frozenset({"FixtureNode"}))])
    monkeypatch.setattr(_install, "get_known_node_packs", lambda *a, **k: [])
    monkeypatch.setattr(_install, "_batch_restore_entry", lambda *a, **k: locked)
    def evidence(*args, **kwargs):
        assert kwargs == {"requirements_txt": None}
        return {**_source_evidence(), "recipe": {"requirements_txt": None, "pip_no_deps": []}, "packages": []}
    result = plan(source, target=target, source_inspector=evidence)
    item = result["requirements"][0]
    assert item["destination"] == str(Path(target["custom_nodes_root"]) / "RegistryAlias")
    assert item["restore_entry"]["name"] == "RegistryAlias"
    assert item["restore_entry"]["patches"] == [{"path": "patched.py", "sha256": "d" * 64}]
    assert item["packages"][0]["requirement"] == "legacy==1"
    assert item["packages"][0]["origin"] == "reviewed_pip_packages"
    assert "package_resolution_unknown" in {g["code"] for g in result["gaps"]}


def test_node_final_symlink_remains_a_conflict(node_world):
    source, target, ref = node_world
    root = Path(target["custom_nodes_root"])
    actual = root / "real-directory"
    actual.mkdir(parents=True)
    (root / "NodePack").symlink_to(actual, target_is_directory=True)
    result = plan(source, target=target, added_node_refs=[ref], source_inspector=_source_evidence)
    item = result["requirements"][0]
    assert item["destination"] == str(root / "NodePack")
    assert item["observed"]["state"] == "conflict"
    assert item["action"]["kind"] == "manual"


def test_explicit_same_shipped_pin_keeps_installers_legacy_packages(node_world, monkeypatch):
    source, target, ref = node_world
    from vibecomfy.node_packs import LockEntry
    import vibecomfy.node_approvals as authority
    ref = {**ref, "requirements_txt": None, "pip_no_deps": []}
    shipped = LockEntry(name="NodePack", url=REPO, commit=COMMIT, pip_packages=("legacy==1",))
    monkeypatch.setattr(authority, "reviewed_lock_entry", lambda node: shipped)
    def evidence(*args, **kwargs):
        return {**_source_evidence(), "packages": [], "recipe": {"requirements_txt": None, "pip_no_deps": []}}
    result = plan(source, target=target, added_node_refs=[ref], source_inspector=evidence)
    item = result["requirements"][0]
    assert item["approval"]["state"] == "reviewed"
    assert item["packages"][0]["requirement"] == "legacy==1"
    assert item["reviewed_lock_entry"]["pip_packages"] == ["legacy==1"]
