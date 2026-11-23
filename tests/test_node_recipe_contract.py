"""P56 WS-7a: portable recipe declarations, without installing anything."""
from __future__ import annotations

import json

import pytest

from vibecomfy.custom_node_refs import (
    CustomNodeRefConflict,
    lock_entry_to_ref,
    normalize_custom_node_requirements,
    workflow_lock_entries,
)
from vibecomfy.node_packs import LockEntry, read_lockfile, upsert_lockfile_entry, write_lockfile
from vibecomfy.workflow import VibeWorkflow, WorkflowSource


PIN = "a" * 40
REF = {"slug": "test-pack", "source": "git", "url": "https://example.test/pack.git", "commit": PIN}
RECIPE = {"requirements_txt": "deps/requirements.txt", "pip_no_deps": ["z-last==2", "a-first==1"]}


def test_recipe_survives_lock_ref_workflow_and_json_round_trip(tmp_path):
    path = tmp_path / "custom_nodes.lock"
    entry = LockEntry(name="test-pack", url=REF["url"], commit=PIN, **RECIPE)
    write_lockfile([entry], path)
    restored = read_lockfile(path)[0]
    assert restored.requirements_txt == RECIPE["requirements_txt"]
    assert restored.pip_no_deps == tuple(RECIPE["pip_no_deps"])
    ref = lock_entry_to_ref(restored)
    assert {key: ref[key] for key in RECIPE} == RECIPE
    requirements, _ = normalize_custom_node_requirements({"custom_node_refs": [ref]})
    workflow = VibeWorkflow("recipe", WorkflowSource("recipe"), metadata={"requirements": json.loads(json.dumps(requirements))})
    assert workflow_lock_entries(workflow) == [restored]


def test_upsert_keeps_recipe_when_preserving_schema_evidence(tmp_path):
    path = tmp_path / "custom_nodes.lock"
    write_lockfile([LockEntry(name="test-pack", url=REF["url"], commit=PIN, class_schema_sha256="b" * 64)], path)
    upsert_lockfile_entry(LockEntry(name="test-pack", url=REF["url"], commit=PIN, **RECIPE), path)
    row = read_lockfile(path)[0]
    assert row.class_schema_sha256 == "b" * 64
    assert row.requirements_txt == RECIPE["requirements_txt"]
    assert row.pip_no_deps == tuple(RECIPE["pip_no_deps"])


@pytest.mark.parametrize("field,value", [("requirements_txt", "other.txt"), ("requirements_txt", None), ("pip_no_deps", ["other==1"])])
def test_duplicate_refs_cannot_silently_choose_a_different_recipe(field, value):
    with pytest.raises(CustomNodeRefConflict) as caught:
        normalize_custom_node_requirements({"custom_node_refs": [{**REF, **RECIPE}, {**REF, **RECIPE, field: value}]})
    assert caught.value.field == field


def test_recipe_hash_is_canonical_and_keeps_installation_order():
    from vibecomfy.node_recipes import canonical_recipe, recipe_sha256

    assert canonical_recipe({}) == {"requirements_txt": None, "pip_no_deps": []}
    assert recipe_sha256({}) == recipe_sha256({"pip_no_deps": (), "requirements_txt": None})
    assert recipe_sha256(RECIPE) == recipe_sha256(dict(reversed(list(RECIPE.items()))))
    assert len(recipe_sha256(RECIPE)) == 64
    assert recipe_sha256(RECIPE) != recipe_sha256({**RECIPE, "requirements_txt": "other.txt"})
    assert recipe_sha256(RECIPE) != recipe_sha256({**RECIPE, "pip_no_deps": ["z-last==3", "a-first==1"]})
    assert recipe_sha256(RECIPE) != recipe_sha256({**RECIPE, "pip_no_deps": list(reversed(RECIPE["pip_no_deps"]))})
    result = canonical_recipe(RECIPE)
    result["pip_no_deps"].append("another")
    assert RECIPE["pip_no_deps"] == ["z-last==2", "a-first==1"]


@pytest.mark.parametrize("recipe", [
    {"requirements_txt": "../outside.txt"}, {"requirements_txt": "/tmp/outside.txt"},
    {"requirements_txt": "C:/outside.txt"}, {"requirements_txt": "deps\\requirements.txt"},
    {"requirements_txt": "deps//requirements.txt"}, {"requirements_txt": "./requirements.txt"},
    {"requirements_txt": "requirements.txt\n"}, {"requirements_txt": ""},
    {"requirements_txt": True}, {"pip_no_deps": "pkg"}, {"pip_no_deps": None},
    {"pip_no_deps": ["--index-url=https://example.test"]}, {"pip_no_deps": ["  -r file"]},
    {"pip_no_deps": ["pkg\n--other"]}, {"pip_no_deps": [""]}, {"pip_no_deps": [1]},
])
def test_invalid_recipe_is_rejected_at_lock_and_ref_boundaries(recipe):
    with pytest.raises(ValueError):
        LockEntry(name="test-pack", url=REF["url"], commit=PIN, **recipe)
    with pytest.raises(ValueError):
        normalize_custom_node_requirements({"custom_node_refs": [{**REF, **recipe}]})


def test_hash_refuses_unrecognized_recipe_fields():
    from vibecomfy.node_recipes import recipe_sha256

    with pytest.raises(ValueError, match="recipe"):
        recipe_sha256({"install_py": True})


def test_plain_legacy_refs_do_not_grow_recipe_keys():
    entry = LockEntry(name="test-pack", url=REF["url"], commit=PIN)
    assert lock_entry_to_ref(entry) == REF
    requirements, _ = normalize_custom_node_requirements({"custom_node_refs": [REF]})
    assert requirements["custom_node_refs"] == [REF]
