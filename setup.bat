@echo off
setlocal enabledelayedexpansion
echo ========================================
echo   A2UI - First Time Setup
echo ========================================
echo.

REM --- Check prerequisites ---
echo Checking prerequisites...

where python >nul 2>&1
if !errorlevel! neq 0 (
    echo ERROR: Python is not installed or not in PATH.
    echo        Install Python 3.10+ from https://www.python.org
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    if %%a LSS 3 (
        echo ERROR: Python 3.10+ required, found %PYVER%
        pause
        exit /b 1
    )
    if %%a EQU 3 if %%b LSS 10 (
        echo ERROR: Python 3.10+ required, found %PYVER%
        pause
        exit /b 1
    )
)

where node >nul 2>&1
if !errorlevel! neq 0 (
    echo ERROR: Node.js is not installed or not in PATH.
    echo        Install Node.js 18+ from https://nodejs.org
    pause
    exit /b 1
)

echo   [OK] Python %PYVER% found
echo   [OK] Node.js found
echo.

REM --- Backend setup ---
echo [1/2] Setting up backend (Python)...
echo.

if not exist "server\.venv" (
    echo Creating virtual environment...
    python -m venv server\.venv
    if !errorlevel! neq 0 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo   [OK] Virtual environment created
) else (
    echo   [OK] Virtual environment already exists
)

echo Installing Python dependencies...
call server\.venv\Scripts\activate.bat && pip install -r server\requirements.txt --quiet
if !errorlevel! neq 0 (
    echo ERROR: Failed to install Python dependencies.
    pause
    exit /b 1
)
echo   [OK] Python dependencies installed
echo.

REM --- Frontend setup ---
echo [2/2] Setting up frontend (Node)...
echo.

echo Installing Node packages...
pushd client
call npm install
set INSTALL_ERR=!errorlevel!
popd
if !INSTALL_ERR! neq 0 (
    echo ERROR: Failed to install Node packages.
    pause
    exit /b 1
)
echo   [OK] Node packages installed

echo.
echo ========================================
echo   Setup complete!
echo ========================================
echo.
echo Next steps:
echo   1. Get an API key from https://openrouter.ai
echo   2. Run 'run.bat' to start the application
echo   3. Paste your API key in the Settings panel
echo.
pause
