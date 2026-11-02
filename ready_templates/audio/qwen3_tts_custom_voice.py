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
    'config.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/config.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5'),
    'generation_config.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/generation_config.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5'),
    'merges.txt': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/merges.txt', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5'),
    'model.safetensors': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/model.safetensors', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', sha256='bc3c7e785eb961179c25450d1acff03f839e0002f2f3a5aeb67b5735c0fa2adb', size_bytes=1811626576),
    'preprocessor_config.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/preprocessor_config.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5'),
    'tokenizer_config.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/tokenizer_config.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5'),
    'vocab.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/vocab.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5'),
    'speech_tokenizer/config.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/speech_tokenizer/config.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice/speech_tokenizer', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5'),
    'speech_tokenizer/configuration.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/speech_tokenizer/configuration.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice/speech_tokenizer', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5'),
    'speech_tokenizer/model.safetensors': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/speech_tokenizer/model.safetensors', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice/speech_tokenizer', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', sha256='836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258', size_bytes=682293092),
    'speech_tokenizer/preprocessor_config.json': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/speech_tokenizer/preprocessor_config.json', subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice/speech_tokenizer', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5'),
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

