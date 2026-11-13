# vibecomfy: generated
# For hand-editing, run: python -m vibecomfy.cli copy-to-recipe <id>
"""Auto-generated ready_template — use python -m vibecomfy.cli copy-to-recipe <id> for hand-editing."""
from __future__ import annotations

from vibecomfy.templates import InputSpec, ReadyMetadata, new_workflow
from vibecomfy.nodes.core import CFGGuider, CLIPTextEncode, CheckpointLoaderSimple, CreateVideo, EmptyLTXVLatentVideo, GetImageSize, GetVideoComponents, KSamplerSelect, LTXAVTextEncoderLoader, LTXVConditioning, LTXVCropGuides, LoadVideo, ManualSigmas, RandomNoise, ResizeImageMaskNode, SamplerCustomAdvanced, SaveVideo, SimpleMath_2, VAEDecodeTiled
from vibecomfy.nodes.ltxvideo import LTXAddVideoICLoRAGuide, LTXICLoRALoaderModelOnly, LTXVHDRDecodePostprocess


CKPT_NAME = 'ltx-2.3-22b-dev.safetensors'
DEFAULT_PROMPT = 'pc game, console game, video game, ugly, still, static, slow'
DEFAULT_SEED = 42
GUIDE_STRENGTH = 1
GUIDE_STRENGTH_2 = 0.5
LORA_NAME = 'ltxv/ltx2/ltx-2.3-22b-ic-lora-hdr-0.9.safetensors'
LORA_NAME_2 = 'ltxv/ltx2/ltx-2.3-22b-distilled-lora-384-1.1.safetensors'
TEXT_ENCODER_NAME = 'comfy_gemma_3_12B_it.safetensors'


PUBLIC_INPUT_METADATA = {
    'seed': InputSpec(node='4832', field='noise_seed', default=DEFAULT_SEED, type='INT'),
    'fps': InputSpec(node='5108', field='fps', default=30, type='FLOAT', omit_if_schema_default=True),
    'prompt': InputSpec(node='2483', field='text', default='HDR footage', type='STRING', required=True, media_semantics='text'),
    'negative_prompt': InputSpec(node='2612', field='text', default=DEFAULT_PROMPT, type='STRING', aliases=('negative',), media_semantics='text'),
}

READY_METADATA = ReadyMetadata.build(
    capability='video',
    inputs=PUBLIC_INPUT_METADATA,
    requirements={'models': [{'name': 'ltx-2.3-22b-dev.safetensors', 'subdir': 'checkpoints', 'url': 'https://huggingface.co/Lightricks/LTX-2.3-fp8/resolve/91eda216f820e5ecb3d17dc9fe3b7cdaf56b587d/ltx-2.3-22b-dev-fp8.safetensors', 'sha256': '28606c5b5a06ce56f896d4dfcb20f212739e07a68fbe48e53638188449d26450', 'size_bytes': 29145431166, 'hf_revision': '91eda216f820e5ecb3d17dc9fe3b7cdaf56b587d'},
            {'name': 'ltxv/ltx2/ltx-2.3-22b-distilled-lora-384-1.1.safetensors', 'subdir': 'loras', 'url': 'https://huggingface.co/Lightricks/LTX-2.3/resolve/c1521179de480464f366a98a9d9b2acc4cc097b9/ltx-2.3-22b-distilled-lora-384-1.1.safetensors', 'sha256': 'f5d4953f3386197a4b4f5abdb17616ff256171e8075c111d6e7d2dfa6e823b3a', 'size_bytes': 7605507256, 'hf_revision': 'c1521179de480464f366a98a9d9b2acc4cc097b9'},
            {'name': 'ltxv/ltx2/ltx-2.3-22b-ic-lora-hdr-0.9.safetensors', 'subdir': 'loras', 'url': 'https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-HDR/resolve/42954a39c9b98745bc015380fdf7ec121e6aeff1/ltx-2.3-22b-ic-lora-hdr-0.9.safetensors', 'sha256': 'c56bfa0f2e4461a8b2f318f494c61c5bf97f462f2220e31ece93ea7851ca871e', 'size_bytes': 327309312, 'hf_revision': '42954a39c9b98745bc015380fdf7ec121e6aeff1'},
            {'name': 'comfy_gemma_3_12B_it.safetensors', 'subdir': 'text_encoders', 'url': 'https://huggingface.co/Comfy-Org/ltx-2/resolve/ccde4ba417d7900669fd56dd292a883cee11ff37/split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors', 'sha256': 'aaca463d11e6d8d2a4bdb0d6299214c15ef78a3f73e0ef8113d5a9d0219b3f6d', 'size_bytes': 9447702218, 'hf_revision': 'ccde4ba417d7900669fd56dd292a883cee11ff37'}]},
    custom_node_packs={'ComfyUI-LTXVideo': {'commit': '229437c6b65796d6a7a63ae34be2bd5ba31fa543', 'url': 'https://github.com/Lightricks/ComfyUI-LTXVideo.git', 'class_schema_sha256': '82e0b1f31509a969cf441c45e2517d0cd93f31b5390cc16f4a0ffa244421f39e', 'classes_used': ['EmptyLTXVLatentVideo', 'LTXAVTextEncoderLoader', 'LTXVConditioning', 'LTXVCropGuides'], 'pip_packages': [], 'status': 'discovered'}},
    provenance={'source_path': 'ready_templates/sources/custom_nodes/ltxvideo/lightricks_2_3/LTX-2.3_ICLoRA_HDR_Distilled.json', 'source_id': 'video/ltx2_3_lightricks_iclora_hdr', 'upstream_source_id': 'LTX-2.3_ICLoRA_HDR_Distilled', 'source_type': 'api', 'source_workflow_path': 'ready_templates/sources/custom_nodes/ltxvideo/lightricks_2_3/LTX-2.3_ICLoRA_HDR_Distilled.json', 'output_mode': 'ready_template', 'ready_id': 'video/ltx2_3_lightricks_iclora_hdr'},
)

def build() -> VibeWorkflow:
    """Build the workflow (auto-generated)."""
    wf = new_workflow(READY_METADATA, source_path=__file__)

    # Loaders
    model, _, vae = CheckpointLoaderSimple(_id='3940', ckpt_name=CKPT_NAME)

    # Sampling
    ksamplerselect = KSamplerSelect(_id='4831', sampler_name='euler_ancestral')

    randomnoise = RandomNoise(
        _id='4832',
        noise_seed=DEFAULT_SEED,
        control_after_generate='fixed',
    )

    ltxavtextencoderloader = LTXAVTextEncoderLoader(
        _id='5023',
        text_encoder=TEXT_ENCODER_NAME,
        ckpt_name=CKPT_NAME,
        device='default',
    )

    manualsigmas = ManualSigmas(
        _id='5025',
        sigmas='1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0',
    )

    loadvideo = LoadVideo(_id='5106', file='hdr_input_video (1).mp4')

    # Conditioning
    cliptextencode = CLIPTextEncode(
        _id='2483',
        text='HDR footage',
        clip=ltxavtextencoderloader,
    )

    cliptextencode_2 = CLIPTextEncode(
        _id='2612',
        text=DEFAULT_PROMPT,
        clip=ltxavtextencoderloader,
    )

    images, audio, fps = GetVideoComponents(_id='5105', video=loadvideo)

    model_3, _ = LTXICLoRALoaderModelOnly(
        _id='5125',
        lora_name=LORA_NAME_2,
        strength_model=GUIDE_STRENGTH_2,
        model=model,
    )

    positive, negative = LTXVConditioning(
        _id='1241',
        frame_rate=fps,
        negative=cliptextencode_2,
        positive=cliptextencode,
    )

    model_2, latent_downscale_factor = LTXICLoRALoaderModelOnly(
        _id='5011',
        lora_name=LORA_NAME,
        model=model_3,
    )

    math_int, _ = SimpleMath_2(_id='5111', value='a*32', a=latent_downscale_factor)

    resizeimagemasknode = ResizeImageMaskNode(
        _id='5112',
        resize_type='scale to multiple',
        scale_method='lanczos',
        input=images,
        **{'resize_type.multiple': math_int},
    )

    width, height, batch_size = GetImageSize(_id='5029', image=resizeimagemasknode)

    emptyltxvlatentvideo = EmptyLTXVLatentVideo(
        _id='3059',
        width=width,
        height=height,
        length=batch_size,
    )

    positive_2, negative_2, latent = LTXAddVideoICLoRAGuide(
        _id='5012',
        crop=1,
        use_tiled_encode='disabled',
        image=resizeimagemasknode,
        latent=emptyltxvlatentvideo,
        negative=negative,
        positive=positive,
        vae=vae,
    )

    cfgguider = CFGGuider(
        _id='4828',
        cfg=GUIDE_STRENGTH,
        model=model_2,
        negative=negative_2,
        positive=positive_2,
    )

    output, _ = SamplerCustomAdvanced(
        _id='4829',
        guider=cfgguider,
        latent_image=latent,
        noise=randomnoise,
        sampler=ksamplerselect,
        sigmas=manualsigmas,
    )

    _, _, latent_2 = LTXVCropGuides(
        _id='5013',
        latent=output,
        negative=negative_2,
        positive=positive_2,
    )

    # Decode
    vaedecodetiled = VAEDecodeTiled(
        _id='4851',
        tile_size=768,
        overlap=256,
        temporal_size=8,
        temporal_overlap=4,
        samples=latent_2,
        vae=vae,
    )

    _, hdr_linear = LTXVHDRDecodePostprocess(
        _id='5114',
        exposure=7.1,
        output_dir='output/hdr_exr3',
        save_exr=True,
        image=vaedecodetiled,
    )

    createvideo = CreateVideo(
        _id='5108',
        audio=audio,
        images=hdr_linear,
    )

    # Outputs
    savevideo = SaveVideo(_id='5109', filename_prefix='output', video=createvideo)

    return wf.finalize(PUBLIC_INPUT_METADATA, output_node=savevideo, output_type='SaveVideo', name='video', artifact_kind='video', mime_type='video/mp4', expected_cardinality='one', filename_prefix='output')

