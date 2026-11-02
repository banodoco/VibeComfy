"""Regenerate the Foley candidate using the existing source-to-ready converter.

Run from the repository root with the selected VibeComfy interpreter:
python ready_templates/sources/custom_nodes/hunyuan_foley/bobrandomnumber/_generate.py
No node imports, dependency installation, model downloads or inference occur.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory


SOURCE = Path(__file__).resolve().parent
ROOT = SOURCE.parents[4]
TEMPLATE_ID = "audio/hunyuan_video_foley"


def generate() -> None:
    from tools.build_node_corpus import PackReport, _write_shard
    from tools.refresh_template_index import main as refresh_index
    from vibecomfy.ingest.normalize import from_api
    from vibecomfy.node_packs import CustomNodePack
    from vibecomfy.node_packs._lockfile import LockEntry, compute_schema_hash, upsert_lockfile_entry
    from vibecomfy.porting.convert import _ready_requirements, port_convert_and_write, port_convert_workflow
    from vibecomfy.schema import get_authoring_schema_provider
    from vibecomfy.schema.extract import normalize_entry
    from vibecomfy.security.provenance import Provenance
    from vibecomfy.workflow_bundle import emit_bundle_with_candidate, load_bundle

    lock = json.loads((SOURCE / "assets.json").read_text())
    pack = lock["node_pack"]
    schema_source = json.loads((SOURCE / "node_schemas.json").read_text())
    schemas = {
        name: normalize_entry(class_name=name, raw_inputs=inputs, pack_name=pack["name"],
                              version=pack["commit"], python_module="hunyuan_foley",
                              attrs={"RETURN_TYPES": schema_source["outputs"][name], "FUNCTION": "execute"})
        for name, inputs in schema_source["inputs"].items()
    }
    cache = ROOT / "vibecomfy/porting/cache/object_info"
    index = json.loads((cache / "index.json").read_text())
    _write_shard(CustomNodePack(pack["name"], pack["url"], frozenset(schemas)),
                 "source-" + pack["commit"][:7], schemas, cache, index, PackReport(name=pack["name"], repo=pack["url"]))
    (cache / "index.json").write_text(json.dumps(dict(sorted(index.items())), indent=2) + "\n")
    upsert_lockfile_entry(LockEntry(name=pack["name"], git_commit_sha=pack["commit"],
        url=pack["url"], class_set=tuple(schemas), class_schema_sha256=compute_schema_hash(schemas),
        pip_packages=("diffusers", "timm", "transformers>=4.49.0", "descript-audiotools", "omegaconf")),
        ROOT / "custom_nodes.lock")

    provider = get_authoring_schema_provider(on_demand_schemas=False)
    source = SOURCE / "hunyuan_video_foley.json"
    raw = json.loads(source.read_text())
    workflow = from_api(raw, workflow_id=TEMPLATE_ID, schema_provider=provider)
    workflow.register_input("video_ref", "23", "file", "foley-input.mp4", type="COMBO",
                            required=True, media_semantics="video")
    workflow.register_input("prompt", "22", "prompt", raw["22"]["inputs"]["prompt"],
                            type="STRING", required=True)
    from vibecomfy.registry.ready_template import bind_output
    bind_output(workflow, "27", name="audio", output_type="SaveAudio", artifact_kind="audio",
                mime_type="audio/flac", expected_cardinality="one", filename_prefix="audio/hunyuan_video_foley")
    workflow.register_input("seed", "22", "seed", 123, type="INT", default=123)
    coverage = json.loads((ROOT / "ready_templates/sources/manifests/coverage.json").read_text())
    declaration = next(row for row in coverage["workflows"] if row.get("ready_template") == TEMPLATE_ID)
    assets = [{key: value for key, value in asset.items() if key != "repository"} for asset in lock["assets"]]
    workflow.metadata.update(license_notice=declaration["license_notice"],
        model_assets=assets,
        source_workflow=str(source.relative_to(ROOT)))
    result = port_convert_workflow(workflow, ready_id=TEMPLATE_ID,
        source_path=str(source.relative_to(ROOT)), source_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
        schema_provider=provider, raw_workflow=raw, preserve_node_ids=True)
    destination = ROOT / "ready_templates/audio/hunyuan_video_foley.py"
    # Publish the canonical pair using the same writer as templates create.
    # Production snapshots retain both members before staging or admission.
    with TemporaryDirectory(prefix="hunyuan-foley-authoring-") as temporary:
        candidate = Path(temporary) / destination.name
        port_convert_and_write(result, candidate)
        built = load_bundle(candidate, trust=Provenance.USER_CONFIRMED, schema_provider=provider)
        # Runtime picker requirements and auxiliary downloads have different
        # scopes. Use the shared picker projection; keep all ten locked files
        # in model_assets for the normal downloader.
        built.workflow.requirements.models = _ready_requirements(built.workflow)["models"]
        emit_bundle_with_candidate(built.workflow, destination, {"operation": "authored"}, None,
            operation="authored", source_provenance={"ready_id": TEMPLATE_ID,
                "source_workflow": str(source.relative_to(ROOT)), "output_mode": "ready_template"},
            source_format="ready_template", preserve_authored_graph=True)
    if refresh_index([]):
        raise RuntimeError("template index regeneration failed")


if __name__ == "__main__":
    generate()
