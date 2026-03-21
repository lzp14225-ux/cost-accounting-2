"""
InputNormalizer - 输入标准化器

职责：
1. 将各种格式的输入标准化为统一格式
2. 支持子图ID的多种格式变体
3. 支持尺寸字符串的解析和标准化
"""
import re
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class InputNormalizer:
    """输入标准化器"""
    
    @staticmethod
    def normalize_subgraph_id(input_id: str) -> List[str]:
        """
        标准化子图ID
        
        支持的输入格式：
        - 小写: "ph204" → ["PH204", "PH-204"]
        - 大写: "PH204" → ["PH204", "PH-204"]
        - 带连字符: "PH2-04" → ["PH204", "PH-204"]
        - 带空格: "PH2 04" → ["PH204", "PH-204"]
        - 混合: "ph2-04" → ["PH204", "PH-204"]
        
        Args:
            input_id: 用户输入的ID
        
        Returns:
            可能的标准格式列表
        """
        if not input_id:
            return []
        
        # 1. 转大写并去除首尾空格
        normalized = input_id.upper().strip()
        
        # 2. 移除所有空格、连字符、下划线
        clean = re.sub(r'[\s\-_]', '', normalized)
        
        # 3. 生成可能的格式变体
        variants = [clean]  # 无连字符版本
        
        # 4. 尝试插入连字符（在字母和数字之间）
        # 支持多种模式：
        # - UP01 → UP-01
        # - PH204 → PH-204, PH2-04
        # - DIE03 → DIE-03
        # - UB07 → UB-07
        
        # 模式1: 纯字母 + 纯数字 (如 UP01 → UP-01)
        match1 = re.match(r'^([A-Z]+)(\d+)$', clean)
        if match1:
            prefix, number = match1.groups()
            variants.append(f"{prefix}-{number}")
        
        # 模式2: 字母 + 数字 + 数字 (如 PH204 → PH2-04)
        match2 = re.match(r'^([A-Z]+\d)(\d+)$', clean)
        if match2:
            prefix, number = match2.groups()
            variants.append(f"{prefix}-{number}")
        
        # 模式3: 字母 + 字母+数字 (如 PUBL2 → PU-BL2)
        match3 = re.match(r'^([A-Z]{2})([A-Z]+\d+)$', clean)
        if match3:
            prefix, suffix = match3.groups()
            variants.append(f"{prefix}-{suffix}")
        
        # 去重并保持顺序
        seen = set()
        result = []
        for v in variants:
            if v not in seen:
                seen.add(v)
                result.append(v)
        
        logger.debug(f"标准化 '{input_id}' → {result}")
        return result
    
    @staticmethod
    def normalize_dimension(input_dim: str) -> Optional[Dict[str, float]]:
        """
        标准化尺寸输入
        
        支持的输入格式：
        - "200*150*30"
        - "200x150x30"
        - "200X150X30"
        - "200×150×30"
        - "200 * 150 * 30"
        
        Args:
            input_dim: 用户输入的尺寸字符串
        
        Returns:
            标准化的尺寸字典，如果解析失败返回 None
        """
        if not input_dim:
            return None
        
        # 移除所有空格
        clean = input_dim.strip().replace(' ', '')
        
        # 支持多种分隔符: *, x, X, ×
        parts = re.split(r'[*xX×]+', clean)
        
        if len(parts) != 3:
            logger.warning(f"尺寸格式错误: '{input_dim}'，应为 length*width*thickness")
            return None
        
        try:
            result = {
                "length": float(parts[0]),
                "width": float(parts[1]),
                "thickness": float(parts[2])
            }
            logger.debug(f"标准化尺寸 '{input_dim}' → {result}")
            return result
        except ValueError as e:
            logger.warning(f"尺寸解析失败: '{input_dim}' - {e}")
            return None
    
    @staticmethod
    def normalize_material(input_material: str) -> str:
        """
        标准化材质代码
        
        支持的转换：
        - 大小写统一: "cr12" → "CR12"
        - 去除空格: "CR 12" → "CR12"
        - 特殊材质: "TOOLOX33" → "T00L0X33"
        
        Args:
            input_material: 用户输入的材质
        
        Returns:
            标准化的材质代码
        """
        if not input_material:
            return ""
        
        # 转大写并去除空格
        normalized = input_material.upper().strip().replace(' ', '')
        
        # 特殊材质转换: TOOLOX → T00L0X
        normalized = re.sub(r'TOOLOX(\d+)', r'T00L0X\1', normalized)
        
        logger.debug(f"标准化材质 '{input_material}' → '{normalized}'")
        return normalized
    
    @staticmethod
    def normalize_input(text: str) -> str:
        """
        标准化用户输入文本
        
        - 去除首尾空格
        - 统一多个空格为单个空格
        - 去除特殊控制字符
        
        Args:
            text: 用户输入文本
        
        Returns:
            标准化后的文本
        """
        if not text:
            return ""
        
        # 去除首尾空格
        normalized = text.strip()
        
        # 统一多个空格为单个空格
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # 去除特殊控制字符（保留换行、制表符）
        normalized = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', normalized)
        
        return normalized
