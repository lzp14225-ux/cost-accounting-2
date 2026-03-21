# -*- coding: utf-8 -*-
"""
水磨数据识别模块
识别图纸中的备料信息（"备料于xxx"）
"""
import re
import logging
from typing import Optional, List


def extract_material_preparation(all_texts: List[str]) -> Optional[str]:
    """
    从所有文本中提取备料信息
    
    Args:
        all_texts: 所有文本内容列表
    
    Returns:
        Optional[str]: 如果是备料件，返回备料信息（xxx部分），否则返回 None
    """
    # 匹配 "备料于xxx" 或 "备料在xxx" 的正则表达式
    # 支持多种可能的格式：备料于xxx、备料於xxx、备料在xxx 等
    pattern = re.compile(r'备料[于於在](.+?)(?:\s|$|[，。、])')
    
    for text in all_texts:
        match = pattern.search(text)
        if match:
            material_prep_info = match.group(1).strip()
            logging.info(f"✅ 检测到备料件: 备料信息={material_prep_info}")
            return material_prep_info
    
    logging.info("ℹ️ 未检测到备料信息，非备料件")
    return None
