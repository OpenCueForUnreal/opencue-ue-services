@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "SUBMITTER_EXE=%SCRIPT_DIR%\opencue-ue-submitter.exe"
if not exist "%SUBMITTER_EXE%" set "SUBMITTER_EXE=%SCRIPT_DIR%\dist\opencue-ue-submitter.exe"

if exist "%SUBMITTER_EXE%" (
  pushd "%SCRIPT_DIR%"
  "%SUBMITTER_EXE%" %*
  set "EXITCODE=%ERRORLEVEL%"
  popd
  endlocal
  exit /b %EXITCODE%
)

set "RESOLVED_PYTHON_EXE="
if not "%CONDA_PREFIX%"=="" if exist "%CONDA_PREFIX%\python.exe" set "RESOLVED_PYTHON_EXE=%CONDA_PREFIX%\python.exe"
if "%RESOLVED_PYTHON_EXE%"=="" if exist "%SCRIPT_DIR%\.venv\Scripts\python.exe" set "RESOLVED_PYTHON_EXE=%SCRIPT_DIR%\.venv\Scripts\python.exe"
if "%RESOLVED_PYTHON_EXE%"=="" if not "%USERPROFILE%"=="" if exist "%USERPROFILE%\miniconda3\envs\opencue_ue\python.exe" set "RESOLVED_PYTHON_EXE=%USERPROFILE%\miniconda3\envs\opencue_ue\python.exe"
if "%RESOLVED_PYTHON_EXE%"=="" set "RESOLVED_PYTHON_EXE=python"

pushd "%SCRIPT_DIR%"
"%RESOLVED_PYTHON_EXE%" -m src.ue_submit %*
set "EXITCODE=%ERRORLEVEL%"
popd

endlocal
exit /b %EXITCODE%
