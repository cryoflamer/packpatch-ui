"""Place application-owned dialogs near their parent, including on their first show."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QFileDialog, QWidget


# Called with a diagnostic message and whether a placement problem was detected.
PlacementReporter = Callable[[str, bool], None]


def _can_position_top_level_windows() -> bool:
    return not QGuiApplication.platformName().startswith("wayland")


def expected_dialog_position(dialog: QDialog, owner: QWidget) -> QPoint | None:
    """Compute frame top-left in the window system's coordinates (not client-local)."""
    screen = owner.windowHandle().screen() if owner.windowHandle() else None
    if screen is None:
        screen = QGuiApplication.screenAt(owner.frameGeometry().center())
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None

    available = screen.availableGeometry()
    owner_rect = owner.frameGeometry()
    dialog_rect = dialog.frameGeometry()
    width, height = dialog_rect.width(), dialog_rect.height()
    x = owner_rect.center().x() - width // 2
    y = owner_rect.center().y() - height // 2
    return QPoint(
        max(available.left(), min(x, available.right() - width + 1)),
        max(available.top(), min(y, available.bottom() - height + 1)),
    )


def center_dialog(dialog: QDialog, owner: QWidget) -> QPoint | None:
    """Explicitly position a dialog, even *before* its first showEvent.

    QDialog.showEvent() applies its own default placement unless WA_Moved is
    set.  Positioning only in a queued callback is too late to control the
    initial position, especially with WSLg's window integration.
    """
    try:
        if not owner.isVisible() or not _can_position_top_level_windows():
            return None
        if not dialog.isVisible():
            dialog.adjustSize()
        target = expected_dialog_position(dialog, owner)
        if target is not None:
            dialog.move(target)
            # Do not let QDialog.showEvent overwrite an explicitly chosen spot.
            dialog.setAttribute(Qt.WidgetAttribute.WA_Moved, True)
        return target
    except RuntimeError:
        # A static dialog may have been destroyed before a queued callback.
        return None


def exec_centered(dialog: QDialog, owner: QWidget) -> int:
    """Set the initial geometry before Qt enters its modal show/exec path."""
    center_dialog(dialog, owner)
    return dialog.exec()


class DialogPositioningFilter(QObject):
    """Place owned dialogs synchronously at Show, then verify after mapping.

    An event filter sees QEvent.Show before QDialog.showEvent(), letting us
    establish WA_Moved before Qt's automatic positioning runs.  Follow-up
    corrections handle platform window-manager placement after mapping.
    """

    def __init__(self, owner: QWidget, *, report: PlacementReporter | None = None) -> None:
        super().__init__(owner)
        self.owner = owner
        self.report = report

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.Show or not isinstance(watched, QDialog):
            return False
        if isinstance(watched, QFileDialog) and not watched.testOption(QFileDialog.Option.DontUseNativeDialog):
            return False
        ancestor = watched.parentWidget()
        while ancestor is not None and ancestor is not self.owner:
            ancestor = ancestor.parentWidget()
        if ancestor is not self.owner:
            return False

        # Set WA_Moved before QDialog.showEvent attempts its default placement.
        center_dialog(watched, self.owner)
        # Let Qt and the compositor map the window, then correct if necessary.
        QTimer.singleShot(0, lambda dialog=watched: self._correct(dialog))
        QTimer.singleShot(150, lambda dialog=watched: self._verify(dialog))
        return False

    def _correct(self, dialog: QDialog) -> None:
        try:
            if dialog.isVisible():
                center_dialog(dialog, self.owner)
        except RuntimeError:
            pass

    def _verify(self, dialog: QDialog) -> None:
        if self.report is None:
            return
        try:
            if not dialog.isVisible():
                return
            backend = QGuiApplication.platformName()
            target = expected_dialog_position(dialog, self.owner)
            if target is None:
                return
            actual = dialog.frameGeometry().topLeft()
            owner_rect = self.owner.frameGeometry()
            # A few pixels of frame/decoration uncertainty are harmless.
            misplaced = _can_position_top_level_windows() and (
                abs(actual.x() - target.x()) > 12 or abs(actual.y() - target.y()) > 12
            )
            # Do not move an already-correct window after the user can interact.
            # If it is misplaced, make one final placement attempt after mapping.
            if misplaced:
                center_dialog(dialog, self.owner)
                actual = dialog.frameGeometry().topLeft()
                misplaced = abs(actual.x() - target.x()) > 12 or abs(actual.y() - target.y()) > 12
            self.report(
                f"Dialog placement: {dialog.windowTitle()!r}; Qt={backend}; "
                f"owner=({owner_rect.x()},{owner_rect.y()},"
                f"{owner_rect.width()}x{owner_rect.height()}); "
                f"target=({target.x()},{target.y()}); "
                f"actual=({actual.x()},{actual.y()}); "
                f"status={'mismatch' if misplaced else 'verified' if _can_position_top_level_windows() else 'compositor-managed'}",
                misplaced,
            )
        except RuntimeError:
            pass


def choose_directory(owner: QWidget, title: str) -> str:
    """Open a Qt-owned directory picker so it follows normal dialog placement."""
    picker = QFileDialog(owner)
    # Must be set before changing other properties to avoid the native picker.
    picker.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    picker.setFileMode(QFileDialog.FileMode.Directory)
    picker.setOption(QFileDialog.Option.ShowDirsOnly, True)
    picker.setWindowTitle(title)
    if exec_centered(picker, owner) != QDialog.DialogCode.Accepted:
        return ""
    paths = picker.selectedFiles()
    return paths[0] if paths else ""
