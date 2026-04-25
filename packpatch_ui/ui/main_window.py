"""Main application window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
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
    QPushButton,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from packpatch_ui.config import APP_NAME
from packpatch_ui.core.artifacts import ArtifactInfo, list_pack_archives, list_patch_files
from packpatch_ui.core.git_repo import GitRepoInfo, list_repo_files, read_git_repo_info
from packpatch_ui.core.pack_runner import create_slice_pack
from packpatch_ui.core.patch_runner import apply_latest_patch
from packpatch_ui.services.settings_store import AppSession, DEFAULT_SESSION_NAME, SessionStore
from packpatch_ui.ui.file_tree import FileTreeWidget


class MainWindow(QMainWindow):
    """Main window with repository status, file selection, pack creation, and patch apply controls."""

    def __init__(self) -> None:
        super().__init__()
        self._repo_info: GitRepoInfo | None = None
        self._session_store = SessionStore()
        self._loading_session = False
        self._current_session_name = DEFAULT_SESSION_NAME

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

        self.task_name_edit = QLineEdit(self)
        self.task_name_edit.setPlaceholderText("Task name for slice pack, e.g. fix-ui")
        self.create_pack_button = QPushButton("Create slice pack", self)

        self.patch_dir_edit = QLineEdit(self)
        self.patch_dir_edit.setPlaceholderText("Directory with .patch/.diff files, e.g. ~/Downloads")
        self.patch_dir_edit.setText(str(Path.home() / "Downloads"))
        self.browse_patch_dir_button = QPushButton("Browse patches...", self)
        self.dry_run_patch_button = QPushButton("Dry-run latest patch", self)
        self.apply_latest_patch_button = QPushButton("Apply latest patch", self)

        self.refresh_artifacts_button = QPushButton("Refresh packs/patches", self)
        self.copy_pack_path_button = QPushButton("Copy pack path", self)
        self.copy_patch_path_button = QPushButton("Copy patch path", self)
        self.pack_list = QListWidget(self)
        self.patch_list = QListWidget(self)
        self.pack_list.setAlternatingRowColors(True)
        self.patch_list.setAlternatingRowColors(True)

        self.file_tree = FileTreeWidget()
        self.check_all_button = QPushButton("Check all", self)
        self.clear_selection_button = QPushButton("Clear", self)
        self.selection_value = QLabel("0 files selected", self)

        self.log = QTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Command output and status messages will appear here.")
        self.log.setMinimumHeight(220)

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

    def _build_central_widget(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel(APP_NAME, widget)
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        title.setStyleSheet("font-size: 22px; font-weight: 600;")

        description = QLabel(
            "Select a repository, choose files, create slice packs, and apply generated patches.",
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

        status_grid = QGridLayout()
        status_grid.setHorizontalSpacing(12)
        status_grid.setVerticalSpacing(8)
        status_grid.addWidget(QLabel("Git root:", widget), 0, 0)
        status_grid.addWidget(self.root_value, 0, 1)
        status_grid.addWidget(QLabel("Branch:", widget), 1, 0)
        status_grid.addWidget(self.branch_value, 1, 1)
        status_grid.addWidget(QLabel("Status:", widget), 2, 0)
        status_grid.addWidget(self.status_value, 2, 1)
        status_grid.setColumnStretch(1, 1)

        pack_controls = QHBoxLayout()
        pack_controls.addWidget(QLabel("Task:", widget))
        pack_controls.addWidget(self.task_name_edit, stretch=1)
        pack_controls.addWidget(self.create_pack_button)

        patch_controls = QHBoxLayout()
        patch_controls.addWidget(QLabel("Patches:", widget))
        patch_controls.addWidget(self.patch_dir_edit, stretch=1)
        patch_controls.addWidget(self.browse_patch_dir_button)
        patch_controls.addWidget(self.dry_run_patch_button)
        patch_controls.addWidget(self.apply_latest_patch_button)

        artifact_controls = QHBoxLayout()
        artifact_controls.addWidget(self.refresh_artifacts_button)
        artifact_controls.addStretch(1)
        artifact_controls.addWidget(self.copy_pack_path_button)
        artifact_controls.addWidget(self.copy_patch_path_button)

        artifact_lists = QHBoxLayout()
        pack_column = QVBoxLayout()
        pack_column.addWidget(QLabel("Latest packs", widget))
        pack_column.addWidget(self.pack_list)
        patch_column = QVBoxLayout()
        patch_column.addWidget(QLabel("Latest patches", widget))
        patch_column.addWidget(self.patch_list)
        artifact_lists.addLayout(pack_column, stretch=1)
        artifact_lists.addLayout(patch_column, stretch=1)

        tree_controls = QHBoxLayout()
        tree_controls.addWidget(self.check_all_button)
        tree_controls.addWidget(self.clear_selection_button)
        tree_controls.addStretch(1)
        tree_controls.addWidget(self.selection_value)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(session_row)
        layout.addLayout(repo_row)
        layout.addLayout(status_grid)
        layout.addLayout(pack_controls)
        layout.addLayout(patch_controls)
        layout.addLayout(artifact_controls)
        layout.addLayout(artifact_lists, stretch=1)
        layout.addLayout(tree_controls)
        layout.addWidget(self.file_tree, stretch=2)
        layout.addWidget(self.log, stretch=1)
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
        self.task_name_edit.textEdited.connect(lambda *_: self._schedule_autosave())

        self.check_all_button.clicked.connect(self._check_all_files)
        self.clear_selection_button.clicked.connect(self._clear_file_selection)
        self.create_pack_button.clicked.connect(self._create_slice_pack)
        self.browse_patch_dir_button.clicked.connect(self._browse_patch_directory)
        self.dry_run_patch_button.clicked.connect(lambda: self._apply_latest_patch(dry_run=True))
        self.apply_latest_patch_button.clicked.connect(lambda: self._apply_latest_patch(dry_run=False))
        self.refresh_artifacts_button.clicked.connect(self._refresh_artifact_lists)
        self.copy_pack_path_button.clicked.connect(lambda: self._copy_selected_artifact_path(self.pack_list, "pack"))
        self.copy_patch_path_button.clicked.connect(lambda: self._copy_selected_artifact_path(self.patch_list, "patch"))
        self.file_tree.itemChanged.connect(lambda *_: self._selection_changed())

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
            self.task_name_edit.setText(session.task_name)
        finally:
            self._loading_session = False

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
            selected_files=self.file_tree.selected_paths(),
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
        normalized_selection = self._normalize_selected_files(selected_files)
        if normalized_selection is not None:
            self.file_tree.set_selected_paths(normalized_selection)
        self._update_selection_count()
        self._refresh_artifact_lists()
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
        self._update_selection_count()
        self.statusBar().showMessage(message)
        self._append_log(message)

    def _check_all_files(self) -> None:
        self.file_tree.check_all()
        self._selection_changed()

    def _clear_file_selection(self) -> None:
        self.file_tree.clear_selection()
        self._selection_changed()

    def _selection_changed(self) -> None:
        self._update_selection_count()
        self._schedule_autosave()

    def _update_selection_count(self) -> None:
        count = len(self.file_tree.selected_paths())
        self.selection_value.setText(f"{count} file{'s' if count != 1 else ''} selected")

    def _create_slice_pack(self) -> None:
        if self._repo_info is None:
            self._append_log("Cannot create pack: no git repository selected.")
            self.statusBar().showMessage("No git repository selected")
            return

        selected_files = self.file_tree.selected_paths()
        task_name = self.task_name_edit.text().strip()

        self._append_log("Creating slice pack...")
        try:
            result = create_slice_pack(self._repo_info.root, task_name, selected_files)
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
            self.statusBar().showMessage("Slice pack created")
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

    def _apply_latest_patch(self, *, dry_run: bool) -> None:
        if self._repo_info is None:
            self._append_log("Cannot apply patch: no git repository selected.")
            self.statusBar().showMessage("No git repository selected")
            return

        patch_dir = Path(self.patch_dir_edit.text().strip()).expanduser()
        action = "Dry-running latest patch" if dry_run else "Applying latest patch"
        self._append_log(f"{action}...")

        try:
            result = apply_latest_patch(self._repo_info.root, patch_dir, dry_run=dry_run)
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
            self.statusBar().showMessage("Patch dry-run completed" if dry_run else "Patch applied")
            self._refresh_repository_status()
            self._schedule_autosave()
        else:
            self.statusBar().showMessage(f"Patch command failed with exit code {result.returncode}")

    def _append_log(self, message: str) -> None:
        self.log.append(message)
