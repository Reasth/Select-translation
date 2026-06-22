# Build and publish a GitHub Release under Reasth/Select-translation.
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\publish_github_release.ps1

[CmdletBinding()]
param(
    [string]$Version = "",
    [switch]$Draft,
    [switch]$Prerelease,
    [switch]$AllowDirty,
    [switch]$UseExistingTag
)

$ErrorActionPreference = "Stop"

$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$BuildScript = Join-Path $ProjectRoot "scripts\build_release_exe.ps1"
$Repo = "Reasth/Select-translation"
$ExpectedRemotePattern = 'github\.com[:/]Reasth/Select-translation(\.git)?$'
$ExpectedGitHubLogin = "Reasth"
$GitUserName = "Reasth"
$GitUserEmail = "reastemail@163.com"

function Invoke-GitText {
    param([Parameter(Mandatory=$true)][string[]]$GitArgs)
    $output = & git @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArgs -join ' ') failed"
    }
    return ($output -join "`n").Trim()
}

function Get-ProjectVersion {
    $configText = Get-Content -LiteralPath (Join-Path $ProjectRoot "config.py") -Raw -Encoding UTF8
    $issText = Get-Content -LiteralPath (Join-Path $ProjectRoot "TranslatePopup.iss") -Raw -Encoding UTF8
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

function Get-GitHubToken {
    if ($env:GITHUB_TOKEN) {
        return $env:GITHUB_TOKEN
    }

    $credentialInput = @("protocol=https", "host=github.com", "")
    $credential = $credentialInput | git credential fill
    if ($LASTEXITCODE -ne 0) {
        return ""
    }
    foreach ($line in $credential) {
        if ($line.StartsWith("password=")) {
            return $line.Substring("password=".Length)
        }
    }
    return ""
}

function New-ReleaseNotes {
    param(
        [Parameter(Mandatory=$true)][string]$Tag,
        [Parameter(Mandatory=$true)][string]$AssetName,
        [Parameter(Mandatory=$true)][string]$Sha256
    )

    $notes = @"
TranslatePopup $Tag

- Windows x64 single-file executable.
- Built with the stable release flow from scripts/build_release_exe.ps1.
- SHA256: $Sha256

Asset: $AssetName
"@
    $notesPath = Join-Path ([System.IO.Path]::GetTempPath()) "TranslatePopup-$Tag-release-notes.md"
    Set-Content -LiteralPath $notesPath -Value $notes -Encoding UTF8
    return $notesPath
}

Push-Location $ProjectRoot
try {
    & git config user.name $GitUserName
    & git config user.email $GitUserEmail

    $remote = Invoke-GitText @("remote", "get-url", "origin")
    if ($remote -notmatch $ExpectedRemotePattern) {
        throw "origin remote must point to Reasth/Select-translation, got: $remote"
    }

    if (-not $AllowDirty) {
        $dirty = Invoke-GitText @("status", "--porcelain")
        if ($dirty) {
            throw "Working tree is not clean. Commit or stash changes first, or rerun with -AllowDirty for a nonstandard release."
        }
    }

    $detectedVersion = Get-ProjectVersion
    if ($Version -and $Version -ne $detectedVersion) {
        throw "Requested version $Version does not match project version $detectedVersion"
    }
    $Version = $detectedVersion
    $tag = "v$Version"
    $assetName = "TranslatePopup-$tag-windows-x64.exe"
    $assetPath = Join-Path $ProjectRoot ("dist\" + $assetName)

    $headCommit = Invoke-GitText @("rev-parse", "HEAD")
    $localTag = Invoke-GitText @("tag", "-l", $tag)
    $remoteTag = Invoke-GitText @("ls-remote", "--tags", "origin", "refs/tags/$tag")
    if ($localTag -or $remoteTag) {
        if (-not $UseExistingTag) {
            throw "Tag already exists: $tag. Use -UseExistingTag only when recovering a failed release creation for the current HEAD."
        }
        if (-not $localTag) {
            throw "Remote tag exists but local tag is missing: $tag. Fetch tags before using -UseExistingTag."
        }
        $localTagCommit = Invoke-GitText @("rev-list", "-n", "1", $tag)
        if ($localTagCommit -ne $headCommit) {
            throw "Local tag $tag points to $localTagCommit, expected current HEAD $headCommit."
        }
        $remotePeeled = Invoke-GitText @("ls-remote", "--tags", "origin", "refs/tags/$tag^{}")
        $remoteTagCommit = ""
        if ($remotePeeled) {
            $remoteTagCommit = ($remotePeeled -split "\s+")[0]
        } elseif ($remoteTag) {
            $remoteTagCommit = ($remoteTag -split "\s+")[0]
        }
        if ($remoteTagCommit -ne $headCommit) {
            throw "Remote tag $tag points to $remoteTagCommit, expected current HEAD $headCommit."
        }
    }

    Write-Host "[1/5] Building release exe..." -ForegroundColor Cyan
    & $BuildScript -Version $Version
    if ($LASTEXITCODE -ne 0) { throw "Build script failed." }

    Copy-Item -LiteralPath (Join-Path $ProjectRoot "dist\TranslatePopup.exe") -Destination $assetPath -Force
    $sha256 = (Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash
    $notesPath = New-ReleaseNotes -Tag $tag -AssetName $assetName -Sha256 $sha256

    $branch = Invoke-GitText @("branch", "--show-current")
    if (-not $branch) { throw "Could not determine current branch." }

    Write-Host "[2/5] Pushing branch $branch..." -ForegroundColor Cyan
    & git push origin $branch
    if ($LASTEXITCODE -ne 0) { throw "git push origin $branch failed." }

    if ($UseExistingTag) {
        Write-Host "[3/5] Using existing tag $tag..." -ForegroundColor Cyan
    } else {
        Write-Host "[3/5] Creating and pushing tag $tag..." -ForegroundColor Cyan
        & git tag -a $tag -m "TranslatePopup $tag"
        if ($LASTEXITCODE -ne 0) { throw "git tag failed." }
        & git push origin $tag
        if ($LASTEXITCODE -ne 0) { throw "git push origin $tag failed." }
    }

    Write-Host "[4/5] Publishing GitHub Release..." -ForegroundColor Cyan
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($gh) {
        $ghLogin = (& gh api user --jq ".login" 2>$null)
        if ($LASTEXITCODE -ne 0 -or -not $ghLogin) {
            throw "Could not verify GitHub CLI authenticated user."
        }
        $ghLogin = ($ghLogin -join "`n").Trim()
        if ($ghLogin -ne $ExpectedGitHubLogin) {
            throw "GitHub CLI is authenticated as '$ghLogin', expected '$ExpectedGitHubLogin'."
        }
        $args = @(
            "release", "create", $tag, $assetPath,
            "--repo", $Repo,
            "--title", "TranslatePopup $tag",
            "--notes-file", $notesPath
        )
        if ($Draft) { $args += "--draft" }
        if ($Prerelease) { $args += "--prerelease" }
        & gh @args
        if ($LASTEXITCODE -ne 0) { throw "gh release create failed." }
    } else {
        $token = Get-GitHubToken
        if (-not $token) {
            throw "GitHub CLI not found and no token was available. Install gh, set GITHUB_TOKEN, or configure git credentials with a PAT."
        }
        $headers = @{
            Authorization = "Bearer $token"
            Accept = "application/vnd.github+json"
            "X-GitHub-Api-Version" = "2022-11-28"
        }
        $tokenUser = Invoke-RestMethod `
            -Method Get `
            -Uri "https://api.github.com/user" `
            -Headers $headers
        if ($tokenUser.login -ne $ExpectedGitHubLogin) {
            throw "GitHub token is authenticated as '$($tokenUser.login)', expected '$ExpectedGitHubLogin'."
        }
        $notesBody = [string](Get-Content -LiteralPath $notesPath -Raw -Encoding UTF8)
        $releaseBody = @{
            tag_name = $tag
            name = "TranslatePopup $tag"
            body = $notesBody
            draft = [bool]$Draft
            prerelease = [bool]$Prerelease
        } | ConvertTo-Json -Depth 4
        $release = Invoke-RestMethod `
            -Method Post `
            -Uri "https://api.github.com/repos/$Repo/releases" `
            -Headers $headers `
            -ContentType "application/json" `
            -Body $releaseBody

        $uploadUrl = $release.upload_url -replace '\{\?name,label\}', ("?name=" + [System.Uri]::EscapeDataString($assetName))
        Invoke-RestMethod `
            -Method Post `
            -Uri $uploadUrl `
            -Headers $headers `
            -ContentType "application/octet-stream" `
            -InFile $assetPath | Out-Null
    }

    Write-Host "[5/5] Release complete." -ForegroundColor Green
    Write-Host "Release: https://github.com/$Repo/releases/tag/$tag"
    Write-Host "Asset: $assetName"
    Write-Host "SHA256: $sha256"
} finally {
    Pop-Location
}
