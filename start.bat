@echo off
setlocal
cd /d "%~dp0"
where wt.exe >nul 2>nul
if errorlevel 1 (
    echo Windows Terminal is required. Install it, then run this file again.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    echo Create the virtual environment first:
    echo   python -m venv .venv
    echo   .venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)
if not exist ".env" (
    echo Copy .env.example to .env and set your portal password first.
    pause
    exit /b 1
)
rem One Windows Terminal window, two tabs; each service runs in the foreground.
wt.exe -w new new-tab --title "BotManager" -d "%~dp0." powershell.exe -NoLogo -NoProfile -NoExit -ExecutionPolicy Bypass -File "%~dp0scripts\run-service.ps1" -Service portal ; new-tab --title "Caddy" -d "%~dp0." powershell.exe -NoLogo -NoProfile -NoExit -ExecutionPolicy Bypass -File "%~dp0scripts\run-service.ps1" -Service caddy
if errorlevel 1 (
    echo Windows Terminal could not launch the tabs.
    pause
    exit /b 1
)
endlocal
