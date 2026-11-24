"""WS-7b: restore the declared recipe through the controlled pip path."""
from __future__ import annotations

import importlib.metadata
from dataclasses import replace
from pathlib import Path

import pytest

from tests.fixtures.node_recipe_runner import RecipeRunner
from vibecomfy.node_approvals import approval_record
from vibecomfy.node_packs import CustomNodePack, LockEntry, read_lockfile, write_lockfile
from vibecomfy.node_packs import _install as install


PIN = "a" * 40
NO_DEPS = (
    "dacvae @ git+https://github.com/facebookresearch/dacvae.git@414c20785fc3a28373073ea8ef7a1316eeeaca6e",
    "perception-models @ git+https://github.com/facebookresearch/perception_models.git@e72b6810b1133e1c879f2cc965d276eb73803f1f",
    "sam-audio @ git+https://github.com/facebookresearch/sam-audio.git@bb4c6999d2677c7402360e426afc01ddfad6dce0",
)


@pytest.fixture
def target(tmp_path, monkeypatch):
    versions = {"torch": "2.10.0+cu130"}

    def version(name):
        if name not in versions:
            raise importlib.metadata.PackageNotFoundError(name)
        return versions[name]

    monkeypatch.setattr(install.importlib.metadata, "version", version)
    monkeypatch.delenv("VIBECOMFY_PROTECTED_RUNTIME_PACKAGES", raising=False)
    monkeypatch.setattr(install, "_pack_by_name", lambda name: None)
    return tmp_path / "custom_nodes", tmp_path / "custom_nodes.lock", versions


def recipe_entry(**changes):
    return replace(LockEntry(
        name="recipe-pack", url="https://example.test/recipe-pack.git", commit=PIN,
        requirements_txt="deps/requirements.txt", pip_no_deps=NO_DEPS,
        class_set=("RecipeNode",), class_schema_sha256="b" * 64,
        source_sha256={"nodes.py": "c" * 64},
    ), **changes)


def restore(entry, target, runner):
    root, lock, _ = target
    # The missing-pin negative case must reach production validation unchanged.
    records = approved(entry) if entry.git_commit_sha is not None else []
    return install.restore_pack(entry, install_root=root, lockfile_path=lock, runner=runner, approvals=records)


def approved(entry):
    return [approval_record({"repo": entry.url, "commit": entry.git_commit_sha,
        "requirements_txt": entry.requirements_txt, "pip_no_deps": list(entry.pip_no_deps)}, placement_class="local")]


def test_restore_recipe_clone_checkout_requirements_then_ordered_no_deps(target):
    root, lock, _ = target
    entry = recipe_entry()
    runner = RecipeRunner()
    result = restore(entry, target, runner)
    assert result.status == "installed"
    assert runner.calls[:2] == [
        ["git", "clone", entry.url, str(root / entry.name)],
        ["git", "-C", str(root / entry.name), "checkout", PIN],
    ]
    assert len(runner.installs) == 4
    assert runner.installs[0][-2:] == ["-r", str((root / entry.name / entry.requirements_txt).resolve())]
    assert [call[-2:] for call in runner.installs[1:]] == [["--no-deps", package] for package in NO_DEPS]
    preflights = [call for call in runner.pip_calls if "--dry-run" in call]
    assert len(preflights) == 8
    assert all(runner.calls.index(call) < runner.calls.index(runner.installs[0]) for call in preflights[:4])
    for index, call in enumerate(runner.installs):
        assert runner.calls[runner.calls.index(call) - 1] == preflights[4 + index]
        assert preflights[4 + index][-2:] == call[-2:]
    assert all(call[1:5] == ["-I", "-m", "pip", "install"] for call in runner.pip_calls)
    assert all(cwd is not None and not Path(cwd).resolve().is_relative_to((root / entry.name).resolve())
               for call, cwd in zip(runner.calls, runner.cwds) if call in runner.pip_calls)
    assert all("torch==2.10.0+cu130" in contents for _, contents in runner.constraints)
    assert all(not path.exists() for path, _ in runner.constraints)
    assert read_lockfile(lock) == [entry]
    assert not (root / install.INSTALL_STATE_DIR / f"{entry.name}.json").exists()


def test_restore_recipe_is_authoritative_over_same_name_catalog(target, monkeypatch):
    entry = recipe_entry()
    catalog = CustomNodePack(entry.name, "https://example.test/other.git", frozenset({"OtherNode"}), ("catalog-only==99",))
    monkeypatch.setattr(install, "_pack_by_name", lambda name: catalog)
    runner = RecipeRunner()
    assert restore(entry, target, runner).status == "installed"
    assert len(runner.installs) == 4
    assert not any("catalog-only==99" in call for call in runner.calls)
    assert read_lockfile(target[1]) == [entry]


def test_restore_uses_entry_pip_packages_without_catalog(target, monkeypatch):
    entry = recipe_entry(requirements_txt=None, pip_no_deps=(), pip_packages=("entry-only==2",))
    # Legacy pip_packages authority is the exact shipped review witness.
    monkeypatch.setattr("vibecomfy.node_packs.read_lockfile", lambda: [entry])
    runner = RecipeRunner()
    assert restore(entry, target, runner).status == "installed"
    assert len(runner.installs) == 1
    assert runner.installs[0][-1] == "entry-only==2"


@pytest.mark.parametrize("initial_head", [PIN, "d" * 40], ids=["same-head", "changed-head"])
def test_existing_checkout_applies_own_recipe(target, initial_head):
    entry = recipe_entry()
    runner = RecipeRunner(head=initial_head)
    runner.checkout_tree(target[0] / entry.name)
    result = restore(entry, target, runner)
    assert result.status == "refreshed"
    assert len(runner.installs) == 4
    assert not any(call[:2] == ["git", "clone"] for call in runner.calls)
    checkouts = [call for call in runner.calls if call[:2] == ["git", "-C"] and call[3] == "checkout"]
    assert len(checkouts) == (0 if initial_head == PIN else 1)
    assert read_lockfile(target[1]) == [entry]


@pytest.mark.parametrize("step", range(4), ids=["requirements", "first-no-deps", "second-no-deps", "third-no-deps"])
def test_protected_change_fails_recipe_before_pip_mutation(target, step):
    entry = recipe_entry()
    old = recipe_entry(commit="e" * 40, git_commit_sha="e" * 40)
    write_lockfile([old], target[1])
    before = target[1].read_bytes()
    runner = RecipeRunner()
    runner.reports = [{"install": []}] * step + [{"install": [{"metadata": {"name": "Torch", "version": "2.11.0"}}]}]
    result = restore(entry, target, runner)
    assert result.status == "failed"
    assert "protected runtime package torch" in result.error
    assert not runner.installs
    assert target[1].read_bytes() == before
    assert (target[0] / install.INSTALL_STATE_DIR / f"{entry.name}.json").exists()
    assert all(not path.exists() for path, _ in runner.constraints)


@pytest.mark.parametrize("phase", ["dry_run", "install"])
def test_recipe_pip_failure_keeps_incomplete_state(target, phase):
    entry = recipe_entry()
    runner = RecipeRunner()
    setattr(runner, "fail_" + phase, True)
    result = restore(entry, target, runner)
    assert result.status == "failed"
    assert "recorded" in result.error
    assert not target[1].exists()
    assert (target[0] / install.INSTALL_STATE_DIR / f"{entry.name}.json").exists()
    assert len(runner.installs) == (1 if phase == "install" else 0)
    assert all(not path.exists() for path, _ in runner.constraints)


@pytest.mark.parametrize("report", [None, {}, {"install": [{}]}], ids=["missing", "malformed", "missing-metadata"])
def test_recipe_no_deps_requires_valid_resolution_report(target, report):
    entry = recipe_entry(requirements_txt=None, pip_no_deps=("one==1",))
    runner = RecipeRunner()
    runner.reports = [report]
    result = restore(entry, target, runner)
    assert result.status == "failed"
    assert "pip dry-run" in result.error
    assert not runner.installs
    assert not target[1].exists()


@pytest.mark.parametrize("kind", ["missing", "outside-symlink"])
def test_requirements_file_must_exist_inside_checkout(target, tmp_path, kind):
    entry = recipe_entry()
    files = {}
    if kind == "outside-symlink":
        outside = tmp_path / "outside.txt"
        outside.write_text("outside-only==1\n")
        files[entry.requirements_txt] = outside
    runner = RecipeRunner(files=files)
    result = restore(entry, target, runner)
    assert result.status == "failed"
    assert "requirements" in result.error.lower()
    assert not runner.pip_calls
    assert not target[1].exists()


def test_restore_verifies_checkout_before_reading_recipe(target):
    runner = RecipeRunner()
    runner.ignore_checkout = True
    result = restore(recipe_entry(), target, runner)
    assert result.status == "failed"
    assert "expected git HEAD" in result.error
    assert not runner.pip_calls
    assert not target[1].exists()


def test_restore_rechecks_head_after_recipe_install(target):
    runner = RecipeRunner()
    runner.after_install = lambda: setattr(runner, "head", "f" * 40)
    result = restore(recipe_entry(), target, runner)
    assert result.status == "failed"
    assert "expected git HEAD" in result.error
    assert not target[1].exists()


def test_protected_version_checked_after_each_recipe_install(target):
    runner = RecipeRunner()
    runner.after_install = lambda: target[2].update(torch="2.11.0")
    result = restore(recipe_entry(), target, runner)
    assert result.status == "failed"
    assert "changed protected runtime package torch" in result.error
    assert len(runner.installs) == 1
    assert not target[1].exists()


def test_install_script_never_executed(target):
    entry = recipe_entry()
    runner = RecipeRunner()
    assert restore(entry, target, runner).status == "installed"
    assert (target[0] / entry.name / "install.py").exists()
    assert not (target[0] / entry.name / "SCRIPT_EXECUTED").exists()
    assert not any(any(arg.endswith("install.py") for arg in call) for call in runner.calls)
    assert len(runner.installs) == 4


def test_batch_restores_recipe_from_exact_entry(target):
    entry = recipe_entry()
    pack = CustomNodePack(entry.name, entry.url, frozenset(entry.class_set))
    runner = RecipeRunner()
    result = install.install_required_packs(
        [pack], restore_entries=[entry], install_root=target[0], lockfile_path=target[1], runner=runner,
        approvals=approved(entry),
    )
    assert result.ok
    assert len(runner.installs) == 4
    assert read_lockfile(target[1]) == [entry]


def test_batch_preflight_uses_entry_dependencies_instead_of_catalog(target, monkeypatch):
    entry = recipe_entry(pip_packages=("entry-only==2",))
    monkeypatch.setattr("vibecomfy.node_packs.read_lockfile", lambda: [entry])
    pack = CustomNodePack(entry.name, entry.url, frozenset(entry.class_set), ("catalog-only==99",))
    runner = RecipeRunner()
    result = install.install_required_packs(
        [pack], restore_entries=[entry], install_root=target[0], lockfile_path=target[1], runner=runner,
        approvals=approved(entry),
    )
    assert result.ok
    assert result.preflight.packages == ("entry-only==2",)
    assert not any("catalog-only==99" in call for call in runner.calls)
    assert len(runner.installs) == 5
    assert read_lockfile(target[1]) == [entry]


def test_recipe_keeps_declared_runtime_requirements_protected(target):
    entry = recipe_entry()
    target[2]["requests"] = "2.31.0"
    pack = CustomNodePack(entry.name, entry.url, frozenset(entry.class_set))
    runner = RecipeRunner()
    result = install.install_required_packs(
        [pack], restore_entries=[entry], install_root=target[0], lockfile_path=target[1], runner=runner,
        runtime_requirements=("requests>=2",),
        approvals=approved(entry),
    )
    assert result.ok
    assert len(runner.installs) == 4
    assert all("requests==2.31.0" in contents for _, contents in runner.constraints)


def test_missing_declared_recipe_pin_fails_before_clone(target):
    entry = recipe_entry(commit=None, git_commit_sha=None)
    runner = RecipeRunner()
    result = restore(entry, target, runner)
    assert result.status == "failed"
    assert "commit" in result.error.lower()
    assert not runner.calls
    assert not target[1].exists()
