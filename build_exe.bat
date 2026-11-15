@echo off
rem Build TelegramAnonymizer.exe (Windows). Requires Python 3.9+.
rem Result: dist\TelegramAnonymizer.exe
setlocal
cd /d "%~dp0"
python -m venv .buildenv || goto :error
.buildenv\Scripts\python.exe -m pip install --upgrade pyinstaller || goto :error
.buildenv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --console ^
  --name TelegramAnonymizer --add-data "builtin_names.txt;." app.py || goto :error
echo.
echo Done: dist\TelegramAnonymizer.exe
exit /b 0
:error
echo Build failed.
exit /b 1
