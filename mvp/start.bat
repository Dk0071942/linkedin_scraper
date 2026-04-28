@echo off
REM One-click launcher: bootstraps a clean machine end-to-end.
REM Installs uv if missing, syncs Python deps + downloads a managed Python
REM if needed, installs Chromium for Playwright, copies the example config
REM on first run, and starts the web UI. Idempotent on subsequent runs.

setlocal
cd /d "%~dp0\.."

REM --- 1. Bootstrap uv if missing ---
where uv >nul 2>nul
if errorlevel 1 (
  echo [bootstrap] uv not found. Installing the official Astral release...
  echo [bootstrap] Press Ctrl+C now if you don't want this.
  echo.
  powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  REM uv installs to %USERPROFILE%\.local\bin and updates user PATH, but the
  REM running shell won't see that. Prepend manually for this session.
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)
where uv >nul 2>nul
if errorlevel 1 (
  echo.
  echo [error] uv install failed or uv is not on PATH.
  echo         Open a new terminal and re-run this script.
  pause
  exit /b 1
)

REM --- 2. Sync Python deps (uv auto-downloads a managed Python if needed) ---
echo.
echo [1/4] Syncing Python dependencies...
uv sync --extra web --extra mvp
if errorlevel 1 (
  echo.
  echo [error] uv sync failed. See output above.
  pause
  exit /b 1
)

REM --- 3. Ensure Chromium for Playwright ---
echo.
echo [2/4] Ensuring Chromium is installed for Playwright...
uv run --extra web --extra mvp playwright install chromium
if errorlevel 1 (
  echo [warn] playwright install reported an error. Continuing.
)

REM --- 4. First-run config bootstrap ---
if not exist "mvp\config.yaml" (
  echo.
  echo [3/4] No mvp\config.yaml yet. Copying from mvp\config.example.yaml...
  copy "mvp\config.example.yaml" "mvp\config.yaml" >nul
  echo       Edit searches and filters in the Config page once the UI opens.
) else (
  echo.
  echo [3/4] Using existing mvp\config.yaml.
)

REM --- 5. Launch ---
echo.
echo [4/4] Starting MVP UI on http://127.0.0.1:8765/
echo       Press Ctrl+C in this window to stop the server.
echo       First time? After the page opens, go to Run and click "Log in to LinkedIn".
echo.
start "" http://127.0.0.1:8765/
uv run --extra web --extra mvp python -m mvp.web

endlocal
