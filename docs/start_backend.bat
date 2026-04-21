@echo off
chcp 65001 >nul
title Backend Main

cd /d D:\AI\Pycharm\chengben2\mold_main\backend
if errorlevel 1 (
    echo [ERROR] Failed to enter backend directory.
    pause
    exit /b 1
)

echo Activating conda environment NX...
call D:\AI\Anaconda\condabin\conda.bat activate NX
if errorlevel 1 (
    echo [ERROR] Failed to activate conda environment NX.
    pause
    exit /b 1
)

echo Starting backend service...
python main.py

if errorlevel 1 (
    echo [ERROR] Backend service failed to start.
    pause
)
