@echo off
setlocal
cd /d "%~dp0"
docker compose logs -f
