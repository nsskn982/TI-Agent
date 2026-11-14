@echo off
rem Starts the local PostgreSQL container (docker-compose.yml) if it isn't running,
rem starting Docker Desktop first when needed. Exit code 0 = database ready.
setlocal
cd /d "%~dp0.."
docker info >nul 2>&1
if errorlevel 1 (
    echo [..] Docker isn't running - starting Docker Desktop...
    if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
    for /l %%i in (1,1,36) do (
        timeout /t 5 /nobreak >nul
        docker info >nul 2>&1 && goto :engine_up
    )
    echo [x] Docker did not start. Open Docker Desktop and try again.
    exit /b 2
)
:engine_up
docker compose up -d --wait >nul 2>&1
if errorlevel 1 (
    echo [x] Could not start the database container. Try: docker compose up -d
    exit /b 2
)
exit /b 0
