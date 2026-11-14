"""Offline regression checks for per-request Hugging Face credentials."""

from contextlib import contextmanager
import hashlib
import json
import secrets

import httpx
import pytest

import vibecomfy.fetch as fetch


@pytest.fixture
def credential(monkeypatch):
    value = secrets.token_urlsafe(32)
    monkeypatch.setenv("HF_TOKEN", value)
    return value


def _has_credential(headers, credential):
    # Return a boolean so failed assertions cannot print the credential.
    return headers.get("Authorization") == f"Bearer {credential}"


def _contains_credential(text, credential):
    return credential in text


def _entry(url):
    return {"name": "model.bin", "subdir": "checkpoints", "url": url}


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://huggingface.co/file", True),
        ("https://hf.co/file", True),
        ("https://www.huggingface.co/file", True),
        ("https://www.hf.co/file", True),
        ("https://cdn-lfs.huggingface.co/file", True),
        ("https://cdn.hf.co/file", True),
        ("https://a.b.huggingface.co/file", True),
        ("https://HUGGINGFACE.CO/file", True),
        ("https://example.com/file", False),
        ("https://evilhuggingface.co/file", False),
        ("https://evilhf.co/file", False),
        ("https://huggingface.co.evil.example/file", False),
        ("https://hf.co.evil.example/file", False),
        ("http://huggingface.co/file", False),
        ("http://cdn-lfs.huggingface.co/file", False),
        ("https://huggingface.co@evil.example/file", False),
        ("https://evil.example/huggingface.co/file", False),
        ("https://huggingface.co./file", False),
    ],
)
def test_initial_request_credential_host(url, allowed, credential, monkeypatch, tmp_path):
    seen = []

    @contextmanager
    def stream(method, requested_url, **kwargs):
        seen.append(kwargs["headers"])
        yield httpx.Response(200, content=b"model", request=httpx.Request(method, requested_url))

    monkeypatch.setattr(fetch.httpx, "stream", stream)
    fetch.download(_entry(url), root=tmp_path)

    request_count = len(seen)
    assert request_count == 1
    has_credential = _has_credential(seen[0], credential)
    assert has_credential is allowed
    if not allowed:
        has_authorization = "Authorization" in seen[0]
        assert not has_authorization


class RedirectClient:
    """A client that deliberately retains headers if asked to auto-follow."""

    def __init__(self, destination, *, wrapped=False):
        self.destination = destination
        self.wrapped = wrapped
        self.requests = []
        self.closed = 0

    def _request(self, method, url, headers):
        self.requests.append((url, dict(headers)))
        return httpx.Response(
            302 if len(self.requests) == 1 else 200,
            headers={"Location": self.destination} if len(self.requests) == 1 else {},
            content=b"model",
            request=httpx.Request(method, url),
        )

    @contextmanager
    def stream(self, method, url, *, headers, follow_redirects, **kwargs):
        response = self._request(method, url, headers)
        if follow_redirects and response.status_code == 302:
            response = self._request(method, self.destination, headers)
        try:
            yield WrappedResponse(response) if self.wrapped else response
        finally:
            response.close()
            self.closed += 1


class WrappedResponse:
    """Match the Agent's status/URL/body-only resuming response wrapper."""

    def __init__(self, response):
        self._response = response
        self.status_code = response.status_code
        self.url = response.url

    def iter_bytes(self):
        yield from self._response.iter_bytes()


@pytest.mark.parametrize("client_kind", ["httpx", "default", "stub", "wrapped"])
@pytest.mark.parametrize(
    ("destination", "allowed"),
    [
        ("https://evil.example/file", False),
        ("http://huggingface.co/file", False),
        ("https://cdn-lfs.huggingface.co/file", True),
        ("/other-file", True),
    ],
)
def test_redirect_rechecks_credential_host(
    client_kind, destination, allowed, credential, monkeypatch, tmp_path, capsys, caplog
):
    initial = "https://huggingface.co/file"
    requests = []

    def handler(request):
        requests.append((str(request.url), dict(request.headers)))
        return httpx.Response(
            302 if len(requests) == 1 else 200,
            headers={"Location": destination} if len(requests) == 1 else {},
            content=b"model",
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        if client_kind in {"stub", "wrapped"}:
            client = RedirectClient(destination, wrapped=client_kind == "wrapped")
            requests = client.requests
        elif client_kind == "default":
            monkeypatch.setattr(fetch.httpx, "stream", http_client.stream)
            client = None
        else:
            client = http_client
        entry = _entry(initial)
        path = fetch.download(entry, root=tmp_path, client=client)

    request_count = len(requests)
    assert request_count == 2
    first_headers = httpx.Headers(requests[0][1])
    last_headers = httpx.Headers(requests[1][1])
    first_has_credential = _has_credential(first_headers, credential)
    last_has_credential = _has_credential(last_headers, credential)
    assert first_has_credential
    assert last_has_credential is allowed
    if not allowed:
        has_authorization = "Authorization" in last_headers
        assert not has_authorization
    assert requests[1][0] == str(httpx.URL(initial).join(destination))
    if client_kind in {"stub", "wrapped"}:
        assert client.closed == 2
    assert path.read_bytes() == b"model"
    receipt = fetch.read_resolution_receipt(entry, root=tmp_path)
    assert receipt is not None
    assert receipt["effective_url"] == requests[1][0]
    assert receipt["observed_sha256"] == hashlib.sha256(b"model").hexdigest()
    receipt_contains_credential = _contains_credential(json.dumps(receipt), credential)
    assert not receipt_contains_credential
    for receipt_file in (tmp_path / ".vibecomfy").rglob("*.json"):
        receipt_contains_credential = _contains_credential(receipt_file.read_text(), credential)
        assert not receipt_contains_credential
    captured = capsys.readouterr()
    output_contains_credential = _contains_credential(captured.out + captured.err, credential)
    log_contains_credential = _contains_credential(caplog.text, credential)
    assert not output_contains_credential
    assert not log_contains_credential


def test_redirect_loop_is_bounded(credential, tmp_path):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(302, headers={"Location": "/loop"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.TooManyRedirects):
            fetch.download(_entry("https://huggingface.co/file"), root=tmp_path, client=client)

    assert count == 21
    assert not list(tmp_path.rglob("*.bin"))
