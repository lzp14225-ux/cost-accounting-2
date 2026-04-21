@echo off
chcp 65001 >nul
set "NX_PYTHON=D:\AI\Anaconda\envs\NX\python.exe"

if /I "%~1"=="frontend" goto frontend
if /I "%~1"=="backend" goto backend
if /I "%~1"=="mcp" goto mcp
goto main

:main
title Mold Main Startup
echo ====================================
echo    Mold Main - One Click Startup
echo ====================================
echo.

echo [1/3] Starting frontend...
start "frontend-dev" cmd /k call "%~f0" frontend

echo [2/3] Starting backend...
start "backend-main" cmd /k call "%~f0" backend

echo [3/3] Starting MCP...
start "backend-mcp" cmd /k call "%~f0" mcp

echo.
echo Startup commands sent.
pause
goto :eof

:frontend
title Frontend Dev
cd /d D:\AI\Pycharm\chengben2\mold_main\mold_cost_account_react
if errorlevel 1 (
    echo [ERROR] Failed to enter frontend directory.
    pause
    exit /b 1
)

echo Starting frontend...
npm run dev
if errorlevel 1 (
    echo [ERROR] Frontend failed to start.
    pause
)
goto :eof

:backend
title Backend Main
cd /d D:\AI\Pycharm\chengben2\mold_main\backend
if errorlevel 1 (
    echo [ERROR] Failed to enter backend directory.
    pause
    exit /b 1
)

if not exist "%NX_PYTHON%" (
    echo [ERROR] NX python not found:
    echo %NX_PYTHON%
    pause
    exit /b 1
)

echo Starting backend service...
"%NX_PYTHON%" main.py
if errorlevel 1 (
    echo [ERROR] Backend service failed to start.
    pause
)
goto :eof

:mcp
title Backend MCP
cd /d D:\AI\Pycharm\chengben2\mold_main\backend
if errorlevel 1 (
    echo [ERROR] Failed to enter backend directory.
    pause
    exit /b 1
)

if not exist "%NX_PYTHON%" (
    echo [ERROR] NX python not found:
    echo %NX_PYTHON%
    pause
    exit /b 1
)

echo Starting MCP service...
"%NX_PYTHON%" mcp_services\cad_price_search_mcp\server.py
if errorlevel 1 (
    echo [ERROR] MCP service failed to start.
    pause
)
goto :eof
