@echo off
REM ==============================================================================
REM CDISC Builder v2 - Standalone App Launcher (Windows)
REM ==============================================================================

echo ========================================================
echo   Starting CDISC Builder v2 (Yamaa Schema Standard)
echo ========================================================

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Error: Python 3.9+ is required but not found in PATH.
    pause
    exit /b 1
)

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    echo Installing CDISC Builder v2 dependencies...
    python -m pip install --upgrade pip
    pip install -e .
) else (
    call .venv\Scripts\activate.bat
)

echo Launching CDISC Builder Web UI...
python -m cdiscbuilderv2.cli app --host 127.0.0.1 --port 8000 --open-browser
pause
