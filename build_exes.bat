@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%build_exes.ps1" %*
set "EXITCODE=%ERRORLEVEL%"

endlocal
exit /b %EXITCODE%
