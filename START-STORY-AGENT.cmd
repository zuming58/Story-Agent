@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Story Agent Launcher
cd /d "%~dp0"

set "STORY_URL=http://127.0.0.1:5173/overview"
set "API_URL=http://127.0.0.1:8765/api/v1/health"
set "API_PYTHON=%~dp0apps\api\.venv\Scripts\python.exe"
if exist "F:\Cache\uv\cache" set "UV_CACHE_DIR=F:\Cache\uv\cache"

powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%API_URL%' | Out-Null; Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%STORY_URL%' | Out-Null; exit 0 } catch { exit 1 }"
if not errorlevel 1 (
  echo Story Agent is already running. Opening the workspace...
  start "" "%STORY_URL%"
  exit /b 0
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js 24 LTS / npm was not found.
  echo Install Node.js 24 LTS, then double-click this file again.
  pause
  exit /b 1
)

if not exist "apps\web\node_modules\vite" (
  echo Installing web dependencies...
  call npm --prefix apps/web install
  if errorlevel 1 goto :install_failed
)

if not exist "%API_PYTHON%" (
  where uv >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] The API environment has not been initialized and uv was not found.
    echo Install uv once, then double-click this file again.
    pause
    exit /b 1
  )
  echo Installing API dependencies...
  call uv sync --project apps/api --dev
  if errorlevel 1 goto :install_failed
)

echo Starting Story Agent services...
start "Story Agent API" /min /D "%~dp0apps\api" cmd /k ""%API_PYTHON%" -m uvicorn story_agent_api.main:app --host 127.0.0.1 --port 8765"
start "Story Agent Web" /min /D "%~dp0apps\web" cmd /k "npm run dev -- --host 127.0.0.1 --port 5173 --strictPort"

echo Waiting for the workspace to become ready...
powershell -NoProfile -Command ^
  "$deadline=(Get-Date).AddSeconds(90);" ^
  "do {" ^
  "  try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%API_URL%' | Out-Null; Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%STORY_URL%' | Out-Null; Start-Process '%STORY_URL%'; exit 0 }" ^
  "  catch { Start-Sleep -Milliseconds 750 }" ^
  "} while ((Get-Date) -lt $deadline);" ^
  "exit 1"

if errorlevel 1 (
  echo [ERROR] Story Agent did not become ready within 90 seconds.
  echo Check the minimized "Story Agent API" and "Story Agent Web" windows for details.
  pause
  exit /b 1
)

echo Story Agent is ready.
exit /b 0

:install_failed
echo [ERROR] Dependency installation failed. Review the messages above.
pause
exit /b 1
