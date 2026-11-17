"""Process-local prepared workflow authority.

Preparation is deliberately separate from decoded ApprovedProjectionRecord values.
The session owner supplies identities from admitted, immutable source and target
snapshots. A new source, authority, installation or target generation has a new
context; a serialized handle never recreates a session's authority.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from vibecomfy.testing.canonical import canonical_digest
from vibecomfy.workflow_bundle import WorkflowBundleError


class PreparedWorkflowUnavailable(WorkflowBundleError):
    """This workflow needs the ordinary full preparation path."""


@dataclass(frozen=True, slots=True)
class PreparedWorkflowContext:
    """Identities supplied by the trusted pack/session admission owner."""

    source_identity: str
    capability_identity: str
    authority_scope: str
    settings_generation: str
    installation_generation: str
    target_identity: str
    target_generation: str
    schema_digest: str
    compiler_identity: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if type(value) is not str or not value.strip():
                raise WorkflowBundleError(f"prepared workflow {name} must be nonblank")

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))


def _value_shape(value: Any, *, depth: int = 0) -> Any:
    """A bounded JSON type/shape, with no schema, range or model preflight."""
    if depth > 32:
        raise WorkflowBundleError("prepared input exceeds the transport nesting bound")
    if value is None:
        return "null"
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is float:
        if not math.isfinite(value):
            raise WorkflowBundleError("prepared input must be finite")
        return "float"
    if type(value) is str:
        return "str"
    if type(value) in (list, tuple):
        if len(value) > 4096:
            raise WorkflowBundleError("prepared input exceeds the transport collection bound")
        return ("array", tuple(_value_shape(item, depth=depth + 1) for item in value))
    if isinstance(value, Mapping):
        if len(value) > 4096 or any(type(key) is not str for key in value):
            raise WorkflowBundleError("prepared input requires bounded string object keys")
        return (
            "object",
            tuple((key, _value_shape(value[key], depth=depth + 1)) for key in sorted(value)),
        )
    raise WorkflowBundleError(f"prepared input is not JSON-safe: {type(value).__name__}")
