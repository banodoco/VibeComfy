"""Plan 56 LE-4: recorded-response regressions. No network or install."""
from __future__ import annotations

import httpx
import pytest

from vibecomfy.registry import pack_resolver as resolver


QUERY = "ProbeNode"
PACK = "probe-pack"
API = resolver.API_BASE_URL
EXACT = f"{API}/comfy-nodes/{QUERY}/node"
VERSIONS = f"{API}/nodes/{PACK}/versions"
SCHEMA = f"{API}/nodes/{PACK}/versions/1.2.3/schema"


@pytest.fixture(autouse=True)
def reset_search_budget():
    resolver._reset_process_github_code_search_budget()
    yield
    resolver._reset_process_github_code_search_budget()


def client(routes, calls):
    def handle(request):
        url = str(request.url).split("?", 1)[0]
        calls.append(url)
        value = routes.get(url, (404, {}))
        if isinstance(value, type) and issubclass(value, httpx.RequestError):
            raise value("recorded transport failure", request=request)
        status, payload = value
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload, request=request)
        return httpx.Response(status, json=payload, request=request)

    return httpx.Client(transport=httpx.MockTransport(handle))


def run(tmp_path, *, registry=None, manager=None, github=None):
    calls = {"registry": [], "manager": [], "github": []}
    empty_manager = {
        resolver.MANAGER_NODE_MAP_URL: (200, {}),
        resolver.MANAGER_NODE_LIST_URL: (200, []),
    }
    empty_github = {
        f"{resolver.GITHUB_API_BASE_URL}/search/code": (200, {"items": []}),
        f"{resolver.GITHUB_API_BASE_URL}/search/repositories": (200, {"items": []}),
    }
    with (
        client(registry or {}, calls["registry"]) as registry_http,
        client(manager if manager is not None else empty_manager, calls["manager"]) as manager_http,
        client(github if github is not None else empty_github, calls["github"]) as github_http,
    ):
        result = resolver.resolve_missing_nodes(
            QUERY,
            query_intent="class_name",
            cache_root=tmp_path,
            registry_client=registry_http,
            manager_client=manager_http,
            github_client=github_http,
        )
    return result, calls


def registry_routes(schema=(200, {"nodes": {QUERY: {"input": {}}}})):
    return {
        EXACT: (200, {"node": {
            "id": PACK, "name": PACK, "latest_version": "1.2.3",
            "repository": "https://github.com/example/probe-pack",
        }}),
        VERSIONS: (200, [{"version": "1.2.3"}]),
        SCHEMA: schema,
    }


@pytest.mark.parametrize("failure", [(401, {}), (403, {}), (200, b"not JSON"), httpx.ConnectError])
def test_registry_schema_failure_retains_candidate(tmp_path, failure):
    # A schema failure does not erase the package identity already found.
    result, calls = run(tmp_path, registry=registry_routes(failure))
    candidate = next(c for c in result.candidates if c.ref.slug == PACK)
    assert candidate.ref.version == "1.2.3"
    assert candidate.ref.url == "https://github.com/example/probe-pack"
    assert candidate.warnings
    if isinstance(failure, tuple) and failure[0] in {401, 403}:
        assert any(str(failure[0]) in warning for warning in candidate.warnings)
    assert not candidate.provisional_schema
    assert candidate.runnable is False
    assert result.source_tier_status["comfy-registry"] == "degraded"
    assert calls["github"]


@pytest.mark.parametrize("failure", [(401, {}), (503, {}), (200, b"not JSON"), httpx.ConnectError])
def test_manager_failure_is_not_a_negative_lookup(tmp_path, failure):
    manager = {
        resolver.MANAGER_NODE_MAP_URL: failure,
        resolver.MANAGER_EXTENSION_MAP_URL: failure,
        resolver.MANAGER_NODE_LIST_URL: failure,
    }
    result, calls = run(tmp_path, registry=registry_routes(), manager=manager)
    assert result.source_tier_status["comfyui-manager"] == "unavailable"
    assert result.source_tier_status["comfy-registry"] == "matched"
    assert any(c.ref.slug == PACK for c in result.candidates)
    assert calls["registry"] and calls["github"]
    assert result.to_dict()["source_tier_status"]["comfyui-manager"] == "unavailable"


def test_completed_empty_search_is_no_match(tmp_path):
    result, _ = run(tmp_path)
    assert result.candidates == ()
    assert result.to_dict()["source_tier_status"] == {
        "comfyui-manager": "no_match",
        "comfy-registry": "no_match",
        "github": "no_match",
    }
    assert result.runnable is False


def test_cache_write_failure_keeps_fetched_evidence(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise PermissionError("recorded read-only cache")

    monkeypatch.setattr(resolver, "_atomic_write_json", fail)
    result, _ = run(tmp_path, registry=registry_routes())
    candidate = next(c for c in result.candidates if c.ref.slug == PACK)
    assert candidate.expected_classes == (QUERY,)
    assert candidate.provisional_schema
    assert result.source_tier_status["comfy-registry"] == "degraded"
    assert any("cache write" in warning for warning in result.warnings)


def test_github_bad_json_isolated(tmp_path):
    github = {
        f"{resolver.GITHUB_API_BASE_URL}/search/code": (200, b"not JSON"),
        f"{resolver.GITHUB_API_BASE_URL}/search/repositories": httpx.ConnectError,
    }
    result, calls = run(tmp_path, registry=registry_routes(), github=github)
    assert result.source_tier_status["github"] == "unavailable"
    assert any(c.ref.slug == PACK for c in result.candidates)
    assert len(calls["github"]) == 2


def test_missing_manager_feeds_stay_unavailable_on_warm_cache(tmp_path):
    manager = {
        resolver.MANAGER_NODE_MAP_URL: (404, {}),
        resolver.MANAGER_EXTENSION_MAP_URL: (404, {}),
        resolver.MANAGER_NODE_LIST_URL: (404, {}),
    }
    first, _ = run(tmp_path, manager=manager)
    second, calls = run(tmp_path, manager=manager)
    assert first.source_tier_status["comfyui-manager"] == "unavailable"
    assert second.source_tier_status["comfyui-manager"] == "unavailable"
    assert not calls["manager"]
