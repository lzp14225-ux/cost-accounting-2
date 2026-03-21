#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CAD 拆图模块
"""

import sys
from pathlib import Path
from loguru import logger

# 添加 scripts 目录到路径（用于导入 minio_client）
_current_dir = Path(__file__).parent
_scripts_dir = _current_dir.parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

# 尝试导入 MinIO 客户端
_minio_client = None
try:
    from minio_client import minio_client as _minio_client
    logger.info("✅ MinIO 客户端自动导入成功")
except ImportError as e:
    logger.warning(f"⚠️ MinIO 客户端导入失败（MinIO 功能将不可用）: {e}")
    _minio_client = None

# 导入核心模块
from .converter import DWGConverter
from .number_extractor import ProfessionalDrawingNumberExtractor
from .text_processor import IntelligentTextProcessor
from .cutting_detector import RelaxedCuttingDetector
from .block_analyzer import OptimizedCADBlockAnalyzer
from .cad_system import CADAnalysisSystem
from .database import DatabaseManager
from .storage import FileStorageManager
from .utils import extract_model_code_from_source

# 导入主处理函数（延迟导入避免循环依赖）
chaitu_process = None
init_managers = None

def _lazy_import():
    """延迟导入 main 模块"""
    global chaitu_process, init_managers
    if chaitu_process is None:
        from .main import chaitu_process as _chaitu_process
        from .main import init_managers as _init_managers
        chaitu_process = _chaitu_process
        init_managers = _init_managers
        # 初始化管理器
        try:
            init_managers(_minio_client)
        except Exception as e:
            logger.warning(f"⚠️ 管理器初始化失败: {e}")

# 立即执行延迟导入
_lazy_import()

__all__ = [
    'DWGConverter',
    'ProfessionalDrawingNumberExtractor',
    'IntelligentTextProcessor',
    'RelaxedCuttingDetector',
    'OptimizedCADBlockAnalyzer',
    'CADAnalysisSystem',
    'DatabaseManager',
    'FileStorageManager',
    'extract_model_code_from_source',
    'chaitu_process',
    'init_managers',
]
