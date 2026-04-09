rem Windows 计划任务入口：调用 Python 清理后端过期文件
@echo off
setlocal
"D:\AI\Anaconda\python.exe" "D:\AI\Pycharm\chengben2\mold_main\backend\scripts\cleanup_expired_backend_files.py"
