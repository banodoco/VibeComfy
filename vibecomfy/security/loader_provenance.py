"""S4 Step 10 — provenance classifier for `exec_module` loader call sites.

Used by ``vibecomfy/scratchpad_loader.py`` and ``vibecomfy/registry/ready.py``
to decide, *before* ``spec.loader.exec_module(...)`` fires, whether the source
file lives under a trusted in-repo directory (``out/scratchpads/`` or the
built-in ``ready_templates/`` directory) or is an external, attacker-controlled
path.

Classification uses ``Path.resolve()`` + ``pathlib.Path.is_relative_to``
against the resolved trusted-directory paths. This defeats traversal
(``out/scratchpads/../../tmp/evil.py``) and symlink-escape attacks that a
prefix-string match would miss.
"""

from __future__ import annotations

from pathlib import Path

from vibecomfy import resources
from vibecomfy.errors import CheckoutRequiredError
from vibecomfy.security.provenance import Provenance


def _trusted_roots() -> list[Path]:
    """Resolved trusted-directory roots for exec_module loaders.

    Trust checkout scratchpads and ready templates, or the installed package's
    ready templates when there is no checkout. Resolve roots before comparison
    to catch traversal and symlink escapes.
    """
    roots: list[Path] = []
    # Resolve the required resource before considering trust. A missing shipped
    # corpus is an installation error, rather than an empty set of trusted data.
    ready_root = resources.ready_templates_root().resolve()
    container = resources._layout_root().resolve()
    if ready_root.is_relative_to(container):
        roots.append(ready_root)

    if resources.layout() != "checkout":
        return roots
    try:
        repo = resources._checkout_root()
    except CheckoutRequiredError:
        return roots

    # Only actual checkout scratchpads receive this additional trust. Resolve
    # and contain the root too, so a symlink cannot widen its authority.
    try:
        scratchpads = (repo / "out" / "scratchpads").resolve()
        if scratchpads.is_relative_to(repo.resolve()):
            roots.append(scratchpads)
    except OSError:
        pass
    return roots


def _provenance_for_path(path: Path) -> Provenance:
    """Classify an exec_module source file path as trusted or untrusted.

    Returns ``"agent_authored"`` if ``path.resolve()`` is under either of the
    trusted roots, otherwise ``"untrusted_source"``. Never uses prefix-string
    matching.
    """
    try:
        resolved = Path(path).resolve()
    except OSError:
        return "untrusted_source"
    for root in _trusted_roots():
        try:
            if resolved.is_relative_to(root):
                return "agent_authored"
        except (ValueError, OSError):
            continue
    return "untrusted_source"


__all__ = ["_provenance_for_path"]
