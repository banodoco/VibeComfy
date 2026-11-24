"""LE-2b: the real target admission refuses code before any git or pip call."""
from __future__ import annotations

import copy
import json
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.fixtures.node_recipe_runner import RecipeRunner
from tests.test_node_recipe_install import recipe_entry, target  # noqa: F401
from vibecomfy.commands import nodes
from vibecomfy.node_approvals import approval_record, consent_token
from vibecomfy.node_packs import CustomNodePack, PackRef, read_lockfile, write_lockfile
from vibecomfy.node_packs import _install as install


def record(entry, placement="runpod"):
    return approval_record({"repo": entry.url, "commit": entry.git_commit_sha,
                            "requirements_txt": entry.requirements_txt,
                            "pip_no_deps": list(entry.pip_no_deps)}, placement_class=placement)


@pytest.mark.parametrize("change", ["absent", "repo", "commit", "recipe", "order", "placement", "hash", "malformed"])
def test_apply_refuses_unapproved_code(target, change):
    entry = recipe_entry()
    approved = record(entry)
    records = [approved]
    if change == "absent":
        records = []
    elif change == "repo":
        entry = replace(entry, url="https://example.test/another-recipe.git")
    elif change == "commit":
        entry = replace(entry, commit="b" * 40, git_commit_sha="b" * 40)
    elif change == "recipe":
        entry = replace(entry, requirements_txt="other-requirements.txt")
    elif change == "order":
        entry = replace(entry, pip_no_deps=tuple(reversed(entry.pip_no_deps)))
    elif change == "placement":
        records = [record(entry, "local")]
    elif change == "hash":
        records = [{**approved, "approval_sha256": "0" * 64}]
    else:
        records = {"not": "records"}
    runner = RecipeRunner()
    result = install.restore_pack(entry, install_root=target[0], lockfile_path=target[1],
                                  runner=runner, approvals=records, placement_class="runpod")
    assert result.status == "failed"
    assert result.error.startswith("needs_consent:") and "approve the exact resolved commit" in result.error
    assert runner.calls == []
    assert not target[0].exists()
    assert not target[1].exists()


def test_approved_recipe_uses_controlled_installer(target):
    entry = recipe_entry()
    runner = RecipeRunner()
    result = install.restore_pack(entry, install_root=target[0], lockfile_path=target[1],
                                  runner=runner, approvals=[record(entry)], placement_class="runpod")
    assert result.status == "installed"
    assert runner.calls[:2] == [["git", "clone", entry.url, str(target[0] / entry.name)],
                               ["git", "-C", str(target[0] / entry.name), "checkout", entry.git_commit_sha]]
    assert len(runner.installs) == 4
    assert runner.installs[0][-2:] == ["-r", str((target[0] / entry.name / entry.requirements_txt).resolve())]
    assert [call[-2:] for call in runner.installs[1:]] == [["--no-deps", item] for item in entry.pip_no_deps]
    assert not (target[0] / entry.name / "SCRIPT_EXECUTED").exists()


def test_existing_checkout_cannot_substitute_the_approved_repository(target):
    entry = recipe_entry()
    checkout = target[0] / entry.name
    RecipeRunner().checkout_tree(checkout)
    calls = []

    def wrong_origin(args, **kwargs):
        calls.append(list(args))
        assert list(args) == ["git", "-C", str(checkout), "config", "--get", "remote.origin.url"]
        return subprocess.CompletedProcess(args, 0, stdout="https://example.test/other.git\n", stderr="")

    before = {path.relative_to(checkout): path.read_bytes() for path in checkout.rglob("*") if path.is_file()}
    result = install.restore_pack(entry, install_root=target[0], lockfile_path=target[1],
        runner=wrong_origin, approvals=[record(entry)], placement_class="runpod")
    assert result.status == "failed" and "repository differs" in result.error
    assert result.error.startswith("conflict:") and f"remove {checkout} or approve the new repository" in result.error
    assert len(calls) == 1
    assert not target[1].exists()
    assert before == {path.relative_to(checkout): path.read_bytes() for path in checkout.rglob("*") if path.is_file()}


def test_target_lock_extra_ref_refuses_entire_batch_before_restore(target, monkeypatch, capsys):
    entry = recipe_entry()
    extra = replace(entry, name="extra", url="https://example.test/extra.git")
    write_lockfile([entry, extra], target[1])
    approval_path = target[1].with_suffix(".approvals.json")
    approval_path.write_text(json.dumps([record(entry)]))
    calls = []
    monkeypatch.setattr(nodes.node_packs_install, "restore_pack", lambda *a, **kw: calls.append((a, kw)))
    before = target[1].read_bytes()
    result = nodes._cmd_nodes_restore(SimpleNamespace(lockfile=str(target[1]),
        approvals=str(approval_path), placement_class="runpod"))
    assert result == 1
    assert "needs_consent" in capsys.readouterr().err
    assert calls == []
    assert target[1].read_bytes() == before
    assert not target[0].exists()


def test_cli_restores_only_exact_record_and_keeps_target_lock_path(target, monkeypatch):
    entry = recipe_entry()
    write_lockfile([entry], target[1])
    approval_path = target[1].with_suffix(".approvals.json")
    approval_path.write_text(json.dumps([record(entry)]))
    runner = RecipeRunner()
    restore = install.restore_pack
    monkeypatch.setattr(nodes.node_packs_install, "restore_pack", lambda item, **kw: restore(
        item, install_root=target[0], runner=runner, **kw))
    assert nodes._cmd_nodes_restore(SimpleNamespace(lockfile=str(target[1]),
        approvals=str(approval_path), placement_class="runpod")) == 0
    assert len(runner.installs) == 4


def test_unapproved_batch_stops_before_pip_preflight(target):
    entry = recipe_entry()
    pack = CustomNodePack(entry.name, entry.url, frozenset(entry.class_set))
    runner = RecipeRunner()
    result = install.install_required_packs([pack], restore_entries=[entry],
        install_root=target[0], lockfile_path=target[1], runner=runner)
    assert not result.ok
    assert runner.calls == []


def test_shipped_ref_without_records_restores_but_changed_commit_is_refused(target):
    entry = next(row for row in read_lockfile() if row.name == "ComfyUI-VideoHelperSuite")
    runner = RecipeRunner()
    result = install.restore_pack(entry, install_root=target[0], lockfile_path=target[1],
                                  runner=runner, placement_class="runpod")
    assert result.status == "installed"
    assert ["git", "-C", str(target[0] / entry.name), "checkout", entry.git_commit_sha] in runner.calls
    before = target[1].read_bytes()
    changed = replace(entry, commit="b" * 40, git_commit_sha="b" * 40)
    forbidden = RecipeRunner()
    refused = install.restore_pack(changed, install_root=target[0], lockfile_path=target[1],
                                   runner=forbidden, placement_class="runpod")
    assert refused.status == "failed" and "needs_consent:" in refused.error
    assert forbidden.calls == [] and target[1].read_bytes() == before


def test_batch_without_target_lock_restores_only_shipped_full_pin(target):
    entry = next(row for row in read_lockfile() if row.name == "ComfyUI-VideoHelperSuite")
    # A workflow's same-name dependency list is not the reviewed authority.
    pack = CustomNodePack(entry.name, entry.url, frozenset(entry.class_set), ("unshown==99",))
    runner = RecipeRunner()
    result = install.install_required_packs([pack], install_root=target[0], lockfile_path=target[1], runner=runner)
    assert result.ok
    assert ["git", "clone", entry.url, str(target[0] / entry.name)] in runner.calls
    assert ["git", "-C", str(target[0] / entry.name), "checkout", entry.git_commit_sha] in runner.calls
    assert not any("unshown==99" in call for call in runner.calls)
    assert read_lockfile(target[1]) == [entry]


@pytest.mark.parametrize("selector", ["workflow-pack", "url-only", "tag", "unapproved-pin"])
def test_batch_without_lock_cannot_install_unreviewed_or_unpinned_ref(target, selector):
    shipped = next(row for row in read_lockfile() if row.name == "ComfyUI-VideoHelperSuite")
    unknown = recipe_entry(requirements_txt=None, pip_no_deps=())
    packs = [CustomNodePack(shipped.name, shipped.url, frozenset(shipped.class_set)),
             CustomNodePack(unknown.name, unknown.url, frozenset(unknown.class_set))]
    refs = {} if selector == "workflow-pack" else {unknown.name: PackRef(
        slug=unknown.name, source="git", url=unknown.url,
        version="main" if selector == "tag" else None,
        commit=unknown.commit if selector == "unapproved-pin" else None)}
    runner = RecipeRunner()
    result = install.install_required_packs(packs, install_refs_by_name=refs,
        install_root=target[0], lockfile_path=target[1], runner=runner)
    assert not result.ok
    assert all(row.status == "failed" and "needs_consent:" in row.error for row in result.results)
    assert runner.calls == []
    assert not target[0].exists() and not target[1].exists()


def test_batch_approved_full_pin_preserves_version_annotation_without_executing_tag(target):
    entry = recipe_entry(requirements_txt=None, pip_no_deps=())
    pack = CustomNodePack(entry.name, entry.url, frozenset(entry.class_set))
    runner = RecipeRunner()
    result = install.install_required_packs([pack], install_refs_by_name={entry.name: PackRef(
        slug=entry.name, source="aux-git", url=entry.url, version="v1.2.3", commit=entry.commit)},
        approvals=[record(entry)], placement_class="runpod", install_root=target[0],
        lockfile_path=target[1], runner=runner)
    assert result.ok
    assert ["git", "-C", str(target[0] / entry.name), "checkout", entry.commit] in runner.calls
    assert not any(call[-1] == "v1.2.3" for call in runner.calls)
    [saved] = read_lockfile(target[1])
    assert saved.commit == entry.commit and saved.version == "v1.2.3"


def test_force_does_not_authorize_dirty_code_at_a_reviewed_pin(target):
    entry = next(row for row in read_lockfile() if row.name == "ComfyUI-VideoHelperSuite")
    checkout = target[0] / entry.name
    checkout.mkdir(parents=True)
    write_lockfile([entry], target[1])
    before = target[1].read_bytes()
    calls = []

    def dirty_checkout(args, **kwargs):
        calls.append(list(args))
        outputs = {
            ("config", "--get", "remote.origin.url"): entry.url + "\n",
            ("rev-parse", "HEAD"): entry.commit + "\n",
            ("status", "--porcelain"): " M nodes.py\n",
        }
        assert args[:3] == ["git", "-C", str(checkout)]
        assert tuple(args[3:]) in outputs
        return subprocess.CompletedProcess(args, 0, stdout=outputs[tuple(args[3:])], stderr="")

    pack = CustomNodePack(entry.name, entry.url, frozenset(entry.class_set))
    result = install.install_required_packs([pack], force=True, restore_entries=[entry],
        install_root=target[0], lockfile_path=target[1], runner=dirty_checkout)
    assert not result.ok and result.results[0].status == "skipped_dirty"
    assert result.results[0].error.startswith("conflict:")
    assert f"remove or clean {checkout}, then retry" in result.results[0].error
    assert len(calls) == 3 and target[1].read_bytes() == before


@pytest.mark.parametrize("field,value", [("pip_packages", ("unshown==1",)), ("name", "../escape")])
def test_uncovered_lock_fields_cannot_bypass_recipe_approval(target, field, value):
    entry = recipe_entry()
    runner = RecipeRunner()
    result = install.restore_pack(replace(entry, **{field: value}), install_root=target[0],
        lockfile_path=target[1], runner=runner, approvals=[record(entry)], placement_class="runpod")
    assert result.status == "failed"
    assert runner.calls == []


def test_approval_validation_is_shared_and_data_only():
    entry = recipe_entry()
    original = record(entry)
    changed = copy.deepcopy(original)
    changed["identity"]["commit"] = "c" * 40
    with pytest.raises(ValueError):
        consent_token(changed)
    assert len(consent_token(original)) == 12
