"""One exact, data-only plan shared by preview and apply orchestration."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from vibecomfy.node_recipes import canonical_recipe, recipe_sha256

_SCHEMA = "vibecomfy.requirements-plan.v1"
_SHA = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def plan_digest(plan: Mapping[str, Any]) -> str:
    """Hash every inspectable bound field except the digest itself.

    This is a plan identity, not a capability or proof of current approval.
    Apply must recompute from current source/target/approval observations.
    """
    body = {key: value for key, value in plan.items() if key != "digest"}
    return hashlib.sha256((_SCHEMA + "\0" + _json(body)).encode("utf-8")).hexdigest()


def _gap(gaps, code, requirement=None, *, state="unknown", who="agent", detail=None):
    row = {"code": code, "state": state, "who": who, "requirement": requirement}
    if detail is not None:
        row["detail"] = detail
    if row not in gaps:
        gaps.append(row)


def _byte_count(value):
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("byte counts must be nonnegative integers or null")
    return value


def _error_state(exc):
    return "timeout" if isinstance(exc, subprocess.TimeoutExpired) or isinstance(exc.__cause__, subprocess.TimeoutExpired) else "unknown"


def plan(
    source,
    *,
    target,
    add: Sequence[str] = (),
    add_models: Sequence[str | Mapping[str, Any]] = (),
    added_node_refs: Sequence[Mapping[str, Any]] = (),
    approvals: Sequence[Mapping[str, Any]] = (),
    workflow=None,
    source_inspector: Callable[[str, str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Describe FILE/ENTRY requirements without target or entry mutation.

    ``target`` is the already-selected target. It carries ``root``, ``python``,
    ``comfyui_root``, ``models_root``, ``custom_nodes_root``, ``placement_class``
    and optional ``capacity_bytes``/immutable environment ``recipe``. Missing
    destinations/capacity remain unknown; host defaults are never substituted.

    ``approvals`` contains existing P56 records supplied by the Agent authority.
    Their reported match is not a current Runtime grant. This producer never
    creates/persists approvals, reads a new ledger, invokes pip or install.py,
    or publishes an entry. ``source_inspector`` is an exact-tree read seam for
    recorded fixtures/transport; production defaults to isolated Git reads.
    """
    from ._input import read_workflow, WorkflowNotAdmitted
    from ._observe import normalize_target
    from ._sources import inspect_source
    from vibecomfy.custom_node_refs import apply_added_node_refs, resolve_added_node_refs
    from vibecomfy.node_approvals import validate_approvals
    from vibecomfy.node_packs import CustomNodePack
    from vibecomfy.node_packs._install import missing_packs_for_workflow, _batch_restore_entry

    selected = normalize_target(target)
    gaps: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    read_source = source_inspector or inspect_source
    try:
        built, binding = read_workflow(source, workflow=workflow)
    except WorkflowNotAdmitted as exc:
        result = {"schema": _SCHEMA, "workflow": exc.binding, "target": selected,
                  "target_observed": _observe_target(selected, gaps),
                  "inputs": {"add": list(add), "added_node_refs": copy.deepcopy(list(added_node_refs)),
                             "add_models": copy.deepcopy(list(add_models)), "approvals": copy.deepcopy(list(approvals))},
                  "requirements": [], "gaps": [], "actions": [],
                  "bytes": {"download": None, "known_download": 0, "unknown": ["workflow"],
                            "additional_disk": None, "capacity": _byte_count(selected.get("capacity_bytes"))}}
        _gap(gaps, "workflow_code_not_admitted", state="unapproved", who="human")
        result["gaps"] = sorted(gaps, key=_json)
        result["digest"] = plan_digest(result)
        return result
    supplied_approvals = copy.deepcopy(list(approvals))
    try:
        records = validate_approvals(supplied_approvals)
    except (TypeError, ValueError):
        records = []
        _gap(gaps, "invalid_approval_records", state="unapproved", who="human")
    original_add = list(add)
    supplied_refs = copy.deepcopy(list(added_node_refs))
    additions = list(supplied_refs)
    for value in original_add:
        try:
            additions.extend(resolve_added_node_refs([value]))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            _gap(gaps, "source_ref_unresolved", value, state=_error_state(exc), detail={"source": value})
    # Conflicting declarations are reported by the existing canonical normalizer.
    # No normalizer/installer lock is written here.
    try:
        apply_added_node_refs(built, additions)
    except (TypeError, ValueError) as exc:
        _gap(gaps, "conflicting_node_refs", state="blocked", detail=str(exc))
        additions = []

    refs = copy.deepcopy(list(built.requirements.custom_node_refs))
    inspected: dict[tuple[str, str], dict[str, Any]] = {}
    resolved_packs = []
    for ref in refs:
        if not ref.get("url"):
            continue
        if not _COMMIT.fullmatch(str(ref.get("commit", ""))):
            try:
                selector = ref.get("version") or "HEAD"
                resolved = resolve_added_node_refs([ref["url"] + "@" + selector])[0]
                ref["commit"] = resolved["commit"]
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                _gap(gaps, "source_ref_unresolved", ref.get("slug"), state=_error_state(exc))
                continue
        key = (ref["url"], ref["commit"])
        try:
            evidence = _source_evidence(read_source, *key, ref=ref)
            inspected[key] = evidence
            resolved_packs.append(CustomNodePack(name=ref["slug"], repo=ref["url"],
                                                 classes=frozenset(evidence["class_names"])))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            _gap(gaps, "source_tree_unavailable", ref.get("slug"), state=_error_state(exc))

    packs, unresolved = missing_packs_for_workflow(
        built, resolved_packs=resolved_packs, include_schema_known=True,
    )
    for class_type in unresolved:
        _gap(gaps, "node_class_unresolved", class_type)
    # Explicit sources remain requirements even if class extraction is partial.
    by_name = {pack.name: pack for pack in packs}
    for ref in refs:
        if ref.get("url") and ref.get("slug"):
            by_name.setdefault(ref["slug"], CustomNodePack(ref["slug"], ref["url"], frozenset()))
    for name, pack in sorted(by_name.items()):
        selected_refs = [ref for ref in refs if ref.get("slug") == name or ref.get("name") == name]
        if len(selected_refs) > 1:
            _gap(gaps, "conflicting_node_refs", name, state="blocked")
            continue
        ref = selected_refs[0] if selected_refs else None
        restore_entry = None
        if ref is None:
            try:
                locked = _batch_restore_entry(pack, None, ())
                from dataclasses import asdict
                restore_entry = json.loads(_json(asdict(locked)))
                ref = {"slug": name, "url": locked.url, "commit": locked.commit,
                       "requirements_txt": locked.requirements_txt, "pip_no_deps": list(locked.pip_no_deps)}
            except ValueError:
                ref = {"slug": name, "url": pack.repo, "commit": None}
        repo, commit = ref.get("url"), ref.get("commit")
        key = (repo, commit)
        evidence = inspected.get(key)
        if evidence is None and repo and _COMMIT.fullmatch(str(commit or "")):
            try:
                evidence = inspected[key] = _source_evidence(read_source, repo, commit, ref=ref)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                _gap(gaps, "source_tree_unavailable", name, state=_error_state(exc))
        requirements.append(_node_requirement(name, ref, evidence, selected, records, gaps, restore_entry=restore_entry))

    requirements.extend(_model_requirements(built, add_models, selected, gaps))
    for field in ("root", "python"):
        if selected.get(field) is None:
            _gap(gaps, "target_" + field + "_unknown", who="human")
    if selected.get("placement_class") == "runpod" or selected.get("location") == "remote":
        _gap(gaps, "remote_apply_out_of_scope", state="blocked", who="human")
    target_observed = _observe_target(selected, gaps)
    requirements.sort(key=lambda item: item["id"])
    destinations: dict[str, str] = {}
    for item in requirements:
        destination = item.get("destination")
        if destination is not None and destination in destinations:
            _gap(gaps, "conflicting_destination", item["id"], state="blocked",
                 detail={"destination": destination, "other": destinations[destination]})
        elif destination is not None:
            destinations[destination] = item["id"]
    totals = _bytes(requirements, selected, gaps)
    actions = [item["action"] for item in requirements if item["action"]["kind"] != "none"]
    result = {
        "schema": _SCHEMA,
        "workflow": binding,
        "target": selected,
        "target_observed": target_observed,
        "inputs": {"add": original_add, "added_node_refs": supplied_refs,
                   "add_models": copy.deepcopy(list(add_models)), "approvals": supplied_approvals},
        "requirements": requirements,
        "gaps": sorted(gaps, key=_json),
        "bytes": totals,
        "actions": actions,
    }
    result["digest"] = plan_digest(result)
    return result


def _source_evidence(reader, repo, commit, *, ref):
    options = {"requirements_txt": ref["requirements_txt"]} if "requirements_txt" in ref else {}
    evidence = copy.deepcopy(dict(reader(repo, commit, **options)))
    if evidence.get("repo") != repo or evidence.get("commit") != commit:
        raise ValueError("source inspection returned a different repository or commit")
    if not _COMMIT.fullmatch(str(evidence.get("tree", ""))):
        raise ValueError("source inspection needs a complete Git tree identity")
    if not isinstance(evidence.get("class_names"), list):
        raise ValueError("source inspection needs explicit class evidence")
    _json(evidence)
    return evidence


def _node_requirement(name, ref, evidence, target, approvals, gaps, *, restore_entry=None):
    from ._observe import observe_node
    from vibecomfy.node_approvals import approval_record, approval_matches, consent_token, reviewed_lock_entry
    identity = "node:" + name
    recipe = canonical_recipe({key: ref[key] for key in ("requirements_txt", "pip_no_deps") if key in ref})
    if evidence is not None and not any(key in ref for key in ("requirements_txt", "pip_no_deps")):
        recipe = canonical_recipe(evidence["recipe"])
    node = {"repo": ref.get("url"), "commit": ref.get("commit"), **recipe}
    # The P56 value is a public consent code, not a credential. Keep its
    # canonical computation while using a field safe for Agent redaction.
    approval = {"state": "unknown", "record": None, "consent_code": None, "runtime_grant": "not_observed"}
    reviewed = None
    try:
        record = approval_record(node, placement_class=target["placement_class"])
        reviewed = reviewed_lock_entry(node)
        approval.update(record=record, consent_code=consent_token(record))
        approval["state"] = ("record_matches" if any(approval_matches(row, node, placement_class=target["placement_class"]) for row in approvals)
                             else "reviewed" if reviewed is not None else "needs_approval")
        if approval["state"] == "needs_approval":
            _gap(gaps, "node_code_unapproved", identity, state="unapproved", who="human",
                 detail={"consent": "code=" + approval["consent_code"]})
    except ValueError:
        _gap(gaps, "node_identity_unresolved", identity)
    packages = []
    for value in (evidence or {}).get("packages", ()):
        packages.append(_package(value, "requirements"))
    for value in recipe["pip_no_deps"]:
        packages.append(_package(value, "pip_no_deps"))
    # restore_pack's existing _reviewed_dependencies fills these even for an
    # explicit same-pin ref. Bind the effective shipped dependency witness.
    legacy = list((restore_entry or {}).get("pip_packages", ()))
    if not legacy and reviewed is not None:
        legacy = list(reviewed.pip_packages)
    for value in legacy:
        packages.append(_package(value, "reviewed_pip_packages"))
    if any(not package["immutable"] for package in packages):
        _gap(gaps, "package_resolution_unknown", identity)
    if evidence is None or evidence.get("dynamic_dependencies") or evidence.get("submodules"):
        _gap(gaps, "dependency_tree_incomplete", identity)
    if evidence is not None and recipe["requirements_txt"] is not None:
        if recipe["requirements_txt"] not in {item["path"] for item in evidence["files"]}:
            _gap(gaps, "recipe_file_unobserved", identity, state="blocked")
    destination = None
    root = target.get("custom_nodes_root")
    if root is not None:
        # Use the exact LockEntry.name consumed by restore_pack. Registry
        # aliases need not equal the repository basename. Preserve a final
        # symlink so observation refuses it just as the installer does.
        directory = (restore_entry or {}).get("name", name)
        try:
            if (not directory or directory in {".", ".."} or Path(directory).name != directory
                    or any(char.isspace() or char in "/\\:" for char in directory)):
                raise ValueError("invalid node restore directory")
            destination = str(Path(root) / directory)
            if _local(target) and not Path(destination).resolve().is_relative_to(Path(root)):
                raise ValueError("node destination escapes selected root")
        except (TypeError, ValueError, OSError):
            _gap(gaps, "node_destination_invalid", identity, state="blocked", who="human")
            destination = None
    if destination is None:
        _gap(gaps, "node_destination_unknown", identity, who="human")
    observed = observe_node(destination, repo=node["repo"], commit=node["commit"], local=_local(target))
    state = observed["state"]
    action = "none" if state == "present" and not packages else "restore_node" if state in {"missing", "present"} else "manual"
    if state not in {"missing", "present"}:
        _gap(gaps, "node_target_" + state, identity, state="blocked" if state in {"conflict", "incomplete"} else "timeout" if state == "timeout" else "unknown", who="human")
    if packages:
        # Installed code is not evidence of dependency readiness. The selected
        # interpreter's resolved package inventory belongs to the consumer.
        _gap(gaps, "package_observation_unknown", identity)
        if target.get("owner") != "astrid" and state != "missing":
            action = "manual"
            _gap(gaps, "human_environment_change", identity, state="blocked", who="human")
    result = {"id": identity, "kind": "node", "node": node, "source": {"repo": node["repo"], "commit": node["commit"]},
            "restore_entry": restore_entry,
            "source_tree": evidence, "recipe": recipe, "recipe_sha256": recipe_sha256(recipe),
            "packages": packages, "size_bytes": None, "checkout_bytes": (evidence or {}).get("checkout_bytes"),
            "destination": destination, "observed": observed, "approval": approval,
            "action": {"kind": action, "requirement": identity, "destination": destination,
                       "python": target.get("python"), "who": "human" if action == "manual" else "agent",
                       "install_py": "never"}}
    if reviewed is not None:
        from dataclasses import asdict
        result["reviewed_lock_entry"] = json.loads(_json(asdict(reviewed)))
    return result


def _package(value, origin):
    # A declaration stays a declaration. A floating version/range or index
    # version alone does not identify immutable downloadable package bytes.
    git_pin = re.search(r"git\+https://[^\s@]+(?:@[^\s@]+)*@([0-9a-f]{40})(?:[#;\s]|$)", value)
    artifact_hash = re.search(r"(?:#sha256=|--hash=sha256:)([0-9a-f]{64})(?:\s|$)", value)
    return {"requirement": value, "origin": origin, "immutable": bool(git_pin or artifact_hash),
            "commit": git_pin.group(1) if git_pin else None,
            "sha256": artifact_hash.group(1) if artifact_hash else None,
            "size_bytes": None, "observed": "unknown"}


def _local(target):
    return target.get("location", "local") == "local" and target.get("placement_class") != "runpod"


def _observe_target(target, gaps):
    from ._observe import observe_model
    observed = {}
    for field in ("root", "python"):
        value = target.get(field)
        row = {"state": "unknown"}
        if _local(target) and value is not None:
            try:
                path = Path(value)
                info = path.stat()
                if field == "root":
                    row["state"] = "present" if stat.S_ISDIR(info.st_mode) else "conflict"
                elif not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
                    row["state"] = "conflict"
                else:
                    # Retain the venv path in target.python while binding the
                    # executable bytes behind its final symlink independently.
                    real = str(path.resolve(strict=True))
                    row = {**observe_model(real, expected_sha256=None, size_bytes=None),
                           "executable": real}
            except FileNotFoundError:
                row["state"] = "missing"
            except (OSError, RuntimeError):
                row["state"] = "unknown"
        observed[field] = row
        if row["state"] != "present" and value is not None:
            _gap(gaps, "target_" + field + "_" + row["state"],
                 state="blocked" if row["state"] in {"missing", "conflict"} else row["state"], who="human")
    return observed


def _parse_model(value):
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    if not isinstance(value, str) or "=" not in value:
        raise ValueError("--add-model requires DEST=URL#sha256")
    destination, url = value.split("=", 1)
    from vibecomfy.fetch import _relative_asset_path
    path = _relative_asset_path(destination, field="destination")
    if len(path.parts) < 2:
        raise ValueError("model destination must include an explicit model subdirectory")
    parsed = urlsplit(url)
    digest = parsed.fragment.removeprefix("sha256=")
    if not _SHA.fullmatch(digest):
        raise ValueError("--add-model requires a full SHA-256 fragment")
    return {"name": path.name, "subdir": path.parent.as_posix(),
            "url": urlunsplit(parsed._replace(fragment="")), "sha256": digest, "size_bytes": None}


def _model_requirements(workflow, additions, target, gaps):
    from ._observe import observe_model
    from vibecomfy.fetch import AssetRoots, _authorized_destination, _relative_asset_path
    from vibecomfy.model_assets import canonical_model_requirement, referenced_model_requirements, _referenced_model_values
    authored = [*workflow.requirements.models, *workflow.metadata.get("model_assets", ())]
    authored.extend(_parse_model(value) for value in additions)
    roots = None
    if _local(target) and target.get("models_root") is not None and target.get("comfyui_root") is not None:
        roots = AssetRoots(models=Path(target["models_root"]), comfyui=Path(target["comfyui_root"]))
    # Inference is offline. Clear declarations only on our private copy, then
    # reconcile them below without discarding competing source identities.
    inferred_workflow = copy.deepcopy(workflow)
    inferred_workflow.metadata["model_assets"] = []
    inferred = referenced_model_requirements(inferred_workflow, registry=(), models_root=roots)
    # The loader's legacy bare labels are evidence of a picker, not a second
    # asset with an invented unknown destination. Resolve only a unique exact
    # name against structured declarations or the canonical picker inference.
    structured = [row for row in authored if isinstance(row, Mapping)]
    expanded = []
    for row in authored:
        if isinstance(row, Mapping):
            expanded.append(row)
            continue
        candidates = [item for item in structured if item.get("name") == row]
        if not candidates:
            candidates = [item for item in inferred if item.get("name") == row]
        keys = {(item.get("name"), item.get("subdir")) for item in candidates}
        if len(keys) != 1:
            expanded.append(row)
        elif not any(item.get("name") == row for item in structured):
            expanded.append(candidates[0])
    authored = expanded
    declared_keys = {(str(row.get("subdir")), str(row.get("name"))) for row in authored if isinstance(row, Mapping)}
    models = list(authored)
    models.extend(row for row in inferred if (str(row.get("subdir")), str(row.get("name"))) not in declared_keys)
    for reference in _referenced_model_values(workflow, include_unresolved=True):
        if reference.get("unresolved"):
            models.append({"name": reference["value"], "subdir": None, "url": None, "reference": reference})
    result = []
    seen = set()
    for raw in models:
        model = canonical_model_requirement(raw) if isinstance(raw, Mapping) else {"name": str(raw), "subdir": None, "url": None, "size_bytes": None, "sha256": None}
        fingerprint = _json(model)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        identity = "model:" + hashlib.sha256(fingerprint.encode()).hexdigest()[:20]
        size = _byte_count(model.get("size_bytes"))
        digest = model.get("sha256")
        if digest is not None and (not isinstance(digest, str) or not _SHA.fullmatch(digest)):
            raise ValueError("model sha256 must be a full lowercase SHA-256 or null")
        url = model.get("url")
        if url is not None:
            parsed = urlsplit(url)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError("model URL must be credential-free HTTP(S) without a fragment")
        destination = None
        if _local(target):
            try:
                if "target_path" in model:
                    relative = _relative_asset_path(model["target_path"], field="target_path")
                    if len(relative.parts) < 3 or relative.parts[0] != "custom_nodes":
                        raise ValueError("target_path requires custom_nodes/<pack>/...")
                    if target.get("comfyui_root") is not None:
                        destination = str(_authorized_destination(Path(target["comfyui_root"]), relative, field="target_path")[1])
                elif model.get("subdir") is not None and target.get("models_root") is not None:
                    relative = (_relative_asset_path(model["subdir"], field="subdir") /
                                _relative_asset_path(model["name"], field="name"))
                    destination = str(_authorized_destination(Path(target["models_root"]), relative, field="subdir/name")[1])
            except (KeyError, ValueError, OSError) as exc:
                _gap(gaps, "model_destination_invalid", identity, state="blocked", who="human", detail=str(exc))
        if destination is None:
            _gap(gaps, "model_destination_unknown", identity, who="human")
        observed = observe_model(destination, expected_sha256=digest, size_bytes=size, local=_local(target))
        state = observed["state"]
        action = "none" if state == "present" else "download_model" if state == "missing" and url and digest else "manual"
        if state == "conflict":
            _gap(gaps, "model_destination_conflict", identity, state="blocked", who="human")
        elif state not in {"present", "missing"}:
            _gap(gaps, "model_observation_" + state, identity, state="timeout" if state == "timeout" else "unknown")
        if state != "present":
            if not url:
                _gap(gaps, "model_source_unknown", identity, who="human")
            if digest is None:
                _gap(gaps, "model_hash_unknown", identity)
            if size is None:
                _gap(gaps, "model_size_unknown", identity)
        result.append({"id": identity, "kind": "model", "model": model,
                       "source": {"url": url, "sha256": digest, "revision": model.get("revision")},
                       "size_bytes": size, "destination": destination, "observed": observed,
                       "approval": {"state": "not_required", "runtime_grant": "not_observed"},
                       "action": {"kind": action, "requirement": identity, "destination": destination,
                                  "who": "human" if action == "manual" else "agent"}})
    return result


def _bytes(requirements, target, gaps):
    known = 0
    unknown = []
    for item in requirements:
        if item["action"]["kind"] == "none":
            continue
        size = item["size_bytes"]
        if size is None:
            unknown.append(item["id"])
        else:
            known += size
    capacity = _byte_count(target.get("capacity_bytes"))
    transfer = None if unknown else known
    needs_write = any(item["action"]["kind"] != "none" for item in requirements)
    # Transfer bytes alone are not peak disk space for staging, package wheels,
    # checkout expansion or backups. Only the transfer owner can supply a
    # measured additional-disk requirement; missing capacity is never zero.
    disk = _byte_count(target.get("required_disk_bytes")) if needs_write else 0
    if needs_write and capacity is None:
        _gap(gaps, "target_capacity_unknown")
    if needs_write and disk is None:
        _gap(gaps, "required_disk_unknown")
    if disk is not None and capacity is not None and disk > capacity:
        _gap(gaps, "insufficient_capacity", state="blocked", who="human")
    if disk is not None and disk < known:
        _gap(gaps, "disk_budget_incomplete", state="blocked")
    return {"download": transfer, "known_download": known, "unknown": unknown,
            "additional_disk": disk, "capacity": capacity}
