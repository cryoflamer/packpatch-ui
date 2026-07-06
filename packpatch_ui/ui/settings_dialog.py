"""Settings dialog for repository workflow behavior."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class SettingsDialog(QDialog):
    """Expose per-session behavior settings without crowding the main window."""

    def __init__(
        self,
        *,
        auto_export_pack_check: QCheckBox,
        include_sensitive_files_check: QCheckBox,
        include_unversioned_files_check: QCheckBox,
        git_history_depth_spin: QSpinBox,
        auto_create_pack_after_apply_check: QCheckBox,
        apply_mode_combo: QComboBox,
        allow_unversioned_apply_check: QCheckBox,
        stash_changes_after_undo_check: QCheckBox,
        watch_repository_state_check: QCheckBox,
        auto_deploy_after_commit_check: QCheckBox,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumWidth(460)

        pack_group = QGroupBox("Pack", self)
        pack_layout = QFormLayout(pack_group)
        pack_layout.addRow(auto_export_pack_check)
        pack_layout.addRow(include_sensitive_files_check)
        pack_layout.addRow(include_unversioned_files_check)
        pack_layout.addRow("Git history depth:", git_history_depth_spin)
        pack_layout.addRow(auto_create_pack_after_apply_check)

        apply_group = QGroupBox("Apply", self)
        apply_layout = QFormLayout(apply_group)
        apply_layout.addRow("Apply mode:", apply_mode_combo)
        apply_layout.addRow(allow_unversioned_apply_check)
        apply_layout.addRow(stash_changes_after_undo_check)

        repository_group = QGroupBox("Repository", self)
        repository_layout = QVBoxLayout(repository_group)
        repository_layout.addWidget(watch_repository_state_check)

        deploy_group = QGroupBox("Deploy", self)
        deploy_layout = QVBoxLayout(deploy_group)
        deploy_layout.addWidget(auto_deploy_after_commit_check)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.close)

        layout = QVBoxLayout(self)
        layout.addWidget(pack_group)
        layout.addWidget(apply_group)
        layout.addWidget(repository_group)
        layout.addWidget(deploy_group)
        layout.addWidget(buttons)

    def show_settings(self) -> None:
        """Open the dialog with the current live session settings."""
        self.exec()
