"""Regenerate the transcription node's declared lock entry."""
from pathlib import Path
from vibecomfy.node_packs._lockfile import LockEntry, read_lockfile, write_lockfile

path = Path('custom_nodes.lock')
entries = [entry for entry in read_lockfile(path) if entry.name != 'ComfyUI-Whisper']
entries.append(LockEntry(
    name='ComfyUI-Whisper', git_commit_sha='006a709848259ed3d69e2f9fcfd7a75f6c860ddd',
    url='https://github.com/yuvraj108c/ComfyUI-Whisper.git',
    class_schema_sha256='f3933350d1e63c45f36fe1dac1d56691b388c2faaee37e65ff458a5cd5200029',
    class_set=('Apply Whisper',), pip_packages=('openai-whisper', 'soundfile'),
))
write_lockfile(entries, path)
