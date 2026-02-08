@echo off
setlocal

if "%CONDA_ENV%"=="" set "CONDA_ENV=opencue_ue"
if "%CONDA_ROOT%"=="" set "CONDA_ROOT=%USERPROFILE%\miniconda3"

if "%CUEBOT_HOSTNAME%"=="" set "CUEBOT_HOSTNAME=localhost"
if "%CUEBOT_PORT%"=="" set "CUEBOT_PORT=8443"
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

if not exist "%CONDA_ROOT%\Scripts\activate.bat" (
  echo [run_rqd] ERROR: activate.bat not found under "%CONDA_ROOT%"
  exit /b 1
)

echo [run_rqd] Activate conda env: %CONDA_ENV%
call "%CONDA_ROOT%\Scripts\activate.bat" %CONDA_ENV%
if errorlevel 1 (
  echo [run_rqd] ERROR: failed to activate env "%CONDA_ENV%"
  exit /b 1
)

set "RQD_EXE=%CONDA_PREFIX%\Scripts\rqd.exe"
if not exist "%RQD_EXE%" (
  echo [run_rqd] ERROR: rqd.exe not found: "%RQD_EXE%"
  exit /b 1
)

set "PATH=%SCRIPT_DIR%;%PATH%"

echo [run_rqd] CUEBOT_HOSTNAME=%CUEBOT_HOSTNAME%
echo [run_rqd] CUEBOT_PORT=%CUEBOT_PORT%
echo [run_rqd] Start: "%RQD_EXE%"
echo.

"%RQD_EXE%"
set "EXITCODE=%ERRORLEVEL%"

endlocal
exit /b %EXITCODE%
