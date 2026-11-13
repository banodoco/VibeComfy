"""Read immutable model records from their ready-template declarations.

This is an offline projection, not a second model catalog. Source facts stay
in the template's ModelAsset (or generated requirements.models record).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from vibecomfy.registry.ready import repo_ready_template_discovery, resolve_ready_template
from vibecomfy.registry.static_contract import extract_ready_template_contract


@dataclass(frozen=True)
class ModelRecord:
    repository: str
    revision: str
    path: str
    sha256: str
    bytes: int
    destination: str

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repository}/resolve/{self.revision}/{self.path}"


def ready_model_records(template_id: str) -> tuple[ModelRecord, ...]:
    """Read exactly one repository template without importing its Python code.

    Unresolved local assets are not downloads. A downloadable asset missing
    any provenance or integrity fact fails rather than receiving a default.
    """
    template = resolve_ready_template(template_id, repo_ready_template_discovery())
    records = []
    destinations = set()
    for asset in extract_ready_template_contract(template.path)["model_assets"]:
        url = asset.get("url")
        if url is None:
            continue
        parsed = urlsplit(url)
        parts = parsed.path.strip("/").split("/")
        revision = asset.get("hf_revision")
        digest = asset.get("sha256")
        size = asset.get("size_bytes")
        if (parsed.scheme != "https" or parsed.netloc != "huggingface.co"
                or parsed.query or parsed.fragment or len(parts) < 5
                or parts[2] != "resolve"
                or not re.fullmatch(r"[0-9a-f]{40}", revision or "")
                or parts[3] != revision
                or not re.fullmatch(r"[0-9a-f]{64}", digest or "")
                or type(size) is not int or size <= 0):
            raise ValueError(f"incomplete immutable model record: {template_id}: {asset.get('name')}")
        path = "/".join(parts[4:])
        destination = str(PurePosixPath(asset["subdir"]) / asset["name"])
        for value in (path, destination):
            if (PurePosixPath(value).is_absolute() or "\\" in value
                    or any(part in {"", ".", ".."} for part in value.split("/"))):
                raise ValueError(f"unsafe model record path: {value!r}")
        if asset.get("target_path") is not None or destination in destinations:
            raise ValueError(f"ambiguous model record destination: {template_id}: {destination}")
        destinations.add(destination)
        records.append(ModelRecord("/".join(parts[:2]), revision, path, digest, size, destination))
    return tuple(records)
