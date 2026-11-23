"""Bundle-owned object-info views must be bounded to one publication."""
from __future__ import annotations

import contextvars
import hashlib
import sys
import json
import shutil
import threading
from pathlib import Path

import pytest

from vibecomfy import workflow_bundle as bundle
from vibecomfy.cli_loader import load_workflow_any
from vibecomfy.errors import ObjectInfoCacheCorruptError
from vibecomfy.porting.object_info import consume
from vibecomfy.workflow import VibeWorkflow, WorkflowSource


@pytest.fixture(autouse=True)
def reset_reader():
    consume.reset_cache()
    yield
    consume.reset_cache()


def sample():
    workflow = VibeWorkflow('sample', WorkflowSource('sample'))
    workflow.add_node('ImageResizeKJ', uid='one')
    return workflow


def cache_copy(tmp_path, monkeypatch):
    cache = shutil.copytree(consume.CACHE_DIR, tmp_path / 'cache')
    monkeypatch.setattr(consume, 'CACHE_DIR', cache)
    return cache


def test_warm_qwen_reader_hash_count_under_300(tmp_path, monkeypatch):
    workflow = load_workflow_any('image/qwen_image_2_1_turbo')
    bundle.emit_bundle(workflow, tmp_path / 'warm' / 'workflow.py', {})
    original_sha256 = hashlib.sha256
    count = 0
    def counted(*args, **kwargs):
        nonlocal count
        frame = sys._getframe(1)
        while frame is not None:
            if '/vibecomfy/porting/object_info/' in frame.f_code.co_filename:
                count += 1
                break
            frame = frame.f_back
        return original_sha256(*args, **kwargs)
    monkeypatch.setattr(hashlib, 'sha256', counted)
    bundle.emit_bundle(workflow, tmp_path / 'out' / 'workflow.py', {})
    assert 0 < count < 300, count


@pytest.mark.parametrize('candidate', [False, True])
def test_change_before_publication_refuses_without_publishing(tmp_path, monkeypatch, candidate):
    cache = cache_copy(tmp_path, monkeypatch)
    dest = tmp_path / 'out' / 'workflow.py'
    original_verify = consume.BundleReadSet.verify
    changed = []
    def mutate_then_verify(read_set):
        assert read_set.witnesses
        index = cache / 'index.json'
        index.write_text('[]', encoding='utf-8')
        changed.append(index)
        return original_verify(read_set)
    monkeypatch.setattr(consume.BundleReadSet, 'verify', mutate_then_verify)
    with pytest.raises(ObjectInfoCacheCorruptError):
        if candidate:
            bundle.emit_bundle_with_candidate(sample(), dest, {}, None)
        else:
            bundle.emit_bundle(sample(), dest, {})
    assert changed
    assert not dest.exists()
    assert not dest.with_suffix('.vibe.json').exists()


def test_overlapping_copied_context_keeps_inner_read_set_alive(tmp_path, monkeypatch):
    cache = cache_copy(tmp_path, monkeypatch)
    outer, inner = (tmp_path / name / 'workflow.py' for name in ('outer', 'inner'))
    reached, finished = threading.Event(), threading.Event()
    thread = None
    results = []
    original_lookup = consume._resolve_class_type
    original_read = Path.read_bytes
    swapped = []
    original_journal = bundle._write_publish_transaction
    count = 0
    def lookup(name, **kwargs):
        nonlocal count
        if threading.current_thread() is not thread:
            return original_lookup(name, **kwargs)
        count += 1
        try:
            return original_lookup(name, **kwargs)
        finally:
            if count == 30:
                reached.set()
                assert finished.wait(20)
    def read(path):
        value = original_read(path)
        if threading.current_thread() is thread and count == 30 and path == cache / 'index.json' and not swapped:
            path.write_text('[]', encoding='utf-8')
            swapped.append(True)
        return value
    def emit_inner():
        try:
            bundle.emit_bundle(sample(), inner, {})
            results.append(None)
        except Exception as exc:
            results.append(exc)
        finally:
            reached.set()
    def journal(path, record):
        nonlocal thread
        original_journal(path, record)
        if path == outer and record['state'] == 'prepared' and thread is None:
            thread = threading.Thread(target=contextvars.copy_context().run, args=(emit_inner,))
            thread.start()
            assert reached.wait(20)
    monkeypatch.setattr(Path, 'read_bytes', read)
    monkeypatch.setattr(consume, '_resolve_class_type', lookup)
    monkeypatch.setattr(bundle, '_write_publish_transaction', journal)
    try:
        bundle.emit_bundle(sample(), outer, {})
    finally:
        finished.set()
        if thread:
            thread.join(20)
    assert thread is not None and not thread.is_alive()
    assert count >= 30 and swapped
    assert len(results) == 1 and isinstance(results[0], ObjectInfoCacheCorruptError)
    assert not inner.exists() and not inner.with_suffix('.vibe.json').exists()


def test_symlinked_cache_root_matches_scalar_checks(tmp_path, monkeypatch):
    cache = cache_copy(tmp_path, monkeypatch)
    link = tmp_path / 'linked-cache'
    link.symlink_to(cache, target_is_directory=True)
    monkeypatch.setattr(consume, 'CACHE_DIR', link)
    expected = consume.get_class('ImageResizeKJ')
    read_set = consume.BundleReadSet()
    assert consume.get_class('ImageResizeKJ', read_set=read_set) == expected
    index = cache / 'index.json'
    index.write_text('[]', encoding='utf-8')
    with pytest.raises(ObjectInfoCacheCorruptError):
        consume.get_class('ImageResizeKJ')
    with pytest.raises(ObjectInfoCacheCorruptError):
        consume.get_class('ImageResizeKJ', read_set=read_set)
