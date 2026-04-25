"""Main application window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from packpatch_ui.config import APP_NAME


class MainWindow(QMainWindow):
    """Initial working window for the PackPatch UI."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(900, 600)
        self.setCentralWidget(self._build_central_widget())
        self.setStatusBar(self._build_status_bar())

    def _build_central_widget(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel(APP_NAME, widget)
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        title.setStyleSheet("font-size: 22px; font-weight: 600;")

        description = QLabel(
            "PackPatch UI is running. Next steps: connect repository detection, file tree selection, "
            "pack creation, and patch application.",
            widget,
        )
        description.setWordWrap(True)

        refresh_button = QPushButton("Refresh repository status", widget)
        refresh_button.setEnabled(False)
        refresh_button.setToolTip("Repository status support will be added in the next milestone.")

        log = QTextEdit(widget)
        log.setReadOnly(True)
        log.setPlaceholderText("Command output will appear here.")
        log.setMinimumHeight(260)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(refresh_button)
        layout.addWidget(log, stretch=1)
        return widget

    def _build_status_bar(self) -> QStatusBar:
        status_bar = QStatusBar(self)
        status_bar.showMessage("Ready")
        return status_bar
