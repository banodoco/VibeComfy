# vibecomfy: generated
# For hand-editing, run: python -m vibecomfy.cli copy-to-recipe <id>
# vibecomfy: surface=canonical
"""Auto-generated ready_template — use python -m vibecomfy.cli copy-to-recipe <id> for hand-editing."""
from __future__ import annotations

from vibecomfy.templates import InputSpec, ModelAsset, OutputSpec, ReadyMetadata, new_workflow, ref
from vibecomfy.workflow import VibeWorkflow
from vibecomfy.nodes.core import ConditioningZeroOut, DualCLIPLoader, EmptyAceStep1_5LatentAudio, KSampler, ModelSamplingAuraFlow, PrimitiveFloat, PrimitiveInt, SaveAudioMP3, TextEncodeAceStepAudio1_5, UNETLoader, VAEDecodeAudio, VAELoader


CLIP_NAME = 'qwen_0.6b_ace15.safetensors'
CLIP_NAME_2 = 'qwen_4b_ace15.safetensors'
GUIDE_STRENGTH = 1
UNET_NAME = 'acestep_v1.5_turbo.safetensors'
VAE_NAME = 'ace_1.5_vae.safetensors'
DEFAULT_PROMPT = 'synthwave, techno, synthpop, futuristic, electro, with liquid drum & bass drive.\nRestless, confident, dreamy mood at 128 BPM.\nAnalog bass, pulsating arps, percussive synth stabs, gated drums.\nQuick build,  then explosive drum burst, then clean fade.\nBreathy, rhythmic female vocals, minimal emotion, metallic echo.'
DEFAULT_LYRICS = 'Verse\nNeon rain on my screen,\nDreams compile in silver sheen.\nNo weight, just motion,\nI’m plugged into emotion.\n\nChorus\nComfy Cloud — breathing light,\nCode and color, spark and wire.\nDrift through data, feel alive,\nIn your circuits, I arrive.'
DEFAULT_DURATION = 30.0
DEFAULT_SEED = 561594583201063


MODELS = {
    'text_encoder': ModelAsset(url='https://huggingface.co/Comfy-Org/ACE-Step-1.5/resolve/371bb1680f8c88d8c1083f6ffb6330d3d55bff76/split_files/text_encoders/qwen_0.6b_ace15.safetensors', sha256='fd4590c82153b8ddb67e15a2e7aaa8afa8b83a858c8a9b82a4831063156aa7a7', size_bytes=1191588248, subdir='text_encoders'),
    'text_encoder_2': ModelAsset(url='https://huggingface.co/Comfy-Org/ACE-Step-1.5/resolve/371bb1680f8c88d8c1083f6ffb6330d3d55bff76/split_files/text_encoders/qwen_4b_ace15.safetensors', sha256='ffe5ffb855086c2ab55e467e9859fb01894781020a0376484dd19de166b79873', size_bytes=8379154232, subdir='text_encoders'),
    'vae': ModelAsset(url='https://huggingface.co/Comfy-Org/ACE-Step-1.5/resolve/371bb1680f8c88d8c1083f6ffb6330d3d55bff76/split_files/vae/ace_1.5_vae.safetensors', sha256='6de92e3a862acd287e08b024ac90f0783a8635451b728721a33ff03565bcb2bb', size_bytes=337431732, subdir='vae'),
    'diffusion_model': ModelAsset(url='https://huggingface.co/Comfy-Org/ACE-Step-1.5/resolve/371bb1680f8c88d8c1083f6ffb6330d3d55bff76/split_files/diffusion_models/acestep_v1.5_turbo.safetensors', sha256='3f6e0797fad420a39bd33979eb6e840e30989e34a3794e843d23b60ec6e422d7', size_bytes=4787825604, subdir='diffusion_models'),
}


PUBLIC_INPUT_METADATA = {
    'prompt': InputSpec(node=ref('textencodeacestepaudio1_5'), field='tags', default=DEFAULT_PROMPT, type='STRING', infer_type=False),
    'lyrics': InputSpec(node=ref('textencodeacestepaudio1_5'), field='lyrics', default=DEFAULT_LYRICS, type='STRING', infer_type=False),
    'duration': InputSpec(node=ref('primitivefloat'), field='value', default=DEFAULT_DURATION, type='FLOAT', infer_type=False),
    'seed': InputSpec(node=ref('primitiveint'), field='value', default=DEFAULT_SEED, type='INT', infer_type=False),
}


READY_METADATA = ReadyMetadata.build(
    capability='audio',
    template_id='audio/ace_step_1_5_t2a_song',
    inputs=PUBLIC_INPUT_METADATA,
    models=MODELS,
    requirements={'custom_nodes': ['EmptyAceStep1', 'TextEncodeAceStepAudio1']},
    provenance={'operation': 'authored'},
    operation='authored',
    source_id='audio/ace_step_1_5_t2a_song',
    source_path='ready_templates/sources/official/audio/ace_step_1_5_t2a_song.json',
    upstream_source_id='ace_step_1_5_t2a_song',
    source_type='api',
    source_workflow_path='ready_templates/sources/official/audio/ace_step_1_5_t2a_song.json',
    output_mode='ready_template',
    ready_id='audio/ace_step_1_5_t2a_song',
    source_bundle={'format_version': 2, 'generation_id': '1d986c1500fb8eb04799a0b9227beee5056a90516bc8575b5a520877f8690eff', 'custody_digest': '52ad872436e34b9e09d0e43c33514ffb7acce7fcbb1850b0c26f2d9c79d51fb1'},
)

def build() -> VibeWorkflow:
    """Build the workflow (auto-generated)."""
    with new_workflow(READY_METADATA, source_path=__file__) as wf:

        # Loaders
        dualcliploader = DualCLIPLoader(
            _native_ports={'native_input_names': ['clip_name1', 'clip_name2', 'type', 'device'], 'native_output_names': ['CLIP'], 'native_input_types': ['CHOICE', 'CHOICE', 'CHOICE', 'CHOICE'], 'native_output_types': ['CLIP'], 'native_input_optional': [False, False, False, True], 'native_input_asset_kinds': None, 'native_output_slots': None},
            clip_name1=CLIP_NAME,
            clip_name2=CLIP_NAME_2,
            type='ace',
            device='default',
            _id='105',
            _uid='105',
        )

        vaeloader = VAELoader(
            _native_ports={'native_input_names': ['vae_name'], 'native_output_names': ['VAE'], 'native_input_types': ['CHOICE'], 'native_output_types': ['VAE'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            vae_name=VAE_NAME,
            _id='106',
            _uid='106',
        )

        # Inputs
        primitivefloat = PrimitiveFloat(
            _native_ports={'native_input_names': ['value'], 'native_output_names': ['FLOAT'], 'native_input_types': ['FLOAT'], 'native_output_types': ['FLOAT'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            value=DEFAULT_DURATION,
            _id='110',
            _uid='110',
        )

        unetloader = UNETLoader(
            _native_ports={'native_input_names': ['unet_name', 'weight_dtype'], 'native_output_names': ['MODEL'], 'native_input_types': ['CHOICE', 'CHOICE'], 'native_output_types': ['MODEL'], 'native_input_optional': [False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            unet_name=UNET_NAME,
            weight_dtype='default',
            _id='125',
            _uid='125',
        )

        primitiveint = PrimitiveInt(
            _native_ports={'native_input_names': ['value'], 'native_output_names': ['INT'], 'native_input_types': ['INT'], 'native_output_types': ['INT'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            value=DEFAULT_SEED,
            _id='126',
            _uid='126',
        )

        modelsamplingauraflow = ModelSamplingAuraFlow(
            _native_ports={'native_input_names': ['shift', 'model'], 'native_output_names': ['MODEL'], 'native_input_types': ['FLOAT', 'MODEL'], 'native_output_types': ['MODEL'], 'native_input_optional': [False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            shift=3,
            model=unetloader.out('MODEL'),
            _id='78',
            _uid='78',
        )

        emptyacestep1_5latentaudio = EmptyAceStep1_5LatentAudio(
            _native_ports={'native_input_names': ['seconds', 'batch_size'], 'native_output_names': ['LATENT'], 'native_input_types': ['FLOAT', 'INT'], 'native_output_types': ['LATENT'], 'native_input_optional': [False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            batch_size=1,
            seconds=primitivefloat.out('FLOAT'),
            _id='122',
            _uid='122',
        )

        textencodeacestepaudio1_5 = TextEncodeAceStepAudio1_5(
            _native_ports={'native_input_names': ['tags', 'lyrics', 'seed', 'bpm', 'duration', 'timesignature', 'language', 'keyscale', 'generate_audio_codes', 'cfg_scale', 'temperature', 'top_p', 'top_k', 'min_p', 'clip'], 'native_output_names': ['CONDITIONING'], 'native_input_types': ['STRING', 'STRING', 'INT', 'INT', 'FLOAT', 'COMBO', 'COMBO', 'COMBO', 'BOOLEAN', 'FLOAT', 'FLOAT', 'FLOAT', 'INT', 'FLOAT', 'CLIP'], 'native_output_types': ['CONDITIONING'], 'native_input_optional': [False, False, False, False, False, False, False, False, False, False, False, False, False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            tags=DEFAULT_PROMPT,
            lyrics=DEFAULT_LYRICS,
            bpm=120,
            timesignature='4',
            language='en',
            keyscale='E minor',
            generate_audio_codes=True,
            cfg_scale=1.5,
            temperature=0.85,
            top_p=0.9,
            top_k=0,
            min_p=0,
            seed=primitiveint.out('INT'),
            duration=primitivefloat.out('FLOAT'),
            clip=dualcliploader.out('CLIP'),
            _id='124',
            _uid='124',
        )

        conditioningzeroout = ConditioningZeroOut(
            _native_ports={'native_input_names': ['conditioning'], 'native_output_names': ['CONDITIONING'], 'native_input_types': ['CONDITIONING'], 'native_output_types': ['CONDITIONING'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            conditioning=textencodeacestepaudio1_5.out('CONDITIONING'),
            _id='47',
            _uid='47',
        )

        # Sampling
        ksampler = KSampler(
            _native_ports={'native_input_names': ['seed', 'steps', 'cfg', 'sampler_name', 'scheduler', 'denoise', 'latent_image', 'model', 'negative', 'positive'], 'native_output_names': ['LATENT'], 'native_input_types': ['INT', 'INT', 'FLOAT', 'CHOICE', 'CHOICE', 'FLOAT', 'LATENT', 'MODEL', 'CONDITIONING', 'CONDITIONING'], 'native_output_types': ['LATENT'], 'native_input_optional': [False, False, False, False, False, False, False, False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            steps=8,
            cfg=GUIDE_STRENGTH,
            sampler_name='euler',
            scheduler='simple',
            denoise=1,
            seed=primitiveint.out('INT'),
            latent_image=emptyacestep1_5latentaudio.out('LATENT'),
            model=modelsamplingauraflow.out('MODEL'),
            negative=conditioningzeroout.out('CONDITIONING'),
            positive=textencodeacestepaudio1_5.out('CONDITIONING'),
            _id='3',
            _uid='3',
        )

        vaedecodeaudio = VAEDecodeAudio(
            _native_ports={'native_input_names': ['samples', 'vae'], 'native_output_names': ['AUDIO'], 'native_input_types': ['LATENT', 'VAE'], 'native_output_types': ['AUDIO'], 'native_input_optional': [False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            samples=ksampler.out('LATENT'),
            vae=vaeloader.out('VAE'),
            _id='123',
            _uid='123',
        )

        # Outputs
        saveaudiomp3 = SaveAudioMP3(
            _native_ports={'native_input_names': ['filename_prefix', 'quality', 'extra_pnginfo', 'prompt', 'audio'], 'native_output_names': None, 'native_input_types': ['STRING', 'COMBO', 'EXTRA_PNGINFO', 'PROMPT', 'AUDIO'], 'native_output_types': None, 'native_input_optional': [False, False, True, True, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            filename_prefix='audio/ace_step_song',
            quality='V0',
            audio=vaedecodeaudio.out('AUDIO'),
            _id='59',
            _uid='59',
        )

        return wf.finalize(PUBLIC_INPUT_METADATA, outputs=[OutputSpec(node=saveaudiomp3, output_type='SaveAudioMP3', name='audio', artifact_kind='audio', mime_type='audio/mpeg', filename_prefix='audio/ace_step_song', expected_cardinality='one')])
