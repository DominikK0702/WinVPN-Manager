import ctypes
import json
import os
import subprocess
import time
from typing import Optional

from core.logger import get_logger
from core.models import OperationResult, VpnProfile, VpnProfileSpec
from core.vpn_backend import VpnBackend


class PowerShellRasBackend(VpnBackend):
    def __init__(self) -> None:
        self.logger = get_logger()
        self.last_error = ""

    def list_profiles(self, include_all_users: bool = False) -> list[VpnProfile]:
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
                profiles.extend(self._list_all_user_profiles())
            except RuntimeError as exc:
                self.last_error = f"All-user query failed: {exc}"
                self.logger.warning(self.last_error)
        return profiles

    def get_status(self, name: str, all_users: bool = False) -> str:
        all_users_flag = " -AllUserConnection" if all_users else ""
        try:
            data = self._run_powershell_json(
                f"Get-VpnConnection -Name {self._ps_quote(name)}{all_users_flag} "
                "| Select-Object ConnectionStatus"
            )
        except RuntimeError as exc:
            self.logger.error("Status query failed for %s: %s", name, exc)
            return "Error"

        if not data:
            return "Unknown"
        return str(data[0].get("ConnectionStatus") or "Unknown")

    def connect(self, name: str, all_users: bool = False, timeout: int = 20) -> OperationResult:
        return self._run_rasdial(self._rasdial_args(name, all_users), timeout=timeout)

    def disconnect(self, name: str, all_users: bool = False, timeout: int = 20) -> OperationResult:
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
        result = self._connect_with_credential_recovery(name, all_users)
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
                    True,
                    f"Connected to {name}.",
                    status=last_status,
                )
            if last_status.lower() == "error":
                break

        message = self._add_credential_hint(f"Timed out waiting for {name} to connect.", result.details)
        if self._is_credential_issue(message, result.details):
            message = f"{message} Please save credentials in the Windows prompt."
        return OperationResult(
            False,
            message,
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
            "-TunnelType 'Automatic' "
            "-RememberCredential"
        )
        if all_users:
            command += " -AllUserConnection"
        return self._run_powershell(command, success_message=f"Created VPN profile {spec.name}.")

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
            "-TunnelType 'Automatic' "
            "-RememberCredential "
            "-Force"
        )
        if all_users:
            command += " -AllUserConnection"
        return self._run_powershell(command, success_message=f"Updated VPN profile {name}.")

    def delete_profile(self, name: str, all_users: bool = False) -> OperationResult:
        admin_error = self._ensure_admin(all_users)
        if admin_error:
            return admin_error

        command = f"Remove-VpnConnection -Name {self._ps_quote(name)} -Force"
        if all_users:
            command += " -AllUserConnection"
        return self._run_powershell(command, success_message=f"Deleted VPN profile {name}.")

    def open_native_credential_prompt(
        self,
        name: str,
        all_users: bool = False,
        wait: bool = False,
        timeout: int = 120,
    ) -> OperationResult:
        args = ["rasphone.exe"]
        phonebook = self._rasphonebook_path(all_users)
        if phonebook:
            args.extend(["-f", phonebook])
        args.extend(["-d", name])

        try:
            if wait:
                subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=timeout,
                )
            else:
                subprocess.Popen(args)
        except subprocess.TimeoutExpired:
            return OperationResult(
                False,
                f"Windows credential prompt timed out after {timeout} seconds.",
                status="Error",
            )
        except Exception as exc:
            return OperationResult(
                False,
                f"Could not open Windows credential prompt: {exc}",
                status="Error",
            )
        return OperationResult(True, f"Opened Windows credential prompt for {name}.")

    def _connect_with_credential_recovery(self, name: str, all_users: bool = False) -> OperationResult:
        first = self.connect(name, all_users)
        if first.success:
            return first
        if not self._is_credential_issue(first.message, first.details):
            return first

        prompt = self.open_native_credential_prompt(name, all_users, wait=True, timeout=120)
        if not prompt.success:
            first.message = (
                f"{first.message} Could not complete credential recovery: {prompt.message}"
            ).strip()
            return first

        retry = self.connect(name, all_users)
        if retry.success:
            retry.message = f"{prompt.message} Retried connection successfully."
            return retry
        retry.message = (
            f"{retry.message} Credential prompt was shown and reconnect was retried once."
        ).strip()
        return retry

    def _list_user_profiles(self) -> list[VpnProfile]:
        data = self._run_powershell_json(
            "Get-VpnConnection "
            "| Select-Object Name,ServerAddress,TunnelType,AuthenticationMethod,ConnectionStatus"
        )
        return self._to_profiles(data, all_users=False)

    def _list_all_user_profiles(self) -> list[VpnProfile]:
        data = self._run_powershell_json(
            "Get-VpnConnection -AllUserConnection "
            "| Select-Object Name,ServerAddress,TunnelType,AuthenticationMethod,ConnectionStatus"
        )
        return self._to_profiles(data, all_users=True)

    def _to_profiles(self, data: list[dict], all_users: bool) -> list[VpnProfile]:
        profiles: list[VpnProfile] = []
        for entry in data:
            profiles.append(
                VpnProfile(
                    name=str(entry.get("Name", "")),
                    server_address=self._stringify(entry.get("ServerAddress")),
                    tunnel_type=self._stringify(entry.get("TunnelType")) or "Automatic",
                    authentication_method=self._stringify(entry.get("AuthenticationMethod")),
                    connection_status=self._stringify(entry.get("ConnectionStatus") or "Unknown"),
                    all_users=all_users,
                )
            )
        return profiles

    def _run_powershell_json(self, command: str, timeout: int = 15) -> list[dict]:
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
            errors="replace",
            timeout=timeout,
            **self._subprocess_hidden_window_kwargs(),
        )

        stdout = (process.stdout or "").strip()
        stderr = (process.stderr or "").strip()
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
        timeout: int = 25,
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
            errors="replace",
            timeout=timeout,
            **self._subprocess_hidden_window_kwargs(),
        )

        stdout = (process.stdout or "").strip()
        stderr = (process.stderr or "").strip()
        details = "\n".join(part for part in [stdout, stderr] if part)
        if process.returncode != 0:
            message = stderr or stdout or "PowerShell command failed."
            return OperationResult(False, message, status="Error", details=details)
        return OperationResult(True, success_message, details=details)

    def _run_rasdial(self, args: list[str], timeout: int = 20) -> OperationResult:
        try:
            process = subprocess.run(
                ["rasdial.exe", *args],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
                **self._subprocess_hidden_window_kwargs(),
            )
        except subprocess.TimeoutExpired:
            message = self._add_credential_hint(
                "rasdial timed out while waiting for credentials.",
                "",
            )
            return OperationResult(False, message, status="Error")

        stdout = (process.stdout or "").strip()
        stderr = (process.stderr or "").strip()
        details = "\n".join(part for part in [stdout, stderr] if part)
        if process.returncode != 0:
            message = self._add_credential_hint(stderr or stdout or "rasdial returned an error.", details)
            return OperationResult(False, message, status="Error", details=details)
        return OperationResult(True, stdout or "rasdial completed.", status="Connected", details=details)

    def _rasdial_args(self, name: str, all_users: bool, disconnect: bool = False) -> list[str]:
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
        if self._is_credential_issue(message, details):
            return f"{text} {hint}"
        return text

    def _is_credential_issue(self, message: str, details: str) -> bool:
        combined = f"{message}\n{details}".lower()
        return (
            "ras-fehler 691" in combined
            or "error 691" in combined
            or " 691" in combined
            or "benutzername" in combined
            or "kennwort" in combined
            or "authentifizierungsprotokoll" in combined
            or "verweigert" in combined
            or "credential" in combined
            or "password" in combined
            or "username" in combined
            or "timed out" in combined
        )

    def _is_admin(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def _subprocess_hidden_window_kwargs(self) -> dict:
        kwargs: dict = {}
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return kwargs

    def _ensure_admin(self, all_users: bool) -> Optional[OperationResult]:
        if not all_users or self._is_admin():
            return None
        return OperationResult(
            False,
            "Admin privileges are required to manage system-wide VPN profiles. "
            "Run the app as Administrator.",
            status="Error",
        )
