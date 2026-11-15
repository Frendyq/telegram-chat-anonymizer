@echo off
setlocal
chcp 65001 >nul

rem Drag and drop result.json (Telegram export) onto this file.

if "%~1"=="" (
  echo Drag and drop result.json from the Telegram export onto run.bat
  echo or run:  run.bat "path\to\result.json"
  pause
  exit /b 1
)

set "PY=python"
where python >nul 2>nul || set "PY=py"

set "DIR=%~dp1"
%PY% "%~dp0anonymize_tg.py" "%~1" --txt "%DIR%%~n1_anon.txt" --suggest "%DIR%%~n1_suggest.txt"
if errorlevel 1 (
  echo.
  echo ERROR. Make sure Python 3.8+ is installed: https://www.python.org/downloads/
  pause
  exit /b 1
)

echo.
echo ===== Leak check =====
%PY% "%~dp0check_anon.py" "%DIR%%~n1_anon.json"
echo.
echo Done. Next to your result.json:
echo   %~n1_anon.json     - anonymized chat
echo   %~n1_anon.txt      - the same as plain text
echo   %~n1_suggest.txt   - words that may be missed names
pause
