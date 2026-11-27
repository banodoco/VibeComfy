"""Exact-source inspection uses real Git objects through a local transport seam."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from vibecomfy.requirements._sources import inspect_source

REPO = "https://example.test/author/ExamplePack.git"


def _commit(tmp_path, files):
    root = tmp_path / "upstream"
    root.mkdir()
    for path, content in files.items():
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content.encode() if isinstance(content, str) else content)
    for argv in (["init", "--quiet"], ["config", "user.name", "Source fixture"],
                 ["config", "user.email", "source@example.test"], ["add", "."],
                 ["commit", "--quiet", "--allow-empty", "-m", "source fixture"]):
        subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True)
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    return root, commit


class LocalGit:
    """Redirect only the fixture's HTTPS transport; retain actual Git reads."""

    def __init__(self, source):
        self.source = source
        self.calls = []
        self.temporary = None

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.temporary = Path(kwargs["cwd"])
        assert kwargs["env"]["GIT_CONFIG_GLOBAL"] == os.devnull
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        actual = list(argv)
        if "fetch" in actual:
            index = actual.index("--", actual.index("fetch")) + 1
            assert actual[index] == REPO
            actual[index] = str(self.source)
            actual[1:1] = ["-c", "protocol.file.allow=always"]
        return subprocess.run(actual, **kwargs)


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts}


def test_reads_pinned_tree_dependencies_and_class_literals_without_execution(tmp_path, monkeypatch):
    marker = tmp_path / "code-executed"
    files = {
        "requirements.txt": "numpy>=1.26\n-r deps/runtime.txt\n-c constraints.txt\n",
        "deps/runtime.txt": "einops\ntransformers>=4.54.0\n",
        "constraints.txt": "numpy==2.0.0\n",
        "pyproject.toml": '[project]\nname="example"\ndependencies=["soundfile==0.14.0"]\n',
        "install.py": f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\n',
        "nodes.py": f'from pathlib import Path\nPath({str(marker)!r}).write_text("imported")\nNODE_CLASS_MAPPINGS = {{"ExampleNode": UndefinedClass}}\n',
    }
    source, commit = _commit(tmp_path, files)
    before = _snapshot(source)
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "must-not-use"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "must-not-write"))
    runner = LocalGit(source)
    result = inspect_source(REPO, commit, runner=runner)
    assert result["repo"] == REPO and result["commit"] == commit
    assert result["tree"] == subprocess.check_output(["git", "--git-dir", str(source / ".git"), "rev-parse", "HEAD^{tree}"], text=True).strip()
    assert result["recipe"] == {"requirements_txt": "requirements.txt", "pip_no_deps": []}
    assert result["packages"] == ["numpy>=1.26", "einops", "transformers>=4.54.0"]
    assert result["pyproject_packages"] == ["soundfile==0.14.0"]
    assert result["constraints"] == ["numpy==2.0.0"]
    assert result["dynamic_dependencies"] is False
    assert result["class_names"] == ["ExampleNode"]
    assert result["class_files"] == [{"path": "nodes.py", "git_blob": subprocess.check_output(["git", "--git-dir", str(source / ".git"), "rev-parse", "HEAD:nodes.py"], text=True).strip(), "classes": ["ExampleNode"]}]
    assert result["install_py"]["present"] is True and result["install_py"]["run"] is False
    assert result["install_py"]["sha256"] == hashlib.sha256(files["install.py"].encode()).hexdigest()
    assert result["checkout_bytes"] == sum(len(content.encode()) for content in files.values())
    assert [record["path"] for record in result["files"]] == ["constraints.txt", "deps/runtime.txt", "pyproject.toml", "requirements.txt"]
    for record in result["files"]:
        assert record["content"] == files[record["path"]]
        assert record["sha256"] == hashlib.sha256(record["content"].encode()).hexdigest()
    assert not marker.exists()
    assert _snapshot(source) == before
    assert not runner.temporary.exists()
    assert all(call[0] == "git" and "checkout" not in call for call in runner.calls)
    assert not (tmp_path / "must-not-write").exists()
    assert inspect_source(REPO, commit, runner=LocalGit(source)) == result


@pytest.mark.parametrize("repo,commit", [
    ("file:///tmp/repo", "a" * 40),
    ("https://person:password@example.test/pack", "a" * 40),
    (REPO + "?token=private", "a" * 40),
    (REPO + "@main", "a" * 40),
    (REPO, "main"),
    (REPO, "A" * 40),
])
def test_refuses_noncanonical_sources_before_transport(repo, commit):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid source must not reach Git")

    with pytest.raises(ValueError):
        inspect_source(repo, commit, runner=forbidden)


@pytest.mark.parametrize("files,error", [
    ({"requirements.txt": "-r absent.txt\n"}, "missing"),
    ({"requirements.txt": "-r ../outside.txt\n"}, "escapes"),
    ({"requirements.txt": "-r requirements.txt\n"}, "cyclic"),
    ({"requirements.txt": "-r https://example.test/requirements.txt\n"}, "inside"),
    ({"requirements.txt": "--requirem deps.txt\n", "deps.txt": "numpy\n"}, "unsupported"),
    ({"requirements.txt": "--index-url https://example.test/packages\n"}, "unsupported"),
    ({"requirements.txt": "example @ ${PRIVATE_URL}\n"}, "substitutions"),
    ({"requirements.txt": b"\xff\n"}, "UTF-8"),
    ({"pyproject.toml": "[project]\ndependencies=7\n"}, "dependencies"),
])
def test_incomplete_dependency_evidence_refuses_instead_of_empty_success(tmp_path, files, error):
    source, commit = _commit(tmp_path, files)
    runner = LocalGit(source)
    with pytest.raises(ValueError, match=error):
        inspect_source(REPO, commit, runner=runner)
    assert not runner.temporary.exists()


def test_symlink_dependency_refuses_without_following_target(tmp_path):
    source, _ = _commit(tmp_path, {"deps.txt": "numpy==2\n"})
    (source / "requirements.txt").symlink_to("deps.txt")
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "--quiet", "-m", "symlink"], check=True)
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    with pytest.raises(ValueError, match="regular blob"):
        inspect_source(REPO, commit, runner=LocalGit(source))


def test_unknown_dynamic_dependencies_and_classes_remain_explicit(tmp_path):
    source, commit = _commit(tmp_path, {
        "pyproject.toml": '[project]\nname="example"\ndynamic=["dependencies"]\n',
        "nodes.py": 'NODE_CLASS_MAPPINGS = build_mapping()\n',
    })
    result = inspect_source(REPO, commit, runner=LocalGit(source))
    assert result["dynamic_dependencies"] is True
    assert result["packages"] == []
    assert result["class_names"] == []
    assert result["incomplete_class_files"] == ["nodes.py"]
    assert result["install_py"] == {"present": False, "git_blob": None, "sha256": None, "run": False}


def test_timeout_remains_typed_and_cleans_scratch(tmp_path):
    temporary = []

    def timeout(argv, **kwargs):
        temporary.append(Path(kwargs["cwd"]))
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    with pytest.raises(subprocess.TimeoutExpired):
        inspect_source(REPO, "a" * 40, runner=timeout)
    assert temporary and not temporary[0].exists()


def test_modified_blob_bytes_refuse_content_identity(tmp_path):
    source, commit = _commit(tmp_path, {"requirements.txt": "example==1\n"})
    transport = LocalGit(source)

    def corrupt(argv, **kwargs):
        result = transport(argv, **kwargs)
        if "cat-file" in argv:
            return subprocess.CompletedProcess(argv, 0, b"example==2\n", b"")
        return result

    with pytest.raises(ValueError, match="blob bytes"):
        inspect_source(REPO, commit, runner=corrupt)


def test_gitlink_size_stays_unknown_and_no_submodule_fetch_runs(tmp_path):
    source, child = _commit(tmp_path, {"nodes.py": "NODE_CLASS_MAPPINGS = {}\n"})
    subprocess.run(["git", "-C", str(source), "update-index", "--add", "--cacheinfo", "160000", child, "vendor/dependency"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "--quiet", "-m", "gitlink"], check=True)
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    transport = LocalGit(source)
    result = inspect_source(REPO, commit, runner=transport)
    assert result["checkout_bytes"] is None
    assert result["submodules"] == [{"path": "vendor/dependency", "commit": child}]
    assert sum("fetch" in call for call in transport.calls) == 1
    assert all("submodule" not in call for call in transport.calls)


def test_recursive_long_form_includes_preserve_requirement_order(tmp_path):
    source, commit = _commit(tmp_path, {
        "requirements.txt": "--requirement=deps/base.txt\nlast==3\n",
        "deps/base.txt": "first==1\n--requirement ../second.txt\n--constraint=../constraints.txt\n",
        "second.txt": "second==2\n",
        "constraints.txt": "first==1\n-r extra.txt\n",
        "extra.txt": "extra==4\n",
    })
    result = inspect_source(REPO, commit, runner=LocalGit(source))
    assert result["packages"] == ["first==1", "second==2", "extra==4", "last==3"]
    assert result["constraints"] == ["first==1"]
    assert len(result["files"]) == 5


def test_wrong_fetched_commit_refuses_before_tree_read(tmp_path):
    source, commit = _commit(tmp_path, {"requirements.txt": "example==1\n"})
    transport = LocalGit(source)

    def substitute(argv, **kwargs):
        if "rev-parse" in argv and argv[-1].endswith("^{commit}"):
            return subprocess.CompletedProcess(argv, 0, b"0" * 40 + b"\n", b"")
        return transport(argv, **kwargs)

    with pytest.raises(ValueError, match="immutable commit/tree"):
        inspect_source(REPO, commit, runner=substitute)
    assert all("ls-tree" not in call for call in transport.calls)


@pytest.mark.parametrize("selected,packages,files", [
    (None, [], ["pyproject.toml"]),
    ("deps/selected.txt", ["selected==2", "included==3"],
     ["deps/selected.txt", "included.txt", "pyproject.toml"]),
])
def test_explicit_recipe_controls_selected_dependencies(tmp_path, selected, packages, files):
    source, commit = _commit(tmp_path, {
        "requirements.txt": "unselected==1\n",
        "deps/selected.txt": "selected==2\n-r ../included.txt\n",
        "included.txt": "included==3\n",
        "pyproject.toml": '[project]\nname="example"\ndependencies=["metadata-only==4"]\n',
    })
    result = inspect_source(REPO, commit, requirements_txt=selected, runner=LocalGit(source))
    assert result["recipe"] == {"requirements_txt": selected, "pip_no_deps": []}
    assert result["packages"] == packages
    assert result["pyproject_packages"] == ["metadata-only==4"]
    assert [record["path"] for record in result["files"]] == files


def test_explicit_missing_recipe_refuses_even_when_default_file_exists(tmp_path):
    source, commit = _commit(tmp_path, {"requirements.txt": "default==1\n"})
    with pytest.raises(ValueError, match="missing"):
        inspect_source(REPO, commit, requirements_txt="other.txt", runner=LocalGit(source))


@pytest.mark.parametrize("selected", ["../outside.txt", "/absolute.txt", "deps/../requirements.txt", "", 7])
def test_invalid_selected_recipe_refuses_before_transport(selected):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid selected recipe must not reach Git")

    with pytest.raises(ValueError, match="requirements_txt"):
        inspect_source(REPO, "a" * 40, requirements_txt=selected, runner=forbidden)
