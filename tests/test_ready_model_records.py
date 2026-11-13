"""Every downloadable ready asset is a complete, immutable offline record."""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit

import pytest

from vibecomfy.registry.ready import repo_ready_template_discovery
from vibecomfy.registry.static_contract import extract_ready_template_contract


@pytest.mark.parametrize("record", repo_ready_template_discovery().records,
                         ids=lambda record: record.template_id)
def test_every_downloadable_ready_model_is_pinned(record):
    for asset in extract_ready_template_contract(record.path)["model_assets"]:
        if not asset.get("url"):
            continue
        label = f"{record.template_id}: {asset['subdir']}/{asset['name']}"
        assert re.fullmatch(r"[0-9a-f]{40}", asset.get("hf_revision") or ""), label
        assert re.fullmatch(r"[0-9a-f]{64}", asset.get("sha256") or ""), label
        assert type(asset.get("size_bytes")) is int and asset["size_bytes"] > 0, label
        parts = PurePosixPath(urlsplit(asset["url"]).path).parts
        assert parts[3:5] == ("resolve", asset["hf_revision"]), label


def test_music_record_is_the_authored_download_record():
    from vibecomfy.model_records import ready_model_records

    records = ready_model_records("audio/ace_step_1_5_t2a_song")
    record = next(row for row in records if row.destination == "text_encoders/qwen_0.6b_ace15.safetensors")
    assert record.url == (
        f"https://huggingface.co/{record.repository}/resolve/{record.revision}/{record.path}")
    assert record.bytes > 0 and len(record.sha256) == 64
