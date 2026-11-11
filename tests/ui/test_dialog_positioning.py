"""Placement of small app-owned dialogs after initial display."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

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


@pytest.mark.parametrize("dialog_type", [QDialog, QMessageBox, QInputDialog])
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


def test_qt_file_dialog_is_positioned(window, qtbot, monkeypatch):
    recorded = []
    monkeypatch.setattr(placement, "center_dialog", lambda *args: recorded.append(args))
    dialog = QFileDialog(window)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: bool(recorded))
    assert (dialog, window) in recorded


def test_choose_directory_uses_qt_widget_picker(window, monkeypatch):
    recorded = []

    class Picker(QFileDialog):
        def exec(self):
            recorded.append((self.parentWidget(), self.windowTitle()))
            assert self.testOption(QFileDialog.Option.DontUseNativeDialog)
            assert self.testOption(QFileDialog.Option.ShowDirsOnly)
            assert self.fileMode() == QFileDialog.FileMode.Directory
            return QDialog.DialogCode.Accepted

        def selectedFiles(self):  # noqa: N802
            return ["/tmp/my-project"]

    monkeypatch.setattr(placement, "QFileDialog", Picker)
    assert placement.choose_directory(window, "Select git repository") == "/tmp/my-project"
    assert recorded == [(window, "Select git repository")]


def test_choose_directory_cancel_returns_empty(window, monkeypatch):
    class Picker(QFileDialog):
        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(placement, "QFileDialog", Picker)
    assert placement.choose_directory(window, "Select patch directory") == ""


def test_wayland_skips_unsupported_dialog_move(window, qtbot, monkeypatch):
    dialog = QDialog(window)
    qtbot.addWidget(dialog)
    dialog.show()
    QApplication.processEvents()
    previous = dialog.pos()
    monkeypatch.setattr(placement, "_can_position_top_level_windows", lambda: False)
    placement.center_dialog(dialog, window)
    assert dialog.pos() == previous


def test_show_filter_positions_dialog_synchronously(window, monkeypatch):
    calls = []
    original = placement.center_dialog

    def record(dialog, owner):
        calls.append((dialog, owner))
        return original(dialog, owner)

    monkeypatch.setattr(placement, "center_dialog", record)
    dialog = QDialog(window)
    dialog.setWindowTitle("Synchronous placement")
    dialog.show()
    # No event-loop tick: this must run before QDialog.showEvent() completes.
    assert calls and calls[0] == (dialog, window)
    assert dialog.testAttribute(Qt.WidgetAttribute.WA_Moved)


def test_exec_centered_prepositions_dialog(window, monkeypatch):
    dialog = QDialog(window)
    dialog.setWindowTitle("Before exec")
    observed = []

    def fake_exec(self):
        observed.append((self.pos(), self.testAttribute(Qt.WidgetAttribute.WA_Moved)))
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    assert placement.exec_centered(dialog, window) == QDialog.DialogCode.Rejected
    assert len(observed) == 1
    assert observed[0][1] is True
    assert observed[0][0] == placement.expected_dialog_position(dialog, window)


def test_verification_reports_actual_geometry_and_backend(window, monkeypatch):
    recorded = []
    diag = placement.DialogPositioningFilter(window, report=lambda message, failed: recorded.append((message, failed)))
    dialog = QDialog(window)
    dialog.setWindowTitle("Position debug")
    dialog.show()
    QApplication.processEvents()

    monkeypatch.setattr(placement, "expected_dialog_position", lambda *_: QPoint(40000, 40000))
    monkeypatch.setattr(placement, "center_dialog", lambda *_: None)
    monkeypatch.setattr(placement, "_can_position_top_level_windows", lambda: True)
    diag._verify(dialog)
    assert len(recorded) == 1
    report, failed = recorded[0]
    assert failed
    assert "Position debug" in report
    assert "Qt=" in report
    assert "owner=(" in report
    assert "target=(40000,40000)" in report
    assert "actual=(" in report
    assert "status=mismatch" in report


def test_verification_ignores_compositor_managed_coordinates(window, monkeypatch):
    recorded = []
    diag = placement.DialogPositioningFilter(window, report=lambda message, failed: recorded.append((message, failed)))
    dialog = QDialog(window)
    dialog.show()
    QApplication.processEvents()

    monkeypatch.setattr(placement, "expected_dialog_position", lambda *_: QPoint(40000, 40000))
    monkeypatch.setattr(placement, "_can_position_top_level_windows", lambda: False)
    diag._verify(dialog)
    assert recorded and recorded[-1][1] is False
    assert "status=compositor-managed" in recorded[-1][0]
