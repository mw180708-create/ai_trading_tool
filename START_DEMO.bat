@echo off
cd /d "%~dp0"
echo ============================================
echo   AI Trading Tool - installeren en starten
echo ============================================
where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo Python is niet gevonden. Installeer Python opnieuw via python.org
    echo en vink "Add Python to PATH" aan.
    pause
    exit /b 1
  )
  set PY=py
) else (
  set PY=python
)
echo Libraries installeren (eenmalig, kan even duren)...
%PY% -m pip install -r requirements.txt
echo.
echo Backtest starten...
%PY% main.py --demo
echo.
echo Klaar! De resultaten staan in de map "results".
start "" "results"
pause
