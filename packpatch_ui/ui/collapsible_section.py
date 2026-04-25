"""Reusable collapsible UI section."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    """A small titled section that can show or hide its content."""

    toggled = Signal(bool)

    def __init__(self, title: str, content: QWidget, *, collapsed: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._content = content

        self._toggle_button = QToolButton(self)
        self._toggle_button.setText(title)
        self._toggle_button.setCheckable(True)
        self._toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle_button.toggled.connect(self._set_expanded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._toggle_button)
        layout.addWidget(self._content)

        self.set_collapsed(collapsed)

    def is_collapsed(self) -> bool:
        """Return whether the section content is currently hidden."""
        return not self._toggle_button.isChecked()

    def set_collapsed(self, collapsed: bool) -> None:
        """Show or hide the content."""
        self._toggle_button.setChecked(not collapsed)

    def _set_expanded(self, expanded: bool) -> None:
        self._content.setVisible(expanded)
        self._toggle_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.toggled.emit(expanded)
