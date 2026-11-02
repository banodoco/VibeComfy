"""Canonical publication and selected-target auxiliary model custody."""
import pytest
from vibecomfy.registry.ready import workflow_from_ready
from vibecomfy.security.provenance import Provenance
from vibecomfy.workflow_bundle import emit_bundle, load_bundle


def test_target_filename_survives_canonical_source_publication(tmp_path):
    workflow = workflow_from_ready("image/z_image_turbo")
    exact_vae = r"FLUX1\ae.safetensors"
    workflow.set_input("vae", exact_vae)
    workflow.requirements.models = [
        exact_vae if isinstance(item, dict) and item.get("name") == "ae.safetensors" else item
        for item in workflow.requirements.models
    ]
    # The selected filename is attested by a target picker, not by the old
    # default filename's download URL/hash. Other download witnesses remain.
    workflow.metadata["model_assets"] = [
        item for item in workflow.metadata["model_assets"] if item.get("name") != "ae.safetensors"
    ]
    before = workflow.semantic_digest()
    published = emit_bundle(workflow, tmp_path / "workflow.py", {"operation": "authored"})
    loaded = load_bundle(published.python_path, trust=Provenance.USER_CONFIRMED)
    loaded.require_canonical_authority("target model publication regression")
    assert loaded.workflow.semantic_digest() == before
    assert exact_vae in loaded.workflow.requirements.models
    assert len(loaded.workflow.requirements.models) == 3
    assert loaded.workflow.inputs["vae"].value == exact_vae
    api = loaded.workflow.compile("api")
    vae = next(node for node in api.values() if node["class_type"] == "VAELoader")
    assert vae["inputs"]["vae_name"] == exact_vae


# This declaration is the fake target's provisioning data, independent from
# graph picker choices and from the workflow's authored requirements.
SYNCHFORMER = {
    'name': 'synchformer_state_dict.pth', 'subdir': 'hunyuan_foley',
    'size': 950058171,
    'sha256': '8aff082f2df5c3bc52759db0c865c7ee772ae6400b860d1b7e90413f2defb67c',
}


def _target_info(workflow):
    import copy
    from vibecomfy.porting.object_info import get_class

    result = {}
    for node in workflow.runtime_nodes().values():
        definition = get_class(node.class_type)
        assert definition is not None, node.class_type
        result[node.class_type] = {
            'input': copy.deepcopy(definition['inputs']),
            'input_order': copy.deepcopy(definition['input_order']),
            'output': [out['type'] for out in definition['outputs']],
            'output_name': [out['name'] for out in definition['outputs']],
            'output_is_list': [out['is_list'] for out in definition['outputs']],
            'output_node': node.class_type == 'SaveAudio',
        }
    for cls, field, name in (
        ('UNETLoader', 'unet_name', 'z_image_turbo_bf16.safetensors'),
        ('CLIPLoader', 'clip_name', 'qwen_3_4b.safetensors'),
        ('VAELoader', 'vae_name', 'ae.safetensors'),
    ):
        if cls in result:
            result[cls]['input']['required'][field] = [[name]]
    return result


def _auxiliary_workflow():
    workflow = workflow_from_ready('image/z_image_turbo')
    workflow.metadata['model_assets'].append({
        'name': SYNCHFORMER['name'], 'subdir': SYNCHFORMER['subdir'],
        'sha256': SYNCHFORMER['sha256'], 'size_bytes': SYNCHFORMER['size'],
        'url': 'https://huggingface.co/tencent/HunyuanVideo-Foley/resolve/'
               '3abd4e833b95b8db0fc9c687afc52483a48e9a97/synchformer_state_dict.pth',
    })
    return workflow


def _target(workflow, *, custody='target', assets=()):
    from vibecomfy.schema.provider import TargetSchemaProvider

    return TargetSchemaProvider.from_object_info(
        _target_info(workflow), server_url='http://selected-target.invalid:8188',
        model_availability='target', auxiliary_model_custody=custody,
        target_model_assets=assets,
    )


def test_auxiliary_asset_missing_locally_is_rejected(tmp_path):
    import pytest
    from vibecomfy.workflow_bundle import WorkflowBundleError

    workflow = _auxiliary_workflow()
    # A local execution cannot use even a correct remote declaration.
    target = _target(workflow, custody='local', assets=[SYNCHFORMER])
    with pytest.raises(WorkflowBundleError, match='not present locally: synchformer_state_dict.pth'):
        load_bundle(workflow).compile(schema_provider=target, models_root=tmp_path)


def test_auxiliary_asset_matching_target_declaration_is_approved(tmp_path):
    workflow = _auxiliary_workflow()
    declaration = dict(SYNCHFORMER)
    target = _target(workflow, assets=[declaration])
    # Captures must be detached, including their returned public view.
    declaration['sha256'] = '0' * 64
    target.target_model_asset(SYNCHFORMER['name'], SYNCHFORMER['subdir'])['size'] = 0
    record = load_bundle(workflow).compile(schema_provider=target, models_root=tmp_path)
    assert record.api_digest
    evidence = [row for row in target._approval_diagnostics if row['code'] == 'target_model_asset']
    assert len(evidence) == 1
    assert all(evidence[0][key] == value for key, value in SYNCHFORMER.items())
    assert evidence[0]['model_bytes_status'] == 'verified_target_provisioning'
    assert not list(tmp_path.iterdir())  # No host model copy or download.


@pytest.mark.parametrize('change', ['sha256', 'size', 'name', 'subdir', 'missing'])
def test_auxiliary_asset_wrong_target_identity_is_rejected(tmp_path, change):
    from vibecomfy.workflow_bundle import WorkflowBundleError

    workflow = _auxiliary_workflow()
    declaration = dict(SYNCHFORMER)
    declaration.update({'sha256': '0' * 64} if change == 'sha256' else
                       {'size': SYNCHFORMER['size'] + 1} if change == 'size' else
                       {'name': 'different.pth'} if change == 'name' else
                       {'subdir': 'other'} if change == 'subdir' else {})
    target = _target(workflow, assets=[] if change == 'missing' else [declaration])
    with pytest.raises(WorkflowBundleError, match='selected target.*(identity mismatch|does not declare)'):
        load_bundle(workflow).compile(schema_provider=target, models_root=tmp_path)


@pytest.mark.parametrize('change', ['match', 'sha256', 'size'])
def test_local_auxiliary_asset_verifies_local_bytes_at_explicit_root(tmp_path, change):
    import hashlib
    from vibecomfy.workflow_bundle import WorkflowBundleError

    workflow = _auxiliary_workflow()
    asset = workflow.metadata['model_assets'][-1]
    content = b'CPU custody fixture; not model weights'
    asset.update(sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content))
    path = tmp_path / asset['subdir'] / asset['name']
    path.parent.mkdir()
    path.write_bytes(content if change == 'match' else
                     b'x' * len(content) if change == 'sha256' else content + b'x')
    workflow.metadata['models_root'] = str(tmp_path)
    target = _target(workflow, custody='local', assets=[SYNCHFORMER])
    if change == 'match':
        assert load_bundle(workflow).compile(schema_provider=target).api_digest
    else:
        with pytest.raises(WorkflowBundleError, match='verification failed'):
            load_bundle(workflow).compile(schema_provider=target)


def test_foley_approves_only_with_its_selected_targets_complete_auxiliary_inventory(tmp_path):
    import json
    from pathlib import Path
    bundle = load_bundle(Path(__file__).resolve().parents[1] /
                         'ready_templates/audio/hunyuan_video_foley.py')
    workflow = bundle.workflow
    # Fake target explicitly declares its provisioned assets from its own lock.
    lock = json.loads((Path(__file__).resolve().parents[1] /
        'ready_templates/sources/custom_nodes/hunyuan_foley/bobrandomnumber/assets.json').read_text())
    assets = [{'name': row['name'], 'subdir': row['subdir'], 'sha256': row['sha256'],
               'size': row['size_bytes']} for row in lock['assets']]
    target = _target(workflow, assets=assets)
    record = bundle.compile(schema_provider=target, models_root=tmp_path)
    assert record.api_digest
    assert any(row.get('name') == SYNCHFORMER['name'] for row in target._approval_diagnostics)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('bad', [
    {'size': True}, {'sha256': 'not-a-hash'}, {'name': ''}, {'subdir': None},
])
def test_target_asset_declaration_requires_exact_identity(bad):
    workflow = _auxiliary_workflow()
    with pytest.raises(ValueError, match='target model asset'):
        _target(workflow, assets=[{**SYNCHFORMER, **bad}])
