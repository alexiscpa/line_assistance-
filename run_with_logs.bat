@echo off
cd /d "%~dp0"
echo ========================================
echo Starting LINE Bot with detailed logging
echo ========================================
call .venv_win\Scripts\activate.bat
set FLASK_ENV=development
set FLASK_DEBUG=0
python app.py
pause
