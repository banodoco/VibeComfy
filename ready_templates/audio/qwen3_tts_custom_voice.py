# vibecomfy: generated
# For hand-editing, run: python -m vibecomfy.cli copy-to-recipe <id>
# vibecomfy: surface=canonical
"""Auto-generated ready_template — use python -m vibecomfy.cli copy-to-recipe <id> for hand-editing."""
from __future__ import annotations

from vibecomfy.templates import InputSpec, ModelAsset, OutputSpec, ReadyMetadata, new_workflow, ref
from vibecomfy.workflow import VibeWorkflow
from vibecomfy.nodes.core import SaveAudioMP3
from vibecomfy.nodes.qwentts import AILab_Qwen3TTSCustomVoice


DEFAULT_PROMPT = 'VibeComfy generated this short Qwen voice smoke test from a reusable Python template.'
DEFAULT_SEED = 123
DEFAULT_VOICE = 'Ryan'


MODELS = {
    'config': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/config.json', sha256=None, hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', size_bytes=4908, subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice'),
    'generation_config': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/generation_config.json', sha256=None, hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', size_bytes=245, subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice'),
    'merges': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/merges.txt', sha256=None, hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', size_bytes=1671839, subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice'),
    'model': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/model.safetensors', sha256='bc3c7e785eb961179c25450d1acff03f839e0002f2f3a5aeb67b5735c0fa2adb', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', size_bytes=1811626576, subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice'),
    'preprocessor_config': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/preprocessor_config.json', sha256=None, hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', size_bytes=127, subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice'),
    'tokenizer_config': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/tokenizer_config.json', sha256=None, hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', size_bytes=7344, subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice'),
    'vocab': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/vocab.json', sha256=None, hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', size_bytes=2776833, subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice'),
    'config_2': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/speech_tokenizer/config.json', sha256=None, hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', size_bytes=2336, subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice/speech_tokenizer'),
    'configuration': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/speech_tokenizer/configuration.json', sha256=None, hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', size_bytes=76, subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice/speech_tokenizer'),
    'model_2': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/speech_tokenizer/model.safetensors', sha256='836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258', hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', size_bytes=682293092, subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice/speech_tokenizer'),
    'preprocessor_config_2': ModelAsset(url='https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/resolve/85e237c12c027371202489a0ec509ded67b5e4b5/speech_tokenizer/preprocessor_config.json', sha256=None, hf_revision='85e237c12c027371202489a0ec509ded67b5e4b5', size_bytes=234, subdir='TTS/Qwen3-TTS/Qwen3-TTS-12Hz-0.6B-CustomVoice/speech_tokenizer'),
}


PUBLIC_INPUT_METADATA = {
    'seed': InputSpec(node=ref('ailab_qwen3ttscustomvoice'), field='seed', default=DEFAULT_SEED, type='INT', infer_type=False),
    'text': InputSpec(node=ref('ailab_qwen3ttscustomvoice'), field='text', default=DEFAULT_PROMPT, type='STRING', required=True, media_semantics='text', infer_type=False),
    'voice': InputSpec(node=ref('ailab_qwen3ttscustomvoice'), field='speaker', default=DEFAULT_VOICE, type='CHOICE', range={'choices': ['Aiden', 'Dylan', 'Eric', 'Ono_Anna', 'Ryan', 'Serena', 'Sohee', 'Uncle_Fu', 'Vivian']}, infer_type=False),
}


READY_METADATA = ReadyMetadata.build(
    capability='audio',
    template_id='audio/qwen3_tts_custom_voice',
    inputs=PUBLIC_INPUT_METADATA,
    models=MODELS,
    custom_node_packs={'ComfyUI-QwenTTS': {'commit': 'd8122a8ba835b65fd65c113d2b273b1ad1579293', 'url': 'https://github.com/1038lab/ComfyUI-QwenTTS.git', 'class_schema_sha256': '4137bb4f37ea178be0e794377829905d9ede1bc65496a23a51d766a3f03b2c84', 'classes_used': ['AILab_Qwen3TTSCustomVoice'], 'pip_packages': ['accelerate', 'librosa', 'openai-whisper', 'qwen-tts', 'soundfile', 'tiktoken'], 'status': 'discovered'}},
    operation='authored',
    provenance={'operation': 'authored', 'source_workflow': 'ready_templates/sources/custom_nodes/qwen_tts/1038lab/qwen3_tts_custom_voice.json', 'source_id': 'audio/qwen3_tts_custom_voice', 'ready_id': 'audio/qwen3_tts_custom_voice'},
    source_hash='c6aed8da86a51e4590ae97497301e7d2cb30cbb4a8123f273ec25956c0243053',
    source_path='ready_templates/sources/custom_nodes/qwen_tts/1038lab/qwen3_tts_custom_voice.json',
    source_id='audio/qwen3_tts_custom_voice',
    upstream_source_id='qwen3_tts_custom_voice',
    source_type='api',
    source_workflow_path='ready_templates/sources/custom_nodes/qwen_tts/1038lab/qwen3_tts_custom_voice.json',
    output_mode='ready_template',
    ready_id='audio/qwen3_tts_custom_voice',
    source_bundle={'format_version': 2, 'generation_id': 'c6136ae0a75ec895b61cf4d7927c519cafac0bd34343de46ccde479ad6c5cd85', 'custody_digest': '81702e938e165605bbea82a8cb0616fa4118b2942c123dcb4954fa2d81a99ea2'},
)

def build() -> VibeWorkflow:
    """Build the workflow (auto-generated)."""
    with new_workflow(READY_METADATA, source_path=__file__) as wf:

        ailab_qwen3ttscustomvoice = AILab_Qwen3TTSCustomVoice(
            _native_ports={'native_input_names': ['text', 'speaker', 'model_size', 'language', 'instruct', 'unload_models', 'seed'], 'native_output_names': ['AUDIO'], 'native_input_types': ['STRING', 'CHOICE', 'CHOICE', 'CHOICE', 'STRING', 'BOOLEAN', 'INT'], 'native_output_types': ['AUDIO'], 'native_input_optional': [False, False, False, False, True, True, True], 'native_input_asset_kinds': None, 'native_output_slots': None},
            instruct='Calm, clear, friendly delivery.',
            language='English',
            model_size='0.6B',
            seed=DEFAULT_SEED,
            speaker=DEFAULT_VOICE,
            text=DEFAULT_PROMPT,
            _id='1',
            _uid='n1',
        )

        saveaudiomp3 = SaveAudioMP3(
            _native_ports={'native_input_names': ['filename_prefix', 'quality', 'extra_pnginfo', 'prompt', 'audio'], 'native_output_names': None, 'native_input_types': ['STRING', 'COMBO', 'EXTRA_PNGINFO', 'PROMPT', 'AUDIO'], 'native_output_types': None, 'native_input_optional': [False, False, True, True, False], 'native_input_asset_kinds': None, 'native_output_slots': None},
            filename_prefix='audio/qwen3_tts_custom_voice',
            quality='V0',
            audio=ailab_qwen3ttscustomvoice.out('AUDIO'),
            _id='2',
            _uid='n2',
        )

        return wf.finalize(PUBLIC_INPUT_METADATA, outputs=[OutputSpec(node=saveaudiomp3, output_type='SaveAudioMP3', name='audio', artifact_kind='audio', mime_type='audio/mpeg', filename_prefix='audio/qwen3_tts_custom_voice', expected_cardinality='one')])
