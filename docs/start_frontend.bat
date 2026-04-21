@echo off
chcp 65001 >nul
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
