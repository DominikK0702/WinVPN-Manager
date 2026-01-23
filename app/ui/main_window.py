from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.logger import get_logger
from core.models import OperationResult, VpnProfile, VpnProfileSpec
from core.vpn_backend import VpnBackend
from core.workers import Worker


class ProfileDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        profile: Optional[VpnProfile] = None,
        allow_scope_change: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Profile" if profile else "New Profile")

        self.name_input = QLineEdit()
        self.server_input = QLineEdit()
        self.tunnel_combo = QComboBox()
        self.scope_checkbox = QCheckBox("Systemweit (Admin)")

        tunnel_types = ["Automatic", "Ikev2", "Sstp", "L2tp", "Pptp"]
        self.tunnel_combo.addItems(tunnel_types)

        if profile:
            self.name_input.setText(profile.name)
            self.name_input.setReadOnly(True)
            self.server_input.setText(profile.server_address)
            current_tunnel = profile.tunnel_type or "Automatic"
            if current_tunnel and current_tunnel not in tunnel_types:
                self.tunnel_combo.addItem(current_tunnel)
            self.tunnel_combo.setCurrentText(current_tunnel)
            self.scope_checkbox.setChecked(profile.all_users)
            self.scope_checkbox.setEnabled(allow_scope_change)
        else:
            self.tunnel_combo.setCurrentText("Automatic")

        form_layout = QFormLayout()
        form_layout.addRow("Name:", self.name_input)
        form_layout.addRow("Server Address:", self.server_input)
        form_layout.addRow("Tunnel Type:", self.tunnel_combo)
        form_layout.addRow("", self.scope_checkbox)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form_layout)
        layout.addWidget(button_box)

    def profile_spec(self) -> VpnProfileSpec:
        return VpnProfileSpec(
            name=self.name_input.text().strip(),
            server_address=self.server_input.text().strip(),
            tunnel_type=self.tunnel_combo.currentText().strip() or "Automatic",
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


class MainWindow(QMainWindow):
    def __init__(self, backend: VpnBackend) -> None:
        super().__init__()
        self.backend = backend
        self.logger = get_logger()
        self.thread_pool = QThreadPool()
        self.profiles: List[VpnProfile] = []
        self.filtered_profiles: List[VpnProfile] = []
        self.pending_status_key: Optional[tuple[str, bool]] = None
        self.pending_profile_key: Optional[tuple[str, bool]] = None
        self.pending_delete_row: Optional[int] = None
        self.selection_key_to_restore: Optional[tuple[str, bool]] = None
        self.selection_row_to_restore: Optional[int] = None
        self.busy = False

        self.setWindowTitle("McWurzn")
        self.resize(980, 620)

        self._build_ui()
        self._connect_signals()
        self.refresh_profiles()

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)

        top_bar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by name or server address...")
        self.include_all_users = QCheckBox("Include all users")
        self.refresh_button = QPushButton("Refresh")
        top_bar.addWidget(QLabel("Search:"))
        top_bar.addWidget(self.search_input, 1)
        top_bar.addWidget(self.include_all_users)
        top_bar.addWidget(self.refresh_button)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                "Name",
                "Scope",
                "Server Address",
                "Tunnel Type",
                "Authentication",
                "Status",
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        action_bar = QHBoxLayout()
        self.status_label = QLabel("Status: -")
        self.new_button = QPushButton("New...")
        self.edit_button = QPushButton("Edit...")
        self.edit_button.setEnabled(False)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setEnabled(False)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setEnabled(False)
        action_bar.addWidget(self.status_label)
        action_bar.addStretch(1)
        action_bar.addWidget(self.new_button)
        action_bar.addWidget(self.edit_button)
        action_bar.addWidget(self.delete_button)
        action_bar.addWidget(self.connect_button)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(140)

        layout.addLayout(top_bar)
        layout.addWidget(self.table, 1)
        layout.addLayout(action_bar)
        layout.addWidget(QLabel("Last action / error:"))
        layout.addWidget(self.log_output)

        self.setCentralWidget(central)

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_profiles)
        self.search_input.textChanged.connect(self.apply_filter)
        self.include_all_users.stateChanged.connect(self.refresh_profiles)
        self.table.itemSelectionChanged.connect(self._update_action_state)
        self.table.itemDoubleClicked.connect(self._toggle_selected)
        self.connect_button.clicked.connect(self._toggle_selected)
        self.new_button.clicked.connect(self._new_profile)
        self.edit_button.clicked.connect(self._edit_profile)
        self.delete_button.clicked.connect(self._delete_profile)

    def refresh_profiles(
        self,
        select_key: Optional[tuple[str, bool]] = None,
        select_row: Optional[int] = None,
    ) -> None:
        if select_key is not None and not isinstance(select_key, tuple):
            select_key = None
        if select_row is not None and not isinstance(select_row, int):
            select_row = None
        if select_key is None and select_row is None:
            select_key = self._current_selection_key()
        self.selection_key_to_restore = select_key
        self.selection_row_to_restore = select_row
        self._set_busy(True)
        self._log_message("Refreshing VPN profiles...")
        worker = Worker(self.backend.list_profiles, self.include_all_users.isChecked())
        worker.signals.finished.connect(self._on_profiles_loaded)
        worker.signals.error.connect(self._on_worker_error)
        self.thread_pool.start(worker)

    def apply_filter(self) -> None:
        text = self.search_input.text().strip().lower()
        if not text:
            self.filtered_profiles = list(self.profiles)
        else:
            self.filtered_profiles = [
                profile
                for profile in self.profiles
                if text in profile.name.lower()
                or text in profile.server_address.lower()
            ]
        self._populate_table(self.filtered_profiles)
        self._update_action_state()

    def _populate_table(self, profiles: List[VpnProfile]) -> None:
        self.table.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            self._set_table_item(row, 0, profile.name)
            scope_label = "System" if profile.all_users else "User"
            self._set_table_item(row, 1, scope_label)
            self._set_table_item(row, 2, profile.server_address)
            self._set_table_item(row, 3, profile.tunnel_type)
            self._set_table_item(row, 4, profile.authentication_method)
            self._set_table_item(row, 5, profile.connection_status)

    def _set_table_item(self, row: int, column: int, value: str) -> None:
        item = QTableWidgetItem(value)
        item.setData(Qt.UserRole, value)
        self.table.setItem(row, column, item)

    def _get_selected_profile(self) -> Optional[VpnProfile]:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.filtered_profiles):
            return None
        return self.filtered_profiles[row]

    def _profile_key(self, profile: VpnProfile) -> tuple[str, bool]:
        return (profile.name, profile.all_users)

    def _current_selection_key(self) -> Optional[tuple[str, bool]]:
        profile = self._get_selected_profile()
        if not profile:
            return None
        return self._profile_key(profile)

    def _select_profile_by_key(self, key: tuple[str, bool]) -> bool:
        for row, profile in enumerate(self.filtered_profiles):
            if self._profile_key(profile) == key:
                self.table.setCurrentCell(row, 0)
                return True
        return False

    def _select_row_clamped(self, row: int) -> None:
        if not self.filtered_profiles:
            return
        row = max(0, min(row, len(self.filtered_profiles) - 1))
        self.table.setCurrentCell(row, 0)

    def _update_action_state(self) -> None:
        profile = self._get_selected_profile()
        if not profile:
            self.connect_button.setEnabled(False)
            self.connect_button.setText("Connect")
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.status_label.setText("Status: -")
            return

        status = profile.connection_status or "Unknown"
        self.status_label.setText(f"Status: {status}")
        self.edit_button.setEnabled(not self.busy)
        self.delete_button.setEnabled(not self.busy)

        if self.busy:
            self.connect_button.setEnabled(False)
            return

        if status.lower() == "connected":
            self.connect_button.setText("Disconnect")
            self.connect_button.setEnabled(True)
        elif status.lower() == "connecting":
            self.connect_button.setEnabled(False)
        else:
            self.connect_button.setText("Connect")
            self.connect_button.setEnabled(True)

    def _toggle_selected(self) -> None:
        if self.busy:
            return
        profile = self._get_selected_profile()
        if not profile:
            return
        status = profile.connection_status.lower()
        if status == "connecting":
            return
        if status == "connected":
            self._disconnect_profile(profile)
        else:
            self._connect_profile(profile)

    def _new_profile(self) -> None:
        dialog = ProfileDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        spec = dialog.profile_spec()
        all_users = dialog.all_users()
        self.pending_profile_key = (spec.name, all_users)
        self._set_busy(True)
        self._log_message(f"Creating profile {spec.name}...")
        worker = Worker(self.backend.create_profile, spec, all_users)
        worker.signals.finished.connect(self._on_create_finished)
        worker.signals.error.connect(self._on_worker_error)
        self.thread_pool.start(worker)

    def _edit_profile(self) -> None:
        profile = self._get_selected_profile()
        if not profile:
            return
        dialog = ProfileDialog(self, profile, allow_scope_change=False)
        if dialog.exec() != QDialog.Accepted:
            return
        spec = dialog.profile_spec()
        self.pending_profile_key = self._profile_key(profile)
        self._set_busy(True)
        self._log_message(f"Updating profile {profile.name}...")
        worker = Worker(self.backend.update_profile, profile.name, spec, profile.all_users)
        worker.signals.finished.connect(self._on_update_finished)
        worker.signals.error.connect(self._on_worker_error)
        self.thread_pool.start(worker)

    def _delete_profile(self) -> None:
        profile = self._get_selected_profile()
        if not profile:
            return
        scope_label = "System" if profile.all_users else "User"
        confirm = QMessageBox.question(
            self,
            "Delete Profile",
            f"Delete VPN profile '{profile.name}' ({scope_label})?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.pending_profile_key = self._profile_key(profile)
        self.pending_delete_row = self.table.currentRow()
        self._set_busy(True)
        self._log_message(f"Deleting profile {profile.name}...")
        worker = Worker(self.backend.delete_profile, profile.name, profile.all_users)
        worker.signals.finished.connect(self._on_delete_finished)
        worker.signals.error.connect(self._on_worker_error)
        self.thread_pool.start(worker)

    def _connect_profile(self, profile: VpnProfile) -> None:
        self.pending_status_key = self._profile_key(profile)
        self._update_profile_status(self.pending_status_key, "Connecting")
        self._set_busy(True)
        self._log_message(f"Connecting to {profile.name}...")
        worker = Worker(self.backend.connect_and_wait, profile.name, profile.all_users)
        worker.signals.finished.connect(self._on_connect_finished)
        worker.signals.error.connect(self._on_worker_error)
        self.thread_pool.start(worker)

    def _disconnect_profile(self, profile: VpnProfile) -> None:
        self.pending_status_key = self._profile_key(profile)
        self._set_busy(True)
        self._log_message(f"Disconnecting from {profile.name}...")
        worker = Worker(self.backend.disconnect, profile.name, profile.all_users)
        worker.signals.finished.connect(self._on_disconnect_finished)
        worker.signals.error.connect(self._on_worker_error)
        self.thread_pool.start(worker)

    def _on_profiles_loaded(self, profiles: List[VpnProfile]) -> None:
        self._set_busy(False)
        self.profiles = profiles
        self.apply_filter()
        restored = False
        if self.selection_key_to_restore:
            restored = self._select_profile_by_key(self.selection_key_to_restore)
        if not restored and self.selection_row_to_restore is not None:
            self._select_row_clamped(self.selection_row_to_restore)
        self.selection_key_to_restore = None
        self.selection_row_to_restore = None
        last_error = getattr(self.backend, "last_error", "")
        if last_error:
            self._log_message(last_error)
        self._log_message(f"Loaded {len(profiles)} VPN profiles.")

    def _on_connect_finished(self, result: OperationResult) -> None:
        self._set_busy(False)
        key = self.pending_status_key
        if key:
            self._update_profile_status(key, result.status or "Error")
        if result.success:
            self._log_message(result.message)
        else:
            self._log_message(f"Connect failed: {result.message}")
        self.pending_status_key = None

    def _on_disconnect_finished(self, result: OperationResult) -> None:
        self._set_busy(False)
        key = self.pending_status_key
        if key:
            self._update_profile_status(key, result.status or "Disconnected")
        if result.success:
            self._log_message(result.message)
        else:
            self._log_message(f"Disconnect failed: {result.message}")
        self.pending_status_key = None

    def _on_create_finished(self, result: OperationResult) -> None:
        self._set_busy(False)
        if result.success:
            self._log_message(result.message)
            self.refresh_profiles(select_key=self.pending_profile_key)
        else:
            self._log_message(f"Create failed: {result.message}")
        self.pending_profile_key = None

    def _on_update_finished(self, result: OperationResult) -> None:
        self._set_busy(False)
        if result.success:
            self._log_message(result.message)
            self.refresh_profiles(select_key=self.pending_profile_key)
        else:
            self._log_message(f"Update failed: {result.message}")
        self.pending_profile_key = None

    def _on_delete_finished(self, result: OperationResult) -> None:
        self._set_busy(False)
        if result.success:
            self._log_message(result.message)
            self.refresh_profiles(select_row=self.pending_delete_row)
        else:
            self._log_message(f"Delete failed: {result.message}")
        self.pending_profile_key = None
        self.pending_delete_row = None

    def _on_worker_error(self, error_text: str) -> None:
        self._set_busy(False)
        self.logger.error(error_text)
        self.pending_profile_key = None
        self.pending_status_key = None
        self.pending_delete_row = None
        self._log_message("Unexpected error. See log file for details.")

    def _update_profile_status(self, key: tuple[str, bool], status: str) -> None:
        for profile in self.profiles:
            if self._profile_key(profile) == key:
                profile.connection_status = status
        for profile in self.filtered_profiles:
            if self._profile_key(profile) == key:
                profile.connection_status = status
        self.apply_filter()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.refresh_button.setEnabled(not busy)
        self.include_all_users.setEnabled(not busy)
        self.search_input.setEnabled(not busy)
        self.new_button.setEnabled(not busy)
        if busy:
            self.connect_button.setEnabled(False)
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)
        else:
            self._update_action_state()

    def _log_message(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(f"[{timestamp}] {message}")
        self.logger.info(message)
