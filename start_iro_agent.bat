@echo off
set "PYTHONDONTWRITEBYTECODE=1"
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

if /i "%~1"=="doctor" goto DO_DOCTOR
if /i "%~1"=="test" goto DO_TEST
if /i "%~1"=="config" goto DO_CONFIG
if /i "%~1"=="setup" goto DO_SETUP
if /i "%~1"=="sources" goto DO_SOURCES

"%PYTHON_EXE%" -m iro_agent.cli setup --check >nul 2>nul
if errorlevel 1 (
    echo [必需] 请先完成本项目配置引导，才能执行初始化、查询或网关服务。
    "%PYTHON_EXE%" -m iro_agent.cli setup
    if errorlevel 1 goto DO_PAUSE
)

if /i "%~1"=="chat" goto DO_CHAT
if /i "%~1"=="gateway" goto DO_GATEWAY
if /i "%~1"=="init" goto DO_INIT

:MENU
echo -------------------------------------------------------
echo    [10] 项目配置向导（添加/删除多个来源）
echo    [11] 运行自动化验证套件 (Pytest)
echo    [12] 工控机与数据来源体检 (Doctor Check)
echo    [13] 初始化/更新项目认知 (Project Bootstrap)
echo -------------------------------------------------------
echo  【日常业务运行】(完成前置步骤后选用):
echo    [1] 交互式只读诊断对话 (CLI Chat) [默认]
echo    [2] 飞书机器人网关服务 (Feishu Gateway)
echo -------------------------------------------------------
echo  【辅助配置与系统退出】:
echo    [21] 重新运行项目配置向导
echo    [22] 退出
echo    [23] 查看本项目数据来源
echo    [24] 查看脱敏后的生效配置
echo =======================================================
echo.

set "CHOICE=1"
set /p "CHOICE=请输入选择 [默认 1]: "

if "%CHOICE%"=="1" goto DO_CHAT
if "%CHOICE%"=="2" goto DO_GATEWAY
if "%CHOICE%"=="10" goto DO_SETUP
if "%CHOICE%"=="11" goto DO_TEST
if "%CHOICE%"=="12" goto DO_DOCTOR
if "%CHOICE%"=="13" goto DO_INIT
if "%CHOICE%"=="21" goto DO_SETUP
if "%CHOICE%"=="22" goto DO_EXIT
if "%CHOICE%"=="23" goto DO_SOURCES
if "%CHOICE%"=="24" goto DO_CONFIG
@rem 兼容旧版数字按键输入
if "%CHOICE%"=="3" goto DO_DOCTOR
if "%CHOICE%"=="4" goto DO_TEST
if "%CHOICE%"=="5" goto DO_INIT
if "%CHOICE%"=="6" goto DO_SETUP
if "%CHOICE%"=="7" goto DO_EXIT

echo [提示] 输入无效，请重新选择。
echo.
goto MENU

:DO_INIT
"%PYTHON_EXE%" -m iro_agent.cli init --refresh
goto DO_PAUSE

:DO_CONFIG
"%PYTHON_EXE%" -m iro_agent.cli config
goto DO_PAUSE

:DO_SETUP
"%PYTHON_EXE%" -m iro_agent.cli setup
goto DO_PAUSE

:DO_SOURCES
"%PYTHON_EXE%" -m iro_agent.cli sources
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
set "IRO_EXIT_CODE=%errorlevel%"
pause
exit /b %IRO_EXIT_CODE%

:DO_EXIT
exit /b 0
