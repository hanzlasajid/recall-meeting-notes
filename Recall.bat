@echo off
setlocal
cd /d "%~dp0"
title Recall
rem Drag one or more recordings onto this file (or its desktop shortcut), or double-click it to pick one.
if not exist ".venv\Scripts\python.exe" (
  echo First run - setting up the tool...
  call "%~dp0setup_windows.bat" || exit /b 1
)
".venv\Scripts\python.exe" -m recall %*
echo.
pause
