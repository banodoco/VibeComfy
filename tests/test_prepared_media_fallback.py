"""LS-4: prepared filename limits defer supported jobs to full preparation."""
from __future__ import annotations

import pytest

from tests.test_prepared_workflow import context, tiny
from vibecomfy.prepared import PreparedWorkflowSession, PreparedWorkflowUnavailable
from vibecomfy.workflow_bundle import load_bundle


@pytest.mark.parametrize("entry", ["prepare", "cached_prepare", "accepts", "fill"])
def test_prepared_media_colon_uses_full_path(entry):
    bundle, provider = tiny()
    bundle.workflow.inputs["text"].media_semantics = "image"
    bundle = load_bundle(bundle.workflow)
    values = {"text": "img:1.png"}

    # This prepared-only bound must not replace the ordinary compiler's policy.
    full = bundle.compile(run_inputs=values, schema_provider=provider)
    assert full.api_projection["1"]["inputs"]["text"] == "img:1.png"

    session = PreparedWorkflowSession(context())
    if entry == "prepare":
        with pytest.raises(PreparedWorkflowUnavailable, match="prepared filename"):
            session.prepare(bundle, inputs=values, schema_provider=provider)
        return

    handle = session.prepare(bundle, inputs={"text": "img1.png"}, schema_provider=provider)
    if entry == "cached_prepare":
        with pytest.raises(PreparedWorkflowUnavailable, match="prepared filename"):
            session.prepare(bundle, inputs=values, schema_provider=provider)
    elif entry == "accepts":
        assert session.accepts(handle, values) is False
    else:
        with pytest.raises(PreparedWorkflowUnavailable, match="prepared filename"):
            session.fill(handle, values, attempt_id="colon-media", context=context())
