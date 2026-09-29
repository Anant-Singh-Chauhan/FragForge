@echo off
:: Anchor execution directly to the script's home directory
cd /d "%~dp0"
setlocal enabledelayedexpansion

echo ========================================================
echo               FragForge Automated Setup
echo ========================================================
echo.

:: 1. Verify Python installation
echo [*] Checking Python environment...
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not installed or not available on your system PATH.
    echo Download and install Python 3.10+ from https://www.python.org/
    echo Be sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
) else (
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PY_VER=%%i
    echo [OK] !PY_VER! detected on system PATH.
)
echo.

:: 2. Verify FFmpeg installation
echo [*] Checking FFmpeg installation...
ffmpeg -version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [WARNING] FFmpeg was not detected on your system PATH.
    echo FragForge requires FFmpeg to process and composite videos.
    echo Install it via Windows Terminal:
    echo     winget install Gyan.FFmpeg
    echo (Restart your terminal or VS Code after installing FFmpeg)
) else (
    for /f "tokens=1,2,3" %%a in ('ffmpeg -version 2^>^&1 ^| findstr /i "version"') do set FF_VER=%%a %%b %%c
    echo [OK] FFmpeg detected: !FF_VER!
)
echo.

:: 3. Detect Dedicated GPU
echo [*] Checking hardware capabilities...
nvidia-smi >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set HAS_NVIDIA=1
    for /f "skip=8 tokens=1-3" %%a in ('nvidia-smi 2^>^&1') do (
        if not defined GPU_NAME (
            set GPU_NAME=%%a %%b %%c
        )
    )
    echo [OK] Dedicated NVIDIA GPU detected via nvidia-smi.
) else (
    set HAS_NVIDIA=0
    echo [NOTICE] No dedicated NVIDIA GPU detected or nvidia-smi not available.
    echo FragForge will configure PyTorch for CPU-based OCR.
)
echo.

:: 4. Virtual environment creation & verification
echo [*] Checking virtual environment (.\venv)...
if not exist "venv" (
    echo [*] Creating virtual environment...
    python -m venv venv
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to create virtual environment. Check directory permissions.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created successfully.
) else (
    echo [OK] Existing virtual environment found.
)
echo.

:: 5. Activate virtual environment
echo [*] Activating virtual environment...
call venv\Scripts\activate.bat
if %ERRORLEVEL% equ 0 (
    echo [OK] Virtual environment activated.
) else (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)
echo.

:: 6. Upgrade Pip and Install PyTorch
echo [*] Upgrading pip...
python -m pip install --upgrade pip >nul 2>&1
echo [OK] Pip is up to date.

if "%HAS_NVIDIA%"=="1" (
    echo [*] Installing PyTorch with CUDA 12.6 hardware acceleration...
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
) else (
    echo [*] Installing standard PyTorch for CPU computation...
    pip install torch torchvision
)

if %ERRORLEVEL% equ 0 (
    echo [OK] PyTorch runtime installed successfully.
) else (
    echo [ERROR] PyTorch installation failed. Please check network connectivity.
    pause
    exit /b 1
)
echo.

:: 7. Install pipeline dependencies
echo [*] Installing dependencies from requirements.txt...
pip install -r requirements.txt
if %ERRORLEVEL% equ 0 (
    echo [OK] All requirements installed successfully.
) else (
    echo [ERROR] Failed to install one or more dependencies from requirements.txt.
    pause
    exit /b 1
)
echo.

:: 8. Provision config.json from config.example.json
echo [*] Verifying project configuration...
if not exist "config.json" (
    if exist "config.example.json" (
        echo [*] Initializing config.json from config.example.json...
        copy "config.example.json" "config.json" >nul
        if %ERRORLEVEL% equ 0 (
            echo [OK] Default config.json created successfully.
        ) else (
            echo [ERROR] Failed to copy config.example.json to config.json.
        )
    ) else (
        echo [ERROR] config.example.json was not found in %~dp0
        echo Please ensure config.example.json is present in the repository root.
    )
) else (
    echo [OK] Existing config.json detected. Keeping custom settings.
)
echo.

:: 9. Ensure directory scaffolding exists
echo [*] Verifying directory structure...
if not exist "raw_clips\valo" mkdir "raw_clips\valo"
if not exist "raw_clips\cs2" mkdir "raw_clips\cs2"
if not exist "raw_clips\processed\valo" mkdir "raw_clips\processed\valo"
if not exist "raw_clips\processed\cs2" mkdir "raw_clips\processed\cs2"
if not exist "output\trimmed" mkdir "output\trimmed"
if not exist "temp" mkdir "temp"
if not exist "assets\branding" mkdir "assets\branding"
echo [OK] Folder scaffolding verified (raw_clips, output, temp, assets).

echo.
echo ========================================================
echo           FragForge setup completed successfully!
echo.
echo Launch the desktop application anytime by running:
echo     run_gui.bat
echo ========================================================
echo.
pause