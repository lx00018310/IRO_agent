@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo =======================================================
echo   IRO_agent (工业软件只读智能诊断助手)
echo =======================================================
echo.

set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if "%PYTHON_EXE%"=="" (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_EXE=python"
)

if "%PYTHON_EXE%"=="" (
    echo [错误] 未找到 Python 环境，请先安装 Python 并初始化 .venv 虚拟环境。
    pause
    exit /b 1
)

if /i "%~1"=="chat" goto DO_CHAT
if /i "%~1"=="gateway" goto DO_GATEWAY
if /i "%~1"=="doctor" goto DO_DOCTOR
if /i "%~1"=="test" goto DO_TEST
if /i "%~1"=="config" goto DO_CONFIG

:MENU
echo 请选择运行模式:
echo   [1] 交互式只读诊断对话 (CLI Chat) [默认]
echo   [2] 飞书机器人网关服务 (Feishu Gateway)
echo   [3] 工控机体检与安全体检 (Doctor Check)
echo   [4] 运行自动化验证套件 (Pytest)
echo   [5] 编辑配置文件 (记事本打开 config.json)
echo   [6] 退出
echo.

set "CHOICE=1"
set /p "CHOICE=请输入选择 [1-6, 默认 1]: "

if "%CHOICE%"=="1" goto DO_CHAT
if "%CHOICE%"=="2" goto DO_GATEWAY
if "%CHOICE%"=="3" goto DO_DOCTOR
if "%CHOICE%"=="4" goto DO_TEST
if "%CHOICE%"=="5" goto DO_CONFIG
if "%CHOICE%"=="6" goto DO_EXIT

echo [提示] 输入无效，请重新选择。
echo.
goto MENU

:DO_CONFIG
if exist "config.json" (
    start notepad.exe config.json
) else (
    echo [错误] 未找到 config.json 配置文件。
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
goto DO_EXIT

:DO_EXIT
exit /b 0