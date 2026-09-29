@echo off
setlocal enabledelayedexpansion

echo ========================================================
echo               FragForge Automated Setup
echo ========================================================
echo.

:: 1. Verify Python
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not installed or not on system PATH.
    echo Please install Python 3.10+ from python.org and check "Add Python to PATH".
    pause
    exit /b 1
)

:: 2. Verify FFmpeg
ffmpeg -version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [WARNING] FFmpeg was not detected on your system PATH!
    echo FragForge requires FFmpeg to render videos.
    echo Install via Windows Terminal: winget install Gyan.FFmpeg
    echo.
)

:: 3. Create venv
if not exist "venv" (
    echo [*] Creating virtual environment (.\venv)...
    python -m venv venv
) else (
    echo [*] Virtual environment already exists.
)

:: 4. Activate venv
call venv\Scripts\activate.bat

:: 5. Install PyTorch with CUDA 12.6
echo [*] Installing PyTorch with CUDA 12.6 hardware acceleration...
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126

:: 6. Install remaining dependencies
echo [*] Installing FragForge GUI and OCR dependencies...
pip install -r requirements.txt

:: 7. Create config.json from template if missing
if not exist "config.json" (
    if exist "config.example.json" (
        echo [*] Initializing config.json from template...
        copy config.example.json config.json >nul
    )
)

:: 8. Create folder scaffolding
if not exist "raw_clips\valo" mkdir "raw_clips\valo"
if not exist "raw_clips\cs2" mkdir "raw_clips\cs2"
if not exist "output\trimmed" mkdir "output\trimmed"
if not exist "temp" mkdir "temp"

echo.
echo ========================================================
echo           FragForge setup completed successfully!
echo   Launch the application anytime by running run_gui.bat
echo ========================================================
echo.
pause