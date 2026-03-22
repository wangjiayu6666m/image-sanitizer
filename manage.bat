@echo off
setlocal enabledelayedexpansion
title SANITIZE - Manager

set "PROJECT_DIR=%~dp0"
set "APP_PORT=8080"

:menu
cls
echo.
echo  ================================================
echo   SANITIZE // Service Manager
echo  ================================================
echo.

docker compose -f "%PROJECT_DIR%docker-compose.yml" ps --format "{{.Name}} {{.Status}}" 2>nul | find "running" >nul 2>&1
if %errorlevel% equ 0 (
    echo   Status : RUNNING - http://localhost:%APP_PORT%
) else (
    echo   Status : STOPPED
)

echo.
echo   [1] Start
echo   [2] Stop
echo   [3] Restart
echo   [4] Logs (live)
echo   [5] Open browser
echo   [6] Container stats
echo   [7] Rebuild
echo   [8] Uninstall (remove containers + images)
echo   [0] Exit
echo.
set /p "CHOICE=  Select [0-8]: "

if "!CHOICE!"=="1" goto :start
if "!CHOICE!"=="2" goto :stop
if "!CHOICE!"=="3" goto :restart
if "!CHOICE!"=="4" goto :logs
if "!CHOICE!"=="5" goto :browser
if "!CHOICE!"=="6" goto :stats
if "!CHOICE!"=="7" goto :rebuild
if "!CHOICE!"=="8" goto :uninstall
if "!CHOICE!"=="0" exit /b 0
goto :menu

:start
cd /d "%PROJECT_DIR%" && docker compose up -d
pause & goto :menu

:stop
cd /d "%PROJECT_DIR%" && docker compose down
pause & goto :menu

:restart
cd /d "%PROJECT_DIR%" && docker compose restart
pause & goto :menu

:logs
cd /d "%PROJECT_DIR%" && docker compose logs -f
pause & goto :menu

:browser
start http://localhost:%APP_PORT%
goto :menu

:stats
docker stats --no-stream
pause & goto :menu

:rebuild
cd /d "%PROJECT_DIR%"
docker compose down
docker compose build --no-cache
docker compose up -d
pause & goto :menu

:uninstall
echo.
echo  WARNING: This will remove all containers and images.
echo  Project files will NOT be deleted.
echo.
set /p "CONFIRM=  Type YES to confirm: "
if not "!CONFIRM!"=="YES" ( echo Cancelled. & pause & goto :menu )
cd /d "%PROJECT_DIR%"
docker compose down --rmi all --volumes --remove-orphans
echo Done.
pause & goto :menu
