@echo off

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
set "VIRTUAL_ENV_PROMPT=.venv"
set "PYTHONHOME="
set "PATH=%VENV_DIR%\Scripts;%PATH%"
set "PROMPT=(.venv) %PROMPT%"

echo Activated BeautyAI backend virtual environment.
echo Current directory: %CD%
