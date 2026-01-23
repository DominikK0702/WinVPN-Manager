import ctypes
import json
import os
import subprocess
import time
from typing import List, Optional

from core.logger import get_logger
from core.models import OperationResult, VpnProfile, VpnProfileSpec
from core.vpn_backend import VpnBackend


class PowerShellRasBackend(VpnBackend):
    def __init__(self) -> None:
        self.logger = get_logger()
        self.last_error = ""

    def list_profiles(self, include_all_users: bool = False) -> List[VpnProfile]:
        self.last_error = ""
        profiles = self._list_user_profiles()

        if include_all_users:
            if not self._is_admin():
                self.last_error = (
                    "Admin privileges are required to list system-wide VPN profiles. "
                    "Run the app as Administrator."
                )
                return profiles

            try:
                all_user_profiles = self._list_all_user_profiles()
            except RuntimeError as exc:
                self.logger.warning("All-user query failed: %s", exc)
                self.last_error = f"All-user query failed: {exc}"
            else:
                profiles.extend(all_user_profiles)

        return profiles

    def get_status(self, name: str, all_users: bool = False) -> str:
        try:
            all_users_flag = " -AllUserConnection" if all_users else ""
            data = self._run_powershell_json(
                f"Get-VpnConnection -Name {self._ps_quote(name)}{all_users_flag} "
                "| Select-Object ConnectionStatus"
            )
        except RuntimeError as exc:
            self.logger.error("Status query failed for %s: %s", name, exc)
            return "Error"

        if not data:
            return "Unknown"
        status = data[0].get("ConnectionStatus") or "Unknown"
        return str(status)

    def connect(self, name: str, all_users: bool = False, timeout: int = 20) -> OperationResult:
        # rasdial.exe is the built-in Windows CLI for VPN connect/disconnect.
        # We call "rasdial <ProfileName>" to connect using the saved credentials.
        return self._run_rasdial(self._rasdial_args(name, all_users), timeout=timeout)

    def disconnect(self, name: str, all_users: bool = False, timeout: int = 20) -> OperationResult:
        # rasdial.exe supports "/disconnect" to terminate a VPN connection.
        result = self._run_rasdial(
            self._rasdial_args(name, all_users, disconnect=True),
            timeout=timeout,
        )
        if result.success:
            result.status = self.get_status(name, all_users)
        return result

    def connect_and_wait(
        self,
        name: str,
        all_users: bool = False,
        poll_interval: float = 1.0,
        max_wait: int = 20,
    ) -> OperationResult:
        result = self.connect(name, all_users)
        if not result.success:
            result.status = "Error"
            return result

        waited = 0.0
        last_status = "Connecting"
        while waited < max_wait:
            time.sleep(poll_interval)
            waited += poll_interval
            last_status = self.get_status(name, all_users)
            if last_status.lower() == "connected":
                return OperationResult(
                    success=True,
                    message=f"Connected to {name}.",
                    status=last_status,
                )
            if last_status.lower() == "error":
                break

        message = f"Timed out waiting for {name} to connect."
        message = self._add_credential_hint(message, result.details)
        return OperationResult(
            success=False,
            message=message,
            status=last_status if last_status else "Error",
            details=result.details,
        )

    def create_profile(self, spec: VpnProfileSpec, all_users: bool = False) -> OperationResult:
        admin_error = self._ensure_admin(all_users)
        if admin_error:
            return admin_error

        command = (
            "Add-VpnConnection "
            f"-Name {self._ps_quote(spec.name)} "
            f"-ServerAddress {self._ps_quote(spec.server_address)} "
            f"-TunnelType {self._ps_quote(spec.tunnel_type)}"
        )
        if all_users:
            command += " -AllUserConnection"
        return self._run_powershell(
            command,
            success_message=f"Created VPN profile {spec.name}.",
        )

    def update_profile(
        self,
        name: str,
        spec: VpnProfileSpec,
        all_users: bool = False,
    ) -> OperationResult:
        admin_error = self._ensure_admin(all_users)
        if admin_error:
            return admin_error

        command = (
            "Set-VpnConnection "
            f"-Name {self._ps_quote(name)} "
            f"-ServerAddress {self._ps_quote(spec.server_address)} "
            f"-TunnelType {self._ps_quote(spec.tunnel_type)} "
            "-Force"
        )
        if all_users:
            command += " -AllUserConnection"
        return self._run_powershell(
            command,
            success_message=f"Updated VPN profile {name}.",
        )

    def delete_profile(self, name: str, all_users: bool = False) -> OperationResult:
        admin_error = self._ensure_admin(all_users)
        if admin_error:
            return admin_error

        command = f"Remove-VpnConnection -Name {self._ps_quote(name)} -Force"
        if all_users:
            command += " -AllUserConnection"
        return self._run_powershell(
            command,
            success_message=f"Deleted VPN profile {name}.",
        )

    def _list_user_profiles(self) -> List[VpnProfile]:
        # PowerShell: Get-VpnConnection returns VPN objects; ConvertTo-Json makes parsing reliable.
        data = self._run_powershell_json(
            "Get-VpnConnection "
            "| Select-Object Name,ServerAddress,TunnelType,AuthenticationMethod,ConnectionStatus"
        )
        return self._to_profiles(data, all_users=False)

    def _list_all_user_profiles(self) -> List[VpnProfile]:
        data = self._run_powershell_json(
            "Get-VpnConnection -AllUserConnection "
            "| Select-Object Name,ServerAddress,TunnelType,AuthenticationMethod,ConnectionStatus"
        )
        return self._to_profiles(data, all_users=True)

    def _to_profiles(self, data: List[dict], all_users: bool) -> List[VpnProfile]:
        profiles = []
        for entry in data:
            profiles.append(
                VpnProfile(
                    name=str(entry.get("Name", "")),
                    server_address=self._stringify(entry.get("ServerAddress")),
                    tunnel_type=self._stringify(entry.get("TunnelType")),
                    authentication_method=self._stringify(entry.get("AuthenticationMethod")),
                    connection_status=self._stringify(entry.get("ConnectionStatus") or "Unknown"),
                    all_users=all_users,
                )
            )
        return profiles

    def _run_powershell_json(self, command: str, timeout: int = 10) -> List[dict]:
        full_command = f"$ErrorActionPreference='Stop'; {command} | ConvertTo-Json -Depth 4"
        process = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                full_command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        stdout = process.stdout.strip()
        stderr = process.stderr.strip()
        if process.returncode != 0:
            raise RuntimeError(stderr or stdout or "PowerShell command failed.")

        if not stdout:
            return []

        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse PowerShell output: {exc}") from exc

        if parsed is None:
            return []
        if isinstance(parsed, dict):
            return [parsed]
        return list(parsed)

    def _run_powershell(
        self,
        command: str,
        timeout: int = 20,
        success_message: str = "PowerShell command completed.",
    ) -> OperationResult:
        full_command = f"$ErrorActionPreference='Stop'; {command}"
        process = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                full_command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        stdout = process.stdout.strip()
        stderr = process.stderr.strip()
        details = "\n".join(part for part in [stdout, stderr] if part)

        if process.returncode != 0:
            message = stderr or stdout or "PowerShell command failed."
            return OperationResult(False, message, status="Error", details=details)

        return OperationResult(True, success_message, details=details)

    def _run_rasdial(self, args: List[str], timeout: int = 20) -> OperationResult:
        try:
            process = subprocess.run(
                ["rasdial.exe", *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            message = self._add_credential_hint(
                "rasdial timed out while waiting for credentials.",
                "",
            )
            self.logger.error(message)
            return OperationResult(False, message, status="Error")

        stdout = process.stdout.strip()
        stderr = process.stderr.strip()
        details = "\n".join(part for part in [stdout, stderr] if part)

        if process.returncode != 0:
            message = stderr or stdout or "rasdial returned an error."
            message = self._add_credential_hint(message, details)
            self.logger.error("rasdial error: %s", message)
            return OperationResult(False, message, status="Error", details=details)

        return OperationResult(True, stdout or "rasdial completed.", status="Connected", details=details)

    def _rasdial_args(self, name: str, all_users: bool, disconnect: bool = False) -> List[str]:
        args = [name]
        phonebook = self._rasphonebook_path(all_users)
        if phonebook:
            args.append(f"/PHONEBOOK:{phonebook}")
        if disconnect:
            args.append("/disconnect")
        return args

    def _rasphonebook_path(self, all_users: bool) -> Optional[str]:
        if not all_users:
            return None
        base_dir = os.environ.get("PROGRAMDATA")
        if not base_dir:
            return None
        return os.path.join(
            base_dir,
            "Microsoft",
            "Network",
            "Connections",
            "Pbk",
            "rasphone.pbk",
        )

    def _ps_quote(self, value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def _stringify(self, value: Optional[object]) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return str(value)

    def _add_credential_hint(self, message: str, details: str) -> str:
        hint = "Please connect once via Windows VPN settings and save credentials."
        text = f"{message}".strip()
        combined = f"{message}\n{details}".lower()
        if (
            "credential" in combined
            or "password" in combined
            or "username" in combined
            or "timed out" in combined
        ):
            return f"{text} {hint}"
        return text

    def _is_admin(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def _ensure_admin(self, all_users: bool) -> Optional[OperationResult]:
        if not all_users:
            return None
        if self._is_admin():
            return None
        message = (
            "Admin privileges are required to manage system-wide VPN profiles. "
            "Run the app as Administrator."
        )
        return OperationResult(False, message, status="Error")
