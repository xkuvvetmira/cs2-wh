@echo off
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Python yüklü degil. Lutfen https://www.python.org/downloads/ adresinden Python'u indirip kurunuz.
    pause
    exit /b 1
)

pip install --upgrade pip
pip install ctypes customtkinter pillow

echo Tum paketler yuklendi.
python main.py
pause
