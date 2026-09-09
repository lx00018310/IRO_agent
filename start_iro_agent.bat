@echo off
cd /d "%~dp0"

echo =======================================================
echo   IRO_agent (Industrial Read-Only Diagnostic Agent)
echo =======================================================
echo.

:: 自动生成初始配置文件
if not exist "config.json" (
    if exist "config.example.json" (
        copy "config.example.json" "config.json" >nul
        echo [INFO] Initialized config.json from config.example.json.
    )
)

set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_EXE=python"
    )
)

if "%PYTHON_EXE%"=="" (
    echo [ERROR] Python not found. Please install Python or initialize .venv.
    pause
    exit /b 1
)

if /i "%~1"=="chat" goto DO_CHAT
if /i "%~1"=="gateway" goto DO_GATEWAY
if /i "%~1"=="doctor" goto DO_DOCTOR
if /i "%~1"=="test" goto DO_TEST
if /i "%~1"=="config" goto DO_CONFIG

echo Select an option:
echo   [1] Interactive Diagnostic Chat (CLI Chat) [Default]
echo   [2] WeChat Gateway Service (WeChat Gateway)
echo   [3] Environment and Security Check (Doctor Check)
echo   [4] Run Automated Verification Tests (Pytest)
echo   [5] Edit Configuration File (Notepad config.json)
echo   [6] Exit
echo.

set "CHOICE=1"
set /p "CHOICE=Enter choice [1-6, default 1]: "

if "%CHOICE%"=="1" goto DO_CHAT
if "%CHOICE%"=="2" goto DO_GATEWAY
if "%CHOICE%"=="3" goto DO_DOCTOR
if "%CHOICE%"=="4" goto DO_TEST
if "%CHOICE%"=="5" goto DO_CONFIG
if "%CHOICE%"=="6" goto DO_EXIT

:DO_CONFIG
if exist "config.json" (
    start notepad.exe config.json
) else (
    echo [WARN] config.json not found.
)
goto DO_PAUSE

:DO_CHAT
"%PYTHON_EXE%" -m iro_agent.cli chat
goto DO_PAUSE

:DO_GATEWAY
"%PYTHON_EXE%" -m iro_agent.cli gateway start
goto DO_PAUSE

:DO_DOCTOR
"%PYTHON_EXE%" -m iro_agent.cli doctor
goto DO_PAUSE

:DO_TEST
"%PYTHON_EXE%" -m pytest -v
goto DO_PAUSE

:DO_PAUSE
pause

:DO_EXIT
