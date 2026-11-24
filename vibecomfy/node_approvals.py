"""Canonical node-code approvals shared by Astrid and target restoration.

Records confirm the exact source, recipe and placement shown for consent. They
are not signatures or secrets; only the caller obtaining consent may issue them.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict

PlacementClass = Literal["local", "attached", "runpod"]
PLACEMENT_CLASSES = frozenset({"local", "attached", "runpod"})
_CONTEXT = b"astrid.node-code-approval.v1\0"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class NodeIdentity(TypedDict):
    repo: str
    commit: str


class NodeApproval(TypedDict):
    identity: NodeIdentity
    recipe_sha256: str
    approval_sha256: str
    placement_class: PlacementClass


def _identity(value: Any) -> NodeIdentity:
    if not isinstance(value, Mapping) or set(value) != {"repo", "commit"}:
        raise ValueError("node approval identity must contain repo and commit")
    repo, commit = value["repo"], value["commit"]
    if (not isinstance(repo, str) or not repo.strip() or repo != repo.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in repo)):
        raise ValueError("node approval repo must be a nonempty source identity")
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("node approval commit must be a full lowercase 40-hex commit")
    return {"repo": repo, "commit": commit}


def _approval_hash(identity: NodeIdentity, recipe_hash: str, placement_class: str) -> str:
    payload = {"identity": identity, "recipe_sha256": recipe_hash, "placement_class": placement_class}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(_CONTEXT + encoded).hexdigest()


def approval_record(node: Mapping[str, Any], *, placement_class: PlacementClass) -> NodeApproval:
    """Describe one manifest node; callers must obtain consent before saving it."""
    from vibecomfy.node_recipes import RECIPE_FIELDS, recipe_sha256

    if (not isinstance(node, Mapping) or not {"repo", "commit"} <= set(node)
            or set(node) - ({"repo", "commit"} | RECIPE_FIELDS)):
        raise ValueError("approval requires the closed extra.nodes shape")
    identity = _identity({key: node[key] for key in ("repo", "commit")})
    if not isinstance(placement_class, str) or placement_class not in PLACEMENT_CLASSES:
        raise ValueError("approval needs a resolved placement class: local, attached or runpod")
    recipe_hash = recipe_sha256({key: node[key] for key in RECIPE_FIELDS if key in node})
    return {"identity": identity, "recipe_sha256": recipe_hash,
            "approval_sha256": _approval_hash(identity, recipe_hash, placement_class),
            "placement_class": placement_class}


def validate_approval_record(record: Any) -> NodeApproval:
    """Validate/copy stored data; this proves consistency, never authenticity."""
    if not isinstance(record, Mapping) or set(record) != {"identity", "recipe_sha256", "approval_sha256", "placement_class"}:
        raise ValueError("invalid node approval record shape")
    identity = _identity(record["identity"])
    placement = record["placement_class"]
    if not isinstance(placement, str) or placement not in PLACEMENT_CLASSES:
        raise ValueError("invalid approval placement class")
    recipe_hash, approval_hash = record["recipe_sha256"], record["approval_sha256"]
    if any(not isinstance(value, str) or _SHA256.fullmatch(value) is None for value in (recipe_hash, approval_hash)):
        raise ValueError("approval hashes must be lowercase SHA-256 values")
    expected = _approval_hash(identity, recipe_hash, placement)
    if not hmac.compare_digest(approval_hash, expected):
        raise ValueError("node approval record does not match its identity, recipe and placement")
    return {"identity": identity, "recipe_sha256": recipe_hash, "approval_sha256": expected, "placement_class": placement}


def consent_token(record: Mapping[str, Any]) -> str:
    """The 12 lowercase hex characters shown with the warning."""
    return validate_approval_record(record)["approval_sha256"][:12]


def consent_matches(token: Any, node: Mapping[str, Any], *, placement_class: PlacementClass) -> bool:
    if not isinstance(token, str) or re.fullmatch(r"[0-9a-f]{12}", token) is None:
        return False
    return hmac.compare_digest(token, consent_token(approval_record(node, placement_class=placement_class)))


def approval_matches(record: Mapping[str, Any], node: Mapping[str, Any], *, placement_class: PlacementClass) -> bool:
    saved = validate_approval_record(record)
    current = approval_record(node, placement_class=placement_class)
    return hmac.compare_digest(saved["approval_sha256"], current["approval_sha256"])



def validate_approvals(records: Any) -> list[NodeApproval]:
    """Validate a complete transported approval set before any restore starts."""
    if not isinstance(records, (list, tuple)):
        raise ValueError("node code approvals must be an array")
    result = [validate_approval_record(record) for record in records]
    if len({record["approval_sha256"] for record in result}) != len(result):
        raise ValueError("duplicate node code approval")
    return result


def require_approved_nodes(
    nodes: Sequence[Mapping[str, Any]],
    records: Any,
    *,
    placement_class: PlacementClass,
) -> list[NodeApproval]:
    """Return exact matching records, or refuse the whole set without I/O."""
    approved = validate_approvals(records)
    by_hash = {row["approval_sha256"]: row for row in approved}
    selected = []
    names: dict[str, str] = {}
    from urllib.parse import urlsplit
    for node in nodes:
        record = approval_record(node, placement_class=placement_class)
        source = urlsplit(record["identity"]["repo"])
        if (source.scheme != "https" or not source.hostname
                or source.username is not None or source.password is not None
                or source.query or source.fragment):
            raise ValueError("node code requires a credential-free HTTPS repository")
        name = source.path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        if not name or name in {".", ".."} or any(char.isspace() or char in "/\\" for char in name):
            raise ValueError("invalid approved node directory")
        previous = names.setdefault(name.casefold(), record["approval_sha256"])
        if previous != record["approval_sha256"]:
            raise ValueError(f"conflicting node code approvals for {name}")
        if record["approval_sha256"] not in by_hash:
            raise ValueError(f"needs_consent: no matching code approval for {record['identity']['repo']}@{record['identity']['commit']} on {placement_class}")
        selected.append(by_hash[record["approval_sha256"]])
    return selected

