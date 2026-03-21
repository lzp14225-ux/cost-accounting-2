# -*- coding: utf-8 -*-
"""
油槽识别模块
识别零件中的油槽特征
"""
import logging
import ezdxf
from typing import List


def detect_oil_tank(all_texts: List[str], 
                   doc: ezdxf.document.Drawing = None) -> int:
    """
    检测是否有油槽（仅使用文字识别）
    
    在所有文本中搜索"油槽"关键词
    
    Args:
        all_texts: 所有文本内容列表
        doc: DXF文档对象（保留参数以兼容调用方，但不使用）
    
    Returns:
        int: 1表示有油槽，0表示无油槽
    """
    oil_tank_keywords = ['油槽']
    
    for text in all_texts:
        for keyword in oil_tank_keywords:
            if keyword in text:
                logging.info(f"✅ 通过文字识别到油槽: {text}")
                return 1
    
    logging.info("ℹ️ 未检测到油槽")
    return 0
