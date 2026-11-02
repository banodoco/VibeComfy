"""Focused CPU contracts for the five authorized Phase 2 ready defaults."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from vibecomfy.registry.ready import ready_template_ids, workflow_from_ready
from vibecomfy.runtime.session import _model_assets_from_workflow
from vibecomfy.security.provenance import Provenance
from vibecomfy.workflow_bundle import emit_bundle, load_bundle

ROOT = Path(__file__).resolve().parents[1]
BINDINGS = {
    'audio/qwen3_tts_custom_voice': {'text': ('1', 'text'), 'voice': ('1', 'speaker'), 'seed': ('1', 'seed')},
    'audio/minimax_music_3': {'prompt': ('13', 'caption'), 'lyrics': ('13', 'lyrics'), 'duration': ('13', 'max_duration'), 'seed': ('38', 'seed')},
    'audio/hunyuan_video_foley': {'video_ref': ('23', 'file'), 'prompt': ('22', 'prompt'), 'seed': ('22', 'seed')},
    'image/qwen_image_2_1_turbo': {'prompt': ('5', 'prompt'), 'seed': ('8', 'noise_seed'), 'width': ('4', 'width'), 'height': ('4', 'height')},
    'edit/qwen_image_2_1_turbo_edit': {'image': ('4', 'image'), 'prompt': ('5', 'prompt'), 'seed': ('8', 'noise_seed')},
}


@pytest.mark.parametrize('template_id', BINDINGS)
def test_default_public_overrides_and_canonical_roundtrip(template_id, tmp_path):
    assert template_id in ready_template_ids()
    source = ROOT / 'ready_templates' / f'{template_id}.py'
    assert source.with_suffix('.vibe.json').is_file()
    original = load_bundle(template_id)
    original.require_canonical_authority('Phase 2 source')
    workflow = workflow_from_ready(template_id)
    for public, (node_id, field) in BINDINGS[template_id].items():
        binding = workflow.inputs[public]
        assert (str(binding.node_id), binding.field) == (node_id, field)
        value = {'seed': 1729, 'width': 768, 'height': 1024, 'duration': 12.0,
                 'voice': 'Serena', 'image': 'reference.png', 'video_ref': 'reference.mp4',
                 'text': 'A short CPU binding check.', 'prompt': 'Copper bells under moonlight.',
                 'lyrics': '[Verse]\nCopper bells ring.'}[public]
        workflow.set_input(public, value)
        assert workflow.compile('api')[node_id]['inputs'][field] == value
    bundle = emit_bundle(workflow, tmp_path / 'workflow.py', {'operation': 'authored'})
    reopened = load_bundle(bundle.python_path, trust=Provenance.USER_CONFIRMED)
    reopened.require_canonical_authority('Phase 2 roundtrip')
    assert reopened.workflow.compile('api') == workflow.compile('api')
    for public in BINDINGS[template_id]:
        assert reopened.workflow.inputs[public].value == workflow.inputs[public].value
    assert reopened.workflow.outputs[0].artifact_kind == ('audio' if template_id.startswith('audio/') else 'image')
    assert _model_assets_from_workflow(reopened.workflow) == _model_assets_from_workflow(workflow)


def test_music_blueprint_path_and_shared_seed():
    workflow = workflow_from_ready('audio/minimax_music_3')
    workflow.set_input('seed', 1729)
    workflow.set_input('duration', 12.0)
    api = workflow.compile('api')
    assert api['13']['inputs']['seed'] == api['9']['inputs']['seed'] == ['38', 0]
    assert api['38']['inputs']['seed'] == 1729
    assert api['15']['inputs']['seconds'] == ['13', 1]
    assert api['42']['class_type'] == 'VAEDecodeAudioTiled'
    assert api['42']['inputs']['samples'] == ['9', 0]
    assert api['44']['inputs']['audio'] == ['42', 0]
    assert api['13']['inputs']['max_duration'] == 12.0
    assert api['9']['inputs']['steps'] == 30 and api['9']['inputs']['cfg'] == 1.7
    source = ROOT / workflow.metadata['source_workflow']
    assert hashlib.sha256(source.read_bytes()).hexdigest() == '2bc91e6e4895842b47b2f6deac1626109ae08d8ca2f2fe877c312f5ee9d143fb'
    assets = _model_assets_from_workflow(workflow)
    assert len(assets) == 3
    assert all(row['hf_revision'] == '9e364ccd290a401561091fb441ed19cd7de92550' and len(row['sha256']) == 64 and row['size_bytes'] > 0 for row in assets)


def test_qwen_voice_is_a_supported_speaker_and_snapshot_is_complete():
    workflow = workflow_from_ready('audio/qwen3_tts_custom_voice')
    api = workflow.compile('api')
    assert api['1']['inputs']['model_size'] == '0.6B'
    assert 'Serena' in workflow.inputs['voice'].range['choices']
    assert workflow.inputs['voice'].field == 'speaker'
    assert api['2']['inputs']['audio'] == ['1', 0]
    assert api['2']['inputs']['quality'] == 'V0'
    assets = _model_assets_from_workflow(workflow)
    prefix = 'TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice/'
    paths = {row['subdir'] + '/' + row['name']: row for row in assets}
    expected = {'config.json', 'generation_config.json', 'merges.txt', 'model.safetensors',
                'preprocessor_config.json', 'tokenizer_config.json', 'vocab.json',
                'speech_tokenizer/config.json', 'speech_tokenizer/configuration.json',
                'speech_tokenizer/model.safetensors', 'speech_tokenizer/preprocessor_config.json'}
    assert set(paths) == {prefix + path for path in expected}
    for path, row in paths.items():
        assert row['hf_revision'] == '85e237c12c027371202489a0ec509ded67b5e4b5'
        assert row['hf_revision'] in row['url']
        if path.endswith('.safetensors'):
            assert len(row['sha256']) == 64 and row['size_bytes'] > 0
    pack = workflow.metadata['custom_node_packs']['ComfyUI-QwenTTS']
    assert pack['commit'] == 'd8122a8ba835b65fd65c113d2b273b1ad1579293'


@pytest.mark.parametrize('template_id,source_digest', [
    ('image/qwen_image_2_1_turbo', '3eb9cef2866c0186fbe30172701f112b35e574cf3c6575c6e4a6b5dd1e76a403'),
    ('edit/qwen_image_2_1_turbo_edit', '5a9622d550866800414afcb9c70523ec5c6965eb171476e401e243a7fe8d5a4e'),
])
def test_qwen_image_source_and_exact_shared_asset_set(template_id, source_digest):
    workflow = workflow_from_ready(template_id)
    source = ROOT / workflow.metadata['source_workflow']
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_digest
    assets = _model_assets_from_workflow(workflow)
    assert {row['name'] for row in assets} == {'qwen_image_2.1_turbo_int8_convrot.safetensors', 'qwen3vl_8b_int8_convrot.safetensors', 'qwen_image_2.1_vae_bf16.safetensors'}
    assert all(row['hf_revision'] == 'aacf31a6d48e707f352ecba714cee0680da3479b' and len(row['sha256']) == 64 and row['size_bytes'] > 0 for row in assets)
    api = workflow.compile('api')
    assert api['10']['inputs']['cfg'] == 1.0
    assert api['9']['inputs']['sampler_name'] == 'euler'
    assert api['11']['inputs']['latent_image'] == (['5', 2] if template_id.startswith('edit/') else ['4', 0])
    if template_id.startswith('edit/'):
        assert api['5']['inputs']['images.image_1'] == ['4', 0]
        assert workflow.inputs['image'].media_semantics == 'image'


def test_coverage_and_generated_index_include_five_defaults():
    coverage = json.loads((ROOT / 'ready_templates/sources/manifests/coverage.json').read_text())['workflows']
    index = {row['id']: row for row in json.loads((ROOT / 'template_index.json').read_text())['templates']}
    for identity, bindings in BINDINGS.items():
        declarations = [row for row in coverage if row.get('ready_template') == identity]
        assert len(declarations) == 1
        assert declarations[0]['coverage_tier'] == 'required'
        assert (ROOT / declarations[0]['path']).is_file()
        actual = {row['name']: (row['node_id'], row['field']) for row in index[identity]['public_inputs']}
        for name, binding in bindings.items():
            assert actual[name] == binding
        assert index[identity]['public_outputs'][0]['name'] == ('audio' if identity.startswith('audio/') else 'image')
    assert index['audio/hunyuan_video_foley']['license_notice'] == 'Tencent Hunyuan Community license excludes the EU, UK, and South Korea.'
    assert 'video/h3_av' not in ready_template_ids()
