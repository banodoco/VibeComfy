# vibecomfy: manual
"""Transcribe one whole audio or video input into timed word alignments."""
from __future__ import annotations

from vibecomfy.templates import InputSpec, ModelAsset, ReadyMetadata, new_workflow, node, ref

MODEL = 'large-v3-turbo'
MODEL_URL = 'https://openaipublic.azureedge.net/main/whisper/models/aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a/large-v3-turbo.pt'
PUBLIC_INPUT_METADATA = {
    'audio_ref': InputSpec(node=ref('audio'), field='audio', default='input.wav', type='COMBO', required=True, media_semantics='audio', infer_type=False),
}
MODELS = {
    MODEL: ModelAsset(
        url=MODEL_URL,
        sha256='aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a',
        size_bytes=1617941637,
        subdir='stt/whisper',
    ),
}
WHISPER_REQUIREMENT = {
    'slug': 'ComfyUI-Whisper',
    'source': 'git',
    'commit': '006a709848259ed3d69e2f9fcfd7a75f6c860ddd',
    'url': 'https://github.com/yuvraj108c/ComfyUI-Whisper.git',
    'class_set': ['Apply Whisper'],
    'class_schema_sha256': 'a035372485b38b70022c249aa4cfb2034a832b27b683069b8de7762597c1115e',
    'pip_packages': ['openai-whisper==20250625', 'soundfile'],
}
REQUIREMENTS = {
    'custom_nodes': ['ComfyUI-Whisper'],
    'custom_node_refs': [WHISPER_REQUIREMENT],
}
READY_METADATA = ReadyMetadata.build(
    capability='audio',
    template_id='audio/transcribe',
    inputs=PUBLIC_INPUT_METADATA,
    models=MODELS,
    requirements=REQUIREMENTS,
    custom_node_packs={
        WHISPER_REQUIREMENT['slug']: {
            'commit': WHISPER_REQUIREMENT['commit'],
            'url': WHISPER_REQUIREMENT['url'],
            'class_schema_sha256': WHISPER_REQUIREMENT['class_schema_sha256'],
            'classes_used': WHISPER_REQUIREMENT['class_set'],
            'pip_packages': WHISPER_REQUIREMENT['pip_packages'],
            'status': 'discovered',
        },
    },
    comfy_core={
        'version': '0.36.0',
        'commit': '6bfaacc67c2103481e5f0c84d75257cd0581d86a',
        'status': 'static_source_schema_only',
    },
    ready_id='audio/transcribe',
)


def build():
    with new_workflow(READY_METADATA, source_path=__file__) as wf:
        audio = node(wf, 'LoadAudio', 'load_audio', _outputs=('AUDIO',), audio='input.wav')
        aligned = node(wf, 'Apply Whisper', 'apply_whisper', _outputs=('text', 'segments_alignment', 'words_alignment'), audio=audio.out(0), model=MODEL, language='auto', prompt='')
        output = node(wf, 'VibeComfySaveTranscript', 'save_transcript', text=aligned.out(0), segments_alignment=aligned.out(1), words_alignment=aligned.out(2), filename_prefix='audio/transcript')
        return wf.finalize(PUBLIC_INPUT_METADATA, output_node=output, output_type='VibeComfySaveTranscript', name='transcript_json', artifact_kind='json', mime_type='application/json', expected_cardinality='one', filename_prefix='audio/transcript')
