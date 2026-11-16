@echo off
chcp 65001 >nul
rem 与macOS共用同一Python运行管理；路径以脚本目录解析。
if defined MODULEA_PYTHON (
  "%MODULEA_PYTHON%" -B "%~dp0tools\manage_service.py" %*
) else (
  py -3 -B "%~dp0tools\manage_service.py" %*
)
exit /b %errorlevel%
