"""Main application window."""

from __future__ import annotations

import base64
import html
from pathlib import Path

from PySide6.QtCore import QByteArray, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from packpatch_ui.config import APP_NAME
from packpatch_ui.core.artifacts import ArtifactInfo, delete_artifact, list_pack_archives, list_patch_files
from packpatch_ui.core.git_repo import (
    GitRepoInfo,
    list_changed_files,
    list_recent_commits,
    list_repo_files,
    read_git_repo_info,
)
from packpatch_ui.core.pack_runner import PACK_MODE_LABELS, create_pack, default_task_name_for_mode
from packpatch_ui.core.patch_runner import apply_latest_patch, check_latest_patch, read_patch_preview, undo_last_commit
from packpatch_ui.services.settings_store import AppSession, DEFAULT_SESSION_NAME, SessionStore
from packpatch_ui.ui.collapsible_section import CollapsibleSection
from packpatch_ui.ui.file_tree import FileTreeWidget


class MainWindow(QMainWindow):
    """Main window with repository status, file selection, pack creation, and patch apply controls."""

    def __init__(self) -> None:
        super().__init__()
        self._repo_info: GitRepoInfo | None = None
        self._session_store = SessionStore()
        self._loading_session = False
        self._current_session_name = DEFAULT_SESSION_NAME
        self._geometry_restore_done = False

        self.session_combo = QComboBox(self)
        self.new_session_button = QPushButton("New", self)
        self.save_session_button = QPushButton("Save", self)
        self.save_session_as_button = QPushButton("Save as...", self)
        self.delete_session_button = QPushButton("Delete", self)

        self.repo_path_edit = QLineEdit(self)
        self.repo_path_edit.setPlaceholderText("Select a git repository...")

        self.browse_button = QPushButton("Browse...", self)
        self.refresh_button = QPushButton("Refresh", self)

        self.root_value = QLabel("-", self)
        self.branch_value = QLabel("-", self)
        self.status_value = QLabel("-", self)

        self.pack_mode_combo = QComboBox(self)
        for mode, label in PACK_MODE_LABELS.items():
            self.pack_mode_combo.addItem(label, mode)

        self.task_name_edit = QLineEdit(self)
        self.task_name_edit.setPlaceholderText("Task name for pack, e.g. fix-ui")
        self.create_pack_button = QPushButton("Create pack", self)

        self.commit_message_edit = QLineEdit(self)
        self.commit_message_edit.setPlaceholderText("Commit message, e.g. Add session management UI")
        self.undo_last_commit_button = QPushButton("Undo last commit", self)
        self.refresh_commits_button = QPushButton("Refresh commits", self)
        self.copy_commit_hash_button = QPushButton("Copy hash", self)
        self.commit_list = QListWidget(self)
        self.commit_list.setAlternatingRowColors(True)

        self.patch_dir_edit = QLineEdit(self)
        self.patch_dir_edit.setPlaceholderText("Directory with .patch/.diff files, e.g. ~/Downloads")
        self.patch_dir_edit.setText(str(Path.home() / "Downloads"))
        self.browse_patch_dir_button = QPushButton("Browse patches...", self)
        self.check_latest_patch_button = QPushButton("Check latest patch", self)
        self.dry_run_patch_button = QPushButton("Dry-run latest patch", self)
        self.apply_latest_patch_button = QPushButton("Apply latest patch", self)

        self.refresh_artifacts_button = QPushButton("Refresh packs/patches", self)
        self.copy_pack_path_button = QPushButton("Copy pack path", self)
        self.copy_patch_path_button = QPushButton("Copy patch path", self)
        self.delete_pack_button = QPushButton("Delete pack", self)
        self.delete_patch_button = QPushButton("Delete patch", self)
        self.pack_list = QListWidget(self)
        self.patch_list = QListWidget(self)
        self.pack_list.setAlternatingRowColors(True)
        self.patch_list.setAlternatingRowColors(True)

        self.file_tree = FileTreeWidget()
        self.file_filter_edit = QLineEdit(self)
        self.file_filter_edit.setPlaceholderText("Filter files, e.g. main_window.py, tools/, docs/")
        self.check_changed_button = QPushButton("Select changed", self)
        self.check_all_button = QPushButton("Check all", self)
        self.clear_selection_button = QPushButton("Clear", self)
        self.selection_value = QLabel("0 files selected", self)

        self.patch_preview = QTextEdit(self)
        self.patch_preview.setReadOnly(True)
        self.patch_preview.setPlaceholderText("Selected/latest patch preview will appear here.")
        self.patch_preview.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.patch_preview.setMinimumHeight(160)

        self.log = QTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Command output and status messages will appear here.")
        self.log.setMinimumHeight(260)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(750)

        self.setWindowTitle(APP_NAME)
        self.resize(1120, 780)
        self.setCentralWidget(self._build_central_widget())
        self.setStatusBar(self._build_status_bar())
        self._connect_signals()
        self._reload_session_combo(select_name=DEFAULT_SESSION_NAME)
        self._load_current_session()
        if not self._geometry_restore_done:
            self._center_on_primary_screen()
            self._geometry_restore_done = True

    def _build_central_widget(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel(APP_NAME, widget)
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        title.setStyleSheet("font-size: 22px; font-weight: 600;")

        description = QLabel(
            "Select a repository, choose files, create packs, and apply generated patches.",
            widget,
        )
        description.setWordWrap(True)

        session_row = QHBoxLayout()
        session_row.addWidget(QLabel("Session:", widget))
        session_row.addWidget(self.session_combo, stretch=1)
        session_row.addWidget(self.new_session_button)
        session_row.addWidget(self.save_session_button)
        session_row.addWidget(self.save_session_as_button)
        session_row.addWidget(self.delete_session_button)

        repo_row = QHBoxLayout()
        repo_row.addWidget(self.repo_path_edit, stretch=1)
        repo_row.addWidget(self.browse_button)
        repo_row.addWidget(self.refresh_button)

        status_widget = QWidget(widget)
        status_grid = QGridLayout(status_widget)
        status_grid.setContentsMargins(0, 0, 0, 0)
        status_grid.setHorizontalSpacing(12)
        status_grid.setVerticalSpacing(8)
        status_grid.addWidget(QLabel("Git root:", widget), 0, 0)
        status_grid.addWidget(self.root_value, 0, 1)
        status_grid.addWidget(QLabel("Branch:", widget), 1, 0)
        status_grid.addWidget(self.branch_value, 1, 1)
        status_grid.addWidget(QLabel("Status:", widget), 2, 0)
        status_grid.addWidget(self.status_value, 2, 1)
        status_grid.setColumnStretch(1, 1)
        self.repository_status_section = CollapsibleSection(
            "Repository status",
            status_widget,
            collapsed=False,
            parent=widget,
        )

        pack_controls = QHBoxLayout()
        pack_controls.addWidget(QLabel("Pack mode:", widget))
        pack_controls.addWidget(self.pack_mode_combo)
        pack_controls.addWidget(QLabel("Task:", widget))
        pack_controls.addWidget(self.task_name_edit, stretch=1)
        pack_controls.addWidget(self.create_pack_button)

        commit_controls = QHBoxLayout()
        commit_controls.addWidget(QLabel("Commit:", widget))
        commit_controls.addWidget(self.commit_message_edit, stretch=1)

        patch_controls = QHBoxLayout()
        patch_controls.addWidget(QLabel("Patches:", widget))
        patch_controls.addWidget(self.patch_dir_edit, stretch=1)
        patch_controls.addWidget(self.browse_patch_dir_button)
        patch_controls.addWidget(self.check_latest_patch_button)
        patch_controls.addWidget(self.dry_run_patch_button)
        patch_controls.addWidget(self.apply_latest_patch_button)

        artifact_controls = QHBoxLayout()
        artifact_controls.addWidget(self.refresh_artifacts_button)
        artifact_controls.addStretch(1)
        artifact_controls.addWidget(self.copy_pack_path_button)
        artifact_controls.addWidget(self.copy_patch_path_button)
        artifact_controls.addWidget(self.delete_pack_button)
        artifact_controls.addWidget(self.delete_patch_button)

        artifact_lists = QHBoxLayout()
        artifact_lists.setSpacing(8)
        pack_column_widget = QWidget(widget)
        pack_column = QVBoxLayout(pack_column_widget)
        pack_column.setContentsMargins(0, 0, 0, 0)
        self.pack_list.setMaximumHeight(96)
        pack_column.addWidget(self.pack_list)

        patch_column_widget = QWidget(widget)
        patch_column = QVBoxLayout(patch_column_widget)
        patch_column.setContentsMargins(0, 0, 0, 0)
        self.patch_list.setMaximumHeight(96)
        patch_column.addWidget(self.patch_list)

        self.packs_section = CollapsibleSection("Latest packs", pack_column_widget, collapsed=True, parent=widget)
        self.patches_section = CollapsibleSection("Latest patches", patch_column_widget, collapsed=False, parent=widget)
        artifact_lists.addWidget(self.packs_section, stretch=1)
        artifact_lists.addWidget(self.patches_section, stretch=1)

        file_tree_widget = QWidget(widget)
        file_tree_layout = QVBoxLayout(file_tree_widget)
        file_tree_layout.setContentsMargins(0, 0, 0, 0)
        file_tree_layout.setSpacing(4)

        tree_controls = QHBoxLayout()
        tree_controls.addWidget(QLabel("Filter:", widget))
        tree_controls.addWidget(self.file_filter_edit, stretch=1)
        tree_controls.addWidget(self.check_changed_button)
        tree_controls.addWidget(self.check_all_button)
        tree_controls.addWidget(self.clear_selection_button)
        tree_controls.addStretch(1)
        tree_controls.addWidget(self.selection_value)
        file_tree_layout.addLayout(tree_controls)
        file_tree_layout.addWidget(self.file_tree, stretch=1)

        self.file_tree_section = CollapsibleSection("Repository files", file_tree_widget, collapsed=False, parent=widget)
        self.patch_preview_section = CollapsibleSection("Patch preview", self.patch_preview, collapsed=True, parent=widget)

        commit_history_widget = QWidget(widget)
        commit_history_layout = QVBoxLayout(commit_history_widget)
        commit_history_layout.setContentsMargins(0, 0, 0, 0)
        commit_history_layout.setSpacing(4)
        commit_history_controls = QHBoxLayout()
        commit_history_controls.addWidget(self.refresh_commits_button)
        commit_history_controls.addWidget(self.copy_commit_hash_button)
        commit_history_controls.addWidget(self.undo_last_commit_button)
        commit_history_controls.addStretch(1)
        self.commit_list.setMinimumHeight(160)
        commit_history_layout.addLayout(commit_history_controls)
        commit_history_layout.addWidget(self.commit_list, stretch=1)

        self.log_section = CollapsibleSection("Log", self.log, collapsed=False, parent=widget)
        self.git_commits_section = CollapsibleSection("Git commits", commit_history_widget, collapsed=False, parent=widget)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(session_row)
        layout.addLayout(repo_row)
        layout.addWidget(self.repository_status_section)
        layout.addLayout(pack_controls)
        layout.addLayout(commit_controls)
        layout.addLayout(patch_controls)
        layout.addLayout(artifact_controls)
        layout.addLayout(artifact_lists)
        layout.addWidget(self.file_tree_section, stretch=2)
        layout.addWidget(self.patch_preview_section)

        bottom_workspace = QHBoxLayout()
        bottom_workspace.setSpacing(8)
        bottom_workspace.addWidget(self.log_section, stretch=3)
        bottom_workspace.addWidget(self.git_commits_section, stretch=2)
        layout.addLayout(bottom_workspace, stretch=3)
        return widget

    def _build_status_bar(self) -> QStatusBar:
        status_bar = QStatusBar(self)
        status_bar.showMessage("Ready")
        return status_bar

    def _connect_signals(self) -> None:
        self.session_combo.currentTextChanged.connect(self._load_session_by_name)
        self.new_session_button.clicked.connect(self._new_session)
        self.save_session_button.clicked.connect(self._save_current_session)
        self.save_session_as_button.clicked.connect(self._save_session_as)
        self.delete_session_button.clicked.connect(self._delete_current_session)
        self._autosave_timer.timeout.connect(self._autosave_current_session)

        self.browse_button.clicked.connect(self._browse_repository)
        self.refresh_button.clicked.connect(lambda: self._refresh_repository_status())
        self.repo_path_edit.returnPressed.connect(self._refresh_repository_status)
        self.repo_path_edit.textEdited.connect(lambda *_: self._schedule_autosave())
        self.patch_dir_edit.textEdited.connect(lambda *_: self._schedule_autosave())
        self.pack_mode_combo.currentIndexChanged.connect(self._pack_mode_changed)
        self.task_name_edit.textEdited.connect(lambda *_: self._schedule_autosave())
        self.commit_message_edit.textEdited.connect(lambda *_: self._schedule_autosave())
        self.file_filter_edit.textChanged.connect(self._file_filter_changed)
        self.undo_last_commit_button.clicked.connect(self._undo_last_commit)
        self.refresh_commits_button.clicked.connect(self._refresh_commit_list)
        self.copy_commit_hash_button.clicked.connect(self._copy_selected_commit_hash)

        self.check_changed_button.clicked.connect(self._select_changed_files)
        self.check_all_button.clicked.connect(self._check_all_files)
        self.clear_selection_button.clicked.connect(self._clear_file_selection)
        self.create_pack_button.clicked.connect(self._create_pack)
        self.browse_patch_dir_button.clicked.connect(self._browse_patch_directory)
        self.check_latest_patch_button.clicked.connect(self._check_latest_patch)
        self.dry_run_patch_button.clicked.connect(lambda: self._apply_latest_patch(dry_run=True))
        self.apply_latest_patch_button.clicked.connect(lambda: self._apply_latest_patch(dry_run=False))
        self.refresh_artifacts_button.clicked.connect(self._refresh_artifact_lists)
        self.copy_pack_path_button.clicked.connect(lambda: self._copy_selected_artifact_path(self.pack_list, "pack"))
        self.copy_patch_path_button.clicked.connect(lambda: self._copy_selected_artifact_path(self.patch_list, "patch"))
        self.delete_pack_button.clicked.connect(lambda: self._delete_selected_artifact(self.pack_list, "pack"))
        self.delete_patch_button.clicked.connect(
            lambda: self._delete_selected_artifact(self.patch_list, "patch", include_patch_sidecars=True)
        )
        self.patch_list.currentItemChanged.connect(lambda *_: self._preview_selected_patch(silent=True))
        self.file_tree.itemChanged.connect(lambda *_: self._selection_changed())
        self.repository_status_section.toggled.connect(lambda *_: self._panel_collapsed_state_changed())
        self.packs_section.toggled.connect(lambda *_: self._panel_collapsed_state_changed())
        self.patches_section.toggled.connect(lambda *_: self._panel_collapsed_state_changed())
        self.file_tree_section.toggled.connect(lambda *_: self._panel_collapsed_state_changed())
        self.patch_preview_section.toggled.connect(self._patch_preview_section_toggled)
        self.log_section.toggled.connect(lambda *_: self._panel_collapsed_state_changed())
        self.git_commits_section.toggled.connect(lambda *_: self._panel_collapsed_state_changed())

    def _reload_session_combo(self, *, select_name: str | None = None) -> None:
        sessions = self._session_store.load_sessions()
        names = [session.name for session in sessions]
        if DEFAULT_SESSION_NAME not in names:
            names.insert(0, DEFAULT_SESSION_NAME)

        self._loading_session = True
        try:
            self.session_combo.clear()
            self.session_combo.addItems(names)
            target = select_name or self._current_session_name or DEFAULT_SESSION_NAME
            index = self.session_combo.findText(target)
            self.session_combo.setCurrentIndex(index if index >= 0 else 0)
            self._current_session_name = self.session_combo.currentText() or DEFAULT_SESSION_NAME
        finally:
            self._loading_session = False

    def _load_session_by_name(self, name: str) -> None:
        if self._loading_session or not name:
            return
        self._current_session_name = name
        self._load_current_session()

    def _load_current_session(self) -> None:
        session = self._session_store.get_session(self._current_session_name)
        if session is None:
            session = AppSession(name=self._current_session_name, patch_dir=str(Path.home() / "Downloads"))

        self._loading_session = True
        try:
            self.repo_path_edit.setText(session.repo_path)
            self.patch_dir_edit.setText(session.patch_dir or str(Path.home() / "Downloads"))
            self._set_pack_mode(session.pack_mode)
            self.task_name_edit.setText(session.task_name)
            self.commit_message_edit.setText(session.commit_message)
            self.file_filter_edit.setText(session.file_filter)
            self.repository_status_section.set_collapsed(session.repository_status_collapsed)
            self.packs_section.set_collapsed(session.latest_packs_collapsed)
            self.patches_section.set_collapsed(session.latest_patches_collapsed)
            self.file_tree_section.set_collapsed(session.file_tree_collapsed)
            self.patch_preview_section.set_collapsed(session.patch_preview_collapsed)
            self.log_section.set_collapsed(session.log_collapsed)
            self.git_commits_section.set_collapsed(session.git_commits_collapsed)
        finally:
            self._loading_session = False

        self._restore_window_geometry(session.window_geometry)

        if session.repo_path:
            self._refresh_repository_status(selected_files=session.selected_files)
        else:
            self._set_no_repo("Session loaded. Select a git repository.")
            self._refresh_artifact_lists()

        self._append_log(f"Session loaded: {session.name}")

    def _new_session(self) -> None:
        name, accepted = QInputDialog.getText(self, "New session", "Session name:")
        name = name.strip()
        if not accepted or not name:
            return
        if self._session_store.get_session(name) is not None:
            self._append_log(f"Session already exists: {name}")
            self.statusBar().showMessage("Session already exists")
            return

        session = AppSession(name=name, patch_dir=str(Path.home() / "Downloads"))
        self._session_store.upsert_session(session)
        self._reload_session_combo(select_name=name)
        self._load_current_session()
        self.statusBar().showMessage("Session created")

    def _save_session_as(self) -> None:
        name, accepted = QInputDialog.getText(
            self,
            "Save session as",
            "Session name:",
            text=self._current_session_name,
        )
        name = name.strip()
        if not accepted or not name:
            return
        self._current_session_name = name
        self._session_store.upsert_session(self._current_session_snapshot(name))
        self._reload_session_combo(select_name=name)
        self.statusBar().showMessage("Session saved")
        self._append_log(f"Session saved as: {name}")

    def _save_current_session(self) -> None:
        self._session_store.upsert_session(self._current_session_snapshot(self._current_session_name))
        self._reload_session_combo(select_name=self._current_session_name)
        self.statusBar().showMessage("Session saved")
        self._append_log(f"Session saved: {self._current_session_name}")

    def _delete_current_session(self) -> None:
        name = self._current_session_name
        if name == DEFAULT_SESSION_NAME:
            self._append_log("Default session cannot be deleted.")
            self.statusBar().showMessage("Default session cannot be deleted")
            return
        self._session_store.delete_session(name)
        self._reload_session_combo(select_name=DEFAULT_SESSION_NAME)
        self._load_current_session()
        self.statusBar().showMessage("Session deleted")
        self._append_log(f"Session deleted: {name}")

    def _current_session_snapshot(self, name: str) -> AppSession:
        return AppSession(
            name=name or DEFAULT_SESSION_NAME,
            repo_path=self.repo_path_edit.text().strip(),
            patch_dir=self.patch_dir_edit.text().strip(),
            task_name=self.task_name_edit.text().strip(),
            pack_mode=self._current_pack_mode(),
            commit_message=self.commit_message_edit.text().strip(),
            selected_files=self.file_tree.selected_paths(),
            file_filter=self.file_filter_edit.text().strip(),
            window_geometry=self._encoded_window_geometry(),
            latest_packs_collapsed=self.packs_section.is_collapsed(),
            latest_patches_collapsed=self.patches_section.is_collapsed(),
            patch_preview_collapsed=self.patch_preview_section.is_collapsed(),
            repository_status_collapsed=self.repository_status_section.is_collapsed(),
            file_tree_collapsed=self.file_tree_section.is_collapsed(),
            log_collapsed=self.log_section.is_collapsed(),
            git_commits_collapsed=self.git_commits_section.is_collapsed(),
        )

    def _schedule_autosave(self) -> None:
        if self._loading_session:
            return
        self._autosave_timer.start()

    def _autosave_current_session(self) -> None:
        if self._loading_session:
            return
        self._session_store.upsert_session(self._current_session_snapshot(self._current_session_name))
        self.statusBar().showMessage("Session autosaved")

    def _patch_preview_section_toggled(self, expanded: bool) -> None:
        self._panel_collapsed_state_changed()
        if expanded:
            self._preview_selected_patch(silent=True)

    def _panel_collapsed_state_changed(self) -> None:
        if self._loading_session:
            return
        self.centralWidget().updateGeometry()
        self._schedule_autosave()

    def _encoded_window_geometry(self) -> str:
        geometry = self.saveGeometry()
        encoded = geometry.toBase64().data()
        return encoded.decode("ascii")

    def _restore_window_geometry(self, encoded_geometry: str) -> None:
        if not encoded_geometry:
            self._center_on_primary_screen()
            self._geometry_restore_done = True
            return

        try:
            raw = base64.b64decode(encoded_geometry.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError):
            self._center_on_primary_screen()
            self._geometry_restore_done = True
            return

        if not raw or not self.restoreGeometry(QByteArray(raw)):
            self._center_on_primary_screen()
            self._geometry_restore_done = True
            return

        if not self._is_window_visible_on_any_screen():
            self._center_on_primary_screen()
        self._geometry_restore_done = True

    def _center_on_primary_screen(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available_geometry = screen.availableGeometry()
        frame_geometry = self.frameGeometry()
        frame_geometry.moveCenter(available_geometry.center())
        self.move(frame_geometry.topLeft())

    def _is_window_visible_on_any_screen(self) -> bool:
        window_geometry = self.frameGeometry()
        return any(screen.availableGeometry().intersects(window_geometry) for screen in QApplication.screens())

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        self._schedule_autosave()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._schedule_autosave()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._autosave_current_session()
        super().closeEvent(event)

    def _browse_repository(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select git repository")
        if selected:
            self.repo_path_edit.setText(selected)
            self._refresh_repository_status()
            self._schedule_autosave()

    def _browse_patch_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select patch directory")
        if selected:
            self.patch_dir_edit.setText(selected)
            self._refresh_artifact_lists()
            self._schedule_autosave()

    def _refresh_repository_status(self, selected_files: object = None) -> None:
        raw_path = self.repo_path_edit.text().strip()
        if not raw_path:
            self._set_no_repo("Repository path is empty.")
            return

        start_dir = Path(raw_path).expanduser()
        if not start_dir.exists():
            self._set_no_repo(f"Path does not exist: {start_dir}")
            return

        info = read_git_repo_info(start_dir)
        if info is None:
            self._set_no_repo(f"Not inside a git repository: {start_dir}")
            return

        self._repo_info = info
        self.root_value.setText(str(info.root))
        self.branch_value.setText(info.branch or "detached HEAD")
        self.status_value.setText("dirty" if info.is_dirty else "clean")

        files = list_repo_files(info.root)
        self.file_tree.set_files(files)
        self.file_tree.set_filter(self.file_filter_edit.text())
        normalized_selection = self._normalize_selected_files(selected_files)
        if normalized_selection is not None:
            self.file_tree.set_selected_paths(normalized_selection)
        self._update_selection_count()
        self._refresh_artifact_lists()
        self._refresh_commit_list(log_result=False)
        self._schedule_autosave()

        self.statusBar().showMessage("Repository status refreshed")
        self._append_log(
            "Repository status refreshed:\n"
            f"  root: {info.root}\n"
            f"  branch: {info.branch or 'detached HEAD'}\n"
            f"  status: {'dirty' if info.is_dirty else 'clean'}\n"
            f"  files: {len(files)}"
        )

    def _normalize_selected_files(self, selected_files: object) -> list[str] | None:
        if selected_files is None or isinstance(selected_files, bool):
            return None
        if isinstance(selected_files, str):
            return [selected_files] if selected_files else []

        try:
            return [path for path in selected_files if isinstance(path, str) and path]
        except TypeError:
            return None

    def _set_no_repo(self, message: str) -> None:
        self._repo_info = None
        self.root_value.setText("-")
        self.branch_value.setText("-")
        self.status_value.setText("not available")
        self.file_tree.clear()
        self.pack_list.clear()
        self.patch_list.clear()
        self.commit_list.clear()
        self._update_selection_count()
        self.statusBar().showMessage(message)
        self._append_log(message)

    def _current_pack_mode(self) -> str:
        mode = self.pack_mode_combo.currentData()
        return str(mode or "slice")

    def _set_pack_mode(self, mode: str) -> None:
        index = self.pack_mode_combo.findData(mode or "slice")
        self.pack_mode_combo.setCurrentIndex(index if index >= 0 else 0)

    def _pack_mode_changed(self) -> None:
        if not self.task_name_edit.text().strip():
            self.task_name_edit.setText(default_task_name_for_mode(self._current_pack_mode()))
        self._schedule_autosave()

    def _ensure_task_name_for_mode(self, mode: str) -> str:
        task_name = self.task_name_edit.text().strip()
        if task_name:
            return task_name

        task_name = default_task_name_for_mode(mode)
        self.task_name_edit.setText(task_name)
        return task_name

    def _select_changed_files(self) -> None:
        if self._repo_info is None:
            self._append_log("Cannot select changed files: no git repository selected.")
            self.statusBar().showMessage("No git repository selected")
            return

        changed_files = list_changed_files(self._repo_info.root)
        self.file_tree.set_selected_paths(changed_files)
        self._selection_changed()
        if changed_files:
            preview = "\n".join(f"  {path}" for path in changed_files[:50])
            suffix = "" if len(changed_files) <= 50 else f"\n  ... and {len(changed_files) - 50} more"
            self._append_log(f"Selected changed files ({len(changed_files)}):\n{preview}{suffix}")
            self.statusBar().showMessage(f"Selected {len(changed_files)} changed file(s)")
        else:
            self._append_log("No changed or untracked files found.")
            self.statusBar().showMessage("No changed files")

    def _check_all_files(self) -> None:
        self.file_tree.check_all()
        self._selection_changed()

    def _clear_file_selection(self) -> None:
        self.file_tree.clear_selection()
        self._selection_changed()

    def _selection_changed(self) -> None:
        self._update_selection_count()
        self._schedule_autosave()

    def _file_filter_changed(self, text: str) -> None:
        self.file_tree.set_filter(text)
        self._update_selection_count()
        self._schedule_autosave()

    def _update_selection_count(self) -> None:
        count = len(self.file_tree.selected_paths())
        self.selection_value.setText(f"{count} file{'s' if count != 1 else ''} selected")

    def _create_pack(self) -> None:
        if self._repo_info is None:
            self._append_log("Cannot create pack: no git repository selected.")
            self.statusBar().showMessage("No git repository selected")
            return

        selected_files = self.file_tree.selected_paths()
        mode = self._current_pack_mode()
        task_name = self._ensure_task_name_for_mode(mode)

        self._append_log(f"Creating pack with mode: {PACK_MODE_LABELS.get(mode, mode)}...")
        try:
            result = create_pack(self._repo_info.root, mode, task_name, selected_files)
        except (FileNotFoundError, ValueError) as error:
            self._append_log(f"Cannot create pack: {error}")
            self.statusBar().showMessage("Pack creation failed")
            return

        self._append_log("Command:")
        self._append_log("  " + " ".join(result.command))
        if result.stdout.strip():
            self._append_log(result.stdout.strip())
        if result.stderr.strip():
            self._append_log(result.stderr.strip())

        if result.succeeded:
            self.statusBar().showMessage("Pack created")
            self._refresh_artifact_lists()
            self._schedule_autosave()
        else:
            self.statusBar().showMessage(f"Pack creation failed with exit code {result.returncode}")

    def _refresh_artifact_lists(self) -> None:
        self.pack_list.clear()
        self.patch_list.clear()

        pack_count = 0
        if self._repo_info is not None:
            pack_count = self._populate_artifact_list(self.pack_list, list_pack_archives(self._repo_info.root))

        patch_dir = Path(self.patch_dir_edit.text().strip()).expanduser()
        patch_count = self._populate_artifact_list(self.patch_list, list_patch_files(patch_dir))

        self._append_log(
            "Artifact lists refreshed:\n"
            f"  packs: {pack_count}\n"
            f"  patches: {patch_count}"
        )

    def _populate_artifact_list(self, widget: QListWidget, artifacts: list[ArtifactInfo]) -> int:
        for artifact in artifacts:
            item = QListWidgetItem(artifact.display_name)
            item.setToolTip(str(artifact.path))
            item.setData(Qt.ItemDataRole.UserRole, str(artifact.path))
            widget.addItem(item)
        if artifacts:
            widget.setCurrentRow(0)
        return len(artifacts)

    def _selected_patch_path(self) -> Path | None:
        item = self.patch_list.currentItem()
        if item is None:
            return None

        path = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(path, str) or not path:
            return None
        return Path(path).expanduser()

    def _preview_selected_patch(self, *, silent: bool = False) -> None:
        patch_path = self._selected_patch_path()
        if patch_path is None:
            self.patch_preview.clear()
            return

        try:
            text, truncated = read_patch_preview(patch_path)
        except FileNotFoundError as error:
            self.patch_preview.setPlainText(str(error))
            if not silent:
                self._append_log(f"Cannot preview patch: {error}")
                self.statusBar().showMessage("Patch preview failed")
            return

        self._set_patch_preview_text(patch_path, text, truncated)
        if not silent:
            self.patch_preview_section.set_collapsed(False)
            self._append_log(f"Previewed patch: {patch_path}")
            self.statusBar().showMessage("Patch preview loaded")

    def _set_patch_preview_text(self, patch_path: Path, text: str, truncated: bool) -> None:
        header = f"# {patch_path}\n"
        if truncated:
            header += "# Preview truncated to 512 KB.\n"
        header += "\n"
        self.patch_preview.setPlainText(header + text)

    def _copy_selected_artifact_path(self, widget: QListWidget, label: str) -> None:
        item = widget.currentItem()
        if item is None:
            self._append_log(f"No {label} selected.")
            self.statusBar().showMessage(f"No {label} selected")
            return

        path = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(path, str) or not path:
            self._append_log(f"Selected {label} has no path metadata.")
            self.statusBar().showMessage(f"Cannot copy {label} path")
            return

        QApplication.clipboard().setText(path)
        self._append_log(f"Copied {label} path: {path}")
        self.statusBar().showMessage(f"Copied {label} path")

    def _delete_selected_artifact(
        self,
        widget: QListWidget,
        label: str,
        *,
        include_patch_sidecars: bool = False,
    ) -> None:
        item = widget.currentItem()
        if item is None:
            self._append_log(f"No {label} selected.")
            self.statusBar().showMessage(f"No {label} selected")
            return

        path_value = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(path_value, str) or not path_value:
            self._append_log(f"Selected {label} has no path metadata.")
            self.statusBar().showMessage(f"Cannot delete {label}")
            return

        path = Path(path_value).expanduser()
        sidecar_note = " and its sidecar files" if include_patch_sidecars else ""
        response = QMessageBox.question(
            self,
            f"Delete selected {label}",
            f"Delete selected {label}{sidecar_note}?\n\n{path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            self._append_log(f"Delete {label} cancelled.")
            self.statusBar().showMessage(f"Delete {label} cancelled")
            return

        try:
            deleted = delete_artifact(path, include_patch_sidecars=include_patch_sidecars)
        except (OSError, ValueError) as error:
            self._append_log(f"Cannot delete {label}: {error}")
            self.statusBar().showMessage(f"Delete {label} failed")
            return

        if not deleted:
            self._append_log(f"No files deleted for selected {label}: {path}")
            self.statusBar().showMessage(f"No {label} deleted")
            self._refresh_artifact_lists()
            return

        deleted_preview = "\n".join(f"  {item}" for item in deleted)
        self._append_log(f"Deleted {label} artifact files:\n{deleted_preview}")
        if label == "patch":
            self.patch_preview.clear()
        self._refresh_artifact_lists()
        self.statusBar().showMessage(f"Deleted {label}")

    def _check_latest_patch(self) -> None:
        if self._repo_info is None:
            self._append_log("Cannot check patch: no git repository selected.")
            self.statusBar().showMessage("No git repository selected")
            return

        patch_dir = Path(self.patch_dir_edit.text().strip()).expanduser()
        self._append_log("Checking latest patch...")

        try:
            result = check_latest_patch(self._repo_info.root, patch_dir)
        except FileNotFoundError as error:
            self._append_log(f"Cannot check patch: {error}")
            self.statusBar().showMessage("Patch check failed")
            return

        self._append_log("Command:")
        self._append_log("  " + " ".join(result.command))
        if result.stdout.strip():
            self._append_log(result.stdout.strip())
        if result.stderr.strip():
            self._append_log(result.stderr.strip())

        if result.succeeded:
            self._append_log("Patch check OK: clean apply is possible.")
            self.statusBar().showMessage("Patch check OK")
        else:
            self._append_log("Patch check failed: clean apply is not possible; Apply latest patch may use fallback.")
            self.statusBar().showMessage(f"Patch check failed with exit code {result.returncode}")

    def _apply_latest_patch(self, *, dry_run: bool) -> None:
        if self._repo_info is None:
            self._append_log("Cannot apply patch: no git repository selected.")
            self.statusBar().showMessage("No git repository selected")
            return

        patch_dir = Path(self.patch_dir_edit.text().strip()).expanduser()
        action = "Dry-running latest patch" if dry_run else "Applying latest patch"
        self._append_log(f"{action}...")

        commit_message = self.commit_message_edit.text().strip() if not dry_run else ""
        if commit_message:
            self._append_log("Commit message is set: patch will be applied and committed.")

        try:
            result = apply_latest_patch(
                self._repo_info.root,
                patch_dir,
                dry_run=dry_run,
                commit_message=commit_message,
            )
        except FileNotFoundError as error:
            self._append_log(f"Cannot apply patch: {error}")
            self.statusBar().showMessage("Patch apply failed")
            return

        self._append_log("Command:")
        self._append_log("  " + " ".join(result.command))
        if result.stdout.strip():
            self._append_log(result.stdout.strip())
        if result.stderr.strip():
            self._append_log(result.stderr.strip())

        if result.succeeded:
            if dry_run:
                self.statusBar().showMessage("Patch dry-run completed")
            elif commit_message:
                self.commit_message_edit.clear()
                self._append_log("Commit message field cleared after successful commit.")
                self.statusBar().showMessage("Patch applied and committed")
            else:
                self.statusBar().showMessage("Patch applied")
            self._refresh_repository_status()
            self._schedule_autosave()
        else:
            self.statusBar().showMessage(f"Patch command failed with exit code {result.returncode}")

    def _undo_last_commit(self) -> None:
        if self._repo_info is None:
            self._append_log("Cannot undo commit: no git repository selected.")
            self.statusBar().showMessage("No git repository selected")
            return

        self._append_log("Undoing last commit with git reset --mixed HEAD~1...")
        result = undo_last_commit(self._repo_info.root)
        self._append_log("Command:")
        self._append_log("  " + " ".join(result.command))
        if result.stdout.strip():
            self._append_log(result.stdout.strip())
        if result.stderr.strip():
            self._append_log(result.stderr.strip())

        if result.succeeded:
            self.statusBar().showMessage("Last commit undone")
            self._refresh_repository_status()
            self._schedule_autosave()
        else:
            self.statusBar().showMessage(f"Undo failed with exit code {result.returncode}")

    def _refresh_commit_list(self, *, log_result: bool = True) -> None:
        self.commit_list.clear()
        if self._repo_info is None:
            if log_result:
                self._append_log("Cannot refresh commits: no git repository selected.")
                self.statusBar().showMessage("No git repository selected")
            return

        commits = list_recent_commits(self._repo_info.root, limit=20)
        for commit in commits:
            item = QListWidgetItem(commit.display_name)
            item.setToolTip(commit.display_name)
            item.setData(Qt.ItemDataRole.UserRole, commit.short_hash)
            self.commit_list.addItem(item)

        if commits:
            self.commit_list.setCurrentRow(0)

        if log_result:
            self._append_log(f"Git commits refreshed: {len(commits)}")
            self.statusBar().showMessage("Git commits refreshed")

    def _copy_selected_commit_hash(self) -> None:
        item = self.commit_list.currentItem()
        if item is None:
            self._append_log("No commit selected.")
            self.statusBar().showMessage("No commit selected")
            return

        commit_hash = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(commit_hash, str) or not commit_hash:
            self._append_log("Selected commit has no hash metadata.")
            self.statusBar().showMessage("Cannot copy commit hash")
            return

        QApplication.clipboard().setText(commit_hash)
        self._append_log(f"Copied commit hash: {commit_hash}")
        self.statusBar().showMessage("Copied commit hash")

    def _append_log(self, message: str) -> None:
        """Append log output with lightweight severity-based coloring."""
        lines = message.splitlines() or [""]
        html_lines = [self._format_log_line(line) for line in lines]
        self.log.append("<br>".join(html_lines))

    def _format_log_line(self, line: str) -> str:
        escaped = html.escape(line)
        lower = line.lower()

        if self._is_error_log_line(lower):
            return f'<span style="color:#b00020; font-weight:600;">{escaped}</span>'
        if self._is_warning_log_line(lower):
            return f'<span style="color:#9a6700; font-weight:600;">{escaped}</span>'
        if self._is_success_log_line(line, lower):
            return f'<span style="color:#1a7f37; font-weight:600;">{escaped}</span>'
        if self._is_command_log_line(line):
            return f'<span style="font-family:monospace; color:#6639ba;">{escaped}</span>'
        if self._is_path_log_line(line):
            return f'<span style="font-family:monospace; color:#0969da;">{escaped}</span>'

        return escaped

    @staticmethod
    def _is_error_log_line(lower: str) -> bool:
        error_tokens = (
            "error",
            "failed",
            "failure",
            "traceback",
            "exception",
            "cannot ",
            "could not",
            "exit code",
        )
        return any(token in lower for token in error_tokens)

    @staticmethod
    def _is_warning_log_line(lower: str) -> bool:
        warning_tokens = ("warning", "fallback", "dirty", "conflict", "partial")
        return any(token in lower for token in warning_tokens)

    @staticmethod
    def _is_success_log_line(line: str, lower: str) -> bool:
        success_tokens = (
            " ok",
            "ok:",
            "created",
            "applied",
            "committed",
            "completed",
            "refreshed",
            "copied",
            "loaded",
            "saved",
            "cleared",
        )
        return line.startswith("OK") or any(token in lower for token in success_tokens)

    @staticmethod
    def _is_command_log_line(line: str) -> bool:
        stripped = line.strip()
        return stripped == "Command:" or stripped.startswith(("bash ", "git ", "python ", "tar "))

    @staticmethod
    def _is_path_log_line(line: str) -> bool:
        stripped = line.strip()
        return stripped.startswith(("/", "~/")) or stripped.endswith((".patch", ".diff", ".tar.gz"))
