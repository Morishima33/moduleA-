@chcp 65001 >nul
@echo off
rem Safe stop then hidden start; never terminates an arbitrary process.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\start_v2.ps1" -Restart %*
set "moduleaExitCode=%errorlevel%"
if not "%moduleaExitCode%"=="0" pause
exit /b %moduleaExitCode%
