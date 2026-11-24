@echo off
setlocal
cd /d "%~dp0"
title Recall - setup
echo ================================================
echo   Recall - one-time setup for Windows
echo ================================================
echo.

rem ---- 1. Find Python 3.10-3.13 (installs 3.12 with winget if missing) ----
set "PY="
for %%V in (3.12 3.11 3.13 3.10) do (
  if not defined PY (
    py -%%V --version >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY (
  echo Python 3.12 is not installed. Installing it for your user account with winget...
  echo If winget asks you to accept its terms, type Y and press Enter.
  winget install -e --id Python.Python.3.12 --scope user
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY (
  echo.
  echo Could not find or install Python. Install Python 3.12 from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH"^), then run this setup again.
  pause & exit /b 1
)
echo Using Python: %PY%
%PY% -c "import tkinter" >nul 2>nul || (
  echo.
  echo Note: this Python has no Tk, so Recall will ask in this window instead of showing windows.
  echo       For windows: reinstall Python from python.org with "tcl/tk and IDLE" ticked.
)

rem ---- 2. Private environment for the tool ----
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo Creating the tool's own Python environment in .venv ...
  %PY% -m venv .venv || (echo Could not create .venv & pause & exit /b 1)
)
set "VPY=%~dp0.venv\Scripts\python.exe"
"%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip

echo.
echo Installing the tool's libraries (a few minutes the first time)...
"%VPY%" -m pip install --disable-pip-version-check -r requirements.txt || (echo Install failed & pause & exit /b 1)

rem ---- 3. NVIDIA GPU support ----
where nvidia-smi >nul 2>nul
if not errorlevel 1 (
  echo.
  echo NVIDIA graphics card found - installing its CUDA libraries ^(about 1 GB^)...
  "%VPY%" -m pip install --disable-pip-version-check "nvidia-cublas-cu12" "nvidia-cudnn-cu12==9.*"
)

rem ---- 4. Desktop shortcut you can drop videos on ----
powershell -NoProfile -Command ^
  "$d=[Environment]::GetFolderPath('Desktop'); Remove-Item -ErrorAction SilentlyContinue ($d+'\Meeting Notes.lnk');" ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($d+'\Recall.lnk');" ^
  "$s.TargetPath='%~dp0Recall.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%SystemRoot%\System32\imageres.dll,18'; $s.Save()"

echo.
echo === Your hardware and the transcription model it will use ===
"%VPY%" -m recall --hardware
echo.
echo Setup finished. A "Recall" shortcut is on your desktop:
echo   - drag a recording onto it, or
echo   - double-click it and choose a recording.
echo No Anthropic API key? Recall can write the report with a free local AI instead
echo ^(it offers to install Ollama and a model the first time^).
pause
