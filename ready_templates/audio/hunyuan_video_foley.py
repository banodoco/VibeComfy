# vibecomfy: generated
# For hand-editing, run: python -m vibecomfy.cli copy-to-recipe <id>
# vibecomfy: surface=canonical
"""Auto-generated ready_template — use python -m vibecomfy.cli copy-to-recipe <id> for hand-editing."""
from __future__ import annotations

from vibecomfy.templates import InputSpec, ModelAsset, OutputSpec, ReadyMetadata, new_workflow, node as raw_call, ref
from vibecomfy.workflow import VibeWorkflow
from vibecomfy.nodes.core import GetVideoComponents, LoadVideo, SaveAudio


DEFAULT_NEGATIVE = 'noisy, harsh'
DEFAULT_PROMPT = 'Synchronized footsteps on gravel.'
DEFAULT_SEED = 123
FOLEY_CHECKPOINT_NAME = 'hunyuanvideo_foley_xl.pth'
VAE_NAME = 'hunyuan_foley/vae_128d_48k.pth'
DEFAULT_VIDEO_REF = 'foley-input.mp4'


MODELS = {
    'hunyuanvideo_foley_xl': ModelAsset(url='https://huggingface.co/tencent/HunyuanVideo-Foley/resolve/3abd4e833b95b8db0fc9c687afc52483a48e9a97/hunyuanvideo_foley_xl.pth', sha256='cf7e93dca93063942bc22b53d4fe888e9d9d5a1ad7977873b7b2c6b126cf00ca', hf_revision='3abd4e833b95b8db0fc9c687afc52483a48e9a97', size_bytes=5854140970, subdir='hunyuan_foley'),
    'synchformer_state_dict': ModelAsset(url='https://huggingface.co/tencent/HunyuanVideo-Foley/resolve/3abd4e833b95b8db0fc9c687afc52483a48e9a97/synchformer_state_dict.pth', sha256='8aff082f2df5c3bc52759db0c865c7ee772ae6400b860d1b7e90413f2defb67c', hf_revision='3abd4e833b95b8db0fc9c687afc52483a48e9a97', size_bytes=950058171, subdir='hunyuan_foley'),
    'vae_128d_48k': ModelAsset(url='https://huggingface.co/tencent/HunyuanVideo-Foley/resolve/3abd4e833b95b8db0fc9c687afc52483a48e9a97/vae_128d_48k.pth', sha256='07e6139ff33bd21ba8a7a7f40ed24aab13ac0d100cd686f8a9f3e03dc5251cb1', hf_revision='3abd4e833b95b8db0fc9c687afc52483a48e9a97', size_bytes=1486465965, subdir='hunyuan_foley'),
    'model': ModelAsset(url='https://huggingface.co/google/siglip2-base-patch16-512/resolve/a89f5c5093f902bf39d3cd4d81d2c09867f0724b/model.safetensors', sha256='fe0e601c625e69eed8e73500d39e9b6164403fe03db8048e87913c3cefbbb3fe', hf_revision='a89f5c5093f902bf39d3cd4d81d2c09867f0724b', size_bytes=1503344520, subdir='hunyuan_foley/siglip2'),
    'config': ModelAsset(url='https://huggingface.co/google/siglip2-base-patch16-512/resolve/a89f5c5093f902bf39d3cd4d81d2c09867f0724b/config.json', sha256='a15bc39fbcd92498dea6d5d3cb2b0d8b9ba389d6a3f2b565ea66128a2d141934', hf_revision='a89f5c5093f902bf39d3cd4d81d2c09867f0724b', size_bytes=276, subdir='hunyuan_foley/siglip2'),
    'preprocessor_config': ModelAsset(url='https://huggingface.co/google/siglip2-base-patch16-512/resolve/a89f5c5093f902bf39d3cd4d81d2c09867f0724b/preprocessor_config.json', sha256='63ff380d3e424f93e6fbca5cc8e74eeed882e96fd6be2b7728aed308f3ad1513', hf_revision='a89f5c5093f902bf39d3cd4d81d2c09867f0724b', size_bytes=394, subdir='hunyuan_foley/siglip2'),
    'model_2': ModelAsset(url='https://huggingface.co/laion/larger_clap_general/resolve/16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db/model.safetensors', sha256='c3d0e564a97cb5eccea412f11d5c51c8a1ccceb80c51e3c6957bb5a796b423b6', hf_revision='16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db', size_bytes=776327440, subdir='hunyuan_foley/clap'),
    'config_2': ModelAsset(url='https://huggingface.co/laion/larger_clap_general/resolve/16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db/config.json', sha256='6268f76a067e3104bf9001e97d7dcc0fcfb16f3086cfb478ee72d95900d7fc1d', hf_revision='16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db', size_bytes=643, subdir='hunyuan_foley/clap'),
    'merges': ModelAsset(url='https://huggingface.co/laion/larger_clap_general/resolve/16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db/merges.txt', sha256='1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5', hf_revision='16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db', size_bytes=456318, subdir='hunyuan_foley/clap'),
    'vocab': ModelAsset(url='https://huggingface.co/laion/larger_clap_general/resolve/16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db/vocab.json', sha256='ed19656ea1707df69134c4af35c8ceda2cc9860bf2c3495026153a133670ab5e', hf_revision='16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db', size_bytes=798293, subdir='hunyuan_foley/clap'),
}


PUBLIC_INPUT_METADATA = {
    'seed': InputSpec(node=ref('hunyuanfoleysampler'), field='seed', default=DEFAULT_SEED, type='INT', infer_type=False),
    'video_ref': InputSpec(node=ref('loadvideo'), field='file', default=DEFAULT_VIDEO_REF, type='COMBO', required=True, media_semantics='video', infer_type=False),
    'prompt': InputSpec(node=ref('hunyuanfoleysampler'), field='prompt', default=DEFAULT_PROMPT, type='STRING', required=True, infer_type=False),
}


READY_METADATA = ReadyMetadata.build(
    capability='audio',
    template_id='audio/hunyuan_video_foley',
    inputs=PUBLIC_INPUT_METADATA,
    models=MODELS,
    custom_node_packs={'ComfyUI-HunyuanVideo_Foley': {'commit': 'b94f7aca877ff2be5bc264b057abee3dac682c1b', 'url': 'https://github.com/BobRandomNumber/ComfyUI-HunyuanVideo_Foley.git', 'class_schema_sha256': 'b997f40ea6ff56898d81210bcec94811396be39dc6192608ff5318f020ea6c0c', 'classes_used': ['DACHunyuanVAEDecode', 'HunyuanFoleyModelLoader', 'HunyuanFoleySampler', 'LoadDACHunyuanVAE'], 'pip_packages': ['descript-audiotools', 'diffusers', 'omegaconf', 'timm', 'transformers>=4.49.0'], 'status': 'discovered'}},
    source_path='ready_templates/sources/custom_nodes/hunyuan_foley/bobrandomnumber/hunyuan_video_foley.json',
    source_id='audio/hunyuan_video_foley',
    source_type='api',
    source_provenance={'records': [], 'requirements': [], 'warnings': [], 'conflicts': [], 'version_pins': [], 'required_pack_slugs': [], 'aux_only': [], 'unprovenanced': [], 'core_slug_non_core': [], 'low_confidence': False},
    source_hash='720916735c73726206dfa21fa235791c1cfd37330e74cc65ed2111a588e28747',
    output_mode='ready_template',
    artifact_class='execution_ready_candidate',
    execution_ready=True,
    ready_id='audio/hunyuan_video_foley',
    license_notice='Tencent Hunyuan Community license excludes the EU, UK, and South Korea.',
    provenance={'source_path': 'ready_templates/sources/custom_nodes/hunyuan_foley/bobrandomnumber/hunyuan_video_foley.json', 'source_id': 'audio/hunyuan_video_foley', 'source_type': 'api', 'source_provenance': {'records': [], 'requirements': [], 'warnings': [], 'conflicts': [], 'version_pins': [], 'required_pack_slugs': [], 'aux_only': [], 'unprovenanced': [], 'core_slug_non_core': [], 'low_confidence': False}, 'source_hash': '720916735c73726206dfa21fa235791c1cfd37330e74cc65ed2111a588e28747', 'output_mode': 'ready_template', 'artifact_class': 'execution_ready_candidate', 'execution_ready': True, 'ready_id': 'audio/hunyuan_video_foley', 'source_workflow': 'ready_templates/sources/custom_nodes/hunyuan_foley/bobrandomnumber/hunyuan_video_foley.json'},
    source_bundle={'format_version': 2, 'generation_id': '5548cf57ba27539d18c4d662f851366c8cc54b5f85e40962bc79f9c501de29d4', 'custody_digest': 'a2810246152f374153d2943809460f7e61c973b7c5ef25178b825c5ec55a7181'},
)

def build() -> VibeWorkflow:
    """Build the workflow (auto-generated)."""
    with new_workflow(READY_METADATA, source_path=__file__) as wf:

        hunyuanfoleymodelloader = raw_call('HunyuanFoleyModelLoader',
            _outputs=('FOLEY_MODEL',),
            foley_checkpoint_name=FOLEY_CHECKPOINT_NAME,
            model_path_name='hunyuan_foley',
        )

        loaddachunyuanvae = raw_call('LoadDACHunyuanVAE', _outputs=('VAE',), vae_name=VAE_NAME)
        loadvideo = LoadVideo(file=DEFAULT_VIDEO_REF)
        getvideocomponents = GetVideoComponents(video=loadvideo.out(0))

        hunyuanfoleysampler = raw_call('HunyuanFoleySampler',
            _outputs=('LATENT',),
            guidance_scale=4.5,
            negative_prompt=DEFAULT_NEGATIVE,
            prompt=DEFAULT_PROMPT,
            seed=DEFAULT_SEED,
            steps=50,
            foley_model=hunyuanfoleymodelloader.out('FOLEY_MODEL'),
            fps=getvideocomponents.out(2),
            video_frames=getvideocomponents.out(0),
        )

        dachunyuanvaedecode = raw_call('DACHunyuanVAEDecode',
            _outputs=('AUDIO',),
            unload_models_after_use=True,
            samples=hunyuanfoleysampler.out('LATENT'),
            vae=loaddachunyuanvae.out('VAE'),
        )

        saveaudio = SaveAudio(
            filename_prefix='audio/hunyuan_video_foley',
            audio=dachunyuanvaedecode.out('AUDIO'),
        )

        wf.strict_types = False
        return wf.finalize(PUBLIC_INPUT_METADATA, outputs=[OutputSpec(node=saveaudio, output_type='SaveAudio', name='audio', artifact_kind='audio', mime_type='audio/flac', filename_prefix='audio/hunyuan_video_foley', expected_cardinality='one')])

