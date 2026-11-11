"""Placement of small app-owned dialogs after initial display."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from packpatch_ui.ui.main_window import MainWindow
import packpatch_ui.ui.dialog_positioning as placement


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    main = MainWindow()
    qtbot.addWidget(main)
    main.show()
    QApplication.processEvents()
    main._autosave_timer.stop()
    main._repository_watch_timer.stop()
    return main


@pytest.mark.parametrize("dialog_type", [QDialog, QMessageBox])
def test_dialog_is_centered_after_show(window, qtbot, dialog_type):
    dialog = dialog_type(window)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.isVisible())
    # Process queued centering after Qt has finalized the window size.
    QApplication.processEvents()
    QApplication.processEvents()
    screen = window.windowHandle().screen()
    available = screen.availableGeometry()
    frame = dialog.frameGeometry()
    assert available.contains(frame.topLeft())
    # A dialog that fits should be fully visible in the available screen area.
    if frame.width() <= available.width() and frame.height() <= available.height():
        assert available.contains(frame.bottomRight())
    expected_x = max(available.left(), min(window.frameGeometry().center().x() - frame.width() // 2, available.right() - frame.width() + 1))
    expected_y = max(available.top(), min(window.frameGeometry().center().y() - frame.height() // 2, available.bottom() - frame.height() + 1))
    assert abs(frame.left() - expected_x) <= 2
    assert abs(frame.top() - expected_y) <= 2


def test_file_dialog_is_not_intercepted(window, monkeypatch):
    recorded = []
    monkeypatch.setattr(placement, "center_dialog", lambda *args: recorded.append(args))
    dialog = QFileDialog(window)
    event_filter = window._dialog_positioning_filter
    event_filter.eventFilter(dialog, QEvent(QEvent.Type.Show))
    QApplication.processEvents()
    assert recorded == []


def test_unrelated_dialog_is_not_intercepted(window, monkeypatch):
    recorded = []
    monkeypatch.setattr(placement, "center_dialog", lambda *args: recorded.append(args))
    dialog = QDialog()
    event_filter = window._dialog_positioning_filter
    event_filter.eventFilter(dialog, QEvent(QEvent.Type.Show))
    QApplication.processEvents()
    assert recorded == []
