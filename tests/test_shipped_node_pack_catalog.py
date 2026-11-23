"""WS-0c: the shipped catalog is independent of the target working directory."""
from pathlib import Path

from vibecomfy.node_packs import (
    get_known_node_packs,
    missing_packs_for_workflow,
    read_lockfile,
    resolve_lockfile_path,
    resolve_node_packs,
)
from vibecomfy.node_packs._install import _pack_by_name
from vibecomfy.workflow import VibeNode, VibeWorkflow, WorkflowSource


def test_shipped_catalog_from_target_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "node_index.json").write_text("[]", encoding="utf-8")
    target_lock = tmp_path / "custom_nodes.lock"
    target_lock.write_text(
        '[nodepacks.TargetOnly]\nsource = "local"\npath = "."\nclass_set = ["TargetNode"]\n',
        encoding="utf-8",
    )
    before = target_lock.read_bytes()
    name = "ComfyUI-HunyuanVideo_Foley"
    node = "HunyuanFoleySampler"
    revision = "b94f7aca877ff2be5bc264b057abee3dac682c1b"

    [pack] = resolve_node_packs({node})
    assert pack.name == name
    assert _pack_by_name(name) == pack
    assert _pack_by_name("TargetOnly") is None
    assert pack in get_known_node_packs()
    assert resolve_lockfile_path() != target_lock
    [row] = [row for row in read_lockfile() if row.name == name]
    assert row.git_commit_sha == revision
    assert row.url == pack.repo
    workflow = VibeWorkflow("foley", WorkflowSource("foley"))
    workflow.nodes["1"] = VibeNode("1", node)
    assert missing_packs_for_workflow(workflow) == ([pack], [])
    assert resolve_node_packs({"TargetNode"}) == []
    assert [p.name for p in resolve_node_packs({"TargetNode"}, lockfile_path=Path("custom_nodes.lock"))] == ["TargetOnly"]
    assert target_lock.read_bytes() == before


def test_shipped_lock_does_not_contain_example_fixture():
    rows = read_lockfile()
    assert all(row.name != "ExamplePack" for row in rows)
    assert all("example.test" not in (row.url or "") for row in rows)
