# Build the optional Windows installer.
# The stable one-file exe is always built first by scripts/build_release_exe.ps1.
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\build_win.ps1

[CmdletBinding()]
param(
    [switch]$SkipExeBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

Push-Location $ProjectRoot
try {
    if (-not $SkipExeBuild) {
        & (Join-Path $ProjectRoot "scripts\build_release_exe.ps1")
        if ($LASTEXITCODE -ne 0) { throw "Stable exe build failed." }
    }

    if (-not (Test-Path -LiteralPath "dist\TranslatePopup.exe")) {
        throw "Missing dist\TranslatePopup.exe. Run scripts\build_release_exe.ps1 first."
    }
    if (-not (Test-Path -LiteralPath "build\AppIcon.ico")) {
        throw "Missing build\AppIcon.ico. Run scripts\build_release_exe.ps1 first."
    }

    Write-Host "[installer] Locating Inno Setup..." -ForegroundColor Cyan
    $iscc = Get-Command iscc -ErrorAction SilentlyContinue
    if ($null -eq $iscc) {
        foreach ($candidate in @(
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
        )) {
            if (Test-Path -LiteralPath $candidate) {
                $iscc = $candidate
                break
            }
        }
    }
    if ($null -eq $iscc) {
        throw "Inno Setup ISCC.exe was not found. Install Inno Setup 6 to build installer\TranslatePopup-Setup.exe."
    }

    Write-Host "[installer] Building installer..." -ForegroundColor Cyan
    & $iscc "TranslatePopup.iss" | Select-Object -Last 3
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }

    $setup = "installer\TranslatePopup-Setup.exe"
    if (-not (Test-Path -LiteralPath $setup)) {
        throw "Installer output was not created: $setup"
    }
    $mb = [math]::Round((Get-Item -LiteralPath $setup).Length / 1MB, 1)
    Write-Host "Installer complete: $setup ($mb MB)" -ForegroundColor Green
} finally {
    Pop-Location
}
