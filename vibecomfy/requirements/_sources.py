"""Read an immutable node repository without checking out or executing its code.

Only Git objects in a temporary bare repository are read. Dependency declarations
are evidence, not a solved package lock or an installation instruction. In
particular, finding ``install.py`` never makes it an executable plan action.
"""
from __future__ import annotations

import ast
import hashlib
import math
import os
import posixpath
import re
import shlex
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Callable

_SHA = re.compile(r"[0-9a-f]{40}")
_MAX_TEXT_BYTES = 2 * 1024 * 1024
_AUTO_REQUIREMENTS = object()


def _relative(path: str, *, parent: str = "") -> str:
    if (not path or path.startswith(("/", "-")) or ":" in path or "\\" in path
            or any(ord(char) < 32 or ord(char) == 127 for char in path)):
        raise ValueError(f"dependency path must stay inside the pinned tree: {path!r}")
    result = posixpath.normpath(posixpath.join(parent, path))
    if result in {".", ".."} or result.startswith("../"):
        raise ValueError(f"dependency path escapes the pinned tree: {path!r}")
    return result


def _tree_rows(payload: bytes) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for record in payload.split(b"\0"):
        if not record:
            continue
        try:
            header, raw_path = record.split(b"\t", 1)
            mode, kind, blob, size = header.decode("ascii").split()
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise ValueError("malformed pinned Git tree") from exc
        if (_relative(path) != path or path in rows or not _SHA.fullmatch(blob)
                or (kind, mode) not in {("blob", "100644"), ("blob", "100755"),
                                        ("blob", "120000"), ("commit", "160000")}):
            raise ValueError(f"unsupported pinned Git tree entry: {path!r}")
        if (kind == "blob" and (not size.isdecimal() or int(size) < 0)
                or kind == "commit" and size != "-"):
            raise ValueError(f"invalid pinned Git object size: {path!r}")
        rows[path] = {"mode": mode, "kind": kind, "git_blob": blob,
                      "size": int(size) if size != "-" else None}
    return rows


def _logical_lines(content: str) -> list[str]:
    """Use pip's continuation-before-comment order without interpreting code."""
    lines, continued = [], []
    for line in content.splitlines():
        comment = re.match(r"(^|\s+)#", line)
        if line.endswith("\\") and not comment:
            continued.append(line[:-1])
        else:
            lines.append("".join(continued) + (" " if comment else "") + line)
            continued.clear()
    if continued:
        raise ValueError("unterminated dependency line continuation")
    return [value for raw in lines if (value := re.sub(r"(^|\s+)#.*$", "", raw).strip())]


def inspect_source(
    repo: str,
    commit: str,
    *,
    requirements_txt: str | None | object = _AUTO_REQUIREMENTS,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    """Return content-bound declarations from exactly ``repo`` at ``commit``.

    ``runner`` is the subprocess seam for recorded transport fixtures. No
    checkout, Python import, package solver, installer, or target probe runs.
    Timeouts retain ``subprocess.TimeoutExpired``; missing or malformed source
    evidence raises ``ValueError`` rather than reporting an empty dependency set.
    ``checkout_bytes`` counts Git blob bytes, not transfer or disk capacity.
    Static class declarations never prove that a target can import those nodes.
    Omitted ``requirements_txt`` discovers the root requirements file; explicit
    ``None`` selects no requirements step. ``packages`` describes only the
    selected step, while ``pyproject_packages`` remains separate source evidence.
    """
    from vibecomfy.custom_node_refs import _added_repository
    from vibecomfy.node_recipes import canonical_recipe

    canonical, _, selector = _added_repository(repo)
    if canonical != repo or selector != "HEAD" or "@" in repo:
        raise ValueError("source inspection requires a canonical HTTPS repository URL")
    if not isinstance(commit, str) or _SHA.fullmatch(commit) is None:
        raise ValueError("source inspection requires a full lowercase 40-hex commit")
    if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
            or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("source inspection timeout must be positive")
    if requirements_txt is not _AUTO_REQUIREMENTS:
        canonical_recipe({"requirements_txt": requirements_txt})
    run = subprocess.run if runner is None else runner
    # A caller's Git worktree/config/alternate-object variables must never bind
    # these reads to a different source or cause writes outside the scratch repo.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_ASKPASS="", SSH_ASKPASS="")
    options = ["git", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
               "-c", "credential.helper=", "-c", f"core.hooksPath={os.devnull}",
               "-c", "init.templateDir="]

    with tempfile.TemporaryDirectory(prefix="vibecomfy-plan-source-") as temporary:
        git_dir = Path(temporary) / "objects.git"

        def git(*args: str, initialise: bool = False) -> bytes:
            argv = [*options, *([] if initialise else [f"--git-dir={git_dir}"]), *args]
            try:
                result = run(argv, cwd=temporary, env=env, capture_output=True,
                             check=True, timeout=timeout)
            except subprocess.CalledProcessError as exc:
                raise ValueError(f"cannot read pinned source {repo}@{commit}: Git {args[0]} failed") from exc
            if result.returncode:
                raise ValueError(f"cannot read pinned source {repo}@{commit}: Git {args[0]} failed")
            if not isinstance(result.stdout, bytes):
                raise ValueError("pinned Git source reader requires byte output")
            return result.stdout

        git("init", "--bare", str(git_dir), initialise=True)
        git("fetch", "--no-tags", "--depth=1", "--no-recurse-submodules", "--", repo, commit)
        observed = git("rev-parse", "--verify", f"{commit}^{{commit}}").decode("ascii").strip()
        tree = git("rev-parse", "--verify", f"{commit}^{{tree}}").decode("ascii").strip()
        if observed != commit or _SHA.fullmatch(tree) is None:
            raise ValueError("fetched Git source does not match its immutable commit/tree")
        rows = _tree_rows(git("ls-tree", "-r", "-l", "-z", "--full-tree", commit))
        cache: dict[str, dict[str, Any]] = {}

        def read(path: str) -> dict[str, Any]:
            if path in cache:
                return cache[path]
            row = rows.get(path)
            if row is None or row["mode"] not in {"100644", "100755"}:
                raise ValueError(f"dependency/source file is missing or is not a regular blob: {path}")
            if row["size"] > _MAX_TEXT_BYTES:
                raise ValueError(f"source declaration exceeds the text inspection limit: {path}")
            raw = git("cat-file", "blob", row["git_blob"])
            blob_hash = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
            if len(raw) != row["size"] or blob_hash != row["git_blob"]:
                raise ValueError(f"Git blob bytes do not match the pinned tree: {path}")
            try:
                content = raw.decode("utf-8")
            except UnicodeError as exc:
                raise ValueError(f"source declaration must use UTF-8: {path}") from exc
            cache[path] = {"path": path, "git_blob": row["git_blob"],
                           "sha256": hashlib.sha256(raw).hexdigest(), "content": content}
            return cache[path]

        dependency_paths: set[str] = set()
        packages: list[str] = []
        constraints: list[str] = []
        seen: set[tuple[str, bool]] = set()

        def requirements(path: str, ancestors: tuple[str, ...] = (), constraint: bool = False) -> None:
            if path in ancestors:
                raise ValueError(f"cyclic requirements include in pinned tree: {path}")
            if (path, constraint) in seen:
                return
            content = read(path)["content"]
            dependency_paths.add(path)
            seen.add((path, constraint))
            for header in content.splitlines()[:2]:
                encoding = re.search(r"coding[:=]\s*([-\w.]+)", header)
                if encoding and encoding[1].lower().replace("_", "-") not in {"utf-8", "utf8"}:
                    raise ValueError(f"requirements file must declare UTF-8: {path}")
            for line in _logical_lines(content.lstrip("\ufeff")):
                if "${" in line:
                    raise ValueError(f"requirements file cannot use environment substitutions: {path}")
                if not line.startswith("-"):
                    (constraints if constraint else packages).append(line)
                    continue
                tokens = shlex.split(line)
                option, equals, value = tokens[0].partition("=")
                is_constraint = option in {"-c", "--constraint"} or option.startswith("-c")
                if option in {"--requirement", "--constraint"}:
                    include = value if equals else tokens[1] if len(tokens) == 2 else ""
                    expected = 1 if equals else 2
                elif tokens[0].startswith(("-r", "-c")) and not tokens[0].startswith("--"):
                    include = tokens[0][2:] or (tokens[1] if len(tokens) == 2 else "")
                    expected = 1 if tokens[0][2:] else 2
                else:
                    raise ValueError(f"unsupported dependency option in {path}: {tokens[0]}")
                if len(tokens) != expected or not include:
                    raise ValueError(f"requirements include has no unambiguous path in {path}")
                child = _relative(include, parent=posixpath.dirname(path))
                requirements(child, (*ancestors, path), is_constraint)

        selected_requirements = ("requirements.txt" if "requirements.txt" in rows else None
                                 ) if requirements_txt is _AUTO_REQUIREMENTS else requirements_txt
        if selected_requirements is not None:
            requirements(selected_requirements)
        dynamic_dependencies = False
        pyproject_packages: list[str] = []
        if "pyproject.toml" in rows:
            dependency_paths.add("pyproject.toml")
            project = tomllib.loads(read("pyproject.toml")["content"]).get("project", {})
            if not isinstance(project, dict):
                raise ValueError("pyproject.toml project must be a table")
            dependencies = project.get("dependencies", [])
            if not isinstance(dependencies, list) or any(not isinstance(item, str) or not item.strip() for item in dependencies):
                raise ValueError("pyproject.toml dependencies must be nonempty strings")
            pyproject_packages.extend(dependencies)
            dynamic = project.get("dynamic", [])
            if not isinstance(dynamic, list) or any(not isinstance(item, str) for item in dynamic):
                raise ValueError("pyproject.toml dynamic must be an array of strings")
            dynamic_dependencies = "dependencies" in dynamic

        install = {"present": "install.py" in rows, "git_blob": None, "sha256": None, "run": False}
        if install["present"]:
            record = read("install.py")
            install.update(git_blob=record["git_blob"], sha256=record["sha256"])
        class_names: set[str] = set()
        class_files: list[dict[str, Any]] = []
        incomplete_class_files: list[str] = []
        for path, row in sorted(rows.items()):
            if not path.endswith(".py") or row["mode"] not in {"100644", "100755"}:
                continue
            try:
                module = ast.parse(read(path)["content"], filename=path)
            except (ValueError, SyntaxError):
                incomplete_class_files.append(path)
                continue
            names: set[str] = set()
            for statement in module.body:
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target] if isinstance(statement, ast.AnnAssign) else []
                if not any(isinstance(target, ast.Name) and target.id == "NODE_CLASS_MAPPINGS" for target in targets):
                    continue
                value = statement.value
                if not isinstance(value, ast.Dict) or any(not isinstance(key, ast.Constant) or not isinstance(key.value, str) for key in value.keys):
                    incomplete_class_files.append(path)
                    continue
                names.update(key.value for key in value.keys)
            if names:
                class_names.update(names)
                class_files.append({"path": path, "git_blob": row["git_blob"], "classes": sorted(names)})
        submodules = [{"path": path, "commit": row["git_blob"]} for path, row in sorted(rows.items()) if row["kind"] == "commit"]
        return {
            "repo": repo, "commit": commit, "tree": tree,
            "files": [cache[path] for path in sorted(dependency_paths)],
            "recipe": {"requirements_txt": selected_requirements, "pip_no_deps": []},
            "packages": packages, "constraints": constraints, "pyproject_packages": pyproject_packages,
            "dynamic_dependencies": dynamic_dependencies, "install_py": install,
            "class_names": sorted(class_names), "class_files": class_files,
            "incomplete_class_files": sorted(set(incomplete_class_files)),
            "submodules": submodules,
            "checkout_bytes": None if submodules else sum(row["size"] for row in rows.values()),
        }
