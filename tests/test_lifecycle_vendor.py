"""Offline contract for the lifecycle wheel used by the RunPod extras."""
import ast
import hashlib
import json
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version


ROOT = Path(__file__).resolve().parents[1]


def test_lifecycle_candidate_wheel_contract():
    candidate = json.loads((ROOT / "candidate-dependencies.json").read_text())["runpod-lifecycle"]
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    wheel = ROOT / candidate["artifact"]
    assert candidate["revision"] == "a67f2fe0f6fa497de152163e7d832e357191bf92"
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == candidate["wheel"]
    assert project["tool"]["uv"]["sources"]["runpod-lifecycle"]["path"] == candidate["artifact"]
    with zipfile.ZipFile(wheel) as archive:
        metadata_path = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(archive.read(metadata_path).decode())
        assert metadata["Version"] == candidate["version"]
        api = ast.parse(archive.read("runpod_lifecycle/api.py"))
    for extra in ("runpod-local", "runpod-launch"):
        requirements = [Requirement(value) for value in project["project"]["optional-dependencies"][extra]]
        requirement = next(item for item in requirements if item.name == "runpod-lifecycle")
        assert Version(candidate["version"]) in requirement.specifier
    pods_url = next(node.value.value for node in api.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "PODS_URL" for target in node.targets))
    assert pods_url == "https://api.runpod.io/v2/pods"
    from runpod_lifecycle.api import PODS_URL

    assert PODS_URL == pods_url
