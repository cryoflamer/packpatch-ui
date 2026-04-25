"""Checkable git file tree widget."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


class FileTreeWidget(QTreeWidget):
    """Tree widget that displays repository files with checkboxes."""

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderLabels(["Repository files"])
        self.setColumnCount(1)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)

    def set_files(self, paths: Iterable[str]) -> None:
        """Replace tree contents with *paths* relative to the repository root."""
        self.clear()
        nodes: dict[str, QTreeWidgetItem] = {}

        for raw_path in sorted(set(paths)):
            path = raw_path.strip()
            if path:
                self._add_path(path, nodes)

        self.expandToDepth(0)

    def selected_paths(self) -> list[str]:
        """Return checked file paths relative to the repository root."""
        selected: list[str] = []
        root = self.invisibleRootItem()
        for index in range(root.childCount()):
            self._collect_checked_files(root.child(index), selected)
        return selected

    def clear_selection(self) -> None:
        """Uncheck all tree items."""
        root = self.invisibleRootItem()
        for index in range(root.childCount()):
            self._set_check_state_recursive(root.child(index), Qt.CheckState.Unchecked)

    def check_all(self) -> None:
        """Check all tree items."""
        root = self.invisibleRootItem()
        for index in range(root.childCount()):
            self._set_check_state_recursive(root.child(index), Qt.CheckState.Checked)

    def _add_path(self, path: str, nodes: dict[str, QTreeWidgetItem]) -> None:
        parent = self.invisibleRootItem()
        current_parts: list[str] = []

        for part in PurePosixPath(path).parts:
            current_parts.append(part)
            key = "/".join(current_parts)
            item = nodes.get(key)
            if item is None:
                item = QTreeWidgetItem(parent, [part])
                item.setData(0, Qt.ItemDataRole.UserRole, key)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                nodes[key] = item
            parent = item

    def _collect_checked_files(self, item: QTreeWidgetItem, selected: list[str]) -> None:
        if item.childCount() == 0 and item.checkState(0) == Qt.CheckState.Checked:
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(path, str):
                selected.append(path)

        for index in range(item.childCount()):
            self._collect_checked_files(item.child(index), selected)

    def _set_check_state_recursive(self, item: QTreeWidgetItem, state: Qt.CheckState) -> None:
        item.setCheckState(0, state)
        for index in range(item.childCount()):
            self._set_check_state_recursive(item.child(index), state)
