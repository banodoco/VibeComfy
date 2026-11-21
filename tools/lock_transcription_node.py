"""Regenerate the transcription node's lock entry from its pinned schema."""
from pathlib import Path

from vibecomfy.node_packs._lockfile import LockEntry, compute_schema_hash, read_lockfile, write_lockfile
from vibecomfy.porting.object_info import get_class_by_identity


def main() -> None:
    pack = 'ComfyUI-Whisper'
    commit = '006a709848259ed3d69e2f9fcfd7a75f6c860ddd'
    class_type = 'Apply Whisper'
    schema = get_class_by_identity(class_type, pack_slug=pack, git_commit=commit)
    if schema is None:
        raise RuntimeError(f'Missing {class_type} schema for {pack}@{commit}')
    path = Path(__file__).resolve().parents[1] / 'custom_nodes.lock'
    entries = [entry for entry in read_lockfile(path) if entry.name != pack]
    entries.append(LockEntry(
        name=pack,
        git_commit_sha=commit,
        url='https://github.com/yuvraj108c/ComfyUI-Whisper.git',
        class_schema_sha256=compute_schema_hash({class_type: schema}),
        class_set=(class_type,),
        pip_packages=('openai-whisper==20250625', 'soundfile'),
    ))
    write_lockfile(entries, path)


if __name__ == '__main__':
    main()
