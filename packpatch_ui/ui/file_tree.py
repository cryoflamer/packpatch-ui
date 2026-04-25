"""Checkable git file tree widget."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


class FileTreeWidget(QTreeWidget):
    """Tree widget that displays repository files with checkboxes and filtering."""

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderLabels(["Repository files"])
        self.setColumnCount(1)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self._all_paths: list[str] = []
        self._selected_paths: set[str] = set()
        self._filter_text = ""
        self._updating_tree = False
        self.itemChanged.connect(self._item_changed)

    def set_files(self, paths: Iterable[str]) -> None:
        """Replace tree contents with *paths* relative to the repository root."""
        self._all_paths = sorted({raw_path.strip() for raw_path in paths if raw_path.strip()})
        self._selected_paths.intersection_update(self._all_paths)
        self._rebuild_tree()

    def set_filter(self, text: str) -> None:
        """Filter visible files by substring or directory prefix."""
        self._filter_text = text.strip().lower()
        self._rebuild_tree()

    def selected_paths(self) -> list[str]:
        """Return checked file paths relative to the repository root."""
        return sorted(self._selected_paths)

    def set_selected_paths(self, paths: Iterable[str]) -> None:
        """Check only the file leaves listed in *paths*."""
        selected = self._normalize_paths(paths)
        if self._all_paths:
            selected.intersection_update(self._all_paths)
        self._selected_paths = selected
        self._rebuild_tree()

    def clear_selection(self) -> None:
        """Uncheck all tree items."""
        self._selected_paths.clear()
        self._rebuild_tree()

    def check_all(self) -> None:
        """Check all known repository files, including currently hidden files."""
        self._selected_paths = set(self._all_paths)
        self._rebuild_tree()

    def _normalize_paths(self, paths: Iterable[str]) -> set[str]:
        if isinstance(paths, str):
            return {paths} if paths else set()

        try:
            return {path for path in paths if isinstance(path, str) and path}
        except TypeError:
            return set()

    def _rebuild_tree(self) -> None:
        blocker = QSignalBlocker(self)
        self._updating_tree = True
        try:
            self.clear()
            nodes: dict[str, QTreeWidgetItem] = {}
            for path in self._filtered_paths():
                self._add_path(path, nodes)
            self.expandToDepth(0)
        finally:
            self._updating_tree = False
            del blocker

    def _filtered_paths(self) -> list[str]:
        if not self._filter_text:
            return self._all_paths
        return [path for path in self._all_paths if self._matches_filter(path)]

    def _matches_filter(self, path: str) -> bool:
        query = self._filter_text
        normalized_path = path.lower()
        if query.endswith("/"):
            return normalized_path.startswith(query)
        return query in normalized_path

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
                item.setCheckState(0, self._check_state_for_path(key, is_leaf=(key == path)))
                nodes[key] = item
            parent = item

    def _check_state_for_path(self, path: str, *, is_leaf: bool) -> Qt.CheckState:
        if is_leaf and path in self._selected_paths:
            return Qt.CheckState.Checked
        return Qt.CheckState.Unchecked

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating_tree or column != 0:
            return
        if item.childCount() != 0:
            return

        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(path, str) or not path:
            return

        if item.checkState(0) == Qt.CheckState.Checked:
            self._selected_paths.add(path)
        else:
            self._selected_paths.discard(path)
