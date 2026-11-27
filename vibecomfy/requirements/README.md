# Canonical workflow requirements plan

`vibecomfy.requirements.plan` is the P90 desired-state producer used by Agent
preview and apply orchestration. It returns ordinary JSON data and does not
install anything, publish an entry, save approval records or create grants.

```python
from vibecomfy.requirements import plan, plan_digest

preview = plan(
    workflow_file_or_entry,
    target={
        "root": selected_engine_root,
        "python": selected_python,
        "comfyui_root": selected_comfyui_root,
        "models_root": selected_models_root,
        "custom_nodes_root": selected_custom_nodes_root,
        "placement_class": "local",  # local, attached or runpod
        "location": "local",
        "owner": "astrid",
        "capacity_bytes": None,
    },
    add=["https://github.com/owner/pack.git@ref"],
    add_models=["checkpoints/model.safetensors=https://host/model#<64-hex-sha256>"],
    added_node_refs=[],
    approvals=[],
)
assert preview["digest"] == plan_digest(preview)
```

## Input ownership

The Agent selects the target through its existing authority. `root` can be an
engine root and is not assumed to be the ComfyUI checkout. Pass actual resolved
subdirectories from the selected recipe/receipt. Unknown paths stay absent or
null. The planner never substitutes its own model directory, interpreter or
`COMFYUI_PATH`. The final Python symlink is retained, so a venv remains distinct
from the system interpreter; executable bytes are observed separately.

FILE accepts JSON or an already built `VibeWorkflow`. ENTRY accepts an entry
directory, `entry.json`, or an existing entry ID. **The planner never executes
Python workflow code.** For Python files and Python-backed entries, a consumer
that has already admitted and built that exact bundle through the existing
workflow authority passes `workflow=that_workflow`. The plan binds both its
semantic projection and the actual source/companion/entry bytes. Without that
admitted object it returns `workflow_code_not_admitted`, an unapproved gap,
with no requirements/actions. It does not grant confirmation or use entry
publication as a loader. The consumer must not load arbitrary Python as a
side effect of an otherwise read-only preview.

`added_node_refs` accepts the existing resolved `--add` shape (`slug`, `source`,
`url`, full `commit`, optional `requirements_txt` and ordered `pip_no_deps`).
The existing resolver freezes branch/tag declarations to a full commit. A
source's exact Git tree supplies class/dependency evidence; a repository name
alone is not evidence of implemented classes. No catalog entry is created.

`add_models` also accepts canonical model records with `name`, `subdir`, `url`,
`sha256` and `size_bytes`. `target_path` retains its existing, distinct meaning:
a file under `custom_nodes/<pack>/...` relative to the selected ComfyUI root.
It is not an alias for a path under the models root. Invalid or conflicting
destinations are explicit blocked gaps.

## Returned JSON

The required keys are `requirements`, `gaps`, `bytes`, and `digest`. Additional
`schema`, `workflow`, `target`, `target_observed`, `inputs`, and `actions` make
every bound input reviewable. Each item has its source identity, size,
destination, actual observation, approval state and intended action.

Node items retain the exact closed P56 `node` shape alongside the canonical
recipe hash, selected dependency declarations, source-tree records and
`install_py` evidence. Shipped lock rows and effective legacy pip dependencies
remain bound; installer directory names are preserved even when they differ
from the repository basename. The controlled installer remains the apply
owner. Finding an `install.py` always produces `run: false`/`install_py: never`.

Dependencies selected by `requirements_txt` are separate from pyproject
metadata. Floating or unresolved package artifacts remain
`package_resolution_unknown`. Repository commits and artifact hashes are not
guessed. Installed code is not proof that its interpreter dependencies are
ready: until the consumer supplies its qualified dependency path, the plan
reports `package_observation_unknown`. A plan containing those gaps must not
be offered as executable. This producer does not introduce a package solver.

`gaps` use `blocked`, `unknown`, `timeout` or `unapproved`, with `who` and the
affected requirement. They are not successful readiness states. `actions`
describe intent for the existing consumer; their presence never authorizes
execution or means a public apply command has landed.

`bytes.download` is null if any pending requirement has unknown transfer size;
`known_download` is only a subtotal. `checkout_bytes` is source blob bytes,
not clone traffic, wheel expansion, disk peak or a capacity estimate. Actual
target `capacity_bytes` and measured `required_disk_bytes`, if supplied by the
transfer owner, are separately bound. No hard-link probe or disk-write test is
performed. Missing capacity/peak information stays unknown. Model-only no-ops
need zero additional bytes but do not fabricate available capacity.

## Approval and digest

`approvals` contains existing P56 records supplied through the Agent authority.
The existing `approval_record`, `approval_matches` and `consent_token` functions
remain canonical. The planner reports `needs_approval`, `reviewed`, or
`record_matches`, preserving the exact `code=<token>` warning data. A matching
record proves consistency, not current actor authorization;
`runtime_grant: not_observed` is explicit. The planner has no grant API,
transport, ledger or persistence path.

The digest is SHA-256 of `vibecomfy.requirements-plan.v1`, a NUL byte, and the
sorted compact ASCII JSON of the entire returned object excluding `digest`.
It binds exact workflow members and semantics, selected roots/interpreter and
recipe, source/commit/tree/dependency files, ordered package recipe, item
destinations, observations, approval inputs and planned actions. Dictionary
insertion order is irrelevant. There are no current timestamps or temp paths.
Identical bound state produces identical bytes/digest. A changed bound field
invalidates the previous digest.

Apply must obtain fresh selected-target/source/approval observations, recompute
this same producer, compare the requested digest, and re-read the existing
actor-scoped Runtime grant authority before writing. It must not treat this
preview, its record match, a cached hash, or a generic app-state write as a
grant. P90 WS3 owns that orchestration; P94 owns transfer/environment checks.
Paid/remote application is outside this producer closure.

## Proof and golden fixtures

The production Git reader fetches into an isolated temporary bare repository,
verifies commit/tree/blob identities and reads declarations without checking
out or importing source. Local target observers hash real model/executable
bytes and read Git state with optional locks, hooks and fsmonitor disabled.
Configured content filters or redirected worktrees refuse observation before
status can execute them. Installer sentinels are bound without cleanup.

`tests/fixtures/requirements/README.md` identifies the canonical SAM and local
model fixtures, source provenance, complete expected JSON and portable review
digests. The latter are not real-target apply tokens. `source_inspector` is an
injected read seam used by recorded tests; its callable accepts `repo`, full
`commit` and optional keyword `requirements_txt`. Production uses the real
exact-tree reader.

Run from the complete checkout with the pinned Dev runner:

```sh
bash "$DEV/env/vc-setup.sh"
bash "$DEV/env/vc-pytest.sh" \
  tests/test_pack_resolver.py tests/test_model_assets.py \
  tests/test_node_restore_approval.py tests/test_entry_publication_transaction.py \
  tests/test_requirements_plan.py tests/test_requirements_plan_golden.py \
  tests/test_requirements_sources.py tests/test_requirements_observation.py
```

Run the original four files on the exact accepted base as well. Record complete
source identities, import origins, frozen dependencies, full diff, collected
counts and exits. Author CPU proof does not replace the assigned native
custodian or RS1 acceptance, packaged-tuple proof, or physical SAM execution.
