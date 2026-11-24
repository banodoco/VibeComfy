"""CPU-only recorded git/pip target for recipe installation tests."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


class RecipeRunner:
    """Create a temporary checkout and answer only the allowed git/pip calls."""

    def __init__(self, *, head="0" * 40, files=None, origin="https://example.test/recipe-pack.git"):
        self.head = head
        self.origin = origin
        self.files = files if files is not None else {"deps/requirements.txt": "regular-dependency==1\n"}
        self.calls = []
        self.head_reads = []
        self.cwds = []
        self.constraints = []
        self.reports = []
        self.fail_dry_run = False
        self.fail_install = False
        self.ignore_checkout = False
        self.after_install = None

    def checkout_tree(self, path):
        path.mkdir(parents=True, exist_ok=True)
        (path / ".git").mkdir(exist_ok=True)
        for name, contents in self.files.items():
            target = path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(contents, Path):
                target.symlink_to(contents)
            else:
                target.write_text(contents, encoding="utf-8")
        # Running this repository's script would leave a visible witness.
        (path / "install.py").write_text(
            "from pathlib import Path\nPath(__file__).with_name('SCRIPT_EXECUTED').touch()\n",
            encoding="utf-8",
        )

    def __call__(self, args, *, check, capture_output, text, cwd=None):
        call = list(args)
        self.calls.append(call)
        self.cwds.append(cwd)
        assert check and capture_output and text
        output = ""
        if call[:2] == ["git", "clone"]:
            self.checkout_tree(Path(call[-1]))
            self.origin = call[-2]
        elif call[:2] == ["git", "-C"]:
            operation = call[3]
            if operation == "checkout":
                if not self.ignore_checkout and call[4] != "HEAD":
                    self.head = call[4]
            elif operation == "rev-parse":
                output = self.head + "\n"
                self.head_reads.append((call, output.strip()))
            elif call[3:] == ["config", "--get", "remote.origin.url"]:
                output = self.origin + "\n"
            elif operation not in {"fetch", "status"}:
                raise AssertionError(f"Unexpected git operation: {call}")
        elif call[1:4] == ["-m", "pip", "install"]:
            if "--help" in call:
                output = "--dry-run --report"
            else:
                constraint = Path(call[call.index("--constraint") + 1])
                self.constraints.append((constraint, constraint.read_text()))
                if "--dry-run" in call:
                    if self.fail_dry_run:
                        raise subprocess.CalledProcessError(1, call, stderr="recorded dry-run failure")
                    report = self.reports.pop(0) if self.reports else {"install": []}
                    if report is not None:
                        Path(call[call.index("--report") + 1]).write_text(json.dumps(report))
                else:
                    if self.fail_install:
                        raise subprocess.CalledProcessError(1, call, stderr="recorded install failure")
                    if self.after_install is not None:
                        self.after_install()
        else:
            raise AssertionError(f"Uncontrolled subprocess: {call}")
        return subprocess.CompletedProcess(call, 0, stdout=output, stderr="")

    @property
    def pip_calls(self):
        return [call for call in self.calls if call[1:4] == ["-m", "pip", "install"] and "--help" not in call]

    @property
    def installs(self):
        return [call for call in self.pip_calls if "--dry-run" not in call]
