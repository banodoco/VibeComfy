"""Live V3 and legacy combo contracts must grant the same picker authority."""
from __future__ import annotations

import copy
import json

import pytest

from tests.test_target_model_approval import provider
from tests.test_target_model_bundle_custody import _target_info
from vibecomfy.registry.ready import workflow_from_ready
from vibecomfy.workflow_bundle import WorkflowBundleError, load_bundle


@pytest.mark.parametrize('long_inventory', [False, True])
@pytest.mark.parametrize('shape', ['v3', 'legacy'])
@pytest.mark.parametrize('class_type,field,value,other', [
    ('HunyuanFoleyModelLoader', 'foley_checkpoint_name',
     'hunyuanvideo_foley_xl.pth', 'hunyuanvideo_foley.pth'),
    ('LoadDACHunyuanVAE', 'vae_name',
     'hunyuan_foley/vae_128d_48k.pth', 'other/vae_128d_48k.pth'),
])
def test_foley_combo_approval_requires_advertised_value(tmp_path, long_inventory, shape, class_type, field, value, other):
    workflow = workflow_from_ready('audio/hunyuan_foley_v2a')
    data = _target_info(workflow)
    spec = (['COMBO', {'multiselect': False, 'options': [value]}] if shape == 'v3' else [[value], {}])
    data[class_type]['input']['required'][field] = spec
    assets = [
        {'name': asset['name'], 'subdir': asset['subdir'],
         'size': asset['size_bytes'], 'sha256': asset['sha256']}
        for asset in workflow.metadata['model_assets']
    ]

    def target(capture):
        return provider(capture, model_availability='target',
                        auxiliary_model_custody='target', target_model_assets=assets)

    selected = target(data)
    record = load_bundle(workflow).compile(schema_provider=selected, models_root=tmp_path)
    assert selected.target_model_value(class_type, field, value) == value
    bound = next(node for node in record.api_projection.values() if node['class_type'] == class_type)
    assert bound['inputs'][field] == value
    assert not list(tmp_path.iterdir())

    refused = copy.deepcopy(data)
    options = [other] + ([f'not_selected_{i:04d}.pth' for i in range(100)] if long_inventory else [])
    refused[class_type]['input']['required'][field] = (
        ['COMBO', {'multiselect': False, 'options': options}] if shape == 'v3' else [options, {}]
    )
    selected = target(refused)
    assert selected.target_model_value(class_type, field, value) is None
    message = f'model picker value is not advertised by the selected target: {class_type}.{field}={value!r}'
    with pytest.raises(WorkflowBundleError) as error:
        load_bundle(workflow).compile(schema_provider=selected, models_root=tmp_path)
    advertised = json.dumps(refused[class_type]["input"]["required"][field])
    expected = advertised if len(advertised) <= 200 else advertised[:197] + "..."
    assert str(error.value) == message + "; advertised: " + expected
    assert len(str(error.value).split("; advertised: ", 1)[1]) <= 200


@pytest.mark.parametrize('boundary', ['schema', 'call', 'edit', 'discovery'])
def test_v3_combo_choices_reach_consumers(boundary):
    data = {'ChoiceNode': {'input': {'required': {
        'mode': ['COMBO', {'options': ['fast', 'slow'], 'default': 'fast'}],
    }}, 'output': []}}
    selected = provider(data, model_availability='target')
    spec = selected.get_schema('ChoiceNode').inputs['mode']
    assert spec.choices == ['fast', 'slow']
    if boundary == 'schema':
        from vibecomfy.schema.validate import validate_api_against_schema

        issues = validate_api_against_schema(
            {'1': {'class_type': 'ChoiceNode', 'inputs': {'mode': 'invented'}}}, selected,
        )
        assert any(issue.code == 'value_not_in_enum' for issue in issues)
    elif boundary == 'call':
        from vibecomfy.schema.call_validation import validate_node_call

        report = validate_node_call('ChoiceNode', {'mode': 'invented'}, selected)
        assert any(issue.code == 'value_not_in_enum' for issue in report.issues)
    elif boundary == 'edit':
        from vibecomfy.porting.edit.validate import validate_literal_value

        issues = validate_literal_value(value='invented', spec=spec, class_type='ChoiceNode',
                                        input_name='mode', context='test')
        assert any(issue.code == 'value_not_in_enum' for issue in issues)
    else:
        from vibecomfy.porting.wrappers.discovery import _inputs_from_object_info

        fields = _inputs_from_object_info(data['ChoiceNode'])
        assert fields['mode'].options == ('fast', 'slow')


def test_v3_picker_choices_do_not_invent_inventory():
    data = {'VAELoader': {'input': {'optional': {
        'vae_name': ['COMBO', {'options': ['folder/model.pth']}],
    }}, 'output': []}}
    selected = provider(data, model_availability='target')
    assert selected.target_model_value('VAELoader', 'vae_name', 'folder/model.pth') == 'folder/model.pth'
    assert selected.target_model_value('VAELoader', 'vae_name', 'model.pth') is None
    assert selected.target_model_value('VAELoader', 'vae_name', 'other/model.pth') is None
    for spec in (['COMBO', {'options': []}], ['COMBO'],
                 ['COMBO', {'options': 'folder/model.pth'}],
                 ['STRING', {'options': ['folder/model.pth']}],
                 ['COMBO', {'unresolved_choices': True}]):
        data['VAELoader']['input']['optional']['vae_name'] = spec
        selected = provider(data, model_availability='target')
        assert selected.target_model_value('VAELoader', 'vae_name', 'folder/model.pth') is None


def test_capture_sanitizes_v3_combo_choices_without_changing_valid_shapes():
    from vibecomfy.schema.extract import _sanitize_observed_inputs

    valid = ['COMBO', {'options': ['folder/model.pth'], 'multiselect': False}]
    assert _sanitize_observed_inputs({'required': {'model': valid}}) == {'required': {'model': valid}}
    for options in ([], ['<class dummy>'], [True]):
        raw = {'required': {'model': ['COMBO', {'options': options}]}}
        assert _sanitize_observed_inputs(raw) == {
            'required': {'model': ['COMBO', {'unresolved_choices': True}]},
        }
