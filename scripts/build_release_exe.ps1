# Stable Windows release-exe build for TranslatePopup.
# Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File scripts\build_release_exe.ps1

[CmdletBinding()]
param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$Python = Join-Path $ProjectRoot ".conda-env\python.exe"
$ExePath = Join-Path $ProjectRoot "dist\TranslatePopup.exe"

function Require-Path {
    param([Parameter(Mandatory=$true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required path not found: $Path"
    }
}

function Get-ProjectVersion {
    $configPath = Join-Path $ProjectRoot "config.py"
    $issPath = Join-Path $ProjectRoot "TranslatePopup.iss"
    $configText = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
    $issText = Get-Content -LiteralPath $issPath -Raw -Encoding UTF8

    if ($configText -notmatch 'CLIENT_VERSION\s*=\s*"([^"]+)"') {
        throw "Could not find CLIENT_VERSION in config.py"
    }
    $clientVersion = $Matches[1]

    if ($issText -notmatch '#define\s+MyAppVersion\s+"([^"]+)"') {
        throw "Could not find MyAppVersion in TranslatePopup.iss"
    }
    $installerVersion = $Matches[1]

    if ($clientVersion -ne $installerVersion) {
        throw "Version mismatch: config.py=$clientVersion, TranslatePopup.iss=$installerVersion"
    }
    return $clientVersion
}

function Remove-ProjectDirectory {
    param([Parameter(Mandatory=$true)][string]$Name)

    $target = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $Name))
    $rootPrefix = $ProjectRoot.TrimEnd("\", "/") + [System.IO.Path]::DirectorySeparatorChar
    if (-not $target.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside project root: $target"
    }
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

Require-Path $Python
Require-Path (Join-Path $ProjectRoot "assets\AppIcon-src.png")
Require-Path (Join-Path $ProjectRoot "scripts\make_ico.py")
Require-Path (Join-Path $ProjectRoot "TranslatePopup.spec")

$detectedVersion = Get-ProjectVersion
if ($Version -and $Version -ne $detectedVersion) {
    throw "Requested version $Version does not match project version $detectedVersion"
}
$Version = $detectedVersion

Push-Location $ProjectRoot
$oldPath = $env:Path
try {
    $env:Path = "$ProjectRoot\.conda-env;$ProjectRoot\.conda-env\Library\bin;$ProjectRoot\.conda-env\Scripts;$env:Path"

    Write-Host "[1/6] Running internal tests..." -ForegroundColor Cyan
    & $Python "test_internals.py"
    if ($LASTEXITCODE -ne 0) { throw "Internal tests failed." }

    Write-Host "[2/6] Cleaning build artifacts..." -ForegroundColor Cyan
    Remove-ProjectDirectory "build"
    Remove-ProjectDirectory "dist"

    Write-Host "[3/6] Generating Windows icon..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "build") | Out-Null
    & $Python -c "from PIL import Image; Image.open('assets/AppIcon-src.png').convert('RGBA').resize((1024, 1024), Image.LANCZOS).save('build/icon-1024.png')"
    if ($LASTEXITCODE -ne 0) { throw "Icon source conversion failed." }
    & $Python "scripts\make_ico.py"
    if ($LASTEXITCODE -ne 0) { throw "ICO generation failed." }

    Write-Host "[4/6] Building one-file exe with PyInstaller..." -ForegroundColor Cyan
    & $Python -m PyInstaller --noconfirm "TranslatePopup.spec"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
    Require-Path $ExePath

    Write-Host "[5/6] Running packaged exe smoke test..." -ForegroundColor Cyan
    $oldSmoke = $env:TRANSLATE_POPUP_SMOKE_TEST
    $oldQt = $env:QT_QPA_PLATFORM
    $oldSmokePath = $env:Path
    try {
        $env:TRANSLATE_POPUP_SMOKE_TEST = "1"
        $env:QT_QPA_PLATFORM = "offscreen"
        $env:Path = "$env:SystemRoot\System32;$env:SystemRoot"
        & $ExePath
        if ($LASTEXITCODE -ne 0) {
            throw "Packaged exe smoke test failed with exit code $LASTEXITCODE."
        }
    } finally {
        $env:TRANSLATE_POPUP_SMOKE_TEST = $oldSmoke
        $env:QT_QPA_PLATFORM = $oldQt
        $env:Path = $oldSmokePath
    }

    Write-Host "[6/6] Calculating SHA256..." -ForegroundColor Cyan
    $hash = (Get-FileHash -LiteralPath $ExePath -Algorithm SHA256).Hash
    $sizeMb = [math]::Round((Get-Item -LiteralPath $ExePath).Length / 1MB, 2)

    Write-Host ""
    Write-Host "Build complete." -ForegroundColor Green
    Write-Host "Version: $Version"
    Write-Host "Exe: $ExePath"
    Write-Host "Size: $sizeMb MB"
    Write-Host "SHA256: $hash"
} finally {
    $env:Path = $oldPath
    Pop-Location
}
