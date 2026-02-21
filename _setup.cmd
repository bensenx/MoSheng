@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

:: Log all output to file
set "LOGFILE=_setup.log"
> "%LOGFILE%" echo MoSheng setup started: %date% %time%
>> "%LOGFILE%" echo Working directory: %cd%

echo ================================================
echo   MoSheng - First-time Setup
echo ================================================
echo.

:: ---- Mirror source selection ----
set "_HAS_MIRROR=0"
if exist "mirror.env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%a in ("mirror.env") do (
        if not "%%a"=="" (
            set "%%a=%%b"
            set "_HAS_MIRROR=1"
        )
    )
)

if "!_HAS_MIRROR!"=="0" (
    echo Select download source:
    echo   [1] International ^(default^)
    echo   [2] China mainland mirror
    echo.
    choice /c 12 /t 15 /d 1 /m "Enter 1 or 2 (15s auto-select 1): "
    if !ERRORLEVEL! EQU 2 (
        > "mirror.env" echo UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
        >>"mirror.env" echo HF_ENDPOINT=https://hf-mirror.com
        set "UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple"
        set "HF_ENDPOINT=https://hf-mirror.com"
        echo [*] Using China mainland mirror
    ) else (
        type nul > "mirror.env"
        echo [*] Using international source
    )
    echo.
)

:: ---- ASR model selection ----
echo Select ASR model:
echo   [1] Qwen3-ASR-1.7B (default, ~4GB download, 6GB+ VRAM recommended)
echo   [2] Qwen3-ASR-0.6B (compact, ~1.8GB download, 3GB+ VRAM recommended)
echo.
choice /c 12 /t 15 /d 1 /m "Enter 1 or 2 (15s auto-select 1): "
if !ERRORLEVEL! EQU 2 (
    set "MOSHENG_MODEL_ID=Qwen/Qwen3-ASR-0.6B"
    set "MOSHENG_MODEL_NAME=Qwen3-ASR-0.6B"
    echo [*] Selected: Qwen3-ASR-0.6B
) else (
    set "MOSHENG_MODEL_ID=Qwen/Qwen3-ASR-1.7B"
    set "MOSHENG_MODEL_NAME=Qwen3-ASR-1.7B"
    echo [*] Selected: Qwen3-ASR-1.7B
)
echo.

:: ---- Check required files ----
if not exist "uv.exe" (
    echo [ERROR] uv.exe not found!
    >> "%LOGFILE%" echo ERROR: uv.exe not found in %cd%
    goto :fail
)
if not exist "configs\pyproject-cuda.toml" (
    if not exist "configs\pyproject-cpu.toml" (
        echo [ERROR] Config files not found!
        >> "%LOGFILE%" echo ERROR: configs directory missing or empty
        goto :fail
    )
)

:: ---- GPU detection ----
nvidia-smi >nul 2>&1
if errorlevel 1 (
    echo [!] No NVIDIA GPU detected, installing CPU version
    >> "%LOGFILE%" echo GPU: No CUDA, using CPU
    copy /y "configs\pyproject-cpu.toml" "pyproject.toml" >nul
    copy /y "configs\uv-cpu.lock" "uv.lock" >nul
) else (
    echo [+] NVIDIA GPU detected, installing CUDA version
    >> "%LOGFILE%" echo GPU: CUDA detected
    copy /y "configs\pyproject-cuda.toml" "pyproject.toml" >nul
    copy /y "configs\uv-cuda.lock" "uv.lock" >nul
)

:: Verify copy succeeded
if not exist "pyproject.toml" (
    echo [ERROR] Failed to create pyproject.toml!
    >> "%LOGFILE%" echo ERROR: Failed to create pyproject.toml
    goto :fail
)

echo.
echo Installing dependencies (first run downloads ~2GB, please wait)...
echo.

>> "%LOGFILE%" echo Running: uv sync
.\uv.exe sync --color never
if errorlevel 1 goto :uv_fail
>> "%LOGFILE%" echo uv sync completed successfully
goto :uv_ok

:uv_fail
>> "%LOGFILE%" echo FAILED: uv sync
echo.
echo ================================================
echo   Install failed!
echo   Please check your network connection.
echo   Details saved to _setup.log
echo ================================================
goto :fail

:uv_ok

:: Write initial model selection to settings (only if no settings exist yet)
if not exist "%USERPROFILE%\.mosheng" mkdir "%USERPROFILE%\.mosheng"
if not exist "%USERPROFILE%\.mosheng\settings.json" (
    > "%USERPROFILE%\.mosheng\settings.json" echo {"asr":{"model_name":"!MOSHENG_MODEL_NAME!","model_id":"!MOSHENG_MODEL_ID!"}}
    >> "%LOGFILE%" echo Model selection saved: !MOSHENG_MODEL_NAME!
)

:: Write version marker
> ".venv\.mosheng_version" echo 1.1.0
>> "%LOGFILE%" echo SUCCESS: setup completed

echo.
echo ================================================
echo   Setup complete! Starting MoSheng...
echo ================================================
timeout /t 3 >nul
exit /b 0

:fail
echo.
echo Press any key to exit...
pause >nul
exit /b 1
