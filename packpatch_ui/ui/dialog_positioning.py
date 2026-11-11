"""Place application-owned dialogs near their parent on first display."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QFileDialog, QWidget


def center_dialog(dialog: QDialog, owner: QWidget) -> None:
    """Center a visible dialog over its owner and keep it on the owner's screen."""
    if not dialog.isVisible() or not owner.isVisible():
        return
    screen = owner.windowHandle().screen() if owner.windowHandle() else None
    if screen is None:
        screen = QGuiApplication.screenAt(owner.frameGeometry().center())
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        return

    available = screen.availableGeometry()
    owner_rect = owner.frameGeometry()
    dialog_rect = dialog.frameGeometry()
    width = dialog_rect.width()
    height = dialog_rect.height()
    x = owner_rect.center().x() - width // 2
    y = owner_rect.center().y() - height // 2
    x = max(available.left(), min(x, available.right() - width + 1))
    y = max(available.top(), min(y, available.bottom() - height + 1))
    try:
        dialog.move(QPoint(x, y))
    except RuntimeError:
        # The dialog may have been closed and deleted before the queued callback.
        pass


class DialogPositioningFilter(QObject):
    """Center Qt dialogs owned by one main window, including static message boxes.

    A queued placement runs after Qt has computed dialog layout and frame size.
    Native file pickers are deliberately excluded.
    """

    def __init__(self, owner: QWidget) -> None:
        super().__init__(owner)
        self.owner = owner

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.Show or not isinstance(watched, QDialog):
            return False
        if isinstance(watched, QFileDialog):
            return False
        ancestor = watched.parentWidget()
        while ancestor is not None and ancestor is not self.owner:
            ancestor = ancestor.parentWidget()
        if ancestor is self.owner:
            QTimer.singleShot(0, lambda dialog=watched: center_dialog(dialog, self.owner))
        return False
