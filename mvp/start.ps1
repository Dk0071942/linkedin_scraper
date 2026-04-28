# One-click launcher: bootstraps a clean machine end-to-end.
# Installs uv if missing, syncs Python deps + downloads a managed Python
# if needed, installs Chromium for Playwright, copies the example config
# on first run, and starts the web UI. Idempotent on subsequent runs.
#
# Run via:    powershell -ExecutionPolicy Bypass -File mvp\start.ps1
# or right-click the file in Explorer -> Run with PowerShell.

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

# --- 1. Bootstrap uv if missing ---
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "[bootstrap] uv not found. Installing the official Astral release..." -ForegroundColor Cyan
    Write-Host "[bootstrap] Press Ctrl+C now if you don't want this." -ForegroundColor DarkGray
    Write-Host ""
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    # uv installs to %USERPROFILE%\.local\bin and updates user PATH, but the
    # running shell won't see that. Prepend manually for this session.
    $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "[error] uv install failed or uv is not on PATH." -ForegroundColor Red
    Write-Host "        Open a new terminal and re-run this script." -ForegroundColor DarkGray
    Read-Host "Press Enter to exit"
    exit 1
}

# --- 2. Sync Python deps ---
Write-Host ""
Write-Host "[1/4] Syncing Python dependencies..." -ForegroundColor Cyan
uv sync --extra web --extra mvp
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[error] uv sync failed. See output above." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# --- 3. Ensure Chromium for Playwright ---
Write-Host ""
Write-Host "[2/4] Ensuring Chromium is installed for Playwright..." -ForegroundColor Cyan
uv run playwright install chromium
if ($LASTEXITCODE -ne 0) {
    Write-Host "[warn] playwright install reported an error. Continuing." -ForegroundColor Yellow
}

# --- 4. First-run config bootstrap ---
$cfg = Join-Path (Get-Location) 'mvp\config.yaml'
$example = Join-Path (Get-Location) 'mvp\config.example.yaml'
if (-not (Test-Path $cfg)) {
    Write-Host ""
    Write-Host "[3/4] No mvp\config.yaml yet. Copying from mvp\config.example.yaml..." -ForegroundColor Cyan
    Copy-Item $example $cfg
    Write-Host "      Edit searches and filters in the Config page once the UI opens." -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "[3/4] Using existing mvp\config.yaml." -ForegroundColor Cyan
}

# --- 5. Launch ---
Write-Host ""
Write-Host "[4/4] Starting MVP UI on http://127.0.0.1:8765/" -ForegroundColor Green
Write-Host "      Press Ctrl+C in this window to stop the server." -ForegroundColor DarkGray
Write-Host "      First time? After the page opens, go to Run and click 'Log in to LinkedIn'." -ForegroundColor DarkGray
Write-Host ""
Start-Process "http://127.0.0.1:8765/"
uv run python -m mvp.web
