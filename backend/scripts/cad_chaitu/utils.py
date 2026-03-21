#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
工具函数模块
"""

import re
from pathlib import Path
from typing import Optional


def extract_model_code_from_source(source: str) -> Optional[str]:
    """
    从路径或 URL 中提取模型代码（如 M250247-P6）
    
    示例:
        - http://example.com/files/M250247-P6_xxx.dwg -> M250247-P6
        - D:\path\M250247.P6.dwg -> M250247-P6
    """
    try:
        if source.startswith(('http://', 'https://')):
            filename = source.split('/')[-1]
        else:
            filename = Path(source).name
        
        match = re.search(r'(M\d{6})[.\-]?(P\d+)', filename, re.IGNORECASE)
        if match:
            return f"{match.group(1)}-{match.group(2)}"
        
        match = re.search(r'(M\d{6})', filename, re.IGNORECASE)
        if match:
            return match.group(1)
        
        return None
    except Exception:
        return None
