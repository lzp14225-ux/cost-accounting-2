# -*- coding: utf-8 -*-
"""
倒角识别模块
识别零件中的倒角特征（C倒角和R倒角）
"""
import logging
import re
from typing import List, Dict, Tuple, Union


def detect_chamfers(all_texts: List[str], processing_instructions: Union[Dict[str, any], List[str]]) -> Dict[str, int]:
    """
    识别倒角个数
    
    在除了加工说明外的文字中识别匹配 "Cx" 或 "Rx"，其中 x 是一个数字
    
    分类规则：
    - C1-C2: c1_c2_chamfer (0 < 值 < 3)
    - C3及以上: c3_c5_chamfer (值 ≥ 3)
    - R1-R2: r1_r2_chamfer (0 < 值 < 3)
    - R3及以上: r3_r5_chamfer (值 ≥ 3)
    
    Args:
        all_texts: 所有文本内容列表
        processing_instructions: 需要排除的加工说明
            格式1: {'M': '说明内容', 'M1': '说明内容', ...}  # 旧格式（字典）
            格式2: {'frame_1': ['文本1', '文本2', ...]}  # 图框格式（字典）
            格式3: ['完整文本1', '完整文本2', ...]  # 新格式（列表，推荐）
    
    Returns:
        Dict: {
            'c1_c2_chamfer': int,
            'c3_c5_chamfer': int,
            'r1_r2_chamfer': int,
            'r3_r5_chamfer': int
        }
    """
    # 收集需要排除的文字
    instruction_texts = set()
    
    if processing_instructions:
        if isinstance(processing_instructions, list):
            # 格式3: ['完整文本1', '完整文本2', ...] - 新格式，推荐
            instruction_texts.update(processing_instructions)
            logging.debug(f"使用列表格式排除 {len(processing_instructions)} 条加工说明文本")
        elif isinstance(processing_instructions, dict):
            # 格式1和格式2: 字典格式 - 兼容旧代码
            for key, value in processing_instructions.items():
                if isinstance(value, list):
                    # 格式2: {'frame_1': ['文本1', '文本2', ...]}
                    instruction_texts.update(value)
                elif isinstance(value, str):
                    # 格式1: {'M': '说明内容', 'M1': '说明内容', ...}
                    instruction_texts.add(value)
            logging.debug(f"使用字典格式排除 {len(instruction_texts)} 条文本")
    
    # 初始化计数器
    c1_c2_count = 0
    c3_c5_count = 0
    r1_r2_count = 0
    r3_r5_count = 0
    
    # 正则表达式：匹配 C 或 R 后面跟数字（可能有小数点）
    # 例如：C1, C2, C0.5, R1, R2.5, R3
    chamfer_pattern = re.compile(r'[CR](\d+(?:\.\d+)?)', re.IGNORECASE)
    
    # 用于记录已识别的倒角（避免重复计数）
    found_chamfers = []
    
    for text in all_texts:
        # 跳过需要排除的文字（精确匹配）
        if text in instruction_texts:
            continue
        
        # 跳过材质信息相关的文本（避免误识别 Cr12mov, HRC56 等）
        material_keywords = ['HRC', 'Cr12', 'SKD', 'SKH', 'NAK', 'S136', 'H13', 'P20', 'DC53']
        if any(keyword.lower() in text.lower() for keyword in material_keywords):
            continue
        
        # 查找所有匹配的倒角标注
        matches = chamfer_pattern.findall(text)
        
        for match in matches:
            try:
                # 提取数字值并四舍五入到两位小数
                value = round(float(match), 2)
                
                # 提取倒角类型（C 或 R）
                chamfer_type = None
                match_obj = re.search(r'([CR])' + re.escape(match), text, re.IGNORECASE)
                if match_obj:
                    chamfer_type = match_obj.group(1).upper()
                
                if not chamfer_type:
                    continue
                
                # 记录找到的倒角（使用四舍五入后的值）
                chamfer_info = f"{chamfer_type}{value}"
                found_chamfers.append({
                    'type': chamfer_type,
                    'value': value,
                    'text': text,
                    'label': chamfer_info
                })
                
                # 根据类型和数值范围分类计数
                if chamfer_type == 'C':
                    if 0 < value < 3:
                        c1_c2_count += 1
                    elif value >= 3:
                        c3_c5_count += 1
                elif chamfer_type == 'R':
                    if 0 < value < 3:
                        r1_r2_count += 1
                    elif value >= 3:
                        r3_r5_count += 1
                        
            except ValueError:
                continue
    
    # 输出识别结果日志
    if found_chamfers:
        logging.info(f"✅ 识别到 {len(found_chamfers)} 个倒角标注:")
        
        # 按类型分组显示
        c_chamfers = [c for c in found_chamfers if c['type'] == 'C']
        r_chamfers = [c for c in found_chamfers if c['type'] == 'R']
        
        if c_chamfers:
            c_labels = [c['label'] for c in c_chamfers]
            logging.info(f"   C倒角: {', '.join(c_labels)}")
        
        if r_chamfers:
            r_labels = [r['label'] for r in r_chamfers]
            logging.info(f"   R倒角: {', '.join(r_labels)}")
        
        logging.info(f"   分类统计: C1-C2={c1_c2_count}个, C3-C5={c3_c5_count}个, R1-R2={r1_r2_count}个, R3-R5={r3_r5_count}个")
    else:
        logging.info("ℹ️ 未识别到倒角标注")
    
    return {
        'c1_c2_chamfer': c1_c2_count,
        'c3_c5_chamfer': c3_c5_count,
        'r1_r2_chamfer': r1_r2_count,
        'r3_r5_chamfer': r3_r5_count
    }


def get_chamfer_summary(chamfer_counts: Dict[str, int]) -> str:
    """
    生成倒角统计摘要
    
    Args:
        chamfer_counts: 倒角计数字典
    
    Returns:
        str: 摘要文本
    """
    parts = []
    
    if chamfer_counts['c1_c2_chamfer'] > 0:
        parts.append(f"C1-C2: {chamfer_counts['c1_c2_chamfer']}个")
    
    if chamfer_counts['c3_c5_chamfer'] > 0:
        parts.append(f"C3-C5: {chamfer_counts['c3_c5_chamfer']}个")
    
    if chamfer_counts['r1_r2_chamfer'] > 0:
        parts.append(f"R1-R2: {chamfer_counts['r1_r2_chamfer']}个")
    
    if chamfer_counts['r3_r5_chamfer'] > 0:
        parts.append(f"R3-R5: {chamfer_counts['r3_r5_chamfer']}个")
    
    if not parts:
        return "无倒角"
    
    return ", ".join(parts)
