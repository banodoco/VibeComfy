"""The canonical bundle gate distinguishes target picker names from model bytes."""
from __future__ import annotations

import copy
import json

import pytest

from vibecomfy.porting.object_info import get_class
from vibecomfy.registry.ready import workflow_from_ready
from vibecomfy.schema.provider import TargetSchemaProvider
from vibecomfy.workflow_bundle import WorkflowBundleError, load_bundle


EXACT_VAE = r'FLUX1\ae.safetensors'


def target_info(workflow):
    """A synthetic target capture uses pinned schemas and selected model names."""
    data = {}
    for node in workflow.runtime_nodes().values():
        entry = get_class(node.class_type)
        assert entry is not None, node.class_type
        outputs = entry['outputs']
        data[node.class_type] = {
            'input': copy.deepcopy(entry['inputs']),
            'input_order': copy.deepcopy(entry['input_order']),
            'output': [item['type'] for item in outputs],
            'output_name': [item['name'] for item in outputs],
            'output_is_list': [item['is_list'] for item in outputs],
        }
    for cls, field, name in (
        ('UNETLoader', 'unet_name', 'z_image_turbo_bf16.safetensors'),
        ('CLIPLoader', 'clip_name', 'qwen_3_4b.safetensors'),
        ('VAELoader', 'vae_name', 'ae.safetensors'),
    ):
        data[cls]['input']['required'][field] = [[name]]
    return data


def provider(data, **kwargs):
    return TargetSchemaProvider.from_object_info(
        data, server_url='http://target.invalid:8188', **kwargs,
    )


@pytest.mark.parametrize('template_id', ['image/z_image_turbo', 'image/z_image_img2img'])
def test_turbo_compiles_via_canonical_approval_with_exact_graph_bindings(template_id):
    workflow = workflow_from_ready(template_id)
    assert workflow.metadata['unbound_inputs'] == {}
    workflow.set_input('prompt', 'The exact user prompt.')
    data = target_info(workflow)
    target = provider(data, model_availability='target')
    # This is the production canonical bundle boundary, with no registry,
    # presence, approval, or schema gate patched out.
    bundle = load_bundle(workflow)
    record = bundle.compile(schema_provider=target)
    graph = record.api_projection
    loaders = {item['class_type']: item['inputs'] for item in graph.values()}
    assert loaders['UNETLoader']['unet_name'] == 'z_image_turbo_bf16.safetensors'
    assert loaders['CLIPLoader']['clip_name'] == 'qwen_3_4b.safetensors'
    assert loaders['VAELoader']['vae_name'] == 'ae.safetensors'
    assert loaders['ModelSamplingAuraFlow']['shift'] == 3
    assert loaders['KSampler']['steps'] == 8
    assert loaders['KSampler']['cfg'] == 1
    assert loaders['KSampler']['sampler_name'] == 'res_multistep'
    assert loaders['KSampler']['scheduler'] == 'simple'
    positive_id = loaders['KSampler']['positive'][0]
    assert graph[positive_id]['inputs']['text'] == 'The exact user prompt.'
    assert record.api_digest
    record.assert_matches(bundle, api_projection=record.api_projection, ui_projection=record.ui_projection)
    refs = [d for d in target._approval_diagnostics if d['code'] == 'target_model_reference']
    assert len(refs) == 3
    assert all(d['model_bytes_status'] == 'unverified_target_inventory' for d in refs)
    assert all(d['target_schema_digest'] == target._object_info_digest for d in refs)
    assert all('sha256' not in d for d in refs)


def _workflow_with_vae(value):
    workflow = workflow_from_ready('image/z_image_turbo')
    workflow.set_input('vae', value)
    # Remove the old source-backed asset, preserving exact picker authority.
    workflow.metadata['model_assets'] = [
        a for a in workflow.metadata['model_assets'] if a['name'] != 'ae.safetensors'
    ]
    workflow.requirements.models = [
        value if (a.get('name') if isinstance(a, dict) else a) == 'ae.safetensors' else a
        for a in workflow.requirements.models
    ]
    return workflow


@pytest.mark.parametrize('advertised', [False, True])
def test_literal_backslash_model_name_requires_target_authority(advertised):
    workflow = _workflow_with_vae(EXACT_VAE)
    data = target_info(workflow)
    if advertised:
        data['VAELoader']['input']['required']['vae_name'] = [[EXACT_VAE]]
    target = provider(data, model_availability='target')
    graph = workflow.compile('api')
    vae = next(n for n in graph.values() if n['class_type'] == 'VAELoader')
    assert vae['inputs']['vae_name'] == EXACT_VAE
    assert json.loads(json.dumps(graph))['3']['inputs']['vae_name'] == EXACT_VAE
    if advertised:
        record = load_bundle(workflow).compile(schema_provider=target)
        assert record.api_projection['3']['inputs']['vae_name'] == EXACT_VAE
    else:
        with pytest.raises(WorkflowBundleError, match='model asset reference must be.*relative path'):
            load_bundle(workflow).compile(schema_provider=target)


@pytest.mark.parametrize('value', [
    '../ae.safetensors', 'FLUX1/../ae.safetensors',
    r'..\ae.safetensors', r'FLUX1\..\ae.safetensors',
    '/models/ae.safetensors', r'C:\models\ae.safetensors',
    'C:/models/ae.safetensors', r'\\server\models\ae.safetensors',
    r'\models\ae.safetensors', 'C:ae.safetensors',
])
def test_unsafe_model_name_is_refused_even_when_advertised(value):
    workflow = _workflow_with_vae(value)
    data = target_info(workflow)
    data['VAELoader']['input']['required']['vae_name'] = [[value]]
    with pytest.raises(WorkflowBundleError, match='model asset reference must be.*relative path'):
        load_bundle(workflow).compile(schema_provider=provider(data, model_availability='target'))


@pytest.mark.parametrize('advertised', [EXACT_VAE, 'FLUX1/ae.safetensors'])
def test_windows_saved_workflow_imports_and_compiles_with_target_spelling(tmp_path, advertised):
    from vibecomfy.security.provenance import Provenance
    from vibecomfy.workflow_bundle import emit_bundle

    source = tmp_path / 'windows-workflow.json'
    saved = json.dumps({
        'workflow_id': 'windows-saved-vae',
        'nodes': [{'id': 3, 'type': 'VAELoader', 'widgets_values': [EXACT_VAE]}],
        'links': [], 'groups': [],
    })
    source.write_text(saved, encoding='utf-8')
    data = target_info(workflow_from_ready('image/z_image_turbo'))
    data['VAELoader']['input']['required']['vae_name'] = [[advertised]]
    target = provider(data, model_availability='target')
    imported = load_bundle(source, schema_provider=target)
    assert imported.workflow.compile('api')['3']['inputs']['vae_name'] == EXACT_VAE
    destination = tmp_path / 'converted.py'
    emit_bundle(imported.workflow, destination, {'operation': 'captured'})
    bundle = load_bundle(destination, trust=Provenance.USER_CONFIRMED)
    assert bundle.workflow.compile('api')['3']['inputs']['vae_name'] == EXACT_VAE
    record = bundle.compile(schema_provider=target)
    assert record.api_projection['3']['inputs']['vae_name'] == advertised
    from vibecomfy.runtime.execution import authorized_queue_payload

    assert authorized_queue_payload(record, bundle)['3']['inputs']['vae_name'] == advertised
    assert source.read_text(encoding='utf-8') == saved


@pytest.mark.parametrize('source,choices,expected', [
    (EXACT_VAE, [EXACT_VAE, 'FLUX1/ae.safetensors'], EXACT_VAE),
    (EXACT_VAE, ['FLUX1/ae.safetensors'], 'FLUX1/ae.safetensors'),
    ('FLUX1/ae.safetensors', [EXACT_VAE], EXACT_VAE),
])
def test_target_picker_binding_uses_exact_advertised_spelling(source, choices, expected):
    workflow = _workflow_with_vae(source)
    data = target_info(workflow)
    data['VAELoader']['input']['required']['vae_name'] = [choices]
    target = provider(data, model_availability='target')
    before = workflow.semantic_digest()
    record = load_bundle(workflow).compile(schema_provider=target)
    assert record.api_projection['3']['inputs']['vae_name'] == expected
    record.assert_matches(load_bundle(workflow), api_projection=record.api_projection, ui_projection=record.ui_projection)
    assert workflow.semantic_digest() == before


def test_queue_record_still_refuses_a_different_model_prefix():
    from vibecomfy.runtime.execution import authorized_queue_payload
    from vibecomfy.testing.canonical import canonical_digest
    from vibecomfy.workflow_bundle import ApprovedProjectionRecord

    workflow = _workflow_with_vae(EXACT_VAE)
    data = target_info(workflow)
    data['VAELoader']['input']['required']['vae_name'] = [[EXACT_VAE]]
    bundle = load_bundle(workflow)
    approved = bundle.compile(schema_provider=provider(data, model_availability='target'))
    forged = approved.to_dict()
    forged['api_projection']['3']['inputs']['vae_name'] = 'other/ae.safetensors'
    forged['api_digest'] = canonical_digest(forged['api_projection'])
    with pytest.raises(WorkflowBundleError, match='does not match current bundle'):
        authorized_queue_payload(ApprovedProjectionRecord.from_dict(forged), bundle)


def test_target_picker_binding_does_not_match_only_a_basename():
    workflow = _workflow_with_vae('FLUX1/ae.safetensors')
    data = target_info(workflow)
    data['VAELoader']['input']['required']['vae_name'] = [['other/ae.safetensors']]
    with pytest.raises(WorkflowBundleError, match='not advertised by the selected target'):
        load_bundle(workflow).compile(schema_provider=provider(data, model_availability='target'))


@pytest.mark.parametrize('declaration', ['model_assets', 'requirements'])
def test_target_picker_authority_does_not_relax_authored_asset_paths(declaration):
    workflow = _workflow_with_vae(EXACT_VAE)
    asset = {'name': EXACT_VAE, 'subdir': 'vae', 'url': None}
    if declaration == 'model_assets':
        workflow.metadata['model_assets'].append(asset)
    else:
        workflow.requirements.models.append(asset)
    data = target_info(workflow)
    data['VAELoader']['input']['required']['vae_name'] = [[EXACT_VAE]]
    with pytest.raises(WorkflowBundleError, match='model asset (name|reference) must be.*relative path'):
        load_bundle(workflow).compile(schema_provider=provider(data, model_availability='target'))


@pytest.mark.parametrize('boundary', ['schema', 'edit'])
def test_model_choice_validators_do_not_match_only_a_basename(boundary):
    workflow = _workflow_with_vae('FLUX1/ae.safetensors')
    data = target_info(workflow)
    data['VAELoader']['input']['required']['vae_name'] = [['other/ae.safetensors']]
    target = provider(data, model_availability='target')
    if boundary == 'schema':
        from vibecomfy.schema.validate import validate_api_against_schema

        issues = validate_api_against_schema(workflow.compile('api'), target)
        assert any(issue.code == 'value_not_in_enum' and issue.severity == 'error' for issue in issues)
    else:
        from vibecomfy.porting.edit.validate import validate_literal_value

        issues = validate_literal_value(
            value='FLUX1/ae.safetensors', spec=target.get_schema('VAELoader').inputs['vae_name'],
            class_type='VAELoader', input_name='vae_name', context='test',
        )
        assert [(issue.code, issue.severity) for issue in issues] == [('asset_not_installed', 'warning')]


def test_capture_is_detached_and_target_model_mode_is_explicit(tmp_path):
    workflow = workflow_from_ready('image/z_image_turbo')
    data = target_info(workflow)
    target = provider(data, model_availability='target')
    data['UNETLoader']['input']['required']['unet_name'][0].clear()
    assert target.target_model_reference('UNETLoader', 'unet_name', 'z_image_turbo_bf16.safetensors')
    local = provider(target_info(workflow))
    assert not local.target_model_reference('UNETLoader', 'unet_name', 'z_image_turbo_bf16.safetensors')
    with pytest.raises(WorkflowBundleError, match='not present locally'):
        load_bundle(workflow).compile(schema_provider=local, models_root=tmp_path)


@pytest.mark.parametrize('replacement', ['z_image_bf16.safetensors', 'z_image_turbo_bf16-copy.safetensors'])
def test_target_model_gate_rejects_base_or_similar_turbo_filename(replacement):
    workflow = workflow_from_ready('image/z_image_turbo')
    data = target_info(workflow)
    data['UNETLoader']['input']['required']['unet_name'] = [[replacement]]
    with pytest.raises(WorkflowBundleError, match='not advertised by the selected target'):
        load_bundle(workflow).compile(schema_provider=provider(data, model_availability='target'))


def test_target_inventory_does_not_discharge_unbound_authored_model_requirement():
    workflow = workflow_from_ready('image/z_image_turbo')
    workflow.requirements.models.append('unbound-extra-model.safetensors')
    data = target_info(workflow)
    data['VAELoader']['input']['required']['vae_name'][0].append('unbound-extra-model.safetensors')
    with pytest.raises(WorkflowBundleError, match='not locally registered: unbound-extra-model'):
        load_bundle(workflow).compile(schema_provider=provider(data, model_availability='target'))


def test_original_z_image_template_remains_base():
    graph = workflow_from_ready('image/z_image').compile('api')
    unet = next(n for n in graph.values() if n['class_type'] == 'UNETLoader')
    assert unet['inputs']['unet_name'] == 'z_image_bf16.safetensors'


def test_target_model_mode_does_not_approve_stale_bundle_revision():
    workflow = workflow_from_ready('image/z_image_turbo')
    target = provider(target_info(workflow), model_availability='target')
    bundle = load_bundle(workflow)
    workflow.set_input('prompt', 'Changed after the bundle revision was captured.')
    with pytest.raises(WorkflowBundleError, match='revision is stale'):
        bundle.compile(schema_provider=target)


def test_target_model_mode_still_requires_full_schema_validation():
    workflow = workflow_from_ready('image/z_image_turbo')
    data = target_info(workflow)
    data['KSampler']['input']['required']['sampler_name'] = [['euler']]
    with pytest.raises(WorkflowBundleError, match='sampler_name'):
        load_bundle(workflow).compile(schema_provider=provider(data, model_availability='target'))


def test_final_reconciliation_refreshes_through_the_same_target_transport(monkeypatch):
    import asyncio

    from vibecomfy.runtime.reconciliation import reconcile_before_queue_async
    import vibecomfy.schema.provider as provider_module

    workflow = workflow_from_ready('image/z_image_turbo')
    data = target_info(workflow)
    refreshed = copy.deepcopy(data)
    refreshed['UNETLoader']['input']['required']['unet_name'] = [['z_image_bf16.safetensors']]
    captures = []

    def capture():
        captures.append('same-target-client')
        return refreshed

    def forbidden_client(*_args, **_kwargs):
        raise AssertionError('external captures must retain the caller target transport')

    monkeypatch.setattr(provider_module, 'ComfyClient', forbidden_client)
    target = provider(data, model_availability='target', refresh_object_info=capture)
    old_digest = target._object_info_digest
    bundle = load_bundle(workflow)
    bundle.compile(schema_provider=target)
    reconciliation = asyncio.run(reconcile_before_queue_async(
        bundle, target_schema_provider=target, publish=False,
    ))
    assert captures == ['same-target-client']
    assert target._object_info_digest != old_digest
    assert reconciliation.schema['digest'] == target._object_info_digest
    with pytest.raises(WorkflowBundleError, match='not advertised by the selected target'):
        reconciliation.bundle.compile(schema_provider=target)


def test_external_capture_without_refresh_callback_cannot_reuse_stale_queue_evidence():
    import asyncio

    from vibecomfy.schema.provider import SchemaProviderError

    workflow = workflow_from_ready('image/z_image_turbo')
    target = provider(target_info(workflow), model_availability='target')
    with pytest.raises(SchemaProviderError, match='refresh_object_info'):
        asyncio.run(target.object_info_async())
