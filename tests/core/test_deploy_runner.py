from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from packpatch_ui.core.deploy_runner import deploy_repo


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    git(repo, "config", "user.name", "Deploy Test User")
    git(repo, "config", "user.email", "deploy-test@example.invalid")
    (repo / "tracked.txt").write_text("committed\n", encoding="utf-8")
    (repo / "dir").mkdir()
    (repo / "dir" / "nested.txt").write_text("nested\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Deploy source was added")
    return repo


def test_deploy_copies_committed_head_only_and_removes_stale_target_files(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    target = tmp_path / "deploy"
    target.mkdir()
    (target / "stale.txt").write_text("stale\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("working tree change\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")

    result = deploy_repo(repo, target)

    assert result.succeeded
    assert (target / "tracked.txt").read_text(encoding="utf-8") == "committed\n"
    assert (target / "dir" / "nested.txt").read_text(encoding="utf-8") == "nested\n"
    assert not (target / "untracked.txt").exists()
    assert not (target / "stale.txt").exists()
    assert "git" in " ".join(result.command)
    assert "archive" in result.command
    assert "rsync" in " ".join(result.command)


def test_deploy_reports_git_archive_failure_for_non_repository_source(tmp_path: Path) -> None:
    source = tmp_path / "plain"
    target = tmp_path / "deploy"
    source.mkdir()

    result = deploy_repo(source, target)

    assert not result.succeeded
    assert result.returncode != 0
    assert result.stderr


@pytest.mark.parametrize("target_kind", ["same", "inside", "contains"])
def test_deploy_rejects_overlapping_source_and_target_paths(tmp_path: Path, target_kind: str) -> None:
    repo = init_repo(tmp_path)
    if target_kind == "same":
        target = repo
    elif target_kind == "inside":
        target = repo / "deploy"
    else:
        target = tmp_path

    with pytest.raises(ValueError):
        deploy_repo(repo, target)


def test_deploy_rejects_missing_or_non_directory_source(tmp_path: Path) -> None:
    target = tmp_path / "deploy"
    missing = tmp_path / "missing"
    file_source = tmp_path / "source.txt"
    file_source.write_text("not a dir\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source does not exist"):
        deploy_repo(missing, target)
    with pytest.raises(ValueError, match="source is not a directory"):
        deploy_repo(file_source, target)
