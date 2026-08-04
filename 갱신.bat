@echo off
chcp 65001 > nul
title 자산 인사이트 갱신
cd /d "%~dp0"

python run.py

echo.
echo ================================================================
echo   폰 앱  https://enair840926-star.github.io/insight/
echo   1~2분 뒤 반영됩니다. 앱을 껐다 켜면 최신이 뜹니다.
echo ================================================================
echo.
pause
