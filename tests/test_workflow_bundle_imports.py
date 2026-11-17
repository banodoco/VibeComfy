"""The bundle reader must not initialize ComfyUI nodes or native math libraries."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def _assert_lightweight_imports(code: str) -> None:
    # Other tests import the emitter during collection, so inspect a fresh
    # interpreter rather than depending on the pytest process's module cache.
    probe = """
import importlib.abc
import sys

forbidden_modules = ("vibecomfy.comfy_nodes", "vibecomfy.nodes", "numpy", "torch",
                     "vibecomfy.porting.emit")
attempts = []

def is_forbidden(name):
    return any(name == root or name.startswith(root + ".") for root in forbidden_modules)

class ImportRecorder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if is_forbidden(fullname):
            attempts.append(fullname)
        return None

sys.meta_path.insert(0, ImportRecorder())
"""
    probe += textwrap.dedent(code)
    probe += """
loaded = sorted(name for name in sys.modules if is_forbidden(name))
assert not loaded, f"bundle reader loaded node/emitter/native modules: {loaded}"
assert not attempts, f"bundle reader attempted node/emitter/native imports: {attempts}"
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_importing_bundle_does_not_load_node_library() -> None:
    _assert_lightweight_imports("import vibecomfy.workflow_bundle\n")


def test_emitter_reexports_the_same_ui_only_classes() -> None:
    from vibecomfy.porting.emit.emit_constants import UI_ONLY_CLASS_TYPES as emit_types
    from vibecomfy.porting.emitter import UI_ONLY_CLASS_TYPES as compatibility_types
    from vibecomfy.ui_constants import UI_ONLY_CLASS_TYPES

    assert UI_ONLY_CLASS_TYPES is emit_types is compatibility_types
    assert UI_ONLY_CLASS_TYPES == frozenset({"Note", "MarkdownNote", "Label (rgthree)"})


def test_emitter_reexports_the_same_presentation_records() -> None:
    from vibecomfy.porting.emit.ui import (
        PresentationGraphRecords as emitted_records,
        capture_presentation_graph_records as emitted_capture,
    )
    from vibecomfy.presentation import PresentationGraphRecords, capture_presentation_graph_records

    assert emitted_records is PresentationGraphRecords
    assert emitted_capture is capture_presentation_graph_records


@pytest.mark.parametrize("class_type", [None, "Note", "MarkdownNote", "Label (rgthree)"])
def test_validating_annotations_does_not_load_node_library(class_type: str | None) -> None:
    _assert_lightweight_imports(
        f"""
        from vibecomfy.workflow import VibeWorkflow, WorkflowSource
        from vibecomfy.workflow_bundle import _validate_annotations

        workflow = VibeWorkflow("import-boundary", WorkflowSource("import-boundary"))
        class_type = {class_type!r}
        annotations = [] if class_type is None else [{{
            "annotation_id": "note", "scope_path": "",
            "owner": {{"kind": "node", "uid": "note"}},
            "class_type": class_type, "title": "Note", "content": "Keep this note",
        }}]
        assert _validate_annotations(annotations, workflow) == annotations
        """
    )


@pytest.mark.parametrize("with_presentation", [False, True])
def test_loading_python_bundle_does_not_load_node_library(with_presentation: bool) -> None:
    _assert_lightweight_imports(
        "with_presentation = " + repr(with_presentation) + "\n" + textwrap.dedent("""
        import json
        import tempfile
        from pathlib import Path

        from vibecomfy.security.provenance import Provenance
        from vibecomfy.testing.canonical import canonical_digest
        from vibecomfy.workflow_bundle import load_bundle

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "workflow.py"
            source.write_text(
                "from vibecomfy.workflow import VibeWorkflow, WorkflowSource\\n"
                "def build():\\n"
                "    workflow = VibeWorkflow('import-boundary', WorkflowSource('import-boundary'))\\n"
                "    workflow.add_node('Integer', uid='integer-node', value=7)\\n"
                "    return workflow\\n",
                encoding="utf-8",
            )
            custody = {"scopes": [{"scope_path": "", "nodes": [], "helpers": []}]}
            companion = {
                "format_version": 2,
                "bind": {
                    "workflow_identity": "import-boundary",
                    "generation_id": "import-boundary-v1",
                    "custody_digest": canonical_digest(custody),
                },
                "custody": custody,
                "presentation": {
                    "nodes": {}, "links": [], "groups": [], "canvas": {}, "annotations": [],
                },
            }
            if with_presentation:
                companion["presentation"]["nodes"] = {
                    "note": {"class_type": "MarkdownNote", "id": 7},
                }
                companion["presentation"]["annotations"] = [{
                    "annotation_id": "note", "scope_path": "",
                    "owner": {"kind": "node", "uid": "note"},
                    "class_type": "MarkdownNote", "title": "Note", "content": "preserve me",
                }]
            source.with_suffix(".vibe.json").write_text(json.dumps(companion), encoding="utf-8")

            bundle = load_bundle(source, trust=Provenance.USER_CONFIRMED)
            assert bundle.workflow_identity == "import-boundary"
            assert len(bundle.workflow.nodes) == 1
            assert bundle.workflow.nodes["1"].inputs["value"] == 7
            assert bundle.ui_sidecar == companion
        """)
    )


# Preserve the exact nonempty-v2 diagnostic reported in PR #174. The shared
# harness additionally checks descendants and attempted imports.
_NONEMPTY_V2_PRESENTATION_PROBE = r'''import sys
from vibecomfy.testing.canonical import canonical_digest
from vibecomfy.workflow import VibeWorkflow, WorkflowSource
from vibecomfy.workflow_bundle import validate_sidecar

workflow = VibeWorkflow("annotated-bundle", WorkflowSource("annotated-bundle"))
workflow.add_node("Integer", uid="integer-node", value=7)
custody = {"scopes": [{"scope_path": "", "nodes": [], "helpers": []}]}
companion = {
    "format_version": 2,
    "bind": {
        "workflow_identity": workflow.id,
        "generation_id": "probe",
        "custody_digest": canonical_digest(custody),
    },
    "custody": custody,
    "presentation": {
        "nodes": {"note": {"class_type": "MarkdownNote", "id": 7}},
        "links": [], "groups": [], "canvas": {},
        "annotations": [{
            "annotation_id": "note", "scope_path": "",
            "owner": {"kind": "node", "uid": "note"},
            "class_type": "MarkdownNote", "title": "Note", "content": "preserve me",
        }],
    },
}
forbidden = {"vibecomfy.comfy_nodes", "numpy", "vibecomfy.porting.emit"}
assert not forbidden & sys.modules.keys()
normalized = validate_sidecar(companion, workflow)
assert normalized["presentation"]["annotations"][0]["content"] == "preserve me"
loaded = sorted(forbidden & sys.modules.keys())
print(loaded)
assert not loaded, loaded
'''


def test_nonempty_v2_presentation_does_not_load_node_library() -> None:
    _assert_lightweight_imports(_NONEMPTY_V2_PRESENTATION_PROBE)
