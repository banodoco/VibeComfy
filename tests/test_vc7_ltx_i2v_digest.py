"""The managed checkpoint records must carry the observed file identity."""
from vibecomfy.registry.ready import workflow_from_ready
from vibecomfy.runtime.session import _model_assets_from_workflow
from vibecomfy.testing.canonical import canonical_digest


def test_ltx_i2v_checkpoint_records_have_exact_hf_identity():
    workflow = workflow_from_ready("video/ltx2_3_i2v")
    # This filename has two authored destination aliases for the same HF file.
    rows = [row for row in _model_assets_from_workflow(workflow)
            if row["name"] in {"ltx-2.3-22b-dev.safetensors", "ltx-2.3-22b-dev-fp8.safetensors"}]
    assert {row["name"] for row in rows} == {
        "ltx-2.3-22b-dev.safetensors", "ltx-2.3-22b-dev-fp8.safetensors",
    }
    for row in rows:
        assert row["sha256"] == "28606c5b5a06ce56f896d4dfcb20f212739e07a68fbe48e53638188449d26450"
        assert row["size_bytes"] == 29145431166
        assert row["hf_revision"] == "91eda216f820e5ecb3d17dc9fe3b7cdaf56b587d"
        assert row["url"] == (
            "https://huggingface.co/Lightricks/LTX-2.3-fp8/resolve/"
            "91eda216f820e5ecb3d17dc9fe3b7cdaf56b587d/ltx-2.3-22b-dev-fp8.safetensors"
        )
    assert canonical_digest(workflow.compile("api")) == "7b93818753cd39ace1c6621ef37946bfde8acd64eaac6ee71f46b2a6d95cf263"
