"""Main application window."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget

from packpatch_ui.config import APP_NAME


class MainWindow(QMainWindow):
    """Initial placeholder window for the PackPatch UI."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(900, 600)
        self.setCentralWidget(self._build_central_widget())

    def _build_central_widget(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("PackPatch UI skeleton is ready."))
        return widget
