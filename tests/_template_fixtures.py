"""Keep graph regressions for templates intentionally removed from discovery."""
from pathlib import Path

from vibecomfy.registry.ready import ready_template_discovery, ready_template_ids, workflow_from_ready


ROOT = Path(__file__).resolve().parents[1]


def template_fixture_path(template_id: str) -> Path:
    ready = ROOT / 'ready_templates' / f'{template_id}.py'
    draft = ROOT / 'draft_templates' / f'{template_id}.py'
    if draft.is_file():
        assert not ready.exists()
        assert template_id not in ready_template_ids()
        return draft
    return ready


def workflow_from_template_fixture(template_id: str, *, _discovery=None):
    """Load the same graph fixture while proving drafts stay unlisted."""
    if _discovery is not None:
        return workflow_from_ready(template_id, _discovery=_discovery)
    path = template_fixture_path(template_id)
    if path.is_relative_to(ROOT / 'draft_templates'):
        discovery = ready_template_discovery(roots=[ROOT / 'draft_templates'], include_json_references=False)
        return workflow_from_ready(template_id, _discovery=discovery)
    return workflow_from_ready(template_id)


def load_template_fixture_bundle(template_id: str):
    from vibecomfy.security.provenance import Provenance
    from vibecomfy.workflow_bundle import load_bundle

    path = template_fixture_path(template_id)
    if path.is_relative_to(ROOT / 'draft_templates'):
        # These are the same checked-in fixtures formerly trusted as built-ins.
        return load_bundle(path, trust=Provenance.USER_CONFIRMED)
    return load_bundle(template_id)


def template_fixture_ids() -> tuple[str, ...]:
    drafts = {path.relative_to(ROOT / 'draft_templates').with_suffix('').as_posix()
              for path in (ROOT / 'draft_templates').glob('*/*.py')}
    assert drafts.isdisjoint(ready_template_ids())
    return tuple(sorted(set(ready_template_ids()) | drafts))
