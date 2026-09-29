@echo off
cd /d "%~dp0"

IF EXIST "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) ELSE (
    echo [Warning] Virtual environment not found at .\venv. Using system Python.
)

start "" pythonw gui.py
exit