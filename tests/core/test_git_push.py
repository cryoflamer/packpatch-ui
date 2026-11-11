from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from packpatch_ui.core.git_push import (
    PUSH_TIMEOUT_SECONDS,
    PushUnavailable,
    current_push_state,
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
    assert result.pushed
    assert (result.ahead, result.behind) == (1, 0)
    assert git(remote, "rev-parse", "refs/heads/main") == head
    assert git(remote, "rev-parse", "refs/heads/unrelated") == other_head
    assert git(repo, "rev-parse", "HEAD") == head
    assert (current_push_state(repo).ahead, current_push_state(repo).behind) == (0, 0)
    assert "Already up to date" in push_current_branch(repo).message


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
    commit(repo, "local ahead")
    seen = {}
    real_run = subprocess.run

    def time_out(command, **kwargs):
        if command[:2] != ["git", "push"]:
            return real_run(command, **kwargs)
        seen["command"] = command
        seen["env"] = kwargs["env"]
        seen["timeout"] = kwargs["timeout"]
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"partial stdout", stderr=b"partial stderr")

    monkeypatch.setattr("packpatch_ui.core.git_push.subprocess.run", time_out)
    result = push_current_branch(repo)
    assert not result.succeeded
    assert "timed out" in result.message
    assert seen["timeout"] == PUSH_TIMEOUT_SECONDS
    assert seen["command"] == ["git", "push", "--porcelain", "--", "origin", "HEAD:refs/heads/main"]
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert seen["env"]["GCM_INTERACTIVE"] == "never"


def test_already_synced_branch_skips_network_and_confirmation_is_not_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, remote = setup_repo(tmp_path)
    real_run = subprocess.run
    calls = []

    def reject_push(command, **kwargs):
        if command[:2] == ["git", "push"]:
            calls.append(command)
            pytest.fail("Network push was attempted for an up-to-date branch")
        return real_run(command, **kwargs)

    monkeypatch.setattr("packpatch_ui.core.git_push.subprocess.run", reject_push)
    state = current_push_state(repo)
    assert (state.ahead, state.behind) == (0, 0)
    result = push_current_branch(repo)
    assert result.succeeded and not result.pushed
    assert "Already up to date" in result.message
    assert "local tracking ref" in result.message
    assert calls == []
    assert git(remote, "rev-parse", "refs/heads/main") == git(repo, "rev-parse", "HEAD")


def test_behind_upstream_does_not_start_a_network_push(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, remote = setup_repo(tmp_path)
    competitor = tmp_path / "competitor"
    git(tmp_path, "clone", str(remote), str(competitor))
    git(competitor, "checkout", "-b", "main", "origin/main")
    git(competitor, "config", "user.name", "Other")
    git(competitor, "config", "user.email", "other@example.invalid")
    remote_head = commit(competitor, "remote ahead")
    git(competitor, "push", "origin", "main")
    git(repo, "fetch", "origin", "main")
    real_run = subprocess.run

    def reject_push(command, **kwargs):
        if command[:2] == ["git", "push"]:
            pytest.fail("Network push was attempted with no local commits to send")
        return real_run(command, **kwargs)

    monkeypatch.setattr("packpatch_ui.core.git_push.subprocess.run", reject_push)
    state = current_push_state(repo)
    assert (state.ahead, state.behind) == (0, 1)
    result = push_current_branch(repo)
    assert result.succeeded and not result.pushed
    assert "ahead by 1 commit" in result.message
    assert git(remote, "rev-parse", "refs/heads/main") == remote_head


def test_diverged_upstream_push_is_attempted_normally_and_rejected(tmp_path: Path) -> None:
    repo, remote = setup_repo(tmp_path)
    competitor = tmp_path / "competitor"
    git(tmp_path, "clone", str(remote), str(competitor))
    git(competitor, "checkout", "-b", "main", "origin/main")
    git(competitor, "config", "user.name", "Other")
    git(competitor, "config", "user.email", "other@example.invalid")
    remote_head = commit(competitor, "remote ahead")
    git(competitor, "push", "origin", "main")
    git(repo, "fetch", "origin", "main")
    head = commit(repo, "local ahead")
    state = current_push_state(repo)
    assert (state.ahead, state.behind) == (1, 1)
    result = push_current_branch(repo)
    assert not result.succeeded
    assert (result.ahead, result.behind) == (1, 1)
    assert git(remote, "rev-parse", "refs/heads/main") == remote_head
    assert git(repo, "rev-parse", "HEAD") == head


def test_timeout_preserves_partial_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _ = setup_repo(tmp_path)
    commit(repo, "local ahead")
    real_run = subprocess.run

    def time_out(command, **kwargs):
        if command[:2] != ["git", "push"]:
            return real_run(command, **kwargs)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"partial out", stderr=b"partial err")

    monkeypatch.setattr("packpatch_ui.core.git_push.subprocess.run", time_out)
    result = push_current_branch(repo)
    assert not result.succeeded
    assert result.stdout == "partial out"
    assert result.stderr == "partial err"
    assert "Partial Git output" in result.message
    assert (result.ahead, result.behind) == (1, 0)
