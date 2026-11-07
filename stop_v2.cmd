@chcp 65001 >nul
@echo off
rem Explicit safe stop for this configured Module A instance only.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\start_v2.ps1" -Stop %*
set "moduleaExitCode=%errorlevel%"
if not "%moduleaExitCode%"=="0" pause
exit /b %moduleaExitCode%
