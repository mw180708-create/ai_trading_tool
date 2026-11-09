@echo off
cd /d "%~dp0"
where python >nul 2>nul && (set PY=python) || (set PY=py)
echo Libraries installeren (eenmalig)...
%PY% -m pip install -r requirements.txt
echo.
echo De website opent zo in je browser. Sluit dit venster om te stoppen.
%PY% -m streamlit run app.py
pause
