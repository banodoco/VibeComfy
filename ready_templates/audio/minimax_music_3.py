# Adapted from Comfy-Org/ComfyUI@426f5eea52a7ece1dd599fff4cb6cd1f352ddd24
# blueprints/Text to Music (MiniMax Music 3).json, SHA256 2bc91e6e4895842b47b2f6deac1626109ae08d8ca2f2fe877c312f5ee9d143fb
"""MiniMax Music 3: official sampling path with tiled decode and MP3 output."""
from __future__ import annotations

from vibecomfy.templates import InputSpec, ModelAsset, ReadyMetadata, new_workflow, node
from vibecomfy.nodes.core import CLIPLoader, UNETLoader, VAELoader, ConditioningZeroOut, KSampler, VAEDecodeAudioTiled, SaveAudioMP3

REVISION = '9e364ccd290a401561091fb441ed19cd7de92550'
BASE = f'https://huggingface.co/Comfy-Org/MiniMax-Music-3/resolve/{REVISION}'
UNET_NAME = 'minimax_music3_dit_int8_convrot.safetensors'
CLIP_NAME = 'minimax_music3_text_encoder_pruned_int8_convrot.safetensors'
VAE_NAME = 'minimax_music3_dav.safetensors'
MODELS = {
    'diffusion_model': ModelAsset(url=f'{BASE}/diffusion_models/{UNET_NAME}', subdir='diffusion_models', hf_revision=REVISION, sha256='d6b959633e69899f99f3a92d6741c0fe79f26958a30811e50e372ef978b24d5f', size_bytes=2502161682),
    'text_encoder': ModelAsset(url=f'{BASE}/text_encoders/{CLIP_NAME}', subdir='text_encoders', hf_revision=REVISION, sha256='010b7416d2336a08c711bc22ee65849c9623069ddb7d89bec011a75699e52014', size_bytes=9196611886),
    'vae': ModelAsset(url=f'{BASE}/vae/{VAE_NAME}', subdir='vae', hf_revision=REVISION, sha256='2a32155b769be01445fcc2a8663b910fc9e1751e18dc1c3ec528064512d9ef0c', size_bytes=216696128),
}
PUBLIC_INPUT_METADATA = {
    'prompt': InputSpec(node='13', field='caption', default='', type='STRING', required=True, media_semantics='text'),
    'lyrics': InputSpec(node='13', field='lyrics', default='', type='STRING', media_semantics='text'),
    'duration': InputSpec(node='13', field='max_duration', default=60.0, type='FLOAT', range={'min': 0.04, 'max': 360.0, 'step': 0.04}),
    'seed': InputSpec(node='38', field='seed', default=123, type='INT'),
}
READY_METADATA = ReadyMetadata.build(
    capability='audio', inputs=PUBLIC_INPUT_METADATA, models=MODELS,
    provenance={'source_workflow': 'ready_templates/sources/official/audio/minimax_music_3.json',
                'source_commit': '426f5eea52a7ece1dd599fff4cb6cd1f352ddd24',
                'source_hash': '2bc91e6e4895842b47b2f6deac1626109ae08d8ca2f2fe877c312f5ee9d143fb',
                'adaptation': 'Tiled decode branch; INT8 diffusion weights; MP3 saver; official seed node feeds encoding and sampling.'})


def build():
    wf = new_workflow(READY_METADATA, source_path=__file__)
    model = UNETLoader(_id='6', unet_name=UNET_NAME, weight_dtype='default')
    clip = CLIPLoader(_id='3', clip_name=CLIP_NAME, type='minimax', device='default')
    vae = VAELoader(_id='7', vae_name=VAE_NAME)
    seed = node('SeedNode', _id='38', seed=123)
    encoded = node('MiniMaxMusic3TextEncode', _id='13', clip=clip, caption='', lyrics='', seed=seed, max_duration=60.0, cfg_scale=1.7, top_k=50)
    negative = ConditioningZeroOut(_id='10', conditioning=encoded.out(0))
    latent = node('EmptyMiniMaxMusic3LatentAudio', _id='15', seconds=encoded.out(1), batch_size=1)
    samples = KSampler(_id='9', model=model, positive=encoded.out(0), negative=negative, latent_image=latent, seed=seed, steps=30, cfg=1.7, sampler_name='euler', scheduler='simple', denoise=1.0)
    audio = VAEDecodeAudioTiled(_id='42', samples=samples, vae=vae, tile_size=1536, overlap=64)
    saved = SaveAudioMP3(_id='44', audio=audio, filename_prefix='audio/minimax_music_3', quality='V0')
    return wf.finalize(PUBLIC_INPUT_METADATA, output_node=saved, output_type='SaveAudioMP3', name='audio', artifact_kind='audio', mime_type='audio/mpeg', expected_cardinality='one', filename_prefix='audio/minimax_music_3')
