"""Command witness shared by restore tests; no product-side test seam."""
from pathlib import Path


def assert_staged_restore(calls, root, name, repo, pin):
    [clone] = [call for call in calls if call[:2] == ["git", "clone"] and call[-2] == repo]
    staged = Path(clone[-1])
    live = root / name
    assert staged.is_absolute()
    assert not staged.is_relative_to(root.resolve())
    assert staged.parent.parent == root.resolve().parent
    assert clone == ["git", "clone", "--no-checkout", "--", repo, str(staged)]
    git = ["git", "-C", str(staged)]
    start = calls.index(clone)
    assert calls[start:start + 6] == [
        clone,
        [*git, "config", "--get", "remote.origin.url"],
        [*git, "fetch", "--", repo, pin],
        [*git, "checkout", pin],
        [*git, "rev-parse", "HEAD"],
        [*git, "config", "--get", "remote.origin.url"],
    ]
    assert ["git", "-C", str(live), "rev-parse", "HEAD"] in calls[start + 6:]
    assert live.is_dir()
    assert not staged.exists()
