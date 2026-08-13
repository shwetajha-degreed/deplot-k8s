# Creates an empty Zerops project for Deplot wizard deploy testing.
# Deplot platform stays on ZEROPS_PROJECT_ID; wizard deploys use ZEROPS_DEPLOY_PROJECT_ID.

param(
    [switch]$SkipImport
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ImportFile = Join-Path $RepoRoot "zerops\import-deploy-sandbox.yaml"
$EnvFile = Join-Path $RepoRoot ".env"

Write-Host "Deplot deploy sandbox setup" -ForegroundColor Cyan
Write-Host "Import file: $ImportFile"

if (-not (Test-Path $ImportFile)) {
    Write-Error "Missing $ImportFile"
}

# Load token from .env if present
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*ZEROPS_API_TOKEN=(.+)$') {
            $env:ZEROPS_TOKEN = $matches[1].Trim().Trim('"')
        }
    }
}

if (-not $env:ZEROPS_TOKEN) {
    Write-Warning "ZEROPS_TOKEN not set. Run: zcli login"
}

$zcli = Get-Command zcli -ErrorAction SilentlyContinue
if (-not $zcli) {
    Write-Error "zcli not found. Install: https://docs.zerops.io/references/zcli"
}

if ($SkipImport) {
    Write-Host "SkipImport set - not running zcli import." -ForegroundColor Yellow
    exit 0
}

Write-Host "`nCreating sandbox project (empty shell)..." -ForegroundColor Green
Push-Location $RepoRoot
try {
    & zcli project project-import $ImportFile
    if ($LASTEXITCODE -ne 0) {
        Write-Error "zcli project import failed (exit $LASTEXITCODE)"
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Copy the new project ID from zcli output above"
Write-Host '2. Add to .env: ZEROPS_DEPLOY_PROJECT_ID=<sandbox-project-id>'
Write-Host "3. Keep ZEROPS_PROJECT_ID as your Deplot platform project"
Write-Host "4. Verify: curl http://localhost:8000/api/v1/health"
Write-Host "5. Run wizard with Demo Mode OFF"
Write-Host "Docs: docs/deploy-sandbox.md" -ForegroundColor Cyan
