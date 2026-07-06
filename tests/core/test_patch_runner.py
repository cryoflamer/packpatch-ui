from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from packpatch_ui.core.patch_runner import (
    APPLY_MODE_COMPATCH_THEN_PACKPATCH,
    APPLY_MODE_PACKPATCH_THEN_COMPATCH,
    apply_latest_patch,
    undo_last_commit,
)


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    command = ["git", *args]
    completed = subprocess.run(
        command,
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout.strip()


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    git(repo, "config", "user.name", "Local User")
    git(repo, "config", "user.email", "local@example.com")
    (repo / "example.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", "example.txt")
    git(repo, "commit", "-m", "Base commit")
    return repo


def make_packpatch(repo: Path, patch_dir: Path, replacement: str = "changed\n") -> Path:
    patch_dir.mkdir(exist_ok=True)
    target = repo / "example.txt"
    target.write_text(replacement, encoding="utf-8")
    patch_path = patch_dir / "change.patch"
    patch_path.write_text(git(repo, "diff") + "\n", encoding="utf-8")
    git(repo, "checkout", "--", "example.txt")
    return patch_path


def make_compatch(
    repo: Path,
    patch_dir: Path,
    *,
    replacement: str = "changed by compatch\n",
    author_name: str = "Patch Author",
    author_email: str = "patch@example.com",
) -> Path:
    patch_dir.mkdir(exist_ok=True)
    target = repo / "example.txt"
    target.write_text(replacement, encoding="utf-8")
    git(repo, "add", "example.txt")
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
        }
    )
    git(repo, "commit", "-m", "Compatch change", env=env)
    patch_path = patch_dir / "change.patch"
    patch_path.write_text(git(repo, "format-patch", "-1", "--stdout") + "\n", encoding="utf-8")
    git(repo, "reset", "--hard", "HEAD~1")
    return patch_path


def test_packpatch_applies_and_creates_commit(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    patch_dir = tmp_path / "patches"
    patch = make_packpatch(repo, patch_dir)

    result = apply_latest_patch(
        repo,
        patch_dir,
        patch_path=patch,
        commit_message="PackPatch change was applied",
        apply_mode=APPLY_MODE_PACKPATCH_THEN_COMPATCH,
    )

    assert result.succeeded
    assert result.was_applied
    assert result.created_commit
    assert result.applied_with == "PackPatch"
    assert (repo / "example.txt").read_text(encoding="utf-8") == "changed\n"
    assert git(repo, "log", "-1", "--format=%s") == "PackPatch change was applied"
    assert git(repo, "status", "--porcelain") == ""


def test_packpatch_repeated_apply_is_skipped(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    patch_dir = tmp_path / "patches"
    patch = make_packpatch(repo, patch_dir)
    first = apply_latest_patch(
        repo,
        patch_dir,
        patch_path=patch,
        commit_message="PackPatch change was applied",
        apply_mode=APPLY_MODE_PACKPATCH_THEN_COMPATCH,
    )
    head_after_first = git(repo, "rev-parse", "HEAD")

    second = apply_latest_patch(
        repo,
        patch_dir,
        patch_path=patch,
        commit_message="Duplicate commit must not be created",
        apply_mode=APPLY_MODE_PACKPATCH_THEN_COMPATCH,
    )

    assert first.succeeded
    assert second.succeeded
    assert not second.was_applied
    assert not second.created_commit
    assert "already appears to be applied" in second.stdout
    assert git(repo, "rev-parse", "HEAD") == head_after_first


def test_compatch_applies_with_git_am_and_overrides_author(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    patch_dir = tmp_path / "patches"
    patch = make_compatch(repo, patch_dir)

    result = apply_latest_patch(
        repo,
        patch_dir,
        patch_path=patch,
        apply_mode=APPLY_MODE_COMPATCH_THEN_PACKPATCH,
    )

    assert result.succeeded
    assert result.was_applied
    assert result.created_commit
    assert result.applied_with == "Compatсh"
    assert git(repo, "log", "-1", "--format=%s") == "Compatch change"
    assert git(repo, "log", "-1", "--format=%an <%ae>") == "Local User <local@example.com>"
    assert "Compatсh author was overridden" in result.stdout
    assert git(repo, "status", "--porcelain") == ""


def test_compatch_repeated_apply_is_skipped(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    patch_dir = tmp_path / "patches"
    patch = make_compatch(repo, patch_dir)
    first = apply_latest_patch(repo, patch_dir, patch_path=patch)
    head_after_first = git(repo, "rev-parse", "HEAD")

    second = apply_latest_patch(repo, patch_dir, patch_path=patch)

    assert first.succeeded
    assert second.succeeded
    assert not second.was_applied
    assert not second.created_commit
    assert "changes already exist" in second.stdout
    assert git(repo, "rev-parse", "HEAD") == head_after_first


def test_compatch_first_falls_back_to_packpatch_for_plain_diff(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    patch_dir = tmp_path / "patches"
    patch = make_packpatch(repo, patch_dir)

    result = apply_latest_patch(
        repo,
        patch_dir,
        patch_path=patch,
        commit_message="Fallback change was applied",
        apply_mode=APPLY_MODE_COMPATCH_THEN_PACKPATCH,
    )

    assert result.succeeded
    assert result.applied_with == "PackPatch"
    assert result.was_applied
    assert "[Compatсh] failed" in result.stdout
    assert "[PackPatch] OK" in result.stdout
    assert "Fallback result: succeeded with PackPatch" in result.stdout


def test_tracked_changes_block_apply(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    patch_dir = tmp_path / "patches"
    patch = make_packpatch(repo, patch_dir)
    (repo / "example.txt").write_text("local tracked change\n", encoding="utf-8")

    result = apply_latest_patch(repo, patch_dir, patch_path=patch)

    assert not result.succeeded
    assert result.applied_with == "safety check"
    assert "Working tree is not clean" in result.stdout
    assert (repo / "example.txt").read_text(encoding="utf-8") == "local tracked change\n"


def test_unversioned_files_block_apply_by_default(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    patch_dir = tmp_path / "patches"
    patch = make_packpatch(repo, patch_dir)
    (repo / "local.tmp").write_text("local\n", encoding="utf-8")

    result = apply_latest_patch(repo, patch_dir, patch_path=patch)

    assert not result.succeeded
    assert result.applied_with == "safety check"
    assert "Only unversioned files were found" in result.stdout
    assert "?? local.tmp" in result.stdout


def test_allowed_unversioned_files_do_not_block_apply(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    patch_dir = tmp_path / "patches"
    patch = make_packpatch(repo, patch_dir)
    (repo / "local.tmp").write_text("local\n", encoding="utf-8")

    result = apply_latest_patch(
        repo,
        patch_dir,
        patch_path=patch,
        commit_message="PackPatch change was applied",
        allow_unversioned_files=True,
    )

    assert result.succeeded
    assert result.was_applied
    assert (repo / "local.tmp").read_text(encoding="utf-8") == "local\n"
    assert git(repo, "status", "--porcelain") == "?? local.tmp"


def test_dry_run_never_changes_repository(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    patch_dir = tmp_path / "patches"
    patch = make_packpatch(repo, patch_dir)
    head_before = git(repo, "rev-parse", "HEAD")

    result = apply_latest_patch(repo, patch_dir, patch_path=patch, dry_run=True)

    assert result.succeeded
    assert not result.was_applied
    assert not result.created_commit
    assert git(repo, "rev-parse", "HEAD") == head_before
    assert (repo / "example.txt").read_text(encoding="utf-8") == "base\n"
    assert git(repo, "status", "--porcelain") == ""


def test_failed_git_am_is_aborted(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    patch_dir = tmp_path / "patches"
    patch = make_compatch(repo, patch_dir, replacement="patch version\n")
    (repo / "example.txt").write_text("conflicting version\n", encoding="utf-8")
    git(repo, "add", "example.txt")
    git(repo, "commit", "-m", "Conflicting change")

    result = apply_latest_patch(repo, patch_dir, patch_path=patch)

    assert not result.succeeded
    assert result.applied_with == "Compatсh"
    git_dir = Path(git(repo, "rev-parse", "--git-dir"))
    if not git_dir.is_absolute():
        git_dir = repo / git_dir
    assert not (git_dir / "rebase-apply").exists()
    assert git(repo, "status", "--porcelain") == ""
    assert (repo / "example.txt").read_text(encoding="utf-8") == "conflicting version\n"


def test_undo_with_stash_preserves_changes_and_untracked_files(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "example.txt").write_text("second commit\n", encoding="utf-8")
    git(repo, "add", "example.txt")
    git(repo, "commit", "-m", "Second commit")
    (repo / "local.tmp").write_text("local\n", encoding="utf-8")

    result = undo_last_commit(repo, stash_changes=True)

    assert result.reset_succeeded
    assert result.stash_succeeded
    assert result.unversioned_files == ("local.tmp",)
    assert result.stash_ref == "stash@{0}"
    assert git(repo, "log", "-1", "--format=%s") == "Base commit"
    assert git(repo, "status", "--porcelain") == ""
    assert "Second commit" not in git(repo, "log", "--format=%s")
    assert "PackPatch UI: changes after undo" in git(repo, "stash", "list")


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (APPLY_MODE_COMPATCH_THEN_PACKPATCH, "Compatсh -> PackPatch fallback"),
        (APPLY_MODE_PACKPATCH_THEN_COMPATCH, "PackPatch -> Compatсh fallback"),
    ],
)
def test_apply_context_reports_selected_mode(tmp_path: Path, mode: str, expected: str) -> None:
    repo = init_repo(tmp_path)
    patch_dir = tmp_path / "patches"
    patch = make_packpatch(repo, patch_dir)

    result = apply_latest_patch(
        repo,
        patch_dir,
        patch_path=patch,
        commit_message="Mode test was applied",
        apply_mode=mode,
    )

    assert result.succeeded
    assert f"Apply mode: {expected}" in result.stdout
