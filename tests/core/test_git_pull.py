from pathlib import Path

from packpatch_ui.core.git_pull import pull_current_branch
from test_git_push import setup_repo, git, commit


def remote_commit(tmp_path, remote):
    other = tmp_path / "other"
    git(tmp_path, "clone", "-b", "main", str(remote), str(other))
    git(other, "config", "user.name", "Other")
    git(other, "config", "user.email", "other@example.invalid")
    head = commit(other, "remote change")
    git(other, "push", "origin", "main")
    return head


def test_pull_fetches_even_when_cached_upstream_is_current(tmp_path: Path):
    repo, remote = setup_repo(tmp_path)
    head = remote_commit(tmp_path, remote)
    git(repo, "config", "pull.rebase", "true")
    result = pull_current_branch(repo)
    assert result.succeeded and result.updated, result.stderr
    assert git(repo, "rev-parse", "HEAD") == head
    result = pull_current_branch(repo)
    assert result.succeeded and not result.updated


def test_pull_rejects_divergence(tmp_path: Path):
    repo, remote = setup_repo(tmp_path)
    remote_commit(tmp_path, remote)
    head = commit(repo, "local change")
    assert not pull_current_branch(repo).succeeded
    assert git(repo, "rev-parse", "HEAD") == head
    assert not git(repo, "status", "--porcelain")


def test_pull_rejects_dirty_tree(tmp_path: Path):
    repo, remote = setup_repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    remote_commit(tmp_path, remote)
    (repo / "untracked").write_text("keep me")
    assert not pull_current_branch(repo).succeeded
    assert git(repo, "rev-parse", "HEAD") == head
    assert (repo / "untracked").read_text() == "keep me"


def test_pull_rejects_no_upstream_and_detached_head(tmp_path: Path):
    repo, _ = setup_repo(tmp_path)
    git(repo, "checkout", "-b", "local")
    assert not pull_current_branch(repo).succeeded
    git(repo, "checkout", "--detach", "HEAD")
    assert not pull_current_branch(repo).succeeded


def test_pull_uses_legacy_compatible_autostash_override(tmp_path, monkeypatch):
    import subprocess

    repo, remote = setup_repo(tmp_path)
    head = remote_commit(tmp_path, remote)
    git(repo, "config", "merge.autostash", "true")
    git(repo, "config", "pull.rebase", "true")
    original_run = subprocess.run
    calls = []

    def legacy_git(args, *positional, **kwargs):
        if args[0] == "git" and "pull" in args:
            calls.append(args)
            if "--no-autostash" in args:
                raise subprocess.CalledProcessError(
                    128, args, stderr="fatal: --[no-]autostash option is only valid with --rebase."
                )
        return original_run(args, *positional, **kwargs)

    monkeypatch.setattr(subprocess, "run", legacy_git)
    result = pull_current_branch(repo)
    assert result.succeeded and result.updated, result.stderr
    assert len(calls) == 1
    assert calls[0][:8] == ["git", "-c", "merge.autostash=false", "pull", "--ff-only",
                            "--no-rebase", "--no-recurse-submodules", "--"]
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "config", "merge.autostash") == "true"
