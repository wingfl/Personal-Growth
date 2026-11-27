@echo off
setlocal
title 个人成长档案
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 goto nopython

python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if errorlevel 1 goto oldpython

echo.
echo   正在启动个人成长档案……
echo   浏览器会自动打开；关闭这个窗口即停止服务。
echo.
python tools\launch_ui.py
if errorlevel 1 goto failed
exit /b 0

:nopython
echo.
echo   没有找到 python。请安装 Python 3.10+，安装时勾选 "Add python.exe to PATH"。
echo   下载地址：https://www.python.org/downloads/
echo.
pause
exit /b 1

:oldpython
echo.
echo   Python 版本过低，需要 3.10 及以上。当前版本：
python -V
echo.
pause
exit /b 1

:failed
echo.
echo   启动失败，原因见上方。按任意键关闭。
echo.
pause
exit /b 1
