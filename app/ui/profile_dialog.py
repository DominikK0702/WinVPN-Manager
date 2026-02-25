from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from core.models import VpnProfile, VpnProfileSpec
from core.resources import app_logo_icon


class ProfileDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        profile: Optional[VpnProfile] = None,
        allow_scope_change: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Profile" if profile else "New Profile")
        self.setWindowIcon(app_logo_icon())

        self.name_input = QLineEdit()
        self.server_input = QLineEdit()
        self.scope_checkbox = QCheckBox("System-wide (Admin)")

        if profile:
            self.name_input.setText(profile.name)
            self.name_input.setReadOnly(True)
            self.server_input.setText(profile.server_address)
            self.scope_checkbox.setChecked(profile.all_users)
            self.scope_checkbox.setEnabled(allow_scope_change)

        form_layout = QFormLayout()
        form_layout.addRow("Name:", self.name_input)
        form_layout.addRow("Server Address:", self.server_input)
        form_layout.addRow("", self.scope_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form_layout)
        layout.addWidget(buttons)

    def profile_spec(self) -> VpnProfileSpec:
        return VpnProfileSpec(
            name=self.name_input.text().strip(),
            server_address=self.server_input.text().strip(),
        )

    def all_users(self) -> bool:
        return self.scope_checkbox.isChecked()

    def accept(self) -> None:
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Validation", "Name is required.")
            return
        if not self.server_input.text().strip():
            QMessageBox.warning(self, "Validation", "Server address is required.")
            return
        super().accept()
