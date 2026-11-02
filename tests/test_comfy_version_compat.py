"""CPU schema qualification against immutable v0.43.0 source definitions.

This checks canonical API graphs and socket types, not imports, installed-node
ABI, dynamic file choices, model loads, inference, or GPU capacity.
"""
from __future__ import annotations

import json
from pathlib import Path
import tomllib

import pytest

from vibecomfy.porting.object_info import get_class
from vibecomfy.registry.ready import workflow_from_ready
from vibecomfy.schema import ObjectInfoSchemaProvider, socket_types_compatible, validate_node_call

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / 'vibecomfy/porting/cache/object_info/comfy_core@zz-official-426f5eea.json'
DEFAULTS = (
    'audio/qwen3_tts_custom_voice', 'audio/minimax_music_3',
    'audio/hunyuan_video_foley', 'image/qwen_image_2_1_turbo',
    'edit/qwen_image_2_1_turbo_edit',
)


def _wire(row):
    return {'input': row['inputs'], 'input_order': row['input_order'],
            'output': [item['type'] for item in row['outputs']],
            'output_name': [item['name'] for item in row['outputs']],
            'output_is_list': [item['is_list'] for item in row['outputs']],
            'output_node': row.get('output_node', False)}


@pytest.mark.parametrize('template_id', DEFAULTS)
def test_default_api_matches_exact_release_schemas(template_id, tmp_path):
    workflow = workflow_from_ready(template_id)
    api = workflow.compile('api')
    core = json.loads(CORE_PATH.read_text())
    rows = {}
    for node in api.values():
        name = node['class_type']
        row = core.get(name)
        if row is None:
            row = get_class(name)
            assert row is not None, name
            assert name in {
                'AILab_Qwen3TTSCustomVoice', 'HunyuanFoleyModelLoader',
                'HunyuanFoleySampler', 'LoadDACHunyuanVAE', 'DACHunyuanVAEDecode',
            }, name
        else:
            assert row['source_commit'] == '426f5eea52a7ece1dd599fff4cb6cd1f352ddd24'
            assert row['source_kind'] == 'static_ast'
        rows[name] = _wire(row)
    path = tmp_path / 'selected-source-schemas.json'
    path.write_text(json.dumps(rows))
    provider = ObjectInfoSchemaProvider(path)
    for node_id, node in api.items():
        report = validate_node_call(node['class_type'], node['inputs'], provider)
        assert report.ok, (template_id, node_id, report.to_json())
        schema = provider.get_schema(node['class_type'])
        # Required names must be present even when an authoring provider has
        # defaults: this is the graph actually sent to ComfyUI.
        required = set(rows[node['class_type']]['input'].get('required', {}))
        assert required <= set(node['inputs']), (node_id, required - set(node['inputs']))
        for field, value in node['inputs'].items():
            if not (isinstance(value, list) and len(value) == 2 and isinstance(value[1], int)):
                continue
            upstream = api[str(value[0])]
            source_schema = provider.get_schema(upstream['class_type'])
            assert 0 <= value[1] < len(source_schema.outputs), (node_id, field, value)
            assert socket_types_compatible(source_schema.outputs[value[1]].type, schema.inputs[field].type), (node_id, field, value)


def test_official_release_qualification_tuple_is_immutable():
    metadata = json.loads((ROOT / 'vibecomfy/comfy_metadata.json').read_text())
    assert metadata['version'] == '0.43.0'
    assert metadata['commit'] == '426f5eea52a7ece1dd599fff4cb6cd1f352ddd24'
    assert metadata['status'] == 'static_source_schema_only'
    assert metadata['install_dir'] is None
    for row in json.loads(CORE_PATH.read_text()).values():
        assert row['source_commit'] == metadata['commit']
        assert len(row['source_sha256']) == 64
        assert metadata['commit'] in row['source_url']


def test_packaged_fork_pin_is_explicit_and_locked():
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    lock = tomllib.loads((ROOT / 'uv.lock').read_text())
    matrix = json.loads((ROOT / 'vibecomfy/registry/comfy_version_matrix.json').read_text())
    assert 'comfyui==0.43.0.2' in project['project']['optional-dependencies']['comfy']
    package = next(row for row in lock['package'] if row['name'] == 'comfyui')
    assert package['version'] == matrix['supported_comfyui_version'] == '0.43.0.2'
    assert matrix['pinned_comfyui_commit'] == 'ff7644a70dba1707f4caee52576496ce848792f8'
    assert package['source']['registry'] == 'https://nodes.appmana.com/simple/'
    artifacts = [package['sdist'], *package['wheels']]
    assert artifacts
    for artifact in artifacts:
        assert '/hiddenswitch/forks-pip-and-uv-installable-ComfyUI/' in artifact['url']
        assert artifact['hash'].startswith('sha256:')
        assert len(artifact['hash']) == len('sha256:') + 64
