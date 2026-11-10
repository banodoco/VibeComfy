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
    requirements={
        'models': [
            'hunyuan_foley/hunyuanvideo_foley_xl.pth',
            'hunyuan_foley/synchformer_state_dict.pth',
            'hunyuan_foley/vae_128d_48k.pth',
            'hunyuan_foley/siglip2/model.safetensors',
            'hunyuan_foley/clap/model.safetensors',
        ],
    },
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
