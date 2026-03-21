# -*- coding: utf-8 -*-
"""
尺寸提取模块
从 DXF 文件中提取长宽厚尺寸信息
"""
import logging
import re
from typing import Tuple, Optional

logging.basicConfig(level=logging.INFO)


def extract_dimensions_from_text(doc) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    从DXF文件的文字中提取尺寸信息（L, W, T）
    
    Args:
        doc: ezdxf Document 对象
    
    Returns:
        Tuple[length, width, thickness] 或 (None, None, None)
    
    支持的格式:
        - "123.5 L × 45.6 W × 7.8 T"（固定顺序）
        - "32.00Tx110.0Lx87.0W"（任意顺序，根据L/W/T标识匹配）
        - "123.5 L 45.6 W 7.8 T"
        - "L 123.5 × W 45.6 × T 7.8"
        - "长123.5×宽45.6×厚7.8"
        - "123.5 × 45.6 × 7.8"
    """
    try:
        msp = doc.modelspace()
        
        # 定义多种可能的尺寸格式模式
        # 固定顺序的模式（保持向后兼容）
        # 注意：使用 [*×xX]+ 来匹配一个或多个分隔符（支持连续两个分隔符）
        fixed_order_patterns = [
            r'(\d+\.?\d*)\s*L\s*[*×xX]+\s*(\d+\.?\d*)\s*W\s*[*×xX]+\s*(\d+\.?\d*)\s*T',
            r'(\d+\.?\d*)\s*L\s+(\d+\.?\d*)\s*W\s+(\d+\.?\d*)\s*T',
            r'L\s*(\d+\.?\d*)\s*[*×xX]+\s*W\s*(\d+\.?\d*)\s*[*×xX]+\s*T\s*(\d+\.?\d*)',
            r'长\s*(\d+\.?\d*)\s*[*×xX]+\s*宽\s*(\d+\.?\d*)\s*[*×xX]+\s*厚\s*(\d+\.?\d*)',
            r'(\d+\.?\d*)\s*[*×xX]+\s*(\d+\.?\d*)\s*[*×xX]+\s*(\d+\.?\d*)',
        ]
        
        all_texts = []
        
        # 提取所有文字实体
        for entity in msp:
            entity_type = entity.dxftype()
            if entity_type not in ['TEXT', 'MTEXT', 'ATTRIB', 'ATTDEF']:
                continue
            
            try:
                if entity_type == 'MTEXT':
                    text_content = entity.text if hasattr(entity, 'text') else entity.dxf.text
                elif entity_type == 'TEXT':
                    text_content = entity.dxf.text
                elif entity_type in ['ATTRIB', 'ATTDEF']:
                    text_content = entity.dxf.text
                else:
                    continue
                
                if not text_content:
                    continue
                
                all_texts.append(text_content)
                
            except Exception:
                continue
        
        # 尝试匹配尺寸信息
        for text_content in all_texts:
            # 策略1: 尝试任意顺序的L/W/T标识匹配（优先级最高）
            result = _extract_flexible_order_dimensions(text_content)
            if result:
                length, width, thickness = result
                if 0 < length < 10000 and 0 < width < 10000 and 0 < thickness < 10000:
                    logging.info(f"成功从文字提取尺寸（任意顺序）: L={length}, W={width}, T={thickness}")
                    return length, width, thickness
            
            # 策略2: 尝试固定顺序的模式匹配
            for pattern in fixed_order_patterns:
                match = re.search(pattern, text_content, re.IGNORECASE)
                if match:
                    length = float(match.group(1))
                    width = float(match.group(2))
                    thickness = float(match.group(3))
                    
                    # 验证数值合理性
                    if 0 < length < 10000 and 0 < width < 10000 and 0 < thickness < 10000:
                        logging.info(f"成功从文字提取尺寸（固定顺序）: L={length}, W={width}, T={thickness}")
                        return length, width, thickness
        
        logging.warning("未找到符合格式的尺寸文字信息，将返回 (0, 0, 0)")
        return None, None, None
        
    except Exception as e:
        logging.error(f"从文字提取尺寸失败: {str(e)}")
        return None, None, None


def _extract_flexible_order_dimensions(text: str) -> Optional[Tuple[float, float, float]]:
    """
    从文本中提取任意顺序的L/W/T尺寸
    
    支持格式:
        - "32.00Tx110.0Lx87.0W"
        - "110.0L x 32.00T x 87.0W"
        - "87.0W * 110.0L * 32.00T"
        - "560L*560W**69.1T"（连续两个分隔符）
        - "560L**560W*69.1T"（连续两个分隔符）
    
    Args:
        text: 文本内容
    
    Returns:
        (length, width, thickness) 或 None
    """
    try:
        # 匹配所有 "数字+L/W/T" 的组合
        # 支持格式: 数字L、数字W、数字T（数字可以有小数点）
        # 注意：这个模式会忽略分隔符，所以连续两个分隔符不影响识别
        pattern = r'(\d+\.?\d*)\s*([LWT])'
        matches = re.findall(pattern, text, re.IGNORECASE)
        
        if not matches:
            return None
        
        # 提取L、W、T对应的值
        dimensions = {}
        for value, label in matches:
            label_upper = label.upper()
            if label_upper in ['L', 'W', 'T']:
                # 如果同一个标签出现多次，使用第一次出现的值
                if label_upper not in dimensions:
                    dimensions[label_upper] = float(value)
        
        # 检查是否包含L、W、T三个维度
        if 'L' in dimensions and 'W' in dimensions and 'T' in dimensions:
            logging.debug(f"任意顺序尺寸提取成功: L={dimensions['L']}, W={dimensions['W']}, T={dimensions['T']}")
            return dimensions['L'], dimensions['W'], dimensions['T']
        
        return None
        
    except Exception as e:
        logging.debug(f"任意顺序尺寸提取失败: {e}")
        return None


def extract_dimensions(doc) -> Tuple[float, float, float]:
    """
    提取尺寸的统一接口
    
    Args:
        doc: ezdxf Document 对象
    
    Returns:
        Tuple[length, width, thickness] - 尺寸（单位：mm）
        如果提取失败，返回 (0.0, 0.0, 0.0)
    
    策略:
        从文字标注中提取，失败时返回 (0, 0, 0)
    """
    # 从文字中提取
    length, width, thickness = extract_dimensions_from_text(doc)
    
    # 如果文字提取失败，返回 (0, 0, 0)
    if length is None or width is None or thickness is None:
        logging.warning("文字提取失败，返回 (0, 0, 0)")
        return 0.0, 0.0, 0.0
    
    return length, width, thickness


if __name__ == "__main__":
    """测试代码"""
    import ezdxf
    
    # 测试示例
    print("尺寸提取模块测试")
    print("=" * 50)
    
    # 这里可以添加测试代码
    # doc = ezdxf.readfile("test.dxf")
    # length, width, thickness = extract_dimensions(doc)
    # print(f"提取的尺寸: L={length}, W={width}, T={thickness}")
