@echo off
chcp 65001 > nul
title 자산 인사이트 갱신
cd /d "%~dp0"

REM 인자를 그대로 넘긴다 — 갱신.bat kr / 갱신.bat 저녁 / 갱신.bat --auto
python run.py %*

echo.
echo ================================================================
echo   폰 앱  https://enair840926-star.github.io/insight/
echo   1~2분 뒤 반영됩니다. 앱을 껐다 켜면 최신이 뜹니다.
echo ================================================================
echo.
pause
