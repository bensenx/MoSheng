@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
:: Manual invocation uses the same runtime selection and installation lock.
if not defined MOSHENG_RUNTIME (
    if not exist "MoSheng.exe" exit /b 1
    start "" /wait "MoSheng.exe" --setup-only
    if errorlevel 1 exit /b 1
    exit /b 0
)

set "LOGFILE=%MOSHENG_HOME%\_setup.log"
> "%LOGFILE%" echo MoSheng dependency setup started: %date% %time%
:: A returning user's settings and model selection already exist.
if exist "%USERPROFILE%\.mosheng\settings.json" goto :sync
if exist "%MOSHENG_HOME%\mirror.env" goto :model

echo Select download source:
echo   [1] International
echo   [2] China mainland mirror
choice /c 12 /t 15 /d 1 /m "Select a source (default 1):"
if not errorlevel 2 goto :international
if errorlevel 3 goto :international
set "UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple"
set "HF_ENDPOINT=https://hf-mirror.com"
> "%MOSHENG_HOME%\mirror.env" echo UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
>>"%MOSHENG_HOME%\mirror.env" echo HF_ENDPOINT=https://hf-mirror.com
goto :model

:international
type nul > "%MOSHENG_HOME%\mirror.env"

:model
echo Select ASR model:
echo   [1] Qwen3-ASR-1.7B (default)
echo   [2] Qwen3-ASR-0.6B (compact)
set "MOSHENG_MODEL_NAME=Qwen3-ASR-1.7B"
choice /c 12 /t 15 /d 1 /m "Select a model (default 1):"
if errorlevel 3 goto :sync
if errorlevel 2 set "MOSHENG_MODEL_NAME=Qwen3-ASR-0.6B"

:sync
echo Preparing the shared MoSheng runtime. Compatible builds will reuse it.
".\uv.exe" sync --project "%MOSHENG_RUNTIME%" --frozen --no-install-project --color never
if errorlevel 1 (
    >> "%LOGFILE%" echo uv sync failed. See console output above.
    pause
    exit /b 1
)
if exist "%USERPROFILE%\.mosheng\settings.json" goto :done
if not exist "%USERPROFILE%\.mosheng" mkdir "%USERPROFILE%\.mosheng"
> "%USERPROFILE%\.mosheng\settings.json" echo {"asr":{"model_name":"%MOSHENG_MODEL_NAME%","model_id":"Qwen/%MOSHENG_MODEL_NAME%"}}
if errorlevel 1 exit /b 1
:done
>> "%LOGFILE%" echo Shared runtime prepared successfully.
exit /b 0
