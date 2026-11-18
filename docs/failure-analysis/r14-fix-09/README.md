# R14-FIX-09: JSON workflow import boundary evidence

Packet: [astrid-dev #836](https://github.com/banodoco/astrid-dev/issues/836).
Pull request: [VibeComfy #177](https://github.com/banodoco/VibeComfy/pull/177).
The accepted packet and release authority are at astrid-dev
`b60132b7ac21164e4bf66d95ad8c8d4b5c37cac7`.

## Source identities and change

- Base: `c27fe76b79d917fd9c08246660bc77211be64146`, VibeComfy `release/14/main`.
- Before-proof checkpoint: `ea29d1ddddbc1d7d9ce525b1d90716ec4b0d695e`.
  Its product bytes match the base. It adds two official JSON regressions and
  per-test reporting, preserving the existing test file as an exact prefix.
- Product correction: `eacb092f2600298d926d5b2da4f749a59e998d54`.
  Its tree is `542af4059477cf4a6e7c470823927a90e64ea9c9`.
  Subsequent proof/reporting changes do not change these product or test bytes.
- Branch: `release/14/json-workflow-import` to `release/14/main`.
  The PR and mailbox handoff name the final head and hosted runs.

Normalization now imports UI classification from `vibecomfy.ui_constants`.
The canonical hashing primitives moved to a standard-library-only package
leaf. Their executable AST is identical to the old implementation, excluding
the module docstring. The old agent import path re-exports the same objects;
new identity assertions also bind the projection registry to that same owner.
Ingest snapshots use the shared leaf directly. The IR boundary checker is
unchanged. No existing test body, fixture, marker or assertion is modified.

## Local before/after proof

Environment: Linux, CPython 3.11.18; editable `.[dev]`, NumPy and Pillow.
No ComfyUI server or GPU is needed. The original before-proof test file was
run against base product bytes; the after selection used exactly the product
and test bytes in `eacb092f`.

Before command, exit 1:

```sh
python -m pytest -q -rA --tb=short tests/test_workflow_bundle_imports.py
```

[before-imports.log](before-imports.log) records ten existing passes and both
new official JSON cases failing on forbidden imports. Each case calls the
Agent entry point `vibecomfy.cli_loader.load_bundle` in a fresh interpreter.
The existing harness records attempted imports as well as loaded modules,
including descendants of `comfy_nodes`, `numpy`, `torch` and the emitter.

The baseline focused command, exit 1, ran these unchanged test files:

```sh
python -m pytest -q -rA --tb=short \
  tests/test_ingest_snapshot.py tests/test_m1_contracts.py \
  tests/test_b18_browser_contract.py tests/test_cli_loader.py
```

The after command, exit 1, added `tests/test_workflow_bundle_imports.py` to
that same focused selection. Results (with trailing whitespace stripped from pytest output) are in
[before-focused.log](before-focused.log) and [after-focused.log](after-focused.log).
All fourteen import tests pass after the correction.

The unchanged `env/baseline-diff.py` from the pinned astrid-dev revision
(blob `919e1b7440fa3627c16ef5b2879ba0d1b56b806e`) compared the two baseline
logs with the after log by test ID. Its exit was 0; the exact results are in
[local-comparison](local-comparison/summary.md):

| Comparison | Result |
|---|---:|
| Baseline IDs, including the two new regressions on base product | 115 |
| Candidate IDs | 117 |
| Regressions | 0 |
| Missing IDs | 0 |
| Fixed failures | 2 |
| Pre-existing failures | 3 |

The two extra candidate IDs prove the new neutral leaf is lightweight and
the compatibility exports retain shared object identity.

`PYTHONPATH=. python scripts/check_ir_boundary.py` exits 0 and prints
`IR boundary: clean` on both base and candidate.

## Loaded graph and digest preservation

[probe_json_load.py](probe_json_load.py) calls the real loader.
[Before](before-json-fingerprints.json) and [after](after-json-fingerprints.json)
records have identical source SHA-256, workflow identity, node and edge counts,
bundle semantic digest, snapshot semantic digest and source representation.
Only `forbidden_roots_loaded` changes: all three forbidden roots on base,
none on the candidate. The subprocess tests independently establish this
for each workflow in a fresh interpreter.

| Official source | Nodes | Edges | SHA-256 |
|---|---:|---:|---|
| `image/z_image.json` | 14 | 10 | `888c112fc224ca73a27273f5aed8fbe3fee411f219a709b65da206b31d445980` |
| `video/ltx2_3_t2v.json` | 48 | 68 | `0d6ea69dc57324ce3f53e3d69f81ecac19c7f71af977fe32506b50c82c03cbfa` |

## Existing failures and hosted qualification limits

These existing failures are retained and reported to Lead in
[mailbox BLOCKED 6990665727](https://github.com/banodoco/astrid-dev/issues/796#issuecomment-6990665727):

- `tests/test_cli_loader.py::test_raw_json_is_bound_import_evidence_and_cannot_be_rebundled_as_authority[raw-api.json-payload0]`
- `tests/test_cli_loader.py::test_raw_json_is_bound_import_evidence_and_cannot_be_rebundled_as_authority[raw-ui.json-payload1]`
- `tests/test_cli_loader.py::test_run_binds_public_inputs_without_mutating_candidate`

The first two observe `authored` provenance where the existing assertions
require `imported`; the third observes an extra `models_root` keyword.
Each fails identically on base and candidate. The pre-existing
`test_r5_mixed_ui_api_fixture_cannot_pair_representations_or_fabricate_removals`
XFAIL is also unchanged and still executes.

The exact-base [CI run 44189391582](https://github.com/banodoco/VibeComfy/actions/runs/44189391582)
passed all 32 import-boundary IDs on Ubuntu and Windows. Its main gate and
browser jobs have **NO-RESULT**: `make install-ci` cannot resolve
`runpod-lifecycle>=0.3.1.dev0,<0.4` from its configured package indexes.
The exact-base [canonical-parity run 44189391570](https://github.com/banodoco/VibeComfy/actions/runs/44189391570)
also has **NO-RESULT** for parity: root hygiene rejects the already tracked
`candidate-dependencies.json`, `draft_templates` and `vendor` first.

The existing workflows and assertions remain in force. The import-boundary
matrix now runs the unchanged IR checker directly, without depending on the
failing runtime installation. A separate Ubuntu/Windows comparison checks
the exact PR base and head, retains all snapshot/contract and CLI test IDs,
and uploads JUnit results. CLI failures keep their raw failing exits in their
own visible step; there is no `continue-on-error`, exit override or new skip.

This evidence establishes the scoped import fix and the shared tests'
before/after outcomes. It does not claim that the repository is all green.
Hosted outcomes and the final candidate commit are linked from the PR and
the packet's final mailbox submission. Integration and any Agent re-pin
remain with Lead.

Routes used: direct packet implementation; N for read-only CI inventory and
log collection. Independent review remains with Lead.
