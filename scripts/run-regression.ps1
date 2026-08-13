param(
    [switch]$ApiOnly,
    [switch]$E2eOnly,
    [switch]$StartServers,
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BackendHealth = "http://localhost:8000/api/v1/health"
$FrontendUrl = "http://localhost:3000"

function Test-UrlReady([string]$Url, [int]$TimeoutSec = 90) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { return $true }
        } catch { Start-Sleep -Seconds 2 }
    }
    return $false
}

$backendJob = $null
$frontendJob = $null

if ($Install) {
    Write-Host "Installing backend dev deps..." -ForegroundColor Cyan
    Push-Location "$Root\backend"
    pip install -e ".[dev]" -q
    Pop-Location

    Write-Host "Installing frontend + Playwright..." -ForegroundColor Cyan
    Push-Location "$Root\frontend"
    npm install
    npx playwright install chromium
    Pop-Location
}

if ($StartServers) {
    Write-Host "Starting backend..." -ForegroundColor Cyan
    $backendJob = Start-Job -ScriptBlock {
        Set-Location $using:Root
        Set-Location backend
        python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
    }
    if (-not (Test-UrlReady $BackendHealth)) {
        throw "Backend did not become ready at $BackendHealth"
    }

    Write-Host "Starting frontend..." -ForegroundColor Cyan
    $frontendJob = Start-Job -ScriptBlock {
        Set-Location $using:Root
        Set-Location frontend
        $env:NEXT_PUBLIC_API_URL = "http://localhost:8000/api/v1"
        npm run dev -- --port 3000
    }
    if (-not (Test-UrlReady $FrontendUrl)) {
        throw "Frontend did not become ready at $FrontendUrl"
    }
} else {
    if (-not $E2eOnly) {
        if (-not (Test-UrlReady $BackendHealth 5)) {
            Write-Warning "Backend not reachable. Start it or pass -StartServers"
        }
    }
    if (-not $ApiOnly) {
        if (-not (Test-UrlReady $FrontendUrl 5)) {
            Write-Warning "Frontend not reachable. Start it or pass -StartServers"
        }
    }
}

$exitCode = 0

if (-not $E2eOnly) {
    Write-Host "`n=== API regression (pytest) ===" -ForegroundColor Green
    Push-Location "$Root\backend"
    python -m pytest tests/ -v --tb=short
    if ($LASTEXITCODE -ne 0) { $exitCode = 1 }
    Pop-Location
}

if (-not $ApiOnly) {
    Write-Host "`n=== Web regression (Playwright) ===" -ForegroundColor Green
    Push-Location "$Root\frontend"
    $env:PLAYWRIGHT_SKIP_WEBSERVER = "1"
    npx playwright test
    if ($LASTEXITCODE -ne 0) { $exitCode = 1 }
    Remove-Item Env:PLAYWRIGHT_SKIP_WEBSERVER -ErrorAction SilentlyContinue
    Pop-Location
}

if ($backendJob) { Stop-Job $backendJob -ErrorAction SilentlyContinue; Remove-Job $backendJob -Force -ErrorAction SilentlyContinue }
if ($frontendJob) { Stop-Job $frontendJob -ErrorAction SilentlyContinue; Remove-Job $frontendJob -Force -ErrorAction SilentlyContinue }

if ($exitCode -eq 0) {
    Write-Host "`nRegression suite passed." -ForegroundColor Green
} else {
    Write-Host "`nRegression suite failed." -ForegroundColor Red
}
exit $exitCode
