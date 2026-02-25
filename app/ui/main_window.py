from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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
from core.models import OperationResult, VpnProfile
from core.resources import app_logo_icon
from core.vpn_backend import VpnBackend
from core.workers import Worker
from ui.profile_dialog import ProfileDialog


class MainWindow(QMainWindow):
    POLL_INTERVAL_MS = 3000

    def __init__(self, backend: VpnBackend) -> None:
        super().__init__()
        self.backend = backend
        self.logger = get_logger()
        self.thread_pool = QThreadPool()

        self.profiles: list[VpnProfile] = []
        self.filtered_profiles: list[VpnProfile] = []
        self.pending_status_key: Optional[tuple[str, bool]] = None
        self.pending_profile_key: Optional[tuple[str, bool]] = None
        self.pending_delete_row: Optional[int] = None
        self.selection_key_to_restore: Optional[tuple[str, bool]] = None
        self.selection_row_to_restore: Optional[int] = None
        self.busy = False
        self.refresh_in_flight = False
        self.active_refresh_silent = False
        self.sort_column = 0
        self.sort_order = Qt.AscendingOrder

        self.setWindowTitle("WinVPN-Manager")
        self.setWindowIcon(app_logo_icon())
        self.resize(1080, 700)

        self._build_ui()
        self._connect_signals()
        self._start_auto_refresh_timer()
        self.refresh_profiles()

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)

        top_bar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Global search...")
        self.include_all_users = QCheckBox("Include all users")
        self.refresh_button = QPushButton("Refresh")
        top_bar.addWidget(QLabel("Search:"))
        top_bar.addWidget(self.search_input, 1)
        top_bar.addWidget(self.include_all_users)
        top_bar.addWidget(self.refresh_button)

        filter_bar = QHBoxLayout()
        self.name_filter_input = QLineEdit()
        self.name_filter_input.setPlaceholderText("Name")
        self.server_filter_input = QLineEdit()
        self.server_filter_input.setPlaceholderText("Server Address")
        self.auth_filter_input = QLineEdit()
        self.auth_filter_input.setPlaceholderText("Authentication")
        self.scope_filter_combo = QComboBox()
        self.scope_filter_combo.addItems(["All", "User", "System"])
        self.status_filter_combo = QComboBox()
        self.status_filter_combo.addItems(
            ["All", "Connected", "Connecting", "Disconnected", "Unknown", "Error"]
        )
        filter_bar.addWidget(QLabel("Name:"))
        filter_bar.addWidget(self.name_filter_input, 2)
        filter_bar.addWidget(QLabel("Server:"))
        filter_bar.addWidget(self.server_filter_input, 2)
        filter_bar.addWidget(QLabel("Auth:"))
        filter_bar.addWidget(self.auth_filter_input, 2)
        filter_bar.addWidget(QLabel("Scope:"))
        filter_bar.addWidget(self.scope_filter_combo, 1)
        filter_bar.addWidget(QLabel("Status:"))
        filter_bar.addWidget(self.status_filter_combo, 1)

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
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(self.sort_column, self.sort_order)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(False)

        action_bar = QHBoxLayout()
        self.status_label = QLabel("Status: -")
        self.new_button = QPushButton("New...")
        self.edit_button = QPushButton("Edit...")
        self.edit_button.setEnabled(False)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setEnabled(False)
        self.credentials_button = QPushButton("Set Credentials (Windows)")
        self.credentials_button.setEnabled(False)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setEnabled(False)
        action_bar.addWidget(self.status_label)
        action_bar.addStretch(1)
        action_bar.addWidget(self.new_button)
        action_bar.addWidget(self.edit_button)
        action_bar.addWidget(self.delete_button)
        action_bar.addWidget(self.credentials_button)
        action_bar.addWidget(self.connect_button)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(140)

        layout.addLayout(top_bar)
        layout.addLayout(filter_bar)
        layout.addWidget(self.table, 1)
        layout.addLayout(action_bar)
        layout.addWidget(QLabel("Last action / error:"))
        layout.addWidget(self.log_output)
        self.setCentralWidget(central)

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_profiles)
        self.search_input.textChanged.connect(self.apply_filter)
        self.name_filter_input.textChanged.connect(self.apply_filter)
        self.server_filter_input.textChanged.connect(self.apply_filter)
        self.auth_filter_input.textChanged.connect(self.apply_filter)
        self.scope_filter_combo.currentTextChanged.connect(self.apply_filter)
        self.status_filter_combo.currentTextChanged.connect(self.apply_filter)
        self.include_all_users.stateChanged.connect(lambda _state: self.refresh_profiles())
        self.table.itemSelectionChanged.connect(self._update_action_state)
        self.table.itemDoubleClicked.connect(self._toggle_selected)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.connect_button.clicked.connect(self._toggle_selected)
        self.new_button.clicked.connect(self._new_profile)
        self.edit_button.clicked.connect(self._edit_profile)
        self.delete_button.clicked.connect(self._delete_profile)
        self.credentials_button.clicked.connect(self._set_credentials_selected)

    def _start_auto_refresh_timer(self) -> None:
        self.auto_refresh_timer = QTimer(self)
        self.auto_refresh_timer.setInterval(self.POLL_INTERVAL_MS)
        self.auto_refresh_timer.timeout.connect(self._auto_refresh_tick)
        self.auto_refresh_timer.start()

    def _auto_refresh_tick(self) -> None:
        if self.busy or self.refresh_in_flight:
            return
        self.refresh_profiles(silent=True)

    def _on_header_clicked(self, column: int) -> None:
        if self.sort_column == column:
            if self.sort_order == Qt.AscendingOrder:
                self.sort_order = Qt.DescendingOrder
            else:
                self.sort_order = Qt.AscendingOrder
        else:
            self.sort_column = column
            self.sort_order = Qt.AscendingOrder
        self.table.horizontalHeader().setSortIndicator(self.sort_column, self.sort_order)
        self.apply_filter()

    def refresh_profiles(
        self,
        select_key: Optional[tuple[str, bool]] = None,
        select_row: Optional[int] = None,
        silent: bool = False,
    ) -> None:
        if self.refresh_in_flight:
            return
        if select_key is None and select_row is None:
            select_key = self._current_selection_key()

        self.selection_key_to_restore = select_key
        self.selection_row_to_restore = select_row
        self.active_refresh_silent = silent
        self.refresh_in_flight = True
        self.refresh_button.setEnabled(False)
        self.include_all_users.setEnabled(False)
        if not silent:
            self._log_message("Refreshing VPN profiles...")
        worker = Worker(self.backend.list_profiles, self.include_all_users.isChecked())
        worker.signals.finished.connect(self._on_profiles_loaded)
        worker.signals.error.connect(self._on_worker_error)
        self.thread_pool.start(worker)

    def apply_filter(self) -> None:
        selected_key = self._current_selection_key()

        global_text = self.search_input.text().strip().lower()
        name_text = self.name_filter_input.text().strip().lower()
        server_text = self.server_filter_input.text().strip().lower()
        auth_text = self.auth_filter_input.text().strip().lower()
        scope_filter = self.scope_filter_combo.currentText().strip().lower()
        status_filter = self.status_filter_combo.currentText().strip().lower()

        filtered: list[VpnProfile] = []
        for profile in self.profiles:
            scope_label = self._scope_label(profile).lower()
            status_norm = self._normalize_status(profile.connection_status).lower()
            searchable = " ".join(
                [
                    profile.name.lower(),
                    profile.server_address.lower(),
                    profile.tunnel_type.lower(),
                    profile.authentication_method.lower(),
                    scope_label,
                    status_norm,
                ]
            )
            if global_text and global_text not in searchable:
                continue
            if name_text and name_text not in profile.name.lower():
                continue
            if server_text and server_text not in profile.server_address.lower():
                continue
            if auth_text and auth_text not in profile.authentication_method.lower():
                continue
            if scope_filter != "all" and scope_filter != scope_label:
                continue
            if status_filter != "all" and status_filter != status_norm:
                continue
            filtered.append(profile)

        self.filtered_profiles = self._sort_profiles(filtered)
        self._populate_table(self.filtered_profiles)

        if selected_key:
            self._select_profile_by_key(selected_key)
        self._update_action_state()

    def _scope_label(self, profile: VpnProfile) -> str:
        return "System" if profile.all_users else "User"

    def _normalize_status(self, status: str) -> str:
        value = (status or "").strip().lower()
        if value == "connected":
            return "Connected"
        if value == "connecting":
            return "Connecting"
        if value == "disconnected" or value == "notconnected":
            return "Disconnected"
        if value == "error":
            return "Error"
        return "Unknown"

    def _status_rank(self, profile: VpnProfile) -> int:
        return 0 if self._normalize_status(profile.connection_status).lower() == "connected" else 1

    def _sort_value_for_column(self, profile: VpnProfile) -> object:
        status = self._normalize_status(profile.connection_status).lower()
        if self.sort_column == 0:
            return profile.name.lower()
        if self.sort_column == 1:
            return self._scope_label(profile).lower()
        if self.sort_column == 2:
            return profile.server_address.lower()
        if self.sort_column == 3:
            return profile.tunnel_type.lower()
        if self.sort_column == 4:
            return profile.authentication_method.lower()
        if self.sort_column == 5:
            return status
        return profile.name.lower()

    def _sort_tiebreaker(self, profile: VpnProfile) -> tuple[object, ...]:
        return (
            profile.name.lower(),
            self._scope_label(profile).lower(),
            profile.server_address.lower(),
        )

    def _sort_profiles(self, profiles: list[VpnProfile]) -> list[VpnProfile]:
        reverse = self.sort_order == Qt.DescendingOrder
        connected: list[VpnProfile] = []
        others: list[VpnProfile] = []
        for profile in profiles:
            if self._status_rank(profile) == 0:
                connected.append(profile)
            else:
                others.append(profile)

        connected.sort(
            key=lambda p: (self._sort_value_for_column(p), self._sort_tiebreaker(p)),
            reverse=reverse,
        )
        others.sort(
            key=lambda p: (self._sort_value_for_column(p), self._sort_tiebreaker(p)),
            reverse=reverse,
        )
        return connected + others

    def _populate_table(self, profiles: list[VpnProfile]) -> None:
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            self._set_table_item(row, 0, profile.name)
            self._set_table_item(row, 1, self._scope_label(profile))
            self._set_table_item(row, 2, profile.server_address)
            self._set_table_item(row, 3, profile.tunnel_type)
            self._set_table_item(row, 4, profile.authentication_method)
            self._set_table_item(row, 5, self._normalize_status(profile.connection_status))
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)

    def _set_table_item(self, row: int, column: int, value: str) -> None:
        self.table.setItem(row, column, QTableWidgetItem(value))

    def _get_selected_profile(self) -> Optional[VpnProfile]:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.filtered_profiles):
            return None
        return self.filtered_profiles[row]

    def _profile_key(self, profile: VpnProfile) -> tuple[str, bool]:
        return profile.name, profile.all_users

    def _current_selection_key(self) -> Optional[tuple[str, bool]]:
        profile = self._get_selected_profile()
        return self._profile_key(profile) if profile else None

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
            self.credentials_button.setEnabled(False)
            self.status_label.setText("Status: -")
            return

        status = self._normalize_status(profile.connection_status)
        self.status_label.setText(f"Status: {status}")
        controls_enabled = not self.busy and not self.refresh_in_flight
        self.edit_button.setEnabled(controls_enabled)
        self.delete_button.setEnabled(controls_enabled)
        self.credentials_button.setEnabled(controls_enabled)
        if not controls_enabled:
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
        if self.busy or self.refresh_in_flight:
            return
        profile = self._get_selected_profile()
        if not profile:
            return
        status = self._normalize_status(profile.connection_status).lower()
        if status == "connecting":
            return
        if status == "connected":
            self._disconnect_profile(profile)
        else:
            self._connect_profile(profile)

    def _new_profile(self) -> None:
        dialog = ProfileDialog(self)
        if dialog.exec() != ProfileDialog.Accepted:
            return
        spec = dialog.profile_spec()
        self.pending_profile_key = (spec.name, dialog.all_users())
        self._set_busy(True)
        self._log_message(f"Creating profile {spec.name}...")
        worker = Worker(self.backend.create_profile, spec, dialog.all_users())
        worker.signals.finished.connect(self._on_create_finished)
        worker.signals.error.connect(self._on_worker_error)
        self.thread_pool.start(worker)

    def _edit_profile(self) -> None:
        profile = self._get_selected_profile()
        if not profile:
            return
        dialog = ProfileDialog(self, profile, allow_scope_change=False)
        if dialog.exec() != ProfileDialog.Accepted:
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
        scope_label = self._scope_label(profile)
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

    def _set_credentials_selected(self) -> None:
        profile = self._get_selected_profile()
        if not profile or self.busy or self.refresh_in_flight:
            return
        result = self.backend.open_native_credential_prompt(profile.name, profile.all_users)
        if result.success:
            self._log_message(result.message)
        else:
            self._log_message(f"Credential prompt failed: {result.message}")

    def _disconnect_profile(self, profile: VpnProfile) -> None:
        self.pending_status_key = self._profile_key(profile)
        self._set_busy(True)
        self._log_message(f"Disconnecting from {profile.name}...")
        worker = Worker(self.backend.disconnect, profile.name, profile.all_users)
        worker.signals.finished.connect(self._on_disconnect_finished)
        worker.signals.error.connect(self._on_worker_error)
        self.thread_pool.start(worker)

    def _on_profiles_loaded(self, profiles: list[VpnProfile]) -> None:
        self.refresh_in_flight = False
        self.refresh_button.setEnabled(not self.busy)
        self.include_all_users.setEnabled(not self.busy)
        self.profiles = profiles
        self.apply_filter()

        restored = False
        if self.selection_key_to_restore:
            restored = self._select_profile_by_key(self.selection_key_to_restore)
        if not restored and self.selection_row_to_restore is not None:
            self._select_row_clamped(self.selection_row_to_restore)
        self.selection_key_to_restore = None
        self.selection_row_to_restore = None

        if not self.active_refresh_silent:
            last_error = getattr(self.backend, "last_error", "")
            if last_error:
                self._log_message(last_error)
            self._log_message(f"Loaded {len(profiles)} VPN profiles.")
        self.active_refresh_silent = False

    def _on_connect_finished(self, result: OperationResult) -> None:
        self._set_busy(False)
        if self.pending_status_key:
            self._update_profile_status(self.pending_status_key, result.status or "Error")
        self.pending_status_key = None
        self._log_message(result.message if result.success else f"Connect failed: {result.message}")

    def _on_disconnect_finished(self, result: OperationResult) -> None:
        self._set_busy(False)
        if self.pending_status_key:
            self._update_profile_status(self.pending_status_key, result.status or "Disconnected")
        self.pending_status_key = None
        self._log_message(result.message if result.success else f"Disconnect failed: {result.message}")

    def _on_create_finished(self, result: OperationResult) -> None:
        self._set_busy(False)
        if result.success:
            self._log_message(result.message)
            if self.pending_profile_key:
                name, all_users = self.pending_profile_key
                prompt_result = self.backend.open_native_credential_prompt(name, all_users)
                if prompt_result.success:
                    self._log_message(prompt_result.message)
                else:
                    self._log_message(f"Credential prompt failed: {prompt_result.message}")
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
        self.refresh_in_flight = False
        self.refresh_button.setEnabled(not self.busy)
        self.include_all_users.setEnabled(not self.busy)
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
        controls_enabled = not busy and not self.refresh_in_flight
        self.refresh_button.setEnabled(controls_enabled)
        self.include_all_users.setEnabled(controls_enabled)
        self.search_input.setEnabled(not busy)
        self.name_filter_input.setEnabled(not busy)
        self.server_filter_input.setEnabled(not busy)
        self.auth_filter_input.setEnabled(not busy)
        self.scope_filter_combo.setEnabled(not busy)
        self.status_filter_combo.setEnabled(not busy)
        self.new_button.setEnabled(not busy)
        if busy:
            self.connect_button.setEnabled(False)
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.credentials_button.setEnabled(False)
        else:
            self._update_action_state()

    def _log_message(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(f"[{timestamp}] {message}")
        self.logger.info(message)
