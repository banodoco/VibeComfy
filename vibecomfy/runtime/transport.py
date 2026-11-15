"""A reusable Comfy transport and isolated, single-submit attempts."""
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
import websockets

from .client import _raise_for_status_with_body


class _HTTPGeneration:
    """A pool retired on websocket loss after its in-flight requests finish."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.inflight = 0
        self.retired = False
        self.closing: asyncio.Task[Any] | None = None
        self.closed = asyncio.Event()

    def retire(self) -> None:
        self.retired = True
        self._close_when_idle()

    def _close_when_idle(self) -> None:
        if self.retired and not self.inflight and self.closing is None:
            self.closing = asyncio.create_task(self._close())

    async def _close(self) -> None:
        try:
            await self.client.__aexit__(None, None, None)
        finally:
            self.closed.set()

    @asynccontextmanager
    async def request(self):
        self.inflight += 1
        try:
            yield self.client
        finally:
            self.inflight -= 1
            self._close_when_idle()

    async def close(self) -> None:
        self.retire()
        await self.closed.wait()
        if self.closing is not None:
            await self.closing


class ComfyTransport:
    """Hold one HTTP pool and websocket per live target generation.

    Socket loss retires that pair and wakes outstanding attempts to reconcile.
    An in-flight POST retains its retired pool until its response is known; it
    is never repeated. Reconciliation uses separate HTTP connections and does
    not establish that a restarted listener is the same server incarnation.
    """

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url.rstrip('/')
        self.client_id: str | None = None
        self.generation = 0
        self._http: _HTTPGeneration | None = None
        self._pools: list[_HTTPGeneration] = []
        self._socket: Any = None
        self._reader: asyncio.Task[Any] | None = None
        self._lock = asyncio.Lock()
        self._submit_lock = asyncio.Lock()
        self._waiters: dict[str, asyncio.Future[bool]] = {}
        self._early: set[str] = set()
        self._posting = 0
        self.progress: dict[str, Any] = {}

    async def _connect(self) -> None:
        async with self._lock:
            if self._socket is not None:
                return
            client = await httpx.AsyncClient(timeout=30).__aenter__()
            pool = _HTTPGeneration(client)
            client_id = uuid.uuid4().hex
            parts = urlsplit(self.server_url)
            url = urlunsplit(('wss' if parts.scheme == 'https' else 'ws', parts.netloc,
                              parts.path.rstrip('/') + '/ws', urlencode({'clientId': client_id}), ''))
            socket = None
            try:
                socket = await websockets.connect(url)
                first = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
                if not isinstance(first, dict) or first.get('type') != 'status':
                    raise RuntimeError('Comfy websocket did not send its initial status')
            except BaseException:
                if socket is not None:
                    await socket.close()
                await pool.close()
                raise
            self.client_id = client_id
            self._http = pool
            self._pools = [old for old in self._pools if not old.closed.is_set()]
            self._pools.append(pool)
            self._socket = socket
            self._reader = asyncio.create_task(self._read(socket, pool))

    async def _read(self, socket: Any, pool: _HTTPGeneration) -> None:
        try:
            async for raw in socket:
                if not isinstance(raw, str):
                    # Standard binary previews do not identify their prompt.
                    self.progress['_preview'] = raw
                    continue
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                data = event.get('data')
                if not isinstance(data, dict):
                    continue
                prompt_id = data.get('prompt_id')
                if prompt_id is None:
                    continue
                prompt_id = str(prompt_id)
                if (event.get('type') == 'executing' and
                        'node' in data and data['node'] is None):
                    waiter = self._waiters.get(prompt_id)
                    if waiter is not None and not waiter.done():
                        waiter.set_result(True)
                    elif self._posting and len(self._early) < 256:
                        self._early.add(prompt_id)
                elif prompt_id in self._waiters:
                    self.progress[prompt_id] = event
        except Exception:
            pass
        finally:
            self.generation += 1
            self._socket = None
            self._http = None
            pool.retire()
            self._early.clear()
            for waiter in self._waiters.values():
                if not waiter.done():
                    waiter.set_result(False)

    def attempt(self) -> 'ComfyAttempt':
        return ComfyAttempt(self)

    async def close(self) -> None:
        if self._socket is not None:
            await self._socket.close()
        if self._reader is not None:
            await asyncio.gather(self._reader, return_exceptions=True)
            self._reader = None
        for pool in self._pools:
            await pool.close()
        self._pools.clear()


class ComfyAttempt:
    def __init__(self, transport: ComfyTransport) -> None:
        self.transport = transport
        self.server_url = transport.server_url
        self._posted = False
        self._prompt_id: str | None = None
        self._waiter: asyncio.Future[bool] | None = None
        self._generation: int | None = None
        self._pool: _HTTPGeneration | None = None

    async def _post_prompt(self, prompt: dict[str, Any]) -> dict[str, Any]:
        if self._posted:
            raise RuntimeError('an attempt may submit only one prompt')
        self._posted = True
        t = self.transport
        async with t._submit_lock:
            await t._connect()
            generation, pool, client_id = t.generation, t._http, t.client_id
            assert pool is not None and client_id is not None
            self._generation, self._pool = generation, pool
            t._posting += 1
            try:
                async with pool.request() as client:
                    response = await client.post(f'{self.server_url}/prompt', json={'prompt': prompt, 'client_id': client_id})
                _raise_for_status_with_body(response, max_chars=600)
                result = response.json()
                raw_prompt_id = result.get('prompt_id')
                prompt_id = str(raw_prompt_id) if raw_prompt_id is not None else None
                if prompt_id and prompt_id.strip():
                    self._prompt_id = prompt_id
                    self._waiter = asyncio.get_running_loop().create_future()
                    if generation != t.generation:
                        self._waiter.set_result(False)
                    elif prompt_id in t._early:
                        t._early.discard(prompt_id)
                        self._waiter.set_result(True)
                    t._waiters[prompt_id] = self._waiter
                return result
            finally:
                t._posting -= 1
                if not t._posting:
                    t._early.clear()

    async def history_ready(self, prompt_id: str) -> bool:
        if prompt_id != self._prompt_id or self._waiter is None:
            raise RuntimeError('prompt does not belong to this attempt')
        return await self._waiter

    async def history(self, prompt_id: str) -> dict[str, Any]:
        if prompt_id != self._prompt_id:
            raise RuntimeError('prompt does not belong to this attempt')
        t = self.transport
        if self._generation == t.generation and self._pool is not None and not self._pool.retired:
            async with self._pool.request() as client:
                response = await client.get(f'{self.server_url}/history/{prompt_id}')
        else:
            # Old-generation, known-ID reconciliation is independent of the
            # new live pool. The caller bounds each request by the job deadline.
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(f'{self.server_url}/history/{prompt_id}')
        _raise_for_status_with_body(response)
        return response.json()

    def release(self) -> None:
        if self._prompt_id is not None:
            self.transport._waiters.pop(self._prompt_id, None)
            self.transport.progress.pop(self._prompt_id, None)
