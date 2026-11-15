import asyncio
import json

import pytest

from vibecomfy.runtime import transport as module
from vibecomfy.runtime.session import _wait_for_server_history, SessionConfig


class Socket:
    def __init__(self):
        self.messages = asyncio.Queue()
        self.messages.put_nowait(json.dumps({'type': 'status', 'data': {}}))
    async def recv(self):
        return await self.messages.get()
    def __aiter__(self):
        return self
    async def __anext__(self):
        item = await self.messages.get()
        if item is None:
            raise StopAsyncIteration
        return item
    async def close(self):
        self.messages.put_nowait(None)
    def event(self, prompt, kind='executing', **fields):
        self.messages.put_nowait(json.dumps({'type': kind, 'data': {'prompt_id': prompt, **fields}}))


class Response:
    def __init__(self, data):
        self.data = data
    def raise_for_status(self):
        pass
    def json(self):
        return self.data


def test_transport_dispatch_and_reconnect(monkeypatch):
    async def case():
        sockets, posts, gets = [], [], []
        async def connect(url):
            sockets.append(Socket())
            return sockets[-1]
        class HTTP:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def post(self, url, json):
                assert sockets and sockets[-1].messages.empty()
                posts.append(json)
                return Response({'prompt_id': f'p{len(posts)}'})
            async def get(self, url):
                gets.append(url)
                pid = url.rsplit('/', 1)[-1]
                return Response({pid: {'outputs': {}, 'status': {'status_str': 'success', 'completed': True, 'messages': []}}})
        monkeypatch.setattr(module.websockets, 'connect', connect)
        monkeypatch.setattr(module.httpx, 'AsyncClient', HTTP)
        t = module.ComfyTransport('http://example')
        a, b = t.attempt(), t.attempt()
        await asyncio.gather(a._post_prompt({}), b._post_prompt({}))
        assert len(sockets) == 1 and all(p['client_id'] == t.client_id for p in posts)
        with pytest.raises(RuntimeError, match='only one'):
            await a._post_prompt({})
        for i in range(1000):
            sockets[0].event('p1', 'progress', value=i)
        sockets[0].event('p2', node=None)
        sockets[0].event('p1', node=None)
        async def no_sleep(*args, **kwargs):
            raise AssertionError('healthy path slept')
        monkeypatch.setattr(asyncio, 'sleep', no_sleep)
        histories = await asyncio.gather(*(_wait_for_server_history(t.server_url, p, config=SessionConfig(), client=x) for p, x in [('p1', a), ('p2', b)]))
        assert len(gets) == 2 and set(histories[0]) == {'p1'} and set(histories[1]) == {'p2'}
        assert t.progress['p1']['data']['value'] == 999
        a.release(); b.release()
        c = t.attempt()
        await c._post_prompt({})
        await sockets[0].close()
        assert await c.history_ready('p3') is False
        assert t.generation == 1
        await _wait_for_server_history(t.server_url, 'p3', config=SessionConfig(), client=c)
        d = t.attempt()
        await d._post_prompt({})
        assert len(sockets) == 2 and len(posts) == 4
        c.release(); d.release()
        await t.close()
    asyncio.run(case())


@pytest.mark.parametrize('status,outputs,raises', [
    ({'status_str': 'success', 'completed': True, 'messages': []}, {'9': {'images': [{'filename': 'cached.png'}]}}, None),
    ({'status_str': 'error', 'completed': False, 'messages': [['execution_error', {'exception_message': 'bad node'}]]}, {}, 'bad node'),
    ({'status_str': 'error', 'completed': False, 'messages': [['execution_interrupted', {}]]}, {}, 'failed'),
])
def test_history_ready_preserves_terminal_results(monkeypatch, status, outputs, raises):
    from vibecomfy.errors import RuntimeNodeError
    async def case():
        class Client:
            calls = 0
            async def history_ready(self, pid): return True
            async def history(self, pid):
                self.calls += 1
                return {pid: {'status': status, 'outputs': outputs}}
        async def no_sleep(*args, **kwargs):
            raise AssertionError('healthy path slept')
        monkeypatch.setattr(asyncio, 'sleep', no_sleep)
        client = Client()
        if raises:
            with pytest.raises(RuntimeNodeError, match=raises):
                await _wait_for_server_history('http://example', 'p', config=SessionConfig(), client=client)
        else:
            result = await _wait_for_server_history('http://example', 'p', config=SessionConfig(), client=client)
            assert result['p']['outputs'] == outputs
        assert client.calls == 1
    asyncio.run(case())


def test_completion_requires_owned_prompt_and_explicit_null_node(monkeypatch):
    async def case():
        socket = Socket()
        async def connect(url): return socket
        class HTTP:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def post(self, *args, **kwargs): return Response({'prompt_id': 'owned'})
        monkeypatch.setattr(module.websockets, 'connect', connect)
        monkeypatch.setattr(module.httpx, 'AsyncClient', HTTP)
        t = module.ComfyTransport('http://example')
        attempt = t.attempt()
        await attempt._post_prompt({})
        waiter = asyncio.create_task(attempt.history_ready('owned'))
        for event in [[], {'type': 'executing', 'data': []},
                      {'type': 'executing', 'data': {'prompt_id': 'owned'}},
                      {'type': 'executing', 'data': {'prompt_id': 'other', 'node': None}}]:
            socket.messages.put_nowait(json.dumps(event))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not waiter.done()
        socket.event('owned', node=None)
        assert await waiter is True
        attempt.release()
        await t.close()
    asyncio.run(case())


def test_drop_during_post_reconciles_without_resubmission_and_reconnects(monkeypatch):
    async def case():
        sockets, clients, posts, gets = [], [], [], []
        started, response_ready = asyncio.Event(), asyncio.Event()
        async def connect(url):
            sockets.append(Socket())
            return sockets[-1]
        class HTTP:
            def __init__(self, **kwargs):
                self.closed = False
                clients.append(self)
            async def __aenter__(self): return self
            async def __aexit__(self, *args): self.closed = True
            async def post(self, url, json):
                posts.append((self, json))
                if len(posts) == 1:
                    started.set()
                    await response_ready.wait()
                return Response({'prompt_id': f'p{len(posts)}'})
            async def get(self, url):
                gets.append(self)
                pid = url.rsplit('/', 1)[-1]
                return Response({pid: {'outputs': {}, 'status': {'status_str': 'success', 'completed': True, 'messages': []}}})
        monkeypatch.setattr(module.websockets, 'connect', connect)
        monkeypatch.setattr(module.httpx, 'AsyncClient', HTTP)
        t = module.ComfyTransport('http://example')
        attempt = t.attempt()
        posting = asyncio.create_task(attempt._post_prompt({}))
        await started.wait()
        old_client, old_id = posts[0][0], posts[0][1]['client_id']
        await sockets[0].close()
        await t._reader
        assert t.generation == 1 and not old_client.closed
        response_ready.set()
        assert (await posting)['prompt_id'] == 'p1'
        assert await attempt.history_ready('p1') is False
        with pytest.raises(RuntimeError, match='only one'):
            await attempt._post_prompt({})
        assert len(posts) == 1
        other = t.attempt()
        await other._post_prompt({})
        assert len(sockets) == 2 and posts[1][0] is not old_client
        assert posts[1][1]['client_id'] != old_id
        await _wait_for_server_history(t.server_url, 'p1', config=SessionConfig(), client=attempt)
        assert gets[0] is not old_client and gets[0] is not posts[1][0]
        assert len(posts) == 2
        attempt.release(); other.release()
        await t.close()
        assert all(client.closed for client in clients)
    asyncio.run(case())


def test_lost_post_acknowledgement_never_resubmits(monkeypatch):
    async def case():
        socket, posts = Socket(), []
        async def connect(url): return socket
        class HTTP:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def post(self, *args, **kwargs):
                posts.append(1)
                await socket.close()
                raise module.httpx.ReadError('acknowledgement lost')
        monkeypatch.setattr(module.websockets, 'connect', connect)
        monkeypatch.setattr(module.httpx, 'AsyncClient', HTTP)
        t = module.ComfyTransport('http://example')
        attempt = t.attempt()
        with pytest.raises(module.httpx.ReadError, match='acknowledgement lost') as failure:
            await attempt._post_prompt({})
        from tests._runtime_session_helpers import _approved, _workflow
        from vibecomfy.runtime.session import _runtime_failure_evidence
        record, _ = _approved(_workflow())
        evidence = _runtime_failure_evidence(
            record, adapter_kind='external', backend='api', endpoint=t.server_url,
            schema_provenance=None, queue_acceptance={'status': 'not_attempted', 'prompt_id': None},
            phase='queue', exc=failure.value, queue_started=True,
        )
        assert evidence['queue_acceptance'] == {'status': 'unknown', 'prompt_id': None}
        assert evidence['terminal']['acceptance_known'] is False
        with pytest.raises(RuntimeError, match='only one'):
            await attempt._post_prompt({})
        assert len(posts) == 1
        await t.close()
    asyncio.run(case())


@pytest.mark.parametrize('terminal,status,outputs,raises', [
    ('execution_cached', {'status_str': 'success', 'completed': True, 'messages': []}, {'9': {'images': [{'filename': 'cached.png'}]}}, None),
    ('execution_error', {'status_str': 'error', 'completed': False, 'messages': [['execution_error', {'exception_message': 'bad node'}]]}, {}, 'bad node'),
    ('execution_interrupted', {'status_str': 'error', 'completed': False, 'messages': [['execution_interrupted', {}]]}, {}, 'failed'),
])
def test_terminal_event_waits_for_history_ready(monkeypatch, terminal, status, outputs, raises):
    from vibecomfy.errors import RuntimeNodeError
    async def case():
        socket, gets = Socket(), []
        async def connect(url): return socket
        class HTTP:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def post(self, *args, **kwargs): return Response({'prompt_id': 'p'})
            async def get(self, url):
                gets.append(url)
                return Response({'p': {'status': status, 'outputs': outputs}})
        monkeypatch.setattr(module.websockets, 'connect', connect)
        monkeypatch.setattr(module.httpx, 'AsyncClient', HTTP)
        t = module.ComfyTransport('http://example')
        attempt = t.attempt()
        await attempt._post_prompt({})
        task = asyncio.create_task(_wait_for_server_history(t.server_url, 'p', config=SessionConfig(), client=attempt))
        socket.event('p', terminal)
        socket.event('p', 'execution_success')
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done() and not gets
        async def no_sleep(*args, **kwargs): raise AssertionError('healthy path slept')
        monkeypatch.setattr(asyncio, 'sleep', no_sleep)
        socket.event('p', node=None)
        if raises:
            with pytest.raises(RuntimeNodeError, match=raises): await task
        else:
            assert (await task)['p']['outputs'] == outputs
        assert len(gets) == 1
        attempt.release()
        await t.close()
    asyncio.run(case())


def test_injected_factories_cover_reconnect_and_reconciliation(monkeypatch):
    async def case():
        sockets, contexts, posts, gets = [], [], [], []
        class Client:
            async def post(self, url, json):
                posts.append(json)
                return Response({'prompt_id': f'p{len(posts)}'})
            async def get(self, url):
                gets.append(url)
                return Response({'p1': {'status': {'status_str': 'success', 'completed': True, 'messages': []}, 'outputs': {}}})
        class Context:
            def __init__(self):
                self.closed = False
                contexts.append(self)
            async def __aenter__(self): return Client()
            async def __aexit__(self, *args): self.closed = True
        async def connect(url):
            assert 'clientId=' in url
            sockets.append(Socket())
            return sockets[-1]
        monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: pytest.fail('raw HTTP fallback'))
        monkeypatch.setattr(module.websockets, 'connect', lambda url: pytest.fail('raw websocket fallback'))
        transport = module.ComfyTransport('http://example', http_factory=Context, websocket_connect=connect)
        first = transport.attempt()
        await first._post_prompt({})
        await sockets[0].close()
        assert await first.history_ready('p1') is False
        second = transport.attempt()
        await second._post_prompt({})
        assert len(contexts) == 2 and len(sockets) == 2
        await _wait_for_server_history(transport.server_url, 'p1', config=SessionConfig(), client=first)
        assert len(contexts) == 3 and len(gets) == 1 and len(posts) == 2
        assert contexts[2].closed
        first.release(); second.release()
        await transport.close()
        assert all(context.closed for context in contexts)
    asyncio.run(case())


def test_refused_websocket_has_no_post_or_fallback(monkeypatch):
    async def case():
        posts, closed = [], []
        class Context:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): closed.append(True)
            async def post(self, *args, **kwargs): posts.append(True)
        async def refuse(url): raise ValueError('redirect refused')
        monkeypatch.setattr(module.websockets, 'connect', lambda url: pytest.fail('websocket fallback'))
        transport = module.ComfyTransport('http://example', http_factory=Context, websocket_connect=refuse)
        attempt = transport.attempt()
        with pytest.raises(ValueError, match='redirect refused'):
            await attempt._post_prompt({})
        assert not posts and closed == [True]
        with pytest.raises(RuntimeError, match='only one'):
            await attempt._post_prompt({})
        await transport.close()
    asyncio.run(case())


def test_events_are_coalesced_prompt_scoped_and_nonblocking(monkeypatch):
    async def case():
        socket = Socket()
        async def connect(url): return socket
        class HTTP:
            count = 0
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def post(self, url, json):
                HTTP.count += 1
                return Response({'prompt_id': f'p{HTTP.count}'})
        monkeypatch.setattr(module.websockets, 'connect', connect)
        monkeypatch.setattr(module.httpx, 'AsyncClient', HTTP)
        t = module.ComfyTransport('http://example')
        a, b = t.attempt(), t.attempt()
        await a._post_prompt({}); await b._post_prompt({})
        for value in range(1000):
            socket.event('p1', 'progress', value=value)
        socket.event('unowned', 'progress', value='private')
        socket.event('p2', 'progress', value=22)
        socket.messages.put_nowait(b'preview-without-prompt')
        socket.event('p1', node=None)
        assert await asyncio.wait_for(a.history_ready('p1'), timeout=1) is True
        assert (await a.next_event())['data']['value'] == 999
        assert (await b.next_event())['data']['value'] == 22
        assert t.unattributed_preview == b'preview-without-prompt'
        pending = asyncio.create_task(b.next_event())
        await asyncio.sleep(0)
        assert not pending.done()
        b.release()
        assert await pending is None and await b.next_event() is None
        a.release()
        await t.close()
    asyncio.run(case())


@pytest.mark.parametrize('fail_prompt,fail_cleanup', [(False, False), (True, False), (True, True)])
def test_injected_attempt_cleanup_preserves_owner_and_primary_error(monkeypatch, tmp_path, fail_prompt, fail_cleanup):
    import importlib
    from contextlib import asynccontextmanager
    from tests._runtime_session_helpers import _approved, _workflow
    from vibecomfy.errors import QueueError
    runtime = importlib.import_module('vibecomfy.runtime.run')
    url = 'http://127.0.0.1:8188'
    calls = []
    @asynccontextmanager
    async def server(*, server_url, log_path, config):
        yield url
    class Client:
        server_url = url
        async def _post_prompt(self, prompt):
            if fail_prompt: raise ValueError('primary failure')
            return {'prompt_id': 'owned'}
        async def history(self, prompt_id):
            return {prompt_id: {'status': {'status_str': 'success', 'completed': True, 'messages': []}, 'outputs': {}}}
        async def release_attempt(self):
            calls.append('release')
            if fail_cleanup: raise ValueError('cleanup failure')
        async def close(self):
            calls.append('close')
    client = Client()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runtime, 'comfy_server', server)
    monkeypatch.setattr(runtime, '_build_schema_provider', lambda *_: None)
    record, bundle = _approved(_workflow())
    if fail_prompt:
        with pytest.raises(QueueError, match='primary failure') as error:
            asyncio.run(runtime.run(record, bundle, server_url=url, server_client=client))
        if fail_cleanup:
            assert any('cleanup failure' in note for note in error.value.__notes__)
    else:
        result = asyncio.run(runtime.run(record, bundle, server_url=url, server_client=client))
        assert result.prompt_id == 'owned'
    assert calls == ['release']


def test_release_during_post_does_not_register_or_resubmit(monkeypatch):
    async def case():
        socket, started, reply = Socket(), asyncio.Event(), asyncio.Event()
        async def connect(url): return socket
        class HTTP:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def post(self, url, json):
                started.set()
                await reply.wait()
                return Response({'prompt_id': 'accepted'})
        monkeypatch.setattr(module.websockets, 'connect', connect)
        monkeypatch.setattr(module.httpx, 'AsyncClient', HTTP)
        t = module.ComfyTransport('http://example')
        attempt = t.attempt()
        posting = asyncio.create_task(attempt._post_prompt({}))
        await started.wait()
        event = asyncio.create_task(attempt.next_event())
        await asyncio.sleep(0)
        attempt.release()
        assert await event is None
        reply.set()
        assert (await posting)['prompt_id'] == 'accepted'
        assert not t._waiters and not t._event_queues
        with pytest.raises(RuntimeError, match='released'):
            await attempt._post_prompt({})
        await t.close()
    asyncio.run(case())


def test_injected_attempt_released_on_early_validation_error():
    import importlib
    from vibecomfy.workflow_bundle import WorkflowBundleError
    runtime = importlib.import_module('vibecomfy.runtime.run')
    class Client:
        server_url = 'http://127.0.0.1:1'
        released = False
        def release_attempt(self): self.released = True
    client = Client()
    with pytest.raises(WorkflowBundleError, match='selected server_url'):
        asyncio.run(runtime.run(None, None, server_url='http://127.0.0.1:2', server_client=client))
    assert client.released
