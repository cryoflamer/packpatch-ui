from __future__ import annotations

import os
from pathlib import Path

import pytest

from packpatch_ui.core.artifacts import delete_artifact, list_pack_archives, list_patch_files


def touch_with_mtime(path: Path, content: str, timestamp: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.utime(path, (timestamp, timestamp))


def test_pack_and_patch_lists_match_patterns_and_sort_newest_first(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    packs = repo / "chatgpt-packs"
    patches = tmp_path / "patches"
    touch_with_mtime(packs / "chatgpt-pack-full-demo-older.tar.gz", "old", 100)
    touch_with_mtime(packs / "chatgpt-pack-full-demo-newer.tar.gz", "newer", 200)
    touch_with_mtime(packs / "unrelated.tar.gz", "ignore", 300)
    touch_with_mtime(patches / "one.patch", "patch", 100)
    touch_with_mtime(patches / "two.diff", "diff-data", 200)
    touch_with_mtime(patches / "notes.txt", "ignore", 300)

    pack_items = list_pack_archives(repo)
    patch_items = list_patch_files(patches)

    assert [item.path.name for item in pack_items] == [
        "chatgpt-pack-full-demo-newer.tar.gz",
        "chatgpt-pack-full-demo-older.tar.gz",
    ]
    assert [item.path.name for item in patch_items] == ["two.diff", "one.patch"]
    assert pack_items[0].size_bytes == 5
    assert pack_items[0].display_name.endswith("(5 B)")


def test_artifact_size_label_uses_binary_units(tmp_path: Path) -> None:
    path = tmp_path / "patches" / "large.patch"
    path.parent.mkdir()
    path.write_bytes(b"x" * 1536)

    item = list_patch_files(path.parent)[0]

    assert item.size_label == "1.5 KB"


def test_delete_artifact_removes_file_and_missing_file_is_noop(tmp_path: Path) -> None:
    path = tmp_path / "change.patch"
    path.write_text("patch", encoding="utf-8")

    assert delete_artifact(path) == [path]
    assert not path.exists()
    assert delete_artifact(path) == []


def test_delete_artifact_rejects_directory(tmp_path: Path) -> None:
    directory = tmp_path / "artifact.patch"
    directory.mkdir()

    with pytest.raises(ValueError, match="not a file"):
        delete_artifact(directory)
