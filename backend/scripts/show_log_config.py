# -*- coding: utf-8 -*-
"""
显示项目日志配置信息
"""

import os
from pathlib import Path

print("=" * 80)
print("项目日志配置信息")
print("=" * 80)

# 当前工作目录
cwd = Path.cwd()
print(f"\n当前工作目录: {cwd}")

# 日志文件列表
log_files = [
    {
        "name": "特征识别日志",
        "file": "feature_recognition.log",
        "module": "feature_recognition/feature_recognition.py",
        "env_var": "LOG_FILE",
        "default": "feature_recognition.log"
    },
    {
        "name": "滑块红色面日志",
        "file": "slider_red_face.log",
        "module": "run_slider_red_face.py",
        "env_var": None,
        "default": "slider_red_face.log"
    }
]

print("\n" + "=" * 80)
print("日志文件配置")
print("=" * 80)

for log_info in log_files:
    print(f"\n【{log_info['name']}】")
    print(f"  配置模块: {log_info['module']}")
    
    if log_info['env_var']:
        env_value = os.getenv(log_info['env_var'])
        if env_value:
            print(f"  环境变量: {log_info['env_var']}={env_value}")
            log_path = Path(env_value)
        else:
            print(f"  环境变量: {log_info['env_var']} (未设置，使用默认值)")
            log_path = cwd / log_info['default']
    else:
        log_path = cwd / log_info['file']
    
    print(f"  日志路径: {log_path}")
    
    if log_path.exists():
        size_kb = log_path.stat().st_size / 1024
        mtime = log_path.stat().st_mtime
        from datetime import datetime
        mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        print(f"  文件状态: ✅ 存在")
        print(f"  文件大小: {size_kb:.2f} KB")
        print(f"  最后修改: {mtime_str}")
    else:
        print(f"  文件状态: ❌ 不存在")

print("\n" + "=" * 80)
print("其他日志输出")
print("=" * 80)

other_modules = [
    "unified_api.py - 仅输出到控制台",
    "minio_client.py - 使用 loguru，输出到控制台",
    "cad_chaitu/*.py - 使用 loguru，输出到控制台",
]

for module in other_modules:
    print(f"  • {module}")

print("\n" + "=" * 80)
print("如何查看日志")
print("=" * 80)
print("""
1. 查看文件日志:
   - feature_recognition.log: 特征识别的详细日志
   - slider_red_face.log: 滑块红色面处理日志

2. 查看控制台日志:
   - 运行服务时直接在终端查看
   - 或使用重定向保存: python unified_api.py > api.log 2>&1

3. 实时监控日志:
   - PowerShell: Get-Content feature_recognition.log -Wait -Tail 50
   - 或使用: tail -f feature_recognition.log (如果有 Git Bash)

4. 自定义日志位置:
   - 在 .env 文件中设置: LOG_FILE=path/to/your.log
""")

print("=" * 80)
