"""Exercise a real run using a fresh, non-editable wheel installation."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import venv


ROOT = Path(__file__).resolve().parents[1]


def test_installed_wheel_executes_with_stub_server(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps",
         "--wheel-dir", str(wheel_dir), str(ROOT)],
        cwd=tmp_path, env=env, check=True, timeout=180,
    )
    wheel, = wheel_dir.glob("vibecomfy-*.whl")
    venv_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(venv_dir)
    python = venv_dir / "bin" / "python"
    subprocess.run([str(python), "-m", "pip", "install", str(wheel)],
                   cwd=tmp_path, env=env, check=True, timeout=180)
    script = textwrap.dedent('''
        import json
        from pathlib import Path
        from types import SimpleNamespace
        import sys
        import vibecomfy
        from vibecomfy.errors import CheckoutRequiredError
        from vibecomfy.utils import find_repo_root
        from vibecomfy.runtime import session
        from vibecomfy.runtime.run import run_sync
        from vibecomfy.schema import NodeSchema
        from vibecomfy.workflow import VibeNode, VibeOutput, VibeWorkflow, WorkflowSource
        from vibecomfy.workflow_bundle import load_bundle
        from vibecomfy.registry.ready import repo_ready_template_root
        from vibecomfy.registry.static_contract import extract_ready_template_contract, _project_version
        from vibecomfy.porting.strict_ready import load_strict_ready_exceptions, _default_exception_path
        from vibecomfy.node_packs._lockfile import resolve_lockfile_path, read_lockfile
        from vibecomfy.contracts.surface import _template_index_row
        from vibecomfy.analysis.corpus import build_corpus_snapshot
        from vibecomfy.porting.simulate import _worker_environment
        from vibecomfy.testing.smoke_fixtures import available_fixtures

        assert Path(vibecomfy.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
        assert all(not Path(p).resolve().is_relative_to(Path(sys.argv[1]).resolve()) for p in sys.path if p)
        try:
            find_repo_root()
        except CheckoutRequiredError:
            pass
        else:
            raise AssertionError('installed wheel found a checkout')
        root = repo_ready_template_root()
        assert root.is_dir()
        template = Path('sample.py')
        template.write_text("READY_METADATA = {'template_id': 'sample'}\\n")
        assert 'diagnostics' in extract_ready_template_contract(template)
        assert _project_version() == '2.8.0'
        assert build_corpus_snapshot().templates_total > 0
        assert _worker_environment()['PYTHONHASHSEED'] == '0'
        assert 'speech_smoke.wav' in available_fixtures()
        assert _default_exception_path().is_file()
        assert load_strict_ready_exceptions()
        assert read_lockfile(resolve_lockfile_path())
        assert _template_index_row('audio/ace_step_1_5_t2a_song')['id'] == 'audio/ace_step_1_5_t2a_song'

        url = 'http://stub.invalid'
        calls = []
        class Client:
            server_url = url
            async def _post_prompt(self, prompt):
                assert prompt
                # This call occurs on the real run_sync execution path, before
                # queue acceptance. Neither function is mocked.
                assert session.current_source_revision() is None
                assert session.current_source_content_digest() is None
                calls.append('prompt')
                return {'prompt_id': 'accepted'}
            async def history(self, prompt_id):
                calls.append('history')
                return {prompt_id: {'status': {'status_str': 'success', 'completed': True, 'messages': []},
                                    'outputs': {'1': {'images': [{'filename': 'final.png', 'subfolder': '', 'type': 'output'}]}}}}
        class Artifacts:
            server_url = url
            async def download_artifacts(self, *, local_root):
                output = local_root / 'output' / 'final.png'
                output.parent.mkdir(parents=True)
                output.write_bytes(b'fake image bytes')
                calls.append('retrieved')
                return {'status': 'retrieved', 'local_root': str(local_root)}
        workflow = VibeWorkflow('installed', WorkflowSource('installed'))
        workflow.nodes['1'] = VibeNode('1', 'SaveImage', uid='save-image', inputs={'filename_prefix': 'installed'})
        workflow.outputs = [VibeOutput('1', 'SaveImage', name='final')]
        bundle = load_bundle(workflow)
        provider = SimpleNamespace(get_schema=lambda name: NodeSchema(name, None, {}, []), requires_fresh_target=True)
        record = bundle.compile(schema_provider=provider)
        result = run_sync(record, bundle, server_url=url, server_client=Client(), artifact_client=Artifacts(), schema_provider=provider)
        assert calls == ['prompt', 'history', 'retrieved'], calls
        assert Path(result.completion_path).is_file()
        assert Path(result.artifacts[0]['path']).is_file()
        assert json.loads((Path(result.metadata_path).parent / 'attempt.json').read_text())['prompt_id'] == 'accepted'
    ''')
    subprocess.run([str(python), "-I", "-c", script, str(ROOT)],
                   cwd=tmp_path, env=env, check=True, timeout=120)
