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
from packpatch_ui.core.git_repo import GitRepoInfo, read_git_repo_info


class MainWindow(QMainWindow):
    """Main window with initial repository status controls."""

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

        self.log = QTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Command output and status messages will appear here.")
        self.log.setMinimumHeight(260)

        self.setWindowTitle(APP_NAME)
        self.resize(980, 640)
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
            "Select a repository and refresh its status. File tree selection, pack creation, "
            "and patch application will be added in the next milestones.",
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

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(repo_row)
        layout.addLayout(status_grid)
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

    def _browse_repository(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select git repository")
        if selected:
            self.repo_path_edit.setText(selected)
            self._refresh_repository_status()

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
        self.statusBar().showMessage("Repository status refreshed")
        self._append_log(
            "Repository status refreshed:\n"
            f"  root: {info.root}\n"
            f"  branch: {info.branch or 'detached HEAD'}\n"
            f"  status: {'dirty' if info.is_dirty else 'clean'}"
        )

    def _set_no_repo(self, message: str) -> None:
        self._repo_info = None
        self.root_value.setText("-")
        self.branch_value.setText("-")
        self.status_value.setText("not available")
        self.statusBar().showMessage(message)
        self._append_log(message)

    def _append_log(self, message: str) -> None:
        self.log.append(message)
