@echo off
chcp 65001 >nul
title 个人成长档案
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo   没有找到 python，请先安装 Python 3.10+ 并勾选 "Add to PATH"。
  echo.
  pause
  exit /b 1
)

echo 正在启动个人成长档案，稍后会自动打开浏览器……
python tools\launch_ui.py
if errorlevel 1 (
  echo.
  echo   启动失败，错误信息见上方。按任意键关闭。
  pause
)
