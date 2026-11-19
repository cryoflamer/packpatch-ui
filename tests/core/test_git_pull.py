from pathlib import Path

import pytest

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


def fetched_update(tmp_path):
    from packpatch_ui.core.git_fetch import fetch_current_branch
    from packpatch_ui.core.git_push import current_push_target

    repo, remote = setup_repo(tmp_path)
    head = remote_commit(tmp_path, remote)
    target = current_push_target(repo)
    result = fetch_current_branch(repo, expected_target=target)
    assert result.succeeded and result.tracking_head == head
    return repo, remote, target, head


def test_auto_pull_uses_fetched_commit_without_network(tmp_path):
    from packpatch_ui.core.git_pull import fast_forward_fetched_branch

    repo, remote, target, head = fetched_update(tmp_path)
    # The already fetched update must remain usable without a second fetch.
    remote.rename(tmp_path / 'offline.git')
    git(repo, 'config', 'merge.autostash', 'true')
    git(repo, 'config', 'merge.ff', 'false')
    result = fast_forward_fetched_branch(repo, expected_target=target, fetched_head=head)
    assert result.succeeded and result.updated, result.stderr
    assert git(repo, 'rev-parse', 'HEAD') == head
    assert git(repo, 'status', '--porcelain') == ''
    assert git(repo, 'stash', 'list') == ''
    assert git(repo, 'config', 'merge.autostash') == 'true'
    result = fast_forward_fetched_branch(repo, expected_target=target, fetched_head=head)
    assert result.succeeded and not result.updated


@pytest.mark.parametrize('condition', ['dirty', 'untracked', 'staged', 'diverged', 'operation', 'branch', 'stale'])
def test_auto_pull_rejects_unsafe_state(tmp_path, condition):
    from packpatch_ui.core.git_pull import fast_forward_fetched_branch

    repo, remote, target, head = fetched_update(tmp_path)
    if condition == 'dirty':
        (repo / 'README.md').write_text('local edits')
    elif condition in ('untracked', 'staged'):
        (repo / 'local.txt').write_text('preserve')
        if condition == 'staged':
            git(repo, 'add', 'local.txt')
    elif condition == 'diverged':
        commit(repo, 'local commit')
    elif condition == 'operation':
        (repo / '.git' / 'MERGE_HEAD').write_text(head + '\n')
    elif condition == 'branch':
        git(repo, 'checkout', '-b', 'other', '--track', 'origin/main')
    elif condition == 'stale':
        git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    before = git(repo, 'rev-parse', 'HEAD')
    status = git(repo, 'status', '--porcelain')
    result = fast_forward_fetched_branch(repo, expected_target=target, fetched_head=head)
    assert not result.succeeded and not result.updated
    assert git(repo, 'rev-parse', 'HEAD') == before
    assert git(repo, 'status', '--porcelain') == status
    assert git(repo, 'stash', 'list') == ''


def test_auto_pull_preserves_conflicting_ignored_file(tmp_path):
    from packpatch_ui.core.git_fetch import fetch_current_branch
    from packpatch_ui.core.git_pull import fast_forward_fetched_branch
    from packpatch_ui.core.git_push import current_push_target

    repo, remote = setup_repo(tmp_path)
    other = tmp_path / 'other'
    git(tmp_path, 'clone', '-b', 'main', str(remote), str(other))
    git(other, 'config', 'user.name', 'Other')
    git(other, 'config', 'user.email', 'other@example.invalid')
    (other / 'local.txt').write_text('remote')
    git(other, 'add', 'local.txt')
    git(other, 'commit', '-m', 'Track local.txt')
    git(other, 'push', 'origin', 'main')
    (repo / '.git' / 'info' / 'exclude').write_text('local.txt\n')
    (repo / 'local.txt').write_text('private')
    target = current_push_target(repo)
    fetched = fetch_current_branch(repo, expected_target=target)
    assert fetched.succeeded
    before = git(repo, 'rev-parse', 'HEAD')
    result = fast_forward_fetched_branch(repo, expected_target=target, fetched_head=fetched.tracking_head)
    assert not result.succeeded
    assert git(repo, 'rev-parse', 'HEAD') == before
    assert (repo / 'local.txt').read_text() == 'private'
