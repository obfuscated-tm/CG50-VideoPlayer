@echo off
rem Double-click this file to open the CG50 Video Converter.
rem The first time, it sets itself up (needs an internet connection and takes a minute or two).
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY goto nopython

if not exist ".venv\Scripts\python.exe" (
    echo First run: setting things up. This takes a minute or two...
    %PY% -m venv .venv || goto failed
)
fc /b converter\requirements.txt .venv\installed-requirements.txt >nul 2>nul
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r converter\requirements.txt || goto failed
    copy /y converter\requirements.txt .venv\installed-requirements.txt >nul
)
start "" ".venv\Scripts\pythonw.exe" converter\convert.py
exit /b 0

:nopython
echo Python 3.9 or newer is needed. Install it from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH" during setup), then double-click this file again.
pause
exit /b 1

:failed
echo Setup didn't finish. Check your internet connection and try again.
pause
exit /b 1
