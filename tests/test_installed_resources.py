"""Release gate for the runtime data in every non-editable install route."""
from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import textwrap
import tomllib
import venv

import pytest


CHECKOUT = Path(__file__).resolve().parents[1]


INSTALLED_CHECK = textwrap.dedent(r'''
    import hashlib
    import importlib.util
    import json
    from pathlib import Path
    import sys

    import vibecomfy
    from vibecomfy import resources
    from vibecomfy.comfy_nodes import _git_info_snapshot
    from vibecomfy.errors import CheckoutRequiredError
    from vibecomfy.registry.ready import workflow_from_ready
    from vibecomfy.runtime.session import (
        current_source_content_digest,
        current_source_revision,
    )
    from vibecomfy.security.agent_generated_loader import load_agent_generated_scratchpad
    from vibecomfy.security.provenance import Provenance
    from vibecomfy.utils import find_repo_root
    from vibecomfy.workflow_bundle import emit_bundle_with_candidate, load_bundle

    checkout = Path(sys.argv[1]).resolve()
    work = Path(sys.argv[2]).resolve()
    package = Path(vibecomfy.__file__).resolve().parent
    assert package.is_relative_to(Path(sys.prefix).resolve()), package
    assert all(
        not Path(path).resolve().is_relative_to(checkout)
        for path in sys.path if path
    ), sys.path
    try:
        find_repo_root()
    except CheckoutRequiredError:
        pass
    else:
        raise AssertionError('a non-editable install found a checkout')
    assert resources.layout() == 'installed'
    index = resources.template_index()
    assert index and index['templates']
    assert 'image/qwen_image_2_1_turbo' in {
        row['id'] for row in index['templates']
    }
    lock = resources.custom_nodes_lock()
    assert lock and lock.get('nodepacks', lock)
    assert isinstance(resources.strict_ready_exceptions(), dict)
    assert resources.comfy_metadata()
    assert resources.coverage_manifest()
    assert resources.ready_templates_root() == package / 'ready_templates'
    assert current_source_revision() is None
    assert current_source_content_digest() is None
    assert _git_info_snapshot() == {
        'sha': None, 'dirty': None, 'state': 'unavailable',
    }

    workflow = workflow_from_ready('image/qwen_image_2_1_turbo')
    smoke_inputs = {
        'prompt': 'A small red fox beside a blue ceramic teacup, clean studio light',
        'negative_prompt': '',
        'width': 512,
        'height': 512,
        'seed': 0,
    }
    assert set(smoke_inputs) <= set(workflow.inputs)
    for name, value in smoke_inputs.items():
        workflow.set_input(name, value)
    bundle = load_bundle(workflow)
    emitted = emit_bundle_with_candidate(
        bundle.workflow,
        work / 'rewritten_qwen.py',
        bundle.provenance,
        bundle.ui_sidecar,
        source_format='ready_template',
    )
    assert emitted.python_path is not None
    reloaded = load_bundle(emitted.python_path, trust=Provenance.USER_CONFIRMED)
    api = reloaded.workflow.compile('api')
    assert api
    assert any(node['class_type'] == 'SaveImage' for node in api.values())
    latent, = (node for node in api.values() if node['class_type'] == 'EmptyLatentImage')
    assert latent['inputs']['width'] == 512
    assert latent['inputs']['height'] == 512
    encoder, = (node for node in api.values() if node['class_type'] == 'TextEncodeQwenImage21')
    assert encoder['inputs']['prompt'] == smoke_inputs['prompt']

    h3 = load_agent_generated_scratchpad(checkout / 'tests/fixtures/h3_canonical.py')
    assert sum(
        node.class_type == 'MiniMaxH3ReferenceToVideo' for node in h3.nodes.values()
    ) >= 7
    h3_api = h3.compile('api')
    assert any(node['class_type'] == 'MiniMaxH3ReferenceToVideo' for node in h3_api.values())
    assert any(node['class_type'] == 'VHS_VideoCombine' for node in h3_api.values())

    builder = checkout / 'comfy-inspection/MiniMax_H3_AV_EncodeDecode_Inpaint.py'
    spec = importlib.util.spec_from_file_location('installed_h3_av', builder)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    h3_av_api = module.build().compile('api')
    assert h3_av_api['92']['class_type'] == 'SaveVideo'
    assert h3_av_api['93']['class_type'] == 'SaveAudio'

    # Compare every tracked package data file, as well as the entire relocated
    # ready-template tree (including Python helpers and JSON sidecars).
    manifest = {}
    for path in package.rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        relative = path.relative_to(package)
        if relative.parts[0] != 'ready_templates' and path.suffix in {'.py', '.pyi'}:
            continue
        manifest[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    print(json.dumps({'package': str(package), 'resources': manifest}, sort_keys=True))
''')


MISSING_CHECK = textwrap.dedent(r'''
    from pathlib import Path
    import sys

    copied_root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(copied_root))
    import vibecomfy
    from vibecomfy.errors import ShippedResourceMissingError
    from vibecomfy.resources import template_index

    package = copied_root / 'vibecomfy'
    assert Path(vibecomfy.__file__).resolve().parent == package
    missing = package / 'template_index.json'
    assert not missing.exists()
    try:
        template_index()
    except ShippedResourceMissingError as exc:
        assert 'template_index.json' in str(exc)
        assert str(missing) in str(exc)
    else:
        raise AssertionError('missing shipped index silently degraded')
''')


@pytest.mark.timeout(1200)
def test_installed_resources_match_and_execute_across_artifacts(tmp_path: Path) -> None:
    # Tool availability is part of this release gate, never a reason to skip it.
    for module in ('build', 'hatchling', 'pip'):
        assert importlib.util.find_spec(module) is not None, f'missing required tool: {module}'

    home = tmp_path / 'home'
    temporary = tmp_path / 'tmp'
    home.mkdir()
    temporary.mkdir()
    env = {
        'PATH': os.environ.get('PATH', os.defpath),
        'HOME': str(home),
        'TMPDIR': str(temporary),
        'PYTHONNOUSERSITE': '1',
    }
    sequence = itertools.count()

    def run(argv: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
        # A fresh, empty cwd prevents imports or data discovery through the
        # test's working directory, even during build/install tool checks.
        cwd = tmp_path / f'empty-{next(sequence)}'
        cwd.mkdir()
        result = subprocess.run(
            argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
        )
        assert result.returncode == 0, (
            f'command failed ({result.returncode}): {argv!r}\n'
            f'{result.stdout}\n{result.stderr}'
        )
        return result

    tracked = run(['git', '-C', str(CHECKOUT), 'ls-files', '-z']).stdout.split('\0')
    expected = {}
    relocated = {
        'template_index.json': 'template_index.json',
        'custom_nodes.lock': 'custom_nodes.lock',
        'docs/templates/strict_ready_exceptions.json': 'porting/strict_ready_exceptions.json',
    }
    for name in tracked:
        path = Path(name)
        if name in relocated:
            relative = relocated[name]
        elif name.startswith('ready_templates/'):
            relative = name
        elif name.startswith('vibecomfy/') and path.suffix not in {'.py', '.pyi'}:
            relative = path.relative_to('vibecomfy').as_posix()
        else:
            continue
        expected[relative] = hashlib.sha256((CHECKOUT / path).read_bytes()).hexdigest()
    assert 'ready_templates/sources/manifests/coverage.json' in expected
    assert any('/schemas/' in name for name in expected)

    direct_dir = tmp_path / 'a'
    sdist_dir = tmp_path / 'b'
    run([
        sys.executable, '-m', 'build', '--wheel', '--no-isolation',
        '--outdir', str(direct_dir), str(CHECKOUT),
    ])
    # build's default is sdist followed by a wheel built FROM that sdist.
    run([
        sys.executable, '-m', 'build', '--no-isolation',
        '--outdir', str(sdist_dir), str(CHECKOUT),
    ])
    direct_wheel, = direct_dir.glob('vibecomfy-*.whl')
    sdist_wheel, = sdist_dir.glob('vibecomfy-*.whl')
    sdist, = sdist_dir.glob('vibecomfy-*.tar.gz')
    assert sdist.is_file()
    dependencies = tomllib.loads((CHECKOUT / 'pyproject.toml').read_text(encoding='utf-8'))[
        'project'
    ]['dependencies']

    manifests = []
    for name, wheel in (('wheel', direct_wheel), ('sdist-wheel', sdist_wheel), ('source', None)):
        venv_dir = tmp_path / name
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        scripts = Path(sysconfig.get_path('scripts', vars={
            'base': str(venv_dir), 'platbase': str(venv_dir),
        }))
        python = scripts / ('python.exe' if os.name == 'nt' else 'python')
        assert python.is_file(), python
        run([str(python), '-I', '-m', 'pip', '--version'])
        if wheel is not None:
            run([str(python), '-I', '-m', 'pip', 'install', str(wheel)])
        else:
            # Source installation must use its own build backend and runtime
            # dependencies; it cannot borrow the outer interpreter's packages.
            run([str(python), '-I', '-m', 'pip', 'install', 'hatchling>=1.20', *dependencies])
            run([
                str(python), '-I', '-m', 'pip', 'install', '--no-deps',
                '--no-build-isolation', str(CHECKOUT),
            ])

        work = tmp_path / f'{name}-work'
        work.mkdir()
        checked = run([
            str(python), '-I', '-c', INSTALLED_CHECK, str(CHECKOUT), str(work),
        ], timeout=180)
        report = json.loads(checked.stdout.splitlines()[-1])
        assert report['resources'] == expected, name
        manifests.append(report['resources'])

        copied = tmp_path / f'{name}-missing'
        shutil.copytree(
            Path(report['package']), copied / 'vibecomfy',
            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'),
        )
        (copied / 'vibecomfy/template_index.json').unlink()
        run([str(python), '-I', '-c', MISSING_CHECK, str(copied)], timeout=60)
        shutil.rmtree(copied)
    assert manifests[0] == manifests[1] == manifests[2]
