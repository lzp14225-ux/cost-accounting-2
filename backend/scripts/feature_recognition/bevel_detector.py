# -*- coding: utf-8 -*-
"""
斜面识别模块
识别零件中的斜面特征
"""
import logging
import ezdxf
import math
import re
from typing import List, Dict, Any, Tuple, Optional


def detect_bevel_by_text(all_texts: List[str], msp) -> List[Tuple[str, Tuple[float, float]]]:
    """
    通过文字标注识别斜面
    
    查找包含"斜面"关键词的文字，返回所有文字位置用于后续计算最近斜线
    
    优先级：
    1. 先检查DXF图纸中的TEXT/MTEXT实体（有精确位置信息）
    2. 如果没找到，再检查all_texts文本列表（使用虚拟位置）
    
    Args:
        all_texts: 所有文本内容列表
        msp: 模型空间
    
    Returns:
        List[Tuple[str, Tuple[float, float]]]: [(文字内容, (x, y)位置), ...]
    """
    bevel_keywords = ['斜面']
    bevel_annotations = []
    
    # 方法1：遍历DXF中的所有文本实体（优先，因为有精确位置）
    for entity in msp.query('TEXT MTEXT'):
        try:
            if entity.dxftype() == 'TEXT':
                text = entity.dxf.text
                position = (entity.dxf.insert.x, entity.dxf.insert.y)
            else:  # MTEXT
                text = entity.text
                position = (entity.dxf.insert.x, entity.dxf.insert.y)
            
            # 检查是否包含"斜面"关键词
            for keyword in bevel_keywords:
                if keyword in text:
                    logging.info(f"✅ 通过DXF文字识别到斜面标注: {text} at ({position[0]:.2f}, {position[1]:.2f})")
                    bevel_annotations.append((text, position))
                    break  # 避免同一文本重复添加
                    
        except Exception:
            continue
    
    # 方法2：如果DXF中没找到，检查all_texts列表（使用虚拟位置）
    if not bevel_annotations and all_texts:
        for i, text in enumerate(all_texts):
            for keyword in bevel_keywords:
                if keyword in text:
                    # 使用虚拟位置（因为文本列表没有位置信息）
                    # 位置设为(0, 0)，后续会匹配所有斜线中最近的
                    virtual_position = (0.0, 0.0)
                    logging.info(f"✅ 通过文本列表识别到斜面标注: {text} (使用虚拟位置)")
                    bevel_annotations.append((text, virtual_position))
                    break  # 避免同一文本重复添加
    
    return bevel_annotations


def detect_bevel_by_angle_annotation(msp) -> List[Tuple[str, Tuple[float, float]]]:
    """
    通过角度标注识别斜面
    
    识别步骤：
    1. 查找所有角度标注（如 38°, 45° 等）
    2. 返回所有标注位置用于后续计算最近斜线
    
    Args:
        msp: 模型空间
    
    Returns:
        List[Tuple[str, Tuple[float, float]]]: [(文字内容, (x, y)位置), ...]
    """
    try:
        # 查找角度标注文字（带度数符号的标注）
        angle_annotations = _find_angle_annotations(msp)
        
        if not angle_annotations:
            logging.info("ℹ️ 未找到角度标注")
            return []
        
        logging.info(f"找到 {len(angle_annotations)} 个角度标注")
        
        # 返回所有角度标注
        result = [(ann['text'], ann['position']) for ann in angle_annotations]
        for text, pos in result:
            logging.info(f"✅ 通过角度标注识别到斜面标注: {text} at ({pos[0]:.2f}, {pos[1]:.2f})")
        
        return result
        
    except Exception as e:
        logging.error(f"角度标注识别失败: {e}")
        return []


def _find_angle_annotations(msp) -> List[Dict[str, Any]]:
    """
    查找角度标注文字
    
    查找带度数符号的标注（如 38°, 45°, 30.5°）
    
    Args:
        msp: 模型空间
    
    Returns:
        List[Dict]: 角度标注列表
    """
    annotations = []
    
    # 正则表达式：匹配数字后面跟度数符号
    angle_pattern = re.compile(r'(\d+(?:\.\d+)?)\s*[°度]')
    
    for entity in msp.query('TEXT MTEXT'):
        try:
            if entity.dxftype() == 'TEXT':
                text = entity.dxf.text
                position = (entity.dxf.insert.x, entity.dxf.insert.y)
            else:  # MTEXT
                text = entity.text
                position = (entity.dxf.insert.x, entity.dxf.insert.y)
            
            # 检查是否是角度标注
            match = angle_pattern.search(text)
            if match:
                value = float(match.group(1))
                annotations.append({
                    'text': text,
                    'value': value,
                    'position': position
                })
                logging.info(f"   找到角度标注: {text} at ({position[0]:.2f}, {position[1]:.2f})")
                
        except Exception:
            continue
    
    return annotations


def _extract_diagonal_lines(msp, angle_tolerance: float = 5.0) -> List[Dict[str, Any]]:
    """
    提取斜线（排除水平和垂直线）
    
    Args:
        msp: 模型空间
        angle_tolerance: 角度容差（度）
    
    Returns:
        List[Dict]: 斜线列表
    """
    diagonal_lines = []
    
    for entity in msp.query('LINE'):
        try:
            start = entity.dxf.start
            end = entity.dxf.end
            
            # 计算线段长度和角度
            dx = end.x - start.x
            dy = end.y - start.y
            length = math.sqrt(dx**2 + dy**2)
            
            if length < 1.0:  # 跳过太短的线段
                continue
            
            # 计算角度
            angle = math.degrees(math.atan2(dy, dx))
            angle = abs(angle) % 180
            
            # 排除水平线和垂直线
            is_horizontal = (angle < angle_tolerance) or (angle > 180 - angle_tolerance)
            is_vertical = (90 - angle_tolerance < angle < 90 + angle_tolerance)
            
            if is_horizontal or is_vertical:
                continue
            
            # 保留斜线
            diagonal_lines.append({
                'start': (start.x, start.y),
                'end': (end.x, end.y),
                'length': length,
                'angle': angle,
                'color': entity.dxf.color if hasattr(entity.dxf, 'color') else None
            })
            
        except Exception:
            continue
    
    return diagonal_lines


def _calculate_nearest_diagonal_line_length(annotation_pos: Tuple[float, float], 
                                           diagonal_lines: List[Dict[str, Any]],
                                           used_lines: set = None) -> Optional[Tuple[float, int]]:
    """
    计算离标注最近的斜线长度
    
    Args:
        annotation_pos: 标注位置 (x, y)
        diagonal_lines: 斜线列表
        used_lines: 已使用的斜线索引集合（避免重复使用）
    
    Returns:
        Optional[Tuple[float, int]]: (最近斜线的长度, 斜线索引)，如果没有斜线返回None
    """
    if not diagonal_lines:
        return None
    
    if used_lines is None:
        used_lines = set()
    
    nearest_line = None
    nearest_index = -1
    min_distance = float('inf')
    
    for i, line in enumerate(diagonal_lines):
        # 跳过已使用的斜线
        if i in used_lines:
            continue
        
        # 计算标注到线段中点的距离
        mid_x = (line['start'][0] + line['end'][0]) / 2
        mid_y = (line['start'][1] + line['end'][1]) / 2
        
        distance = math.sqrt(
            (annotation_pos[0] - mid_x)**2 + 
            (annotation_pos[1] - mid_y)**2
        )
        
        if distance < min_distance:
            min_distance = distance
            nearest_line = line
            nearest_index = i
    
    if nearest_line:
        length = nearest_line['length']
        logging.info(f"   最近的斜线长度: {length:.2f}mm (距离: {min_distance:.2f}mm)")
        return (length, nearest_index)
    
    return None


def _filter_lines_in_views(diagonal_lines: List[Dict[str, Any]], views: Dict) -> List[Dict[str, Any]]:
    """
    过滤斜线 - 只保留在视图内部的斜线
    
    判断逻辑：斜线的中点必须在任一视图的边界内
    
    Args:
        diagonal_lines: 斜线列表
        views: 视图信息字典 {'top_view': {'bounds': {...}}, 'front_view': {...}, 'side_view': {...}}
    
    Returns:
        List[Dict[str, Any]]: 过滤后的斜线列表
    """
    if not views:
        return diagonal_lines
    
    filtered_lines = []
    
    for line in diagonal_lines:
        # 计算斜线中点
        mid_x = (line['start'][0] + line['end'][0]) / 2
        mid_y = (line['start'][1] + line['end'][1]) / 2
        
        # 检查中点是否在任一视图内
        in_view = False
        for view_name, view_data in views.items():
            if view_data and 'bounds' in view_data:
                bounds = view_data['bounds']
                if _point_in_bounds((mid_x, mid_y), bounds):
                    in_view = True
                    logging.debug(f"   斜线中点 ({mid_x:.2f}, {mid_y:.2f}) 在 {view_name} 内")
                    break
        
        if in_view:
            filtered_lines.append(line)
        else:
            logging.debug(f"   斜线中点 ({mid_x:.2f}, {mid_y:.2f}) 不在任何视图内，已过滤")
    
    return filtered_lines


def _point_in_bounds(point: Tuple[float, float], bounds: Dict) -> bool:
    """
    判断点是否在边界内
    
    Args:
        point: 点坐标 (x, y)
        bounds: 边界字典 {'min_x': ..., 'max_x': ..., 'min_y': ..., 'max_y': ...}
    
    Returns:
        bool: True表示在边界内
    """
    x, y = point
    return (bounds['min_x'] <= x <= bounds['max_x'] and
            bounds['min_y'] <= y <= bounds['max_y'])


def detect_bevel(all_texts: List[str], 
                doc: ezdxf.document.Drawing = None,
                views: Dict = None) -> List[float]:
    """
    检测斜面长度（组合方法）- 支持多个斜面
    
    识别步骤：
    1. 查找所有"斜面"文字标注或角度标注（如 38°）
    2. 提取所有斜线
    3. 过滤：只保留在视图内部的斜线
    4. 为每个标注计算离它最近的斜线长度
    5. 返回所有斜面长度的列表
    
    Args:
        all_texts: 所有文本内容列表
        doc: DXF文档对象（必需，用于几何识别）
        views: 视图信息字典 {'top_view': {'bounds': {...}}, 'front_view': {...}, 'side_view': {...}}
    
    Returns:
        List[float]: 斜面长度列表(mm)，未找到标注时返回空列表
    """
    if not doc:
        logging.info("ℹ️ 未提供DXF文档，斜面长度=[]")
        return []
    
    try:
        msp = doc.modelspace()
        
        # 步骤1：查找所有斜面标注（优先查找"斜面"文字）
        bevel_annotations = detect_bevel_by_text(all_texts, msp)
        
        # 如果没有找到"斜面"文字，尝试查找角度标注
        if not bevel_annotations:
            logging.info("未找到'斜面'文字，尝试查找角度标注...")
            bevel_annotations = detect_bevel_by_angle_annotation(msp)
        
        if not bevel_annotations:
            logging.info("ℹ️ 未识别到斜面标注，斜面长度=[]")
            return []
        
        logging.info(f"共识别到 {len(bevel_annotations)} 个斜面标注")
        
        # 步骤2：提取所有斜线
        diagonal_lines = _extract_diagonal_lines(msp)
        
        if not diagonal_lines:
            logging.info("ℹ️ 未找到斜线，斜面长度=[]")
            return []
        
        logging.info(f"找到 {len(diagonal_lines)} 条斜线")
        
        # 步骤3：过滤斜线 - 只保留在视图内部的斜线
        if views:
            filtered_lines = _filter_lines_in_views(diagonal_lines, views)
            logging.info(f"过滤后剩余 {len(filtered_lines)} 条视图内斜线")
            diagonal_lines = filtered_lines
        else:
            logging.warning("⚠️ 未提供视图信息，跳过视图内斜线过滤")
        
        if not diagonal_lines:
            logging.info("ℹ️ 过滤后无可用斜线，斜面长度=[]")
            return []
        
        # 步骤4：为每个标注计算最近的斜线长度
        bevel_lengths = []
        used_lines = set()  # 记录已使用的斜线，避免重复
        
        for i, (annotation_text, annotation_pos) in enumerate(bevel_annotations, 1):
            logging.info(f"处理第 {i} 个斜面标注: {annotation_text}")
            
            result = _calculate_nearest_diagonal_line_length(annotation_pos, diagonal_lines, used_lines)
            
            if result:
                length, line_index = result
                # 四舍五入到两位小数
                length = round(length, 2)
                bevel_lengths.append(length)
                used_lines.add(line_index)  # 标记该斜线已使用
                logging.info(f"   ✅ 斜面 {i} 长度: {length}mm")
            else:
                logging.warning(f"   ⚠️ 斜面 {i} 未找到对应的斜线")
        
        if bevel_lengths:
            # 不在这里打印总结日志，由调用方打印
            return bevel_lengths
        
    except Exception as e:
        logging.error(f"斜面识别失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
    
    # 未找到标注或计算失败
    logging.info("ℹ️ 斜面识别失败，斜面长度=[]")
    return []
