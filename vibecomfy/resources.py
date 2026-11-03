"""Authoritative filesystem resources for checkouts and installed packages.

Runtime data is kept in its canonical checkout locations and relocated inside
the package by the wheel builder. Select a single layout for the whole corpus;
an incomplete installed package must never borrow missing files from a checkout.
"""

from __future__ import annotations

import json
from pathlib import Path
import tomllib
from typing import Any

from vibecomfy.errors import CheckoutRequiredError, ShippedResourceMissingError
from vibecomfy.utils import find_repo_root


_PATHS = {
    "ready_templates": ("ready_templates", "ready_templates"),
    "template_index": ("template_index.json", "template_index.json"),
    "coverage_manifest": (
        "ready_templates/sources/manifests/coverage.json",
        "ready_templates/sources/manifests/coverage.json",
    ),
    "custom_nodes_lock": ("custom_nodes.lock", "custom_nodes.lock"),
    "strict_ready_exceptions": (
        "porting/strict_ready_exceptions.json",
        "docs/templates/strict_ready_exceptions.json",
    ),
    "comfy_metadata": ("comfy_metadata.json", "vibecomfy/comfy_metadata.json"),
}
_INSTALLED_MARKERS = (
    "ready_templates",
    "template_index.json",
    "custom_nodes.lock",
    "porting/strict_ready_exceptions.json",
)


def _selected_layout() -> tuple[str, Path]:
    package = Path(__file__).resolve().parent
    # Metadata and schemas already live in the package in a checkout and cannot
    # distinguish an installed distribution from editable source imports.
    if any(
        (package / marker).exists() or (package / marker).is_symlink()
        for marker in _INSTALLED_MARKERS
    ):
        return "installed", package
    try:
        return "checkout", find_repo_root()
    except CheckoutRequiredError:
        return "installed", package


def layout() -> str:
    """Return ``installed`` or ``checkout`` for this package's runtime data."""
    return _selected_layout()[0]


def _layout_root() -> Path:
    """Return the containing root for resource provenance containment checks."""
    return _selected_layout()[1]


def _checkout_root() -> Path:
    """Retain checkout-only helper compatibility without mapping runtime data."""
    return find_repo_root()


def _resource_location(name: str) -> Path:
    selected, root = _selected_layout()
    installed, checkout = _PATHS[name]
    return root / (installed if selected == "installed" else checkout)


def _is_resource_path(name: str, path: Path) -> bool:
    """Identify explicit shipped paths without weakening external-file APIs."""
    return path.resolve() == _resource_location(name).resolve()


def _resource_path(name: str) -> Path:
    path = _resource_location(name)
    exists = path.is_dir() if name == "ready_templates" else path.is_file()
    if not exists:
        raise ShippedResourceMissingError(name, path)
    return path


def _read_json(name: str) -> dict[str, Any]:
    path = _resource_path(name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ShippedResourceMissingError(name, path) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Shipped VibeComfy resource {name!r} at {path} must contain a JSON object")
    return payload


def ready_templates_root() -> Path:
    """Return the complete, durable built-in template tree."""
    return _resource_path("ready_templates")


def template_index() -> dict[str, Any]:
    return _read_json("template_index")


def coverage_manifest() -> dict[str, Any]:
    return _read_json("coverage_manifest")


def custom_nodes_lock() -> dict[str, Any]:
    path = _resource_path("custom_nodes_lock")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ShippedResourceMissingError("custom_nodes_lock", path) from exc


def strict_ready_exceptions() -> dict[str, Any]:
    return _read_json("strict_ready_exceptions")


def comfy_metadata() -> dict[str, Any]:
    return _read_json("comfy_metadata")


__all__ = [
    "ready_templates_root",
    "template_index",
    "coverage_manifest",
    "custom_nodes_lock",
    "strict_ready_exceptions",
    "comfy_metadata",
    "layout",
]
