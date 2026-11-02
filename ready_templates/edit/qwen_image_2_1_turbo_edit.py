# vibecomfy: generated
# For hand-editing, run: python -m vibecomfy.cli copy-to-recipe <id>
# vibecomfy: surface=canonical
"""Auto-generated ready_template — use python -m vibecomfy.cli copy-to-recipe <id> for hand-editing."""
from __future__ import annotations

from vibecomfy.templates import InputSpec, ModelAsset, OutputSpec, ReadyMetadata, new_workflow, node as raw_call, ref
from vibecomfy.workflow import VibeWorkflow
from vibecomfy.nodes.core import CFGGuider, CLIPLoader, KSamplerSelect, LoadImage, ManualSigmas, RandomNoise, SamplerCustomAdvanced, SaveImage, UNETLoader, VAEDecode, VAELoader


CLIP_NAME = 'qwen3vl_8b_int8_convrot.safetensors'
DEFAULT_SEED = 0
GUIDE_STRENGTH = 1.0
UNET_NAME = 'qwen_image_2.1_turbo_int8_convrot.safetensors'
VAE_NAME = 'qwen_image_2.1_vae_bf16.safetensors'
DEFAULT_PROMPT = ''
DEFAULT_NEGATIVE_PROMPT = ''


MODELS = {
    'diffusion_model': ModelAsset(url='https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/aacf31a6d48e707f352ecba714cee0680da3479b/diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors', sha256='8144a0182964aa8403ad6dbc011db837304167d235161b9aabaa8532e967314c', hf_revision='aacf31a6d48e707f352ecba714cee0680da3479b', size_bytes=7256787829, subdir='diffusion_models'),
    'text_encoder': ModelAsset(url='https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/aacf31a6d48e707f352ecba714cee0680da3479b/text_encoders/qwen3vl_8b_int8_convrot.safetensors', sha256='8bfd0f6e12abf2d2d697ecc888e5e90b0d6741d6708f05799f53afa560452e8f', hf_revision='aacf31a6d48e707f352ecba714cee0680da3479b', size_bytes=9350798360, subdir='text_encoders'),
    'vae': ModelAsset(url='https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/aacf31a6d48e707f352ecba714cee0680da3479b/vae/qwen_image_2.1_vae_bf16.safetensors', sha256='bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9', hf_revision='aacf31a6d48e707f352ecba714cee0680da3479b', size_bytes=675509688, subdir='vae'),
}


PUBLIC_INPUT_METADATA = {
    'seed': InputSpec(node=ref('randomnoise'), field='noise_seed', default=DEFAULT_SEED, type='INT', infer_type=False),
    'diffusion_model': InputSpec(node=ref('unetloader'), field='unet_name', default=UNET_NAME, type='CHOICE', infer_type=False),
    'text_encoder': InputSpec(node=ref('cliploader'), field='clip_name', default=CLIP_NAME, type='CHOICE', infer_type=False),
    'vae': InputSpec(node=ref('vaeloader'), field='vae_name', default=VAE_NAME, type='CHOICE', infer_type=False),
    'prompt': InputSpec(node=ref('textencodeqwenimage21'), field='prompt', default=DEFAULT_PROMPT, type='STRING', required=True, media_semantics='text', infer_type=False),
    'negative_prompt': InputSpec(node=ref('textencodeqwenimage21'), field='negative_prompt', default=DEFAULT_NEGATIVE_PROMPT, type='STRING', media_semantics='text', infer_type=False),
    'image': InputSpec(node=ref('loadimage'), field='image', default='', type='IMAGE', required=True, media_semantics='image', infer_type=False),
}


READY_METADATA = ReadyMetadata.build(
    capability='image',
    template_id='edit/qwen_image_2_1_turbo_edit',
    inputs=PUBLIC_INPUT_METADATA,
    models=MODELS,
    operation='authored',
    provenance={'operation': 'authored', 'source_workflow': 'ready_templates/sources/official/edit/qwen_image_2_1_turbo_edit.json', 'source_id': 'edit/qwen_image_2_1_turbo_edit', 'ready_id': 'edit/qwen_image_2_1_turbo_edit'},
    source_hash='5a9622d550866800414afcb9c70523ec5c6965eb171476e401e243a7fe8d5a4e',
    source_bundle={'format_version': 2, 'generation_id': '56caccc2172df2274d6e447cdfa9f9042efa35c62b00f7a8f827eb9958a6757b', 'custody_digest': '69a50003af7f069ee7a9707c7f79d1a556a0bd0042e586a90f43c4f78e5981a2'},
    source_id='edit/qwen_image_2_1_turbo_edit',
    ready_id='edit/qwen_image_2_1_turbo_edit',
)

def build() -> VibeWorkflow:
    """Build the workflow (auto-generated)."""
    with new_workflow(READY_METADATA, source_path=__file__) as wf:

        # Loaders
        unetloader = UNETLoader(
            _native_ports={'native_input_names': ['unet_name', 'weight_dtype'], 'native_output_names': ['MODEL'], 'native_input_types': ['CHOICE', 'CHOICE'], 'native_output_types': ['MODEL'], 'native_input_optional': [False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            unet_name=UNET_NAME,
            weight_dtype='default',
            _id='1',
            _uid='n1',
        )

        cliploader = CLIPLoader(
            _native_ports={'native_input_names': ['clip_name', 'type', 'device'], 'native_output_names': ['CLIP'], 'native_input_types': ['CHOICE', 'CHOICE', 'CHOICE'], 'native_output_types': ['CLIP'], 'native_input_optional': [False, False, True], 'native_input_asset_kinds': None, 'native_output_slots': None},
            clip_name=CLIP_NAME,
            type='qwen_image',
            _id='2',
            _uid='n2',
        )

        vaeloader = VAELoader(
            _native_ports={'native_input_names': ['vae_name'], 'native_output_names': ['VAE'], 'native_input_types': ['CHOICE'], 'native_output_types': ['VAE'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            vae_name=VAE_NAME,
            _id='3',
            _uid='n3',
        )

        # Inputs
        loadimage = LoadImage(
            _native_ports={'native_input_names': ['image'], 'native_output_names': ['IMAGE', 'MASK'], 'native_input_types': ['CHOICE'], 'native_output_types': ['IMAGE', 'MASK'], 'native_input_optional': [False], 'native_input_asset_kinds': ['image'], 'native_output_slots': None},
            image='input.png',
            _id='4',
            _uid='n4',
        )

        manualsigmas = ManualSigmas(
            _native_ports={'native_input_names': ['sigmas'], 'native_output_names': ['SIGMAS'], 'native_input_types': ['STRING'], 'native_output_types': ['SIGMAS'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            sigmas='1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0',
            _id='7',
            _uid='n7',
        )

        randomnoise = RandomNoise(
            _native_ports={'native_input_names': ['noise_seed'], 'native_output_names': ['NOISE'], 'native_input_types': ['INT'], 'native_output_types': ['NOISE'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            noise_seed=DEFAULT_SEED,
            _id='8',
            _uid='n8',
        )

        # Sampling
        ksamplerselect = KSamplerSelect(
            _native_ports={'native_input_names': ['sampler_name'], 'native_output_names': ['SAMPLER'], 'native_input_types': ['COMBO'], 'native_output_types': ['SAMPLER'], 'native_input_optional': [False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            sampler_name='euler',
            _id='9',
            _uid='n9',
        )

        textencodeqwenimage21 = raw_call('TextEncodeQwenImage21', '5',
            _outputs=('positive', 'negative', 'latent'),
            _native_ports={'native_input_names': ['clip', 'prompt', 'negative_prompt', 'vae', 'resolution', 'images.image_1'], 'native_output_names': ['positive', 'negative', 'latent'], 'native_input_types': ['CLIP', 'STRING', 'STRING', 'VAE', 'INT', 'IMAGE'], 'native_output_types': ['CONDITIONING', 'CONDITIONING', 'LATENT'], 'native_input_optional': None, 'native_input_asset_kinds': None, 'native_output_slots': None},
            negative_prompt=DEFAULT_NEGATIVE_PROMPT,
            prompt=DEFAULT_PROMPT,
            resolution=0,
            clip=cliploader.out('CLIP'),
            vae=vaeloader.out('VAE'),
            _uid='n5',
            _extras={'images.image_1': loadimage.out('IMAGE')},
        )

        qwenimage21cache = raw_call('QwenImage21Cache', '6',
            _outputs=('MODEL',),
            _native_ports={'native_input_names': ['model', 'device', 'dtype'], 'native_output_names': ['MODEL'], 'native_input_types': ['MODEL', 'CHOICE', 'CHOICE'], 'native_output_types': ['MODEL'], 'native_input_optional': [False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            device='auto',
            dtype='default',
            model=unetloader.out('MODEL'),
            _uid='n6',
        )

        # Conditioning
        cfgguider = CFGGuider(
            _native_ports={'native_input_names': ['cfg', 'model', 'negative', 'positive'], 'native_output_names': ['GUIDER'], 'native_input_types': ['FLOAT', 'MODEL', 'CONDITIONING', 'CONDITIONING'], 'native_output_types': ['GUIDER'], 'native_input_optional': [False, False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            cfg=GUIDE_STRENGTH,
            model=qwenimage21cache.out('MODEL'),
            negative=textencodeqwenimage21.out('negative'),
            positive=textencodeqwenimage21.out('positive'),
            _id='10',
            _uid='n10',
        )

        samplercustomadvanced = SamplerCustomAdvanced(
            _native_ports={'native_input_names': ['noise', 'guider', 'sampler', 'sigmas', 'latent_image'], 'native_output_names': ['OUTPUT', 'DENOISED_OUTPUT'], 'native_input_types': ['NOISE', 'GUIDER', 'SAMPLER', 'SIGMAS', 'LATENT'], 'native_output_types': ['LATENT', 'LATENT'], 'native_input_optional': [False, False, False, False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            guider=cfgguider.out('GUIDER'),
            latent_image=textencodeqwenimage21.out('latent'),
            noise=randomnoise.out('NOISE'),
            sampler=ksamplerselect.out('SAMPLER'),
            sigmas=manualsigmas.out('SIGMAS'),
            _id='11',
            _uid='n11',
        )

        # Decode
        vaedecode = VAEDecode(
            _native_ports={'native_input_names': ['samples', 'vae'], 'native_output_names': ['IMAGE'], 'native_input_types': ['LATENT', 'VAE'], 'native_output_types': ['IMAGE'], 'native_input_optional': [False, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            samples=samplercustomadvanced.out('OUTPUT'),
            vae=vaeloader.out('VAE'),
            _id='12',
            _uid='n12',
        )

        # Outputs
        saveimage = SaveImage(
            _native_ports={'native_input_names': ['filename_prefix', 'extra_pnginfo', 'prompt', 'images'], 'native_output_names': None, 'native_input_types': ['STRING', 'EXTRA_PNGINFO', 'PROMPT', 'IMAGE'], 'native_output_types': None, 'native_input_optional': [False, True, True, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            filename_prefix='Qwen_image_2.1',
            images=vaedecode.out('IMAGE'),
            _id='13',
            _uid='n13',
        )

        return wf.finalize(PUBLIC_INPUT_METADATA, outputs=[OutputSpec(node=saveimage, output_type='SaveImage', name='image', artifact_kind='image', mime_type='image/png', filename_prefix='Qwen_image_2.1', expected_cardinality='one')])
