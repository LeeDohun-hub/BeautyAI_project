@echo off
REM ============================================================================
REM 올리브영 국내몰 카탈로그 갱신 배치 (Windows 작업 스케줄러용)
REM
REM 매일 새벽 3시에 자동 실행하도록 등록하려면(관리자 권한 CMD/PowerShell):
REM
REM   schtasks /Create /TN "OliveYoungKR" /SC DAILY /ST 03:00 ^
REM     /TR "C:\WorkSpace\Beauty_Project\BeautyAI_project\scripts\refresh_oliveyoung_kr.bat"
REM
REM 지금 바로 한번 실행: schtasks /Run /TN "OliveYoungKR"
REM 삭제:                schtasks /Delete /TN "OliveYoungKR" /F
REM ============================================================================
setlocal
set "ROOT=%~dp0.."
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
"%ROOT%\backend\.venv\Scripts\python.exe" "%ROOT%\scripts\crawl_oliveyoung_kr.py" %* >> "%ROOT%\data\manifests\oliveyoung_kr_crawl.log" 2>&1
endlocal
