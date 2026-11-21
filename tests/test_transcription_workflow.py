"""Offline contract and approval preflight for the transcription template."""
import copy

import pytest

from vibecomfy.comfy_nodes.transcript_output import VibeComfySaveTranscript
from vibecomfy.porting.object_info import get_class
from vibecomfy.registry.ready import workflow_from_ready
from vibecomfy.schema.provider import TargetSchemaProvider
from vibecomfy.workflow_bundle import WorkflowBundleError, load_bundle


def test_transcription_preflight_with_declared_inventory(tmp_path):
    workflow = workflow_from_ready('audio/transcribe')
    assets = workflow.metadata['requirements']['models']
    assert len(assets) == 1
    asset = assets[0]
    assert (asset['name'], asset['subdir'], asset['size_bytes'], asset['sha256']) == (
        'large-v3-turbo.pt', 'stt/whisper', 1617941637,
        'aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a',
    )
    info = {}
    for node in workflow.runtime_nodes().values():
        if node.class_type == 'VibeComfySaveTranscript':
            info[node.class_type] = {'input': VibeComfySaveTranscript.INPUT_TYPES(), 'output': [], 'output_name': [], 'output_is_list': [], 'output_node': True}
            continue
        schema = get_class(node.class_type)
        assert schema is not None
        info[node.class_type] = {'input': copy.deepcopy(schema['inputs']), 'input_order': copy.deepcopy(schema['input_order']), 'output': [o['type'] for o in schema['outputs']], 'output_name': [o['name'] for o in schema['outputs']], 'output_is_list': [o['is_list'] for o in schema['outputs']], 'output_node': False}
    assert get_class('Apply Whisper')['git_commit'] == '006a709848259ed3d69e2f9fcfd7a75f6c860ddd'
    info['LoadAudio']['input']['required']['audio'] = [['input.wav']]
    inventory = {'name': asset['name'], 'subdir': asset['subdir'], 'size': asset['size_bytes'], 'sha256': asset['sha256']}

    def provider(items):
        return TargetSchemaProvider.from_object_info(info, server_url='http://offline.invalid:8188', model_availability='target', auxiliary_model_custody='target', target_model_assets=items, refresh_object_info=lambda: info)

    approved = load_bundle(workflow).compile(schema_provider=provider([inventory]), models_root=tmp_path)
    assert approved.api_digest
    bad = {**inventory, 'sha256': '0' * 64}
    with pytest.raises(WorkflowBundleError):
        load_bundle(workflow).compile(schema_provider=provider([bad]), models_root=tmp_path)


def test_transcription_draft_entry():
    from vibecomfy.entries import draft_entry
    entry = draft_entry(workflow_from_ready('audio/transcribe'), 'transcription')
    assert entry['kind'] == 'audio'
    assert entry['modes'] == ['transcribe']
    assert entry['binds']['audio_ref'] == 'audio_ref'
    assert not entry['needs']


def test_output_history_descriptor_is_collected(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from vibecomfy.runtime.session import _collect_output_entries
    monkeypatch.setitem(sys.modules, 'folder_paths', SimpleNamespace(
        get_output_directory=lambda: str(tmp_path),
        get_save_image_path=lambda prefix, directory: (directory, prefix, 1, '', prefix)))
    history = VibeComfySaveTranscript().save('', [], [], 'transcript')['ui']
    entries = _collect_output_entries(history, output_directory=tmp_path)
    assert len(entries) == 1
    assert entries[0][1] == str(tmp_path / 'transcript_00001_.json')
