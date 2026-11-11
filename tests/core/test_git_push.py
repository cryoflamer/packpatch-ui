from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from packpatch_ui.core.git_push import (
    PUSH_TIMEOUT_SECONDS,
    PushUnavailable,
    current_push_target,
    push_current_branch,
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def setup_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    git(repo, "config", "user.name", "Push Test")
    git(repo, "config", "user.email", "push@example.invalid")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "Initial commit")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "main")
    return repo, remote


def commit(repo: Path, text: str) -> str:
    (repo / "README.md").write_text(text + "\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", text)
    return git(repo, "rev-parse", "HEAD")


def test_push_only_current_tracking_branch_without_force_or_upstream_modification(tmp_path: Path) -> None:
    repo, remote = setup_repo(tmp_path)
    git(repo, "checkout", "-b", "unrelated")
    other_head = commit(repo, "unrelated")
    git(repo, "push", "-u", "origin", "unrelated")
    git(repo, "checkout", "main")
    head = commit(repo, "new main commit")
    git(repo, "config", "push.default", "matching")

    target = current_push_target(repo)
    assert target.description == "main → origin/main"
    result = push_current_branch(repo, expected_target=target)

    assert result.succeeded, result.stderr
    assert git(remote, "rev-parse", "refs/heads/main") == head
    assert git(remote, "rev-parse", "refs/heads/unrelated") == other_head
    assert git(repo, "rev-parse", "HEAD") == head


def test_no_remote_tracking_branch_and_detached_head_are_not_pushed(tmp_path: Path) -> None:
    repo, remote = setup_repo(tmp_path)
    git(repo, "checkout", "-b", "untracked")
    with pytest.raises(PushUnavailable, match="upstream"):
        current_push_target(repo)
    assert not push_current_branch(repo).succeeded
    git(repo, "checkout", "--detach", "HEAD")
    with pytest.raises(PushUnavailable, match="detached"):
        current_push_target(repo)
    assert not push_current_branch(repo).succeeded
    assert git(remote, "rev-parse", "refs/heads/main") != ""


def test_upstream_change_cancels_confirmed_push(tmp_path: Path) -> None:
    repo, remote = setup_repo(tmp_path)
    target = current_push_target(repo)
    head = commit(repo, "local")
    git(repo, "config", "branch.main.merge", "refs/heads/other")
    result = push_current_branch(repo, expected_target=target)
    assert not result.succeeded
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(remote, "rev-parse", "refs/heads/main") != head


def test_non_fast_forward_rejected_without_losing_local_commit(tmp_path: Path) -> None:
    repo, remote = setup_repo(tmp_path)
    competing = tmp_path / "competing"
    git(tmp_path, "clone", str(remote), str(competing))
    git(competing, "checkout", "-b", "main", "origin/main")
    git(competing, "config", "user.name", "Other")
    git(competing, "config", "user.email", "other@example.invalid")
    remote_head = commit(competing, "remote ahead")
    git(competing, "push", "origin", "main")
    head = commit(repo, "local diverged")

    result = push_current_branch(repo)

    assert not result.succeeded
    assert git(remote, "rev-parse", "refs/heads/main") == remote_head
    assert git(repo, "rev-parse", "HEAD") == head


def test_git_push_timeout_is_bounded_and_non_interactive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _ = setup_repo(tmp_path)
    seen = {}

    def time_out(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs["env"]
        seen["timeout"] = kwargs["timeout"]
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    target = current_push_target(repo)
    monkeypatch.setattr("packpatch_ui.core.git_push.current_push_target", lambda *_: target)
    monkeypatch.setattr("packpatch_ui.core.git_push.subprocess.run", time_out)
    result = push_current_branch(repo)
    assert not result.succeeded
    assert "timed out" in result.message
    assert seen["timeout"] == PUSH_TIMEOUT_SECONDS
    assert seen["command"] == ["git", "push", "--porcelain", "--", "origin", "HEAD:refs/heads/main"]
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert seen["env"]["GCM_INTERACTIVE"] == "never"
