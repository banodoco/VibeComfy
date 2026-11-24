"""Command and returned-HEAD witness shared by staged checkout tests."""
from pathlib import Path


def assert_staged_clone(calls, root, repo):
    [clone] = [call for call in calls if call[:2] == ["git", "clone"] and call[-2] == repo]
    staged = Path(clone[-1])
    assert staged.is_absolute()
    assert not staged.is_relative_to(root.resolve())
    assert staged.parent.parent == root.resolve().parent
    assert clone == ["git", "clone", "--no-checkout", "--", repo, str(staged)]
    return clone, staged


def assert_staged_restore(runner, root, name, repo, pin, *, fetch=True):
    calls = runner.calls
    clone, staged = assert_staged_clone(calls, root, repo)
    live = root / name
    git = ["git", "-C", str(staged)]
    start = calls.index(clone)
    head_call = [*git, "rev-parse", "HEAD"]
    before_publish = [
        clone,
        [*git, "config", "--get", "remote.origin.url"],
    ]
    if fetch:
        before_publish.append([*git, "fetch", "--", repo, pin])
    before_publish.extend([
        [*git, "checkout", pin if fetch else "HEAD"],
        head_call,
        [*git, "config", "--get", "remote.origin.url"],
    ])
    assert calls[start:start + len(before_publish)] == before_publish
    # Record the actual stdout from the staged rev-parse, not just argv.
    assert [value for command, value in runner.head_reads if command == head_call] == [pin]
    assert ["git", "-C", str(live), "rev-parse", "HEAD"] in calls[start + len(before_publish):]
    assert live.is_dir()
    assert not staged.exists()
