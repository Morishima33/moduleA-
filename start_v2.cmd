@chcp 65001 >nul
@echo off
rem 启动新版工作台（新界面 + 本机 JSON 接口）。原工作台仍可用 start.cmd 启动。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\start_v2.ps1"
if errorlevel 1 pause
