"""Presentation records shared by bundle readers and UI emitters.

This module uses only the standard library so reading a bundle never needs to
initialize the emitter package, ComfyUI nodes, or native numerical libraries.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PresentationGraphRecords:
    """Detached structural records crossing the LiteGraph presentation door."""

    nodes: Any
    links: Any
    groups: Any
    groups_present: bool


def capture_presentation_graph_records(candidate: Mapping[str, Any]) -> PresentationGraphRecords:
    """Detach the three graph-shaped presentation records from *candidate*.

    This is deliberately a shape-neutral door.  The bundle boundary retains
    its context-specific validation: UI envelopes require a node list while
    strict sidecars require a UID-keyed node mapping.
    """
    return PresentationGraphRecords(
        nodes=deepcopy(candidate.get("nodes")),
        links=deepcopy(candidate.get("links")),
        groups=deepcopy(candidate.get("groups")),
        groups_present="groups" in candidate,
    )
