# vibecomfy: manual
"""Transcribe one whole audio or video input into timed word alignments."""
from __future__ import annotations

from vibecomfy.templates import InputSpec, ModelAsset, ReadyMetadata, new_workflow, node, ref

MODEL = 'large-v3-turbo'
MODEL_URL = 'https://openaipublic.azureedge.net/main/whisper/models/aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a/large-v3-turbo.pt'
INPUTS = {
    'audio_ref': InputSpec(node=ref('audio'), field='audio', default='input.wav', type='COMBO', required=True, media_semantics='audio', infer_type=False),
}
PUBLIC_INPUTS = INPUTS
READY_METADATA = ReadyMetadata.build(
    capability='audio', template_id='audio/transcribe', inputs=INPUTS,
    models={'large-v3-turbo': ModelAsset(url=MODEL_URL, sha256='aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a', size_bytes=1617941637, subdir='stt/whisper')},
    requirements={'custom_nodes': [{'name': 'ComfyUI-Whisper', 'slug': 'ComfyUI-Whisper', 'source': 'git', 'commit': '006a709848259ed3d69e2f9fcfd7a75f6c860ddd', 'url': 'https://github.com/yuvraj108c/ComfyUI-Whisper.git', 'class_set': ['Apply Whisper'], 'class_schema_sha256': 'a035372485b38b70022c249aa4cfb2034a832b27b683069b8de7762597c1115e', 'pip_packages': ['openai-whisper', 'soundfile']}]},
    custom_node_packs={'ComfyUI-Whisper': {'commit': '006a709848259ed3d69e2f9fcfd7a75f6c860ddd', 'url': 'https://github.com/yuvraj108c/ComfyUI-Whisper.git', 'class_schema_sha256': 'a035372485b38b70022c249aa4cfb2034a832b27b683069b8de7762597c1115e', 'classes_used': ['Apply Whisper'], 'pip_packages': ['openai-whisper', 'soundfile'], 'status': 'discovered'}},
    ready_id='audio/transcribe',
)


def build():
    with new_workflow(READY_METADATA, source_path=__file__) as wf:
        audio = node('LoadAudio', 'load_audio', _outputs=('AUDIO',), audio='input.wav')
        aligned = node('Apply Whisper', 'apply_whisper', _outputs=('text', 'segments_alignment', 'words_alignment'), audio=audio.out(0), model=MODEL, language='auto', prompt='')
        output = node('VibeComfySaveTranscript', 'save_transcript', text=aligned.out(0), segments_alignment=aligned.out(1), words_alignment=aligned.out(2), filename_prefix='audio/transcript')
        return wf.finalize(INPUTS, output_node=output, output_type='VibeComfySaveTranscript', name='transcript_json', artifact_kind='json', mime_type='application/json', expected_cardinality='one', filename_prefix='audio/transcript')
