"""Main application window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from packpatch_ui.config import APP_NAME
from packpatch_ui.core.git_repo import GitRepoInfo, list_repo_files, read_git_repo_info
from packpatch_ui.core.pack_runner import create_slice_pack
from packpatch_ui.core.patch_runner import apply_latest_patch
from packpatch_ui.ui.file_tree import FileTreeWidget


class MainWindow(QMainWindow):
    """Main window with repository status, file selection, pack creation, and patch apply controls."""

    def __init__(self) -> None:
        super().__init__()
        self._repo_info: GitRepoInfo | None = None

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

        self.file_tree = FileTreeWidget()
        self.check_all_button = QPushButton("Check all", self)
        self.clear_selection_button = QPushButton("Clear", self)
        self.selection_value = QLabel("0 files selected", self)

        self.log = QTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Command output and status messages will appear here.")
        self.log.setMinimumHeight(220)

        self.setWindowTitle(APP_NAME)
        self.resize(1120, 780)
        self.setCentralWidget(self._build_central_widget())
        self.setStatusBar(self._build_status_bar())
        self._connect_signals()

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

        tree_controls = QHBoxLayout()
        tree_controls.addWidget(self.check_all_button)
        tree_controls.addWidget(self.clear_selection_button)
        tree_controls.addStretch(1)
        tree_controls.addWidget(self.selection_value)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(repo_row)
        layout.addLayout(status_grid)
        layout.addLayout(pack_controls)
        layout.addLayout(patch_controls)
        layout.addLayout(tree_controls)
        layout.addWidget(self.file_tree, stretch=2)
        layout.addWidget(self.log, stretch=1)
        return widget

    def _build_status_bar(self) -> QStatusBar:
        status_bar = QStatusBar(self)
        status_bar.showMessage("Ready")
        return status_bar

    def _connect_signals(self) -> None:
        self.browse_button.clicked.connect(self._browse_repository)
        self.refresh_button.clicked.connect(self._refresh_repository_status)
        self.repo_path_edit.returnPressed.connect(self._refresh_repository_status)
        self.check_all_button.clicked.connect(self._check_all_files)
        self.clear_selection_button.clicked.connect(self._clear_file_selection)
        self.create_pack_button.clicked.connect(self._create_slice_pack)
        self.browse_patch_dir_button.clicked.connect(self._browse_patch_directory)
        self.dry_run_patch_button.clicked.connect(lambda: self._apply_latest_patch(dry_run=True))
        self.apply_latest_patch_button.clicked.connect(lambda: self._apply_latest_patch(dry_run=False))
        self.file_tree.itemChanged.connect(lambda *_: self._update_selection_count())

    def _browse_repository(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select git repository")
        if selected:
            self.repo_path_edit.setText(selected)
            self._refresh_repository_status()

    def _browse_patch_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select patch directory")
        if selected:
            self.patch_dir_edit.setText(selected)

    def _refresh_repository_status(self) -> None:
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
        self._update_selection_count()

        self.statusBar().showMessage("Repository status refreshed")
        self._append_log(
            "Repository status refreshed:\n"
            f"  root: {info.root}\n"
            f"  branch: {info.branch or 'detached HEAD'}\n"
            f"  status: {'dirty' if info.is_dirty else 'clean'}\n"
            f"  files: {len(files)}"
        )

    def _set_no_repo(self, message: str) -> None:
        self._repo_info = None
        self.root_value.setText("-")
        self.branch_value.setText("-")
        self.status_value.setText("not available")
        self.file_tree.clear()
        self._update_selection_count()
        self.statusBar().showMessage(message)
        self._append_log(message)

    def _check_all_files(self) -> None:
        self.file_tree.check_all()
        self._update_selection_count()

    def _clear_file_selection(self) -> None:
        self.file_tree.clear_selection()
        self._update_selection_count()

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
        else:
            self.statusBar().showMessage(f"Pack creation failed with exit code {result.returncode}")

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
        else:
            self.statusBar().showMessage(f"Patch command failed with exit code {result.returncode}")

    def _append_log(self, message: str) -> None:
        self.log.append(message)
