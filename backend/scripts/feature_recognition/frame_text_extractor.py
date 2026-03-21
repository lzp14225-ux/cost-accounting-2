# -*- coding: utf-8 -*-
"""
图框文字提取模块
从 DXF 文件的图框中提取所有文本内容
"""

import re
import ezdxf
from typing import Dict, List, Tuple, Optional, Any
import logging


def get_text_content(entity) -> Optional[str]:
    """获取文本实体的内容"""
    try:
        entity_type = entity.dxftype()
        
        if entity_type == 'MTEXT':
            # MTEXT 可能有 text 属性或 dxf.text
            if hasattr(entity, 'get_text'):
                content = entity.get_text()
            elif hasattr(entity, 'plain_text'):
                content = entity.plain_text()
            elif hasattr(entity, 'text'):
                content = entity.text
            else:
                content = entity.dxf.text
        elif entity_type == 'TEXT':
            content = entity.dxf.text
        elif entity_type in ['ATTRIB', 'ATTDEF']:
            content = entity.dxf.text
        elif entity_type == 'DIMENSION':
            if hasattr(entity, 'get_measurement'):
                content = str(entity.get_measurement())
            else:
                content = entity.dxf.text if hasattr(entity.dxf, 'text') else None
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


# def clean_text_content(content: str) -> str:
#     """清洗文本内容，移除格式化代码"""
#     if not content:
#         return ""
    
#     # 移除 MTEXT 格式化代码
#     content = re.sub(r'\{\\[^}]*\}', '', content)
#     content = re.sub(r'\\[A-Za-z][^;]*;', '', content)
    
#     # 替换特殊符号
#     replacements = {
#         '%%c': 'Φ', '%%C': 'Φ',
#         '%%d': '°', '%%D': '°',
#         '%%p': '±', '%%P': '±',
#         '\\P': '\n', '\\p': '\n'
#     }
#     for old, new in replacements.items():
#         content = content.replace(old, new)
    
#     # 规范化空白字符
#     content = re.sub(r'\s+', ' ', content).strip()
    
#     return content

def clean_text_content(content: str) -> str:
    """清洗文本内容，移除格式化代码"""
    if not content:
        return ""

    # 解码 Unicode 转义序列（如 \U+52a0 -> 加）
    # 这是为了处理从 DWG 转换的 DXF 文件中的中文字符
    if '\\U+' in content or '\\u' in content:
        def decode_unicode_escape(match):
            code = match.group(1)
            try:
                return chr(int(code, 16))
            except:
                return match.group(0)

        # 解码 \U+xxxx 格式（严格 4 位十六进制）
        content = re.sub(r'\\U\+([0-9a-fA-F]{4})', decode_unicode_escape, content)
        # 解码 \uxxxx 格式（严格 4 位十六进制）
        content = re.sub(r'\\u([0-9a-fA-F]{4})', decode_unicode_escape, content)

    # 移除 MTEXT 格式化代码
    content = re.sub(r'\{\\[^}]*\}', '', content)
    content = re.sub(r'\\[A-Za-z][^;]*;', '', content)

    # 替换特殊符号
    replacements = {
        '%%c': 'Φ', '%%C': 'Φ',
        '%%d': '°', '%%D': '°',
        '%%p': '±', '%%P': '±',
        '\\P': '\n', '\\p': '\n'
    }
    for old, new in replacements.items():
        content = content.replace(old, new)

    # 规范化空白字符
    content = re.sub(r'\s+', ' ', content).strip()

    return content


def identify_frame_blocks(doc, msp) -> List[Dict]:
    """识别图框块"""
    frame_blocks = []
    min_frame_size = 120  # 最小图框尺寸
    
    for insert in msp.query('INSERT'):
        try:
            block_name = insert.dxf.name
            insert_point = insert.dxf.insert
            
            # 获取块定义
            block_def = doc.blocks.get(block_name)
            if not block_def:
                continue
            
            # 计算块边界
            bounds = calculate_block_bounds(block_def, insert)
            if not bounds:
                continue
            
            # 验证是否为有效图框
            if bounds['width'] < min_frame_size and bounds['height'] < min_frame_size:
                continue
            
            frame_blocks.append({
                'block_name': block_name,
                'insert_point': (insert_point.x, insert_point.y),
                'bounds': bounds,
                'block_def': block_def,
                'insert_entity': insert
            })
            
        except Exception as e:
            logging.debug(f"处理块 {insert.dxf.name} 失败: {e}")
            continue
    
    # 去除重叠的图框
    frame_blocks = filter_overlapping_frames(frame_blocks)
    
    logging.info(f"识别到 {len(frame_blocks)} 个图框")
    return frame_blocks


def calculate_block_bounds(block_def, insert) -> Optional[Dict]:
    """计算块的边界框"""
    try:
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        has_entities = False
        
        for entity in block_def:
            bounds = get_entity_bounds(entity)
            if bounds:
                has_entities = True
                min_x = min(min_x, bounds['min_x'])
                max_x = max(max_x, bounds['max_x'])
                min_y = min(min_y, bounds['min_y'])
                max_y = max(max_y, bounds['max_y'])
        
        if not has_entities:
            return None
        
        # 应用插入点和缩放
        insert_point = insert.dxf.insert
        scale_x = getattr(insert.dxf, 'xscale', 1.0)
        scale_y = getattr(insert.dxf, 'yscale', 1.0)
        
        return {
            'min_x': insert_point.x + min_x * scale_x,
            'max_x': insert_point.x + max_x * scale_x,
            'min_y': insert_point.y + min_y * scale_y,
            'max_y': insert_point.y + max_y * scale_y,
            'width': (max_x - min_x) * abs(scale_x),
            'height': (max_y - min_y) * abs(scale_y)
        }
    except Exception as e:
        logging.debug(f"计算块边界失败: {e}")
        return None


def get_entity_bounds(entity) -> Optional[Dict]:
    """获取实体的边界框"""
    try:
        entity_type = entity.dxftype()
        
        if entity_type == 'LINE':
            start, end = entity.dxf.start, entity.dxf.end
            return {
                'min_x': min(start.x, end.x),
                'max_x': max(start.x, end.x),
                'min_y': min(start.y, end.y),
                'max_y': max(start.y, end.y)
            }
        
        elif entity_type in ['CIRCLE', 'ARC']:
            center = entity.dxf.center
            radius = entity.dxf.radius
            return {
                'min_x': center.x - radius,
                'max_x': center.x + radius,
                'min_y': center.y - radius,
                'max_y': center.y + radius
            }
        
        elif entity_type in ['LWPOLYLINE', 'POLYLINE']:
            points = list(entity.get_points(format='xy'))
            if points:
                xs, ys = zip(*points)
                return {
                    'min_x': min(xs),
                    'max_x': max(xs),
                    'min_y': min(ys),
                    'max_y': max(ys)
                }
    
    except Exception:
        pass
    
    return None


def filter_overlapping_frames(frame_blocks: List[Dict]) -> List[Dict]:
    """过滤重叠的图框，保留面积最大的"""
    if len(frame_blocks) <= 1:
        return frame_blocks
    
    # 按面积从大到小排序
    frame_blocks.sort(
        key=lambda x: x['bounds']['width'] * x['bounds']['height'],
        reverse=True
    )
    
    unique_frames = [frame_blocks[0]]
    overlap_threshold = 0.5  # 重叠阈值：50%
    
    for candidate in frame_blocks[1:]:
        c_bounds = candidate['bounds']
        is_overlapping = False
        
        for existing in unique_frames:
            e_bounds = existing['bounds']
            
            # 检查是否有重叠
            if (c_bounds['max_x'] > e_bounds['min_x'] and
                c_bounds['min_x'] < e_bounds['max_x'] and
                c_bounds['max_y'] > e_bounds['min_y'] and
                c_bounds['min_y'] < e_bounds['max_y']):
                
                # 计算重叠面积
                overlap_x_min = max(c_bounds['min_x'], e_bounds['min_x'])
                overlap_x_max = min(c_bounds['max_x'], e_bounds['max_x'])
                overlap_y_min = max(c_bounds['min_y'], e_bounds['min_y'])
                overlap_y_max = min(c_bounds['max_y'], e_bounds['max_y'])
                
                overlap_area = (overlap_x_max - overlap_x_min) * (overlap_y_max - overlap_y_min)
                candidate_area = c_bounds['width'] * c_bounds['height']
                
                overlap_ratio = overlap_area / candidate_area if candidate_area > 0 else 0
                
                if overlap_ratio > overlap_threshold:
                    is_overlapping = True
                    break
        
        if not is_overlapping:
            unique_frames.append(candidate)
    
    return unique_frames


def point_in_bounds(point: Tuple[float, float], bounds: Dict) -> bool:
    """判断点是否在边界内"""
    x, y = point
    return (bounds['min_x'] <= x <= bounds['max_x'] and
            bounds['min_y'] <= y <= bounds['max_y'])


def is_valid_text_content(content: str, entity_type: str = None) -> bool:
    """
    判断文本内容是否有效（过滤无用内容）
    
    过滤规则：
    1. 过滤坐标点格式：(x, y, z)
    2. 过滤纯数字（尺寸标注的测量值）
    3. 过滤空白内容
    4. 过滤单个字母或符号（但保留中文单字和加工代号）
    5. 过滤重复的加工代号标注（如果已经有完整说明）
    6. 特殊规则：保留以 'C' 开头的 MTEXT（多行文字）
    
    Args:
        content: 文本内容
        entity_type: 实体类型 ('TEXT', 'MTEXT', 等)
    """
    if not content or not content.strip():
        return False
    
    content = content.strip()
    
    # 特殊规则：保留以 'C' 开头的 MTEXT（多行文字）
    # 例如：C3, C10 等，如果是 MTEXT 类型则保留
    if entity_type == 'MTEXT' and content.startswith('C'):
        return True
    
    # 过滤坐标点格式：(数字, 数字, 数字)
    if re.match(r'^\([0-9\.\-\+e, ]+\)$', content):
        return False
    
    # 过滤纯数字（包括小数）
    if re.match(r'^[0-9\.\-\+]+$', content):
        return False
    
    # 过滤单个字母或单个符号（但保留中文单字）
    if len(content) == 1 and not re.match(r'[\u4e00-\u9fa5]', content):
        return False
    
    # 过滤只包含空格、逗号、括号等符号的内容
    if re.match(r'^[\s,\(\)\[\]\{\}\.\-\+]+$', content):
        return False
    
    # 过滤单独的加工代号标注（如 "M2", "W1", "M", "L", "C10", "M32" 等）
    # 这些通常是标注位置，而不是实际的加工说明内容
    # 保留带有冒号或详细说明的内容（如 "M2 :1 -M8,Φ9.0钻穿"）
    # 匹配规则：1个大写字母 + 0-2个字母或数字（总长度1-3个字符）
    if re.match(r'^[A-Z][A-Z0-9]{0,2}$', content):
        # 单独的字母或字母+数字组合，可能是重复标注
        return False
    
    return True


def parse_frame_texts_from_extracted(
    text_data: Dict[str, Any], 
    doc
) -> Dict[str, List[Dict]]:
    """
    从预提取的文本数据中解析图框文本（优化版，避免重复读取文件）
    
    Args:
        text_data: extract_all_texts() 返回的文本数据
        doc: ezdxf Document 对象（用于识别图框）
    
    Returns:
        字典，key 为图框编号，value 为文本列表
        {
            'frame_1': [
                {'content': '文本内容', 'position': (x, y), 'type': 'TEXT'},
                ...
            ],
            ...
        }
    """
    try:
        msp = doc.modelspace()
        
        # 识别图框
        frame_blocks = identify_frame_blocks(doc, msp)
        
        if not frame_blocks:
            logging.warning("未识别到图框，将返回所有文本")
            # 如果没有图框，返回所有文本
            all_texts = []
            for i, text in enumerate(text_data['texts']):
                all_texts.append({
                    'content': text,
                    'position': text_data['positions'][i],
                    'type': text_data['types'][i],
                    'layer': text_data['layers'][i]
                })
            return {'all_texts': all_texts}
        
        # 提取每个图框中的文本
        frame_texts = {}
        
        for i, frame in enumerate(frame_blocks, 1):
            frame_id = f"frame_{i}"
            bounds = frame['bounds']
            
            # 从预提取的文本中筛选图框内的文本
            texts = []
            for j, text in enumerate(text_data['texts']):
                position = text_data['positions'][j]
                
                # 检查文本是否在图框内
                if point_in_bounds(position, bounds):
                    texts.append({
                        'content': text,
                        'position': position,
                        'type': text_data['types'][j],
                        'layer': text_data['layers'][j]
                    })
            
            frame_texts[frame_id] = texts
            logging.info(f"图框 {frame_id} 提取到 {len(texts)} 条有效文本")
        
        return frame_texts
        
    except Exception as e:
        logging.error(f"解析图框文字失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {}


def extract_frame_texts(dxf_file_path: str) -> Dict[str, List[Dict]]:
    """
    从 DXF 文件的图框中提取所有文本（兼容旧接口）
    
    注意：此函数会读取整个文件，建议使用 parse_frame_texts_from_extracted
    
    Args:
        dxf_file_path: DXF 文件路径
    
    Returns:
        字典，key 为图框编号，value 为文本列表
        {
            'frame_1': [
                {'content': '文本内容', 'position': (x, y), 'type': 'TEXT'},
                ...
            ],
            ...
        }
    """
    try:
        logging.info(f"开始提取图框文字: {dxf_file_path}")
        doc = ezdxf.readfile(dxf_file_path)
        msp = doc.modelspace()
        
        # 识别图框
        frame_blocks = identify_frame_blocks(doc, msp)
        
        if not frame_blocks:
            logging.warning("未识别到图框，将提取所有文本")
            # 如果没有图框，提取所有文本
            all_texts = extract_all_texts(msp)
            return {'all_texts': all_texts}
        
        # 提取每个图框中的文本
        frame_texts = {}
        
        for i, frame in enumerate(frame_blocks, 1):
            frame_id = f"frame_{i}"
            bounds = frame['bounds']
            
            # 提取图框内的文本
            texts = []
            
            # 遍历所有文本实体
            for entity in msp.query('TEXT MTEXT ATTRIB ATTDEF DIMENSION'):
                content = get_text_content(entity)
                if not content:
                    continue
                
                position = get_text_position(entity)
                if not position:
                    continue
                
                # 检查文本是否在图框内
                if point_in_bounds(position, bounds):
                    cleaned_content = clean_text_content(content)
                    entity_type = entity.dxftype()
                    
                    # 调试日志：记录所有文本的处理过程
                    if cleaned_content and (cleaned_content.startswith('C') and len(cleaned_content) <= 3):
                        logging.info(f"[DEBUG] 图框内文本: '{cleaned_content}' (type={entity_type}, pos={position})")
                    
                    # 验证内容是否有效（过滤坐标点和纯数字）
                    if cleaned_content and is_valid_text_content(cleaned_content, entity_type):
                        texts.append({
                            'content': cleaned_content,
                            'position': position,
                            'type': entity_type,
                            'layer': getattr(entity.dxf, 'layer', '0')
                        })
                else:
                    # 调试日志：记录图框外的文本
                    cleaned_content = clean_text_content(content)
                    if cleaned_content and (cleaned_content.startswith('C') and len(cleaned_content) <= 3):
                        logging.info(f"[DEBUG] 图框外文本（已过滤）: '{cleaned_content}' (pos={position}, bounds={bounds})")
            
            frame_texts[frame_id] = texts
            logging.info(f"图框 {frame_id} 提取到 {len(texts)} 条有效文本")
        
        return frame_texts
        
    except Exception as e:
        logging.error(f"提取图框文字失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {}


def extract_all_texts(msp) -> List[Dict]:
    """提取模型空间中的所有文本"""
    texts = []
    
    for entity in msp.query('TEXT MTEXT ATTRIB ATTDEF DIMENSION'):
        content = get_text_content(entity)
        if not content:
            continue
        
        position = get_text_position(entity)
        if not position:
            continue
        
        cleaned_content = clean_text_content(content)
        entity_type = entity.dxftype()
        
        # 验证内容是否有效（过滤坐标点和纯数字）
        if cleaned_content and is_valid_text_content(cleaned_content, entity_type):
            texts.append({
                'content': cleaned_content,
                'position': position,
                'type': entity_type,
                'layer': getattr(entity.dxf, 'layer', '0')
            })
    
    return texts


def format_frame_texts(frame_texts: Dict[str, List[Dict]]) -> str:
    """
    格式化图框文本为可读字符串
    
    Args:
        frame_texts: 图框文本字典
    
    Returns:
        格式化的字符串
    """
    if not frame_texts:
        return "无文本"
    
    lines = []
    for frame_id, texts in frame_texts.items():
        lines.append(f"\n{frame_id} ({len(texts)} 条文本):")
        lines.append("-" * 60)
        
        for i, text in enumerate(texts, 1):
            content = text['content']
            position = text['position']
            text_type = text['type']
            lines.append(f"{i:3d}. [{text_type:10s}] {content}")
            lines.append(f"      位置: ({position[0]:.2f}, {position[1]:.2f})")
    
    return '\n'.join(lines)


# 测试代码
if __name__ == '__main__':
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) < 2:
        print("用法: python frame_text_extractor.py <dxf_file_path>")
        sys.exit(1)
    
    dxf_path = sys.argv[1]
    frame_texts = extract_frame_texts(dxf_path)
    
    print("\n" + "=" * 80)
    print("图框文字提取结果")
    print("=" * 80)
    print(format_frame_texts(frame_texts))
    print("=" * 80)
