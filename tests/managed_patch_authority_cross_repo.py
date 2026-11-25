"""Explicit offline cross-repo proof; requires the reviewed Agent checkout/env.

Run from VibeComfy with the Agent's Python environment and Agent source on
PYTHONPATH: python -m pytest tests/managed_patch_authority_cross_repo.py
This file is intentionally selected explicitly, so the standalone VibeComfy
suite does not require Astrid Agent. Missing Agent is a failure here, not a skip.
"""
from importlib.resources import files
import subprocess

import pytest

from tests.fixtures.node_recipe_runner import RecipeRunner
from tests.test_node_recipe_install import target  # noqa: F401
from tests.test_managed_patch_authority import MANAGED_LOCKS, assert_admission, run_restore
from vibecomfy.node_packs import read_lockfile


@pytest.fixture(params=MANAGED_LOCKS)
def managed_lock(target, request):
    from astrid.core.generation.engine_recipe import load_recipe
    from astrid.core.generation.managed_preparation import _write_managed_nodes_lock

    name = request.param
    recipe = load_recipe("comfyui", "linux-x86_64-cu130")
    source = next(s for s in recipe.sources if s.relative_path.endswith("/custom_nodes/" + name))
    patches = [p for p in recipe.source_patches if p.source == source.name]
    assert patches
    lock = target[1]
    _write_managed_nodes_lock(lock, [
        {"repo": source.pin.repository, "commit": source.pin.revision},
    ], recipe)
    assert lock.read_text(encoding="utf-8") == MANAGED_LOCKS[name]
    return lock, patches


def test_real_agent_lock_admission(managed_lock):
    lock, _ = managed_lock
    assert_admission(lock)


def test_real_agent_lock_restores_patched_checkout(target, managed_lock, monkeypatch, capsys):
    lock, patches = managed_lock
    [entry] = read_lockfile(lock)
    checkout = target[0] / entry.name
    runner = RecipeRunner(head=entry.git_commit_sha, origin=entry.url, files={})
    runner.checkout_tree(checkout)
    payloads = {patch.path: files("astrid").joinpath(patch.replacement).read_bytes() for patch in patches}
    for path, payload in payloads.items():
        dest = checkout / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)

    def recorded_runner(args, **kwargs):
        result = runner(args, **kwargs)
        if list(args) == ["git", "-C", str(checkout), "status", "--porcelain"]:
            return subprocess.CompletedProcess(args, 0, stdout="".join(
                f" M {path}\n" for path in payloads
            ), stderr="")
        return result

    # Like the managed recipe, the checkout already contains the replacement
    # bytes. Only git/pip transport is recorded, including the dirty status.
    assert run_restore(target, monkeypatch, recorded_runner) == 0
    assert f"declared patches verified: {len(payloads)}" in capsys.readouterr().out
    assert not any(call[:2] == ["git", "clone"] for call in runner.calls)
    assert {path: (checkout / path).read_bytes() for path in payloads} == payloads
    [saved] = read_lockfile(lock)
    assert saved.patches == entry.patches
    assert saved.git_commit_sha == entry.git_commit_sha
