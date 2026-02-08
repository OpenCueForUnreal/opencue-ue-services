@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM -----------------------------------------------------------------------------
REM OpenCue Cuebot (Java) launcher for Windows.
REM
REM Requirements:
REM   - Java 11+ on PATH (Cuebot 1.13.8 is class version 55).
REM   - PostgreSQL reachable.
REM
REM Optional env overrides:
REM   JAVA_EXE           Full path to java.exe (otherwise uses java on PATH)
REM   CUEBOT_JAR         Full path to cuebot-*-all.jar
REM   CUEBOT_DB_URL      JDBC url, e.g. jdbc:postgresql://localhost/cuebot_local
REM   CUEBOT_DB_USER     DB username
REM   CUEBOT_DB_PASS     DB password
REM   CUEBOT_HTTP_PORT   Spring Boot HTTP port (default: 18080, do NOT use 8443)
REM   CUEBOT_LOG_ROOT    Frame log root (default: <repo>\logs)
REM -----------------------------------------------------------------------------

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

if "%CUEBOT_JAR%"=="" set "CUEBOT_JAR=%SCRIPT_DIR%\Downloads\cuebot-1.13.8-all.jar"
if "%CUEBOT_DB_URL%"=="" set "CUEBOT_DB_URL=jdbc:postgresql://localhost/cuebot_local"
if "%CUEBOT_DB_USER%"=="" set "CUEBOT_DB_USER=cuebot"
if "%CUEBOT_DB_PASS%"=="" set "CUEBOT_DB_PASS=cuebot"
if "%CUEBOT_HTTP_PORT%"=="" set "CUEBOT_HTTP_PORT=18080"
if "%CUEBOT_LOG_ROOT%"=="" set "CUEBOT_LOG_ROOT=%SCRIPT_DIR%\logs"
if "%JAVA_EXE%"=="" set "JAVA_EXE=java"

if not exist "%CUEBOT_JAR%" (
  echo [run_cuebot] ERROR: cuebot jar not found: "%CUEBOT_JAR%"
  echo [run_cuebot]        Put jar under "%SCRIPT_DIR%\Downloads" or set CUEBOT_JAR
  exit /b 1
)

if not exist "%CUEBOT_LOG_ROOT%" (
  mkdir "%CUEBOT_LOG_ROOT%" >NUL 2>NUL
)

REM Normalize backslashes to forward slashes for Cuebot flag value
set "CUEBOT_LOG_ROOT_FWD=%CUEBOT_LOG_ROOT:\=/%"

echo [run_cuebot] Using jar: "%CUEBOT_JAR%"
echo [run_cuebot] DB: %CUEBOT_DB_URL%
echo [run_cuebot] HTTP Port: %CUEBOT_HTTP_PORT%
echo [run_cuebot] FrameLogRoot: %CUEBOT_LOG_ROOT_FWD%
echo.

"%JAVA_EXE%" -jar "%CUEBOT_JAR%" ^
  --server.port=%CUEBOT_HTTP_PORT% ^
  --datasource.cue-data-source.jdbc-url=%CUEBOT_DB_URL% ^
  --datasource.cue-data-source.username=%CUEBOT_DB_USER% ^
  --datasource.cue-data-source.password=%CUEBOT_DB_PASS% ^
  --log.frame-log-root.default_os="%CUEBOT_LOG_ROOT_FWD%"

endlocal
