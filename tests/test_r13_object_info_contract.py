"""The recorded and live input contracts must survive conversion and approval."""
from __future__ import annotations

import asyncio
import copy
import io
import json
from urllib.error import HTTPError

import httpx
import pytest

from tests.test_target_model_approval import provider
from tests.test_target_model_bundle_custody import _target_info
from vibecomfy.porting.object_info import get_class
from vibecomfy.registry.ready import workflow_from_ready
from vibecomfy.workflow import VibeWorkflow, WorkflowSource
from vibecomfy.workflow_bundle import WorkflowBundleError, load_bundle


MUSIC = 'audio/ace_step_1_5_t2a_song'
SOURCE = 'ready_templates/sources/official/audio/ace_step_1_5_t2a_song.json'
EXPECTED = {
    'KSampler': {'denoise': 1},
    'SaveAudioMP3': {'quality': 'V0'},
    'TextEncodeAceStepAudio1.5': {
        'bpm': 120, 'generate_audio_codes': True, 'temperature': 0.85,
        'top_p': 0.9, 'top_k': 0, 'min_p': 0,
    },
}


def _shape(raw, shape):
    raw = copy.deepcopy(raw)
    if isinstance(raw[0], list) and shape == 'v3':
        return ['COMBO', {**(raw[1] if len(raw) > 1 else {}), 'options': raw[0]}]
    if raw[0] == 'COMBO' and shape == 'legacy' and 'options' in raw[1]:
        meta = raw[1].copy()
        return [meta.pop('options'), meta]
    return raw


@pytest.mark.parametrize('shape', ['legacy', 'v3'])
@pytest.mark.parametrize('class_type,field', [
    ('TextEncodeAceStepAudio1.5', 'language'), ('SaveAudioMP3', 'quality'),
    ('KSampler', 'sampler_name'), ('HunyuanFoleyModelLoader', 'foley_checkpoint_name'),
])
def test_both_input_shapes_preserve_order_choices_and_defaults(shape, class_type, field):
    from vibecomfy.porting.object_info.consume import compact_literal_widget_order
    from vibecomfy.schema.extract import widget_order
    from vibecomfy.porting.wrappers.discovery import _inputs_from_object_info

    entry = copy.deepcopy(get_class(class_type))
    for group in ('required', 'optional'):
        entry['inputs'][group] = {name: _shape(raw, shape)
                                  for name, raw in entry['inputs'].get(group, {}).items()}
    raw = entry['inputs']['required'][field]
    expected = raw[0] if isinstance(raw[0], list) else raw[1]['options']
    expected_default = raw[1].get('default') if len(raw) > 1 else None
    entry['input'] = entry.pop('inputs')
    selected = provider({class_type: entry}, model_availability='target')
    schema = selected.get_schema(class_type)
    assert schema.inputs[field].choices == expected
    assert schema.inputs[field].default == expected_default
    assert schema.inputs[field].required
    widget_names = [name for name in entry['object_info_widget_order'] if isinstance(name, str)]
    remaining = [name for group in entry['input'] for name in entry['input'][group]]
    assert list(schema.inputs) == list(dict.fromkeys(widget_names + remaining))
    assert field in compact_literal_widget_order(entry)
    assert field in widget_order(entry['input'], entry['input_order_all'])
    discovered = _inputs_from_object_info(entry)[field]
    assert discovered.options == tuple(str(value) for value in expected)
    assert discovered.default == expected_default


@pytest.mark.parametrize('shape', ['legacy', 'v3'])
@pytest.mark.parametrize('class_type,fields', list(EXPECTED.items()))
def test_compile_refuses_missing_required_inputs_even_with_defaults(shape, class_type, fields):
    workflow = VibeWorkflow('required-contract', WorkflowSource('required-contract'))
    workflow.add_node(class_type, '1', uid='required-node')
    # Isolate defaulted required fields, plus an optional defaulted input that
    # must remain optional. No model weights or live target are involved.
    entry = get_class(class_type)
    data = {class_type: {'input': {
        'required': {name: _shape(entry['inputs']['required'][name], shape) for name in fields},
        'optional': {'optional_value': ['INT', {'default': 9}]},
    }, 'output': []}}
    with pytest.raises(WorkflowBundleError) as error:
        load_bundle(workflow).compile(schema_provider=provider(data, model_availability='target'))
    assert f'Node 1 ({class_type})' in str(error.value)
    for name in fields:
        assert f'missing required input {name}' in str(error.value)


@pytest.mark.parametrize('shape', ['legacy', 'v3'])
def test_music_source_emission_and_canonical_approval_keep_required_values(tmp_path, shape):
    from vibecomfy.model_assets import _referenced_model_values
    from vibecomfy.porting.workbench import load_port_source
    from vibecomfy.workflow_bundle import emit_bundle_with_candidate
    from vibecomfy.security.provenance import Provenance

    source = load_port_source(SOURCE).workflow.compile('api')
    workflow = workflow_from_ready(MUSIC)
    graph = workflow.compile('api')
    for class_type, values in EXPECTED.items():
        original = next(row['inputs'] for row in source.values() if row['class_type'] == class_type)
        compiled = next(row['inputs'] for row in graph.values() if row['class_type'] == class_type)
        for field, value in values.items():
            assert original[field] == value
            assert compiled[field] == original[field]

    emitted = emit_bundle_with_candidate(workflow, tmp_path / 'music.py', {'operation': 'authored'}, None)
    bundle = load_bundle(emitted.python_path, trust=Provenance.USER_CONFIRMED)
    data = _target_info(workflow)
    for info in data.values():
        for group in ('required', 'optional'):
            info['input'][group] = {name: _shape(raw, shape)
                                    for name, raw in info['input'].get(group, {}).items()}
    for ref in _referenced_model_values(workflow):
        data[ref['class_type']]['input']['required'][ref['field']] = _shape([[ref['value']], {}], shape)
    target = provider(data, model_availability='target')
    record = bundle.compile(schema_provider=target, models_root=tmp_path / 'no-models')
    for class_type, values in EXPECTED.items():
        inputs = next(row['inputs'] for row in record.api_projection.values() if row['class_type'] == class_type)
        for field, value in values.items():
            assert inputs[field] == value


@pytest.mark.parametrize('transport', ['httpx', 'urllib'])
def test_queue_400_preserves_node_errors_and_truncates_body(monkeypatch, transport):
    import vibecomfy.runtime.client as client_module
    from vibecomfy.errors import WorkflowQueueError
    from vibecomfy.runtime.execution import queue_embedded_prompt, queue_server_prompt
    from tests.test_runtime_execution import _approved

    record, bundle = _approved()
    body = json.dumps({'node_errors': {'124': {'class_type': 'TextEncodeAceStepAudio1.5',
                                            'errors': ['Required input is missing: bpm']}},
                       'padding': 'x' * 2000})
    if transport == 'urllib':
        class Queue:
            async def queue_prompt_api(self, payload):
                raise HTTPError('http://fake.invalid/prompt', 400, 'Bad Request', {}, io.BytesIO(body.encode()))
        operation = queue_embedded_prompt(Queue(), record, bundle)
    else:
        async_client = httpx.AsyncClient
        async def handle(request):
            assert request.url.path == '/prompt'
            return httpx.Response(400, text=body, request=request)
        monkeypatch.setattr(client_module.httpx, 'AsyncClient', lambda **kwargs: async_client(
            transport=httpx.MockTransport(handle), **kwargs))
        operation = queue_server_prompt(record, bundle, server_url='http://fake.invalid')
    with pytest.raises(WorkflowQueueError) as error:
        asyncio.run(operation)
    message = str(error.value)
    assert message.startswith('Workflow queue failed:')
    assert 'node_errors' in message and 'Required input is missing: bpm' in message
    excerpt = error.value.message.split('response body: ', 1)[1]
    assert len(excerpt) <= 600
    assert excerpt.endswith('...')


def test_normalized_dict_specs_share_the_reader_and_keep_false_defaults(monkeypatch):
    from vibecomfy.porting.object_info import consume
    from vibecomfy.porting.wrappers.discovery import _inputs_from_object_info

    entry = {'inputs': {
        'required': {
            'quality': {'type': 'COMBO', 'options': ['V0', '128k'], 'default': 'V0'},
            'enabled': {'type': 'BOOLEAN', 'default': False},
        },
        'optional': {'count': {'type': 'INT', 'default': 0}},
    }, 'input_order_all': ['enabled', 'quality', 'count'],
        'object_info_widget_order': ['enabled', 'quality', 'count'], 'outputs': []}
    selected = provider({'Normalized': entry}, model_availability='target')
    schema = selected.get_schema('Normalized')
    assert list(schema.inputs) == ['enabled', 'quality', 'count']
    assert schema.inputs['quality'].choices == ['V0', '128k']
    assert schema.inputs['enabled'].default is False
    assert schema.inputs['enabled'].required and not schema.inputs['count'].required
    discovered = _inputs_from_object_info(entry)
    assert discovered['quality'].options == ('V0', '128k')
    assert discovered['enabled'].has_default and discovered['enabled'].default is False
    monkeypatch.setattr(consume, 'get_class', lambda class_type: entry)
    assert consume.class_defaults('Normalized') == {'quality': 'V0', 'enabled': False, 'count': 0}
    assert consume.class_input_types('Normalized') == {'quality': 'COMBO', 'enabled': 'BOOLEAN', 'count': 'INT'}
