"""Main application window."""

from __future__ import annotations

import base64
import html
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QTimer, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFileDialog,
    QCheckBox,
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
from packpatch_ui.core.deploy_runner import deploy_repo
from packpatch_ui.core.git_repo import (
    GitRepoInfo,
    GitRepoStateSnapshot,
    list_changed_files,
    list_recent_commits,
    list_repo_files,
    read_git_repo_state_snapshot,
)
from packpatch_ui.core.pack_runner import PACK_MODE_LABELS, create_pack, default_task_name_for_mode
from packpatch_ui.core.patch_runner import (
    APPLY_MODE_LABELS,
    APPLY_MODE_COMPATCH_THEN_PACKPATCH,
    apply_latest_patch,
    check_latest_patch,
    latest_patch_path,
    read_patch_preview,
    undo_last_commit,
)
from packpatch_ui.services.process_runner import run_process
from packpatch_ui.services.settings_store import AppSession, DEFAULT_SESSION_NAME, SessionStore
from packpatch_ui.services.tooltips import tooltip
from packpatch_ui.ui.collapsible_section import CollapsibleSection
from packpatch_ui.ui.artifact_list import FileDragListWidget
from packpatch_ui.ui.file_tree import FileTreeWidget
from packpatch_ui.ui.settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    """Main window with repository status, file selection, pack creation, and patch apply controls."""

    def __init__(self) -> None:
        super().__init__()
        self._repo_info: GitRepoInfo | None = None
        self._session_store = SessionStore()
        self._loading_session = False
        self._current_session_name = DEFAULT_SESSION_NAME
        self._geometry_restore_done = False
        self._repo_state_snapshot: GitRepoStateSnapshot | None = None
        self._repository_watch_busy = False

        self.session_combo = QComboBox(self)
        self.new_session_button = QPushButton("New", self)
        self.save_session_button = QPushButton("Save", self)
        self.save_session_as_button = QPushButton("Save as...", self)
        self.delete_session_button = QPushButton("Delete", self)
        self.settings_button = QPushButton("Settings...", self)

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

        self.auto_export_pack_check = QCheckBox("Auto export pack", self)
        self.include_sensitive_files_check = QCheckBox("Include keys/certs", self)
        self.include_unversioned_files_check = QCheckBox("Include unversioned files", self)
        self.auto_create_pack_after_apply_check = QCheckBox("Create pack after successful apply", self)
        self.export_dir_edit = QLineEdit(self)
        self.export_dir_edit.setPlaceholderText("Export directory for created packs")
        self.browse_export_dir_button = QPushButton("Browse export...", self)

        self.deploy_dir_edit = QLineEdit(self)
        self.deploy_dir_edit.setPlaceholderText("Deploy directory for synced repository files")
        self.browse_deploy_dir_button = QPushButton("Browse deploy...", self)
        self.deploy_repo_button = QPushButton("Deploy repo", self)
        self.auto_deploy_after_commit_check = QCheckBox("Auto deploy after commit", self)

        self.commit_message_edit = QLineEdit(self)
        self.commit_message_edit.setPlaceholderText("Apply commit message for PackPatch, e.g. Update UI wording")
        self.undo_last_commit_button = QPushButton("Undo last commit", self)
        self.refresh_commits_button = QPushButton("Refresh commits", self)
        self.copy_commit_hash_button = QPushButton("Copy hash", self)
        self.commit_list = QListWidget(self)
        self.commit_list.setAlternatingRowColors(True)

        self.patch_dir_edit = QLineEdit(self)
        self.patch_dir_edit.setPlaceholderText("Directory with .patch/.diff files, e.g. ~/Downloads")
        self.patch_dir_edit.setText(str(Path.home() / "Downloads"))
        self.browse_patch_dir_button = QPushButton("Browse patches...", self)
        self.patch_target_combo = QComboBox(self)
        self.patch_target_combo.addItem("latest", "latest")
        self.patch_target_combo.addItem("selected", "selected")
        self.apply_mode_combo = QComboBox(self)
        for mode, label in APPLY_MODE_LABELS.items():
            self.apply_mode_combo.addItem(label, mode)
        self.allow_unversioned_apply_check = QCheckBox("Allow unversioned files during apply", self)
        self.stash_changes_after_undo_check = QCheckBox("Stash changes after undo", self)
        self.watch_repository_state_check = QCheckBox("Watch repository state", self)
        self.check_latest_patch_button = QPushButton("Check patch", self)
        self.dry_run_patch_button = QPushButton("Dry-run patch", self)
        self.apply_latest_patch_button = QPushButton("Apply patch", self)

        self.settings_dialog = SettingsDialog(
            auto_export_pack_check=self.auto_export_pack_check,
            include_sensitive_files_check=self.include_sensitive_files_check,
            include_unversioned_files_check=self.include_unversioned_files_check,
            auto_create_pack_after_apply_check=self.auto_create_pack_after_apply_check,
            apply_mode_combo=self.apply_mode_combo,
            allow_unversioned_apply_check=self.allow_unversioned_apply_check,
            stash_changes_after_undo_check=self.stash_changes_after_undo_check,
            watch_repository_state_check=self.watch_repository_state_check,
            auto_deploy_after_commit_check=self.auto_deploy_after_commit_check,
            parent=self,
        )

        self.refresh_artifacts_button = QPushButton("Refresh packs/patch files", self)
        self.copy_pack_path_button = QPushButton("Copy pack path", self)
        self.show_pack_in_explorer_button = QPushButton("Show in Explorer", self)
        self.copy_patch_path_button = QPushButton("Copy patch path", self)
        self.delete_pack_button = QPushButton("Delete pack", self)
        self.delete_patch_button = QPushButton("Delete patch", self)
        self.pack_list = FileDragListWidget(drag_path_resolver=self._pack_drag_path, parent=self)
        self.patch_list = QListWidget(self)
        self.pack_list.setAlternatingRowColors(True)
        self.patch_list.setAlternatingRowColors(True)
        self.pack_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.patch_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

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

        self._repository_watch_timer = QTimer(self)
        self._repository_watch_timer.setInterval(1000)

        self.setWindowTitle(APP_NAME)
        self.resize(1120, 780)
        self.setCentralWidget(self._build_central_widget())
        self.setStatusBar(self._build_status_bar())
        self._apply_tooltips()
        self._connect_signals()
        self._current_session_name = self._session_store.load_active_session_name()
        self._reload_session_combo(select_name=self._current_session_name)
        self._load_current_session()
        self._repository_watch_timer.start()
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
        session_row.addWidget(self.settings_button)

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

        export_controls = QHBoxLayout()
        export_controls.addWidget(QLabel("Export dir:", widget))
        export_controls.addWidget(self.export_dir_edit, stretch=1)
        export_controls.addWidget(self.browse_export_dir_button)

        deploy_controls = QHBoxLayout()
        deploy_controls.addWidget(QLabel("Deploy dir:", widget))
        deploy_controls.addWidget(self.deploy_dir_edit, stretch=1)
        deploy_controls.addWidget(self.browse_deploy_dir_button)
        deploy_controls.addWidget(self.deploy_repo_button)

        commit_controls = QHBoxLayout()
        commit_controls.addWidget(QLabel("Apply commit message:", widget))
        commit_controls.addWidget(self.commit_message_edit, stretch=1)

        patch_controls = QHBoxLayout()
        patch_controls.addWidget(QLabel("Patches:", widget))
        patch_controls.addWidget(self.patch_dir_edit, stretch=1)
        patch_controls.addWidget(self.browse_patch_dir_button)
        patch_controls.addWidget(QLabel("Patch target:", widget))
        patch_controls.addWidget(self.patch_target_combo)
        patch_controls.addWidget(self.check_latest_patch_button)
        patch_controls.addWidget(self.dry_run_patch_button)
        patch_controls.addWidget(self.apply_latest_patch_button)

        artifact_controls = QHBoxLayout()
        artifact_controls.addWidget(self.refresh_artifacts_button)
        artifact_controls.addStretch(1)

        artifact_lists = QHBoxLayout()
        artifact_lists.setSpacing(8)
        pack_column_widget = QWidget(widget)
        pack_column = QVBoxLayout(pack_column_widget)
        pack_column.setContentsMargins(0, 0, 0, 0)
        pack_column.setSpacing(4)
        pack_actions = QHBoxLayout()
        pack_actions.addWidget(self.copy_pack_path_button)
        pack_actions.addWidget(self.show_pack_in_explorer_button)
        pack_actions.addWidget(self.delete_pack_button)
        pack_actions.addStretch(1)
        self.delete_pack_button.setText("Delete selected packs")
        self.pack_list.setMaximumHeight(96)
        pack_column.addLayout(pack_actions)
        pack_column.addWidget(self.pack_list)

        patch_column_widget = QWidget(widget)
        patch_column = QVBoxLayout(patch_column_widget)
        patch_column.setContentsMargins(0, 0, 0, 0)
        patch_column.setSpacing(4)
        patch_actions = QHBoxLayout()
        patch_actions.addWidget(self.copy_patch_path_button)
        patch_actions.addWidget(self.delete_patch_button)
        patch_actions.addStretch(1)
        self.delete_patch_button.setText("Delete selected patches")
        self.patch_list.setMaximumHeight(96)
        patch_column.addLayout(patch_actions)
        patch_column.addWidget(self.patch_list)

        self.packs_section = CollapsibleSection("Latest packs", pack_column_widget, collapsed=True, parent=widget)
        self.patches_section = CollapsibleSection("Latest patch files", patch_column_widget, collapsed=False, parent=widget)
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
        layout.addLayout(export_controls)
        layout.addLayout(deploy_controls)
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

    def _apply_tooltips(self) -> None:
        """Apply tooltips from the external tooltip configuration."""
        tooltip_map = {
            self.session_combo: "session.combo",
            self.new_session_button: "session.new",
            self.save_session_button: "session.save",
            self.save_session_as_button: "session.save_as",
            self.delete_session_button: "session.delete",
            self.settings_button: "settings.open",
            self.repo_path_edit: "repo.path",
            self.browse_button: "repo.browse",
            self.refresh_button: "repo.refresh",
            self.repository_status_section: "repo.status",
            self.pack_mode_combo: "pack.mode",
            self.task_name_edit: "pack.task",
            self.create_pack_button: "pack.create",
            self.auto_export_pack_check: "pack.auto_export",
            self.include_sensitive_files_check: "pack.include_sensitive",
            self.include_unversioned_files_check: "pack.include_unversioned",
            self.auto_create_pack_after_apply_check: "pack.auto_create_after_apply",
            self.export_dir_edit: "pack.export_dir",
            self.browse_export_dir_button: "pack.browse_export",
            self.deploy_dir_edit: "deploy.dir",
            self.browse_deploy_dir_button: "deploy.browse_dir",
            self.deploy_repo_button: "deploy.run",
            self.auto_deploy_after_commit_check: "deploy.auto_after_commit",
            self.packs_section: "pack.list",
            self.pack_list: "pack.list",
            self.copy_pack_path_button: "pack.copy_path",
            self.show_pack_in_explorer_button: "pack.show_in_explorer",
            self.delete_pack_button: "pack.delete",
            self.patch_dir_edit: "patch.dir",
            self.browse_patch_dir_button: "patch.browse_dir",
            self.patch_target_combo: "patch.target",
            self.apply_mode_combo: "patch.apply_mode",
            self.allow_unversioned_apply_check: "patch.allow_unversioned",
            self.stash_changes_after_undo_check: "commit.stash_after_undo",
            self.watch_repository_state_check: "repo.watch_state",
            self.check_latest_patch_button: "patch.check",
            self.dry_run_patch_button: "patch.dry_run",
            self.apply_latest_patch_button: "patch.apply",
            self.refresh_artifacts_button: "patch.refresh_artifacts",
            self.patches_section: "patch.list",
            self.patch_list: "patch.list",
            self.copy_patch_path_button: "patch.copy_path",
            self.delete_patch_button: "patch.delete",
            self.patch_preview_section: "patch.preview",
            self.patch_preview: "patch.preview",
            self.commit_message_edit: "commit.message",
            self.git_commits_section: "commit.list",
            self.commit_list: "commit.list",
            self.refresh_commits_button: "commit.refresh",
            self.copy_commit_hash_button: "commit.copy_hash",
            self.undo_last_commit_button: "commit.undo",
            self.file_filter_edit: "files.filter",
            self.check_changed_button: "files.select_changed",
            self.check_all_button: "files.check_all",
            self.clear_selection_button: "files.clear",
            self.file_tree_section: "files.tree",
            self.file_tree: "files.tree",
            self.selection_value: "files.selection_count",
            self.log_section: "log",
            self.log: "log",
        }
        for widget, key in tooltip_map.items():
            text = tooltip(key)
            if text:
                widget.setToolTip(text)

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
        self.settings_button.clicked.connect(self.settings_dialog.show_settings)
        self._autosave_timer.timeout.connect(self._autosave_current_session)
        self._repository_watch_timer.timeout.connect(self._poll_repository_state)

        self.browse_button.clicked.connect(self._browse_repository)
        self.refresh_button.clicked.connect(lambda: self._refresh_repository_status())
        self.repo_path_edit.returnPressed.connect(self._refresh_repository_status)
        self.repo_path_edit.textEdited.connect(lambda *_: self._schedule_autosave())
        self.patch_dir_edit.textEdited.connect(lambda *_: self._schedule_autosave())
        self.patch_target_combo.currentIndexChanged.connect(lambda *_: self._schedule_autosave())
        self.apply_mode_combo.currentIndexChanged.connect(lambda *_: self._schedule_autosave())
        self.allow_unversioned_apply_check.toggled.connect(lambda *_: self._schedule_autosave())
        self.stash_changes_after_undo_check.toggled.connect(lambda *_: self._schedule_autosave())
        self.watch_repository_state_check.toggled.connect(self._repository_watch_setting_changed)
        self.auto_export_pack_check.toggled.connect(lambda *_: self._schedule_autosave())
        self.include_sensitive_files_check.toggled.connect(lambda *_: self._schedule_autosave())
        self.include_unversioned_files_check.toggled.connect(lambda *_: self._schedule_autosave())
        self.auto_create_pack_after_apply_check.toggled.connect(lambda *_: self._schedule_autosave())
        self.export_dir_edit.textEdited.connect(lambda *_: self._schedule_autosave())
        self.browse_export_dir_button.clicked.connect(self._browse_export_directory)
        self.deploy_dir_edit.textEdited.connect(lambda *_: self._schedule_autosave())
        self.browse_deploy_dir_button.clicked.connect(self._browse_deploy_directory)
        self.deploy_repo_button.clicked.connect(self._deploy_repository)
        self.auto_deploy_after_commit_check.toggled.connect(lambda *_: self._schedule_autosave())
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
        self.show_pack_in_explorer_button.clicked.connect(self._show_selected_pack_in_explorer)
        self.pack_list.itemDoubleClicked.connect(lambda *_: self._show_selected_pack_in_explorer())
        self.copy_patch_path_button.clicked.connect(lambda: self._copy_selected_artifact_path(self.patch_list, "patch"))
        self.delete_pack_button.clicked.connect(lambda: self._delete_selected_artifacts(self.pack_list, "pack"))
        self.delete_patch_button.clicked.connect(
            lambda: self._delete_selected_artifacts(self.patch_list, "patch")
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
        self._session_store.save_sessions(self._session_store.load_sessions(), active_session=name)
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
            self._set_patch_target_mode(session.patch_target_mode)
            self._set_apply_mode(session.apply_mode)
            self.allow_unversioned_apply_check.setChecked(session.allow_unversioned_apply)
            self.stash_changes_after_undo_check.setChecked(session.stash_changes_after_undo)
            self.watch_repository_state_check.setChecked(session.watch_repository_state)
            self.auto_export_pack_check.setChecked(session.auto_export_pack)
            self.include_sensitive_files_check.setChecked(session.include_sensitive_files)
            self.include_unversioned_files_check.setChecked(session.include_unversioned_files)
            self.auto_create_pack_after_apply_check.setChecked(session.auto_create_pack_after_apply)
            self.export_dir_edit.setText(session.export_dir)
            self.deploy_dir_edit.setText(session.deploy_dir)
            self.auto_deploy_after_commit_check.setChecked(session.auto_deploy_after_commit)
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
        self._current_session_name = self._session_store.load_active_session_name()
        self._reload_session_combo(select_name=self._current_session_name)
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
            patch_target_mode=self._current_patch_target_mode(),
            apply_mode=self._current_apply_mode(),
            allow_unversioned_apply=self.allow_unversioned_apply_check.isChecked(),
            stash_changes_after_undo=self.stash_changes_after_undo_check.isChecked(),
            watch_repository_state=self.watch_repository_state_check.isChecked(),
            auto_export_pack=self.auto_export_pack_check.isChecked(),
            include_sensitive_files=self.include_sensitive_files_check.isChecked(),
            include_unversioned_files=self.include_unversioned_files_check.isChecked(),
            auto_create_pack_after_apply=self.auto_create_pack_after_apply_check.isChecked(),
            export_dir=self.export_dir_edit.text().strip(),
            deploy_dir=self.deploy_dir_edit.text().strip(),
            auto_deploy_after_commit=self.auto_deploy_after_commit_check.isChecked(),
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

    def _browse_export_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select export directory")
        if selected:
            self.export_dir_edit.setText(selected)
            self._schedule_autosave()

    def _browse_deploy_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select deploy directory")
        if selected:
            self.deploy_dir_edit.setText(selected)
            self._schedule_autosave()

    def _browse_patch_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select patch directory")
        if selected:
            self.patch_dir_edit.setText(selected)
            self._refresh_artifact_lists()
            self._schedule_autosave()

    def _refresh_repository_status(self, selected_files: object = None, *, log_result: bool = True) -> None:
        raw_path = self.repo_path_edit.text().strip()
        if not raw_path:
            self._set_no_repo("Repository path is empty.")
            return

        start_dir = Path(raw_path).expanduser()
        if not start_dir.exists():
            self._set_no_repo(f"Path does not exist: {start_dir}")
            return

        snapshot = read_git_repo_state_snapshot(start_dir)
        if snapshot is None:
            self._set_no_repo(f"Not inside a git repository: {start_dir}")
            return

        info = GitRepoInfo(root=snapshot.root, branch=snapshot.branch, is_dirty=snapshot.is_dirty)
        self._repo_state_snapshot = snapshot
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
        if log_result:
            self._append_log(
                "Repository status refreshed:\n"
                f"  root: {info.root}\n"
                f"  branch: {info.branch or 'detached HEAD'}\n"
                f"  status: {'dirty' if info.is_dirty else 'clean'}\n"
                f"  files: {len(files)}"
            )

    def _repository_watch_setting_changed(self, checked: bool) -> None:
        """Persist watcher preference and reset its comparison baseline when enabled."""
        self._schedule_autosave()
        if checked:
            raw_path = self.repo_path_edit.text().strip()
            if raw_path:
                self._repo_state_snapshot = read_git_repo_state_snapshot(Path(raw_path).expanduser())

    def _poll_repository_state(self) -> None:
        """Refresh repository UI when branch, HEAD, or porcelain status changes externally."""
        if (
            self._repository_watch_busy
            or self._loading_session
            or not self.watch_repository_state_check.isChecked()
        ):
            return

        raw_path = self.repo_path_edit.text().strip()
        if not raw_path:
            return

        start_dir = Path(raw_path).expanduser()
        if not start_dir.exists():
            return

        self._repository_watch_busy = True
        try:
            snapshot = read_git_repo_state_snapshot(start_dir)
            previous = self._repo_state_snapshot
            if snapshot is None:
                return
            if previous is None:
                self._repo_state_snapshot = snapshot
                return
            if snapshot == previous:
                return

            if snapshot.root != previous.root:
                self._append_log(f"[repo] repository root changed: {previous.root} -> {snapshot.root}")
            if snapshot.branch != previous.branch:
                old_branch = previous.branch or "detached HEAD"
                new_branch = snapshot.branch or "detached HEAD"
                self._append_log(f"[repo] branch changed: {old_branch} -> {new_branch}")
            if snapshot.head != previous.head:
                old_head = previous.head[:12] or "unborn"
                new_head = snapshot.head[:12] or "unborn"
                self._append_log(f"[repo] HEAD changed: {old_head} -> {new_head}")

            selected_files = self.file_tree.selected_paths()
            self._refresh_repository_status(selected_files=selected_files, log_result=False)
            self.statusBar().showMessage("Repository state updated")
        finally:
            self._repository_watch_busy = False

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
        self._repo_state_snapshot = None
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

    def _current_patch_target_mode(self) -> str:
        mode = self.patch_target_combo.currentData()
        return str(mode or "latest")

    def _set_patch_target_mode(self, mode: str) -> None:
        index = self.patch_target_combo.findData(mode or "latest")
        self.patch_target_combo.setCurrentIndex(index if index >= 0 else 0)

    def _set_apply_mode(self, mode: str) -> None:
        index = self.apply_mode_combo.findData(mode)
        if index < 0:
            index = self.apply_mode_combo.findData(APPLY_MODE_COMPATCH_THEN_PACKPATCH)
        self.apply_mode_combo.setCurrentIndex(index if index >= 0 else 0)

    def _current_apply_mode(self) -> str:
        mode = self.apply_mode_combo.currentData()
        return str(mode or APPLY_MODE_COMPATCH_THEN_PACKPATCH)

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

    def _deploy_repository(self) -> bool:
        if self._repo_info is None:
            self._append_log("Cannot deploy repo: no git repository selected.")
            self.statusBar().showMessage("No git repository selected")
            return False

        deploy_dir_text = self.deploy_dir_edit.text().strip()
        if not deploy_dir_text:
            self._append_log("Cannot deploy repo: deploy directory is empty.")
            self.statusBar().showMessage("Deploy directory is empty")
            return False

        deploy_dir = Path(deploy_dir_text).expanduser()
        self._append_log(
            "Deploying current HEAD tree:\n"
            f"  source: {self._repo_info.root}\n"
            f"  target: {deploy_dir}"
        )
        try:
            result = deploy_repo(self._repo_info.root, deploy_dir)
        except (FileNotFoundError, OSError, ValueError) as error:
            self._append_log(f"Cannot deploy repo: {error}")
            self.statusBar().showMessage("Deploy failed")
            return False

        self._append_log("Command:")
        self._append_log("  " + " ".join(result.command))
        if result.stdout.strip():
            self._append_log(result.stdout.strip())
        if result.stderr.strip():
            self._append_log(result.stderr.strip())

        if result.succeeded:
            self._append_log(f"Deploy completed: current HEAD tree synced to:\n  {deploy_dir.resolve()}")
            self.statusBar().showMessage("Current HEAD tree deployed")
            self._schedule_autosave()
            return True

        self.statusBar().showMessage(f"Deploy failed with exit code {result.returncode}")
        return False

    def _auto_create_pack_after_apply(self) -> None:
        if not self.auto_create_pack_after_apply_check.isChecked():
            self._append_log("Auto pack creation skipped: create pack after apply is disabled.")
            return

        self._append_log("Auto pack creation triggered after successful apply.")
        self._create_pack()

    def _auto_deploy_after_commit(self) -> None:
        if not self.auto_deploy_after_commit_check.isChecked():
            self._append_log("Auto deploy skipped: auto deploy after commit is disabled.")
            return

        self._append_log("Auto deploy triggered after commit.")
        if self._deploy_repository():
            self._append_log("Auto deploy completed successfully.")
        else:
            self._append_log("Auto deploy after commit failed.")

    def _create_pack(self) -> None:
        if self._repo_info is None:
            self._append_log("Cannot create pack: no git repository selected.")
            self.statusBar().showMessage("No git repository selected")
            return

        selected_files = self.file_tree.selected_paths()
        mode = self._current_pack_mode()
        task_name = self._ensure_task_name_for_mode(mode)

        self._append_log(f"Creating pack with mode: {PACK_MODE_LABELS.get(mode, mode)}...")
        if self.include_sensitive_files_check.isChecked():
            self._append_log("Pack sensitive files: including tracked keys/certificates.")
        else:
            self._append_log("Pack sensitive files: excluded.")
        if self.include_unversioned_files_check.isChecked():
            self._append_log("Pack unversioned files: included.")
        else:
            self._append_log("Pack unversioned files: excluded.")
        try:
            result = create_pack(
                self._repo_info.root,
                mode,
                task_name,
                selected_files,
                include_sensitive=self.include_sensitive_files_check.isChecked(),
                include_unversioned=self.include_unversioned_files_check.isChecked(),
            )
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
            self._export_created_pack(result.archive_path)
            self.statusBar().showMessage("Pack created")
            self._refresh_artifact_lists()
            self._schedule_autosave()
        else:
            self.statusBar().showMessage(f"Pack creation failed with exit code {result.returncode}")

    def _export_created_pack(self, archive_path: Path | None) -> None:
        if not self.auto_export_pack_check.isChecked():
            return

        export_dir_text = self.export_dir_edit.text().strip()
        if not export_dir_text:
            self._append_log("Cannot export pack: export directory is empty.")
            self.statusBar().showMessage("Export directory is empty")
            return

        if archive_path is None:
            self._append_log("Cannot export pack: created archive path was not found in command output.")
            self.statusBar().showMessage("Pack export failed")
            return

        export_dir = Path(export_dir_text).expanduser()
        try:
            export_dir.mkdir(parents=True, exist_ok=True)
            destination = export_dir / archive_path.name
            shutil.copy2(archive_path, destination)
        except OSError as error:
            self._append_log(f"Cannot export pack: {error}")
            self.statusBar().showMessage("Pack export failed")
            return

        self._append_log(f"Exported pack:\n  {destination}")
        self.statusBar().showMessage("Pack exported")

    def _pack_drag_path(self, pack_path: Path) -> Path:
        """Prefer the exported Windows-accessible copy for pack file drags."""
        export_dir_text = self.export_dir_edit.text().strip()
        if export_dir_text:
            exported_path = Path(export_dir_text).expanduser() / pack_path.name
            if exported_path.is_file():
                return exported_path
        return pack_path

    def _show_selected_pack_in_explorer(self) -> None:
        """Open Windows Explorer and select the preferred copy of the current pack."""
        item = self.pack_list.currentItem()
        if item is None:
            self._append_log("Cannot show pack in Explorer: no pack selected.")
            self.statusBar().showMessage("No pack selected")
            return

        value = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(value, str) or not value:
            self._append_log("Cannot show pack in Explorer: selected pack has no path metadata.")
            self.statusBar().showMessage("Cannot show pack in Explorer")
            return

        pack_path = self._pack_drag_path(Path(value).expanduser())
        if not pack_path.is_file():
            self._append_log(f"Cannot show pack in Explorer: file not found:\n  {pack_path}")
            self.statusBar().showMessage("Pack file not found")
            return

        try:
            windows_path = run_process(["wslpath", "-w", str(pack_path.resolve())]).stdout.strip()
            if not windows_path:
                raise ValueError("wslpath returned an empty Windows path")
            run_process(["explorer.exe", f"/select,{windows_path}"], check=False)
        except (FileNotFoundError, OSError, ValueError) as error:
            self._append_log(f"Cannot show pack in Explorer: {error}")
            self.statusBar().showMessage("Explorer open failed")
            return

        self._append_log(f"Opened pack in Explorer:\n  {pack_path}")
        self.statusBar().showMessage("Pack shown in Explorer")

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

    def _selected_patch_paths(self) -> list[Path]:
        paths: list[Path] = []
        for item in self.patch_list.selectedItems():
            path = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(path, str) and path:
                paths.append(Path(path).expanduser())
        return paths

    def _selected_patch_path(self) -> Path | None:
        paths = self._selected_patch_paths()
        if len(paths) == 1:
            return paths[0]

        item = self.patch_list.currentItem()
        if item is None:
            return None

        path = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(path, str) or not path:
            return None
        return Path(path).expanduser()

    def _patch_action_path(self) -> tuple[Path | None, bool]:
        mode = self._current_patch_target_mode()
        patch_dir = Path(self.patch_dir_edit.text().strip()).expanduser()

        if mode == "latest":
            try:
                return latest_patch_path(patch_dir), True
            except FileNotFoundError as error:
                self._append_log(f"Cannot resolve latest patch: {error}")
                self.statusBar().showMessage("No latest patch found")
                return None, False

        paths = self._selected_patch_paths()
        if len(paths) != 1:
            if paths:
                names = "\n".join(f"  {path}" for path in paths)
                self._append_log(
                    "Cannot run patch action: selected mode requires exactly one patch; "
                    f"{len(paths)} patches selected.\n{names}"
                )
                self.statusBar().showMessage("Select exactly one patch")
            else:
                self._append_log("Cannot run patch action: selected mode requires one selected patch.")
                self.statusBar().showMessage("No patch selected")
            return None, False
        return paths[0], True

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

    def _selected_artifact_paths(self, widget: QListWidget) -> list[Path]:
        paths: list[Path] = []
        for item in widget.selectedItems():
            path_value = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(path_value, str) and path_value:
                paths.append(Path(path_value).expanduser())
        return paths

    def _delete_selected_artifacts(
        self,
        widget: QListWidget,
        label: str,
    ) -> None:
        paths = self._selected_artifact_paths(widget)
        if not paths:
            self._append_log(f"No {label} selected.")
            self.statusBar().showMessage(f"No {label} selected")
            return

        preview_items = "\n".join(f"  {path}" for path in paths[:10])
        if len(paths) > 10:
            preview_items += f"\n  ... and {len(paths) - 10} more"

        plural_label = f"{label}s" if len(paths) != 1 else label
        response = QMessageBox.question(
            self,
            f"Delete selected {plural_label}",
            f"Delete {len(paths)} selected {plural_label}?\n\n{preview_items}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            self._append_log(f"Delete {plural_label} cancelled.")
            self.statusBar().showMessage(f"Delete {plural_label} cancelled")
            return

        deleted: list[Path] = []
        failed: list[str] = []
        for path in paths:
            try:
                removed_files = delete_artifact(path)
                deleted.extend(removed_files)
                if label == "pack":
                    deleted.extend(self._delete_exported_pack_copies(removed_files))
            except (OSError, ValueError) as error:
                failed.append(f"{path}: {error}")

        if deleted:
            deleted_preview = "\n".join(f"  {item}" for item in deleted)
            self._append_log(f"Deleted {label} artifact files:\n{deleted_preview}")
        else:
            self._append_log(f"No files deleted for selected {plural_label}.")

        if failed:
            failed_preview = "\n".join(f"  {item}" for item in failed)
            self._append_log(f"Failed to delete some {plural_label}:\n{failed_preview}")

        if label == "patch":
            self.patch_preview.clear()
        self._refresh_artifact_lists()
        self.statusBar().showMessage(f"Deleted {len(deleted)} artifact file(s)")

    def _delete_exported_pack_copies(self, removed_files: list[Path]) -> list[Path]:
        export_dir_text = self.export_dir_edit.text().strip()
        if not export_dir_text:
            return []

        export_dir = Path(export_dir_text).expanduser()
        if not export_dir.is_dir():
            return []

        deleted: list[Path] = []
        for removed_file in removed_files:
            exported_path = export_dir / removed_file.name
            if not exported_path.exists():
                continue
            if not exported_path.is_file():
                self._append_log(f"Skipped exported pack cleanup for non-file path:\n  {exported_path}")
                continue
            exported_path.unlink()
            deleted.append(exported_path)

        return deleted

    def _check_latest_patch(self) -> None:
        if self._repo_info is None:
            self._append_log("Cannot check patch: no git repository selected.")
            self.statusBar().showMessage("No git repository selected")
            return

        patch_dir = Path(self.patch_dir_edit.text().strip()).expanduser()
        patch_path, ok = self._patch_action_path()
        if not ok:
            return
        mode = self._current_patch_target_mode()
        label = "latest patch" if mode == "latest" else "selected patch"
        self._append_log(f"Checking {label}...")
        self._append_log(f"Patch target mode: {mode}")
        self._append_log(f"Checking patch:\n  {patch_path}")

        try:
            result = check_latest_patch(self._repo_info.root, patch_dir, patch_path=patch_path)
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
            self._append_log("Patch check failed: clean apply is not possible; Apply patch may use fallback.")
            self.statusBar().showMessage(f"Patch check failed with exit code {result.returncode}")

    def _apply_latest_patch(self, *, dry_run: bool) -> None:
        if self._repo_info is None:
            self._append_log("Cannot apply patch: no git repository selected.")
            self.statusBar().showMessage("No git repository selected")
            return

        patch_dir = Path(self.patch_dir_edit.text().strip()).expanduser()
        patch_path, ok = self._patch_action_path()
        if not ok:
            return
        mode = self._current_patch_target_mode()
        apply_mode = self._current_apply_mode()
        label = "latest patch" if mode == "latest" else "selected patch"
        action = f"Dry-running {label}" if dry_run else f"Applying {label}"
        self._append_log(f"{action}...")
        self._append_log(f"Patch target mode: {mode}")
        self._append_log(f"Apply mode: {APPLY_MODE_LABELS[apply_mode]}")
        if self.allow_unversioned_apply_check.isChecked():
            self._append_log("Apply safety: unversioned files are allowed; tracked changes still block apply.")
        if dry_run:
            self._append_log(f"Dry-running patch:\n  {patch_path}")
        else:
            self._append_log(f"Applying patch:\n  {patch_path}")

        commit_message = self.commit_message_edit.text().strip() if not dry_run else ""
        if commit_message:
            self._append_log("Apply commit message is set: PackPatch apply will create a local commit.")

        try:
            result = apply_latest_patch(
                self._repo_info.root,
                patch_dir,
                dry_run=dry_run,
                commit_message=commit_message,
                patch_path=patch_path,
                apply_mode=apply_mode,
                allow_unversioned_files=self.allow_unversioned_apply_check.isChecked(),
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
            elif result.created_commit:
                if commit_message and result.applied_with == "PackPatch":
                    self.commit_message_edit.clear()
                    self._append_log("Apply commit message field cleared after successful PackPatch commit.")
                self._append_log(f"Apply completed via {result.applied_with}; commit was created.")
                self.statusBar().showMessage(f"Patch applied via {result.applied_with} and committed")
                self._auto_deploy_after_commit()
            else:
                if not dry_run:
                    self._append_log(f"Apply completed via {result.applied_with}; no commit was created.")
                    self._append_log("Auto deploy skipped: no commit was created.")
                self.statusBar().showMessage(f"Patch applied via {result.applied_with}")
            self._refresh_repository_status()
            if not dry_run and result.was_applied:
                self._auto_create_pack_after_apply()
            elif not dry_run and self.auto_create_pack_after_apply_check.isChecked():
                self._append_log("Auto pack creation skipped: patch did not apply new changes.")
            self._schedule_autosave()
        else:
            self.statusBar().showMessage(f"Patch command failed with exit code {result.returncode}")

    def _undo_last_commit(self) -> None:
        if self._repo_info is None:
            self._append_log("Cannot undo commit: no git repository selected.")
            self.statusBar().showMessage("No git repository selected")
            return

        stash_after_undo = self.stash_changes_after_undo_check.isChecked()
        self._append_log("Undoing last commit with git reset --mixed HEAD~1...")
        result = undo_last_commit(self._repo_info.root, stash_changes=stash_after_undo)
        self._append_log("Command:")
        self._append_log("  " + " ".join(result.reset_command))
        if result.reset_stdout.strip():
            self._append_log(result.reset_stdout.strip())
        if result.reset_stderr.strip():
            self._append_log(result.reset_stderr.strip())

        if not result.reset_succeeded:
            self.statusBar().showMessage(f"Undo failed with exit code {result.reset_returncode}")
            return

        self._append_log("Last commit was reset; its changes remain in the working tree.")

        if result.stash_requested:
            if result.unversioned_files:
                self._append_log("Unversioned files before stash:")
                for path in result.unversioned_files:
                    self._append_log(f"  {path}")
            else:
                self._append_log("No unversioned files will be included in the stash.")

            self._append_log("Stashing working tree changes, including unversioned files...")
            if result.stash_command is not None:
                self._append_log("Command:")
                self._append_log("  " + " ".join(result.stash_command))
            if result.stash_stdout.strip():
                self._append_log(result.stash_stdout.strip())
            if result.stash_stderr.strip():
                self._append_log(result.stash_stderr.strip())

            if result.stash_succeeded:
                if result.stash_ref:
                    self._append_log(f"Stash created: {result.stash_ref}")
                else:
                    self._append_log("Stash completed; no stash entry was created.")
                self.statusBar().showMessage("Last commit undone and changes stashed")
            else:
                self._append_log("Commit was reset, but stash failed; changes remain in the working tree.")
                self.statusBar().showMessage("Commit undone, but stash failed")
        else:
            self.statusBar().showMessage("Last commit undone")

        self._refresh_repository_status()
        self._schedule_autosave()

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
        """Append timestamped log output with lightweight severity-based coloring."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        lines = message.splitlines() or [""]
        timestamped_lines = [f"[{timestamp}] {line}" for line in lines]
        html_lines = [self._format_log_line(line) for line in timestamped_lines]
        self.log.append("<br>".join(html_lines))
        self._scroll_log_to_bottom()

    def _scroll_log_to_bottom(self) -> None:
        self.log.moveCursor(QTextCursor.MoveOperation.End)
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

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
