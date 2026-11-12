# vibecomfy: manual
"""Hunyuan-Foley video-to-audio (SFX) ready template.

Hand-written through the node() ABI. Public inputs: ``video`` (a muted clip,
bound through LoadVideo), ``prompt``, ``negative_prompt``, ``seed``, ``steps``,
``guidance_scale``. Output: the original frames muxed with generated foley.

Node input names were taken from the pack at commit
``b94f7aca877ff2be5bc264b057abee3dac682c1b``
(BobRandomNumber/ComfyUI-HunyuanVideo_Foley) and its example workflow
``example_workflows/Hunyuan-Foley.json``. They must be checked against live
``/object_info`` on the 5090 run; any mismatch is a bug to report.

Licence: Tencent Hunyuan Community.
"""
from __future__ import annotations

from vibecomfy.templates import InputSpec, ReadyMetadata, new_workflow, node


DEFAULT_PROMPT = 'A sledgehammer smashes a glass bottle: a heavy whoosh, a sharp glass shatter and tinkling shards. No speech is present. No music is present.'
DEFAULT_NEGATIVE_PROMPT = 'music, melody, song, singing, vocals, score, soundtrack, beat, rhythm bed, instrumental backing, speech, dialogue, talking, narration, tinny, thin, harsh, clipped, distorted, low bitrate'
DEFAULT_VIDEO = 'muted_clip.mp4'
DEFAULT_SEED = 42
DEFAULT_STEPS = 50
DEFAULT_GUIDANCE = 4.5
MODEL_DIR = 'hunyuan_foley'
FOLEY_CHECKPOINT = 'hunyuanvideo_foley_xl.pth'
DAC_VAE = 'hunyuan_foley/vae_128d_48k.pth'
PACK_COMMIT = 'b94f7aca877ff2be5bc264b057abee3dac682c1b'
PACK_URL = 'https://github.com/BobRandomNumber/ComfyUI-HunyuanVideo_Foley.git'


PUBLIC_INPUT_METADATA = {
    'video': InputSpec(node='1', field='file', default=DEFAULT_VIDEO, media_semantics='video'),
    'prompt': InputSpec(node='5', field='prompt', default=DEFAULT_PROMPT, media_semantics='text'),
    'negative_prompt': InputSpec(node='5', field='negative_prompt', default=DEFAULT_NEGATIVE_PROMPT, aliases=('negative',), media_semantics='text'),
    'seed': InputSpec(node='5', field='seed', default=DEFAULT_SEED),
    'steps': InputSpec(node='5', field='steps', default=DEFAULT_STEPS),
    'guidance_scale': InputSpec(node='5', field='guidance_scale', default=DEFAULT_GUIDANCE),
}

READY_METADATA = ReadyMetadata.build(
    capability='audio',
    inputs=PUBLIC_INPUT_METADATA,
    requirements={'models': [{'name': 'hunyuanvideo_foley_xl.pth',
             'subdir': 'hunyuan_foley',
             'url': 'https://huggingface.co/tencent/HunyuanVideo-Foley/resolve/3abd4e833b95b8db0fc9c687afc52483a48e9a97/hunyuanvideo_foley_xl.pth',
             'sha256': 'cf7e93dca93063942bc22b53d4fe888e9d9d5a1ad7977873b7b2c6b126cf00ca',
             'size_bytes': 5854140970,
             'hf_revision': '3abd4e833b95b8db0fc9c687afc52483a48e9a97'},
            {'name': 'synchformer_state_dict.pth',
             'subdir': 'hunyuan_foley',
             'url': 'https://huggingface.co/tencent/HunyuanVideo-Foley/resolve/3abd4e833b95b8db0fc9c687afc52483a48e9a97/synchformer_state_dict.pth',
             'sha256': '8aff082f2df5c3bc52759db0c865c7ee772ae6400b860d1b7e90413f2defb67c',
             'size_bytes': 950058171,
             'hf_revision': '3abd4e833b95b8db0fc9c687afc52483a48e9a97'},
            {'name': 'vae_128d_48k.pth',
             'subdir': 'hunyuan_foley',
             'url': 'https://huggingface.co/tencent/HunyuanVideo-Foley/resolve/3abd4e833b95b8db0fc9c687afc52483a48e9a97/vae_128d_48k.pth',
             'sha256': '07e6139ff33bd21ba8a7a7f40ed24aab13ac0d100cd686f8a9f3e03dc5251cb1',
             'size_bytes': 1486465965,
             'hf_revision': '3abd4e833b95b8db0fc9c687afc52483a48e9a97'},
            {'name': 'model.safetensors',
             'subdir': 'hunyuan_foley/siglip2',
             'url': 'https://huggingface.co/google/siglip2-base-patch16-512/resolve/a89f5c5093f902bf39d3cd4d81d2c09867f0724b/model.safetensors',
             'sha256': 'fe0e601c625e69eed8e73500d39e9b6164403fe03db8048e87913c3cefbbb3fe',
             'size_bytes': 1503344520,
             'hf_revision': 'a89f5c5093f902bf39d3cd4d81d2c09867f0724b'},
            {'name': 'config.json',
             'subdir': 'hunyuan_foley/siglip2',
             'url': 'https://huggingface.co/google/siglip2-base-patch16-512/resolve/a89f5c5093f902bf39d3cd4d81d2c09867f0724b/config.json',
             'sha256': 'a15bc39fbcd92498dea6d5d3cb2b0d8b9ba389d6a3f2b565ea66128a2d141934',
             'size_bytes': 276,
             'hf_revision': 'a89f5c5093f902bf39d3cd4d81d2c09867f0724b'},
            {'name': 'preprocessor_config.json',
             'subdir': 'hunyuan_foley/siglip2',
             'url': 'https://huggingface.co/google/siglip2-base-patch16-512/resolve/a89f5c5093f902bf39d3cd4d81d2c09867f0724b/preprocessor_config.json',
             'sha256': '63ff380d3e424f93e6fbca5cc8e74eeed882e96fd6be2b7728aed308f3ad1513',
             'size_bytes': 394,
             'hf_revision': 'a89f5c5093f902bf39d3cd4d81d2c09867f0724b'},
            {'name': 'model.safetensors',
             'subdir': 'hunyuan_foley/clap',
             'url': 'https://huggingface.co/laion/larger_clap_general/resolve/16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db/model.safetensors',
             'sha256': 'c3d0e564a97cb5eccea412f11d5c51c8a1ccceb80c51e3c6957bb5a796b423b6',
             'size_bytes': 776327440,
             'hf_revision': '16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db'},
            {'name': 'config.json',
             'subdir': 'hunyuan_foley/clap',
             'url': 'https://huggingface.co/laion/larger_clap_general/resolve/16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db/config.json',
             'sha256': '6268f76a067e3104bf9001e97d7dcc0fcfb16f3086cfb478ee72d95900d7fc1d',
             'size_bytes': 643,
             'hf_revision': '16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db'},
            {'name': 'merges.txt',
             'subdir': 'hunyuan_foley/clap',
             'url': 'https://huggingface.co/laion/larger_clap_general/resolve/16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db/merges.txt',
             'sha256': '1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5',
             'size_bytes': 456318,
             'hf_revision': '16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db'},
            {'name': 'vocab.json',
             'subdir': 'hunyuan_foley/clap',
             'url': 'https://huggingface.co/laion/larger_clap_general/resolve/16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db/vocab.json',
             'sha256': 'ed19656ea1707df69134c4af35c8ceda2cc9860bf2c3495026153a133670ab5e',
             'size_bytes': 798293,
             'hf_revision': '16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db'}]},
    custom_node_packs={
        'ComfyUI-HunyuanVideo_Foley': {
            'commit': PACK_COMMIT,
            'url': PACK_URL,
            'class_schema_sha256': None,
            'classes_used': ['HunyuanFoleyModelLoader', 'LoadDACHunyuanVAE', 'HunyuanFoleySampler', 'DACHunyuanVAEDecode'],
            'pip_packages': ['diffusers', 'timm', 'transformers', 'descript-audiotools', 'omegaconf'],
            'status': 'pinned-unverified-live',
        },
    },
    provenance={
        'source_path': 'example_workflows/Hunyuan-Foley.json (commit b94f7aca)',
        'source_id': 'audio/hunyuan_foley_v2a',
        'upstream_source_id': 'Hunyuan-Foley',
        'source_type': 'api',
        'output_mode': 'ready_template',
        'ready_id': 'audio/hunyuan_foley_v2a',
    },
)


def build():
    """Build the workflow (hand-written, manual)."""
    wf = new_workflow(READY_METADATA, source_path=__file__)

    load_video = node('LoadVideo', _id='1', file=DEFAULT_VIDEO)
    frames = node('GetVideoComponents', _id='2', video=load_video.out(0))

    model_loader = node(
        'HunyuanFoleyModelLoader',
        _id='3',
        model_path_name=MODEL_DIR,
        foley_checkpoint_name=FOLEY_CHECKPOINT,
    )
    dac_vae = node('LoadDACHunyuanVAE', _id='4', vae_name=DAC_VAE)

    sampler = node(
        'HunyuanFoleySampler',
        _id='5',
        foley_model=model_loader.out(0),
        video_frames=frames.out(0),
        fps=frames.out(2),
        prompt=DEFAULT_PROMPT,
        negative_prompt=DEFAULT_NEGATIVE_PROMPT,
        guidance_scale=DEFAULT_GUIDANCE,
        steps=DEFAULT_STEPS,
        seed=DEFAULT_SEED,
    )
    decode = node('DACHunyuanVAEDecode', _id='6', samples=sampler.out(0), vae=dac_vae.out(0), unload_models_after_use=False)

    combined = node(
        'CreateVideo',
        _id='7',
        images=frames.out(0),
        audio=decode.out(0),
        fps=frames.out(2),
    )
    save = node(
        'SaveVideo',
        _id='8',
        video=combined.out(0),
        filename_prefix='audio/hunyuan_foley_v2a',
        format='mp4',
        codec='h264',
    )

    return wf.finalize(
        PUBLIC_INPUT_METADATA,
        output_node=save,
        output_type='SaveVideo',
        name='video',
        artifact_kind='video',
        mime_type='video/mp4',
        expected_cardinality='one',
        filename_prefix='audio/hunyuan_foley_v2a',
    )
