"""Artifact list widgets with file drag support."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QListWidget


class FileDragListWidget(QListWidget):
    """List widget that exposes selected artifact paths as file URLs."""

    def __init__(
        self,
        *,
        drag_path_resolver: Callable[[Path], Path] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._drag_path_resolver = drag_path_resolver
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def startDrag(self, supported_actions: Qt.DropAction) -> None:  # noqa: N802 - Qt API name
        paths: list[Path] = []
        for item in self.selectedItems():
            value = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(value, str) or not value:
                continue
            path = Path(value).expanduser()
            if self._drag_path_resolver is not None:
                path = self._drag_path_resolver(path)
            if path.is_file():
                paths.append(path.resolve())

        if not paths:
            return

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction)
