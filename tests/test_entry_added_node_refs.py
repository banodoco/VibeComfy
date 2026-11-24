from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests._cli_helpers import _write_port_node_index, _write_port_workflow
from vibecomfy.custom_node_refs import resolve_added_node_refs
from vibecomfy.entries import import_as_entry
from vibecomfy.security.provenance import Provenance
from vibecomfy.workflow_bundle import load_bundle

URL = "https://github.com/ethanfel/ComfyUI-SAM-Audio"
PIN = "3cfbd03da3019c7252ba13efd5694b1b2ff487e5"
TAG = "a" * 40


@pytest.mark.parametrize(("suffix", "reply", "expected"), [
    ("", f"{PIN}\tHEAD\n", PIN),
    ("@main", f"{PIN}\trefs/heads/main\n", PIN),
    ("@refs/tags/v1", f"{TAG}\trefs/tags/v1\n{PIN}\trefs/tags/v1^{{}}\n", PIN),
])
def test_resolve_add_from_recorded_remote(monkeypatch, suffix, reply, expected):
    calls = []

    def ls_remote(argv, **kwargs):
        calls.append(argv)
        assert argv[:5] == ["git", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always"]
        assert argv[5:9] == ["ls-remote", "--exit-code", "--", URL]
        assert kwargs["check"] and kwargs["timeout"] == 30
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        return subprocess.CompletedProcess(argv, 0, reply, "")

    monkeypatch.setattr(subprocess, "run", ls_remote)
    assert resolve_added_node_refs([URL + suffix]) == [
        {"slug": "ComfyUI-SAM-Audio", "source": "git", "url": URL, "commit": expected}
    ]
    assert len(calls) == 1


@pytest.mark.parametrize("reply", [
    "",
    "deadbeef\trefs/heads/main\n",
    f"{PIN}\trefs/heads/main\n{TAG}\trefs/tags/main\n",
    f"{PIN}\trefs/heads/not-main\n",
])
def test_add_fails_closed_on_missing_ambiguous_or_malformed_ref(monkeypatch, reply):
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs:
                        subprocess.CompletedProcess(argv, 0, reply, ""))
    with pytest.raises(ValueError):
        resolve_added_node_refs([URL + "@main"])


@pytest.mark.parametrize("bad", ["file:///tmp/pack", "ext::cmd", "https://user@github.com/owner/pack",
                                 URL + "@*", URL + "@", URL + "?query=1"])
def test_add_rejects_unsafe_source_before_git(monkeypatch, bad):
    def unexpected(*args, **kwargs):
        pytest.fail("unsafe declaration reached git")
    monkeypatch.setattr(subprocess, "run", unexpected)
    with pytest.raises(ValueError):
        resolve_added_node_refs([bad])


def test_add_round_trips_in_canonical_entry_without_second_lookup(tmp_path, monkeypatch):
    _write_port_node_index(tmp_path)
    monkeypatch.chdir(tmp_path)
    source = _write_port_workflow(tmp_path)
    original_bytes = source.read_bytes()
    calls = []

    def ls_remote(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, f"{PIN}\tHEAD\n", "")

    # Patch only git resolution; use the real conversion, canonical writer,
    # saved manifest and bundle loader for both imports.
    import vibecomfy.custom_node_refs as custom_refs
    monkeypatch.setattr(custom_refs.subprocess, "run", ls_remote)
    entry = import_as_entry(source, "added", tmp_path / "entries", add=[URL])
    folder = Path(entry["bundle"])
    wf = load_bundle(folder / "workflow.py", trust=Provenance.USER_CONFIRMED).workflow
    expected = {"slug": "ComfyUI-SAM-Audio", "source": "git", "url": URL, "commit": PIN}
    assert expected in wf.requirements.custom_node_refs
    assert (folder / "source.json").read_bytes() == original_bytes
    replay = import_as_entry(folder, "replay", tmp_path / "entries")
    restored = load_bundle(Path(replay["bundle"]) / "workflow.py", trust=Provenance.USER_CONFIRMED).workflow
    assert expected in restored.requirements.custom_node_refs
    assert len(calls) == 1
    assert resolve_added_node_refs([URL + "@" + PIN]) == [expected]
    assert len(calls) == 1
