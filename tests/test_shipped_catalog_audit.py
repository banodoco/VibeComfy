"""WS-0c audit: read-only defaults must not consult the working directory."""
from pathlib import Path

import pytest

from vibecomfy.analysis.node_coverage import build_workflow_coverage
from vibecomfy.node_packs._defs import _known_node_packs, _rich_lock_packs
from vibecomfy.workflow import VibeNode, VibeWorkflow, WorkflowSource


def test_private_catalog_and_coverage_read_shipped_lock(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = Path("custom_nodes.lock")
    target.write_text(
        '[nodepacks.TargetOnly]\nsource = "local"\npath = "."\nclass_set = ["TargetNode"]\n',
        encoding="utf-8",
    )
    original = target.read_bytes()
    for read in (_rich_lock_packs, _known_node_packs):
        assert any(pack.name == "ComfyUI-HunyuanVideo_Foley" for pack in read())
        assert not any(pack.name == "TargetOnly" for pack in read())
        assert any(pack.name == "TargetOnly" for pack in read(target))
    workflow = VibeWorkflow("coverage", WorkflowSource("coverage"))
    workflow.nodes["1"] = VibeNode("1", "HunyuanFoleySampler")
    assert build_workflow_coverage(workflow).missing_lock == 0
    assert target.read_bytes() == original
    target.write_text("[bad", encoding="utf-8")
    with pytest.raises(ValueError):
        build_workflow_coverage(workflow, lock_path=target)
