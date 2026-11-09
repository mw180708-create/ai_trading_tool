@echo off
cd /d "%~dp0"
where python >nul 2>nul && (set PY=python) || (set PY=py)
echo Backtest op je eigen data in de map "data"...
%PY% main.py --data-dir data
echo.
start "" "results"
pause
