@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    start "IP 포트 헬스체크 서버" cmd /k py -3 server.py
) else (
    start "IP 포트 헬스체크 서버" cmd /k python server.py
)
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8765
