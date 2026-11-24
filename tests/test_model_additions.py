"""LE-9 recorded HEAD and canonical declaration shape; no network or downloads."""
from __future__ import annotations

import httpx
import pytest

from vibecomfy.model_additions import resolve_added_model_assets
from vibecomfy.model_assets import validate_authored_asset_declarations

SHA = "a" * 64
URL = "https://models.example/checkpoint.safetensors"
DEST = "checkpoints/nested/model.safetensors"


def test_model_addition_records_only_head_size_and_canonical_row(tmp_path):
    calls = []

    def reply(request):
        calls.append((request.method, str(request.url)))
        assert "authorization" not in request.headers
        assert request.headers["accept-encoding"] == "identity"
        if request.url.host == "models.example":
            return httpx.Response(302, headers={"location": "https://cdn.example/model"})
        return httpx.Response(200, headers={"content-length": "123456"})

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        rows = resolve_added_model_assets([f"{DEST}={URL}#{SHA}"], client=client)
    assert rows == [{"name": "nested/model.safetensors", "subdir": "checkpoints",
                     "url": URL, "sha256": SHA, "size_bytes": 123456}]
    assert calls == [("HEAD", URL), ("HEAD", "https://cdn.example/model")]
    assert validate_authored_asset_declarations(rows, root=tmp_path) == rows
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("bad", [
    f"../model={URL}#{SHA}", f"checkpoints/../model={URL}#{SHA}",
    f"checkpoints//model={URL}#{SHA}", f"/model={URL}#{SHA}",
    f"checkpoints/model=http://example/model#{SHA}",
    f"checkpoints/model=https://user:pass@example/model#{SHA}",
    f"checkpoints/model={URL}#short", f"model={URL}#{SHA}",
])
def test_invalid_batch_refused_before_any_head(bad):
    def unexpected(request):
        pytest.fail("invalid batch reached network")

    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        with pytest.raises(ValueError):
            resolve_added_model_assets([f"{DEST}={URL}#{SHA}", bad], client=client)


def test_duplicate_destination_refused_before_head():
    def unexpected(request):
        pytest.fail("duplicate model destination reached network")

    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        with pytest.raises(ValueError, match="duplicate"):
            resolve_added_model_assets([f"{DEST}={URL}#{SHA}"] * 2, client=client)


@pytest.mark.parametrize("status,headers", [
    (200, {}), (200, {"content-length": "0"}),
    (200, {"content-length": "10", "content-encoding": "gzip"}),
    (206, {"content-length": "10", "content-range": "bytes 0-9/100"}),
    (302, {"location": "http://cdn.example/model"}),
    (302, {"location": "https://user:pass@cdn.example/model"}),
    (405, {}),
])
def test_untrustworthy_head_refused_without_get(status, headers):
    calls = []

    def reply(request):
        calls.append(request.method)
        return httpx.Response(status, headers=headers)

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        with pytest.raises((ValueError, httpx.HTTPStatusError)):
            resolve_added_model_assets([f"{DEST}={URL}#{SHA}"], client=client)
    assert calls == ["HEAD"]


def test_resolved_model_row_is_consumed_by_existing_preparation_without_registry(tmp_path, monkeypatch):
    """Witness the real existing consumer, independently of entry/CLI publication."""
    from vibecomfy import fetch
    from vibecomfy.model_assets import referenced_model_requirements
    from vibecomfy.runtime.session import _model_assets_from_workflow
    from vibecomfy.workflow import VibeNode, VibeWorkflow, WorkflowSource

    calls = []

    def reply(request):
        calls.append((request.method, str(request.url)))
        return httpx.Response(200, headers={"content-length": "123456"})

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        row, = resolve_added_model_assets([f"{DEST}={URL}#{SHA}"], client=client)

    workflow = VibeWorkflow("explicit-model", WorkflowSource("explicit-model"))
    workflow.nodes["1"] = VibeNode(
        "1", "CheckpointLoaderSimple", inputs={"ckpt_name": "nested/model.safetensors"},
    )
    workflow.metadata["model_assets"] = [row]
    monkeypatch.setattr("vibecomfy.registry.models_loader.load_registry",
                        lambda: pytest.fail("authored model row must not require registry lookup"))
    requirements = referenced_model_requirements(workflow, require_resolved=True)
    assert requirements == [row]
    assert _model_assets_from_workflow(workflow, models_root=tmp_path) == [row]
    assert fetch.local_path(row, root=tmp_path) == tmp_path / DEST
    assert calls == [("HEAD", URL)]
    assert not list(tmp_path.iterdir())
