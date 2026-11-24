"""RS1.6: authored recipes survive selection and require exact admission."""
from __future__ import annotations

from dataclasses import replace

import pytest

from tests.fixtures.node_recipe_runner import RecipeRunner
from tests.test_node_recipe_install import target  # noqa: F401
from vibecomfy.custom_node_refs import lock_entry_to_ref
from vibecomfy.node_approvals import CodeConsentRequired, approval_record
from vibecomfy.node_packs import CustomNodePack, LockEntry, read_lockfile, write_lockfile
from vibecomfy.node_packs import _install as install
from vibecomfy.workflow import VibeWorkflow, WorkflowSource


def _shipped(**changes):
    return replace(LockEntry(
        name="recipe-pack", url="https://example.test/recipe-pack.git",
        commit="a" * 40, class_set=("RecipeNode",),
    ), **changes)


def _record(entry):
    return approval_record({
        "repo": entry.url, "commit": entry.commit,
        "requirements_txt": entry.requirements_txt, "pip_no_deps": entry.pip_no_deps,
    }, placement_class="local")


def _pack(entry, *, packages=()):
    return CustomNodePack(entry.name, entry.url, frozenset(entry.class_set), packages)


def _workflow_refs(entry, pack):
    workflow = VibeWorkflow("recipe", WorkflowSource("recipe"), metadata={
        "requirements": {"custom_node_refs": [lock_entry_to_ref(entry)]},
    })
    return install.build_install_refs_by_name(workflow, [pack])


@pytest.mark.parametrize("approval_mode", ["shipped-only", "stale-record"])
@pytest.mark.parametrize("case", ["requirements-file", "no-deps-order", "removed-recipe", "no-target-witness"])
def test_changed_authored_recipe_refuses_before_mutation(target, monkeypatch, case, approval_mode):
    root, lock, _ = target
    if case == "no-target-witness":
        shipped = _shipped()
        authored = replace(shipped, pip_no_deps=("new-only==1",))
        entries = []
    else:
        shipped = _shipped(requirements_txt="deps/requirements.txt",
                           pip_no_deps=("first==1", "second==2"))
        changes = {
            "requirements-file": {"requirements_txt": "other.txt"},
            "no-deps-order": {"pip_no_deps": tuple(reversed(shipped.pip_no_deps))},
            "removed-recipe": {"requirements_txt": None, "pip_no_deps": ()},
        }
        authored = replace(shipped, **changes[case])
        entries = [shipped]
        write_lockfile(entries, lock)
    monkeypatch.setattr("vibecomfy.node_packs.read_lockfile", lambda: [shipped])
    pack = _pack(shipped)
    before = lock.read_bytes() if lock.exists() else None
    runner = RecipeRunner()
    result = install.install_required_packs(
        [pack], restore_entries=entries,
        install_refs_by_name=_workflow_refs(authored, pack),
        approvals=[_record(shipped)] if approval_mode == "stale-record" else [],
        install_root=root, lockfile_path=lock, runner=runner,
    )
    assert not result.ok
    assert result.results[0].status == "failed"
    assert result.results[0].error.startswith("needs_consent:")
    assert runner.calls == []
    assert not root.exists()
    assert (lock.read_bytes() if lock.exists() else None) == before


@pytest.mark.parametrize("source", ["workflow", "mapping", "mapping-without-slug"])
def test_fresh_authored_recipe_requires_exact_approval(monkeypatch, source):
    shipped = _shipped(pip_packages=("legacy-only==99",))
    authored = replace(shipped, requirements_txt="deps/requirements.txt",
                       pip_no_deps=("first==1", "second==2", "first==1"), pip_packages=())
    monkeypatch.setattr("vibecomfy.node_packs.read_lockfile", lambda: [shipped])
    pack = _pack(shipped, packages=shipped.pip_packages)
    raw = lock_entry_to_ref(authored)
    if source == "workflow":
        ref = _workflow_refs(authored, pack)[pack.name]
    else:
        if source == "mapping-without-slug":
            raw.pop("slug")
            raw.pop("name", None)
        ref = raw
    selected = install._batch_restore_entry(pack, ref, [shipped])
    assert selected is not shipped
    assert selected.url == authored.url
    assert selected.commit == authored.commit
    assert selected.requirements_txt == authored.requirements_txt
    assert selected.pip_no_deps == authored.pip_no_deps
    assert selected.pip_packages == ()
    with pytest.raises(CodeConsentRequired, match="needs_consent"):
        install.validate_restore_approvals([selected], [_record(shipped)], placement_class="local")
    assert install.validate_restore_approvals(
        [selected], [_record(authored)], placement_class="local",
    ) == [_record(authored)]


@pytest.mark.parametrize("declared", [False, True], ids=["defaults", "ordered"])
def test_same_authored_recipe_reuses_exact_lock(declared):
    shipped = _shipped(**(
        {"requirements_txt": "deps/requirements.txt", "pip_no_deps": ("b==2", "a==1", "b==2")}
        if declared else {}
    ))
    pack = _pack(shipped)
    raw = lock_entry_to_ref(shipped)
    if not declared:
        raw.update(requirements_txt=None, pip_no_deps=[])
    assert install._matching_lock_entry(pack, raw, [shipped]) is shipped
    assert install._batch_restore_entry(pack, raw, [shipped]) is shipped


def test_exact_new_approval_installs_and_persists_authored_recipe(target, monkeypatch):
    root, lock, _ = target
    shipped = _shipped(pip_packages=("legacy-only==99",))
    authored = replace(shipped, requirements_txt="deps/requirements.txt",
                       pip_no_deps=("second==2", "first==1", "second==2"), pip_packages=())
    write_lockfile([shipped], lock)
    monkeypatch.setattr("vibecomfy.node_packs.read_lockfile", lambda: [shipped])
    pack = _pack(shipped, packages=shipped.pip_packages)
    runner = RecipeRunner()
    result = install.install_required_packs(
        [pack], restore_entries=[shipped],
        install_refs_by_name=_workflow_refs(authored, pack),
        approvals=[_record(authored)], install_root=root, lockfile_path=lock, runner=runner,
    )
    assert result.ok, result
    [saved] = read_lockfile(lock)
    assert saved.commit == authored.commit and saved.url == authored.url
    assert saved.requirements_txt == authored.requirements_txt
    assert saved.pip_no_deps == authored.pip_no_deps
    assert saved.pip_packages == ()
    assert len(runner.installs) == 4
    assert runner.installs[0][-2] == "-r"
    assert [call[-2:] for call in runner.installs[1:]] == [
        ["--no-deps", item] for item in authored.pip_no_deps
    ]
    assert not any("legacy-only==99" in call for call in runner.calls)


def test_invalid_direct_recipe_ref_refused_before_mutation(target, monkeypatch):
    root, lock, _ = target
    shipped = _shipped()
    monkeypatch.setattr("vibecomfy.node_packs.read_lockfile", lambda: [shipped])
    pack = _pack(shipped)
    raw = {**lock_entry_to_ref(shipped), "pip_no_deps": ["--index-url=https://example.test"]}
    runner = RecipeRunner()
    result = install.install_required_packs(
        [pack], restore_entries=[shipped], install_refs_by_name={pack.name: raw},
        install_root=root, lockfile_path=lock, runner=runner,
    )
    assert not result.ok
    assert result.results[0].error.startswith("needs_consent:")
    assert "pip_no_deps" in result.results[0].error
    assert runner.calls == []
    assert not root.exists() and not lock.exists()
