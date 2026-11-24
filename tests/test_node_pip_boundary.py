"""Offline RS1.1/.7/.8/.9 witnesses for the controlled pip boundary."""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import venv
import zipfile

import pytest

from vibecomfy.node_packs import CustomNodePack, LockEntry
from vibecomfy.node_packs import _install as install


@pytest.fixture
def protected_versions(monkeypatch):
    versions = {"torch": "2.10.0"}

    def version(name):
        if name not in versions:
            raise importlib.metadata.PackageNotFoundError(name)
        return versions[name]

    monkeypatch.setattr(install.importlib.metadata, "version", version)
    monkeypatch.delenv("VIBECOMFY_PROTECTED_RUNTIME_PACKAGES", raising=False)
    return versions


def _entry(**fields):
    return LockEntry(name="boundary-pack", url="https://example.test/boundary.git",
                     commit="a" * 40, class_set=("BoundaryNode",), **fields)


class PipWitness:
    """Observe both baseline and isolated argv without normalizing either."""

    def __init__(self, *, after_install=None, report=None):
        self.calls = []
        self.installs = []
        self.after_install = after_install
        self.report = report

    def __call__(self, args, **kwargs):
        command = list(args)
        self.calls.append((command, kwargs.get("cwd")))
        assert "pip" in command and "install" in command
        if "--help" in command:
            return subprocess.CompletedProcess(command, 0, "--dry-run --report", "")
        if "--dry-run" in command:
            report = self.report(self) if self.report else {"install": []}
            Path(command[command.index("--report") + 1]).write_text(json.dumps(report))
        else:
            self.installs.append(command)
            if self.after_install:
                self.after_install(self)
        return subprocess.CompletedProcess(command, 0, "", "")


def _apply(entry, checkout, runner):
    return install._install_pack_pip_packages(
        entry.name, None, runner, restore_entry=entry, install_dir=checkout,
    )


def _offline_python_and_wheel(tmp_path):
    # Bootstrap only from the already installed pip; no ensurepip download,
    # package index, project build hook, or mutation of the test interpreter.
    import pip

    target = tmp_path / "target-python"
    venv.EnvBuilder(with_pip=False).create(target)
    python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    site = Path(subprocess.check_output(
        [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True,
    ).strip())
    pip_source = Path(pip.__file__).parent
    shutil.copytree(pip_source, site / "pip")
    for metadata in pip_source.parent.glob("pip-*.dist-info"):
        shutil.copytree(metadata, site / metadata.name)
    wheel = tmp_path / "rs1_f4_witness-1.0-py3-none-any.whl"
    info = "rs1_f4_witness-1.0.dist-info"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("rs1_f4_witness.py", "VALUE = 'installed from offline wheel'\n")
        archive.writestr(f"{info}/METADATA", "Metadata-Version: 2.1\nName: rs1-f4-witness\nVersion: 1.0\n")
        archive.writestr(f"{info}/WHEEL", "Wheel-Version: 1.0\nGenerator: rs1-offline-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr(f"{info}/RECORD", "")
    return python, wheel


@pytest.mark.parametrize("phase", ["recipe", "batch-preflight"])
def test_rs1_7_checkout_cannot_shadow_target_pip(tmp_path, monkeypatch, phase):
    python, wheel = _offline_python_and_wheel(tmp_path)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    marker = tmp_path / "CHECKOUT_CODE_EXECUTED"
    shadow = (
        "import json, sys\nfrom pathlib import Path\n"
        f"Path({str(marker)!r}).touch()\n"
        "if '--report' in sys.argv:\n"
        "    Path(sys.argv[sys.argv.index('--report') + 1]).write_text(json.dumps({'install': []}))\n"
        "if '--help' in sys.argv: print('--dry-run --report')\n"
    )
    (checkout / "pip.py").write_text(shadow)
    (checkout / "sitecustomize.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    (checkout / "deps").mkdir()
    (checkout / "requirements.txt").write_text("-r deps/wheels.txt\n-c deps/constraints.txt\n")
    (checkout / "deps/wheels.txt").write_text(str(wheel) + "\n")
    (checkout / "deps/constraints.txt").write_text("rs1-f4-witness==1.0\n")
    calls = []
    monkeypatch.setattr(install.sys, "executable", str(python))
    monkeypatch.chdir(checkout)

    def real_pip(args, **kwargs):
        calls.append((list(args), kwargs.get("cwd")))
        environment = {**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                       "PYTHONPATH": str(checkout), "PIP_CONFIG_FILE": os.devnull}
        return subprocess.run(args, **kwargs, env=environment)

    if phase == "recipe":
        error = _apply(_entry(requirements_txt="requirements.txt"), checkout, real_pip)
        assert error is None
    else:
        result = install.preflight_pip_requirements(
            [CustomNodePack("pack", "https://example.test/pack", frozenset(), (str(wheel),))],
            runner=real_pip,
        )
        assert result.ok, result.error
    assert not marker.exists(), "checkout pip/sitecustomize executed during controlled pip"
    assert calls and all(call[1:5] == ["-I", "-m", "pip", "install"] for call, _ in calls)
    assert all(cwd is not None and not Path(cwd).resolve().is_relative_to(checkout) for _, cwd in calls)
    if phase == "recipe":
        installed = subprocess.check_output(
            [str(python), "-I", "-c", "import importlib.metadata; print(importlib.metadata.version('rs1-f4-witness'))"], text=True,
        )
        assert installed.strip() == "1.0"


@pytest.mark.parametrize("directive", [
    "-r ../../outside.txt", "-c ../../outside.txt",
    "--requirement=../../outside.txt", "--constraint ../../outside.txt",
    "-r../../outside.txt", "-c../../outside.txt",
    "--req ../../outside.txt", "--constr=../../outside.txt",
    "-r \\\n../../outside.txt", "-c ${RS1_OUTSIDE}",
    "-r file:///outside.txt", "-r https://example.test/requirements.txt",
], ids=["requirements", "constraints", "long-equals", "long-space", "short-attached-r", "short-attached-c",
        "abbreviated-r", "abbreviated-c", "continuation", "environment", "file-url", "https-url"])
def test_rs1_8_nested_include_escape_refused_before_pip(tmp_path, monkeypatch, protected_versions, directive):
    checkout = tmp_path / "checkout"
    (checkout / "deps").mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside-package==1\n")
    monkeypatch.setenv("RS1_OUTSIDE", str(outside))
    (checkout / "requirements.txt").write_text("-r deps/nested.txt\n")
    (checkout / "deps/nested.txt").write_text(directive + "\n")
    runner = PipWitness()
    error = _apply(_entry(requirements_txt="requirements.txt"), checkout, runner)
    assert error is not None and "requirements" in error.lower()
    assert runner.calls == [], "unconfined nested file reached pip"


def test_rs1_8_nested_symlink_escape_refused_before_pip(tmp_path, protected_versions):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside-package==1\n")
    (checkout / "requirements.txt").write_text("-c constraint.txt\n")
    (checkout / "constraint.txt").symlink_to(outside)
    runner = PipWitness()
    error = _apply(_entry(requirements_txt="requirements.txt"), checkout, runner)
    assert error is not None and "checkout" in error.lower()
    assert runner.calls == []


def test_rs1_8_cycle_refused_before_pip(tmp_path, protected_versions):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "requirements.txt").write_text("-r again.txt\n")
    (checkout / "again.txt").write_text("-r requirements.txt\n")
    runner = PipWitness()
    error = _apply(_entry(requirements_txt="requirements.txt"), checkout, runner)
    assert error is not None and "cycl" in error.lower()
    assert runner.calls == []


def test_rs1_8_symlinked_include_uses_its_spelled_parent(tmp_path, protected_versions):
    checkout = tmp_path / "checkout"
    (checkout / "inner").mkdir(parents=True)
    (tmp_path / "outside.txt").write_text("outside-package==1\n")
    (checkout / "outside.txt").write_text("inside-package==1\n")
    (checkout / "requirements.txt").write_text("-r alias.txt\n")
    (checkout / "inner/real.txt").write_text("-r ../outside.txt\n")
    (checkout / "alias.txt").symlink_to(checkout / "inner/real.txt")
    runner = PipWitness()
    error = _apply(_entry(requirements_txt="requirements.txt"), checkout, runner)
    assert error is not None and "inside its checkout" in error
    assert runner.calls == []


def test_rs1_8_includes_rechecked_after_previous_step(tmp_path, protected_versions):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (tmp_path / "outside.txt").write_text("outside-package==1\n")
    requirements = checkout / "requirements.txt"
    requirements.write_text("inside-package==1\n")
    runner = PipWitness(after_install=lambda _: requirements.write_text("-r ../outside.txt\n"))
    error = _apply(_entry(requirements_txt="requirements.txt", pip_packages=("first==1",)), checkout, runner)
    assert error is not None and "inside its checkout" in error
    assert [call[-1] for call in runner.installs] == ["first==1"]


def test_rs1_7_temp_directory_inside_checkout_is_refused(tmp_path, monkeypatch, protected_versions):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(install.tempfile, "tempdir", str(checkout))
    runner = PipWitness()
    error = _apply(_entry(pip_no_deps=("package==1",)), checkout, runner)
    assert error is not None and "outside its checkout" in error
    assert runner.calls == []


def test_rs1_9_later_step_repreflight_observes_current_environment(tmp_path, protected_versions):
    def report(runner):
        if runner.installs:
            return {"install": [{"metadata": {"name": "torch", "version": "2.11.0"}}]}
        return {"install": []}

    runner = PipWitness(report=report)
    error = _apply(_entry(pip_no_deps=("first==1", "second==1")), tmp_path, runner)
    assert error is not None and "would change protected runtime package torch" in error
    assert [call[-1] for call in runner.installs] == ["first==1"]
    phases = [("dry" if "--dry-run" in call else "install", call[-1]) for call, _ in runner.calls]
    assert phases == [("dry", "first==1"), ("dry", "second==1"),
                      ("dry", "first==1"), ("install", "first==1"), ("dry", "second==1")]


@pytest.mark.parametrize("mutation", ["changed", "removed"])
def test_rs1_9_failing_step_still_checks_protected_versions(tmp_path, protected_versions, mutation):
    def fail_after_mutation(runner):
        if mutation == "changed":
            protected_versions["torch"] = "2.11.0"
        else:
            del protected_versions["torch"]
        raise subprocess.CalledProcessError(1, runner.installs[-1], stderr="offline failing build")

    runner = PipWitness(after_install=fail_after_mutation)
    error = _apply(_entry(pip_no_deps=("first==1", "never==1")), tmp_path, runner)
    assert error is not None and "changed protected runtime package torch" in error
    assert "offline failing build" in error
    assert len(runner.installs) == 1


def test_rs1_9_all_recipe_steps_checked_before_first_mutation(tmp_path, protected_versions):
    def report(runner):
        if runner.calls[-1][0][-1] == "last==1":
            return {"install": [{"metadata": {"name": "torch", "version": "2.11.0"}}]}
        return {"install": []}

    runner = PipWitness(report=report)
    error = _apply(_entry(pip_no_deps=("first==1", "last==1")), tmp_path, runner)
    assert error is not None and "protected runtime package torch" in error
    assert runner.installs == []


def test_rs1_1_preparation_refuses_unapproved_batch_before_dependency_resolution(tmp_path, monkeypatch):
    import vibecomfy.node_packs as node_packs
    from vibecomfy.runtime.prepared import PreparationError, prepare_workflow

    pack = CustomNodePack("BoundaryPack", "https://example.test/unapproved.git",
                          frozenset({"BoundaryNode"}), ("unapproved-build-hook==1",))
    ref = {"slug": "boundary-pack", "source": "git", "url": pack.repo, "commit": "a" * 40}
    workflow = SimpleNamespace(metadata={"requirements": {"custom_node_refs": [ref]}},
        nodes={}, runtime_nodes=lambda: {}, requirements=SimpleNamespace(models=[], custom_nodes=[pack.name]))
    calls = []
    monkeypatch.setattr(node_packs, "missing_packs_for_workflow", lambda *args, **kwargs: ([pack], []))

    def early_preflight(packs):
        calls.extend(package for item in packs for package in item.pip_packages)
        return node_packs.PipPreflightResult(ok=True)

    monkeypatch.setattr(node_packs, "preflight_pip_requirements", early_preflight)
    with pytest.raises(PreparationError, match="needs_consent"):
        prepare_workflow(workflow, reference=tmp_path / "workflow.py", runtime_root=tmp_path / "runtime",
                         ensure_models=False, ensure_packs=True)
    assert calls == [], "unapproved workflow dependencies reached the early pip preflight"
    assert not (tmp_path / "runtime/custom_nodes.lock").exists()
