# vibecomfy: generated
# For hand-editing, run: python -m vibecomfy.cli copy-to-recipe <id>
"""Auto-generated ready_template — use python -m vibecomfy.cli copy-to-recipe <id> for hand-editing."""
from __future__ import annotations

from vibecomfy.templates import InputSpec, ModelAsset, ReadyMetadata, new_workflow
from vibecomfy.nodes.core import SaveAudioMP3
from vibecomfy.nodes.qwentts import AILab_Qwen3TTSCustomVoice


DEFAULT_PROMPT = 'VibeComfy generated this short Qwen voice smoke test from a reusable Python template.'
DEFAULT_SEED = 123


PUBLIC_INPUT_METADATA = {
    'text': InputSpec(node='1', field='text', default=DEFAULT_PROMPT, type='STRING', required=True, media_semantics='text'),
    'voice': InputSpec(node='1', field='speaker', default='Ryan', type='CHOICE', range={'choices': ['Aiden', 'Dylan', 'Eric', 'Ono_Anna', 'Ryan', 'Serena', 'Sohee', 'Uncle_Fu', 'Vivian']}),
    'seed': InputSpec(node='1', field='seed', default=DEFAULT_SEED, type='INT'),
}

MODELS = {
    'config.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/config.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', sha256='81aca2b6fac304944d8acf345272d8a9a727d5fc2e2e66b222ab4729340c7455', size_bytes=4908),
    'generation_config.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/generation_config.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', sha256='f1b90b4513f3b34c62851049e2492d7b4c5940daf1276f89c82b8ef04127f3aa', size_bytes=245),
    'merges.txt': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/merges.txt', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', sha256='599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3', size_bytes=1671839),
    'model.safetensors': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/model.safetensors', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', sha256='bc3c7e785eb961179c25450d1acff03f839e0002f2f3a5aeb67b5735c0fa2adb', size_bytes=1811626576),
    'preprocessor_config.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/preprocessor_config.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', sha256='efdde1022ea9d76928bf7a9cd53139138f5ba2e466e837f08f6105ab1af1c119', size_bytes=127),
    'tokenizer_config.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/tokenizer_config.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', sha256='dc3c31c3bdaedd5016382bb3cbe07323026775ad51f5a4fb564505992ae4a670', size_bytes=7344),
    'vocab.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/vocab.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', sha256='ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910', size_bytes=2776833),
    'speech_tokenizer/config.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/speech_tokenizer/config.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice/speech_tokenizer', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', sha256='ee65bb901c876664ab8707c487157aa1a6ee57c65969b28fb5ec9dc211e68167', size_bytes=2336),
    'speech_tokenizer/configuration.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/speech_tokenizer/configuration.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice/speech_tokenizer', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', sha256='6bc26d64eb5024b4d1dab5a52371958b429256d6c9d59787f1f5294a54e0cebd', size_bytes=76),
    'speech_tokenizer/model.safetensors': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/speech_tokenizer/model.safetensors', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice/speech_tokenizer', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', sha256='836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258', size_bytes=682293092),
    'speech_tokenizer/preprocessor_config.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/speech_tokenizer/preprocessor_config.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice/speech_tokenizer', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', sha256='fcb3805e597e786d4067706e602f6688524640f8d3396790e2e09b5942fcbdfb', size_bytes=234),
}

READY_METADATA = ReadyMetadata.build(
    capability='audio',
    models=MODELS,
    inputs=PUBLIC_INPUT_METADATA,
    custom_node_packs={'ComfyUI-QwenTTS': {'commit': 'd8122a8ba835b65fd65c113d2b273b1ad1579293', 'url': 'https://github.com/1038lab/ComfyUI-QwenTTS.git', 'class_schema_sha256': '4137bb4f37ea178be0e794377829905d9ede1bc65496a23a51d766a3f03b2c84', 'classes_used': ['AILab_Qwen3TTSCustomVoice'], 'pip_packages': ['accelerate', 'librosa', 'openai-whisper', 'qwen-tts', 'soundfile', 'tiktoken'], 'status': 'discovered'}},
    provenance={'source_hash': 'c6aed8da86a51e4590ae97497301e7d2cb30cbb4a8123f273ec25956c0243053', 'source_path': 'ready_templates/sources/custom_nodes/qwen_tts/1038lab/qwen3_tts_custom_voice.json', 'source_id': 'audio/qwen3_tts_custom_voice', 'upstream_source_id': 'qwen3_tts_custom_voice', 'source_type': 'api', 'source_workflow_path': 'ready_templates/sources/custom_nodes/qwen_tts/1038lab/qwen3_tts_custom_voice.json', 'output_mode': 'ready_template', 'ready_id': 'audio/qwen3_tts_custom_voice'},
)

def build() -> VibeWorkflow:
    """Build the workflow (auto-generated)."""
    wf = new_workflow(READY_METADATA, source_path=__file__)

    ailab_qwen3ttscustomvoice = AILab_Qwen3TTSCustomVoice(
        _id='1',
        instruct='Calm, clear, friendly delivery.',
        language='English',
        model_size='0.6B',
        speaker='Ryan',
        seed=DEFAULT_SEED,
        text=DEFAULT_PROMPT,
    )

    saveaudiomp3 = SaveAudioMP3(
        _id='2',
        filename_prefix='audio/qwen3_tts_custom_voice',
        quality='V0',
        audio=ailab_qwen3ttscustomvoice,
    )

    return wf.finalize(PUBLIC_INPUT_METADATA, output_node=saveaudiomp3, output_type='SaveAudioMP3', name='audio', artifact_kind='audio', mime_type='audio/mpeg', expected_cardinality='one', filename_prefix='audio/qwen3_tts_custom_voice')

