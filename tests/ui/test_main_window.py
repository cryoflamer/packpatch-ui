from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from packpatch_ui.core.git_repo import GitRepoInfo
from packpatch_ui.services.settings_store import AppSession
from packpatch_ui.ui.main_window import LogSeverity, LogVerbosity, MainWindow


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init")
    git(path, "symbolic-ref", "HEAD", "refs/heads/main")
    git(path, "config", "user.name", "Test User")
    git(path, "config", "user.email", "test@example.invalid")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-m", "Initial commit")
    return path


@pytest.fixture
def window(qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MainWindow:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    instance = MainWindow()
    instance._autosave_timer.stop()
    instance._repository_watch_timer.stop()
    qtbot.addWidget(instance)
    return instance


def test_create_pack_busy_state_is_active_during_operation_and_restored(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[bool, str, bool]] = []

    def fake_create_pack_impl() -> None:
        observed.append(
            (
                window.create_pack_button.isEnabled(),
                window.create_pack_button.text(),
                window.clear_session_files_button.isEnabled(),
            )
        )
        raise RuntimeError("boom")

    monkeypatch.setattr(window, "_create_pack_impl", fake_create_pack_impl)

    with pytest.raises(RuntimeError, match="boom"):
        window._create_pack()

    assert observed == [(False, "Creating...", False)]
    assert window.create_pack_button.isEnabled()
    assert window.create_pack_button.text() == "Create pack"
    assert window.clear_session_files_button.isEnabled()


def test_apply_busy_state_disables_conflicting_actions_and_is_restored(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[bool, ...]] = []

    def fake_apply_impl(*, dry_run: bool) -> None:
        assert not dry_run
        observed.append(
            (
                window.apply_latest_patch_button.isEnabled(),
                window.check_latest_patch_button.isEnabled(),
                window.dry_run_patch_button.isEnabled(),
                window.undo_last_commit_button.isEnabled(),
                window.deploy_repo_button.isEnabled(),
                window.create_pack_button.isEnabled(),
                window.clear_session_files_button.isEnabled(),
            )
        )
        assert window.apply_latest_patch_button.text() == "Applying..."
        raise RuntimeError("boom")

    monkeypatch.setattr(window, "_apply_latest_patch_impl", fake_apply_impl)

    with pytest.raises(RuntimeError, match="boom"):
        window._apply_latest_patch(dry_run=False)

    assert observed == [(False, False, False, False, False, False, False)]
    assert window.apply_latest_patch_button.isEnabled()
    assert window.apply_latest_patch_button.text() == "Apply patch"
    assert window.create_pack_button.isEnabled()
    assert window.clear_session_files_button.isEnabled()


def test_status_log_filters_details_and_debug_but_keeps_warnings(window: MainWindow) -> None:
    window._set_log_verbosity("status")
    window._append_log("status message", verbosity=LogVerbosity.STATUS)
    window._append_log("details message", verbosity=LogVerbosity.DETAILS)
    window._append_log("debug message", verbosity=LogVerbosity.DEBUG)
    window._append_log(
        "warning detail",
        verbosity=LogVerbosity.DEBUG,
        severity=LogSeverity.WARNING,
    )

    text = window.log.toPlainText()
    assert "status message" in text
    assert "details message" not in text
    assert "debug message" not in text
    assert "warning detail" in text


def test_switching_to_debug_rerenders_previously_hidden_entries(window: MainWindow) -> None:
    window._set_log_verbosity("status")
    window._append_log("hidden details", verbosity=LogVerbosity.DETAILS)
    window._append_log("hidden debug", verbosity=LogVerbosity.DEBUG)

    assert "hidden details" not in window.log.toPlainText()
    assert "hidden debug" not in window.log.toPlainText()

    window._set_log_verbosity("debug")

    text = window.log.toPlainText()
    assert "hidden details" in text
    assert "hidden debug" in text


def test_log_verbosity_is_restored_per_session(window: MainWindow) -> None:
    window._session_store.upsert_session(AppSession(name="details", log_verbosity="details"))
    window._session_store.upsert_session(AppSession(name="debug", log_verbosity="debug"))

    window._load_session_by_name("details")
    assert window._current_log_verbosity_name() == "details"

    window._load_session_by_name("debug")
    assert window._current_log_verbosity_name() == "debug"


def test_clear_session_files_requires_confirmation_and_preserves_files_on_cancel(
    window: MainWindow,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = init_repo(tmp_path / "repo-cancel")
    pack_dir = repo / "chatgpt-packs"
    pack_dir.mkdir()
    pack = pack_dir / "chatgpt-pack-full-demo-20260706-1200.tar.gz"
    pack.write_bytes(b"pack")
    patch_dir = tmp_path / "patches-cancel"
    patch_dir.mkdir()
    patch = patch_dir / "change.patch"
    patch.write_text("patch\n", encoding="utf-8")

    window._repo_info = GitRepoInfo(root=repo, branch="main", is_dirty=False)
    window.patch_dir_edit.setText(str(patch_dir))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)

    window._clear_session_files()

    assert pack.exists()
    assert patch.exists()
    assert window.statusBar().currentMessage() == "Session file cleanup cancelled"


def test_clear_session_files_deletes_packs_exports_and_patches(
    window: MainWindow,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = init_repo(tmp_path / "repo-current")
    pack_dir = repo / "chatgpt-packs"
    pack_dir.mkdir()
    pack = pack_dir / "chatgpt-pack-full-demo-20260706-1201.tar.gz"
    pack.write_bytes(b"pack")
    export_dir = tmp_path / "exports-current"
    export_dir.mkdir()
    exported = export_dir / pack.name
    exported.write_bytes(b"pack")
    patch_dir = tmp_path / "patches-current"
    patch_dir.mkdir()
    patch = patch_dir / "change.patch"
    patch.write_text("patch\n", encoding="utf-8")

    window._repo_info = GitRepoInfo(root=repo, branch="main", is_dirty=False)
    window.patch_dir_edit.setText(str(patch_dir))
    window.export_dir_edit.setText(str(export_dir))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    window._clear_session_files()

    assert not pack.exists()
    assert not exported.exists()
    assert not patch.exists()
    text = window.log.toPlainText()
    assert "session files cleared" in text


def test_clear_all_session_files_deletes_unique_artifacts_and_preserves_sessions(
    window: MainWindow,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_a = init_repo(tmp_path / "repo-a")
    repo_b = init_repo(tmp_path / "repo-b")
    pack_dir_a = repo_a / "chatgpt-packs"
    pack_dir_b = repo_b / "chatgpt-packs"
    pack_dir_a.mkdir()
    pack_dir_b.mkdir()
    pack_a = pack_dir_a / "chatgpt-pack-full-a-20260706-1202.tar.gz"
    pack_b = pack_dir_b / "chatgpt-pack-full-b-20260706-1203.tar.gz"
    pack_a.write_bytes(b"a")
    pack_b.write_bytes(b"b")

    export_dir = tmp_path / "shared-exports"
    export_dir.mkdir()
    exported_a = export_dir / pack_a.name
    exported_a.write_bytes(b"a")

    patch_dir = tmp_path / "shared-patches"
    patch_dir.mkdir()
    patch = patch_dir / "shared.patch"
    patch.write_text("patch\n", encoding="utf-8")

    window._session_store.upsert_session(
        AppSession(
            name="alpha",
            repo_path=str(repo_a),
            patch_dir=str(patch_dir),
            export_dir=str(export_dir),
        )
    )
    window._session_store.upsert_session(
        AppSession(
            name="beta",
            repo_path=str(repo_b),
            patch_dir=str(patch_dir),
            export_dir=str(export_dir),
        )
    )
    window._current_session_name = "alpha"
    window.repo_path_edit.setText(str(repo_a))
    window.patch_dir_edit.setText(str(patch_dir))
    window.export_dir_edit.setText(str(export_dir))

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    window._clear_all_sessions_files()

    assert not pack_a.exists()
    assert not pack_b.exists()
    assert not exported_a.exists()
    assert not patch.exists()
    assert window._session_store.get_session("alpha") is not None
    assert window._session_store.get_session("beta") is not None
    assert "all saved sessions processed" in window.log.toPlainText()
