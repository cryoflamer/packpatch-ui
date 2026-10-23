from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from packpatch_ui.core.artifacts import list_patch_files
from packpatch_ui.core.zip_patch import extracted_patch, patch_members


def make_zip(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as handle:
        for name, content in files.items():
            handle.writestr(name, content)
    return path


def test_zip_listing_is_opt_in(tmp_path: Path) -> None:
    make_zip(tmp_path / "example.zip", {"fix.patch": "patch contents"})
    (tmp_path / "normal.patch").write_text("diff", encoding="utf-8")
    assert len(list_patch_files(tmp_path)) == 1
    assert {item.path.suffix for item in list_patch_files(tmp_path, include_zip=True)} == {".zip", ".patch"}


def test_single_member_extraction_is_temporary(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "fix.zip", {"nested/fix.patch": "patch contents", "notes.txt": "ignored"})
    assert patch_members(archive) == ["nested/fix.patch"]
    with extracted_patch(archive, "nested/fix.patch") as extracted:
        assert extracted.read_text() == "patch contents"
        location = extracted
    assert not location.exists()


def test_multiple_members_can_be_selected(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "fix.zip", {"a.patch": "a", "b.diff": "b"})
    assert patch_members(archive) == ["a.patch", "b.diff"]
    with extracted_patch(archive, "b.diff") as extracted:
        assert extracted.read_text() == "b"


def test_unsafe_members_are_excluded(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "fix.zip", {"../../evil.patch": "x", "/abs.patch": "x", "ok.patch": "ok", "bad\\name.patch": "x"})
    assert patch_members(archive) == ["ok.patch"]
    with pytest.raises(ValueError, match="Invalid"):
        with extracted_patch(archive, "../../evil.patch"):
            pass


def test_corrupt_zip_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    archive.write_bytes(b"not zip")
    with pytest.raises(ValueError, match="Cannot read"):
        patch_members(archive)


def test_non_patch_zip_does_not_offer_members(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "none.zip", {"README.md": "hi"})
    assert patch_members(archive) == []


def test_only_zip_archives_containing_usable_patches_are_listed(tmp_path: Path) -> None:
    valid = make_zip(tmp_path / "patches.zip", {"nested/fix.patch": "patch"})
    make_zip(tmp_path / "documents.zip", {"paper.pdf": "content"})
    make_zip(tmp_path / "unsafe.zip", {"../../outside.patch": "malicious"})
    (tmp_path / "broken.zip").write_bytes(b"not a zip")
    (tmp_path / "ordinary.diff").write_text("diff", encoding="utf-8")

    listed = {item.path for item in list_patch_files(tmp_path, include_zip=True)}
    assert listed == {valid, tmp_path / "ordinary.diff"}
    assert {item.path for item in list_patch_files(tmp_path)} == {tmp_path / "ordinary.diff"}


def test_patch_cleanup_does_not_delete_unrelated_zip_files(tmp_path: Path) -> None:
    from packpatch_ui.core.artifacts import delete_artifact

    patch_zip = make_zip(tmp_path / "fix.zip", {"fix.patch": "patch"})
    ordinary_zip = make_zip(tmp_path / "photos.zip", {"photo.png": "data"})
    broken_zip = tmp_path / "broken.zip"
    broken_zip.write_bytes(b"broken")

    for item in list_patch_files(tmp_path, include_zip=True):
        delete_artifact(item.path)

    assert not patch_zip.exists()
    assert ordinary_zip.exists()
    assert broken_zip.exists()
