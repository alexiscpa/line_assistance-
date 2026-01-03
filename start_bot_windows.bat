@echo off
echo ====================================
echo 正在啟動 LINE Bot (Windows)...
echo ====================================
cd /d "%~dp0"

REM 檢查虛擬環境是否存在
if not exist ".venv_win\Scripts\activate.bat" (
    echo.
    echo 虛擬環境不存在，正在建立...
    python -m venv .venv_win
    echo 虛擬環境建立完成！
)

echo.
echo 正在啟動虛擬環境...
call .venv_win\Scripts\activate.bat

echo.
echo 正在安裝/更新套件...
pip install -r requirements.txt

echo.
echo ====================================
echo 正在啟動 LINE Bot 伺服器...
echo ====================================
python app.py

pause
