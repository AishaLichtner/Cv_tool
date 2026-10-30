@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python wurde nicht gefunden / Python not found.
  echo Bitte installieren / Please install: https://www.python.org/downloads/
  echo Wichtig / Important: "Add python.exe to PATH" anhaken / tick it.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Erster Start: Einrichtung ... / First start: setting up ...
  python -m venv .venv
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
".venv\Scripts\python.exe" app.py
pause
