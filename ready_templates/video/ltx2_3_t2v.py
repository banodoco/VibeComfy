# vibecomfy: generated
# For hand-editing, run: python -m vibecomfy.cli copy-to-recipe <id>
# vibecomfy: surface=canonical
"""Auto-generated ready_template — use python -m vibecomfy.cli copy-to-recipe <id> for hand-editing."""
from __future__ import annotations

from vibecomfy.templates import InputSpec, ModelAsset, OutputSpec, ReadyMetadata, authored_channel, new_workflow, ref
from vibecomfy.workflow import VibeWorkflow
from vibecomfy.nodes.core import CFGGuider, CLIPTextEncode, CreateVideo, EmptyLTXVLatentVideo, KSamplerSelect, LTXAVTextEncoderLoader, LTXVAudioVAEDecode, LTXVAudioVAELoader, LTXVConcatAVLatent, LTXVConditioning, LTXVEmptyLatentAudio, LTXVScheduler, LTXVSeparateAVLatent, LoraLoaderModelOnly, ManualSigmas, RandomNoise, SamplerCustomAdvanced, SaveVideo
from vibecomfy.nodes.ltxvideo import GuiderParameters, LTXFloatToInt, LTXVTiledVAEDecode, LowVRAMCheckpointLoader, MultimodalGuider


CKPT_NAME = 'ltx-2.3-22b-dev-fp8.safetensors'
CKPT_NAME_2 = 'ltx-2.3-22b-dev.safetensors'
DEFAULT_FPS = 24.0
DEFAULT_FRAMES = 9
DEFAULT_PROMPT = 'A traditional Japanese tea ceremony takes place in a tatami room as a host carefully prepares matcha. Soft traditional koto music plays in the background, adding to the serene atmosphere. The bamboo whisk taps rhythmically against the ceramic bowl while water simmers in an iron kettle. Guests kneel in formal seiza position, watching in respectful silence. The host bows and presents the tea bowl, turning it precisely before offering it to the first guest with soft-spoken words.'
DEFAULT_PROMPT_2 = 'pc game, console game, video game, cartoon, childish, ugly'
DEFAULT_SEED = 42
DEFAULT_SEED_2 = 43
EULER_ANCESTRAL_CFG_PP = 'euler_ancestral_cfg_pp'
FIXED = 'fixed'
GUIDE_STRENGTH = 7
GUIDE_STRENGTH_2 = 3
GUIDE_STRENGTH_3 = 0.5
GUIDE_STRENGTH_4 = 0.2
GUIDE_STRENGTH_5 = 1
LORA_NAME = 'ltxv/ltx2/ltx-2.3-22b-distilled-lora-384-1.1.safetensors'
TEXT_ENCODER_NAME = 'comfy_gemma_3_12B_it.safetensors'


MODELS = {
    'checkpoint': ModelAsset(filename='ltx-2.3-22b-dev.safetensors', url='https://huggingface.co/Lightricks/LTX-2.3-fp8/resolve/91eda216f820e5ecb3d17dc9fe3b7cdaf56b587d/ltx-2.3-22b-dev-fp8.safetensors', sha256='28606c5b5a06ce56f896d4dfcb20f212739e07a68fbe48e53638188449d26450', hf_revision='91eda216f820e5ecb3d17dc9fe3b7cdaf56b587d', size_bytes=29145431166, subdir='checkpoints'),
    'lora': ModelAsset(filename='ltxv/ltx2/ltx-2.3-22b-distilled-lora-384-1.1.safetensors', url='https://huggingface.co/Lightricks/LTX-2.3/resolve/c1521179de480464f366a98a9d9b2acc4cc097b9/ltx-2.3-22b-distilled-lora-384-1.1.safetensors', sha256='f5d4953f3386197a4b4f5abdb17616ff256171e8075c111d6e7d2dfa6e823b3a', hf_revision='c1521179de480464f366a98a9d9b2acc4cc097b9', size_bytes=7605507256, subdir='loras'),
    'checkpoint_2': ModelAsset(url='https://huggingface.co/Lightricks/LTX-2.3-fp8/resolve/91eda216f820e5ecb3d17dc9fe3b7cdaf56b587d/ltx-2.3-22b-dev-fp8.safetensors', sha256='28606c5b5a06ce56f896d4dfcb20f212739e07a68fbe48e53638188449d26450', hf_revision='91eda216f820e5ecb3d17dc9fe3b7cdaf56b587d', size_bytes=29145431166, subdir='checkpoints'),
    'text_encoder': ModelAsset(filename='comfy_gemma_3_12B_it.safetensors', url='https://huggingface.co/Comfy-Org/ltx-2/resolve/ccde4ba417d7900669fd56dd292a883cee11ff37/split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors', sha256='aaca463d11e6d8d2a4bdb0d6299214c15ef78a3f73e0ef8113d5a9d0219b3f6d', hf_revision='ccde4ba417d7900669fd56dd292a883cee11ff37', size_bytes=9447702218, subdir='text_encoders'),
}


PUBLIC_INPUT_METADATA = {
    'model': InputSpec(node=ref('lowvramcheckpointloader'), field='ckpt_name', default=None, infer_type=False),
    'seed': InputSpec(node=ref('randomnoise'), field='noise_seed', default=DEFAULT_SEED, type='INT', infer_type=False),
    'prompt': InputSpec(node=ref('cliptextencode'), field='text', default=DEFAULT_PROMPT, type='STRING', required=True, media_semantics='text', infer_type=False),
    'width': InputSpec(node=ref('emptyltxvlatentvideo'), field='width', default=960, type='INT', infer_type=False),
    'height': InputSpec(node=ref('emptyltxvlatentvideo'), field='height', default=544, type='INT', infer_type=False),
    'frames': InputSpec(node=ref('emptyltxvlatentvideo'), field='length', default=121, type='INT', infer_type=False),
    'fps': InputSpec(node=ref('createvideo_2'), field='fps', default=DEFAULT_FPS, type='FLOAT', infer_type=False),
    'negative_prompt': InputSpec(node=ref('cliptextencode_2'), field='text', default=DEFAULT_PROMPT_2, type='STRING', aliases=('negative',), media_semantics='text', infer_type=False),
}


READY_METADATA = ReadyMetadata.build(
    capability='video',
    template_id='video/ltx2_3_t2v',
    inputs=PUBLIC_INPUT_METADATA,
    models=MODELS,
    custom_node_packs={'ComfyUI-LTXVideo': {'commit': '229437c6b65796d6a7a63ae34be2bd5ba31fa543', 'url': 'https://github.com/Lightricks/ComfyUI-LTXVideo.git', 'class_schema_sha256': '82e0b1f31509a969cf441c45e2517d0cd93f31b5390cc16f4a0ffa244421f39e', 'classes_used': ['EmptyLTXVLatentVideo', 'LTXAVTextEncoderLoader', 'LTXVAudioVAEDecode', 'LTXVAudioVAELoader', 'LTXVConcatAVLatent', 'LTXVConditioning', 'LTXVEmptyLatentAudio', 'LTXVPreprocess', 'LTXVScheduler', 'LTXVSeparateAVLatent'], 'pip_packages': [], 'status': 'discovered'}},
    source_path='ready_templates/sources/custom_nodes/ltxvideo/ltx2_3_single_stage_distilled_full.json',
    source_id='video/ltx2_3_t2v',
    upstream_source_id='ltx2_3_single_stage_distilled_full',
    source_type='api',
    source_workflow_path='ready_templates/sources/custom_nodes/ltxvideo/ltx2_3_single_stage_distilled_full.json',
    output_mode='ready_template',
    ready_id='video/ltx2_3_t2v',
    provenance={'source_path': 'ready_templates/sources/custom_nodes/ltxvideo/ltx2_3_single_stage_distilled_full.json', 'source_id': 'video/ltx2_3_t2v', 'upstream_source_id': 'ltx2_3_single_stage_distilled_full', 'source_type': 'api', 'source_workflow_path': 'ready_templates/sources/custom_nodes/ltxvideo/ltx2_3_single_stage_distilled_full.json', 'output_mode': 'ready_template', 'ready_id': 'video/ltx2_3_t2v', 'source_workflow': 'ready_templates/sources/custom_nodes/ltxvideo/ltx2_3_single_stage_distilled_full.json'},
    smoke_resolution='384x256x9_frames',
    comfy_configuration={'reserve_vram': 12, 'cache_none': True, 'fp8_e4m3fn_text_enc': True},
    external_python_marker='external_python:video/ltx2_3_t2v',
    entrypoint='patch',
    layer='vibecomfy/patches/resolution.py:resolution:384x256x9',
    patch_applications=[{'name': 'resolution:384x256x9', 'layer': 'patch', 'called': True, 'topology_changed': False, 'nodes_added': [], 'introduced_edges': [], 'rewritten_edges': [], 'value_changed': True}],
    source_bundle={'format_version': 2, 'generation_id': '565b422dd73bd11a119f995535d78b660d95a46244e8f4d7bf8ccb0b61e87da0', 'custody_digest': '6b0014bd72b1b09faf55e43c16ad36663c1dc9af27516e62cb13ebe2f1171ed6'},
)

def build() -> VibeWorkflow:
    """Build the workflow (auto-generated)."""
    with new_workflow(READY_METADATA, source_path=__file__) as wf:

        # Sampling
        emptyltxvlatentvideo = EmptyLTXVLatentVideo(
            _native_ports={'native_input_names': ['width', 'height', 'length', 'batch_size'], 'native_output_names': ['LATENT'], 'native_input_types': ['INT', 'INT', 'INT', 'INT'], 'native_output_types': ['LATENT'], 'native_input_optional': [False, False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            width=authored_channel(384, widget=384, name='widget_0'),
            height=authored_channel(256, widget=256, name='widget_1'),
            length=authored_channel(DEFAULT_FRAMES, widget=9, name='widget_2'),
            batch_size=1,
            _id='3059',
            _uid='n2',
        )

        ltxvaudiovaeloader = LTXVAudioVAELoader(
            _native_ports={'native_input_names': ['ckpt_name'], 'native_output_names': ['AUDIO_VAE'], 'native_input_types': ['COMBO'], 'native_output_types': ['VAE'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            ckpt_name=CKPT_NAME,
            _id='4010',
            _uid='n4',
        )

        randomnoise = RandomNoise(
            _native_ports={'native_input_names': ['noise_seed', 'control_after_generate'], 'native_output_names': ['NOISE'], 'native_input_types': ['INT', None], 'native_output_types': ['NOISE'], 'native_input_optional': None, 'native_input_asset_kinds': None, 'native_output_slots': None},
            noise_seed=DEFAULT_SEED,
            control_after_generate=FIXED,
            _id='4814',
            _uid='n5',
        )

        ksamplerselect_2 = KSamplerSelect(
            _native_ports={'native_input_names': ['sampler_name'], 'native_output_names': ['SAMPLER'], 'native_input_types': ['COMBO'], 'native_output_types': ['SAMPLER'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            sampler_name=EULER_ANCESTRAL_CFG_PP,
            _id='4831',
            _uid='n6',
        )

        randomnoise_2 = RandomNoise(
            _native_ports={'native_input_names': ['noise_seed', 'control_after_generate'], 'native_output_names': ['NOISE'], 'native_input_types': ['INT', None], 'native_output_types': ['NOISE'], 'native_input_optional': None, 'native_input_asset_kinds': None, 'native_output_slots': None},
            noise_seed=DEFAULT_SEED_2,
            control_after_generate=FIXED,
            _id='4832',
            _uid='n7',
        )

        ltxavtextencoderloader = LTXAVTextEncoderLoader(
            _native_ports={'native_input_names': ['text_encoder', 'ckpt_name', 'device'], 'native_output_names': ['CLIP'], 'native_input_types': ['COMBO', 'COMBO', 'COMBO'], 'native_output_types': ['CLIP'], 'native_input_optional': [False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            text_encoder=TEXT_ENCODER_NAME,
            ckpt_name=CKPT_NAME_2,
            device='default',
            _id='4960',
            _uid='n8',
        )

        guiderparameters_2 = GuiderParameters(
            _native_ports={'native_input_names': ['modality', 'cfg', 'stg', 'perturb_attn', 'rescale', 'modality_scale', 'skip_step', 'cross_attn', 'parameters'], 'native_output_names': ['GUIDER_PARAMETERS'], 'native_input_types': ['CHOICE', 'FLOAT', 'FLOAT', 'BOOLEAN', 'FLOAT', 'FLOAT', 'INT', 'BOOLEAN', 'GUIDER_PARAMETERS'], 'native_output_types': ['GUIDER_PARAMETERS'], 'native_input_optional': [False, False, False, False, False, False, False, False, True], 'native_input_asset_kinds': None, 'native_output_slots': None},
            cfg=GUIDE_STRENGTH,
            cross_attn=True,
            modality='AUDIO',
            modality_scale=3,
            perturb_attn=True,
            rescale=0.7,
            skip_step=0,
            stg=1.0,
            _id='4963',
            _uid='n9',
        )

        ksamplerselect = KSamplerSelect(
            _native_ports={'native_input_names': ['widget_0', 'widget_1', 'widget_2', 'widget_3', 'widget_4'], 'native_output_names': None, 'native_input_types': [None, None, None, None, None], 'native_output_types': None, 'native_input_optional': None, 'native_input_asset_kinds': None, 'native_output_slots': [0]},
            sampler_name=EULER_ANCESTRAL_CFG_PP,
            _id='4967',
            _uid='n10',
        )

        manualsigmas = ManualSigmas(
            _native_ports={'native_input_names': ['sigmas'], 'native_output_names': ['SIGMAS'], 'native_input_types': ['STRING'], 'native_output_types': ['SIGMAS'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            sigmas='1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0',
            _id='4971',
            _uid='n11',
        )

        ltxfloattoint = LTXFloatToInt(
            _native_ports={'native_input_names': ['a', 'rounding'], 'native_output_names': ['INT'], 'native_input_types': ['FLOAT', None], 'native_output_types': ['INT'], 'native_input_optional': None, 'native_input_asset_kinds': None, 'native_output_slots': None},
            rounding=0,
            a=24.0,
            _id='4985',
            _uid='n12',
        )

        # Conditioning
        cliptextencode = CLIPTextEncode(
            _native_ports={'native_input_names': ['text', 'clip'], 'native_output_names': ['CONDITIONING'], 'native_input_types': ['STRING', 'CLIP'], 'native_output_types': ['CONDITIONING'], 'native_input_optional': [False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            text=DEFAULT_PROMPT,
            clip=ltxavtextencoderloader.out('CLIP'),
            _id='2483',
            _uid='n13',
        )

        cliptextencode_2 = CLIPTextEncode(
            _native_ports={'native_input_names': ['text', 'clip'], 'native_output_names': ['CONDITIONING'], 'native_input_types': ['STRING', 'CLIP'], 'native_output_types': ['CONDITIONING'], 'native_input_optional': [False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            text=DEFAULT_PROMPT_2,
            clip=ltxavtextencoderloader.out('CLIP'),
            _id='2612',
            _uid='n14',
        )

        lowvramcheckpointloader = LowVRAMCheckpointLoader(
            _native_ports={'native_input_names': ['ckpt_name', 'dependencies'], 'native_output_names': ['MODEL', 'CLIP', 'VAE'], 'native_input_types': ['CHOICE', None], 'native_output_types': ['MODEL', 'CLIP', 'VAE'], 'native_input_optional': None, 'native_input_asset_kinds': None, 'native_output_slots': None},
            ckpt_name=CKPT_NAME,
            dependencies=ltxavtextencoderloader.out('CLIP'),
            _id='3940',
            _uid='n3',
        )

        ltxvemptylatentaudio = LTXVEmptyLatentAudio(
            _native_ports={'native_input_names': ['frames_number', 'frame_rate', 'batch_size', 'audio_vae'], 'native_output_names': ['LATENT'], 'native_input_types': ['INT', 'INT', 'INT', 'VAE'], 'native_output_types': ['LATENT'], 'native_input_optional': [False, False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            frames_number=authored_channel(9, widget=9, name='widget_0'),
            batch_size=1,
            frame_rate=authored_channel(ltxfloattoint.out('INT'), widget=8, name='widget_1', retain_input_default=True),
            audio_vae=ltxvaudiovaeloader.out('AUDIO_VAE'),
            _id='3980',
            _uid='n15',
        )

        guiderparameters = GuiderParameters(
            _native_ports={'native_input_names': ['modality', 'cfg', 'stg', 'perturb_attn', 'rescale', 'modality_scale', 'skip_step', 'cross_attn', 'parameters'], 'native_output_names': ['GUIDER_PARAMETERS'], 'native_input_types': ['CHOICE', 'FLOAT', 'FLOAT', 'BOOLEAN', 'FLOAT', 'FLOAT', 'INT', 'BOOLEAN', 'GUIDER_PARAMETERS'], 'native_output_types': ['GUIDER_PARAMETERS'], 'native_input_optional': [False, False, False, False, False, False, False, False, True], 'native_input_asset_kinds': None, 'native_output_slots': None},
            cfg=GUIDE_STRENGTH_2,
            cross_attn=True,
            modality='VIDEO',
            modality_scale=3,
            perturb_attn=True,
            rescale=0.9,
            skip_step=0,
            stg=1.0,
            parameters=guiderparameters_2.out('GUIDER_PARAMETERS'),
            _id='4964',
            _uid='n17',
        )

        ltxvconditioning = LTXVConditioning(
            _native_ports={'native_input_names': ['frame_rate', 'negative', 'positive'], 'native_output_names': ['POSITIVE', 'NEGATIVE'], 'native_input_types': ['FLOAT', 'CONDITIONING', 'CONDITIONING'], 'native_output_types': ['CONDITIONING', 'CONDITIONING'], 'native_input_optional': [False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            frame_rate=authored_channel(24.0, widget=8, name='widget_0'),
            negative=cliptextencode_2.out('CONDITIONING'),
            positive=cliptextencode.out('CONDITIONING'),
            _id='1241',
            _uid='n20',
        )

        ltxvconcatavlatent = LTXVConcatAVLatent(
            _native_ports={'native_input_names': ['audio_latent', 'video_latent'], 'native_output_names': ['LATENT'], 'native_input_types': ['LATENT', 'LATENT'], 'native_output_types': ['LATENT'], 'native_input_optional': [False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            audio_latent=ltxvemptylatentaudio.out('LATENT'),
            video_latent=emptyltxvlatentvideo.out('LATENT'),
            _id='4528',
            _uid='n25',
        )

        loraloadermodelonly = LoraLoaderModelOnly(
            _native_ports={'native_input_names': ['lora_name', 'strength_model', 'model'], 'native_output_names': ['MODEL'], 'native_input_types': ['CHOICE', 'FLOAT', 'MODEL'], 'native_output_types': ['MODEL'], 'native_input_optional': [False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            lora_name=LORA_NAME,
            strength_model=GUIDE_STRENGTH_3,
            model=lowvramcheckpointloader.out('MODEL'),
            _id='4922',
            _uid='n16',
        )

        loraloadermodelonly_2 = LoraLoaderModelOnly(
            _native_ports={'native_input_names': ['lora_name', 'strength_model', 'model'], 'native_output_names': ['MODEL'], 'native_input_types': ['CHOICE', 'FLOAT', 'MODEL'], 'native_output_types': ['MODEL'], 'native_input_optional': [False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            lora_name=LORA_NAME,
            strength_model=GUIDE_STRENGTH_4,
            model=lowvramcheckpointloader.out('MODEL'),
            _id='4968',
            _uid='n18',
        )

        multimodalguider = MultimodalGuider(
            _native_ports={'native_input_names': ['parameters', 'skip_blocks', 'model', 'negative', 'positive', 'widget_0'], 'native_output_names': ['GUIDER'], 'native_input_types': ['GUIDER_PARAMETERS', 'STRING', 'MODEL', 'CONDITIONING', 'CONDITIONING', None], 'native_output_types': ['GUIDER'], 'native_input_optional': None, 'native_input_asset_kinds': None, 'native_output_slots': None},
            skip_blocks='28',
            model=loraloadermodelonly_2.out('MODEL'),
            negative=ltxvconditioning.out('NEGATIVE'),
            parameters=guiderparameters.out('GUIDER_PARAMETERS'),
            positive=ltxvconditioning.out('POSITIVE'),
            _id='4808',
            _uid='n23',
        )

        cfgguider = CFGGuider(
            _native_ports={'native_input_names': ['cfg', 'model', 'negative', 'positive'], 'native_output_names': ['GUIDER'], 'native_input_types': ['FLOAT', 'MODEL', 'CONDITIONING', 'CONDITIONING'], 'native_output_types': ['GUIDER'], 'native_input_optional': [False, False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            cfg=GUIDE_STRENGTH_5,
            model=loraloadermodelonly.out('MODEL'),
            negative=ltxvconditioning.out('NEGATIVE'),
            positive=ltxvconditioning.out('POSITIVE'),
            _id='4828',
            _uid='n24',
        )

        ltxvscheduler = LTXVScheduler(
            _native_ports={'native_input_names': ['steps', 'max_shift', 'base_shift', 'stretch', 'terminal', 'latent'], 'native_output_names': ['SIGMAS'], 'native_input_types': ['INT', 'FLOAT', 'FLOAT', 'BOOLEAN', 'FLOAT', 'LATENT'], 'native_output_types': ['SIGMAS'], 'native_input_optional': [False, False, False, False, False, True], 'native_input_asset_kinds': None, 'native_output_slots': None},
            steps=15,
            max_shift=2.05,
            base_shift=0.95,
            stretch=True,
            terminal=0.1,
            latent=ltxvconcatavlatent.out('LATENT'),
            _id='4966',
            _uid='n27',
        )

        samplercustomadvanced_2 = SamplerCustomAdvanced(
            _native_ports={'native_input_names': ['noise', 'guider', 'sampler', 'sigmas', 'latent_image'], 'native_output_names': ['OUTPUT', 'DENOISED_OUTPUT'], 'native_input_types': ['NOISE', 'GUIDER', 'SAMPLER', 'SIGMAS', 'LATENT'], 'native_output_types': ['LATENT', 'LATENT'], 'native_input_optional': [False, False, False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            guider=multimodalguider.out('GUIDER'),
            latent_image=ltxvconcatavlatent.out('LATENT'),
            noise=randomnoise.out('NOISE'),
            sampler=ksamplerselect.out(0),
            sigmas=ltxvscheduler.out('SIGMAS'),
            _id='4802',
            _uid='n28',
        )

        samplercustomadvanced = SamplerCustomAdvanced(
            _native_ports={'native_input_names': ['noise', 'guider', 'sampler', 'sigmas', 'latent_image'], 'native_output_names': ['OUTPUT', 'DENOISED_OUTPUT'], 'native_input_types': ['NOISE', 'GUIDER', 'SAMPLER', 'SIGMAS', 'LATENT'], 'native_output_types': ['LATENT', 'LATENT'], 'native_input_optional': [False, False, False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            guider=cfgguider.out('GUIDER'),
            latent_image=ltxvconcatavlatent.out('LATENT'),
            noise=randomnoise_2.out('NOISE'),
            sampler=ksamplerselect_2.out('SAMPLER'),
            sigmas=manualsigmas.out('SIGMAS'),
            _id='4829',
            _uid='n26',
        )

        ltxvseparateavlatent_2 = LTXVSeparateAVLatent(
            _native_ports={'native_input_names': ['av_latent'], 'native_output_names': ['VIDEO_LATENT', 'AUDIO_LATENT'], 'native_input_types': ['LATENT'], 'native_output_types': ['LATENT', 'LATENT'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            av_latent=samplercustomadvanced_2.out('OUTPUT'),
            _id='4824',
            _uid='n30',
        )

        ltxvseparateavlatent = LTXVSeparateAVLatent(
            _native_ports={'native_input_names': ['av_latent'], 'native_output_names': ['VIDEO_LATENT', 'AUDIO_LATENT'], 'native_input_types': ['LATENT'], 'native_output_types': ['LATENT', 'LATENT'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            av_latent=samplercustomadvanced.out('OUTPUT'),
            _id='4845',
            _uid='n29',
        )

        ltxvaudiovaedecode_2 = LTXVAudioVAEDecode(
            _native_ports={'native_input_names': ['audio_vae', 'samples'], 'native_output_names': ['AUDIO'], 'native_input_types': ['VAE', 'LATENT'], 'native_output_types': ['AUDIO'], 'native_input_optional': [False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            audio_vae=ltxvaudiovaeloader.out('AUDIO_VAE'),
            samples=ltxvseparateavlatent_2.out('AUDIO_LATENT'),
            _id='4818',
            _uid='n33',
        )

        ltxvaudiovaedecode = LTXVAudioVAEDecode(
            _native_ports={'native_input_names': ['audio_vae', 'samples'], 'native_output_names': ['AUDIO'], 'native_input_types': ['VAE', 'LATENT'], 'native_output_types': ['AUDIO'], 'native_input_optional': [False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            audio_vae=ltxvaudiovaeloader.out('AUDIO_VAE'),
            samples=ltxvseparateavlatent.out('AUDIO_LATENT'),
            _id='4848',
            _uid='n31',
        )

        ltxvtiledvaedecode = LTXVTiledVAEDecode(
            _native_ports={'native_input_names': ['horizontal_tiles', 'vertical_tiles', 'overlap', 'last_frame_fix', 'working_device', 'working_dtype', 'latents', 'vae'], 'native_output_names': ['IMAGE'], 'native_input_types': ['INT', 'INT', 'INT', 'BOOLEAN', 'CHOICE', 'CHOICE', 'LATENT', 'VAE'], 'native_output_types': ['IMAGE'], 'native_input_optional': [False, False, False, False, True, True, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            horizontal_tiles=2,
            vertical_tiles=2,
            overlap=6,
            last_frame_fix=False,
            latents=ltxvseparateavlatent.out('VIDEO_LATENT'),
            vae=lowvramcheckpointloader.out('VAE'),
            _id='4982',
            _uid='n32',
        )

        ltxvtiledvaedecode_2 = LTXVTiledVAEDecode(
            _native_ports={'native_input_names': ['horizontal_tiles', 'vertical_tiles', 'overlap', 'last_frame_fix', 'working_device', 'working_dtype', 'latents', 'vae'], 'native_output_names': ['IMAGE'], 'native_input_types': ['INT', 'INT', 'INT', 'BOOLEAN', 'CHOICE', 'CHOICE', 'LATENT', 'VAE'], 'native_output_types': ['IMAGE'], 'native_input_optional': [False, False, False, False, True, True, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            horizontal_tiles=2,
            vertical_tiles=2,
            overlap=6,
            last_frame_fix=False,
            latents=ltxvseparateavlatent_2.out('VIDEO_LATENT'),
            vae=lowvramcheckpointloader.out('VAE'),
            _id='4983',
            _uid='n35',
        )

        createvideo_2 = CreateVideo(
            _native_ports={'native_input_names': ['fps', 'audio', 'images'], 'native_output_names': ['VIDEO'], 'native_input_types': ['FLOAT', 'AUDIO', 'IMAGE'], 'native_output_types': ['VIDEO'], 'native_input_optional': [False, True, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            fps=DEFAULT_FPS,
            images=ltxvtiledvaedecode_2.out('IMAGE'),
            _id='4819',
            _uid='n36',
        )

        createvideo = CreateVideo(
            _native_ports={'native_input_names': ['fps', 'audio', 'images'], 'native_output_names': ['VIDEO'], 'native_input_types': ['FLOAT', 'AUDIO', 'IMAGE'], 'native_output_types': ['VIDEO'], 'native_input_optional': [False, True, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            fps=DEFAULT_FPS,
            images=ltxvtiledvaedecode.out('IMAGE'),
            _id='4849',
            _uid='n34',
        )

        # Outputs
        savevideo_2 = SaveVideo(
            _native_ports={'native_input_names': ['filename_prefix', 'format', 'codec', 'extra_pnginfo', 'prompt', 'video'], 'native_output_names': None, 'native_input_types': ['STRING', 'COMBO', 'COMBO', 'EXTRA_PNGINFO', 'PROMPT', 'VIDEO'], 'native_output_types': None, 'native_input_optional': [False, False, False, True, True, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            filename_prefix='output_F',
            format='auto',
            codec='auto',
            video=createvideo_2.out('VIDEO'),
            _id='4823',
            _uid='n38',
        )

        savevideo = SaveVideo(
            _native_ports={'native_input_names': ['filename_prefix', 'format', 'codec', 'extra_pnginfo', 'prompt', 'video'], 'native_output_names': None, 'native_input_types': ['STRING', 'COMBO', 'COMBO', 'EXTRA_PNGINFO', 'PROMPT', 'VIDEO'], 'native_output_types': None, 'native_input_optional': [False, False, False, True, True, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            filename_prefix='output_D',
            format='auto',
            codec='auto',
            video=createvideo.out('VIDEO'),
            _id='4852',
            _uid='n37',
        )

        return wf.finalize(PUBLIC_INPUT_METADATA, outputs=[OutputSpec(node=savevideo_2, output_type='SaveVideo', name='video', artifact_kind='video', mime_type='video/mp4', filename_prefix='output_F', expected_cardinality='one')])
