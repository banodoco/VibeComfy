"""Model picker spellings must retain their authored asset's path and identity."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from vibecomfy.model_assets import model_picker_value, resolve_authored_asset_reference, resolve_referenced_assets
from vibecomfy.schema.provider import TargetSchemaProvider
from vibecomfy.workflow import VibeNode, VibeWorkflow, WorkflowSource
from vibecomfy.workflow_bundle import WorkflowBundleError, load_bundle

from tests.test_target_model_bundle_custody import _target_info


def _workflow(value, assets):
    workflow = VibeWorkflow('reference-custody', WorkflowSource('reference-custody'))
    workflow.metadata['model_assets'] = assets
    workflow.nodes['1'] = VibeNode('1', 'UNETLoader', inputs={'unet_name': value})
    return workflow


ASSET = {'name': 'nested/model.pth', 'subdir': 'diffusion_models',
         'url': 'https://example.invalid/model.pth', 'sha256': '1' * 64, 'size_bytes': 5}


@pytest.mark.parametrize('asset,folder,value', [
    ({'name': 'model.pth', 'subdir': 'diffusion_models/nested'}, 'diffusion_models', 'nested/model.pth'),
    (ASSET, 'diffusion_models', 'nested/model.pth'),
    ({'name': 'vae_128d_48k.pth', 'subdir': 'hunyuan_foley'}, 'hunyuan_foley', 'vae_128d_48k.pth'),
])
@pytest.mark.parametrize('qualified', [False, True])
def test_model_picker_mapping_roundtrips_declared_destination(asset, folder, value, qualified):
    picker = model_picker_value(asset, folder, qualified=qualified)
    assert picker == (f'{folder}/{value}' if qualified else value)
    assert resolve_authored_asset_reference(picker, folder, [asset]) == asset


def test_reconcile_model_requirements_retains_subdirectory_identity():
    from vibecomfy.model_assets import reconcile_model_requirements

    old = {'name': 'model.pth', 'subdir': 'diffusion_models/old'}
    new = {'name': 'model.pth', 'subdir': 'diffusion_models/new'}
    assert reconcile_model_requirements([old, old], [new]) == [new]


@pytest.mark.parametrize('value', ['nested/model.pth', 'diffusion_models/nested/model.pth'])
def test_runtime_reference_uses_declared_asset_identity(value):
    resolved, unresolved = resolve_referenced_assets(_workflow(value, [ASSET]), registry=[])
    assert not unresolved
    assert len(resolved) == 1
    assert all(resolved[0][key] == expected for key, expected in ASSET.items())


@pytest.mark.parametrize('value', ['other/model.pth', 'model.pth',
                                   'other/nested/model.pth'])
def test_runtime_reference_refuses_same_basename_with_wrong_prefix(value):
    resolved, unresolved = resolve_referenced_assets(_workflow(value, [ASSET]), registry=[])
    assert not resolved
    assert [entry['value'] for entry in unresolved] == [value]


@pytest.mark.parametrize('change', [{}, {'sha256': '2' * 64},
                                   {'target_path': 'custom_nodes/pack/model.pth'}])
def test_runtime_reference_rejects_duplicate_or_conflicting_declarations(change):
    with pytest.raises(ValueError, match='ambiguous.*model asset'):
        resolve_referenced_assets(
            _workflow(ASSET['name'], [ASSET, {**ASSET, **change}]), registry=[])


def test_qualified_reference_keeps_distinct_subdirectory_custody():
    other = {**ASSET, 'subdir': 'other_models', 'sha256': '2' * 64}
    assert resolve_authored_asset_reference(ASSET['name'], ASSET['subdir'], [ASSET, other]) == ASSET
    with pytest.raises(ValueError, match='ambiguous.*model asset'):
        resolve_authored_asset_reference(ASSET['name'], '', [ASSET, other])
    assert resolve_authored_asset_reference('diffusion_models/nested/model.pth', '', [ASSET, other]) == ASSET


def test_cross_subdirectory_declarations_cannot_claim_the_same_destination():
    other = {**ASSET, 'subdir': 'diffusion_models/nested', 'name': 'model.pth'}
    with pytest.raises(ValueError, match='ambiguous.*model asset'):
        resolve_referenced_assets(_workflow('diffusion_models/nested/model.pth', [ASSET, other]), registry=[])


def test_declared_subdirectory_is_normalized_without_repairing_picker_prefix():
    asset = {**ASSET, 'subdir': './diffusion_models'}
    resolved, unresolved = resolve_referenced_assets(
        _workflow('diffusion_models/nested/model.pth', [asset]), registry=[])
    assert not unresolved
    assert resolved[0]['name'] == asset['name']
    assert resolved[0]['subdir'] == asset['subdir']


@pytest.mark.parametrize('subdir,directory', [
    ('diffusion_models', './diffusion_models'),
    ('./diffusion_models', 'diffusion_models'),
])
@pytest.mark.parametrize('target_path', [None, 'custom_nodes/pack/model.pth'])
def test_runtime_rejects_legacy_model_field_aliases_without_mutating_declaration(
    tmp_path, monkeypatch, subdir, directory, target_path,
):
    from vibecomfy.fetch import local_path
    from vibecomfy.errors import ModelAssetError
    from vibecomfy.runtime.session import _model_assets_from_workflow

    asset = {**ASSET, 'subdir': subdir, 'directory': directory,
             'filename': './nested/model.pth'}
    if target_path is not None:
        asset['target_path'] = target_path
    workflow = _workflow(asset['name'], [asset])
    monkeypatch.setattr('vibecomfy.registry.models_loader.load_registry', lambda: ())
    before = dict(asset)
    with pytest.raises(ValueError, match='filename/directory aliases'):
        local_path(asset, root=tmp_path)
    with pytest.raises(ModelAssetError, match='invalid workflow model asset declarations: .*filename/directory aliases'):
        _model_assets_from_workflow(workflow, models_root=tmp_path)
    assert asset == before


@pytest.mark.parametrize('value', ['/models/nested/model.pth', '../nested/model.pth',
                                   'other/../nested/model.pth', r'nested\model.pth',
                                   r'C:\models\nested\model.pth'])
def test_runtime_reference_never_repairs_unsafe_picker_paths(value):
    resolved, unresolved = resolve_referenced_assets(_workflow(value, [ASSET]), registry=[])
    assert not resolved
    assert unresolved[0]['value'] == value


def _local_foley(tmp_path, monkeypatch):
    bundle = load_bundle(Path(__file__).resolve().parents[1] /
                         'ready_templates/audio/hunyuan_video_foley.py')
    workflow = bundle.workflow
    for index, asset in enumerate(workflow.metadata['model_assets']):
        content = f'CPU model fixture {index}'.encode()
        asset.update(sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content))
        path = tmp_path / asset['subdir'] / asset['name']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    monkeypatch.setattr('vibecomfy.registry.models_loader.load_registry', lambda: ())
    provider = TargetSchemaProvider.from_object_info(
        _target_info(workflow), server_url='http://local.invalid:8188',
        model_availability='local', auxiliary_model_custody='local')
    return workflow, provider


@pytest.mark.parametrize('change', ['match', 'missing', 'hash', 'size', 'decoy'])
def test_actual_foley_picker_verifies_canonical_local_asset(tmp_path, monkeypatch, change):
    workflow, provider = _local_foley(tmp_path, monkeypatch)
    path = tmp_path / 'hunyuan_foley/vae_128d_48k.pth'
    assert workflow.nodes['12'].inputs['vae_name'] == 'hunyuan_foley/vae_128d_48k.pth'
    if change in {'missing', 'decoy'}:
        path.unlink()
        if change == 'decoy':
            decoy = tmp_path / 'hunyuan_foley/hunyuan_foley/vae_128d_48k.pth'
            decoy.parent.mkdir()
            decoy.write_bytes(b'decoy must not discharge canonical asset')
    elif change == 'hash':
        path.write_bytes(b'x' * path.stat().st_size)
    elif change == 'size':
        path.write_bytes(path.read_bytes() + b'x')
    if change == 'match':
        record = load_bundle(workflow).compile(schema_provider=provider, models_root=tmp_path)
        assert record.api_projection['12']['inputs']['vae_name'] == 'hunyuan_foley/vae_128d_48k.pth'
    else:
        with pytest.raises(WorkflowBundleError, match='(not present locally|verification failed)'):
            load_bundle(workflow).compile(schema_provider=provider, models_root=tmp_path)


@pytest.mark.parametrize('change', ['duplicate', 'hash', 'target_path'])
def test_local_foley_rejects_conflicting_asset_declarations(tmp_path, monkeypatch, change):
    workflow, provider = _local_foley(tmp_path, monkeypatch)
    asset = next(a for a in workflow.metadata['model_assets'] if a['name'] == 'vae_128d_48k.pth')
    conflict = dict(asset)
    if change == 'hash':
        conflict['sha256'] = '0' * 64
    elif change == 'target_path':
        conflict['target_path'] = 'custom_nodes/pack/vae_128d_48k.pth'
    workflow.metadata['model_assets'].append(conflict)
    with pytest.raises(WorkflowBundleError, match='ambiguous.*model asset'):
        load_bundle(workflow).compile(schema_provider=provider, models_root=tmp_path)


def test_local_foley_rejects_same_basename_with_wrong_prefix(tmp_path, monkeypatch):
    workflow, provider = _local_foley(tmp_path, monkeypatch)
    workflow.nodes['12'].inputs['vae_name'] = 'other/vae_128d_48k.pth'
    with pytest.raises(WorkflowBundleError, match='not locally registered: other/vae_128d_48k.pth'):
        load_bundle(workflow).compile(schema_provider=provider, models_root=tmp_path)


def test_actual_foley_runtime_stages_canonical_asset_once(tmp_path, monkeypatch):
    from vibecomfy.runtime.session import _model_assets_from_workflow

    workflow, _ = _local_foley(tmp_path, monkeypatch)
    assets = _model_assets_from_workflow(workflow, models_root=tmp_path)
    vaes = [asset for asset in assets if asset['name'] == 'vae_128d_48k.pth']
    assert len(assets) == 10
    assert len(vaes) == 1
    assert vaes[0]['subdir'] == 'hunyuan_foley'


@pytest.mark.parametrize('value', ['other/vae_128d_48k.pth', '../vae_128d_48k.pth',
                                   '/models/vae_128d_48k.pth',
                                   r'hunyuan_foley\vae_128d_48k.pth'])
def test_actual_foley_runtime_rejects_unresolved_picker_without_basename_repair(
    tmp_path, monkeypatch, value,
):
    from vibecomfy.errors import ModelAssetError
    from vibecomfy.runtime.session import _model_assets_from_workflow

    workflow, _ = _local_foley(tmp_path, monkeypatch)
    workflow.nodes['12'].inputs['vae_name'] = value
    with pytest.raises(ModelAssetError, match='unresolved workflow model assets'):
        _model_assets_from_workflow(workflow, models_root=tmp_path)


@pytest.mark.parametrize('consumer', ['runtime', 'approval', 'target_approval'])
@pytest.mark.parametrize('conflict', ['auxiliary_duplicate', 'directory_alias', 'filename_alias',
                                      'target_path', 'cross_kind'])
def test_all_foley_declarations_reject_conflicting_custody_before_deduplication(
    tmp_path, monkeypatch, consumer, conflict,
):
    from vibecomfy.errors import ModelAssetError
    from vibecomfy.runtime.session import _model_assets_from_workflow

    root = tmp_path / 'models'
    workflow, provider = _local_foley(root, monkeypatch)
    assets = workflow.metadata['model_assets']
    if consumer == 'target_approval':
        provider = TargetSchemaProvider.from_object_info(
            _target_info(workflow), server_url='http://target.invalid:8188',
            model_availability='target', auxiliary_model_custody='target',
            target_model_assets=[{'name': asset['name'], 'subdir': asset['subdir'],
                                  'sha256': asset['sha256'], 'size': asset['size_bytes']}
                                 for asset in assets],
        )
    auxiliary = next(a for a in assets if a['name'] == 'synchformer_state_dict.pth')
    if conflict == 'auxiliary_duplicate':
        assets.append({**auxiliary, 'sha256': '0' * 64})
    elif conflict == 'directory_alias':
        auxiliary['directory'] = 'other_models'
    elif conflict == 'filename_alias':
        auxiliary['filename'] = 'other.pth'
    else:
        content = b'model'
        first = {'name': 'custody-a.pth', 'subdir': 'hunyuan_foley',
                 'url': 'https://example.invalid/model.pth', 'size_bytes': len(content),
                 'sha256': hashlib.sha256(content).hexdigest()}
        if conflict == 'target_path':
            first['target_path'] = 'custom_nodes/pack/shared.pth'
            destination = tmp_path / first['target_path']
        else:
            destination = root / first['subdir'] / first['name']
        second = {**first, 'name': 'custody-b.pth', 'sha256': '0' * 64,
                  'target_path': 'custom_nodes/pack/shared.pth' if conflict == 'target_path'
                  else 'models/hunyuan_foley/custody-a.pth'}
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        assets.extend([first, second])
    expected = ModelAssetError if consumer == 'runtime' else WorkflowBundleError
    if conflict in {'directory_alias', 'filename_alias'}:
        rejection = 'filename/directory aliases'
    elif conflict == 'cross_kind':
        rejection = 'target_path is only for files inside a custom-node pack'
    else:
        rejection = 'ambiguous.*model asset'
    with pytest.raises(expected, match=rejection):
        if consumer != 'runtime':
            load_bundle(workflow).compile(schema_provider=provider, models_root=root)
        else:
            _model_assets_from_workflow(workflow, models_root=root)


@pytest.mark.parametrize('consumer', ['runtime', 'approval'])
@pytest.mark.parametrize('representation', ['target_path', 'nested_subdir'])
def test_authored_target_path_misuse_or_registry_collision_is_refused(
    tmp_path, monkeypatch, consumer, representation,
):
    from vibecomfy.errors import ModelAssetError
    from vibecomfy.registry.models_loader import ModelEntry, ModelSource, ModelTarget
    from vibecomfy.runtime.session import _model_assets_from_workflow

    root = tmp_path / 'models'
    workflow, _ = _local_foley(root, monkeypatch)
    content = b'model'
    asset = {
        'name': 'a.pth', 'subdir': 'diffusion_models',
        'target_path': 'models/diffusion_models/b.pth',
        'url': 'https://example.invalid/a.pth', 'size_bytes': len(content),
        'sha256': hashlib.sha256(content).hexdigest(),
    }
    authored_picker, registry_picker = 'a.pth', 'b.pth'
    if representation == 'nested_subdir':
        asset.pop('target_path')
        asset['subdir'] = 'diffusion_models/nested'
        authored_picker = registry_picker = 'nested/a.pth'
    workflow.metadata['model_assets'].append(asset)
    workflow.nodes['90'] = VibeNode(
        '90', 'UNETLoader', inputs={'unet_name': authored_picker, 'weight_dtype': 'default'}, uid='custody-a')
    workflow.nodes['91'] = VibeNode(
        '91', 'UNETLoader', inputs={'unet_name': registry_picker, 'weight_dtype': 'default'}, uid='custody-b')
    destination = root / 'diffusion_models' / registry_picker
    destination.parent.mkdir(parents=True)
    destination.write_bytes(content)
    registry = [ModelEntry(
        id='registry-collision', source=ModelSource(kind='url', url='https://example.invalid/b.pth'),
        canonical_name=registry_picker, sha256='2' * 64, size_bytes=len(content), min_size=1,
        targets=(ModelTarget('comfy_core', f'diffusion_models/{registry_picker}'),),
    )]
    if representation == 'nested_subdir':
        # Both pickers now correctly bind the same authored nested asset.
        # Declare the competing source in the IR to test a real destination
        # collision; preparation must not derive declarations from a registry.
        workflow.metadata['model_assets'].append({
            'name': registry_picker, 'subdir': 'diffusion_models',
            'url': registry[0].source.url, 'sha256': registry[0].sha256,
            'size_bytes': registry[0].size_bytes,
        })
    monkeypatch.setattr('vibecomfy.registry.models_loader.load_registry', lambda: registry)
    info = _target_info(workflow)
    info['UNETLoader']['input']['required']['unet_name'] = [[authored_picker, registry_picker]]
    provider = TargetSchemaProvider.from_object_info(
        info, server_url='http://local.invalid:8188', model_availability='local')
    expected = ModelAssetError if consumer == 'runtime' else WorkflowBundleError
    if representation == 'target_path':
        rejection = 'target_path is only for files inside a custom-node pack'
    else:
        rejection = 'ambiguous.*model asset'
    with pytest.raises(expected, match=rejection):
        if consumer == 'runtime':
            _model_assets_from_workflow(workflow, models_root=root)
        else:
            load_bundle(workflow).compile(schema_provider=provider, models_root=root)


@pytest.mark.parametrize('custody', ['local', 'target'])
@pytest.mark.parametrize('value', ['/models/vae_128d_48k.pth', '../vae_128d_48k.pth',
                                   'other/../vae_128d_48k.pth', r'other\..\vae_128d_48k.pth',
                                   r'C:\models\vae_128d_48k.pth', r'hunyuan_foley\vae_128d_48k.pth'])
def test_foley_approval_refuses_unsafe_paths_and_requires_target_authority_for_backslashes(
    tmp_path, monkeypatch, custody, value,
):
    workflow, provider = _local_foley(tmp_path, monkeypatch)
    workflow.nodes['12'].inputs['vae_name'] = value
    if custody == 'target':
        info = _target_info(workflow)
        info['LoadDACHunyuanVAE']['input']['required']['vae_name'] = [[value]]
        provider = TargetSchemaProvider.from_object_info(
            info, server_url='http://target.invalid:8188', model_availability='target')
    if custody == 'target' and value == r'hunyuan_foley\vae_128d_48k.pth':
        record = load_bundle(workflow).compile(schema_provider=provider, models_root=tmp_path)
        assert record.api_projection['12']['inputs']['vae_name'] == value
    else:
        with pytest.raises(WorkflowBundleError, match='model asset reference must be.*relative path'):
            load_bundle(workflow).compile(schema_provider=provider, models_root=tmp_path)
