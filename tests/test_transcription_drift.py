"""Transcription declares portable pins and participates in strict drift."""
from copy import deepcopy

import pytest

from vibecomfy import resources
from vibecomfy.custom_node_refs import workflow_lock_entries
from vibecomfy.errors import DriftError
from vibecomfy.node_packs import get_known_node_packs, read_lockfile, write_lockfile
from vibecomfy.porting import object_info
from vibecomfy.registry.ready import workflow_from_ready
from vibecomfy.runtime import drift


def test_transcription_discovery_agrees_with_runtime_and_pack_lock(tmp_path):
    workflow = workflow_from_ready('audio/transcribe')
    shipped, = [entry for entry in read_lockfile() if entry.name == 'ComfyUI-Whisper']
    assert workflow.requirements.custom_nodes == ['ComfyUI-Whisper']
    assert workflow_lock_entries(workflow) == [shipped]
    pack, = [pack for pack in get_known_node_packs(tmp_path / "missing.lock") if pack.name == shipped.name]
    assert pack.class_schema_sha256 == shipped.class_schema_sha256
    assert pack.pip_packages == shipped.pip_packages

    row, = [row for row in resources.template_index()['templates'] if row['id'] == 'audio/transcribe']
    assert row['model_count'] == len(workflow.requirements.models) == 1
    assert row['custom_nodes'] == workflow.requirements.custom_nodes
    assert row['custom_node_refs'] == workflow.requirements.custom_node_refs
    descriptor, = row['public_inputs']
    audio_ref = workflow.inputs['audio_ref']
    assert descriptor['name'] == audio_ref.name == 'audio_ref'
    assert descriptor['required'] is audio_ref.required is True
    assert descriptor['media_semantics'] == audio_ref.media_semantics == 'audio'
    assert descriptor['target'] == {'node_id': audio_ref.node_id, 'field': audio_ref.field}
    output, = row['public_outputs']
    assert output['name'] == workflow.outputs[0].name == 'transcript_json'
    assert output['node_id'] == workflow.outputs[0].node_id == 'save_transcript'


def test_default_strict_drift_verifies_transcription_schema(tmp_path, monkeypatch):
    workflow = workflow_from_ready('audio/transcribe')
    entry, = workflow_lock_entries(workflow)
    # Recreate a single-pack installation through the default library and lock
    # resolution paths. The bundled repository lock also inventories other packs.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('VIBECOMFY_CUSTOM_NODES_DIR', str(tmp_path / 'custom_nodes'))
    checkout = tmp_path / 'custom_nodes' / entry.name
    checkout.mkdir(parents=True)
    monkeypatch.setattr(drift, '_git_head', lambda directory: entry.commit if directory == checkout else None)
    monkeypatch.setattr(drift, '_git_origin', lambda directory: entry.url if directory == checkout else None)
    lock = tmp_path / 'custom_nodes.lock'
    write_lockfile([entry], lock)
    monkeypatch.setattr(resources, '_resource_location', lambda name: lock)

    # Observe the gate's report, so a bypass of lock resolution or canonical
    # schema verification fails even if the gate silently returns.
    reports = []
    collect = drift.collect_drift

    def record_report(*args, **kwargs):
        report = collect(*args, **kwargs)
        reports.append(report)
        return report

    monkeypatch.setattr(drift, 'collect_drift', record_report)
    drift.enforce_strict_drift(workflow)
    observed = reports[0]['actual']['custom_node_packs'][entry.name]
    assert observed['schema_hash_status'] == 'canonical'
    assert observed['actual_schema_hash'] == entry.class_schema_sha256
    assert observed['installed_git_head'] == entry.commit

    lookup = object_info.get_class_by_identity

    def with_stale_language(class_type, **identity):
        schema = deepcopy(lookup(class_type, **identity))
        if class_type == 'Apply Whisper':
            assert 'English' in schema['inputs']['optional']['language'][0]
            schema['inputs']['optional']['language'][0] = ['auto']
        return schema

    monkeypatch.setattr(object_info, 'get_class_by_identity', with_stale_language)
    with pytest.raises(DriftError, match=r'ComfyUI-Whisper schema hash .* does not match pinned'):
        drift.enforce_strict_drift(workflow)
