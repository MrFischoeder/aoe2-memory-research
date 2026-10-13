@echo off
rem Run the research window from a source checkout. First start creates .venv and installs
rem dependencies (needs internet once). Requires 64-bit Python 3.11+ (https://www.python.org).
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul || (echo Python launcher "py" not found. Install 64-bit Python 3.11+ first. & pause & exit /b 1)
    py -3 -c "import struct,sys; sys.exit(0 if struct.calcsize('P')==8 and sys.version_info>=(3,11) else 1)" || (echo 64-bit Python 3.11+ is required. & pause & exit /b 1)
    echo Creating virtual environment...
    py -3 -m venv .venv || (pause & exit /b 1)
)
rem Also covers an existing .venv created without the UI extra.
".venv\Scripts\python.exe" -c "import PySide6, aoe2mr.desktop_ui.app" >nul 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -e ".[ui]" || (pause & exit /b 1)
)
start "" ".venv\Scripts\pythonw.exe" -m aoe2mr.desktop_ui %*
