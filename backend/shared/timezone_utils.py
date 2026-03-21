"""
时区工具模块
负责人：系统架构组

职责：
1. 提供统一的时区处理函数
2. 确保整个系统使用 Asia/Shanghai 时区
3. 处理时区转换和格式化
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional

# 统一使用 Asia/Shanghai 时区
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def now_shanghai() -> datetime:
    """
    获取当前 Asia/Shanghai 时区的时间（naive datetime，用于数据库）
    
    Returns:
        不带时区信息的 datetime 对象（Asia/Shanghai 时间）
        
    Note:
        PostgreSQL 的 TIMESTAMP 类型不支持时区信息，
        因此返回 naive datetime，但时间是 Asia/Shanghai 时区
    """
    return datetime.now(SHANGHAI_TZ).replace(tzinfo=None)


def utc_to_shanghai(dt: datetime) -> datetime:
    """
    将 UTC 时间转换为 Asia/Shanghai 时区
    
    Args:
        dt: UTC 时间（可以是 naive 或 aware）
    
    Returns:
        Asia/Shanghai 时区的 datetime 对象
    """
    if dt.tzinfo is None:
        # 如果是 naive datetime，假设它是 UTC
        dt = dt.replace(tzinfo=timezone.utc)
    
    return dt.astimezone(SHANGHAI_TZ)


def shanghai_to_utc(dt: datetime) -> datetime:
    """
    将 Asia/Shanghai 时区转换为 UTC
    
    Args:
        dt: Asia/Shanghai 时间（可以是 naive 或 aware）
    
    Returns:
        UTC 时区的 datetime 对象
    """
    if dt.tzinfo is None:
        # 如果是 naive datetime，假设它是 Asia/Shanghai
        dt = dt.replace(tzinfo=SHANGHAI_TZ)
    
    return dt.astimezone(timezone.utc)


def format_shanghai_time(dt: Optional[datetime] = None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    格式化 Asia/Shanghai 时区的时间
    
    Args:
        dt: datetime 对象，如果为 None 则使用当前时间
        fmt: 时间格式字符串
    
    Returns:
        格式化后的时间字符串
    """
    if dt is None:
        dt = now_shanghai()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=SHANGHAI_TZ)
    else:
        dt = dt.astimezone(SHANGHAI_TZ)
    
    return dt.strftime(fmt)


def to_naive_shanghai(dt: datetime) -> datetime:
    """
    转换为 naive datetime（Asia/Shanghai 时区，但不带时区信息）
    用于数据库存储（PostgreSQL TIMESTAMP without timezone）
    
    Args:
        dt: datetime 对象
    
    Returns:
        不带时区信息的 datetime 对象（Asia/Shanghai 时间）
    """
    if dt.tzinfo is None:
        # 已经是 naive，假设它是 Asia/Shanghai
        return dt
    
    # 转换到 Asia/Shanghai 时区，然后移除时区信息
    shanghai_dt = dt.astimezone(SHANGHAI_TZ)
    return shanghai_dt.replace(tzinfo=None)


def from_naive_shanghai(dt: datetime) -> datetime:
    """
    将 naive datetime 转换为带时区信息的 datetime（Asia/Shanghai）
    用于从数据库读取时间
    
    Args:
        dt: naive datetime 对象（假设是 Asia/Shanghai 时间）
    
    Returns:
        带 Asia/Shanghai 时区信息的 datetime 对象
    """
    if dt.tzinfo is not None:
        # 已经有时区信息
        return dt.astimezone(SHANGHAI_TZ)
    
    return dt.replace(tzinfo=SHANGHAI_TZ)
