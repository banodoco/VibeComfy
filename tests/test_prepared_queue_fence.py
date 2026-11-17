"""Lead LS-4 probes: record data must never supply queue authority."""
from __future__ import annotations

import asyncio
from dataclasses import fields

import pytest

from tests.test_prepared_workflow import context, tiny
from vibecomfy.prepared import PreparedProjectionRecord, PreparedWorkflowSession
from vibecomfy.runtime.execution import queue_server_prompt
from vibecomfy.testing.canonical import canonical_digest
from vibecomfy.workflow_bundle import WorkflowBundleError


INJECTED = {"999": {"class_type": "InjectedNode", "inputs": {"unapproved": True}}}


def issued(session_type=PreparedWorkflowSession):
    bundle, provider = tiny()
    ctx = context()
    session = session_type(ctx)
    handle = session.prepare(bundle, inputs={"seed": 7}, schema_provider=provider)
    record, frozen = session.fill(handle, {"seed": 9}, attempt_id="attack-probe", context=ctx)
    return session, record, frozen


def assert_refused_before_post(attack, *, target=None):
    sent = []

    class Client:
        server_url = target or context().target_identity

        async def _post_prompt(self, payload):
            sent.append(payload)
            return {"prompt_id": "unapproved-prompt", "node_errors": {}}

    with pytest.raises(WorkflowBundleError):
        record, bundle = attack()
        asyncio.run(queue_server_prompt(record, bundle, client=Client()))
    assert sent == []


def test_public_constructor_with_fake_session_cannot_queue():
    def attack():
        _, record, bundle = issued()

        class FakeSession:
            def authorize(self, *_args):
                return INJECTED

            def require_target(self, *_args):
                pass

        values = {item.name: getattr(record, item.name) for item in fields(record)}
        values.update(_session=FakeSession(), api_projection=INJECTED,
                      api_digest=canonical_digest(INJECTED))
        return PreparedProjectionRecord(**values), bundle

    assert_refused_before_post(attack)


def test_session_subclass_cannot_override_queue_authorization():
    def attack():
        class FakeSession(PreparedWorkflowSession):
            def authorize(self, *_args):
                return INJECTED

        _, record, bundle = issued(FakeSession)
        return record, bundle

    assert_refused_before_post(attack)


@pytest.mark.parametrize("swap_record_digest", [False, True])
def test_swapped_projection_cannot_queue_even_with_matching_record_digest(swap_record_digest):
    def attack():
        _, record, bundle = issued()
        object.__setattr__(record, "api_projection", INJECTED)
        if swap_record_digest:
            object.__setattr__(record, "api_digest", canonical_digest(INJECTED))
        return record, bundle

    assert_refused_before_post(attack)


def test_unregistered_exact_session_cannot_reuse_issued_authority():
    def attack():
        session, record, bundle = issued()
        fake = object.__new__(PreparedWorkflowSession)
        fake.__dict__.update(session.__dict__)
        object.__setattr__(record, "_session", fake)
        object.__setattr__(record, "api_projection", INJECTED)
        object.__setattr__(record, "api_digest", canonical_digest(INJECTED))
        return record, bundle

    assert_refused_before_post(attack)


def test_instance_authorize_override_cannot_bypass_issued_digest():
    def attack():
        session, record, bundle = issued()
        session.authorize = lambda *_args: INJECTED
        object.__setattr__(record, "api_projection", INJECTED)
        object.__setattr__(record, "api_digest", canonical_digest(INJECTED))
        return record, bundle

    assert_refused_before_post(attack)


def test_instance_target_override_cannot_queue_on_another_target():
    def attack():
        session, record, bundle = issued()
        session.require_target = lambda *_args: None
        return record, bundle

    assert_refused_before_post(attack, target="http://wrong-target.invalid:8188")


def test_record_subclass_cannot_enter_the_ordinary_approval_path():
    def attack():
        _, record, bundle = issued()

        class FakeRecord(PreparedProjectionRecord):
            def assert_matches(self, *_args, **_kwargs):
                pass

        fake = object.__new__(FakeRecord)
        for item in fields(record):
            object.__setattr__(fake, item.name, getattr(record, item.name))
        # Keep the final-sink shape valid to reach the ordinary path's fence.
        payload = record.to_dict()["api_projection"]
        payload["1"]["inputs"]["seed"] = 999
        object.__setattr__(fake, "api_projection", payload)
        object.__setattr__(fake, "api_digest", canonical_digest(payload))
        return fake, bundle

    assert_refused_before_post(attack)
