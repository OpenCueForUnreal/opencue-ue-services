@echo off
setlocal

if "%CONDA_ENV%"=="" set "CONDA_ENV=opencue_ue"
if "%CONDA_ROOT%"=="" set "CONDA_ROOT=%USERPROFILE%\miniconda3"

if not exist "%CONDA_ROOT%\Scripts\activate.bat" (
  echo [run_cuegui] ERROR: activate.bat not found under "%CONDA_ROOT%"
  exit /b 1
)

echo [run_cuegui] Activate conda env: %CONDA_ENV%
call "%CONDA_ROOT%\Scripts\activate.bat" %CONDA_ENV%
if errorlevel 1 (
  echo [run_cuegui] ERROR: failed to activate env "%CONDA_ENV%"
  exit /b 1
)

set "CUEGUI_EXE=%CONDA_PREFIX%\Scripts\cuegui.exe"
if not exist "%CUEGUI_EXE%" (
  echo [run_cuegui] ERROR: cuegui.exe not found: "%CUEGUI_EXE%"
  exit /b 1
)

echo [run_cuegui] Start: "%CUEGUI_EXE%"
echo.
"%CUEGUI_EXE%"
set "EXITCODE=%ERRORLEVEL%"

endlocal
exit /b %EXITCODE%
