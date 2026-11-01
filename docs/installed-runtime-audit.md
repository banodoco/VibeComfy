# Installed-runtime path audit

The wheel owns the ready corpus, model registry, Comfy metadata/version matrix,
object-info caches, edit schemas, demo descriptions, and custom-node web assets.
The wheel also packages the checkout's node lock, template index and strict-ready
exception manifest, because approval, contract reporting and validation read
those files. Runtime paths resolve these assets inside the package in a wheel.
A caller-supplied lockfile or workspace remains caller-owned.

Source identity is optional for ordinary sessions and unavailable without a
checkout. Required managed source attestation still rejects unavailable identity.
`utils.repo_relative_path`, `registry.ready` and `security.loader_provenance`
already have installed fallbacks. `comfy_nodes._git_info_snapshot` contains
missing Git and reports unavailable. `session._git_sha` is optional metadata
about the caller's working directory; other runtime Git calls inspect the
selected ComfyUI or third-party node-pack checkout, not the VibeComfy install.
Missing third-party Git identity is handled by drift/dependency policy; a pinned
checkout mutation intentionally requires that target to be a Git checkout.

The following paths are developer or corpus-maintenance operations, not invoked
by generation: `commands._checks.run_checks` scans the checkout itself;
`porting.readability_inventory` computes a repo-only inventory with checkout-
relative report paths; `commands.schemas._import_scenario_obligations` loads
the test harness for its comparison-manifest option; and
`porting.edit.grammar.sync_authoring_doc` edits a repository architecture note.
`commands.test` uses checkout snapshots only when testing a curated checkout;
user recipes work without them. `comfy_nodes.agent.fixture_provider` and demo
replay paths refer to test fixtures or recorded development runs, not normal
agent execution. `testing.smoke_fixtures` uses packaged media and explicitly
regenerates missing fixtures.
`search.bootstrap` and workflow indexes are workspace-generated data and tell
the user to sync sources when absent. `commands.runpod` prefers the installed
lifecycle distribution, with a sibling checkout as an optional development
fallback. `commands.runpod_setup` links the installed package's custom-node
directory as well as a checkout's. `comfy_nodes` and its worker add the package
parent for direct custom-node loading; this is site-packages in a wheel.

The template breadcrumb resolver reads packaged ready-template source files and
falls through to search if external source corpora are absent. The generated
node lock and template index command defaults that write workspace state remain
relative to the caller's workspace; they must not write into site-packages.
