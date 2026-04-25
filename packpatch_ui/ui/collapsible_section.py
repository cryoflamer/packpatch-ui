"""Reusable collapsible UI section."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSizePolicy, QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    """A small titled section that can show or hide its content."""

    toggled = Signal(bool)

    def __init__(self, title: str, content: QWidget, *, collapsed: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self._content = content

        self._toggle_button = QToolButton(self)
        self._toggle_button.setCheckable(True)
        self._toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle_button.toggled.connect(self._set_expanded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._toggle_button)
        layout.addWidget(self._content)

        self.set_collapsed(collapsed)

    def setToolTip(self, text: str) -> None:  # noqa: N802
        """Set tooltip on both the wrapper and the visible toggle button."""
        super().setToolTip(text)
        self._toggle_button.setToolTip(text)

    def is_collapsed(self) -> bool:
        """Return whether the section content is currently hidden."""
        return not self._toggle_button.isChecked()

    def set_collapsed(self, collapsed: bool) -> None:
        """Show or hide the content."""
        expanded = not collapsed
        if self._toggle_button.isChecked() == expanded:
            self._set_expanded(expanded)
            return
        self._toggle_button.setChecked(expanded)

    def _set_expanded(self, expanded: bool) -> None:
        self._content.setVisible(expanded)
        self._toggle_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self._toggle_button.setText(f"{'▼' if expanded else '▶'} {self._title}")
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred if expanded else QSizePolicy.Policy.Maximum,
        )
        self.updateGeometry()
        self.toggled.emit(expanded)
