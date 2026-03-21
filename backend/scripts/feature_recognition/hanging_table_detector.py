# -*- coding: utf-8 -*-
"""
挂台识别模块
识别零件中的挂台特征
"""
import logging
from typing import List, Dict, Any, Tuple
import ezdxf


def detect_hanging_table_by_text(all_texts: List[str]) -> int:
    """
    通过文字标注识别挂台
    
    Args:
        all_texts: 所有文本内容列表
    
    Returns:
        int: 1表示有挂台，0表示无挂台
    """
    hanging_keywords = ['挂台', '台阶']
    
    for text in all_texts:
        for keyword in hanging_keywords:
            if keyword in text:
                logging.info(f"✅ 通过文字识别到挂台: {text}")
                return 1
    
    return 0


def detect_hanging_table_by_geometry(doc: ezdxf.document.Drawing, 
                                     length_mm: float, 
                                     width_mm: float, 
                                     thickness_mm: float) -> int:
    """
    通过几何特征识别挂台
    
    挂台的几何特征：
    1. 在侧视图中表现为底部的台阶结构
    2. 台阶由3-4条线段组成，形成"凹"字形或"凸"字形
    3. 台阶高度相对较小（< 零件高度的30%）
    4. 台阶宽度相对较小（< 零件宽度的50%）
    
    Args:
        doc: DXF文档对象
        length_mm: 零件长度
        width_mm: 零件宽度
        thickness_mm: 零件厚度
    
    Returns:
        int: 1表示有挂台，0表示无挂台
    """
    try:
        msp = doc.modelspace()
        
        # 提取所有线段
        lines = _extract_lines(msp)
        
        if not lines:
            logging.info("ℹ️ 未找到线段，无法进行几何识别")
            return 0
        
        # 分类线段
        horizontal_lines = [l for l in lines if l['type'] == 'horizontal']
        vertical_lines = [l for l in lines if l['type'] == 'vertical']
        
        logging.info(f"提取到 {len(horizontal_lines)} 条水平线，{len(vertical_lines)} 条垂直线")
        
        # 查找台阶结构
        step_structures = _find_step_structures(horizontal_lines, vertical_lines)
        
        if not step_structures:
            logging.info("ℹ️ 未找到台阶结构")
            return 0
        
        logging.info(f"找到 {len(step_structures)} 个台阶结构")
        
        # 验证是否为挂台
        for step in step_structures:
            if _is_hanging_table(step, length_mm, width_mm, thickness_mm):
                logging.info(f"✅ 通过几何特征识别到挂台: 高度={step['height']:.2f}mm, 宽度={step['width']:.2f}mm")
                return 1
        
        logging.info("ℹ️ 台阶结构不符合挂台特征")
        return 0
        
    except Exception as e:
        logging.error(f"几何识别失败: {e}")
        return 0


def _extract_lines(msp, tolerance: float = 1.0) -> List[Dict[str, Any]]:
    """
    提取所有线段并分类
    
    Args:
        msp: 模型空间
        tolerance: 容差值
    
    Returns:
        List[Dict]: 线段列表
    """
    lines = []
    
    for entity in msp.query('LINE'):
        try:
            start = entity.dxf.start
            end = entity.dxf.end
            
            # 计算线段方向
            dx = abs(end.x - start.x)
            dy = abs(end.y - start.y)
            
            # 判断是水平线还是垂直线
            is_horizontal = dy < tolerance and dx > tolerance
            is_vertical = dx < tolerance and dy > tolerance
            
            if is_horizontal:
                lines.append({
                    'type': 'horizontal',
                    'start': (min(start.x, end.x), start.y),
                    'end': (max(start.x, end.x), end.y),
                    'length': dx,
                    'y': start.y,
                    'x_min': min(start.x, end.x),
                    'x_max': max(start.x, end.x)
                })
            elif is_vertical:
                lines.append({
                    'type': 'vertical',
                    'start': (start.x, min(start.y, end.y)),
                    'end': (end.x, max(start.y, end.y)),
                    'length': dy,
                    'x': start.x,
                    'y_min': min(start.y, end.y),
                    'y_max': max(start.y, end.y)
                })
                
        except Exception as e:
            continue
    
    return lines


def _find_step_structures(horizontal_lines: List[Dict], 
                          vertical_lines: List[Dict],
                          tolerance: float = 2.0) -> List[Dict]:
    """
    查找台阶结构
    
    台阶结构特征（侧视图）：
    ┌─────────┐
    │         │
    │         │
    ├───┐     │  ← 台阶
    │   │     │
    └───┴─────┘
    
    由以下线段组成：
    - 1条短水平线（台阶顶部）
    - 1条短垂直线（台阶侧面）
    - 可能有底部水平线
    
    Args:
        horizontal_lines: 水平线列表
        vertical_lines: 垂直线列表
        tolerance: 容差值
    
    Returns:
        List[Dict]: 台阶结构列表
    """
    step_structures = []
    
    # 按y坐标对水平线分组
    h_lines_by_y = {}
    for line in horizontal_lines:
        y = round(line['y'], 1)
        if y not in h_lines_by_y:
            h_lines_by_y[y] = []
        h_lines_by_y[y].append(line)
    
    # 查找同一高度有多条水平线的情况（可能是台阶）
    for y, lines_at_y in h_lines_by_y.items():
        if len(lines_at_y) >= 2:
            # 按长度排序
            lines_at_y.sort(key=lambda l: l['length'])
            
            # 检查是否有短线和长线的组合
            for i in range(len(lines_at_y) - 1):
                short_line = lines_at_y[i]
                long_line = lines_at_y[i + 1]
                
                # 短线长度应该明显小于长线
                if short_line['length'] < long_line['length'] * 0.5:
                    # 查找连接短线的垂直线
                    for v_line in vertical_lines:
                        # 检查垂直线是否在短线的端点附近
                        if (abs(v_line['x'] - short_line['x_max']) < tolerance or
                            abs(v_line['x'] - short_line['x_min']) < tolerance):
                            
                            # 检查垂直线是否与短线的y坐标相交
                            if v_line['y_min'] <= y <= v_line['y_max']:
                                step_structures.append({
                                    'short_line': short_line,
                                    'long_line': long_line,
                                    'vertical_line': v_line,
                                    'height': v_line['length'],
                                    'width': short_line['length'],
                                    'y': y
                                })
    
    return step_structures


def _is_hanging_table(step: Dict, 
                     length_mm: float, 
                     width_mm: float, 
                     thickness_mm: float) -> bool:
    """
    验证台阶是否为挂台
    
    挂台特征：
    1. 台阶高度 < 零件高度的30%
    2. 台阶宽度 < 零件宽度的50%
    3. 台阶高度 > 2mm（最小高度）
    4. 台阶宽度 > 3mm（最小宽度）
    
    Args:
        step: 台阶结构
        length_mm: 零件长度
        width_mm: 零件宽度
        thickness_mm: 零件厚度
    
    Returns:
        bool: True表示是挂台
    """
    step_height = step['height']
    step_width = step['width']
    
    # 使用零件的最大尺寸作为参考
    max_dimension = max(length_mm, width_mm, thickness_mm)
    
    # 检查尺寸比例
    # 台阶高度应该相对较小
    if step_height > max_dimension * 0.3:
        logging.debug(f"台阶高度过大: {step_height:.2f}mm > {max_dimension * 0.3:.2f}mm")
        return False
    
    # 台阶宽度应该相对较小
    if step_width > max_dimension * 0.5:
        logging.debug(f"台阶宽度过大: {step_width:.2f}mm > {max_dimension * 0.5:.2f}mm")
        return False
    
    # 检查最小尺寸
    if step_height < 2.0:
        logging.debug(f"台阶高度过小: {step_height:.2f}mm < 2.0mm")
        return False
    
    if step_width < 3.0:
        logging.debug(f"台阶宽度过小: {step_width:.2f}mm < 3.0mm")
        return False
    
    return True


def detect_hanging_table(all_texts: List[str], 
                         doc: ezdxf.document.Drawing = None,
                         length_mm: float = None,
                         width_mm: float = None,
                         thickness_mm: float = None) -> int:
    """
    检测是否有挂台（组合方法）
    
    优先使用文字识别，失败时使用几何识别
    
    Args:
        all_texts: 所有文本内容列表
        doc: DXF文档对象（可选，用于几何识别）
        length_mm: 零件长度（可选，用于几何识别）
        width_mm: 零件宽度（可选，用于几何识别）
        thickness_mm: 零件厚度（可选，用于几何识别）
    
    Returns:
        int: 1表示有挂台，0表示无挂台
    """
    # 方法1：文字识别（优先）
    result = detect_hanging_table_by_text(all_texts)
    if result == 1:
        return 1
    
    # 方法2：几何识别（备用）
    if doc and length_mm and width_mm and thickness_mm:
        logging.info("文字识别未找到挂台，尝试几何识别...")
        result = detect_hanging_table_by_geometry(doc, length_mm, width_mm, thickness_mm)
        if result == 1:
            return 1
    
    logging.info("ℹ️ 未检测到挂台")
    return 0
