@chcp 65001 >nul
rem 上一行设置 UTF-8，使中文启动提示正常显示。
@echo off
rem 上一行隐藏命令本身，仅显示使用提示。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\start.ps1"
rem 上一行调用项目内启动脚本；只对本次进程指定策略，不修改系统设置。
if errorlevel 1 pause
rem 上一行在启动失败时保留窗口，便于阅读原因。
