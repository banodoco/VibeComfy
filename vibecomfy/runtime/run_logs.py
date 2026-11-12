"""Best-effort declarations of the files belonging to a run."""
from __future__ import annotations

import json
from pathlib import Path

from vibecomfy.utils import atomic_write_json

SCHEMA = "run-logs.v1"
DECLARATION_NAME = "logs.json"


def declare_log(run_dir: Path, name: str, role: str, path: str | Path, *, start: int = 0) -> None:
    """Add or replace a log declaration without affecting the run on failure."""
    try:
        root = Path(run_dir)
        source = Path(path)
        resolved_root = root.resolve()
        resolved_source = (root / source).resolve() if not source.is_absolute() else source.resolve()
        try:
            stored_path = resolved_source.relative_to(resolved_root).as_posix()
        except ValueError:
            stored_path = str(resolved_source)

        declaration_path = root / DECLARATION_NAME
        logs: list[dict[str, object]] = []
        children: list[str] = []
        try:
            existing = json.loads(declaration_path.read_text(encoding="utf-8"))
            if existing.get("schema") == SCHEMA and isinstance(existing.get("logs"), list):
                logs = [item for item in existing["logs"] if isinstance(item, dict) and item.get("name") != name]
                if isinstance(existing.get("children"), list):
                    children = existing["children"]
        except (OSError, ValueError, AttributeError):
            pass
        logs.append({"name": name, "role": role, "path": stored_path, "start": start, "end": None})
        atomic_write_json(declaration_path, {"schema": SCHEMA, "logs": logs, "children": children})
    except Exception:
        return
