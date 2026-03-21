# -*- coding: utf-8 -*-
"""
加工说明提取模块
从 DXF 文件中提取加工说明文本（如 F1, H1, H2, M1 等）
"""

import re
import ezdxf
from typing import Dict, List, Tuple, Optional, Union
import logging


def get_text_content(entity) -> Optional[str]:
    """获取文本实体的内容"""
    try:
        entity_type = entity.dxftype()
        
        if entity_type == 'MTEXT':
            # MTEXT 可能有 text 属性或 dxf.text
            content = entity.text if hasattr(entity, 'text') else entity.dxf.text
        elif entity_type == 'TEXT':
            content = entity.dxf.text
        elif entity_type in ['ATTRIB', 'ATTDEF']:
            content = entity.dxf.text
        else:
            return None
        
        return content if content else None
    except Exception as e:
        logging.debug(f"获取文本内容失败: {e}")
        return None


def get_text_position(entity) -> Optional[Tuple[float, float]]:
    """获取文本实体的位置"""
    try:
        if hasattr(entity.dxf, 'insert'):
            point = entity.dxf.insert
            return (float(point.x), float(point.y))
        elif hasattr(entity.dxf, 'position'):
            point = entity.dxf.position
            return (float(point.x), float(point.y))
    except Exception as e:
        logging.debug(f"获取文本位置失败: {e}")
    return None


def parse_processing_instruction_line(line: str) -> Optional[Tuple[str, str]]:
    """
    解析单行加工说明
    
    支持的格式:
    - F1 上表面铣平,粗糙度Ra 3.2以下
    - H1 2-M12×P1.75螺纹孔,攻丝深度20.0
    - H2 1-M3孔径,4.0±0.02
    - M1 6-M6×P1.0螺纹孔,攻丝深度12.0
    - ZA 1-φ39.0 精铣螺纹孔,倒角
    
    Returns:
        (code, instruction) 元组，如 ('F1', '上表面铣平,粗糙度Ra 3.2以下')
        如果不匹配则返回 None
    """
    line = line.strip()
    if not line:
        return None
    
    # 匹配模式: 代号(字母+数字) + 空格/冒号 + 说明内容
    # 代号格式: 1-2个字母（大小写均可）+ 可选的1-2个数字
    patterns = [
        # 标准格式: F1 说明内容 或 F1: 说明内容 或 F1：说明内容 或 d2: 说明内容
        r'^([A-Za-z]{1,2}\d{0,2})\s*[:：]?\s*(.+)$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, line)
        if match:
            code = match.group(1)
            instruction = match.group(2).strip()
            
            # 验证说明内容不为空且包含中文或常见加工术语
            if instruction and (
                any('\u4e00' <= c <= '\u9fff' for c in instruction) or  # 包含中文
                any(keyword in instruction.lower() for keyword in ['m', 'φ', '±', '×', 'ra', 'rz'])  # 包含加工符号
            ):
                return (code, instruction)
    
    return None


def extract_processing_instructions_from_text(content: str) -> Dict[str, str]:
    """
    从文本内容中提取所有加工说明
    
    Args:
        content: 文本内容，可能包含多行（用 \\P 或 \\n 分隔）
    
    Returns:
        字典，key 为代号（如 'F1'），value 为说明内容
    """
    instructions = {}
    
    if not content:
        return instructions
    
    # 处理 MTEXT 的换行符 \\P 和普通换行符
    lines = content.replace('\\P', '\n').replace('\\p', '\n').split('\n')
    
    for line in lines:
        result = parse_processing_instruction_line(line)
        if result:
            code, instruction = result
            instructions[code] = instruction
    
    return instructions


def is_in_processing_instruction_area(position: Tuple[float, float], doc_bounds: Dict) -> bool:
    """
    判断文本位置是否在加工说明区域
    
    通常加工说明在图纸右侧或右上角
    这里使用简单的启发式规则
    """
    if not position or not doc_bounds:
        return True  # 如果无法判断，默认认为在区域内
    
    x, y = position
    
    # 如果文本在图纸右侧 60% 区域，更可能是加工说明
    width = doc_bounds.get('max_x', 0) - doc_bounds.get('min_x', 0)
    if width > 0:
        x_ratio = (x - doc_bounds.get('min_x', 0)) / width
        if x_ratio > 0.6:  # 右侧 40% 区域
            return True
    
    return True  # 默认都检查


def calculate_doc_bounds(doc) -> Dict:
    """计算文档边界"""
    try:
        msp = doc.modelspace()
        
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        has_entities = False
        
        for entity in msp:
            try:
                if entity.dxftype() == 'LINE':
                    points = [entity.dxf.start, entity.dxf.end]
                elif entity.dxftype() in ['LWPOLYLINE', 'POLYLINE']:
                    points = list(entity.get_points('xyz'))
                elif entity.dxftype() == 'CIRCLE':
                    center = entity.dxf.center
                    radius = entity.dxf.radius
                    points = [
                        (center.x - radius, center.y - radius, 0),
                        (center.x + radius, center.y + radius, 0)
                    ]
                else:
                    continue
                
                for point in points:
                    if isinstance(point, tuple):
                        x, y = point[0], point[1]
                    else:
                        x, y = point.x, point.y
                    
                    min_x = min(min_x, x)
                    max_x = max(max_x, x)
                    min_y = min(min_y, y)
                    max_y = max(max_y, y)
                    has_entities = True
            except:
                continue
        
        if not has_entities:
            return {}
        
        return {
            'min_x': min_x,
            'max_x': max_x,
            'min_y': min_y,
            'max_y': max_y
        }
    except Exception as e:
        logging.error(f"计算文档边界失败: {e}")
        return {}


def parse_processing_instructions_from_texts(texts: List[str]) -> Tuple[Dict[str, str], List[str]]:
    """
    从预提取的文本列表中解析加工说明（优化版，避免重复读取文件）
    
    Args:
        texts: 文本内容列表
    
    Returns:
        Tuple[Dict[str, str], List[str]]: 
            - 字典：key 为代号（如 'F1', 'H1'），value 为说明内容
            - 列表：包含加工说明的完整文本（用于倒角识别时排除）
        
    Example:
        (
            {
                'F1': '上表面铣平,粗糙度Ra 3.2以下',
                'H1': '2-M12×P1.75螺纹孔,攻丝深度20.0',
                'H2': '1-M3孔径,4.0±0.02',
                ...
            },
            [
                'F1 上表面铣平,粗糙度Ra 3.2以下',
                'H1 2-M12×P1.75螺纹孔,攻丝深度20.0',
                'H2 1-M3孔径,4.0±0.02',
                ...
            ]
        )
    """
    try:
        all_instructions = {}
        instruction_full_texts = []  # 新增：保存包含加工说明的完整文本
        instruction_count = 0
        
        # 遍历所有文本
        for content in texts:
            if not content:
                continue
            
            # 提取加工说明
            instructions = extract_processing_instructions_from_text(content)
            
            if instructions:
                instruction_count += len(instructions)
                all_instructions.update(instructions)
                # 如果这个文本包含加工说明，保存完整文本用于排除
                instruction_full_texts.append(content)
                logging.debug(f"从文本中提取到 {len(instructions)} 条加工说明: {list(instructions.keys())}")
        
        logging.info(
            f"加工说明解析完成: 扫描 {len(texts)} 条文本, "
            f"提取到 {instruction_count} 条加工说明, "
            f"去重后 {len(all_instructions)} 条, "
            f"完整文本 {len(instruction_full_texts)} 条"
        )
        
        # 按代号排序
        sorted_instructions = dict(sorted(all_instructions.items()))
        
        return sorted_instructions, instruction_full_texts
        
    except Exception as e:
        logging.error(f"解析加工说明失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {}, []


def extract_processing_instructions(dxf_file_path: str) -> Tuple[Dict[str, str], List[str]]:
    """
    从 DXF 文件中提取所有加工说明（兼容旧接口）
    
    注意：此函数会读取整个文件，建议使用 parse_processing_instructions_from_texts
    
    Args:
        dxf_file_path: DXF 文件路径
    
    Returns:
        Tuple[Dict[str, str], List[str]]: 
            - 字典：key 为代号（如 'F1', 'H1'），value 为说明内容
            - 列表：包含加工说明的完整文本
        
    Example:
        (
            {
                'F1': '上表面铣平,粗糙度Ra 3.2以下',
                'H1': '2-M12×P1.75螺纹孔,攻丝深度20.0',
                'H2': '1-M3孔径,4.0±0.02',
                ...
            },
            [
                'F1 上表面铣平,粗糙度Ra 3.2以下',
                ...
            ]
        )
    """
    try:
        logging.info(f"开始提取加工说明: {dxf_file_path}")
        doc = ezdxf.readfile(dxf_file_path)
        msp = doc.modelspace()
        
        # 收集所有文本
        texts = []
        for entity in msp.query('TEXT MTEXT ATTRIB ATTDEF'):
            content = get_text_content(entity)
            if content:
                texts.append(content)
        
        # 使用新函数解析
        return parse_processing_instructions_from_texts(texts)
        
    except Exception as e:
        logging.error(f"提取加工说明失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {}, []


def format_processing_instructions(instructions: Dict[str, str]) -> str:
    """
    格式化加工说明为可读字符串
    
    Args:
        instructions: 加工说明字典
    
    Returns:
        格式化的字符串
    """
    if not instructions:
        return "无加工说明"
    
    lines = []
    for code, instruction in sorted(instructions.items()):
        lines.append(f"{code}: {instruction}")
    
    return '\n'.join(lines)


# 测试代码
if __name__ == '__main__':
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) < 2:
        print("用法: python processing_instruction_extractor.py <dxf_file_path>")
        sys.exit(1)
    
    dxf_path = sys.argv[1]
    instructions = extract_processing_instructions(dxf_path)
    
    print("\n" + "=" * 80)
    print("加工说明提取结果")
    print("=" * 80)
    print(format_processing_instructions(instructions))
    print("=" * 80)
