# Publish showcase app to a new GitHub repo for live Deplot testing.
# Usage:
#   .\scripts\publish-showcase-repo.ps1 -RemoteUrl https://github.com/YOUR_USER/deplot-showcase.git

param(
    [Parameter(Mandatory = $true)]
    [string]$RemoteUrl
)

$ErrorActionPreference = "Stop"
$ShowcaseDir = Join-Path $PSScriptRoot "..\showcase\deplot-showcase"

if (-not (Test-Path $ShowcaseDir)) {
    Write-Error "Showcase folder not found: $ShowcaseDir"
}

Push-Location $ShowcaseDir
try {
    if (-not (Test-Path ".git")) {
        git init
        git branch -M main
    }

    git add .
    git status

    $pending = git diff --cached --quiet 2>$null
    if ($LASTEXITCODE -ne 0) {
        git commit -m "Deplot showcase app — Next.js + FastAPI fullstack"
    }

    $remotes = git remote
    if ($remotes -contains "origin") {
        git remote set-url origin $RemoteUrl
    } else {
        git remote add origin $RemoteUrl
    }

    Write-Host ""
    Write-Host "Pushing to $RemoteUrl ..."
    git push -u origin main

    Write-Host ""
    Write-Host "Done. Test in Deplot with Demo Mode OFF:"
    Write-Host "  $RemoteUrl -replace '\.git$',''"
} finally {
    Pop-Location
}
