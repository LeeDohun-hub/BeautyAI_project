@echo off
REM ============================================================================
REM 올리브영 글로벌몰 카탈로그 갱신 배치 (검색 API 기반, Windows 작업 스케줄러용)
REM
REM 사이트맵(옛 500개)이 아니라 내부 검색 API로 K뷰티 브랜드 전량(~3000개)을 수집해
REM data/manifests/oliveyoung_global_products.csv 를 갱신하고, 백엔드 컨테이너를 재시작해
REM 새 카탈로그를 즉시 반영한다. cf_clearance 불필요.
REM
REM 매주 일요일 새벽 4시에 자동 실행하도록 등록(관리자 권한 CMD/PowerShell):
REM
REM   schtasks /Create /TN "OliveYoungGlobal" /SC WEEKLY /D SUN /ST 04:00 ^
REM     /TR "C:\WorkSpace\Beauty_Project\BeautyAI_project\scripts\refresh_oliveyoung_global.bat"
REM
REM 지금 바로 한번 실행: schtasks /Run /TN "OliveYoungGlobal"
REM 삭제:                schtasks /Delete /TN "OliveYoungGlobal" /F
REM ============================================================================
setlocal
set "ROOT=%~dp0.."
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "LOG=%ROOT%\data\manifests\oliveyoung_global_crawl.log"

echo [%date% %time%] start global search crawl >> "%LOG%"
"%ROOT%\backend\.venv\Scripts\python.exe" "%ROOT%\scripts\crawl_oliveyoung_global_search.py" --out "%ROOT%\data\manifests\oliveyoung_global_products.csv" --merge %* >> "%LOG%" 2>&1

REM 새 카탈로그 반영: 백엔드 컨테이너 재시작(도커 미실행이면 무시).
docker compose -f "%ROOT%\docker-compose.yml" restart backend >> "%LOG%" 2>&1

echo [%date% %time%] done >> "%LOG%"
endlocal
