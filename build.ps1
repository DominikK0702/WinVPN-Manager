$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )
    Write-Host $Message
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Message failed with exit code $LASTEXITCODE"
    }
}

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found at .venv. Create it first: python -m venv .venv"
}

Invoke-Checked "Upgrading pip..." { & $venvPython -m pip install --upgrade pip }
Invoke-Checked "Installing dependencies..." { & $venvPython -m pip install -r requirements.txt -r requirements-build.txt }

if (-not (Test-Path "app\logo.png")) {
    throw "Missing app\logo.png (required for runtime and EXE icon generation)."
}

Invoke-Checked "Generating app\\logo.ico from app\\logo.png..." {
    & $venvPython -c "from PIL import Image; from pathlib import Path; src=Path('app/logo.png'); dst=Path('app/logo.ico'); im=Image.open(src).convert('RGBA'); sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]; im.save(dst, format='ICO', sizes=sizes); print(dst.resolve())"
}

if (-not (Test-Path "app\logo.ico")) {
    throw "Failed to generate app\logo.ico."
}

if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist) { Remove-Item -Recurse -Force dist }

Invoke-Checked "Building portable executable..." { & $venvPython -m PyInstaller --noconfirm winvpn_manager.spec }

Write-Host ""
Write-Host "Portable build ready:"
Write-Host "  $root\dist\WinVPN-Manager\WinVPN-Manager.exe"
