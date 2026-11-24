"""LE-9 explicit model declaration resolution, without downloading model bytes."""
from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

import httpx

from vibecomfy.fetch import _relative_asset_path

_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
_SIZE = re.compile(r"[0-9]+")
_REDIRECTS = {301, 302, 303, 307, 308}


def _https_source(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.fragment):
        raise ValueError("--add-model source must be credential-free HTTPS")
    # Accessing port validates malformed ports before any network request.
    _ = parsed.port
    return url


def _parse_declaration(declaration: str) -> dict:
    dest, sep, source = declaration.partition("=")
    if not sep:
        raise ValueError("--add-model requires DEST=URL#SHA256")
    parsed = urlsplit(source)
    if not _SHA256.fullmatch(parsed.fragment):
        raise ValueError("--add-model requires a full SHA-256 digest")
    url = _https_source(urlunsplit(parsed._replace(fragment="")))
    subdir, slash, name = dest.partition("/")
    if not slash or not subdir or not name or any(part in ("", ".", "..") for part in dest.split("/")):
        raise ValueError("--add-model destination must be a model folder and relative filename")
    _relative_asset_path(subdir, field="subdir")
    _relative_asset_path(name, field="name")
    _relative_asset_path(dest, field="destination")
    return {"name": name, "subdir": subdir, "url": url, "sha256": parsed.fragment.lower()}


def _head_size(url: str, client: httpx.Client) -> int:
    # Redirects get no inherited credentials and must remain HTTPS. No GET
    # fallback: the declaration is only an observed size, never downloaded bytes.
    for hop in range(6):
        response = client.head(url, follow_redirects=False, timeout=10,
                               headers={"Accept-Encoding": "identity"})
        if response.status_code in _REDIRECTS:
            location = response.headers.get("location")
            if not location or hop == 5:
                raise ValueError("--add-model HEAD redirect could not be resolved")
            url = _https_source(str(response.url.join(location)))
            continue
        response.raise_for_status()
        size = response.headers.get("content-length", "")
        if (response.status_code != 200 or response.headers.get("content-range") is not None
                or response.headers.get("content-encoding", "identity").casefold() != "identity"
                or not _SIZE.fullmatch(size) or int(size) <= 0):
            raise ValueError("--add-model HEAD requires a positive complete content length")
        return int(size)
    raise AssertionError("bounded HEAD loop did not return or refuse")


def resolve_added_model_assets(
    declarations: Iterable[str], *, client: httpx.Client | None = None,
) -> list[dict]:
    """Resolve each explicit destination/URL/digest to a canonical model row.

    Parse the entire batch before contacting any source. Size is a HEAD
    observation; the supplied SHA-256 remains unverified until normal fetch
    custody checks the actual model bytes. No files or entries are written.
    """
    rows = [_parse_declaration(declaration) for declaration in declarations]
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["subdir"], row["name"])
        if key in seen:
            raise ValueError(f"duplicate --add-model destination: {key[0]}/{key[1]}")
        seen.add(key)
    if not rows:
        return []

    def resolve(http: httpx.Client) -> list[dict]:
        return [{**row, "size_bytes": _head_size(row["url"], http)} for row in rows]

    if client is not None:
        return resolve(client)
    with httpx.Client() as http:
        return resolve(http)
