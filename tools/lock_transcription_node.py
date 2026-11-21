"""Regenerate the transcription node's declared lock entry from indexed schema."""
import argparse
import json
from pathlib import Path
from vibecomfy.node_packs._lockfile import LockEntry, compute_schema_hash, read_lockfile, write_lockfile

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'custom_nodes.lock'
parser = argparse.ArgumentParser()
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
index = json.loads((ROOT / 'vibecomfy/porting/cache/object_info/index.json').read_text())
cache = json.loads((ROOT / 'vibecomfy/porting/cache/object_info' / index['Apply Whisper']).read_text())
schema = cache['Apply Whisper']
schema_hash = compute_schema_hash({'Apply Whisper': schema})
entries = [entry for entry in read_lockfile(path) if entry.name != 'ComfyUI-Whisper']
entries.append(LockEntry(
    name='ComfyUI-Whisper', git_commit_sha='006a709848259ed3d69e2f9fcfd7a75f6c860ddd',
    url='https://github.com/yuvraj108c/ComfyUI-Whisper.git',
    class_schema_sha256=schema_hash,
    class_set=('Apply Whisper',), pip_packages=('openai-whisper', 'soundfile'),
))
if args.check:
    current = next(entry for entry in read_lockfile(path) if entry.name == 'ComfyUI-Whisper')
    if current.class_schema_sha256 != schema_hash:
        raise SystemExit('custom_nodes.lock is stale; run python tools/lock_transcription_node.py')
else:
    write_lockfile(entries, path)
