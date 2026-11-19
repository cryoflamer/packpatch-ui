from packpatch_ui.core.git_fetch import fetch_current_branch
from packpatch_ui.core.git_push import current_push_state, current_push_target
from test_git_pull import remote_commit
from test_git_push import setup_repo, git, commit


def test_fetch_updates_tracking_without_touching_dirty_tree(tmp_path):
    repo, remote = setup_repo(tmp_path)
    before = git(repo, 'rev-parse', 'HEAD')
    head = remote_commit(tmp_path, remote)
    (repo / 'README.md').write_text('local edits')
    assert current_push_state(repo).behind == 0
    result = fetch_current_branch(repo, expected_target=current_push_target(repo))
    assert result.succeeded, result.message
    assert git(repo, 'rev-parse', '@{upstream}') == head
    assert git(repo, 'rev-parse', 'HEAD') == before
    assert (repo / 'README.md').read_text() == 'local edits'
    assert current_push_state(repo).behind == 1


def test_fetch_detects_divergence(tmp_path):
    repo, remote = setup_repo(tmp_path)
    remote_commit(tmp_path, remote)
    head = commit(repo, 'local')
    assert fetch_current_branch(repo, expected_target=current_push_target(repo)).succeeded
    state = current_push_state(repo)
    assert (state.ahead, state.behind) == (1, 1)
    assert git(repo, 'rev-parse', 'HEAD') == head


def test_fetch_rejects_changed_branch(tmp_path):
    repo, remote = setup_repo(tmp_path)
    target = current_push_target(repo)
    git(repo, 'checkout', '-b', 'other')
    assert not fetch_current_branch(repo, expected_target=target).succeeded


def test_fetch_failure_keeps_cached_ref(tmp_path):
    repo, remote = setup_repo(tmp_path)
    before = git(repo, 'rev-parse', '@{upstream}')
    git(repo, 'remote', 'set-url', 'origin', str(tmp_path / 'missing'))
    result = fetch_current_branch(repo, expected_target=current_push_target(repo))
    assert not result.succeeded
    assert git(repo, 'rev-parse', '@{upstream}') == before
