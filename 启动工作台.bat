@echo off
chcp 65001 >nul
title Minuet Workbench
cd /d "%~dp0"

rem ------------------------------------------------------------------
rem  优先使用项目内虚拟环境；没有就退回 PATH 里的 python
rem  第一次使用建议先执行：
rem      python -m venv .venv
rem      .venv\Scripts\pip install -r requirements.txt
rem ------------------------------------------------------------------
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
if not defined PY set "PY=python"

"%PY%" "workbench\server.py" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo [!] 启动失败（退出码 %RC%^)，请查看上面的报错信息。
  echo     若提示找不到 Python: 请安装 Python 3.9+ 并勾选 Add to PATH。
  echo     若提示缺少模块:     请执行  pip install -r requirements.txt
)
echo.
pause
