# WinVPN-Manager

Windows desktop app (PySide6) to manage native Windows VPN connections.

<img src="app/logo.png" alt="WinVPN-Manager Logo" width="220" />

## Features
- List Windows VPN profiles (user and optional system scope)
- Create, edit, and delete VPN profiles
- Connect and disconnect profiles
- Live status refresh (auto polling)
- Global and column-based filtering
- Connected profiles pinned to top
- Native Windows credential prompt integration

## Download
Use the latest prebuilt artifact from **GitHub Releases**.

- Download `WinVPN-Manager-Setup-<version>.exe`
- Run the installer
- Start the app from Start Menu or Desktop shortcut

## Quick Start (End Users)
1. Start `WinVPN-Manager`.
2. Click `New...` and create a VPN profile.
3. Use `Set Credentials (Windows)` (or the auto prompt) to save credentials in Windows.
4. Connect, disconnect, and manage profiles from the table.

## Requirements
- Windows 10 or Windows 11
- Built-in Windows VPN components (`VpnClient` cmdlets and `rasdial.exe`)

Notes:
- System-wide (`AllUser`) profile operations require Administrator privileges.
- Credentials are stored by Windows, not by this app.
- In packaged EXE builds, no local `logs\` folder/file is created next to the app.

## Build From Source
### Prerequisites
- Python 3.14 (current project environment target)
- PowerShell
- Inno Setup 6 (`ISCC.exe`) for installer builds

### Run from source
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app/main.py
```

### Build portable release
```powershell
.\build.ps1
```

Build output:
- `dist\WinVPN-Manager\WinVPN-Manager.exe`

Build notes:
- `build.ps1` installs build dependencies from `requirements-build.txt`
- `build.ps1` auto-generates `app\logo.ico` from `app\logo.png` for EXE icon embedding

### Build installer (recommended for shipping)
```powershell
.\build-installer.ps1
```

Installer output:
- `installer-output\WinVPN-Manager-Setup-<version>.exe`
- `installer-output\WinVPN-Manager-Setup-<version>.exe.sha256`

## Troubleshooting
### Black console windows appear
- Use a current build from this repo; subprocesses are configured to run hidden.

### Connect/reconnect fails with credential/auth errors (for example RAS 691)
- Open `Set Credentials (Windows)`, re-enter credentials, and save them in the native Windows dialog.

### All-user profile actions fail
- Run the app as Administrator for system-wide VPN operations.

### EXE blocked by SmartScreen/AV
- This can happen with unsigned binaries. Use trusted release sources and local policy exceptions if required.

### `failed to load python dll, _internal\python314.dll`
- This indicates an incomplete portable copy. Use the installer build for end users.
- If using portable output internally, copy the entire `dist\WinVPN-Manager` folder, not only `WinVPN-Manager.exe`.

## Project Layout
```text
app/
  main.py
  logo.png
  core/
  ui/
build.ps1
build-installer.ps1
installer/
  winvpn-manager.iss
winvpn_manager.spec
requirements.txt
requirements-build.txt
```

## Security & Privacy
- The app does not persist VPN credentials in project files.
- Credential entry/storage is delegated to Windows native components.
- Packaged EXE mode suppresses local file logging beside the executable.

## License
Licensed under the MIT License. See [LICENSE.md](LICENSE.md).
