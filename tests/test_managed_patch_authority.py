"""RS1B.1: shipped review authority, not the target lock, admits managed patches.

These literal target locks are the expected Agent writer output for the reviewed
RunPod recipe at d288aca1ecbbc513292559ce40867140b8aa8a64. The explicit
managed_patch_authority_cross_repo.py proof checks them against the live writer.
"""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from tests.fixtures.node_recipe_runner import RecipeRunner
from tests.fixtures.node_restore_checkout import assert_staged_restore
from tests.test_node_recipe_install import target  # noqa: F401
from vibecomfy.commands import nodes
from vibecomfy.node_approvals import CodeConsentRequired, approval_record
from vibecomfy.node_packs import _install as install
from vibecomfy.node_packs import read_lockfile, write_lockfile


MANAGED_LOCKS = {
    "ComfyUI-Whisper": (
        '[nodepacks."ComfyUI-Whisper"]\n'
        'url = "https://github.com/yuvraj108c/ComfyUI-Whisper.git"\n'
        'commit = "006a709848259ed3d69e2f9fcfd7a75f6c860ddd"\n'
        'patches = [{ path = "apply_whisper.py", sha256 = "459c53daf4217671f2f0bb722e9e22857198ab77314a788b2712572ad16bc4ee" }]\n'
    ),
    "ComfyUI-QwenTTS": (
        '[nodepacks."ComfyUI-QwenTTS"]\n'
        'url = "https://github.com/1038lab/ComfyUI-QwenTTS.git"\n'
        'commit = "d8122a8ba835b65fd65c113d2b273b1ad1579293"\n'
        'patches = [{ path = "qwen_tts/core/models/modeling_qwen3_tts.py", '
        'sha256 = "843101a8dc83a00430a2dfc644b149dbbf523396be30d2fe71ac7c8680da47b1" }, '
        '{ path = "qwen_tts/core/tokenizer_12hz/modeling_qwen3_tts_tokenizer_v2.py", '
        'sha256 = "2e19371f13fbf1317a7e112357e9ba30c29ff9f5eb6843f485bb98b25ff23706" }, '
        '{ path = "qwen_tts/core/models/configuration_qwen3_tts.py", '
        'sha256 = "7365d5a295b610a442e1f7feebba97e89433013bb59ec9da8c2d2b5c00aceb92" }]\n'
    ),
}


def approval(entry):
    return approval_record({
        "repo": entry.url, "commit": entry.git_commit_sha,
        "requirements_txt": entry.requirements_txt, "pip_no_deps": list(entry.pip_no_deps),
    }, placement_class="runpod")


def assert_admission(lock):
    [entry] = read_lockfile(lock)
    # No explicit records: the exact shipped source and recipe must admit.
    assert install.validate_restore_approvals(
        [entry], [], placement_class="runpod", lockfile_path=lock,
    ) == [approval(entry)]


def run_restore(target, monkeypatch, runner, *, approvals=None):
    root, lock, _ = target
    restore = install.restore_pack
    # Only transport is recorded; use the actual CLI, admission and restore.
    monkeypatch.setattr(nodes.node_packs_install, "restore_pack", lambda entry, **kw: restore(
        entry, install_root=root, runner=runner, **kw,
    ))
    return nodes._cmd_nodes_restore(SimpleNamespace(
        lockfile=str(lock), approvals=approvals, placement_class="runpod",
    ))


@pytest.mark.parametrize("name", MANAGED_LOCKS)
def test_managed_recipe_patch_admission(target, name):
    lock = target[1]
    lock.write_text(MANAGED_LOCKS[name], encoding="utf-8")
    assert_admission(lock)


@pytest.mark.parametrize("name", MANAGED_LOCKS)
def test_managed_recipe_patch_restore(target, monkeypatch, name):
    root, lock, _ = target
    lock.write_text(MANAGED_LOCKS[name], encoding="utf-8")
    [entry] = read_lockfile(lock)
    runner = RecipeRunner()
    assert run_restore(target, monkeypatch, runner) == 0
    assert_staged_restore(runner, root, name, entry.url, entry.git_commit_sha)
    [saved] = read_lockfile(lock)
    assert saved.patches == entry.patches
    assert saved.git_commit_sha == entry.git_commit_sha


@pytest.mark.parametrize("name,mutation", [
    ("ComfyUI-Whisper", "different_hash"),
    ("ComfyUI-QwenTTS", "different_hash"),
    ("ComfyUI-Whisper", "added_path"),
    ("ComfyUI-QwenTTS", "added_path"),
    ("ComfyUI-VideoHelperSuite", "added_path"),
])
def test_target_lock_cannot_authorize_patches(target, monkeypatch, capsys, name, mutation):
    root, lock, _ = target
    if name in MANAGED_LOCKS:
        lock.write_text(MANAGED_LOCKS[name], encoding="utf-8")
        [entry] = read_lockfile(lock)
        patch = entry.patches[0]
    else:
        entry = next(row for row in read_lockfile() if row.name == name)
        assert not entry.patches
        lock.write_text(MANAGED_LOCKS["ComfyUI-Whisper"], encoding="utf-8")
        patch = read_lockfile(lock)[0].patches[0]
    if mutation == "different_hash":
        entry = replace(entry, patches=(replace(patch, sha256="0" * 64), *entry.patches[1:]))
    else:
        entry = replace(entry, patches=(*entry.patches, replace(patch, path="unreviewed.py")))
    write_lockfile([entry], lock)
    records = [approval(entry)]
    # A valid consent hash for the pin and recipe is not patch authority.
    with pytest.raises(CodeConsentRequired, match="differs from the trusted shipped recipe"):
        install.validate_restore_approvals(
            read_lockfile(lock), records, placement_class="runpod", lockfile_path=lock,
        )
    approval_path = lock.with_suffix(".approvals.json")
    approval_path.write_text(json.dumps(records), encoding="utf-8")
    before = lock.read_bytes()
    runner = RecipeRunner()
    assert run_restore(target, monkeypatch, runner, approvals=str(approval_path)) == 1
    assert "differs from the trusted shipped recipe" in capsys.readouterr().err
    assert runner.calls == []
    assert lock.read_bytes() == before
    assert not root.exists()
