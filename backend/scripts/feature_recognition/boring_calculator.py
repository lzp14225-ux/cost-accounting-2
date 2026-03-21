# -*- coding: utf-8 -*-
"""
孔数量计算模块
从 wire_cut_details 中统计包含直径符号的工艺编号数量
"""
import logging
import re
from typing import List, Dict, Any


def calculate_boring_num(wire_cut_details: List[Dict[str, Any]]) -> int:
    """
    计算孔的个数
    
    规则：
    - 遍历 wire_cut_details 数组
    - 检查每个项的 instruction 字段是否满足以下两个条件：
      1. 以直径符号（'Φ' 或 '∅'）+ 数字开头，或以 数字 -Φ/∅ 开头
      2. 包含"割"字（表示线割工艺）
    - 匹配模式：
      * 模式1: 以 Φ或∅ + 数字（可选小数）开头 + 包含"割"
      * 模式2: 以 数字 -Φ/∅ + 数字（可选小数）开头 + 包含"割"
    - 示例：
      * 'Φ10.00割,单+0.01(合销)穿线孔Φ5.0钻' ✅ 孔工艺
      * '4 -Φ10.00割,单+0.01(合销)穿线孔Φ5.0钻' ✅ 孔工艺（解析后的格式）
      * 'Φ20.00割,单+0.005，穿线孔Φ5.0钻' ✅ 孔工艺
      * '2 -Φ20.00割,单+0.005，穿线孔Φ5.0钻' ✅ 孔工艺（解析后的格式）
      * 'Φ8.00冲头夹持孔，割，单+0.01' ✅ 孔工艺
      * '3 -Φ8.00冲头夹持孔，割，单+0.01' ✅ 孔工艺（解析后的格式）
      * '∅34.00线割' ✅ 孔工艺
      * '6 -Φ8.5正钻,正攻M10xP1.5深30.0mm' ❌ 不是孔（虽然以Φ开头，但不包含"割"）
      * '4 -Φ18.0钻穿(等高套筒)' ❌ 不是孔（虽然以Φ开头，但不包含"割"）
      * '实数侧割' ❌ 不是孔（不以直径符号开头）
      * 'C5斜角让位' ❌ 不是孔（不以直径符号开头）
      * '10-背铣Φ22.0深15.00mm' ❌ 不是孔（虽然有数字-Φ，但后面是"铣"不是"割"）
    - 如果匹配，则该项对应的是孔工艺，孔的个数就是该项的 matched_count 值
    - 统计所有孔的总数
    
    Args:
        wire_cut_details: 线割详情列表，格式如：
            [
                {
                    "code": "ZA",
                    "instruction": "Φ8.00割++0.005",
                    "matched_count": 2,
                    ...
                },
                {
                    "code": "ZB",
                    "instruction": "∅12.00割",
                    "matched_count": 3,
                    ...
                },
                {
                    "code": "L",
                    "instruction": "Φ10.00割,单+0.01(合销)穿线孔Φ5.0钻",
                    "matched_count": 4,
                    ...
                },
                {
                    "code": "W",
                    "instruction": "Φ8.00冲头夹持孔，割，单+0.01",
                    "matched_count": 3,
                    ...
                },
                {
                    "code": "实数侧割",
                    "instruction": "实数侧割",
                    "matched_count": 1,
                    ...
                }
            ]
    
    Returns:
        孔的总个数
    """
    if not wire_cut_details:
        return 0
    
    total_boring_num = 0
    
    # 匹配模式：以 Φ或∅ + 数字（可选小数）开头，或者以 数字 -Φ/∅ 开头，并且包含"割"字
    # 模式1: 直接以直径符号开头（如 "Φ10.00割"）
    # 模式2: 以数字开头，后跟 -Φ/∅（如 "4 -Φ10.00割"）
    # 使用 ^ 表示字符串开头
    # 例如: 
    #   - Φ10.00割,单+0.01(合销)穿线孔Φ5.0钻 ✅ (以Φ开头且包含"割")
    #   - 4 -Φ10.00割,单+0.01(合销)穿线孔Φ5.0钻 ✅ (以数字-Φ开头且包含"割")
    #   - ∅34.00线割 ✅ (以∅开头且包含"割")
    #   - 2 -∅34.00线割 ✅ (以数字-∅开头且包含"割")
    #   - Φ8.00冲头夹持孔，割，单+0.01 ✅ (以Φ开头且包含"割")
    #   - 3 -Φ8.00冲头夹持孔，割，单+0.01 ✅ (以数字-Φ开头且包含"割")
    #   - 6 -Φ8.5正钻,正攻M10xP1.5深30.0mm ❌ (虽然以数字-Φ开头，但不包含"割")
    #   - 4 -Φ18.0钻穿(等高套筒) ❌ (虽然以数字-Φ开头，但不包含"割")
    #   - 背铣Φ22.0深15.00mm ❌ (Φ不在开头)
    #   - 10-背铣Φ22.0深15.00mm ❌ (虽然有数字-Φ，但后面是"铣"不是"割")
    boring_pattern = re.compile(r'^(?:\d+\s*[-\-]\s*)?[Φ∅]\d+(?:\.\d+)?')
    
    for detail in wire_cut_details:
        instruction = detail.get('instruction', '')
        matched_count = detail.get('matched_count', 0)
        
        # 检查指令是否以直径符号+数字开头（孔工艺特征），并且包含"割"字
        if boring_pattern.match(instruction) and '割' in instruction:
            total_boring_num += matched_count
            logging.info(
                f"发现孔工艺: 编号='{detail.get('code')}', "
                f"指令='{instruction}', 数量={matched_count}"
            )
    
    logging.info(f"孔的总个数: {total_boring_num}")
    return total_boring_num
