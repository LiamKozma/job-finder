@echo off
REM Double-click to find today's jobs. Opens the report in your browser.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -m jobfinder run %*
if errorlevel 1 (
  echo.
  echo Something went wrong. Is Python 3.11+ installed? Run:  winget install Python.Python.3.12
)
if "%JOBFINDER_NOPAUSE%"=="" pause
