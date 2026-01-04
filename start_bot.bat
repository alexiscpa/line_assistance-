@echo off
chcp 65001 >nul
cd /d "%~dp0"
call .venv_win\Scripts\activate.bat
pip install -r requirements.txt
python app.py
pause
