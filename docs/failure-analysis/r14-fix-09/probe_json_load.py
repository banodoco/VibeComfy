import hashlib
import json
import sys
from pathlib import Path

from vibecomfy.cli_loader import load_bundle

records = []
for relative in ("image/z_image.json", "video/ltx2_3_t2v.json"):
    source = Path("ready_templates/sources/official") / relative
    bundle = load_bundle(source)
    from vibecomfy.ingest.snapshot import snapshot_of

    snapshot = snapshot_of(bundle.workflow)
    records.append({
        "source": source.as_posix(),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "workflow_id": bundle.workflow.id,
        "nodes": len(bundle.workflow.nodes),
        "edges": len(bundle.workflow.edges),
        "bundle_semantic_digest": bundle.semantic_digest,
        "snapshot_semantic_digest": snapshot.semantic_digest,
        "snapshot_source_representation": snapshot.source_representation,
        "forbidden_roots_loaded": [
            root for root in ("vibecomfy.comfy_nodes", "numpy", "vibecomfy.porting.emit")
            if root in sys.modules
        ],
    })
print(json.dumps(records, indent=2, sort_keys=True))
