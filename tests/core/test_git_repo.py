from __future__ import annotations

import subprocess
from pathlib import Path

from packpatch_ui.core.git_repo import (
    find_git_root,
    list_changed_files,
    list_recent_commits,
    list_repo_files,
    read_git_repo_info,
    read_git_repo_state_snapshot,
)


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
    git(repo, "config", "user.name", "Repo Test User")
    git(repo, "config", "user.email", "repo-test@example.invalid")
    (repo / "src").mkdir()
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    (repo / "src" / "app.py").write_text("print('base')\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Initial commit")
    return repo


def test_find_git_root_works_from_nested_directory_and_nonrepo_returns_none(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    nested = repo / "src" / "nested"
    nested.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    assert find_git_root(nested) == repo
    assert find_git_root(outside) is None


def test_repository_snapshot_reports_branch_head_and_dirty_state(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")

    clean = read_git_repo_state_snapshot(repo)
    assert clean is not None
    assert clean.root == repo
    assert clean.branch == "main"
    assert clean.head == head
    assert not clean.is_dirty

    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    dirty = read_git_repo_state_snapshot(repo)
    assert dirty is not None
    assert dirty.is_dirty
    assert "README.md" in dirty.status_porcelain

    info = read_git_repo_info(repo)
    assert info is not None
    assert info.root == repo
    assert info.branch == "main"
    assert info.is_dirty


def test_snapshot_detects_head_and_branch_transitions(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    before = read_git_repo_state_snapshot(repo)
    assert before is not None

    git(repo, "checkout", "-b", "feature")
    (repo / "README.md").write_text("feature\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "Feature commit")
    after = read_git_repo_state_snapshot(repo)

    assert after is not None
    assert after.branch == "feature"
    assert after.head != before.head
    assert after.status_porcelain == ""


def test_changed_and_repo_file_lists_handle_tracked_staged_untracked_and_ignored(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / ".gitignore").write_text("ignored.tmp\n", encoding="utf-8")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-m", "Ignore rule was added")

    (repo / "README.md").write_text("unstaged\n", encoding="utf-8")
    (repo / "src" / "app.py").write_text("print('staged')\n", encoding="utf-8")
    git(repo, "add", "src/app.py")
    (repo / "local.tmp").write_text("local\n", encoding="utf-8")
    (repo / "ignored.tmp").write_text("ignored\n", encoding="utf-8")

    assert list_changed_files(repo) == ["README.md", "local.tmp", "src/app.py"]
    assert list_repo_files(repo, include_untracked=False) == [".gitignore", "README.md", "src/app.py"]
    assert list_repo_files(repo, include_untracked=True) == [
        ".gitignore",
        "README.md",
        "local.tmp",
        "src/app.py",
    ]


def test_recent_commits_are_returned_newest_first_and_respect_limit(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    for number in range(1, 4):
        (repo / "README.md").write_text(f"{number}\n", encoding="utf-8")
        git(repo, "add", "README.md")
        git(repo, "commit", "-m", f"Commit {number}")

    commits = list_recent_commits(repo, limit=2)

    assert len(commits) == 2
    assert commits[0].subject.endswith("Commit 3")
    assert commits[1].subject.endswith("Commit 2")
    assert commits[0].display_name.startswith(commits[0].short_hash)
