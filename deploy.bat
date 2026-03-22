@echo off
setlocal enabledelayedexpansion
title SANITIZE - Deploy

set "APP_PORT=8080"
set "PROJECT_DIR=%~dp0"
set "LOG_FILE=%PROJECT_DIR%deploy.log"

echo.
echo  ================================================
echo   SANITIZE // Image Sanitizer - Deploy Script
echo  ================================================
echo.
echo [%date% %time%] Deploy started > "%LOG_FILE%"

:: --- Check admin rights ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] Requesting admin privileges...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)
echo  [OK] Admin rights confirmed

:: --- Check Docker ---
echo  [..] Checking Docker...
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] Docker not found.
    echo  [!] Please install Docker Desktop from:
    echo      https://www.docker.com/products/docker-desktop/
    echo.
    echo  After installing, re-run this script.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('docker --version') do echo  [OK] %%v

:: --- Start Docker engine ---
echo  [..] Checking Docker engine...
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo  [..] Starting Docker Desktop...

    set "DOCKER_EXE="
    if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
        set "DOCKER_EXE=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
    )
    if exist "%LocalAppData%\Programs\Docker\Docker\Docker Desktop.exe" (
        set "DOCKER_EXE=%LocalAppData%\Programs\Docker\Docker\Docker Desktop.exe"
    )

    if defined DOCKER_EXE (
        start "" "!DOCKER_EXE!"
    ) else (
        powershell -Command "Start-Process 'Docker Desktop'" >nul 2>&1
    )

    echo  [..] Waiting for Docker engine (up to 90s)...
    set "WAITED=0"
    :wait_docker
        timeout /t 3 /nobreak >nul
        docker info >nul 2>&1
        if %errorlevel% equ 0 goto :docker_ready
        set /a WAITED+=3
        echo  [..] Still waiting... (!WAITED!s)
        if !WAITED! geq 90 (
            echo  [ERR] Docker engine did not start in time.
            echo        Please start Docker Desktop manually and re-run.
            pause
            exit /b 1
        )
        goto :wait_docker
    :docker_ready
    echo  [OK] Docker engine ready
) else (
    echo  [OK] Docker engine already running
)

:: --- Check port ---
echo  [..] Checking port %APP_PORT%...
netstat -an | find ":%APP_PORT% " | find "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo  [!] Port %APP_PORT% is in use.
    echo      Please close the process using it, or change APP_PORT in this script.
    pause
    exit /b 1
)
echo  [OK] Port %APP_PORT% is free

:: --- Deploy ---
echo.
echo  [..] Building images (first run takes 3-5 min)...
cd /d "%PROJECT_DIR%"

docker compose down --remove-orphans >nul 2>&1

docker compose build --no-cache
if %errorlevel% neq 0 (
    echo  [ERR] Build failed. Check deploy.log for details.
    docker compose logs >> "%LOG_FILE%" 2>&1
    pause
    exit /b 1
)
echo  [OK] Build complete

echo  [..] Starting services...
docker compose up -d
if %errorlevel% neq 0 (
    echo  [ERR] Failed to start services.
    pause
    exit /b 1
)

:: --- Wait for service ---
echo  [..] Waiting for service to be ready...
set "ATTEMPTS=0"
:wait_svc
    timeout /t 3 /nobreak >nul
    powershell -NoProfile -Command "try{$r=(Invoke-WebRequest -Uri 'http://localhost:%APP_PORT%' -UseBasicParsing -TimeoutSec 2).StatusCode;if($r -eq 200){exit 0}exit 1}catch{exit 1}" >nul 2>&1
    if %errorlevel% equ 0 goto :svc_ready
    set /a ATTEMPTS+=1
    if !ATTEMPTS! geq 15 goto :svc_ready
    echo  [..] Attempt !ATTEMPTS!/15...
    goto :wait_svc
:svc_ready

:: --- Done ---
echo.
echo  ================================================
echo   Deploy successful!
echo.
echo   URL : http://localhost:%APP_PORT%
echo   Stop: docker compose down
echo   Logs: docker compose logs -f
echo  ================================================
echo.

start http://localhost:%APP_PORT%
pause
