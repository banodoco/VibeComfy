# vibecomfy: generated
# For hand-editing, run: python -m vibecomfy.cli copy-to-recipe <id>
# vibecomfy: surface=canonical
"""Auto-generated ready_template — use python -m vibecomfy.cli copy-to-recipe <id> for hand-editing."""
from __future__ import annotations

from vibecomfy.templates import InputSpec, ModelAsset, OutputSpec, ReadyMetadata, new_workflow, node as raw_call, ref
from vibecomfy.workflow import VibeWorkflow
from vibecomfy.nodes.core import CLIPLoader, ConditioningZeroOut, KSampler, SaveAudioMP3, UNETLoader, VAEDecodeAudioTiled, VAELoader


CLIP_NAME = 'minimax_music3_text_encoder_pruned_int8_convrot.safetensors'
DEFAULT_SEED = 123
GUIDE_STRENGTH = 1.7
UNET_NAME = 'minimax_music3_dit_int8_convrot.safetensors'
VAE_NAME = 'minimax_music3_dav.safetensors'
DEFAULT_PROMPT = ''
DEFAULT_LYRICS = ''
DEFAULT_DURATION = 60.0


MODELS = {
    'diffusion_model': ModelAsset(url='https://huggingface.co/Comfy-Org/MiniMax-Music-3/resolve/9e364ccd290a401561091fb441ed19cd7de92550/diffusion_models/minimax_music3_dit_int8_convrot.safetensors', sha256='d6b959633e69899f99f3a92d6741c0fe79f26958a30811e50e372ef978b24d5f', hf_revision='9e364ccd290a401561091fb441ed19cd7de92550', size_bytes=2502161682, subdir='diffusion_models'),
    'text_encoder': ModelAsset(url='https://huggingface.co/Comfy-Org/MiniMax-Music-3/resolve/9e364ccd290a401561091fb441ed19cd7de92550/text_encoders/minimax_music3_text_encoder_pruned_int8_convrot.safetensors', sha256='010b7416d2336a08c711bc22ee65849c9623069ddb7d89bec011a75699e52014', hf_revision='9e364ccd290a401561091fb441ed19cd7de92550', size_bytes=9196611886, subdir='text_encoders'),
    'vae': ModelAsset(url='https://huggingface.co/Comfy-Org/MiniMax-Music-3/resolve/9e364ccd290a401561091fb441ed19cd7de92550/vae/minimax_music3_dav.safetensors', sha256='2a32155b769be01445fcc2a8663b910fc9e1751e18dc1c3ec528064512d9ef0c', hf_revision='9e364ccd290a401561091fb441ed19cd7de92550', size_bytes=216696128, subdir='vae'),
}


PUBLIC_INPUT_METADATA = {
    'model': InputSpec(node=ref('unetloader'), field='unet_name', default=None, infer_type=False),
    'seed': InputSpec(node=ref('seednode'), field='seed', default=DEFAULT_SEED, type='INT', infer_type=False),
    'steps': InputSpec(node=ref('ksampler'), field='steps', default=None, infer_type=False),
    'prompt': InputSpec(node=ref('minimaxmusic3textencode'), field='caption', default=DEFAULT_PROMPT, type='STRING', required=True, media_semantics='text', infer_type=False),
    'lyrics': InputSpec(node=ref('minimaxmusic3textencode'), field='lyrics', default=DEFAULT_LYRICS, type='STRING', media_semantics='text', infer_type=False),
    'duration': InputSpec(node=ref('minimaxmusic3textencode'), field='max_duration', default=DEFAULT_DURATION, type='FLOAT', range={'min': 0.04, 'max': 360.0, 'step': 0.04}, infer_type=False),
}


READY_METADATA = ReadyMetadata.build(
    capability='audio',
    template_id='audio/minimax_music_3',
    inputs=PUBLIC_INPUT_METADATA,
    models=MODELS,
    operation='authored',
    provenance={'operation': 'authored', 'source_workflow': 'ready_templates/sources/official/audio/minimax_music_3.json', 'source_id': 'audio/minimax_music_3', 'ready_id': 'audio/minimax_music_3'},
    source_commit='426f5eea52a7ece1dd599fff4cb6cd1f352ddd24',
    source_hash='2bc91e6e4895842b47b2f6deac1626109ae08d8ca2f2fe877c312f5ee9d143fb',
    adaptation='Tiled decode branch; INT8 diffusion weights; MP3 saver; official seed node feeds encoding and sampling.',
    source_bundle={'format_version': 2, 'generation_id': 'f1b850b0de0e995c97014b6a156f535a7d3cf982999ae72482e6e690d01439bf', 'custody_digest': '2c655a16ee93f8e0489a0f269817bbb42e32f8c82ac12b191f0318af275efbf3'},
    source_id='audio/minimax_music_3',
    ready_id='audio/minimax_music_3',
)

def build() -> VibeWorkflow:
    """Build the workflow (auto-generated)."""
    with new_workflow(READY_METADATA, source_path=__file__) as wf:

        # Loaders
        cliploader = CLIPLoader(
            _native_ports={'native_input_names': ['clip_name', 'type', 'device'], 'native_output_names': ['CLIP'], 'native_input_types': ['CHOICE', 'CHOICE', 'CHOICE'], 'native_output_types': ['CLIP'], 'native_input_optional': [False, False, True], 'native_input_asset_kinds': None, 'native_output_slots': None},
            clip_name=CLIP_NAME,
            type='minimax',
            device='default',
            _id='3',
            _uid='n2',
        )

        unetloader = UNETLoader(
            _native_ports={'native_input_names': ['unet_name', 'weight_dtype'], 'native_output_names': ['MODEL'], 'native_input_types': ['CHOICE', 'CHOICE'], 'native_output_types': ['MODEL'], 'native_input_optional': [False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            unet_name=UNET_NAME,
            weight_dtype='default',
            _id='6',
            _uid='n1',
        )

        vaeloader = VAELoader(
            _native_ports={'native_input_names': ['vae_name'], 'native_output_names': ['VAE'], 'native_input_types': ['CHOICE'], 'native_output_types': ['VAE'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            vae_name=VAE_NAME,
            _id='7',
            _uid='n3',
        )

        seednode = raw_call('SeedNode', '38',
            _outputs=('SEED',),
            _native_ports={'native_input_names': ['seed'], 'native_output_names': ['SEED'], 'native_input_types': ['INT'], 'native_output_types': ['INT'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            seed=DEFAULT_SEED,
            _uid='n4',
        )

        minimaxmusic3textencode = raw_call('MiniMaxMusic3TextEncode', '13',
            _outputs=('CONDITIONING', 'SECONDS'),
            _native_ports={'native_input_names': ['clip', 'caption', 'lyrics', 'seed', 'max_duration', 'cfg_scale', 'top_k'], 'native_output_names': ['CONDITIONING', 'SECONDS'], 'native_input_types': ['CLIP', 'STRING', 'STRING', 'INT', 'FLOAT', 'FLOAT', 'INT'], 'native_output_types': ['CONDITIONING', 'FLOAT'], 'native_input_optional': [False, False, False, False, False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            caption=DEFAULT_PROMPT,
            cfg_scale=1.7,
            lyrics=DEFAULT_LYRICS,
            max_duration=DEFAULT_DURATION,
            top_k=50,
            clip=cliploader.out('CLIP'),
            seed=seednode.out('SEED'),
            _uid='n5',
        )

        conditioningzeroout = ConditioningZeroOut(
            _native_ports={'native_input_names': ['conditioning'], 'native_output_names': ['CONDITIONING'], 'native_input_types': ['CONDITIONING'], 'native_output_types': ['CONDITIONING'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            conditioning=minimaxmusic3textencode.out('CONDITIONING'),
            _id='10',
            _uid='n6',
        )

        emptyminimaxmusic3latentaudio = raw_call('EmptyMiniMaxMusic3LatentAudio', '15',
            _outputs=('LATENT',),
            _native_ports={'native_input_names': ['seconds', 'batch_size'], 'native_output_names': ['LATENT'], 'native_input_types': ['FLOAT', 'INT'], 'native_output_types': ['LATENT'], 'native_input_optional': [False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            batch_size=1,
            seconds=minimaxmusic3textencode.out('SECONDS'),
            _uid='n7',
        )

        # Sampling
        ksampler = KSampler(
            _native_ports={'native_input_names': ['seed', 'steps', 'cfg', 'sampler_name', 'scheduler', 'denoise', 'latent_image', 'model', 'negative', 'positive'], 'native_output_names': ['LATENT'], 'native_input_types': ['INT', 'INT', 'FLOAT', 'CHOICE', 'CHOICE', 'FLOAT', 'LATENT', 'MODEL', 'CONDITIONING', 'CONDITIONING'], 'native_output_types': ['LATENT'], 'native_input_optional': [False, False, False, False, False, False, False, False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            steps=30,
            cfg=GUIDE_STRENGTH,
            sampler_name='euler',
            scheduler='simple',
            denoise=1.0,
            seed=seednode.out('SEED'),
            latent_image=emptyminimaxmusic3latentaudio.out('LATENT'),
            model=unetloader.out('MODEL'),
            negative=conditioningzeroout.out('CONDITIONING'),
            positive=minimaxmusic3textencode.out('CONDITIONING'),
            _id='9',
            _uid='n8',
        )

        vaedecodeaudiotiled = VAEDecodeAudioTiled(
            _native_ports={'native_input_names': ['tile_size', 'overlap', 'samples', 'vae'], 'native_output_names': ['AUDIO'], 'native_input_types': ['INT', 'INT', 'LATENT', 'VAE'], 'native_output_types': ['AUDIO'], 'native_input_optional': [False, False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            overlap=64,
            tile_size=1536,
            samples=ksampler.out('LATENT'),
            vae=vaeloader.out('VAE'),
            _id='42',
            _uid='n9',
        )

        # Outputs
        saveaudiomp3 = SaveAudioMP3(
            _native_ports={'native_input_names': ['filename_prefix', 'quality', 'extra_pnginfo', 'prompt', 'audio'], 'native_output_names': None, 'native_input_types': ['STRING', 'COMBO', 'EXTRA_PNGINFO', 'PROMPT', 'AUDIO'], 'native_output_types': None, 'native_input_optional': [False, False, True, True, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            filename_prefix='audio/minimax_music_3',
            quality='V0',
            audio=vaedecodeaudiotiled.out('AUDIO'),
            _id='44',
            _uid='n10',
        )

        return wf.finalize(PUBLIC_INPUT_METADATA, outputs=[OutputSpec(node=saveaudiomp3, output_type='SaveAudioMP3', name='audio', artifact_kind='audio', mime_type='audio/mpeg', filename_prefix='audio/minimax_music_3', expected_cardinality='one')])
