"""
统一日志配置模块
负责人：系统架构

功能：
1. 统一日志格式
2. 支持多种输出方式（控制台、文件、JSON）
3. 支持日志轮转
4. 支持结构化日志
5. 支持分布式追踪（trace_id）
6. 支持不同环境配置（开发、生产）

使用方法：
    from shared.logging_config import setup_logging, get_logger
    
    # 初始化日志系统（在应用启动时调用一次）
    setup_logging()
    
    # 获取 logger
    logger = get_logger(__name__)
    logger.info("这是一条日志")
"""
import logging
import logging.handlers
import sys
import os
import json
import gzip
import shutil
import zipfile
from datetime import datetime
from datetime import time as dt_time
from pathlib import Path
from typing import Optional, Dict, Any
import traceback
from shared.timezone_utils import now_shanghai


# ========== 日志级别配置 ==========

LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL
}


# ========== 自定义 JSON Formatter ==========

class JSONFormatter(logging.Formatter):
    """
    JSON 格式化器
    
    输出结构化的 JSON 日志，便于日志收集和分析
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为 JSON"""
        log_data = {
            "timestamp": now_shanghai().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # 添加额外字段
        if hasattr(record, "trace_id"):
            log_data["trace_id"] = record.trace_id
        
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        
        if hasattr(record, "job_id"):
            log_data["job_id"] = record.job_id
        
        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info)
            }
        
        # 添加自定义字段
        if hasattr(record, "extra_data"):
            log_data["extra"] = record.extra_data
        
        return json.dumps(log_data, ensure_ascii=False)


# ========== 自定义 Console Formatter ==========

class ColoredFormatter(logging.Formatter):
    """
    彩色控制台格式化器
    
    为不同级别的日志添加颜色，提升可读性
    """
    
    # ANSI 颜色代码
    COLORS = {
        "DEBUG": "\033[36m",      # 青色
        "INFO": "\033[32m",       # 绿色
        "WARNING": "\033[33m",    # 黄色
        "ERROR": "\033[31m",      # 红色
        "CRITICAL": "\033[35m",   # 紫色
        "RESET": "\033[0m"        # 重置
    }
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录（带颜色）"""
        # 获取颜色
        color = self.COLORS.get(record.levelname, self.COLORS["RESET"])
        reset = self.COLORS["RESET"]
        
        # 格式化时间
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        
        # 构建日志消息
        log_message = (
            f"{color}[{timestamp}] "
            f"{record.levelname:8s}{reset} "
            f"{record.name:30s} | "
            f"{record.getMessage()}"
        )
        
        # 添加 trace_id（如果存在）
        if hasattr(record, "trace_id"):
            log_message += f" [trace_id={record.trace_id}]"
        
        # 添加异常信息
        if record.exc_info:
            log_message += f"\n{self.formatException(record.exc_info)}"
        
        return log_message


class ModuleFilter(logging.Filter):
    """Route records to a dedicated file by logger name prefix."""

    def __init__(self, module_prefix: str):
        super().__init__()
        self.module_prefix = module_prefix

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith(self.module_prefix)


class CompressedTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """Timed rotating file handler with optional gzip/zip compression."""

    def __init__(self, *args, compression: Optional[str] = None, **kwargs):
        self.compression = _normalize_compression(compression)
        super().__init__(*args, **kwargs)
        if self.compression:
            self.namer = self._namer
            self.rotator = self._rotator

    def _namer(self, default_name: str) -> str:
        return f"{default_name}.{self.compression}"

    def _rotator(self, source: str, dest: str) -> None:
        if self.compression == "gz":
            with open(source, "rb") as src, gzip.open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
        elif self.compression == "zip":
            with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(source, arcname=os.path.basename(source))
        else:
            shutil.move(source, dest)
            return
        os.remove(source)

    def getFilesToDelete(self):
        dir_name, base_name = os.path.split(self.baseFilename)
        file_names = os.listdir(dir_name)
        result = []
        prefix = f"{base_name}."

        for file_name in file_names:
            if not file_name.startswith(prefix):
                continue

            suffix = file_name[len(prefix):]
            if self.compression and suffix.endswith(f".{self.compression}"):
                suffix = suffix[: -(len(self.compression) + 1)]

            if self.extMatch.match(suffix):
                result.append(os.path.join(dir_name, file_name))

        result.sort()
        if len(result) <= self.backupCount:
            return []
        return result[: len(result) - self.backupCount]


def _normalize_compression(value: Optional[str]) -> Optional[str]:
    if value is None:
        return "zip"

    normalized = str(value).strip().lower()
    if normalized in {"", "none", "off", "false", "0"}:
        return None
    if normalized not in {"zip", "gz"}:
        return "zip"
    return normalized


def _parse_rotation_time(value: Optional[str]) -> dt_time:
    raw_value = (value or "00:00").strip()
    try:
        hour_str, minute_str = raw_value.split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)
        return dt_time(hour=hour, minute=minute)
    except Exception:
        return dt_time(hour=0, minute=0)


def get_log_rotation_settings(
    default_level: str = "INFO",
    default_retention_days: int = 30,
) -> Dict[str, Any]:
    level_name = os.getenv("LOG_LEVEL", default_level).upper()
    level = LOG_LEVELS.get(level_name, logging.INFO)

    try:
        retention_days = max(1, int(os.getenv("LOG_RETENTION_DAYS", str(default_retention_days))))
    except ValueError:
        retention_days = max(1, default_retention_days)

    rotation_label = os.getenv("LOG_ROTATION_TIME", "00:00").strip() or "00:00"
    compression = _normalize_compression(os.getenv("LOG_COMPRESSION", "zip"))

    return {
        "level_name": level_name,
        "level": level,
        "retention_days": retention_days,
        "rotation_label": rotation_label,
        "rotation_time": _parse_rotation_time(rotation_label),
        "compression": compression,
    }


def build_standard_file_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def create_daily_rotating_file_handler(
    filename: Path,
    level: Optional[int] = None,
    formatter: Optional[logging.Formatter] = None,
    encoding: str = "utf-8",
    delay: bool = False,
) -> logging.Handler:
    settings = get_log_rotation_settings()
    handler = CompressedTimedRotatingFileHandler(
        filename=str(filename),
        when="midnight",
        interval=1,
        backupCount=settings["retention_days"],
        encoding=encoding,
        delay=delay,
        atTime=settings["rotation_time"],
        compression=settings["compression"],
    )
    handler.setLevel(level if level is not None else settings["level"])
    if formatter is not None:
        handler.setFormatter(formatter)
    return handler


# ========== 日志配置函数 ==========

def setup_logging(
    level: str = None,
    log_dir: str = "logs",
    enable_console: bool = True,
    enable_file: bool = True,
    enable_json: bool = False,
    enable_module_logs: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5
):
    """
    配置日志系统
    
    Args:
        level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
        log_dir: 日志文件目录
        enable_console: 是否启用控制台输出
        enable_file: 是否启用文件输出
        enable_json: 是否启用 JSON 格式文件输出
        max_bytes: 单个日志文件最大大小
        backup_count: 保留的日志文件数量
    """
    # 从环境变量获取日志级别
    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO")
    
    log_level = LOG_LEVELS.get(level.upper(), logging.INFO)
    
    # 获取根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # 清除已有的 handlers
    root_logger.handlers.clear()
    file_formatter = build_standard_file_formatter()
    
    # ========== 控制台输出 ==========
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        
        # 使用彩色格式化器
        console_formatter = ColoredFormatter()
        console_handler.setFormatter(console_formatter)
        
        root_logger.addHandler(console_handler)
    
    # ========== 文件输出 ==========
    if enable_file:
        # 创建日志目录
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        # 普通文本日志
        file_handler = create_daily_rotating_file_handler(
            filename=log_path / "app.log",
            level=log_level,
            formatter=file_formatter,
            encoding="utf-8"
        )
        
        # 使用标准格式化器
        root_logger.addHandler(file_handler)
        
        # 错误日志单独记录
        error_handler = create_daily_rotating_file_handler(
            filename=log_path / "error.log",
            level=logging.ERROR,
            formatter=file_formatter,
            encoding="utf-8"
        )
        
        root_logger.addHandler(error_handler)

        if enable_module_logs:
            module_configs = [
                ("api_gateway", "api_gateway.log"),
                ("workers", "workers.log"),
                ("agents", "agents.log"),
                ("shared", "shared.log"),
            ]

            for module_prefix, filename in module_configs:
                module_handler = create_daily_rotating_file_handler(
                    filename=log_path / filename,
                    level=log_level,
                    formatter=file_formatter,
                    encoding="utf-8"
                )
                module_handler.addFilter(ModuleFilter(module_prefix))
                root_logger.addHandler(module_handler)
    
    # ========== JSON 格式日志 ==========
    if enable_json:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        json_handler = create_daily_rotating_file_handler(
            filename=log_path / "app.json",
            level=log_level,
            encoding="utf-8"
        )
        json_handler.setFormatter(JSONFormatter())
        
        root_logger.addHandler(json_handler)
    
    # 记录初始化信息
    root_logger.info(
        f"✅ 日志系统初始化完成: level={level}, console={enable_console}, "
        f"file={enable_file}, json={enable_json}, module_logs={enable_module_logs}"
    )


# ========== 获取 Logger ==========

def get_logger(name: str) -> logging.Logger:
    """
    获取 logger 实例
    
    Args:
        name: logger 名称（通常使用 __name__）
    
    Returns:
        logging.Logger: logger 实例
    """
    return logging.getLogger(name)


# ========== 日志上下文管理器 ==========

class LogContext:
    """
    日志上下文管理器
    
    用于在日志中添加额外的上下文信息（如 trace_id, user_id, job_id）
    
    使用方法：
        with LogContext(trace_id="xxx", user_id="yyy"):
            logger.info("这条日志会包含 trace_id 和 user_id")
    """
    
    def __init__(self, **kwargs):
        """
        初始化上下文
        
        Args:
            **kwargs: 上下文字段（如 trace_id, user_id, job_id）
        """
        self.context = kwargs
        self.old_factory = None
    
    def __enter__(self):
        """进入上下文"""
        self.old_factory = logging.getLogRecordFactory()
        
        def record_factory(*args, **kwargs):
            record = self.old_factory(*args, **kwargs)
            for key, value in self.context.items():
                setattr(record, key, value)
            return record
        
        logging.setLogRecordFactory(record_factory)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文"""
        logging.setLogRecordFactory(self.old_factory)


# ========== 日志装饰器 ==========

def log_execution(logger: logging.Logger = None):
    """
    日志装饰器
    
    自动记录函数的执行时间和结果
    
    使用方法：
        @log_execution()
        async def my_function():
            pass
    """
    import functools
    import time
    
    def decorator(func):
        nonlocal logger
        if logger is None:
            logger = get_logger(func.__module__)
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            logger.info(f"🚀 开始执行: {func.__name__}")
            
            try:
                result = await func(*args, **kwargs)
                elapsed = time.time() - start_time
                logger.info(f"✅ 执行完成: {func.__name__} (耗时: {elapsed:.2f}s)")
                return result
            
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(f"❌ 执行失败: {func.__name__} (耗时: {elapsed:.2f}s)", exc_info=True)
                raise
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            logger.info(f"🚀 开始执行: {func.__name__}")
            
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                logger.info(f"✅ 执行完成: {func.__name__} (耗时: {elapsed:.2f}s)")
                return result
            
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(f"❌ 执行失败: {func.__name__} (耗时: {elapsed:.2f}s)", exc_info=True)
                raise
        
        # 判断是否为异步函数
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


# ========== 性能日志 ==========

class PerformanceLogger:
    """
    性能日志记录器
    
    用于记录代码块的执行时间
    
    使用方法：
        with PerformanceLogger("数据库查询"):
            result = await db.query(...)
    """
    
    def __init__(self, operation: str, logger: logging.Logger = None):
        """
        初始化性能日志记录器
        
        Args:
            operation: 操作名称
            logger: logger 实例（可选）
        """
        self.operation = operation
        self.logger = logger or get_logger(__name__)
        self.start_time = None
    
    def __enter__(self):
        """进入上下文"""
        self.start_time = now_shanghai()
        self.logger.debug(f"⏱️  开始: {self.operation}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文"""
        elapsed = (now_shanghai() - self.start_time).total_seconds()
        
        if exc_type is None:
            self.logger.info(f"✅ 完成: {self.operation} (耗时: {elapsed:.3f}s)")
        else:
            self.logger.error(f"❌ 失败: {self.operation} (耗时: {elapsed:.3f}s)")
