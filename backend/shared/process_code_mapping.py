"""
工艺代码映射模块
负责人：人员B2

职责：
1. 将中文工艺名称映射到数据库代码
2. 将材质名称映射到数据库代码
3. 支持 job_price_snapshots 表的批量修改
4. 提供工艺类别和详细信息的映射

使用场景：
- 用户说"将这套的线割割一修一的单价改成0.0018"
  → 系统需要将"线割割一修一"映射到 category="wire", sub_category="slow_and_one"
- 用户说"45#价格改成6块"
  → 系统需要将"45#"映射到 category="material", sub_category="45#"
"""
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# 工艺类别映射（中文 → 英文代码）
CATEGORY_MAPPING = {
    "线割": "wire",
    "热处理": "heat",
    "材料": "material",
    "材质": "material",
    "标准": "standard",
    "自找料": "add_auto_material",
}


# 工艺详细映射（中文 → category + sub_category + note）
# 
# 包含两类映射：
# 1. 线割工艺映射（用于工艺修改和价格修改）
# 2. 材质映射（用于材质价格修改）
#
# 线割工艺根据实际数据库对应关系：
# slow_and_three → 慢丝割一修三
# slow_and_two → 慢丝割一修二
# slow_and_one → 慢丝割一修一
# slow_cut → 慢丝割一刀
# middle_and_one → 中丝割一修一
# fast_cut → 快丝割一刀
#
# 材质根据实际数据库对应关系：
# CR12, 45#, SKD11, CR12MOV, SKH-51, SKH-9, T00L0X33, T00L0X44, P20, DC53
PROCESS_DETAIL_MAPPING = {
    # 线割工艺 - 慢丝
    "慢丝割一修三": {
        "category": "wire",
        "sub_category": "slow_and_three",
        "note": "慢丝割一修三"
    },
    "慢丝割一修二": {
        "category": "wire",
        "sub_category": "slow_and_two",
        "note": "慢丝割一修二"
    },
    "慢丝割一修一": {
        "category": "wire",
        "sub_category": "slow_and_one",
        "note": "慢丝割一修一"
    },
    "慢丝割一刀": {
        "category": "wire",
        "sub_category": "slow_cut",
        "note": "慢丝割一刀"
    },
    "慢丝": {
        "category": "wire",
        "sub_category": "slow_and_one",
        "note": "慢丝割一修一"
    },
    
    # 线割工艺 - 中丝
    "中丝割一修一": {
        "category": "wire",
        "sub_category": "middle_and_one",
        "note": "中丝割一修一"
    },
    "中丝": {
        "category": "wire",
        "sub_category": "middle_and_one",
        "note": "中丝割一修一"
    },
    
    # 线割工艺 - 快丝
    "快丝割一刀": {
        "category": "wire",
        "sub_category": "fast_cut",
        "note": "快丝割一刀"
    },
    "快丝": {
        "category": "wire",
        "sub_category": "fast_cut",
        "note": "快丝割一刀"
    },
    
    # 材质映射（用于价格修改）
    # 根据 job_price_snapshots 表的 category="material", sub_category=材质代码
    "CR12": {
        "category": "material",
        "sub_category": "CR12",
        "note": "CR12"
    },
    "45#": {
        "category": "material",
        "sub_category": "45#",
        "note": "45#"
    },
    "SKD11": {
        "category": "material",
        "sub_category": "SKD11",
        "note": "SKD11"
    },
    "CR12MOV": {
        "category": "material",
        "sub_category": "CR12MOV",
        "note": "CR12MOV"
    },
    "SKH-51": {
        "category": "material",
        "sub_category": "SKH-51",
        "note": "SKH-51"
    },
    "SKH-9": {
        "category": "material",
        "sub_category": "SKH-9",
        "note": "SKH-9"
    },
    "T00L0X33": {
        "category": "material",
        "sub_category": "T00L0X33",
        "note": "T00L0X33"
    },
    "TOOLOX33": {  # 别名，标准化为 T00L0X33
        "category": "material",
        "sub_category": "T00L0X33",
        "note": "T00L0X33"
    },
    "T00L0X44": {
        "category": "material",
        "sub_category": "T00L0X44",
        "note": "T00L0X44"
    },
    "TOOLOX44": {  # 别名，标准化为 T00L0X44
        "category": "material",
        "sub_category": "T00L0X44",
        "note": "T00L0X44"
    },
    "P20": {
        "category": "material",
        "sub_category": "P20",
        "note": "P20"
    },
    "DC53": {
        "category": "material",
        "sub_category": "DC53",
        "note": "DC53"
    },
}


def resolve_process_code(chinese_text: str) -> Optional[Dict[str, Any]]:
    """
    解析中文工艺名称到数据库代码
    
    Args:
        chinese_text: 中文工艺名称（如"慢丝割一修一"、"中丝割一修一"、"快丝割一刀"）
    
    Returns:
        {
            "category": "wire",
            "sub_category": "slow_and_one",
            "note": "慢丝割一修一"
        }
        如果未找到，返回 None
    
    Examples:
        >>> resolve_process_code("慢丝割一修一")
        {'category': 'wire', 'sub_category': 'slow_and_one', 'note': '慢丝割一修一'}
        
        >>> resolve_process_code("中丝割一修一")
        {'category': 'wire', 'sub_category': 'middle_and_one', 'note': '中丝割一修一'}
        
        >>> resolve_process_code("快丝割一刀")
        {'category': 'wire', 'sub_category': 'fast_cut', 'note': '快丝割一刀'}
    """
    # 清理输入
    chinese_text = chinese_text.strip()
    
    # 精确匹配
    if chinese_text in PROCESS_DETAIL_MAPPING:
        result = PROCESS_DETAIL_MAPPING[chinese_text]
        logger.info(f"✅ 工艺代码映射: {chinese_text} → {result}")
        return result
    
    # 未找到
    logger.warning(f"⚠️  未找到工艺代码映射: {chinese_text}")
    return None


def resolve_category(chinese_text: str) -> Optional[str]:
    """
    解析中文类别名称到英文代码
    
    Args:
        chinese_text: 中文类别名称（如"线割"、"热处理"）
    
    Returns:
        英文代码（如"wire"、"heat"），如果未找到返回 None
    
    Examples:
        >>> resolve_category("线割")
        'wire'
        
        >>> resolve_category("热处理")
        'heat'
    """
    chinese_text = chinese_text.strip()
    
    if chinese_text in CATEGORY_MAPPING:
        result = CATEGORY_MAPPING[chinese_text]
        logger.info(f"✅ 类别映射: {chinese_text} → {result}")
        return result
    
    logger.warning(f"⚠️  未找到类别映射: {chinese_text}")
    return None


def extract_process_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    从自然语言文本中提取工艺或材质信息
    
    Args:
        text: 用户输入的自然语言（如"将这套的慢丝割一修一的单价改成0.0018"或"材料Cr12的价格改为5"）
    
    Returns:
        工艺/材质代码字典，如果未找到返回 None
    
    Examples:
        >>> extract_process_from_text("将这套的慢丝割一修一的单价改成0.0018")
        {'category': 'wire', 'sub_category': 'slow_and_one', 'note': '慢丝割一修一'}
        
        >>> extract_process_from_text("快丝割一刀的价格改为0.002")
        {'category': 'wire', 'sub_category': 'fast_cut', 'note': '快丝割一刀'}
        
        >>> extract_process_from_text("材料Cr12的价格改为5")
        {'category': 'material', 'sub_category': 'CR12', 'note': 'CR12'}
        
        >>> extract_process_from_text("45#价格改成6块")
        {'category': 'material', 'sub_category': '45#', 'note': '45#'}
        
        >>> extract_process_from_text("TOOLOX33价格改成8块")
        {'category': 'material', 'sub_category': 'T00L0X33', 'note': 'T00L0X33'}
    """
    # 🆕 特殊处理：TOOLOX33/TOOLOX44 标准化为 T00L0X33/T00L0X44
    import re
    text_normalized = text
    text_normalized = re.sub(r'TOOLOX33', 'T00L0X33', text_normalized, flags=re.IGNORECASE)
    text_normalized = re.sub(r'TOOLOX44', 'T00L0X44', text_normalized, flags=re.IGNORECASE)
    
    # 尝试精确匹配所有已知的工艺名称
    for process_name in PROCESS_DETAIL_MAPPING.keys():
        if process_name in text_normalized:
            result = PROCESS_DETAIL_MAPPING[process_name]
            logger.info(f"✅ 从文本提取工艺: {text} → {process_name} → {result}")
            return result
    
    # 🆕 尝试大小写不敏感的材质匹配
    # 提取可能的材质代码（字母+数字+特殊字符的组合）
    
    # 匹配材质代码模式: CR12, 45#, SKD11, SKH-51, TOOLOX33 等
    material_patterns = [
        r'[A-Za-z]{2,}[-]?\d+',  # CR12, SKD11, SKH-51, TOOLOX33
        r'\d+#',                  # 45#
        r'[A-Z]{1,2}\d+'         # P20, DC53
    ]
    
    for pattern in material_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            # 标准化为大写
            normalized = match.upper()
            
            # 🆕 特殊处理：TOOLOX → T00L0X
            normalized = re.sub(r'TOOLOX(\d+)', r'T00L0X\1', normalized)
            
            # 在映射表中查找（大小写不敏感）
            for key, value in PROCESS_DETAIL_MAPPING.items():
                if key.upper() == normalized:
                    logger.info(f"✅ 从文本提取材质（大小写不敏感）: {text} → {match} → {normalized} → {value}")
                    return value
    
    logger.warning(f"⚠️  未能从文本提取工艺或材质: {text}")
    return None


# 导出的公共接口
__all__ = [
    'CATEGORY_MAPPING',
    'PROCESS_DETAIL_MAPPING',
    'resolve_process_code',
    'resolve_category',
    'extract_process_from_text',
]
