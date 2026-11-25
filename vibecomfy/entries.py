"""Thin user entries over canonical imported workflow bundles."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

_ENTRY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_OUTPUT_KINDS = {
    "SaveImage": "image", "PreviewImage": "image", "SaveVideo": "video",
    "VHS_VideoCombine": "video", "SaveAudio": "audio", "SaveAudioMP3": "audio",
    "PreviewAudio": "audio", "VibeComfySaveTranscript": "audio", "SaveAnimatedWEBP": "video", "SaveWEBM": "video",
}
# Roles describe the loader, not an inferred catalog model. Target-side model
# resolution remains the generation backend's responsibility.
LOADER_ROLES = {
    "HunyuanFoleyModelLoader": "checkpoint", "LoadDACHunyuanVAE": "vae",
    "CheckpointLoaderSimple": "checkpoint", "UNETLoader": "diffusion_model",
    "UnetLoaderGGUF": "diffusion_model", "WanVideoModelLoader": "diffusion_model",
    "CLIPLoader": "text_encoder", "DualCLIPLoader": "text_encoder",
    "DualCLIPLoaderGGUF": "text_encoder", "LoadWanVideoT5TextEncoder": "text_encoder",
    "VAELoader": "vae", "VAELoaderKJ": "vae", "WanVideoVAELoader": "vae",
    "LoraLoader": "lora", "LoraLoaderModelOnly": "lora", "ControlNetLoader": "controlnet",
    "CLIPVisionLoader": "vision_encoder", "LatentUpscaleModelLoader": "upscaler",
}

_MEDIA_LOADER_FIELDS = {
    ("LoadImage", "image"): "image",
    ("LoadAudio", "audio"): "audio",
    ("LoadVideo", "file"): "video",
    ("VHS_LoadVideo", "video"): "video",
    ("VHS_LoadVideoFFmpeg", "video"): "video",
}


def media_loader_kind(class_type: str, field: str) -> str | None:
    """Return the media kind of a known filename picker."""
    return _MEDIA_LOADER_FIELDS.get((class_type, field))


def entries_dir() -> Path:
    return Path(os.environ.get("VIBECOMFY_ENTRIES_DIR", "~/.vibecomfy/entries")).expanduser()


def _validate(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict) or set(manifest) != {"id", "kind", "modes", "bundle", "needs", "binds", "defaults"}:
        raise ValueError("entry must contain exactly id, kind, modes, bundle, needs, binds and defaults")
    if not isinstance(manifest["id"], str) or not _ENTRY_ID.fullmatch(manifest["id"]):
        raise ValueError("invalid entry id")
    if manifest["kind"] not in {"image", "video", "audio"}:
        raise ValueError("invalid entry kind")
    modes = manifest["modes"]
    allowed = {"image": {"t2i", "i2i", "edit", "inpaint", "outpaint", "upscale"}, "video": {"t2v", "i2v", "flf", "v2v", "video-edit"}, "audio": {"tts", "music", "sfx", "transcribe"}}
    if not isinstance(modes, list) or any(not isinstance(m, str) or m not in allowed[manifest["kind"]] for m in modes) or len(set(modes)) != len(modes):
        raise ValueError("invalid entry modes")
    if not isinstance(manifest["bundle"], str) or not manifest["bundle"].strip():
        raise ValueError("entry bundle must be a path")
    if not isinstance(manifest["needs"], list) or not all(isinstance(n, dict) for n in manifest["needs"]):
        raise ValueError("entry needs must be a list of objects")
    if not isinstance(manifest["binds"], dict) or not all(isinstance(k, str) and k and ((isinstance(v, str) and v) or (isinstance(v, dict) and set(v) == {"node", "field"} and all(isinstance(x, str) and x for x in v.values()))) for k, v in manifest["binds"].items()):
        raise ValueError("entry binds must map names to public inputs or node/field targets")
    if not isinstance(manifest["defaults"], dict):
        raise ValueError("entry defaults must be an object")
    return manifest


def load_entry(path: str | Path) -> dict[str, Any]:
    path = Path(path).expanduser()
    if path.is_dir():
        path = path / "entry.json"
    manifest = _validate(json.loads(path.read_text(encoding="utf-8"))).copy()
    bundle = Path(manifest["bundle"]).expanduser()
    manifest["bundle"] = str((path.parent / bundle).resolve())
    return manifest


def discover_entries(directory: str | Path | None = None) -> list[dict[str, Any]]:
    root = Path(directory).expanduser() if directory is not None else entries_dir()
    return [load_entry(path) for path in sorted(root.glob("*/entry.json"))]


def infer_output_kind(workflow: Any) -> str:
    """Infer the artifact kind from output nodes, ignoring auxiliary previews."""
    nodes = list(workflow.runtime_nodes().values())
    kinds = {_OUTPUT_KINDS[node.class_type] for node in nodes if node.class_type in _OUTPUT_KINDS and not node.class_type.startswith("Preview")}
    if not kinds:
        kinds = {_OUTPUT_KINDS[node.class_type] for node in nodes if node.class_type in _OUTPUT_KINDS}
    if len(kinds) != 1:
        raise ValueError(f"workflow output kind is ambiguous or unknown: {sorted(kinds)}")
    return kinds.pop()


def draft_entry(workflow: Any, entry_id: str, *, bundle: str = "bundle", input_ambiguities: dict[str, list[dict[str, str]]] | None = None) -> dict[str, Any]:
    kind = infer_output_kind(workflow)
    # InputSpec and its aliases are the source of binding names; translation
    # to catalog options is owned by the generation catalog.
    binds = {name: name for name, item in workflow.inputs.items() if name == item.name}
    for name in input_ambiguities or {}:
        binds.pop(name, None)
    has_image = "image" in (input_ambiguities or {}) or any(name in binds or any(name in i.aliases for i in workflow.inputs.values()) for name in ("image", "input_image"))
    has_video = "video" in (input_ambiguities or {}) or any(name in binds or any(name in i.aliases for i in workflow.inputs.values()) for name in ("video", "input_video"))
    transcribe = any(node.class_type == "VibeComfySaveTranscript" for node in workflow.runtime_nodes().values())
    modes = (["transcribe"] if transcribe else []) if kind == "audio" else [{"image": "edit" if has_image else "t2i", "video": "v2v" if has_video else "i2v" if has_image else "t2v"}[kind]]
    from vibecomfy.model_assets import _referenced_model_values
    needs = []
    if kind == "audio" and not transcribe:
        needs.append({"role": None, "code": "audio_mode_unknown",
                      "ambiguity": "audio mode is unknown; choose tts, music, sfx, or transcribe"})
    needs.extend({"role": None, "ambiguity": f"multiple targets for {name}", "candidates": candidates} for name, candidates in (input_ambiguities or {}).items())
    for reference in _referenced_model_values(workflow, include_unresolved=True):
        role = LOADER_ROLES.get(reference["class_type"])
        if reference.get("unresolved") or (role is None and reference["field"] == "model_name"):
            needs.append({**reference, "role": role, "unresolved": True})
        else:
            needs.append({**reference, "role": role, **({"ambiguity": "unknown loader role"} if role is None else {})})
    return _validate({"id": entry_id, "kind": kind, "modes": modes, "bundle": bundle, "needs": needs, "binds": binds, "defaults": {}})


def entry_added_node_refs(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Read earlier explicit --add declarations from the current canonical entry.

    These rows are source requirements, never evidence of consent. The Agent
    uses this same read boundary for replacement preflight and publication.
    Do not copy every inferred pack from the old graph into a new graph.
    """
    from vibecomfy.security.provenance import Provenance
    from vibecomfy.workflow_bundle import load_bundle

    workflow = load_bundle(Path(entry["bundle"]) / "workflow.py",
                           trust=Provenance.USER_CONFIRMED).workflow
    return [dict(ref) for ref in workflow.requirements.custom_node_refs
            if ref.get("entry_add") is True]


def merge_entry_added_node_refs(
    retained: Iterable[Mapping[str, Any]], additions: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """An explicit replacement supersedes only matching retained declarations.

    Both entry publication and Agent preflight use this selection. New
    declarations are never merged with each other here: the canonical ref
    validator still rejects conflicting new pins or conflicts with authored
    source requirements. This is selection of source intent, not approval.
    """
    incoming = [dict(ref) for ref in additions]

    def repository(ref: Mapping[str, Any]) -> str:
        url = ref.get("url")
        return url.rstrip("/").removesuffix(".git") if isinstance(url, str) else ""

    slugs = {ref.get("slug") for ref in incoming if ref.get("slug")}
    repositories = {repo for ref in incoming if (repo := repository(ref))}
    return [
        dict(ref) for ref in retained
        if ref.get("slug") not in slugs and repository(ref) not in repositories
    ] + incoming


def import_as_entry(source: str | Path, entry_id: str, directory: str | Path | None = None, *, replace: bool = False, add: Iterable[str] = (),
                    added_node_refs: Iterable[Mapping[str, Any]] = (),
                    before_publish: Callable[[dict[str, Any], Path], None] | None = None) -> dict[str, Any]:
    """Import a complete bundle; explicitly replace an entry by swapping its manifest.

    The optional caller hook receives the loaded, unpublished entry and its
    revision directory (including entry.json). It may validate the actual
    bundle and write revision-local sidecars. Any exception aborts publication.
    Every new replacement uses revision-v2-* and retains its local entry.json,
    including imports with no hook. Historical revisions are never migrated.
    The entry directory and older bundle paths stay intact for readers that
    already loaded the old manifest. Retiring those bundles requires separate
    reader-aware cleanup; never remove them during publication.
    """
    from vibecomfy.custom_node_refs import apply_added_node_refs, resolve_added_node_refs
    from vibecomfy.porting.import_service import import_workflow_bytes
    from vibecomfy.security.provenance import Provenance
    from vibecomfy.workflow_bundle import emit_bundle, load_bundle

    if not isinstance(entry_id, str) or not _ENTRY_ID.fullmatch(entry_id):
        raise ValueError("invalid entry id")
    root = Path(directory).expanduser() if directory is not None else entries_dir()
    destination = root / entry_id
    replacing = destination.exists() or destination.is_symlink()
    retained_refs = []
    if replacing:
        if not replace:
            raise FileExistsError(f"entry already exists: {destination}")
        entry_file = destination / "entry.json"
        if destination.is_symlink() or not destination.is_dir() or entry_file.is_symlink() or not entry_file.is_file():
            raise FileExistsError(f"not a replaceable entry: {destination}")
        previous = load_entry(entry_file)
        if previous["id"] != entry_id:
            raise ValueError(f"entry id does not match destination: {destination}")
        retained_refs = entry_added_node_refs(previous)
    source_path = Path(source).expanduser()
    is_json = source_path.is_file() and source_path.suffix.lower() == ".json"
    # Agent preflight may supply its already-resolved declarations so the
    # approved identity is exactly the one written, even if a branch moved.
    refs = merge_entry_added_node_refs(retained_refs, [*added_node_refs, *resolve_added_node_refs(add)])
    artifacts = import_workflow_bytes(source_path.read_bytes(), workflow_id=entry_id, infer_inputs=True,
                                      added_node_refs=refs) if is_json else None
    root.mkdir(parents=True, exist_ok=True)
    # Keep a new revision's entry.json out of discover_entries' */entry.json
    # scan until the entire directory is published. Replacements are already
    # one level below the discovered entry directory.
    staging_parent = None if replacing else Path(tempfile.mkdtemp(prefix=".entry-stage-", dir=root))
    staging = (Path(tempfile.mkdtemp(prefix="revision-v2-", dir=destination))
               if replacing else staging_parent / entry_id)
    published = False
    try:
        if not replacing:
            staging.mkdir()
        folder = staging / "bundle"
        folder.mkdir()
        if artifacts is not None:
            (folder / "workflow.py").write_bytes(artifacts.python_bytes)
            (folder / "workflow.vibe.json").write_bytes(artifacts.companion_bytes)
            (folder / "source.json").write_bytes(artifacts.source_bytes)
        else:
            canonical = load_bundle(source_path, trust=Provenance.USER_CONFIRMED)
            apply_added_node_refs(canonical.workflow, refs)
            emit_bundle(canonical.workflow, folder / "workflow.py", canonical.provenance)
        workflow = load_bundle(folder / "workflow.py", trust=Provenance.USER_CONFIRMED).workflow
        manifest = draft_entry(workflow, entry_id, bundle="bundle", input_ambiguities=artifacts.report.get("input_ambiguities") if artifacts else None)
        (staging / "entry.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if before_publish is not None:
            before_publish(load_entry(staging), staging)

        # This is the only commit point. The replacement manifest selects the
        # complete immutable revision, including any revision-local sidecars.
        if replacing:
            manifest["bundle"] = f"{staging.name}/bundle"
            # Every new v2 revision retains its local manifest as the sidecar
            # anchor. Direct callers write no approvals; they must not inherit
            # the root or any earlier revision's approvals.
            publication = staging / ".publish-entry.json"
            publication.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            os.replace(publication, destination / "entry.json")
        else:
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(f"entry already exists: {destination}")
            os.rename(staging, destination)
        published = True
    finally:
        if staging_parent is not None:
            shutil.rmtree(staging_parent)
        elif not published:
            shutil.rmtree(staging)
    return load_entry(destination)
