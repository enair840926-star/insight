@echo off
REM 예약 실행 전용 — 창을 띄우지 않고 조용히 돌린다.
REM 개장이 임박한 장만 골라 갱신하므로 예약 시각이 조금 어긋나도 안전하다.
chcp 65001 > nul
cd /d "%~dp0"

python run.py --auto >> "data\예약실행.log" 2>&1
