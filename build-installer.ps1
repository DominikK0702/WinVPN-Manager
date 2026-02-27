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

Invoke-Checked "Building application bundle..." { & "$root\build.ps1" }

$buildInputDir = Join-Path $root "dist\WinVPN-Manager"
$requiredFiles = @(
    "WinVPN-Manager.exe",
    "_internal\python314.dll",
    "_internal\PySide6\plugins\platforms\qwindows.dll"
)
foreach ($required in $requiredFiles) {
    $path = Join-Path $buildInputDir $required
    if (-not (Test-Path $path)) {
        throw "Missing required runtime file: $path"
    }
}

function Resolve-IsccPath {
    $checked = New-Object System.Collections.Generic.List[string]

    if (-not [string]::IsNullOrWhiteSpace($env:WINVPN_ISCC_PATH)) {
        $checked.Add($env:WINVPN_ISCC_PATH)
        if (Test-Path $env:WINVPN_ISCC_PATH) {
            return $env:WINVPN_ISCC_PATH
        }
    }

    $isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($isccCommand -and $isccCommand.Source -and (Test-Path $isccCommand.Source)) {
        return $isccCommand.Source
    }

    $commonPaths = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $commonPaths) {
        if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            $checked.Add($candidate)
            if (Test-Path $candidate) {
                return $candidate
            }
        }
    }

    $registryPaths = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe"
    )
    foreach ($regPath in $registryPaths) {
        $defaultValue = (Get-ItemProperty -Path $regPath -ErrorAction SilentlyContinue)."(default)"
        if (-not [string]::IsNullOrWhiteSpace($defaultValue)) {
            $checked.Add($defaultValue)
            if (Test-Path $defaultValue) {
                return $defaultValue
            }
        }
    }

    $uninstallKeys = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($key in $uninstallKeys) {
        $innoInstalls = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like "Inno Setup*" }
        foreach ($install in $innoInstalls) {
            if (-not [string]::IsNullOrWhiteSpace($install.InstallLocation)) {
                $candidate = Join-Path $install.InstallLocation "ISCC.exe"
                $checked.Add($candidate)
                if (Test-Path $candidate) {
                    return $candidate
                }
            }
        }
    }

    $uniqueChecked = $checked | Select-Object -Unique
    $errorText = @(
        "Inno Setup compiler (ISCC.exe) not found.",
        "Install Inno Setup 6 and rerun build-installer.ps1.",
        "Checked locations:"
    ) + ($uniqueChecked | ForEach-Object { "  - $_" })
    throw ($errorText -join [Environment]::NewLine)
}

$iscc = Resolve-IsccPath

$appVersion = $env:WINVPN_APP_VERSION
if ([string]::IsNullOrWhiteSpace($appVersion)) {
    $appVersion = "0.1.0"
}

$issPath = Join-Path $root "installer\winvpn-manager.iss"
Invoke-Checked "Building installer..." {
    & $iscc "/DAppVersion=$appVersion" "/DBuildInputDir=$buildInputDir" "$issPath"
}

$installerOutputDir = Join-Path $root "installer-output"
$setupExe = Get-ChildItem -Path $installerOutputDir -Filter "WinVPN-Manager-Setup-$appVersion*.exe" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $setupExe) {
    throw "Installer output not found in $installerOutputDir."
}

$hash = Get-FileHash -Path $setupExe.FullName -Algorithm SHA256
$hashLine = "$($hash.Hash) *$($setupExe.Name)"
$hashPath = "$($setupExe.FullName).sha256"
Set-Content -Path $hashPath -Value $hashLine -Encoding ascii

Write-Host ""
Write-Host "Installer build ready:"
Write-Host "  $($setupExe.FullName)"
Write-Host "SHA256:"
Write-Host "  $hashPath"
