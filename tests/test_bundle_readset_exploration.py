import json

import pytest

from vibecomfy.porting.object_info import consume
from vibecomfy.workflow_bundle import _with_bundle_class_memo


@pytest.mark.parametrize(('warm_generation', 'omit_pack'), [(False, False), (True, False), (False, True)])
def test_reads_are_recorded_before_later_lookup_and_final_check(tmp_path, monkeypatch, warm_generation, omit_pack):
    """Check observed open paths at lookup boundaries, including warm state."""
    import builtins
    import io
    import os
    from pathlib import Path
    from vibecomfy.workflow import VibeWorkflow, WorkflowSource
    from vibecomfy.workflow_bundle import emit_bundle

    cache = tmp_path / 'cache'
    if warm_generation:
        from vibecomfy.porting.object_info.serialize import build_cache
        source = tmp_path / 'source.json'
        source.write_text(json.dumps({'Spare': {'python_module': 'custom_nodes.Spare.nodes', 'input': {'required': {}}, 'output': ['INT']}}))
        build_cache(source, version='v1', cache_dir=cache)
    else:
        cache.mkdir()
        (cache / 'index.json').write_text(json.dumps({'Integer': 'pack.json'}))
        (cache / 'pack.json').write_text(json.dumps({'Integer': {'outputs': []}}))
    monkeypatch.setattr(consume, 'CACHE_DIR', cache)
    monkeypatch.setattr(consume, '_index', None)
    monkeypatch.setattr(consume, '_pack_cache', {})
    monkeypatch.setattr(consume, '_reader_state', None)
    if warm_generation:
        assert consume.get_class('Spare')

    opened = set()
    checkpoints = []
    cache_root = cache.resolve()
    def record(path):
        if isinstance(path, (str, bytes, os.PathLike)):
            p = Path(os.fsdecode(path)).absolute()
            if p.is_relative_to(cache_root):
                opened.add(p)
    original_io_open, original_builtin_open, original_os_open = io.open, builtins.open, os.open
    def io_open(path, mode='r', *args, **kwargs):
        if 'r' in mode or '+' in mode:
            record(path)
        return original_io_open(path, mode, *args, **kwargs)
    def builtin_open(path, mode='r', *args, **kwargs):
        if 'r' in mode or '+' in mode:
            record(path)
        return original_builtin_open(path, mode, *args, **kwargs)
    def os_open(path, flags, *args, **kwargs):
        if flags & os.O_ACCMODE != os.O_WRONLY:
            record(path)
        return original_os_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(io, 'open', io_open)
    monkeypatch.setattr(builtins, 'open', builtin_open)
    monkeypatch.setattr(os, 'open', os_open)

    original_resolve = consume._resolve_class_type
    original_validate = consume._BundleClassMemo.validate
    original_observe = consume._BundleClassMemo.observe
    if omit_pack:
        def omit(owner, path, witness):
            if path.name != 'pack.json':
                original_observe(owner, path, witness)
        monkeypatch.setattr(consume._BundleClassMemo, 'observe', omit)
    def check(owner, label):
        missing = opened - owner.witnesses.keys()
        checkpoints.append((label, set(opened), set(owner.witnesses)))
        assert not missing, (label, sorted(map(str, missing)))
    def resolve(class_type):
        owner = consume._BUNDLE_CLASS_MEMO.get()
        if isinstance(owner, consume._BundleClassMemo) and owner.active and opened:
            check(owner, 'next lookup')
        return original_resolve(class_type)
    def validate(owner, class_type=None):
        check(owner, 'final' if class_type is None else 'memo hit')
        if warm_generation:
            assert not owner.memo_allowed
        return original_validate(owner, class_type)
    monkeypatch.setattr(consume, '_resolve_class_type', resolve)
    monkeypatch.setattr(consume._BundleClassMemo, 'validate', validate)
    workflow = VibeWorkflow('sample', WorkflowSource('sample'))
    workflow.add_node('Integer', uid='integer-node', value=7)
    if omit_pack:
        with pytest.raises(AssertionError, match='pack.json'):
            emit_bundle(workflow, tmp_path / 'workflow.py', {'operation': 'authored'})
        return
    emit_bundle(workflow, tmp_path / 'workflow.py', {'operation': 'authored'})
    assert opened and any(label == 'next lookup' for label, _, _ in checkpoints)
    final = [row for row in checkpoints if row[0] == 'final']
    assert final and opened <= final[-1][2]
    if warm_generation:
        assert any('Spare' in path.name for path in opened)
    # Mutation control: omitting any actually opened path must fail the check.
    assert not opened <= (final[-1][2] - {next(iter(opened))})


def test_opened_object_info_paths_are_in_readset(tmp_path, monkeypatch):
    from pathlib import Path
    from vibecomfy.workflow import VibeWorkflow, WorkflowSource
    from vibecomfy.workflow_bundle import emit_bundle

    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'index.json').write_text(json.dumps({'Integer': 'pack.json'}))
    (cache / 'pack.json').write_text(json.dumps({'Integer': {'outputs': []}}))
    monkeypatch.setattr(consume, 'CACHE_DIR', cache)
    monkeypatch.setattr(consume, '_index', None)
    monkeypatch.setattr(consume, '_pack_cache', {})
    monkeypatch.setattr(consume, '_reader_state', None)
    opened = set()
    observed = set()
    original_open = Path.open
    original_validate = consume._BundleClassMemo.validate

    def record_open(path, *args, **kwargs):
        if path.is_relative_to(cache) and (not args or 'r' in args[0]):
            opened.add(path)
        return original_open(path, *args, **kwargs)

    def validate(owner, *args, **kwargs):
        result = original_validate(owner, *args, **kwargs)
        observed.update(owner.witnesses)
        return result

    monkeypatch.setattr(Path, 'open', record_open)
    monkeypatch.setattr(consume._BundleClassMemo, 'validate', validate)
    workflow = VibeWorkflow('sample', WorkflowSource('sample'))
    workflow.add_node('Integer', uid='integer-node', value=7)
    emit_bundle(workflow, tmp_path / 'workflow.py', {'operation': 'authored'})
    assert opened
    assert opened <= observed
    # Negative control: omitting a provider from the recorded set must fail.
    assert not opened <= (observed - {cache / 'pack.json'})


def test_opened_committed_generation_paths_are_in_readset(tmp_path, monkeypatch):
    from pathlib import Path
    from vibecomfy.workflow import VibeWorkflow, WorkflowSource
    from vibecomfy.workflow_bundle import emit_bundle

    cache = tmp_path / 'cache'
    from vibecomfy.porting.object_info.serialize import build_cache
    source = tmp_path / 'source.json'
    source.write_text(json.dumps({'Integer': {'python_module': 'nodes', 'input': {'required': {}}, 'output': ['INT']}}))
    build_cache(source, version='v1', cache_dir=cache)
    monkeypatch.setattr(consume, 'CACHE_DIR', cache)
    monkeypatch.setattr(consume, '_index', None)
    monkeypatch.setattr(consume, '_pack_cache', {})
    monkeypatch.setattr(consume, '_reader_state', None)
    opened = set()
    observed = set()
    original_open = Path.open
    original_validate = consume._BundleClassMemo.validate

    def record_open(path, *args, **kwargs):
        if path.is_relative_to(cache) and (not args or 'r' in args[0]):
            opened.add(path)
        return original_open(path, *args, **kwargs)

    def validate(owner, *args, **kwargs):
        result = original_validate(owner, *args, **kwargs)
        observed.update(owner.witnesses)
        return result

    monkeypatch.setattr(Path, 'open', record_open)
    monkeypatch.setattr(consume._BundleClassMemo, 'validate', validate)
    workflow = VibeWorkflow('sample', WorkflowSource('sample'))
    workflow.add_node('Integer', uid='integer-node', value=7)
    emit_bundle(workflow, tmp_path / 'workflow.py', {'operation': 'authored'})
    assert opened
    assert opened <= observed


def test_live_global_mapping_changes_are_seen_on_hits(tmp_path, monkeypatch):
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'index.json').write_text(json.dumps({'A': 'first.json'}))
    (cache / 'first.json').write_text(json.dumps({'A': {'value': 7}}))
    (cache / 'second.json').write_text(json.dumps({'A': {'value': 9}}))
    monkeypatch.setattr(consume, 'CACHE_DIR', cache)
    monkeypatch.setattr(consume, '_index', None)
    monkeypatch.setattr(consume, '_pack_cache', {})
    monkeypatch.setattr(consume, '_reader_state', None)

    @_with_bundle_class_memo
    def lookup():
        assert consume._resolve_class_type('A')['value'] == 7
        consume._pack_cache['first.json']['A'] = {'value': 8}
        assert consume._resolve_class_type('A')['value'] == 8
        consume._index['A'] = 'second.json'
        assert consume._resolve_class_type('A')['value'] == 9
        consume._index.pop('A')
        assert consume._resolve_class_type('A') is None

    lookup()
