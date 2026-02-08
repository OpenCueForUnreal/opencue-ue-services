@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "AGENT_EXE=%SCRIPT_DIR%\opencue-ue-agent.exe"
if not exist "%AGENT_EXE%" set "AGENT_EXE=%SCRIPT_DIR%\dist\opencue-ue-agent.exe"
set "AGENT_HOME=%SCRIPT_DIR%"
if "%DATA_ROOT%"=="" set "DATA_ROOT=%SCRIPT_DIR%\data\worker_pool"
if "%LOG_ROOT%"=="" set "LOG_ROOT=%SCRIPT_DIR%\logs\worker_pool"
if "%WORK_ROOT%"=="" set "WORK_ROOT=%SCRIPT_DIR%\logs\one_shot"
if "%UE_WRAPPER_HEADLESS%"=="" set "UE_WRAPPER_HEADLESS=1"

if exist "%AGENT_EXE%" (
  pushd "%SCRIPT_DIR%"
  "%AGENT_EXE%" %*
  set "EXITCODE=%ERRORLEVEL%"
  popd
  endlocal
  exit /b %EXITCODE%
)

set "RESOLVED_PYTHON_EXE="
if not "%CONDA_PREFIX%"=="" if exist "%CONDA_PREFIX%\python.exe" set "RESOLVED_PYTHON_EXE=%CONDA_PREFIX%\python.exe"
if "%RESOLVED_PYTHON_EXE%"=="" if exist "%SCRIPT_DIR%\.venv\Scripts\python.exe" set "RESOLVED_PYTHON_EXE=%SCRIPT_DIR%\.venv\Scripts\python.exe"
if "%RESOLVED_PYTHON_EXE%"=="" if not "%USERPROFILE%"=="" if exist "%USERPROFILE%\miniconda3\envs\opencue_ue\python.exe" set "RESOLVED_PYTHON_EXE=%USERPROFILE%\miniconda3\envs\opencue_ue\python.exe"
if "%RESOLVED_PYTHON_EXE%"=="" (
  if not "%APPDATA%"=="" (
    for %%I in ("%APPDATA%\..\..") do if exist "%%~fI\miniconda3\envs\opencue_ue\python.exe" set "RESOLVED_PYTHON_EXE=%%~fI\miniconda3\envs\opencue_ue\python.exe"
  )
)
if "%RESOLVED_PYTHON_EXE%"=="" set "RESOLVED_PYTHON_EXE=python"

pushd "%SCRIPT_DIR%"
"%RESOLVED_PYTHON_EXE%" -m src.ue_agent %*
set "EXITCODE=%ERRORLEVEL%"
popd

endlocal
exit /b %EXITCODE%
