from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vibecomfy.socket_types import COMBO, canonical_socket_type


@pytest.mark.parametrize("value", ["CHOICE", "ENUM", "COMBO", " choice ", "enum"])
def test_enum_socket_comparison_name(value: str) -> None:
    assert canonical_socket_type(value) == COMBO


@pytest.mark.parametrize(
    "value, expected",
    [(None, ""), ("", ""), (" image ", "IMAGE"), ("CustomType", "CUSTOMTYPE"), (0, "0")],
)
def test_other_socket_comparison_names(value: object, expected: str) -> None:
    assert canonical_socket_type(value) == expected


@pytest.mark.parametrize("left", ["CHOICE", "ENUM", "COMBO"])
@pytest.mark.parametrize("right", ["CHOICE", "ENUM", "COMBO"])
def test_socket_compatibility_uses_the_shared_vocabulary(left: str, right: str) -> None:
    from vibecomfy.schema.validate import socket_types_compatible
    from vibecomfy.workflow import _types_match

    assert socket_types_compatible(left, right)
    assert socket_types_compatible(f"IMAGE,{left}", right)
    assert _types_match(left, right)
    assert _types_match(f"IMAGE,{left}", right)


# These parse/serialize sites retain historical spellings in stored schemas.
_STORED_SPELLINGS = {
    ("ingest/normalize.py", "_native_port_types", "socket_type", "CHOICE"):
        "Wire lists are stored as CHOICE in envelopes.",
    ("schema/provider.py", "_parse_input_spec", "typ", "CHOICE"):
        "Parsed provider schemas retain CHOICE.",
    ("porting/object_info/consume.py", "_normalize_input_type", "return", "ENUM"):
        "Cache input lists retain ENUM.",
}


def _enum_alias_violations(source: str, path: str) -> list[int]:
    violations = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.function = ""
            self.parents: list[ast.AST] = []

        def generic_visit(self, node: ast.AST) -> None:
            self.parents.append(node)
            super().generic_visit(node)
            self.parents.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            previous = self.function
            self.function = node.name
            self.generic_visit(node)
            self.function = previous

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Constant(self, node: ast.Constant) -> None:
            if node.value in ("CHOICE", "ENUM"):
                parent = self.parents[-1] if self.parents else None
                target = ""
                if isinstance(parent, ast.Return) and parent.value is node:
                    target = "return"
                elif (
                    isinstance(parent, ast.Assign)
                    and parent.value is node
                    and len(parent.targets) == 1
                    and isinstance(parent.targets[0], ast.Name)
                ):
                    target = parent.targets[0].id
                if (path, self.function, target, node.value) not in _STORED_SPELLINGS:
                    violations.append(node.lineno)

    Visitor().visit(ast.parse(source))
    return violations


def test_enum_aliases_have_one_comparison_owner() -> None:
    root = Path(__file__).resolve().parents[1] / "vibecomfy"
    violations = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative == "socket_types.py":
            continue
        violations.extend(
            f"{relative}:{line}" for line in _enum_alias_violations(path.read_text(), relative)
        )
    assert not violations, "Socket aliases belong in socket_types.py: " + ", ".join(violations)


def test_enum_alias_ratchet_rejects_a_local_comparison_set() -> None:
    source = 'def compare(value):\n    return value in {"COMBO", "ENUM", "CHOICE"}\n'
    assert _enum_alias_violations(source, "new_consumer.py") == [2, 2]
    assert _enum_alias_violations(
        source.replace("compare", "_normalize_input_type"), "porting/object_info/consume.py"
    ) == [2, 2]
