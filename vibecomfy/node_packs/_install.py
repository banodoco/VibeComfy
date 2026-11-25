from __future__ import annotations
import contextvars
import hashlib
import importlib.metadata
import importlib.util, json, os, re, shutil, socket, subprocess, sys, tempfile, time
import logging
import shlex
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Protocol, Sequence
from urllib.parse import urlparse
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from packaging.requirements import InvalidRequirement, Requirement
from ._defs import CustomNodePack, get_known_node_packs, resolve_node_packs, unresolved_class_types
from ._lockfile import LockEntry, upsert_lockfile_entry
from vibecomfy.registry.pack_resolver import PackNotFoundError, PackRef

# resolve_pack is imported lazily inside install_pack() so that monkeypatching
# vibecomfy.node_packs.resolve_pack correctly affects install_pack behaviour.
from vibecomfy.security.gate import current_gate_context, require_confirmation, requesting_provenance
from vibecomfy.workflow import VibeWorkflow
InstallStatus = Literal["installed", "refreshed", "skipped_dirty", "failed"]
InstallWitnessState = Literal["clean", "patched", "dirty", "missing", "incomplete", "unknown"]
DEFAULT_INSTALL_ROOT = Path("custom_nodes")  # Canonical install root for custom node packs.
INSTALL_STATE_DIR = ".vibecomfy-install-state"
SENTINEL_LEASE_SECONDS = 1800  # 30 minutes
_ACTIVE_PIP_CONSTRAINT: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "vibecomfy_active_pip_constraint", default=None
)
_ACTIVE_RUNTIME_REQUIREMENTS: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "vibecomfy_active_runtime_requirements", default=()
)


def default_install_root() -> Path:
    """Return the canonical install root for custom node packs.

    When the local-library ``custom_nodes`` slot is configured (via env var
    or TOML) the configured path is returned.  Otherwise falls back to the
    repo-relative ``custom_nodes`` directory.
    """
    from vibecomfy.local_library import Slot, resolved_path

    configured = resolved_path(Slot.custom_nodes)
    return configured if configured is not None else Path("custom_nodes")
CORE_COMFY_CLASSES = frozenset(
    {
        # core Comfy built-ins (original)
        "CFGGuider",
        "CLIPLoader",
        "CLIPTextEncode",
        "DualCLIPLoader",
        "ImageScaleBy",
        "KSamplerSelect",
        "LoadImage",
        "LoraLoaderModelOnly",
        "ManualSigmas",
        "PrimitiveBoolean",
        "PrimitiveFloat",
        "PrimitiveStringMultiline",
        "RandomNoise",
        "SamplerCustomAdvanced",
        "SaveImage",
        "UNETLoader",
        "VAEDecodeTiled",
        "VAELoader",
        # core Comfy built-ins confirmed from comfy_core / comfy_extras object_info snapshots
        "AudioConcat",
        "AudioEncoderEncode",
        "AudioEncoderLoader",
        "BasicScheduler",
        "CheckpointLoaderSimple",
        "ComfyMathExpression",
        "ComfySwitchNode",
        "ConditioningZeroOut",
        "CreateVideo",
        "EmptyAceStep1.5LatentAudio",
        "EmptyAudio",
        "EmptyImage",
        "GetVideoComponents",
        "ImageBlend",
        "ImageBatchExtendWithOverlap",
        "ImageBatchMulti",
        "KSampler",
        "LoadAudio",
        "LoadVideo",
        "LoadVideosFromFolder",
        "LTXVAddGuideMulti",
        "LTXVAudioVAEEncode",
        "LTXVGemmaCLIPModelLoader",
        "LTXVImgToVideoConditionOnly",
        "LTXVImgToVideoInplace",
        "LTXVLatentUpsampler",
        "LTXVPreprocessMasks",
        "LTXVSetVideoLatentNoiseMasks",
        "MaskPreview",
        "MaskToImage",
        "ModelSamplingAuraFlow",
        "ModelSamplingSD3",
        "NormalizeAudioLoudness",
        "PreviewAudio",
        "PreviewImage",
        "PrimitiveInt",
        "PrimitiveNode",
        "PrimitiveString",
        "Reroute",
        "ResizeImageMaskNode",
        "SaveAudioMP3",
        "SaveVideo",
        "SetLatentNoiseMask",
        "SimpleMath+",
        "SolidMask",
        "StringConcatenate",
        "TextEncodeAceStepAudio1.5",
        "TextGenerateLTX2Prompt",
        "TrimAudioDuration",
        "VAEDecode",
        "VAEDecodeAudio",
        "VAEEncode",
        "VRAM_Debug",
    }
)
class Runner(Protocol):
    def __call__(self, args: Sequence[str], *, check: bool, capture_output: bool, text: bool, cwd: str | Path | None = None) -> subprocess.CompletedProcess[str]: ...
@dataclass(frozen=True)
class InstallResult: name: str; status: InstallStatus; git_commit_sha: str | None; error: str | None; verified_patches: int = 0
@dataclass(frozen=True)
class PipPreflightResult:
    ok: bool
    packages: tuple[str, ...] = ()
    unsupported: bool = False
    error: str | None = None
@dataclass(frozen=True)
class InstallBatchResult:
    ok: bool
    results: tuple[InstallResult, ...]
    preflight: PipPreflightResult

    @property
    def preflight_unsupported(self) -> bool:
        return self.preflight.unsupported


@dataclass(frozen=True)
class PackInstallState:
    """Bounded state of one selected installed pack for realization witnesses."""

    install_root: Path | None
    path: Path | None
    expected_head: str | None
    observed_head: str | None
    state: InstallWitnessState
@dataclass(frozen=True)
class _InstallSentinel:
    path: Path
    unreadable: bool = False
    live_owner_pid: int | None = None

    @property
    def incomplete(self) -> bool:
        return self.path.exists() or self.unreadable

    @property
    def reason(self) -> str:
        if self.live_owner_pid is not None:
            return (
                f"incomplete install sentinel for {self.path.stem} is owned by active"
                f" process pid={self.live_owner_pid}: {self.path}"
            )
        if self.unreadable:
            return f"incomplete install sentinel for {self.path.stem} is corrupt or unreadable: {self.path}"
        return f"incomplete install sentinel is present: {self.path}"

    def write(self, *, phase: str, name: str, repo_url: str, install_dir: Path, git_commit_sha: str | None = None, error: str | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "name": name,
            "repo_url": repo_url,
            "install_dir": str(install_dir),
            "phase": phase,
            "complete": False,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "timestamp": time.time(),
        }
        if git_commit_sha is not None:
            payload["git_commit_sha"] = git_commit_sha
        if error is not None:
            payload["error"] = error
        tmp = self.path.with_name(f".{self.path.name}.{id(payload)}.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

def _resolve_cm_cli(install_root: Path, runner: Runner) -> list[str] | None:
    script = install_root / "ComfyUI-Manager" / "cm-cli.py"; sibling = Path(sys.executable).with_name("cm-cli"); found = shutil.which("cm-cli")
    module = [sys.executable, "-m", "comfyui_manager.cm_cli"] if importlib.util.find_spec("comfyui_manager") and importlib.util.find_spec("comfyui_manager.cm_cli") else None
    return next((argv for argv in ([sys.executable, str(script)] if script.exists() else None, [str(sibling)] if sibling.exists() else None, [found] if found else None, module) if argv), None)
def install_pack(
    *,
    name: str | None = None,
    repo: str | None = None,
    force: bool = False,
    install_root: Path | None = None,
    lockfile_path: Path = Path("custom_nodes.lock"),
    runner: Runner = subprocess.run,
    cm_cli_resolver: Callable[[Path, Runner], list[str] | None] = _resolve_cm_cli,
    pack_ref: PackRef | None = None,
    checkout_ref: str | None = None,
    expected_commit: str | None = None,
    allow_source_change: bool = False,
    resolve_latest: bool = False,
) -> InstallResult:
    """Install a pack; an omitted lock path writes the cwd's target lock."""
    from vibecomfy import resources

    if name is None and repo is None: raise ValueError("install_pack requires either name or repo")
    try:
        resources.require_writable_node_lock(lockfile_path)
    except ValueError as exc:
        return InstallResult(name or _pack_name_from_repo(repo or ""), "failed", None, str(exc))
    if install_root is None:
        install_root = default_install_root()
    pack = _pack_by_name(name) if name is not None else None
    resolved_ref: PackRef | None = None
    if pack is None and repo is None and name is not None:
        try:
            from vibecomfy.node_packs import resolve_pack  # see module-level comment

            resolved_ref = pack_ref or resolve_pack(name).ref
        except PackNotFoundError as exc:
            raise ValueError(f"unknown custom node pack {name!r}; pass repo to install an uncatalogued pack") from exc
        repo = resolved_ref.url
    elif pack_ref is not None:
        resolved_ref = pack_ref
    if pack is None and repo is None: raise ValueError(f"unknown custom node pack {name!r}; pass repo to install an uncatalogued pack")
    pack_name = name or _pack_name_from_repo(repo or "")
    if not pack_name: raise ValueError(f"could not infer custom node pack name from repo {repo!r}")
    if resolved_ref is not None and not resolved_ref.slug:
        resolved_ref = _pack_ref_with_slug(resolved_ref, pack_name)
    # An authored ref is authoritative for its source URL, including for a
    # catalogued pack.  Falling back to the catalog here silently discarded
    # requirements.custom_node_refs[].url.
    repo_url = repo or (resolved_ref.url if resolved_ref is not None else None) or (pack.repo if pack is not None else None)
    if repo_url is None: raise ValueError(f"missing repo URL for custom node pack {pack_name!r}")
    install_dir = install_root / pack_name
    sentinel = _install_sentinel(install_root, pack_name)
    if _has_incomplete_install(sentinel): return InstallResult(pack_name, "failed", None, sentinel.reason)
    if install_dir.exists():
        return _refresh_existing(
            pack_name,
            repo_url,
            install_dir,
            force,
            lockfile_path,
            runner,
            pack=pack,
            pack_ref=resolved_ref,
            checkout_ref=checkout_ref,
            expected_commit=expected_commit,
            allow_source_change=allow_source_change or pack_ref is not None,
            resolve_latest=resolve_latest or (pack_ref is not None and checkout_ref is None),
            sentinel=sentinel,
        )
    cm_cli_argv = cm_cli_resolver(install_root, runner)
    # S4 capability fence: gate AFTER parameter validation (name/repo lookup,
    # cm-cli path detection, directory-exists check) and BEFORE any subprocess
    # call (cm-cli install / git clone / pip install). Refusal raises
    # CapabilityFenceError before any process is spawned.
    require_confirmation(
        operation="install_pack",
        class_type=None,
        provenance=requesting_provenance.get(),
        capabilities=frozenset({"code_exec", "network", "filesystem_write"}),
        details={"name": pack_name, "repo": repo_url},
        ctx=current_gate_context(),
    )
    sentinel.write(phase="start", name=pack_name, repo_url=repo_url, install_dir=install_dir)
    if cm_cli_argv is None or checkout_ref is not None or expected_commit is not None or resolve_latest:
        return _install_pack_via_clone(
            pack_name,
            repo_url,
            pack,
            install_dir,
            lockfile_path,
            runner,
            pack_ref=resolved_ref,
            checkout_ref=checkout_ref,
            expected_commit=expected_commit,
            sentinel=sentinel,
        )
    try:
        sentinel.write(phase="cm_cli", name=pack_name, repo_url=repo_url, install_dir=install_dir)
        runner([*cm_cli_argv, "install", pack_name], check=True, capture_output=True, text=True, cwd=install_root.parent)
    except (OSError, subprocess.CalledProcessError):
        return _install_pack_via_clone(
            pack_name,
            repo_url,
            pack,
            install_dir,
            lockfile_path,
            runner,
            pack_ref=resolved_ref,
            checkout_ref=checkout_ref,
            expected_commit=expected_commit,
            sentinel=sentinel,
        )
    if not (install_dir / ".git").exists():
        return _install_pack_via_clone(
            pack_name,
            repo_url,
            pack,
            install_dir,
            lockfile_path,
            runner,
            pack_ref=resolved_ref,
            checkout_ref=checkout_ref,
            expected_commit=expected_commit,
            sentinel=sentinel,
        )
    _, checkout_error = _checkout_ref_and_verify(
        pack_name,
        repo_url,
        install_dir,
        checkout_ref,
        expected_commit,
        runner,
        sentinel=sentinel,
        fetch=False,
    )
    if checkout_error is not None:
        return InstallResult(pack_name, "failed", None, checkout_error)
    return _finalize_install(
        pack_name, repo_url, install_dir, lockfile_path, runner,
        pack=pack, pack_ref=resolved_ref, expected_commit=expected_commit, sentinel=sentinel,
    )


def _replacement_status(install_dir: Path, runner: Runner) -> list[str] | None:
    """Return status records that cannot be discarded during replacement.

    Only ignored Python bytecode is regenerable. Never exempt tracked changes
    or non-ignored files, even if their names look like bytecode.
    """
    try:
        porcelain = _git_porcelain(install_dir, runner, include_ignored=True)
    except UnicodeError:
        return None
    if porcelain is None:
        return None
    protected = []
    for record in porcelain.split("\0"):
        if not record:
            continue
        if record.startswith("!! "):
            relative = record[3:]
            if relative.endswith((".pyc", ".pyo")):
                path = install_dir / relative
                try:
                    if not path.is_symlink() and path.is_file():
                        continue
                except OSError:
                    pass  # Uninspectable paths remain protected.
        protected.append(record)
    return protected


def _replacement_refusal(name: str, install_dir: Path, runner: Runner) -> InstallResult | None:
    # A normal dirty check deliberately excludes ignored files (including for
    # same-pin patch verification). A destructive replacement cannot do that.
    protected = _replacement_status(install_dir, runner)
    if protected == []:
        return None
    head = _git_head(install_dir, runner)
    if protected is None:
        return InstallResult(name, "failed", head,
                             f"conflict: failed to inspect git status including ignored files for {install_dir}; replacement refused")
    ignored = [record[3:] if record[3:].isprintable() else repr(record[3:])
               for record in protected if record.startswith("!! ")]
    if ignored:
        return InstallResult(name, "skipped_dirty", head,
                             f"conflict: {install_dir} contains ignored user data: {', '.join(ignored)}; "
                             "move these paths to a safe location outside the checkout, then retry")
    return InstallResult(name, "skipped_dirty", head,
                         f"conflict: {install_dir} has uncommitted changes; replacement refused")


def _install_pack_via_clone(
    name: str,
    repo_url: str,
    pack: CustomNodePack | None,
    install_dir: Path,
    lockfile_path: Path,
    runner: Runner,
    *,
    pack_ref: PackRef | None = None,
    checkout_ref: str | None = None,
    expected_commit: str | None = None,
    sentinel: _InstallSentinel | None = None,
    restore_entry: LockEntry | None = None,
    replace_existing: bool = False,
) -> InstallResult:
    sentinel = sentinel or _install_sentinel(install_dir.parent, name)
    # Both explicit Git installs and approved restores use the same checkout
    # transaction. Staging is a sibling of the resolved search root so the
    # final publication is a same-filesystem rename, never a copy.
    root = install_dir.parent.resolve()
    if root == root.parent:
        return InstallResult(name, "failed", None, "cannot stage node install outside the install root")
    if replace_existing and (refusal := _replacement_refusal(name, install_dir, runner)) is not None:
        return refusal
    sentinel.write(phase="clone", name=name, repo_url=repo_url, install_dir=install_dir)
    try:
        work_dir = Path(tempfile.mkdtemp(prefix=".vibecomfy-restore-", dir=root.parent))
    except OSError as exc:
        return InstallResult(name, "failed", None, f"failed to create checkout staging: {_error_text(exc)}")
    staged = work_dir / "checkout"
    previous = work_dir / "previous"
    published = False
    result: InstallResult | None = None
    try:
        runner(["git", "clone", "--no-checkout", "--", repo_url, str(staged)],
               check=True, capture_output=True, text=True)
        verified_head, checkout_error = _checkout_ref_and_verify(
            name, repo_url, staged, checkout_ref or expected_commit or "HEAD", expected_commit, runner,
            sentinel=sentinel, fetch=checkout_ref is not None or expected_commit is not None,
            verify_origin=True,
        )
        if checkout_error is not None:
            result = InstallResult(name, "failed", None, checkout_error)
        elif replace_existing and (result := _replacement_refusal(name, install_dir, runner)) is not None:
            # The old checkout may have acquired user data during the clone.
            # Nothing has been published or installed, so a retry is safe.
            sentinel.clear()
        else:
            # The old checkout stays live until the new checkout is verified.
            # Never withdraw an unexpected destination or symlink.
            if install_dir.is_symlink() or install_dir.exists() != replace_existing:
                raise FileExistsError(f"node install destination changed during staging: {install_dir}")
            sentinel.write(phase="publish", name=name, repo_url=repo_url, install_dir=install_dir)
            if replace_existing:
                install_dir.rename(previous)
            staged.rename(install_dir)
            published = True
            result = _finalize_install(
                name, repo_url, install_dir, lockfile_path, runner,
                pack=pack, pack_ref=pack_ref, expected_commit=verified_head, sentinel=sentinel,
                restore_entry=restore_entry,
            )
    except (OSError, subprocess.CalledProcessError) as exc:
        result = InstallResult(name, "failed", None, _error_text(exc) or f"failed to install {name}")
    finally:
        succeeded = result is not None and result.status == "installed"
        if not succeeded:
            if published:
                # Withdraw the failed candidate; for a replacement, restore
                # the previous directory. A fresh failure leaves no pack.
                install_dir.rename(staged)
            if previous.exists():
                if not install_dir.exists() and not install_dir.is_symlink():
                    previous.rename(install_dir)
                else:
                    if result is not None:
                        result = replace(result, error=f"{result.error}; previous checkout retained at {previous}")
        # Never delete a displaced tree if rollback could not put it back or
        # a process wrote into it after the last pre-publication check. A
        # failed inspection is not permission to delete. The retained tree
        # lives outside the custom-node search root.
        if previous.exists() and (
            not succeeded or _replacement_status(previous, runner) != []
        ):
            if staged.exists():
                shutil.rmtree(staged)
            if succeeded and result is not None:
                message = (
                    f"Previous checkout for {name} retained at {previous}: local data present or status unavailable; "
                    "this backup is not cleaned up automatically"
                )
                logging.getLogger(__name__).warning("%s", message)
                result = replace(result, error=f"{result.error}; {message}" if result.error else message)
        else:
            shutil.rmtree(work_dir)
    return result


def _entry_has_dependencies(entry: LockEntry | None) -> bool:
    return entry is not None and bool(
        entry.pip_packages or entry.requirements_txt is not None or entry.pip_no_deps
    )


def _approval_node(entry: LockEntry) -> dict[str, Any]:
    """Project only the source and declarative recipe covered by LE-2a."""
    if (not entry.name or entry.name in {".", ".."} or Path(entry.name).name != entry.name
            or any(char.isspace() or char in "/\\" for char in entry.name)):
        raise ValueError("invalid node restore directory")
    if entry.path:
        raise ValueError("node code approval requires a pinned Git repository")
    if entry.commit != entry.git_commit_sha:
        raise ValueError("node restore commit aliases disagree")
    # Source/version describe resolution provenance. Restore always checks out
    # the full commit below; it never executes an annotated tag or local path.
    return {"repo": entry.url, "commit": entry.git_commit_sha,
            "requirements_txt": entry.requirements_txt, "pip_no_deps": list(entry.pip_no_deps)}


def validate_restore_approvals(entries, approvals, *, placement_class, lockfile_path: Path | None = None):
    """Admit the complete target lock before git, pip, sentinels or lock writes."""
    from vibecomfy import resources
    from vibecomfy.node_approvals import CodeConsentRequired, require_approved_nodes
    from ._lockfile import read_lockfile

    if lockfile_path is not None:
        resources.require_writable_node_lock(lockfile_path)
        # A direct/batch caller may already have selected entries, but must
        # still reject a malformed destination before it can upsert into it.
        read_lockfile(lockfile_path)
    try:
        if len({entry.name.casefold() for entry in entries}) != len(entries):
            raise ValueError("duplicate node restore directory")
        nodes = [_approval_node(entry) for entry in entries]
        records = require_approved_nodes(nodes, approvals, placement_class=placement_class)
        for entry in entries:
            if entry.patches or entry.pip_packages:
                _reviewed_dependencies(entry)
    except ValueError as exc:
        if isinstance(exc, CodeConsentRequired):
            raise
        raise CodeConsentRequired(str(exc)) from exc
    return records


def _reviewed_dependencies(entry: LockEntry) -> LockEntry:
    """Admit non-consented dependencies and patches only from the shipped recipe.

    The v1 consent hash covers repo, commit, canonical recipe and placement,
    not patch hashes or pip_packages. A target lock cannot authorize either.
    """
    from vibecomfy.node_approvals import CodeConsentRequired, reviewed_lock_entry

    reviewed = reviewed_lock_entry(_approval_node(entry))
    if entry.patches and (
        reviewed is None
        or len(set(entry.patches)) != len(entry.patches)
        or set(entry.patches) != set(reviewed.patches)
    ):
        raise CodeConsentRequired(
            f"node restore patch declaration for {entry.name!r} "
            f"({entry.patches[0].path}) differs from the trusted shipped recipe"
        )
    if entry.pip_packages and (reviewed is None or entry.pip_packages != reviewed.pip_packages):
        raise CodeConsentRequired("node code approval does not cover pip_packages; declare requirements_txt or pip_no_deps")
    return replace(entry, pip_packages=reviewed.pip_packages) if reviewed is not None and not entry.pip_packages else entry


def restore_pack(
    entry: LockEntry,
    *,
    install_root: Path | None = None,
    runner: Runner = subprocess.run,
    lockfile_path: Path = Path("custom_nodes.lock"),
    approvals: Sequence[Mapping[str, Any]] = (),
    placement_class: str = "local",
) -> InstallResult:
    """Restore this entry; an omitted lock path writes the cwd's target lock.

    Declared dependencies and recipes come from the entry. Bare legacy entries
    retain catalog pip dependencies, but never discover or run install.py.
    """
    try:
        validate_restore_approvals((entry,), approvals, placement_class=placement_class, lockfile_path=lockfile_path)
    except ValueError as exc:
        return InstallResult(entry.name, "failed", None, str(exc))
    entry = _reviewed_dependencies(entry)
    if install_root is None:
        install_root = default_install_root()
    declared = _entry_has_dependencies(entry)
    install_dir = install_root / entry.name
    if install_dir.is_symlink():
        return InstallResult(entry.name, "failed", None,
            f"conflict: node restore directory must not be a symlink; remove {install_dir}, then retry")
    # Consent covers the entry's recipe, never a same-named ambient catalog recipe.
    pack = None
    sentinel = _install_sentinel(install_root, entry.name)
    if _has_incomplete_install(sentinel): return InstallResult(entry.name, "failed", None, sentinel.reason)
    status: InstallStatus = "installed"
    verified = 0
    if install_dir.exists():
        origin = _git_origin(install_dir, runner)
        if origin is None or _normalize_git_remote(origin) != _normalize_git_remote(entry.url or ""):
            return InstallResult(entry.name, "failed", None,
                f"conflict: approved node repository differs from the existing checkout; remove {install_dir} or approve the new repository")
        current_head = _git_head(install_dir, runner)
        dirty = _git_porcelain(install_dir, runner)
        verified = _verified_declared_patches(install_dir, dirty, entry, current_head) if dirty else 0
        if dirty is None or (dirty and not verified):
            reason = (f"conflict: failed to inspect git status for {install_dir}" if dirty is None
                      else f"conflict: {install_dir} has uncommitted changes; restore refused")
            if dirty and entry.patches and current_head != entry.git_commit_sha:
                reason += f" (declared patch {entry.patches[0].path} requires locked HEAD)"
            reason += f"; remove or clean {install_dir}, then retry"
            return InstallResult(entry.name, "failed" if dirty is None else "skipped_dirty", current_head, reason)
        if current_head == entry.git_commit_sha:
            if not declared:
                return InstallResult(entry.name, "refreshed", entry.git_commit_sha, None, verified)
        else:
            result = _install_pack_via_clone(
                entry.name, entry.url or "", pack, install_dir, lockfile_path, runner,
                checkout_ref=entry.git_commit_sha, expected_commit=entry.git_commit_sha,
                sentinel=sentinel, restore_entry=entry, replace_existing=True,
            )
            return replace(result, status="refreshed") if result.status == "installed" else result
        status = "refreshed"
    else:
        return _install_pack_via_clone(
            entry.name, entry.url or "", pack, install_dir, lockfile_path, runner,
            checkout_ref=entry.git_commit_sha, expected_commit=entry.git_commit_sha,
            sentinel=sentinel, restore_entry=entry,
        )
    result = _finalize_install(
        entry.name, entry.url or "", install_dir, lockfile_path, runner,
        pack=pack, expected_commit=entry.git_commit_sha, sentinel=sentinel, restore_entry=entry,
    )
    return replace(result, status=status, verified_patches=verified) if result.status == "installed" else result
def _refresh_existing(
    name: str,
    repo_url: str,
    install_dir: Path,
    force: bool,
    lockfile_path: Path,
    runner: Runner,
    *,
    pack: CustomNodePack | None = None,
    pack_ref: PackRef | None = None,
    checkout_ref: str | None = None,
    expected_commit: str | None = None,
    allow_source_change: bool = False,
    resolve_latest: bool = False,
    sentinel: _InstallSentinel | None = None,
) -> InstallResult:
    sentinel = sentinel or _install_sentinel(install_dir.parent, name)
    if _has_incomplete_install(sentinel): return InstallResult(name, "failed", None, sentinel.reason)
    current_head = _git_head(install_dir, runner)
    current_origin = _git_origin(install_dir, runner)
    if current_origin is None:
        return InstallResult(name, "skipped_dirty", current_head, f"{install_dir} is not a readable git clone; refusing to overwrite existing contents")
    dirty = _git_porcelain(install_dir, runner)
    if dirty is None: return InstallResult(name, "failed", None, f"failed to inspect git status for {install_dir}")
    if dirty and not force: return InstallResult(name, "skipped_dirty", current_head, f"{install_dir} has uncommitted changes; pass --force to refresh the lockfile pin")
    origin_changed = _normalize_git_remote(current_origin) != _normalize_git_remote(repo_url)
    if origin_changed and not allow_source_change:
        return InstallResult(
            name,
            "skipped_dirty",
            current_head,
            f"{install_dir} points at {current_origin}, expected {repo_url}; refusing to overwrite existing clone",
        )
    if origin_changed or checkout_ref is not None or expected_commit is not None or resolve_latest:
        # A fresh staged clone would discard dirty files even with --force;
        # the flag permits refreshing a lock, not deleting user modifications.
        if dirty:
            return InstallResult(name, "skipped_dirty", current_head,
                                 f"{install_dir} has uncommitted changes; clean it before changing the checkout")
        result = _install_pack_via_clone(
            name, repo_url, pack, install_dir, lockfile_path, runner,
            pack_ref=pack_ref, checkout_ref=checkout_ref, expected_commit=expected_commit,
            sentinel=sentinel, replace_existing=True,
        )
        return replace(result, status="refreshed") if result.status == "installed" else result
    result = _finalize_install(
        name, repo_url, install_dir, lockfile_path, runner,
        pack=pack, pack_ref=pack_ref, expected_commit=expected_commit, sentinel=sentinel,
    )
    if result.status != "installed":
        return result
    return InstallResult(result.name, "refreshed", result.git_commit_sha, result.error)


def preflight_pip_requirements(packs: Sequence[CustomNodePack], *, runner: Runner = subprocess.run) -> PipPreflightResult:
    packages = tuple(sorted({package for pack in packs for package in pack.pip_packages}))
    if not packages:
        return PipPreflightResult(ok=True)
    if (requirement_error := _runtime_requirement_conflict(_ACTIVE_RUNTIME_REQUIREMENTS.get())) is not None:
        return PipPreflightResult(ok=False, packages=packages, error=requirement_error)
    with tempfile.TemporaryDirectory(prefix="vibecomfy-pip-preflight-") as tmp:
        workspace = Path(tmp).resolve()
        current_directory = Path.cwd().resolve()
        if current_directory != current_directory.parent and workspace.is_relative_to(current_directory):
            return PipPreflightResult(ok=False, packages=packages, error="pip working directory must be outside the checkout")
        try:
            help_result = runner(
                [sys.executable, "-I", "-m", "pip", "install", "--help"],
                check=True, capture_output=True, text=True, cwd=workspace,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            return PipPreflightResult(ok=False, packages=packages, unsupported=True, error=_error_text(exc) or "failed to check pip install capabilities")
        help_text = f"{help_result.stdout}\n{help_result.stderr}"
        if "--dry-run" not in help_text or "--report" not in help_text:
            return PipPreflightResult(ok=False, packages=packages, unsupported=True, error="pip install does not support required --dry-run --report preflight")
        conflict = _run_pip_step(
            packages, runner=runner, cwd=workspace, protected=_protected_runtime_packages(),
            constraint_path=_ACTIVE_PIP_CONSTRAINT.get(), report_path=workspace / "pip-report.json",
        )
        if conflict is not None:
            return PipPreflightResult(ok=False, packages=packages, error=conflict)
    return PipPreflightResult(ok=True, packages=packages)


def _write_runtime_constraints(runtime_requirements: Sequence[str] = ()) -> Path:
    fd, raw_path = tempfile.mkstemp(prefix="vibecomfy-runtime-constraints-", suffix=".txt")
    os.close(fd)
    path = Path(raw_path).resolve()
    versions = _protected_runtime_packages(runtime_requirements)
    path.write_text(
        "\n".join(f"{package}=={version}" for package, version in sorted(versions.items())) + "\n",
        encoding="utf-8",
    )
    return path


def _runtime_requirement_conflict(requirements: Sequence[str]) -> str | None:
    for raw_requirement in requirements:
        try:
            requirement = Requirement(str(raw_requirement))
        except InvalidRequirement:
            return f"invalid runtime requirement {raw_requirement!r}"
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        try:
            observed = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            continue
        if requirement.specifier and not requirement.specifier.contains(observed, prereleases=True):
            return f"installed {canonicalize_name(requirement.name)} {observed} does not satisfy declared {requirement}"
    return None


def install_required_packs(
    packs: Sequence[CustomNodePack],
    *,
    force: bool = False,
    restore_entries: Sequence[LockEntry] | None = None,
    install_refs_by_name: Mapping[str, PackRef | LockEntry | dict[str, Any] | str] | None = None,
    install_root: Path = DEFAULT_INSTALL_ROOT,
    lockfile_path: Path = Path("custom_nodes.lock"),
    runner: Runner = subprocess.run,
    cm_cli_resolver: Callable[[Path, Runner], list[str] | None] = _resolve_cm_cli,
    runtime_requirements: Sequence[str] = (),
    approvals: Sequence[Mapping[str, Any]] = (),
    placement_class: str = "local",
) -> InstallBatchResult:
    """Install under runtime constraints, writing the cwd's target lock if omitted."""
    constraint_path = _write_runtime_constraints(runtime_requirements)
    token = _ACTIVE_PIP_CONSTRAINT.set(constraint_path)
    requirements_token = _ACTIVE_RUNTIME_REQUIREMENTS.set(tuple(runtime_requirements))
    try:
        return _install_required_packs_impl(
            packs,
            force=force,
            restore_entries=restore_entries,
            install_refs_by_name=install_refs_by_name,
            install_root=install_root,
            lockfile_path=lockfile_path,
            runner=runner,
            cm_cli_resolver=cm_cli_resolver,
            approvals=approvals,
            placement_class=placement_class,
        )
    finally:
        _ACTIVE_PIP_CONSTRAINT.reset(token)
        _ACTIVE_RUNTIME_REQUIREMENTS.reset(requirements_token)
        try:
            constraint_path.unlink()
        except OSError:
            pass


def _install_required_packs_impl(
    packs: Sequence[CustomNodePack],
    *,
    force: bool = False,
    restore_entries: Sequence[LockEntry] | None = None,
    install_refs_by_name: Mapping[str, PackRef | LockEntry | dict[str, Any] | str] | None = None,
    install_root: Path = DEFAULT_INSTALL_ROOT,
    lockfile_path: Path = Path("custom_nodes.lock"),
    runner: Runner = subprocess.run,
    cm_cli_resolver: Callable[[Path, Runner], list[str] | None] = _resolve_cm_cli,
    approvals: Sequence[Mapping[str, Any]] = (),
    placement_class: str = "local",
) -> InstallBatchResult:
    """Apply the selected packs to a writable target lock, cwd-relative if omitted."""
    ordered_packs = tuple(packs)
    install_refs = install_refs_by_name or {}
    ref_error = validate_install_refs(ordered_packs, install_refs, restore_entries or ())
    if ref_error is not None:
        from vibecomfy.node_approvals import CodeConsentRequired

        error = str(CodeConsentRequired(ref_error))
        return InstallBatchResult(
            ok=False,
            results=tuple(InstallResult(pack.name, "failed", None, error) for pack in ordered_packs),
            preflight=PipPreflightResult(ok=False, error=error),
        )
    try:
        selected_entries = tuple(
            _batch_restore_entry(pack, install_refs.get(pack.name), restore_entries or ())
            for pack in ordered_packs
        )
        validate_restore_approvals(selected_entries, approvals, placement_class=placement_class, lockfile_path=lockfile_path)
        selected_entries = tuple(_reviewed_dependencies(entry) for entry in selected_entries)
    except ValueError as exc:
        error = str(exc)
        return InstallBatchResult(ok=False,
            results=tuple(InstallResult(pack.name, "failed", None, error) for pack in ordered_packs),
            preflight=PipPreflightResult(ok=False, error=error))
    # Preflight the same dependency authority that restore will install.
    # Catalog pip dependencies must not leak into an entry's declared recipe.
    preflight_packs = tuple(
        replace(pack, pip_packages=entry.pip_packages)
        for pack, entry in zip(ordered_packs, selected_entries)
    )
    preflight = preflight_pip_requirements(preflight_packs, runner=runner)
    if not preflight.ok:
        error = preflight.error or "pip preflight failed"
        return InstallBatchResult(
            ok=False,
            results=tuple(InstallResult(pack.name, "failed", None, error) for pack in ordered_packs),
            preflight=preflight,
        )
    results: list[InstallResult] = []
    for pack, entry in zip(ordered_packs, selected_entries):
        # Every selected pack now has an admitted immutable identity. Neither
        # force nor a resolver may substitute dirty code, a tag, or FETCH_HEAD.
        result = restore_pack(entry, install_root=install_root, runner=runner, lockfile_path=lockfile_path,
                              approvals=approvals, placement_class=placement_class)
        if install_refs.get(pack.name) is not None and result.status in {"installed", "refreshed"}:
            upsert_lockfile_entry(entry, lockfile_path)
        results.append(result)
    return InstallBatchResult(
        ok=all(result.status in {"installed", "refreshed"} for result in results),
        results=tuple(results),
        preflight=preflight,
    )
def missing_packs_for_workflow(
    workflow: VibeWorkflow, *, lockfile_path: Path | None = None
) -> tuple[list[CustomNodePack], list[str]]:
    missing_classes = missing_class_types_for_workflow(workflow)
    packs = resolve_node_packs(missing_classes, lockfile_path=lockfile_path)
    portable = _portable_requirement_packs(workflow)
    all_packs = [*packs, *portable]
    covered = set().union(*(pack.classes for pack in all_packs)) if all_packs else set()
    unresolved = sorted(missing_classes - covered)
    return _merge_declared_requirement_packs(workflow, all_packs, lockfile_path=lockfile_path), unresolved


def _portable_requirement_packs(workflow: VibeWorkflow) -> list[CustomNodePack]:
    """Build installable catalog entries from workflow-carried class evidence."""
    requirements = getattr(workflow, "metadata", {}).get("requirements", {})
    refs = requirements.get("custom_node_refs", ()) if isinstance(requirements, Mapping) else ()
    result: list[CustomNodePack] = []
    for ref in refs if isinstance(refs, list) else ():
        if not isinstance(ref, Mapping):
            continue
        classes = ref.get("class_set", ref.get("classes", ()))
        slug = ref.get("slug") or ref.get("name")
        if not isinstance(slug, str) or not slug or not isinstance(classes, (list, tuple)) or not classes:
            continue
        result.append(CustomNodePack(
            name=str(ref.get("name") or slug),
            repo=str(ref.get("url") or ref.get("path") or slug),
            classes=frozenset(str(item) for item in classes if isinstance(item, str) and item),
            pip_packages=tuple(str(item) for item in (ref.get("pip_packages") or ()) if isinstance(item, str)),
            class_schema_sha256=ref.get("class_schema_sha256") or ref.get("schema_hash"),
        ))
    return result


@dataclass(frozen=True)
class _AuthoredPackRef(PackRef):
    """Selection-only carrier; the registry selector itself has no recipe."""

    requirements_txt: str | None = None
    pip_no_deps: tuple[str, ...] = ()


def build_install_refs_by_name(
    workflow: VibeWorkflow,
    packs: Sequence[CustomNodePack],
) -> dict[str, PackRef]:
    """Translate canonical authored node refs to the selected pack names."""
    metadata = getattr(workflow, "metadata", {})
    requirements = metadata.get("requirements") if isinstance(metadata, Mapping) else None
    raw_refs = getattr(getattr(workflow, "requirements", None), "custom_node_refs", None)
    if not isinstance(raw_refs, list):
        raw_refs = requirements.get("custom_node_refs") if isinstance(requirements, Mapping) else ()
    if not isinstance(raw_refs, list):
        return {}

    def selector_key(value: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value).strip().casefold())

    pack_keys: dict[str, list[CustomNodePack]] = {}
    for pack in packs:
        keys = {selector_key(pack.name), selector_key(_pack_name_from_repo(pack.repo))}
        for key in keys:
            if key:
                pack_keys.setdefault(key, []).append(pack)

    refs_by_name: dict[str, PackRef] = {}
    for index, raw_ref in enumerate(raw_refs):
        if not isinstance(raw_ref, Mapping):
            raise ValueError(f"authored custom_node_refs[{index}] must be an object")
        selectors = [raw_ref.get("slug"), raw_ref.get("name")]
        selector_values = [value for value in selectors if isinstance(value, str) and value.strip()]
        if not selector_values:
            raise ValueError(f"authored custom_node_refs[{index}] has no slug or name selector")
        matches = {
            pack.name
            for value in selector_values
            for pack in pack_keys.get(selector_key(value), ())
        }
        if len(matches) != 1:
            selected = ", ".join(selector_values)
            raise ValueError(
                f"authored custom_node_refs[{index}] selector {selected!r} did not select exactly one resolved pack"
            )
        pack_name = next(iter(matches))
        ref = _pack_ref_from_install_ref(raw_ref)
        if ref is None:
            raise ValueError(f"authored custom_node_refs[{index}] is not a valid install ref")
        if not ref.slug:
            ref = _pack_ref_with_slug(ref, pack_name)
        previous = refs_by_name.get(pack_name)
        if previous is not None and previous != ref:
            raise ValueError(f"conflicting authored custom-node refs for {pack_name!r}")
        refs_by_name[pack_name] = ref
    return refs_by_name


def validate_install_refs(
    packs: Sequence[CustomNodePack],
    install_refs_by_name: Mapping[str, PackRef | LockEntry | dict[str, Any] | str],
    restore_entries: Sequence[LockEntry],
) -> str | None:
    """Validate selectors and any available lock identity before mutation."""
    pack_names = {pack.name for pack in packs}
    for name, raw_ref in install_refs_by_name.items():
        if name not in pack_names:
            return f"custom-node install ref {name!r} does not select a resolved pack"
        try:
            ref = _pack_ref_from_install_ref(raw_ref)
        except (AttributeError, TypeError, ValueError) as exc:
            return f"invalid custom-node install ref for {name!r}: {exc}"
        if ref is None:
            # A LockEntry is already a complete restore identity.
            continue
        # A changed selector does not reuse the old witness. The batch must
        # select a full immutable identity and approve it before any mutation.
    return None


def _matching_lock_entry(
    pack: CustomNodePack,
    install_ref: PackRef | LockEntry | dict[str, Any] | str | None,
    restore_entries: Sequence[LockEntry],
) -> LockEntry | None:
    """Return a lock witness only for the same selector and authored recipe."""
    from vibecomfy.node_recipes import recipe_sha256

    if isinstance(install_ref, LockEntry):
        return install_ref
    ref = _pack_ref_from_install_ref(install_ref)
    wanted_recipe = recipe_sha256(
        {"requirements_txt": ref.requirements_txt, "pip_no_deps": ref.pip_no_deps}
        if isinstance(ref, _AuthoredPackRef) else {}
    )
    candidates = [
        entry for entry in restore_entries
        if entry.name == pack.name or entry.slug == pack.name or (ref is not None and entry.slug == ref.slug)
    ]
    for entry in candidates:
        if ref is None:
            return entry
        if ref.url and entry.url and _normalize_git_remote(ref.url) != _normalize_git_remote(entry.url):
            continue
        if ref.url and not entry.url:
            continue
        if not ref.url and entry.url:
            # An authored selector without a source URL is not a witness for
            # an older resolved source. Let the pack resolver/pack default
            # establish the new source rather than reusing stale lock data.
            continue
        if ref.path and ref.path != entry.path:
            continue
        if ref.version is None and entry.version is not None:
            continue
        if ref.version is not None and entry.version != ref.version:
            continue
        locked_commit = entry.commit or entry.git_commit_sha
        if ref.commit and locked_commit != ref.commit:
            continue
        if recipe_sha256({"requirements_txt": entry.requirements_txt,
                          "pip_no_deps": entry.pip_no_deps}) != wanted_recipe:
            continue
        # A commit-only ref is exact only when the lock carries that commit;
        # URL-only and version-only refs are likewise witnessed by the URL or
        # selector checks above.
        return entry
    # A non-matching selector needs a new immutable witness. Batch admission
    # rejects unresolved tags and latest refs before any subprocess.
    return None


def _batch_restore_entry(pack, install_ref, restore_entries) -> LockEntry:
    """Select a target, authored full pin, or exact shipped review witness."""
    from vibecomfy.node_approvals import CodeConsentRequired

    entry = _matching_lock_entry(pack, install_ref, restore_entries)
    if entry is not None:
        return entry
    if install_ref is not None:
        ref = _pack_ref_from_install_ref(install_ref)
        if ref is not None and not ref.path:
            entry = _restore_entry_from_install_ref(pack, ref)
            if entry is not None:
                return entry
        raise CodeConsentRequired(f"{pack.name} requires a resolved repository and full commit before installation")
    from vibecomfy.node_packs import read_lockfile

    reviewed = [row for row in read_lockfile()
                if (row.name == pack.name or row.slug == pack.name)
                and row.url and _normalize_git_remote(row.url) == _normalize_git_remote(pack.repo)]
    if len(reviewed) != 1:
        raise CodeConsentRequired(f"{pack.name} has no exact shipped pin or approved target lock")
    return reviewed[0]


def _merge_declared_requirement_packs(
    workflow: VibeWorkflow,
    packs: list[CustomNodePack],
    *,
    lockfile_path: Path | None = None,
) -> list[CustomNodePack]:
    by_name = {pack.name: pack for pack in get_known_node_packs(lockfile_path=lockfile_path)}
    merged = {pack.name: pack for pack in packs}
    for name in workflow.requirements.custom_nodes:
        pack = by_name.get(name)
        if pack is not None:
            merged.setdefault(pack.name, pack)
    return sorted(merged.values(), key=lambda pack: pack.name.lower())


def missing_class_types_for_workflow(workflow: VibeWorkflow) -> set[str]: return {node.class_type for node in workflow.nodes.values()} - _known_schema_classes() - CORE_COMFY_CLASSES
def _pack_by_name(name: str | None) -> CustomNodePack | None:
    """Look up the shipped catalog, never an implicit writable target lock."""
    return next((pack for pack in get_known_node_packs() if pack.name == name), None)
def _lock_entry_for_pack(name: str, sha: str, repo_url: str, *, pack: CustomNodePack | None, pack_ref: PackRef | None = None) -> LockEntry | None:
    class_set = tuple(sorted(pack.classes)) if pack is not None and pack.classes else ()
    if pack_ref is not None and pack_ref.source == "comfy-registry" and not class_set:
        return None
    # ``commit`` is the resolved identity, while a commit-only authored ref
    # is also a requested selector. Preserve that request in the lock so a
    # later selector removal cannot mistake the old resolved commit for a
    # default/latest resolution.
    requested_version = (
        pack_ref.version
        if pack_ref is not None
        else None
    )
    if requested_version is None and pack_ref is not None and pack_ref.commit is not None:
        requested_version = pack_ref.commit
    return LockEntry(
        name=name,
        git_commit_sha=sha,
        url=repo_url,
        slug=(pack_ref.slug if pack_ref is not None else name),
        source=(pack_ref.source if pack_ref is not None else "git"),
        version=requested_version,
        commit=sha,
        class_set=class_set,
        pip_packages=pack.pip_packages if pack is not None else (),
        class_schema_sha256=pack.class_schema_sha256 if pack_ref is not None and pack is not None else None,
        requirements_txt=pack_ref.requirements_txt if isinstance(pack_ref, _AuthoredPackRef) else None,
        pip_no_deps=pack_ref.pip_no_deps if isinstance(pack_ref, _AuthoredPackRef) else (),
    )
def _restore_entry_from_install_ref(pack: CustomNodePack, install_ref: PackRef | LockEntry | dict[str, Any] | str | None) -> LockEntry | None:
    if install_ref is None:
        return None
    if isinstance(install_ref, LockEntry):
        return install_ref
    pack_ref = _pack_ref_from_install_ref(install_ref)
    if pack_ref is None or not _looks_like_commit(pack_ref.commit):
        return None
    repo_url = pack_ref.url or pack.repo
    if not pack_ref.slug:
        pack_ref = _pack_ref_with_slug(pack_ref, pack.name)
    entry = _lock_entry_for_pack(pack.name, pack_ref.commit or "", repo_url, pack=pack, pack_ref=pack_ref)
    # A synthesized authored row has no reviewed legacy dependency witness.
    # Admission restores those packages only from an exact shipped recipe.
    return replace(entry, pip_packages=()) if entry is not None else None
def _pack_ref_from_install_ref(install_ref: PackRef | LockEntry | dict[str, Any] | str | None) -> PackRef | None:
    if install_ref is None or isinstance(install_ref, LockEntry):
        return None
    if isinstance(install_ref, PackRef):
        return install_ref
    if isinstance(install_ref, str):
        return PackRef(slug="", source="git", version=install_ref, commit=install_ref if _looks_like_commit(install_ref) else None)
    from vibecomfy.node_recipes import RECIPE_FIELDS, canonical_recipe

    recipe = canonical_recipe({key: install_ref[key] for key in RECIPE_FIELDS if key in install_ref})
    selector = PackRef(
        slug=str(install_ref.get("slug") or install_ref.get("name") or ""),
        source=str(install_ref.get("source") or "git"),
        version=str(install_ref["version"]) if install_ref.get("version") is not None else None,
        commit=str(install_ref["commit"]) if install_ref.get("commit") is not None else None,
        url=str(install_ref["url"]) if install_ref.get("url") is not None else None,
        path=str(install_ref["path"]) if install_ref.get("path") is not None else None,
        name=str(install_ref["name"]) if install_ref.get("name") is not None else None,
        registry_id=str(install_ref["registry_id"]) if install_ref.get("registry_id") is not None else None,
        download_url=str(install_ref["download_url"]) if install_ref.get("download_url") is not None else None,
    )
    if recipe["requirements_txt"] is None and not recipe["pip_no_deps"]:
        return selector
    return _AuthoredPackRef(
        **selector.to_dict(),
        requirements_txt=recipe["requirements_txt"],
        pip_no_deps=tuple(recipe["pip_no_deps"]),
    )
def _pack_ref_with_slug(pack_ref: PackRef, slug: str) -> PackRef:
    return replace(pack_ref, slug=slug)
def _checkout_ref_and_verify(
    name: str,
    repo_url: str,
    install_dir: Path,
    checkout_ref: str | None,
    expected_commit: str | None,
    runner: Runner,
    *,
    sentinel: _InstallSentinel,
    fetch: bool,
    verify_origin: bool = False,
) -> tuple[str | None, str | None]:
    if verify_origin:
        origin = _git_origin(install_dir, runner)
        if origin is None or _normalize_git_remote(origin) != _normalize_git_remote(repo_url):
            return None, f"approved node repository differs from staged checkout for {name}"
    if checkout_ref is None and expected_commit is None and not verify_origin:
        return None, None
    git = ["git", "-C", str(install_dir)]
    checkout_target = expected_commit or checkout_ref
    try:
        if fetch and checkout_target is not None:
            sentinel.write(phase="fetch", name=name, repo_url=repo_url, install_dir=install_dir)
            try:
                runner([*git, "fetch", "--", repo_url, checkout_target],
                       check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as exc:
                # Some servers reject an explicit SHA want even when it is
                # reachable from an advertised tag. Fetch only that same
                # approved repository's tags and still verify the exact SHA.
                if expected_commit is None or not re.fullmatch(r"[0-9a-fA-F]{40}", expected_commit):
                    raise
                try:
                    runner([*git, "fetch", "--", repo_url, "+refs/tags/*:refs/tags/*"],
                           check=True, capture_output=True, text=True)
                except (OSError, subprocess.CalledProcessError) as tag_exc:
                    return None, (f"failed to fetch approved commit {expected_commit}: {_error_text(exc)}; "
                                  f"approved tag fetch failed: {_error_text(tag_exc)}")
        if checkout_target is not None:
            sentinel.write(phase="checkout", name=name, repo_url=repo_url, install_dir=install_dir)
            runner([*git, "checkout", checkout_target], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        return None, _error_text(exc) or f"failed to checkout {checkout_ref} for {name}"
    sentinel.write(phase="verification", name=name, repo_url=repo_url, install_dir=install_dir)
    head = _git_head(install_dir, runner)
    if head is None:
        return None, f"failed to read git HEAD for {install_dir}"
    if expected_commit is not None and head != expected_commit:
        return None, f"expected git HEAD {expected_commit} for {install_dir}, got {head}"
    if verify_origin:
        origin = _git_origin(install_dir, runner)
        if origin is None or _normalize_git_remote(origin) != _normalize_git_remote(repo_url):
            return None, f"approved node repository differs from staged checkout for {name}"
    return head, None
def _looks_like_commit(value: str | None) -> bool:
    return bool(value is not None and re.fullmatch(r"[0-9a-fA-F]{7,40}", value))
def _protected_runtime_packages(runtime_requirements: Sequence[str] | None = None) -> dict[str, str]:
    """Return installed foundational packages whose versions node pip may not change."""
    names = {"torch"}
    raw = os.environ.get("VIBECOMFY_PROTECTED_RUNTIME_PACKAGES", "")
    names.update(item.strip().lower() for item in raw.split(",") if item.strip())
    observed: dict[str, str] = {}
    for package in sorted(names):
        try:
            observed[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue
    requirements = _ACTIVE_RUNTIME_REQUIREMENTS.get() if runtime_requirements is None else runtime_requirements
    for raw_requirement in requirements:
        try:
            requirement = Requirement(str(raw_requirement))
        except InvalidRequirement:
            # _runtime_requirement_conflict reports malformed declarations.
            continue
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        package = canonicalize_name(requirement.name)
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue
        if not requirement.specifier or requirement.specifier.contains(version, prereleases=True):
            observed[package] = version
    return observed


def _pip_plan_conflict(report_path: Path, protected: Mapping[str, str]) -> str | None:
    """Reject a dry-run plan that would replace an installed protected package."""
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "pip dry-run did not produce a readable resolution report"
    if not isinstance(report, Mapping) or "install" not in report or not isinstance(report["install"], list):
        return "pip dry-run produced a malformed resolution report"
    installs = report["install"]
    for item in installs:
        if not isinstance(item, Mapping) or not isinstance(item.get("metadata"), Mapping):
            return "pip dry-run produced a malformed install item"
        metadata = item["metadata"]
        if not isinstance(metadata.get("name"), str) or not isinstance(metadata.get("version"), str):
            return "pip dry-run produced an install item without package name/version"
        package = canonicalize_name(metadata["name"])
        planned = metadata.get("version")
        current = next((value for key, value in protected.items() if canonicalize_name(key) == package), None)
        if current is not None:
            try:
                differs = Version(str(planned)) != Version(str(current))
            except InvalidVersion:
                differs = str(planned) != str(current)
            if differs:
                return f"custom-node pip resolution would change protected runtime package {package} from {current} to {planned}"
    return None


def _requirements_tree_error(requirements: Path, checkout: Path) -> str | None:
    """Validate every pip include before pip reads any of the recipe.

    Accept explicit -r/-c and their full long forms. Abbreviated options,
    environment substitutions and non-UTF-8 files are refused, so pip cannot
    reinterpret an include differently after this check. Paths retain their
    spelling for relative includes, while confinement/cycles use real paths.
    """
    pending: list[tuple[Path, tuple[Path, ...]]] = [(requirements, ())]
    checked: set[Path] = set()
    while pending:
        path, ancestors = pending.pop()
        path = Path(os.path.abspath(path))
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(checkout) or not resolved.is_file():
                return f"requirements include {path} must be a file inside its checkout"
            if resolved in ancestors:
                return f"cyclic requirements include at {path}"
            if path in checked:
                continue
            content = path.read_text(encoding="utf-8-sig")
        except (OSError, RuntimeError, UnicodeError) as exc:
            return f"cannot read requirements include {path}: {exc}"
        checked.add(path)
        for header in content.splitlines()[:2]:
            encoding = re.search(r"coding[:=]\s*([-\w.]+)", header)
            if encoding and encoding[1].lower().replace("_", "-") not in {"utf-8", "utf8"}:
                return f"requirements file {path} must use UTF-8 encoding"
        # Match pip's continuation-before-comment order. Options are inspected
        # with shlex; dependency text itself is passed to pip unchanged.
        logical_lines: list[str] = []
        continued: list[str] = []
        for line in content.splitlines():
            comment = re.match(r"(^|\s+)#", line)
            if line.endswith("\\") and not comment:
                continued.append(line.strip("\\"))
            else:
                logical_lines.append("".join(continued) + (" " if comment else "") + line)
                continued.clear()
        if continued:
            logical_lines.append("".join(continued))
        for raw_line in logical_lines:
            line = re.sub(r"(^|\s+)#.*$", "", raw_line).strip()
            if not line:
                continue
            if re.search(r"\$\{[A-Z0-9_]+\}", line):
                return f"requirements file {path} cannot use environment substitutions"
            try:
                tokens = shlex.split(line)
            except ValueError as exc:
                return f"cannot parse requirements file {path}: {exc}"
            index = 0
            while index < len(tokens):
                token = tokens[index]
                index += 1
                include: str | None = None
                option, equals, value = token.partition("=")
                if option in {"--requirement", "--constraint"}:
                    if equals:
                        include = value
                    elif index < len(tokens):
                        include = tokens[index]
                        index += 1
                    else:
                        return f"requirements include {token} in {path} has no path"
                elif token.startswith("--") and any(full.startswith(option) for full in ("--requirement", "--constraint")):
                    return f"requirements file {path} must spell include options in full: {token}"
                elif token.startswith(("-r", "-c")):
                    if len(token) > 2:
                        include = token[2:]
                    elif index < len(tokens):
                        include = tokens[index]
                        index += 1
                    else:
                        return f"requirements include {token} in {path} has no path"
                if include is not None:
                    if (not include or ":" in include or "\\" in include or include.startswith("-")
                            or any(ord(char) < 32 or ord(char) == 127 for char in include)):
                        return f"requirements include {include!r} in {path} must be a local checkout path"
                    pending.append((path.parent / include, (*ancestors, resolved)))
    return None


def _run_pip_step(
    arguments: Sequence[str], *, runner: Runner, cwd: Path,
    protected: Mapping[str, str], constraint_path: Path | None,
    report_path: Path | None = None,
) -> str | None:
    """One isolated pip invocation, with the same checks on both exit paths."""
    command = [sys.executable, "-I", "-m", "pip", "install"]
    phase = "preflight" if report_path is not None else "install"
    if report_path is not None:
        command.extend(["--dry-run", "--report", str(report_path)])
    if constraint_path is not None:
        command.extend(["--constraint", str(constraint_path)])
    error = None
    try:
        runner([*command, *arguments], check=True, capture_output=True, text=True, cwd=cwd)
    except (OSError, subprocess.CalledProcessError) as exc:
        error = _error_text(exc) or f"pip {phase} failed"
    for package, version in protected.items():
        try:
            observed = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            observed = None
        if observed != version:
            change = f"custom-node pip {phase} changed protected runtime package {package} from {version} to {observed}"
            return f"{change}; {error}" if error else change
    if error is not None:
        return error
    return _pip_plan_conflict(report_path, protected) if report_path is not None else None


def _install_pack_pip_packages(
    name: str,
    pack: CustomNodePack | None,
    runner: Runner,
    *,
    restore_entry: LockEntry | None = None,
    install_dir: Path | None = None,
) -> str | None:
    """Preflight and install every dependency step through the same pip guard.

    A declared entry recipe is authoritative, including its empty pip_packages.
    Only bare legacy entries use the catalog's established pip dependencies.
    Requirements files are explicit: no file discovery or install.py execution.
    """
    declared = _entry_has_dependencies(restore_entry)
    packages = pack.pip_packages if pack is not None else ()
    if restore_entry is not None and declared:
        packages = restore_entry.pip_packages
    steps: list[tuple[str, ...]] = [tuple(packages)] if packages else []
    checkout = install_dir.resolve() if install_dir is not None else None
    requirements = None
    if restore_entry is not None:
        if restore_entry.requirements_txt is not None:
            if checkout is None:
                return f"requirements file for {name} needs a checked-out pack directory"
            try:
                requirements = (checkout / restore_entry.requirements_txt).resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                return f"cannot read requirements file for {name}: {exc}"
            if not requirements.is_relative_to(checkout) or not requirements.is_file():
                return f"requirements file for {name} must be a file inside its checkout"
            if (include_error := _requirements_tree_error(requirements, checkout)) is not None:
                return include_error
            steps.append(("-r", str(requirements)))
        steps.extend(("--no-deps", package) for package in restore_entry.pip_no_deps)
    if not steps:
        return None
    if (requirement_error := _runtime_requirement_conflict(_ACTIVE_RUNTIME_REQUIREMENTS.get())) is not None:
        return requirement_error
    protected = _protected_runtime_packages()
    active_constraint = _ACTIVE_PIP_CONSTRAINT.get()
    owned_constraint = active_constraint is None
    if owned_constraint:
        active_constraint = _write_runtime_constraints(_ACTIVE_RUNTIME_REQUIREMENTS.get())
    try:
        with tempfile.TemporaryDirectory(prefix="vibecomfy-node-pip-") as tmp:
            workspace = Path(tmp).resolve()
            if checkout is not None and workspace.is_relative_to(checkout):
                return f"pip working directory for {name} must be outside its checkout"

            def run_step(arguments: Sequence[str], report_path: Path | None = None) -> str | None:
                # A previous package build can have changed an include. Check
                # the complete file graph again immediately before consumption.
                if requirements is not None and checkout is not None:
                    if (include_error := _requirements_tree_error(requirements, checkout)) is not None:
                        return include_error
                return _run_pip_step(
                    arguments, runner=runner, cwd=workspace, protected=protected,
                    constraint_path=active_constraint, report_path=report_path,
                )

            # Check the entire recipe before any pip mutation. Each no-deps
            # requirement is resolved separately with the same flags it will
            # use on installation, preserving the authored sequence.
            for index, arguments in enumerate(steps):
                if (error := run_step(arguments, workspace / f"pip-whole-{index}.json")) is not None:
                    return error
            for index, arguments in enumerate(steps):
                # Resolve against the environment left by the preceding step,
                # retaining the whole-recipe preflight above as an early gate.
                if (error := run_step(arguments, workspace / f"pip-current-{index}.json")) is not None:
                    return error
                if (error := run_step(arguments)) is not None:
                    return error
    finally:
        if owned_constraint and active_constraint is not None:
            active_constraint.unlink(missing_ok=True)
    return None
def _finalize_install(
    name: str,
    repo_url: str,
    install_dir: Path,
    lockfile_path: Path,
    runner: Runner,
    *,
    pack: CustomNodePack | None = None,
    pack_ref: PackRef | None = None,
    expected_commit: str | None = None,
    sentinel: _InstallSentinel,
    restore_entry: LockEntry | None = None,
) -> InstallResult:
    """Verify and install dependencies, then persist the lock and clear the sentinel.

    Every path that installs dependencies (clone, cm-cli success, refresh,
    restore-existing, restore-clone) routes through this single helper so that
    durable invariants — pip dependency installation, commit verification,
    lockfile entry derivation and upsert, and sentinel clearance — are
    applied uniformly and only after all work succeeds.
    """
    from vibecomfy import resources

    try:
        resources.require_writable_node_lock(lockfile_path)
    except ValueError as exc:
        return InstallResult(name, "failed", None, str(exc))
    # Read a recipe only from the requested checkout, before pip can consume
    # its requirements file. Verify again after pip, as for every install.
    if _entry_has_dependencies(restore_entry):
        sentinel.write(phase="verification", name=name, repo_url=repo_url, install_dir=install_dir)
        head = _git_head(install_dir, runner)
        if head is None:
            return InstallResult(name, "failed", None, f"failed to read git HEAD for {install_dir}")
        if expected_commit is not None and head != expected_commit:
            return InstallResult(name, "failed", head, f"expected git HEAD {expected_commit} for {install_dir}, got {head}")
    # 1. Install pip dependencies and the entry's declared recipe.
    sentinel.write(phase="pip", name=name, repo_url=repo_url, install_dir=install_dir)
    if (pip_error := _install_pack_pip_packages(
        name, pack, runner, restore_entry=restore_entry, install_dir=install_dir,
    )) is not None:
        return InstallResult(name, "failed", None, pip_error)
    # 2. Verify git HEAD.
    sentinel.write(phase="verification", name=name, repo_url=repo_url, install_dir=install_dir)
    sha = _git_head(install_dir, runner)
    if sha is None:
        return InstallResult(name, "failed", None, f"failed to read git HEAD for {install_dir}")
    if expected_commit is not None and sha != expected_commit:
        return InstallResult(name, "failed", sha, f"expected git HEAD {expected_commit} for {install_dir}, got {sha}")
    # 3. Preserve the exact restore declaration, including its recipe and
    # evidence. New catalog installs still derive their resolution receipt.
    entry = restore_entry
    if entry is None:
        entry = _lock_entry_for_pack(name, sha, repo_url, pack=pack, pack_ref=pack_ref)
    if entry is None:
        return InstallResult(name, "failed", None, f"failed to derive class_set for registry-driven pack {name}")
    # 4. Upsert lockfile and clear sentinel — only after all durable work succeeds.
    try:
        resources.require_writable_node_lock(lockfile_path)
    except ValueError as exc:
        return InstallResult(name, "failed", sha, str(exc))
    sentinel.write(phase="lockfile", name=name, repo_url=repo_url, install_dir=install_dir, git_commit_sha=sha)
    upsert_lockfile_entry(entry, lockfile_path)
    sentinel.clear()
    return InstallResult(name, "installed", sha, None)


def _install_sentinel(install_root: Path, name: str) -> _InstallSentinel:
    """Create an install sentinel, recovering dead/stale/corrupt sentinels.

    Recovery rules (conservative):
    * No sentinel file -> fresh sentinel.
    * Corrupt / unreadable sentinel -> quarantine and return fresh sentinel
      (no active owner detectable).
    * Valid sentinel with structured owner metadata (pid, hostname, timestamp):
      - Same host, pid alive -> refuse (live owner).
      - Same host, pid dead -> recover (clear sentinel).
      - Different host, lease stale -> recover.
      - Different host, lease fresh -> refuse (owner may be active on other host).
    * Valid sentinel without owner metadata (legacy / incomplete) -> quarantine
      and return fresh sentinel (no active owner detectable).
    """
    path = install_root / INSTALL_STATE_DIR / f"{_safe_pack_slug(name)}.json"
    if not path.exists():
        return _InstallSentinel(path)

    # Attempt to read sentinel payload.
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("complete") is not False:
            # Malformed or already-complete marker — quarantine as corrupt.
            _quarantine_sentinel(path)
            return _InstallSentinel(path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        # Unreadable / corrupt — quarantine.
        _quarantine_sentinel(path)
        return _InstallSentinel(path)

    # Valid, incomplete sentinel.  Check owner metadata.
    owner_pid = data.get("pid")
    owner_hostname = data.get("hostname")
    owner_timestamp = data.get("timestamp")

    if owner_pid is not None and owner_hostname is not None and owner_timestamp is not None:
        current_hostname = socket.gethostname()
        if owner_hostname == current_hostname:
            # Same host — we can test the process directly.
            if _process_alive(owner_pid):
                return _InstallSentinel(path, live_owner_pid=owner_pid)
            else:
                # Process is dead — safe to recover.
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                return _InstallSentinel(path)
        else:
            # Different host — fall back to lease staleness.
            if time.time() - owner_timestamp > SENTINEL_LEASE_SECONDS:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                return _InstallSentinel(path)
            else:
                return _InstallSentinel(path, live_owner_pid=owner_pid)
    else:
        # No structured owner metadata — no active owner detectable.
        _quarantine_sentinel(path)
        return _InstallSentinel(path)


def inspect_pack_install_state(
    name: str,
    *,
    install_roots: Sequence[Path],
    expected_head: str | None = None,
    aux_id: str | None = None,
    version_pin: str | None = None,
    entry: LockEntry | None = None,
) -> PackInstallState:
    """Read the installer-owned bounded state for one required pack.

    This deliberately uses the same first-match lookup, Git status commands,
    and install sentinel authority as installation.  It does not inspect or
    hash arbitrary repository contents.
    """
    from ._git import find_installed_pack_ref

    selected = find_installed_pack_ref(
        name,
        install_roots=install_roots,
        aux_id=aux_id,
        version_pin=version_pin,
    )
    if selected is None or not selected.pack_ref.path:
        return PackInstallState(None, None, expected_head, None, "missing")

    root = Path(selected.install_root)
    path = Path(selected.pack_ref.path)
    sentinel = _install_sentinel(root, name)
    if sentinel.incomplete:
        return PackInstallState(root, path, expected_head, selected.pack_ref.commit, "incomplete")
    observed_head = _git_head(path, subprocess.run)
    if observed_head is None:
        return PackInstallState(root, path, expected_head, None, "unknown")
    dirty = _git_porcelain(path, subprocess.run)
    if dirty is None:
        return PackInstallState(root, path, expected_head, observed_head, "unknown")
    verified = _verified_declared_patches(path, dirty, entry, observed_head) if dirty and entry else 0
    return PackInstallState(root, path, expected_head, observed_head, "patched" if verified else "dirty" if dirty else "clean")


def _has_incomplete_install(sentinel: _InstallSentinel) -> bool:
    return sentinel.incomplete


def _process_alive(pid: int) -> bool:
    """Return True if a process with *pid* exists on this host."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we cannot signal it — treat as alive.
        return True
    except OSError:
        # On some platforms os.kill(pid, 0) may raise OSError for
        # permission or ESRCH-like reasons; err conservatively.
        return True
    return True


def _quarantine_sentinel(path: Path) -> None:
    """Rename *path* to a ``.corrupt-<timestamp>`` sibling so it cannot block
    the next install."""
    ts = int(time.time())
    dest = path.with_name(f".corrupt-{ts}-{path.name}")
    # If the destination already exists (unlikely), append a counter.
    counter = 0
    while dest.exists():
        counter += 1
        dest = path.with_name(f".corrupt-{ts}-{counter}-{path.name}")
    try:
        path.rename(dest)
    except (OSError, FileNotFoundError):
        # Best-effort — if we cannot rename, try to unlink.
        try:
            path.unlink()
        except FileNotFoundError:
            pass
def _safe_pack_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return slug or "pack"
def _pack_name_from_repo(repo: str) -> str: return (name[:-4] if (name := Path((urlparse(repo).path or repo).rstrip("/")).name).endswith(".git") else name)
def _git(pack_dir: Path, args: list[str], runner: Runner) -> str | None:
    try: return runner(["git", "-C", str(pack_dir), *args], check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError): return None
def _verified_declared_patches(pack_dir: Path, porcelain: str, entry: LockEntry, head: str | None) -> int:
    """Count verified worktree-only tracked modifications, or fail closed."""
    if not porcelain or not entry.patches or head is None or head != entry.git_commit_sha:
        return 0
    from vibecomfy.node_approvals import CodeConsentRequired

    try:
        _reviewed_dependencies(entry)
    except CodeConsentRequired:
        # Diagnostic callers also inspect target lock rows; unreviewed
        # modifications are dirty, not verified patches.
        return 0
    patches = {patch.path: patch.sha256 for patch in entry.patches}
    count = 0
    for line in porcelain.splitlines():
        if not line.startswith(" M "):
            return 0
        relative = line[3:]
        if relative.startswith('"') or relative not in patches:
            return 0
        path = pack_dir / relative
        try:
            # Refuse symlinks anywhere in the path, including parent directories.
            if any(part.is_symlink() for part in (path, *list(path.parents)[:len(Path(relative).parts) - 1])):
                return 0
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != patches[relative]:
                return 0
        except OSError:
            return 0
        count += 1
    return count


def _git_porcelain(pack_dir: Path, runner: Runner, *, include_ignored: bool = False) -> str | None:
    args = ["status", "--porcelain"]
    if include_ignored:
        # NUL delimiters avoid Git's quoted-path encoding, including spaces
        # and non-ASCII directory names. Other callers retain line porcelain.
        args.extend(["--ignored", "--untracked-files=all", "-z"])
    return _git(pack_dir, args, runner)
def _git_origin(pack_dir: Path, runner: Runner) -> str | None: return (_git(pack_dir, ["config", "--get", "remote.origin.url"], runner) or "").strip() or None
def _git_head(pack_dir: Path, runner: Runner) -> str | None: return (_git(pack_dir, ["rev-parse", "HEAD"], runner) or "").strip() or None
def _normalize_git_remote(value: str) -> str:
    cleaned = value.strip().rstrip("/")
    scp = re.fullmatch(r"git@([^/:]+):(.+)", cleaned)
    if scp is not None:
        cleaned = f"https://{scp.group(1)}/{scp.group(2)}"
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    # Preserve path case, userinfo and transport; only scheme and host
    # are case insensitive (with the established scp-style Git alias).
    match = re.fullmatch(r"([A-Za-z][A-Za-z0-9+.-]*)://([^/?#]+)(.*)", cleaned)
    if match is None:
        return cleaned
    scheme, authority, tail = match.groups()
    userinfo, separator, host = authority.rpartition("@")
    return f"{scheme.casefold()}://{userinfo}{separator}{host.casefold()}{tail}"
def _known_schema_classes(path: Path = Path("node_index.json")) -> set[str]:
    path = _resolve_node_index_path(path)
    if not path.exists():
        from vibecomfy.schema import get_authoring_schema_provider

        return set(get_authoring_schema_provider(node_index_path=path).schemas())
    try: rows = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc: raise ValueError(f"node_index.json at {path} is not valid JSON: {exc}") from exc
    except OSError as exc: raise ValueError(f"failed to read node_index.json at {path}: {exc}") from exc
    if not isinstance(rows, list): raise ValueError(f"node_index.json at {path} must contain a list of node schemas")
    return {str(row.get("class_type")) for row in rows if isinstance(row, dict) and row.get("class_type")}
def _resolve_node_index_path(path: Path) -> Path:
    if path.is_absolute() or path.exists() or path != Path("node_index.json"):
        return path
    repo_index = Path(__file__).resolve().parent.parent.parent / "node_index.json"
    return repo_index if repo_index.exists() else path
def _error_text(exc: BaseException) -> str | None: return next((text.strip() for value in (getattr(exc, "stderr", None), getattr(exc, "stdout", None)) if isinstance((text := value.decode(errors="replace") if isinstance(value, bytes) else value), str) and text.strip()), str(exc) or None)
