from __future__ import annotations

from types import SimpleNamespace
import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from packpatch_ui.core.git_repo import GitRepoInfo
from packpatch_ui.core.pack_runner import PackResult
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


def test_zip_patch_setting_controls_listing_and_persists(window: MainWindow, tmp_path: Path) -> None:
    import zipfile

    archive = tmp_path / "fix.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("fix.patch", "sample patch")
    window.patch_dir_edit.setText(str(tmp_path))
    window.accept_zip_patches_check.setChecked(True)
    window._refresh_artifact_lists()
    assert window.patch_list.count() == 1
    assert window._current_session_snapshot(
        window.session_combo.currentText()
    ).accept_zip_patches is True

    window.accept_zip_patches_check.setChecked(False)
    assert window.patch_list.count() == 0
    assert window._current_session_snapshot(
        window.session_combo.currentText()
    ).accept_zip_patches is False


def test_zip_patch_resolves_member_until_action_finishes(window: MainWindow, tmp_path: Path) -> None:
    import zipfile

    archive = tmp_path / "fix.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("nested/fix.patch", "patch body")
    with window._resolved_patch(archive) as resolved:
        assert resolved is not None
        assert resolved.read_text() == "patch body"
        extracted_path = resolved
    assert not extracted_path.exists()


def _prepare_export_pack(window: MainWindow, tmp_path: Path) -> tuple[Path, Path]:
    repo = init_repo(tmp_path / "export-repo")
    archive_dir = repo / "chatgpt-packs"
    archive_dir.mkdir()
    archive = archive_dir / "chatgpt-pack-full-export-20261111-0840.tar.gz"
    archive.write_bytes(b"source content")
    export_dir = tmp_path / "export-destination"
    window._repo_info = GitRepoInfo(root=repo, branch="main", is_dirty=False)
    window.export_dir_edit.setText(str(export_dir))
    window._refresh_artifact_lists()
    assert window.pack_list.count() == 1
    return archive, export_dir


def test_manual_export_works_with_auto_export_disabled(window: MainWindow, tmp_path: Path) -> None:
    archive, export_dir = _prepare_export_pack(window, tmp_path)
    window.auto_export_pack_check.setChecked(False)
    assert window.export_pack_button.isEnabled()

    window.export_pack_button.click()

    assert (export_dir / archive.name).read_bytes() == b"source content"
    assert archive.exists()
    assert window.statusBar().currentMessage() == "Pack exported"


def test_manual_export_overwrite_requires_confirmation(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, export_dir = _prepare_export_pack(window, tmp_path)
    export_dir.mkdir()
    target = export_dir / archive.name
    target.write_bytes(b"previous content")
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)

    window._export_selected_pack()
    assert target.read_bytes() == b"previous content"
    assert window.statusBar().currentMessage() == "Pack export cancelled"

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window._export_selected_pack()
    assert target.read_bytes() == b"source content"


def test_manual_export_requires_one_selected_pack(window: MainWindow, tmp_path: Path) -> None:
    archive, export_dir = _prepare_export_pack(window, tmp_path)
    other = archive.parent / "chatgpt-pack-full-other-20261111-0841.tar.gz"
    other.write_bytes(b"other")
    window._refresh_artifact_lists()
    window.pack_list.clearSelection()
    assert not window.export_pack_button.isEnabled()
    window._export_selected_pack()
    assert not export_dir.exists()

    window.pack_list.item(0).setSelected(True)
    window.pack_list.item(1).setSelected(True)
    assert not window.export_pack_button.isEnabled()
    window._export_selected_pack()
    assert not export_dir.exists()


def test_manual_export_skips_same_source_destination(window: MainWindow, tmp_path: Path) -> None:
    archive, _ = _prepare_export_pack(window, tmp_path)
    window.export_dir_edit.setText(str(archive.parent))
    window._export_selected_pack()
    assert archive.read_bytes() == b"source content"
    assert window.statusBar().currentMessage() == "Pack is already in the export directory"


def test_manual_export_button_disabled_during_pack_and_apply(window: MainWindow, tmp_path: Path) -> None:
    _prepare_export_pack(window, tmp_path)
    assert window.export_pack_button.isEnabled()
    window._set_pack_busy(True)
    assert not window.export_pack_button.isEnabled()
    window._set_pack_busy(False)
    assert window.export_pack_button.isEnabled()
    window._set_apply_busy(True)
    assert not window.export_pack_button.isEnabled()
    window._set_apply_busy(False)
    assert window.export_pack_button.isEnabled()


def test_export_new_pack_creates_export_only_with_current_settings(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path / "fresh-export-repo")
    export_dir = tmp_path / "fresh-exports"
    window._repo_info = GitRepoInfo(root=repo, branch="main", is_dirty=False)
    window.export_dir_edit.setText(str(export_dir))
    window.auto_export_pack_check.setChecked(False)
    window.git_history_depth_spin.setValue(3)
    window.include_sensitive_files_check.setChecked(True)
    window.task_name_edit.setText("on-demand")
    window.pack_mode_combo.setCurrentIndex(window.pack_mode_combo.findData("full"))
    seen = []

    def fake_create_pack(root, mode, task, selected, **kwargs):
        assert root == repo
        assert mode == "full"
        assert task == "on-demand"
        assert kwargs["history_depth"] == 3
        assert kwargs["include_sensitive"] is True
        assert kwargs["include_unversioned"] is False
        output_dir = kwargs["output_dir"]
        assert output_dir.is_dir()
        assert output_dir.parent == export_dir
        archive = output_dir / "chatgpt-pack-full-on-demand-20261111-1000.tar.gz"
        archive.write_bytes(b"fresh export only")
        seen.append(output_dir)
        return PackResult(command=["bash", "pack"], returncode=0, stdout=str(archive), stderr="")

    monkeypatch.setattr("packpatch_ui.ui.main_window.create_pack", fake_create_pack)
    window.export_new_pack_button.click()

    target = export_dir / "chatgpt-pack-full-on-demand-20261111-1000.tar.gz"
    assert target.read_bytes() == b"fresh export only"
    assert not (repo / "chatgpt-packs").exists()
    assert not seen[0].exists()  # temporary archive and directory were removed
    assert window.pack_list.count() == 0
    assert window.statusBar().currentMessage() == "New pack exported"
    assert window.export_new_pack_button.isEnabled()
    assert window.export_new_pack_button.text() == "Export new pack"


@pytest.mark.parametrize("accept,expected", [(False, b"existing"), (True, b"new")])
def test_export_new_pack_requires_confirmation_before_overwriting(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, accept: bool, expected: bytes
) -> None:
    repo = init_repo(tmp_path / "overwrite-repo")
    export_dir = tmp_path / "overwrite-exports"
    export_dir.mkdir()
    filename = "chatgpt-pack-full-demo-20261111-1000.tar.gz"
    destination = export_dir / filename
    destination.write_bytes(b"existing")
    window._repo_info = GitRepoInfo(root=repo, branch="main", is_dirty=False)
    window.export_dir_edit.setText(str(export_dir))

    def fake_create_pack(root, mode, task, selected, **kwargs):
        archive = kwargs["output_dir"] / filename
        archive.write_bytes(b"new")
        return PackResult(["bash", "pack"], 0, str(archive), "")

    monkeypatch.setattr("packpatch_ui.ui.main_window.create_pack", fake_create_pack)
    responses = []

    def answer(*args, **kwargs):
        responses.append(True)
        return QMessageBox.StandardButton.Yes if accept else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", answer)
    window.export_new_pack_button.click()
    assert responses == [True]
    assert destination.read_bytes() == expected
    assert not list(export_dir.glob(".packpatch-export-*"))
    assert not (repo / "chatgpt-packs").exists()
    assert window.statusBar().currentMessage() == ("New pack exported" if accept else "Pack export cancelled")


def test_export_new_pack_failure_leaves_no_local_or_partial_export(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path / "failed-repo")
    export_dir = tmp_path / "failed-export"
    window._repo_info = GitRepoInfo(root=repo, branch="main", is_dirty=False)
    window.export_dir_edit.setText(str(export_dir))

    def fake_create_pack(root, mode, task, selected, **kwargs):
        partial = kwargs["output_dir"] / "partial.tar.gz"
        partial.write_bytes(b"partial")
        return PackResult(["bash", "pack"], 1, "", "failure")

    monkeypatch.setattr("packpatch_ui.ui.main_window.create_pack", fake_create_pack)
    window.export_new_pack_button.click()
    assert list(export_dir.iterdir()) == []
    assert not (repo / "chatgpt-packs").exists()
    assert window.statusBar().currentMessage() == "Pack export failed"


def test_export_new_pack_requires_export_dir(window: MainWindow, tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "missing-export-repo")
    window._repo_info = GitRepoInfo(root=repo, branch="main", is_dirty=False)
    window.export_dir_edit.clear()
    window.export_new_pack_button.click()
    assert window.statusBar().currentMessage() == "Export directory is empty"
    assert not (repo / "chatgpt-packs").exists()


def test_export_new_pack_button_disabled_during_create_and_apply(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert window.export_new_pack_button.isEnabled()
    window._set_pack_busy(True)
    assert not window.export_new_pack_button.isEnabled()
    assert window.export_new_pack_button.text() == "Exporting..."
    window._set_pack_busy(False)
    window._set_apply_busy(True)
    assert not window.export_new_pack_button.isEnabled()
    window._set_apply_busy(False)
    assert window.export_new_pack_button.isEnabled()
    assert window.export_new_pack_button.text() == "Export new pack"

    def fake_impl():
        assert not window.export_new_pack_button.isEnabled()
        raise RuntimeError("export failure")

    monkeypatch.setattr(window, "_export_new_pack_impl", fake_impl)
    with pytest.raises(RuntimeError, match="export failure"):
        window._export_new_pack()
    assert window.export_new_pack_button.isEnabled()


def test_export_new_pack_rename_failure_preserves_existing_file(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path / "rename-repo")
    export_dir = tmp_path / "rename-exports"
    export_dir.mkdir()
    filename = "chatgpt-pack-full-demo-20261111-1000.tar.gz"
    destination = export_dir / filename
    destination.write_bytes(b"previous")
    window._repo_info = GitRepoInfo(root=repo, branch="main", is_dirty=False)
    window.export_dir_edit.setText(str(export_dir))

    def fake_create_pack(root, mode, task, selected, **kwargs):
        archive = kwargs["output_dir"] / filename
        archive.write_bytes(b"new")
        return PackResult(["bash", "pack"], 0, str(archive), "")

    monkeypatch.setattr("packpatch_ui.ui.main_window.create_pack", fake_create_pack)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)

    def fail_replace(source, target):
        raise OSError("simulated rename error")

    monkeypatch.setattr("packpatch_ui.ui.main_window.os", SimpleNamespace(replace=fail_replace))
    window.export_new_pack_button.click()

    assert destination.read_bytes() == b"previous"
    assert not list(export_dir.glob(".packpatch-export-*"))
    assert not (repo / "chatgpt-packs").exists()
    assert window.statusBar().currentMessage() == "Pack export failed"


def test_auto_push_setting_defaults_off_and_persists_per_session(window: MainWindow) -> None:
    assert not window.auto_push_after_apply_check.isChecked()
    window.auto_push_after_apply_check.setChecked(True)
    stored = window._current_session_snapshot("push-enabled")
    assert stored.auto_push_after_apply is True
    window._session_store.upsert_session(stored)
    window.auto_push_after_apply_check.setChecked(False)
    window._current_session_name = "push-enabled"
    window._load_current_session()
    assert window.auto_push_after_apply_check.isChecked()


def test_manual_push_requires_confirmation_and_uses_confirmed_target(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packpatch_ui.core.git_push import PushResult, PushTarget

    window._repo_info = GitRepoInfo(root=tmp_path, branch="main", is_dirty=False)
    target = PushTarget("main", "origin", "refs/heads/main")
    monkeypatch.setattr("packpatch_ui.ui.main_window.current_push_target", lambda *_: target)
    pushed = []
    monkeypatch.setattr(
        "packpatch_ui.ui.main_window.push_current_branch",
        lambda root, *, expected_target=None: (pushed.append((root, expected_target)) or PushResult(True, "Pushed.")),
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    window._push_manually()
    assert pushed == []

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window._push_manually()
    assert pushed == [(tmp_path, target)]
    assert "Pushed." in window.log.toPlainText() or window.statusBar().currentMessage() == "Push completed"


@pytest.mark.parametrize(
    "succeeded,dry_run,created_commit,was_applied,expected_push",
    [
        (True, False, True, True, 1),
        (True, False, False, True, 0),
        (True, True, True, True, 0),
        (True, False, True, False, 0),
        (False, False, True, True, 0),
    ],
)
def test_auto_push_only_for_new_commit_created_by_apply(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    succeeded: bool, dry_run: bool, created_commit: bool, was_applied: bool, expected_push: int,
) -> None:
    window._repo_info = GitRepoInfo(root=tmp_path, branch="main", is_dirty=False)
    window.auto_push_after_apply_check.setChecked(True)
    (tmp_path / "test.patch").write_text("test", encoding="utf-8")
    window.patch_dir_edit.setText(str(tmp_path))
    calls = []
    monkeypatch.setattr("packpatch_ui.ui.main_window.apply_latest_patch", lambda *args, **kwargs: SimpleNamespace(
        succeeded=succeeded, created_commit=created_commit, was_applied=was_applied,
        applied_with="Compatсh", command=["git", "am"], stdout="", stderr="", returncode=1,
    ))
    monkeypatch.setattr(window, "_auto_deploy_after_commit", lambda: None)
    monkeypatch.setattr(window, "_auto_create_pack_after_apply", lambda: None)
    monkeypatch.setattr(window, "_auto_push_after_commit", lambda: calls.append("push"))
    monkeypatch.setattr(window, "_refresh_repository_status", lambda *args, **kwargs: None)
    window._apply_latest_patch(dry_run=dry_run)
    assert calls == ["push"] * expected_push


def test_auto_push_failure_does_not_change_apply_result(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packpatch_ui.core.git_push import PushResult, PushTarget

    window._repo_info = GitRepoInfo(root=tmp_path, branch="main", is_dirty=False)
    window.auto_push_after_apply_check.setChecked(True)
    monkeypatch.setattr("packpatch_ui.ui.main_window.current_push_target", lambda *_:
                        PushTarget("main", "origin", "refs/heads/main"))
    monkeypatch.setattr("packpatch_ui.ui.main_window.push_current_branch", lambda *args, **kwargs:
                        PushResult(False, "No upstream configured"))
    window._auto_push_after_commit()
    assert "Auto push failed: No upstream configured" in window.log.toPlainText()
    assert not window._push_busy


def test_auto_push_without_upstream_is_skipped(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packpatch_ui.core.git_push import PushUnavailable

    window._repo_info = GitRepoInfo(root=tmp_path, branch="main", is_dirty=False)
    window.auto_push_after_apply_check.setChecked(True)
    def no_upstream(*args):
        raise PushUnavailable("No upstream")
    monkeypatch.setattr("packpatch_ui.ui.main_window.current_push_target", no_upstream)
    monkeypatch.setattr("packpatch_ui.ui.main_window.push_current_branch", lambda *args, **kwargs:
                        pytest.fail("git push should not run without an upstream"))
    window._auto_push_after_commit()
    assert "Auto push skipped: No upstream" in window.log.toPlainText()
