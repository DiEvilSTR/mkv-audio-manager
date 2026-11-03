@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>nul
if not errorlevel 1 (
    uv run --offline --no-project --no-python-downloads python app.py
    if not errorlevel 1 exit /b 0
)
python app.py
if errorlevel 1 (
    echo.
    echo Could not start MKV Audio Manager. Python 3.10+ with Tkinter is required.
    pause
)
