"""Application bootstrap for PackPatch UI."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from packpatch_ui.qt_platform import configure_qt_platform
from packpatch_ui.ui.main_window import MainWindow


def main() -> int:
    """Run the PackPatch UI application."""
    configure_qt_platform()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
