@echo off
setlocal EnableExtensions

set "PROJECT_ROOT=%~dp0"
set "BACKEND_DIR=%PROJECT_ROOT%backend"
set "VENV_DIR=%BACKEND_DIR%\.venv"

if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo Creating Python virtual environment...
    uv venv "%VENV_DIR%"
    if errorlevel 1 exit /b %ERRORLEVEL%
)

cd /d "%BACKEND_DIR%"
set "VIRTUAL_ENV=%VENV_DIR%"
set "PYTHONHOME="
set "PATH=%VENV_DIR%\Scripts;%PATH%"
python -m uvicorn app.main:app --reload --port 8000
