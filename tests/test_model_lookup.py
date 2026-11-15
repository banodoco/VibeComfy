"""Offline proof of planning, verification and durable model identities."""
from contextlib import contextmanager
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from vibecomfy import fetch
from vibecomfy.runtime.prepared import PreparationError, prepare_workflow

BODY = b"small model bytes"
SHA = hashlib.sha256(BODY).hexdigest()
REV = "c" * 40
URL = "https://huggingface.co/acme/models/resolve/main/model.bin"


def entry(url=URL, **extra):
    return {"name": "model.bin", "subdir": "checkpoints", "url": url, **extra}


@pytest.fixture
def source(monkeypatch):
    state = SimpleNamespace(body=BODY, headers={"x-linked-etag": f'"{SHA}"',
        "x-linked-size": str(len(BODY)), "x-repo-commit": REV}, requests=[])

    @contextmanager
    def stream(method, url, **kwargs):
        state.requests.append((method, url, kwargs))
        yield httpx.Response(200, headers=state.headers if method == "HEAD" else {},
            content=None if method == "HEAD" else state.body,
            request=httpx.Request(method, url))

    monkeypatch.setattr(fetch.httpx, "stream", stream)
    return state


def prepare(tmp_path, model):
    workflow = SimpleNamespace(metadata={"model_assets": [model]}, nodes={},
        runtime_nodes=lambda: {}, requirements=SimpleNamespace(models=[], custom_nodes=[]))
    return prepare_workflow(workflow, reference="fixture.py", runtime_root=tmp_path,
        ensure_packs=False, download_workers=1)


def test_hf_without_declared_digest_prepares_and_records_metadata(tmp_path, source):
    from vibecomfy.templates import ReadyMetadata, new_workflow, OutputSpec
    from vibecomfy.nodes.core import EmptyImage, SaveImage

    with new_workflow(ReadyMetadata.build(template_id="model-lookup-cpu", capability="image",
            model_assets=[entry()])) as workflow:
        image = EmptyImage(width=16, height=16, batch_size=1, color=0)
        saved = SaveImage(images=image.out("IMAGE"), filename_prefix="lookup-proof")
        workflow.finalize({}, outputs=[OutputSpec(node=saved)])
    result = prepare_workflow(workflow, reference="fixture.py", runtime_root=tmp_path,
        ensure_packs=False, download_workers=1)
    assert len(result.model_evidence) == 1
    record = result.model_evidence[0]
    assert record["observed_sha256"] == SHA
    assert record["size_bytes"] == len(BODY)
    assert record["resolved_revision"] == REV
    assert record["fetch_url"] == URL.replace("/main/", f"/{REV}/")
    assert [(method, url) for method, url, _ in source.requests] == [
        ("HEAD", URL), ("GET", record["fetch_url"])]
    assert json.loads(open(result.receipt_path).read())["model_evidence"] == [record]


def test_lookup_size_available_before_download(tmp_path, source):
    planned = fetch.plan_downloads([entry()], root=tmp_path)
    assert planned[0]["size_bytes"] == len(BODY)
    assert planned[0]["sha256"] == SHA
    assert planned[0]["resolved_revision"] == REV
    assert [method for method, _, _ in source.requests] == ["HEAD"]
    assert not list(tmp_path.rglob("*.json"))


def test_looked_up_digest_mismatch_fails_without_record(tmp_path, source):
    source.body = b"different bytes!!"
    with pytest.raises(PreparationError, match="model preparation failed"):
        prepare(tmp_path, entry())
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("headers", [{}, {"etag": '"not-a-sha256"'},
    {"x-linked-etag": '"git-sha1"', "x-linked-size": str(len(BODY)), "x-repo-commit": REV}])
def test_hf_without_published_sha_is_hashed_and_recorded(tmp_path, source, headers):
    source.headers = headers
    result = prepare(tmp_path, entry())
    assert result.model_evidence[0]["observed_sha256"] == SHA
    assert result.model_evidence[0]["size_bytes"] == len(BODY)


def test_failed_head_still_hashes_download(tmp_path, source, monkeypatch):
    original = fetch.httpx.stream

    def stream(method, *args, **kwargs):
        if method == "HEAD":
            raise httpx.ConnectError("metadata unavailable")
        return original(method, *args, **kwargs)

    monkeypatch.setattr(fetch.httpx, "stream", stream)
    assert prepare(tmp_path, entry()).model_evidence[0]["observed_sha256"] == SHA


@pytest.mark.parametrize("remove", [False, True])
def test_generic_record_verifies_second_run_even_after_file_removed(tmp_path, source, remove):
    model = entry("https://example.test/model.bin")
    first = fetch.download(model, root=tmp_path)
    receipt_files = list(tmp_path.rglob("*.json"))
    original = receipt_files[0].read_bytes()
    assert fetch.read_resolution_receipt(model, root=tmp_path)["observed_sha256"] == SHA
    assert [method for method, _, _ in source.requests] == ["GET"]
    if remove:
        first.unlink()
    else:
        first.write_bytes(b"changed same len")
    source.body = b"unexpected changed model"
    with pytest.raises(RuntimeError, match="mismatch"):
        fetch.download(model, root=tmp_path)
    assert receipt_files[0].read_bytes() == original


def test_recorded_identity_reused_without_second_head(tmp_path, source):
    model = entry()
    first = fetch.plan_downloads([model], root=tmp_path)[0]
    fetch.download(first, root=tmp_path)
    fetch.local_path(model, root=tmp_path).unlink()
    second = fetch.plan_downloads([model], root=tmp_path)[0]
    assert second["sha256"] == SHA
    assert second["resolved_revision"] == REV
    assert [method for method, _, _ in source.requests] == ["HEAD", "GET"]


def test_declared_vs_lookup_disagreement_fails_during_planning(tmp_path, source):
    with pytest.raises(RuntimeError, match="sha256.*disagrees"):
        fetch.plan_downloads([entry(sha256="d" * 64)], root=tmp_path)
    assert [method for method, _, _ in source.requests] == ["HEAD"]
    assert not list(tmp_path.rglob("*.json"))


def test_declared_digest_enforced_when_metadata_unavailable(tmp_path, source):
    source.headers = {}
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        planned = fetch.plan_downloads([entry(sha256="d" * 64)], root=tmp_path)
        fetch.download(planned[0], root=tmp_path)
    assert not list(tmp_path.rglob("*.json"))


def test_head_redirects_are_unauthenticated_and_ignore_external_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "fixture-token")
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == "huggingface.co":
            return httpx.Response(302, headers={"location": "https://example.test/blob",
                "x-linked-etag": SHA, "x-linked-size": str(len(BODY)), "x-repo-commit": REV})
        return httpx.Response(200, headers={"x-linked-etag": "e" * 64,
            "x-repo-commit": "e" * 40})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        planned = fetch.plan_downloads([entry()], root=tmp_path, client=client)[0]
    assert planned["sha256"] == SHA
    assert planned["resolved_revision"] == REV
    assert len(seen) == 2
    assert all(request.method == "HEAD" and "authorization" not in request.headers for request in seen)
    seen.clear()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetch.plan_downloads([entry("https://example.test/model.bin")], root=tmp_path, client=client)
    assert seen == []


def test_planning_cannot_override_authored_digest(tmp_path, source):
    authored = entry(sha256="d" * 64)
    with pytest.raises(RuntimeError, match="sha256.*disagrees"):
        fetch.apply_download_plan([authored], [entry(sha256=SHA, size_bytes=len(BODY))])


def test_verify_uses_recorded_digest_and_preserves_source_identity(tmp_path, source):
    model = entry("https://example.test/model.bin")
    path = fetch.download(model, root=tmp_path)
    assert fetch.verify(model, root=tmp_path, force=True) is False
    assert fetch.read_resolution_receipt(model, root=tmp_path)["observed_sha256"] == SHA
    path.write_bytes(b"x" * len(BODY))
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        fetch.verify(model, root=tmp_path)


def test_plan_preserves_canonical_placement_and_normalized_source_url():
    authored = entry(url=URL, target_path="custom_nodes/aux/model.bin")
    planned = entry(url=URL + "?download=true", sha256=SHA, size_bytes=len(BODY))
    applied = fetch.apply_download_plan([authored], [planned])[0]
    assert applied["target_path"] == authored["target_path"]
    assert applied["url"] == URL
    assert applied["sha256"] == SHA


def test_download_requires_durable_learned_identity(tmp_path, source, monkeypatch):
    original = fetch.os.replace

    def replace(src, dst):
        if str(dst).endswith('.json'):
            raise PermissionError('fixture receipt store is unavailable')
        return original(src, dst)

    monkeypatch.setattr(fetch.os, 'replace', replace)
    with pytest.raises(PermissionError, match='receipt store is unavailable'):
        fetch.download(entry('https://example.test/model.bin'), root=tmp_path)
    assert fetch.recorded_model_identity(entry('https://example.test/model.bin'), root=tmp_path) is None
