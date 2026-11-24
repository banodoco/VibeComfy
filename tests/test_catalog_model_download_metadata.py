"""LE-8: download metadata belongs to the existing source catalog."""
from vibecomfy.node_packs import CustomNodePack, LockEntry, get_known_node_packs, write_lockfile


SAM = "ComfyUI-SAM-Audio"
REPO = "https://github.com/ethanfel/ComfyUI-SAM-Audio"


def _pack(lock):
    return next(pack for pack in get_known_node_packs(lock) if pack.name == SAM)


def test_catalog_records_source_backed_sam_download_hint(tmp_path):
    pack = _pack(tmp_path / "missing.lock")
    assert pack.downloads_own_models is True
    assert pack.model_download_bytes_hint == 14_861_356_211
    assert {"SAMAudioPipelineLoader", "SAMAudioTextSeparator"} <= pack.classes


def test_unknown_pack_is_not_classified_by_name():
    pack = CustomNodePack("DownloadAndLoadFake", "https://github.com/example/fake", frozenset({"DownloadModel"}))
    assert pack.downloads_own_models is None
    assert pack.model_download_bytes_hint is None


def test_same_repo_lock_enrichment_preserves_catalog_hint(tmp_path):
    lock = tmp_path / "target.lock"
    write_lockfile([LockEntry(name=SAM, url=REPO, commit="a" * 40,
                              class_set=("SAMAudioPipelineLoader",))], lock)
    pack = _pack(lock)
    assert pack.classes == frozenset({"SAMAudioPipelineLoader"})
    assert pack.downloads_own_models is True
    assert pack.model_download_bytes_hint == 14_861_356_211


def test_different_repo_same_name_does_not_inherit_download_facts(tmp_path):
    lock = tmp_path / "target.lock"
    write_lockfile([LockEntry(name=SAM, url="https://github.com/example/fork", commit="b" * 40,
                              class_set=("OtherNode",))], lock)
    pack = _pack(lock)
    assert pack.classes == frozenset({"OtherNode"})
    assert pack.downloads_own_models is None
    assert pack.model_download_bytes_hint is None
