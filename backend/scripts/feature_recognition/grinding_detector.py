      
# -*- coding: utf-8 -*-
"""
研磨识别模块
通过识别特定的块（BLOCK）并计算插入点之间的距离来确定研磨面数
"""
import logging
import ezdxf
from typing import Optional


def detect_grinding_faces(doc: ezdxf.document.Drawing = None, 
                         length_mm: float = None,
                         width_mm: float = None,
                         thickness_mm: float = None) -> int:
    """
    识别研磨面数
    
    支持两种识别方式：
    1. 通过特定的块名称（如 XYMFH-A）并计算插入点之间的距离
    2. 通过块内部的几何特征（5个尖角的锯齿波形）
    
    规则：
    - 找到所有研磨标记块
    - 计算同一水平线或垂直线上的标记块插入点之间的距离
    - 距离 ≈ 长度(L) → 左右两面研磨
    - 距离 ≈ 宽度(W) → 前后两面研磨
    - 距离 ≈ 厚度(T) → 上下两面研磨
    - 或者：块内部包含5个尖角的锯齿波形 → 研磨符号
    - 结果只能是：0面、2面、4面或6面
    
    Args:
        doc: DXF文档对象（必需）
        length_mm: 零件长度
        width_mm: 零件宽度
        thickness_mm: 零件厚度
    
    Returns:
        int: 研磨面数（0, 2, 4, 6），未找到时返回0
    """
    if not doc:
        logging.info("ℹ️ 未提供DXF文档，研磨面数=0")
        return 0
    
    try:
        msp = doc.modelspace()
        
        # 目标块名称列表（可能有多种命名）
        target_block_names = [
            'XYMFH-A',  # 从图片中看到的块名
            'XYMFH',
            'XYMFH-A0',
            '研磨标记',
            '磨削标记'
        ]
        
        # 收集所有研磨标记块的位置
        grinding_blocks = []
        
        # 收集包含5个尖角的块（新增）
        grinding_blocks_by_geometry = []
        
        # 遍历所有INSERT实体（块引用）
        for entity in msp.query('INSERT'):
            try:
                block_name = entity.dxf.name
                position = entity.dxf.insert
                
                # 方法1：检查是否是目标块名称
                if block_name in target_block_names:
                    grinding_blocks.append({
                        'name': block_name,
                        'x': position.x,
                        'y': position.y
                    })
                
                # 方法2：检查块内部是否包含5个尖角的锯齿波形（新增）
                else:
                    # 获取块定义
                    try:
                        block_def = doc.blocks.get(block_name)
                        if block_def:
                            # 检查块内部的几何特征（支持嵌套块）
                            grinding_info = check_block_for_grinding_pattern(block_def, doc)
                            if grinding_info['is_grinding']:
                                grinding_blocks_by_geometry.append({
                                    'name': block_name,
                                    'x': position.x,
                                    'y': position.y
                                })
                    except Exception as e:
                        logging.debug(f"检查块 {block_name} 的几何特征失败: {e}")
                    
            except Exception as e:
                logging.debug(f"处理块引用失败: {e}")
                continue
        
        # 合并通过几何特征识别的块到主列表
        if grinding_blocks_by_geometry:
            grinding_blocks.extend(grinding_blocks_by_geometry)
        
        # 方法3：直接在模型空间中查找多段线形式的研磨符号
        grinding_polylines = []
        polylines = list(msp.query('POLYLINE')) + list(msp.query('LWPOLYLINE'))
        
        for idx, polyline in enumerate(polylines):
            try:
                # 获取多段线的所有顶点
                points = list(polyline.get_points('xy'))
                
                if len(points) < 6:  # 至少6个点
                    continue
                
                # 检查是否是研磨符号（三个相同的三角形）
                grinding_info = is_grinding_symbol_pattern(points)
                
                if grinding_info['is_grinding'] and grinding_info['first_peak_pos']:
                    # 使用代表顶点作为位置
                    peak_x, peak_y = grinding_info['first_peak_pos']
                    
                    grinding_polylines.append({
                        'name': f'POLYLINE_{idx}',
                        'x': peak_x,
                        'y': peak_y
                    })
                    
            except Exception as e:
                logging.debug(f"处理多段线 #{idx} 失败: {e}")
                continue
        
        # 方法4：直接在模型空间中查找由LINE组成的研磨符号
        # 收集所有LINE实体，尝试识别研磨符号
        lines = list(msp.query('LINE'))
        
        if len(lines) >= 6:
            try:
                # 尝试将LINE实体分组为可能的研磨符号
                # 简化方案：提取所有LINE的端点，然后识别
                points = extract_points_from_lines(lines)
                
                if len(points) >= 6:
                    grinding_info = is_grinding_symbol_pattern(points)
                    
                    if grinding_info['is_grinding'] and grinding_info['first_peak_pos']:
                        peak_x, peak_y = grinding_info['first_peak_pos']
                        
                        grinding_polylines.append({
                            'name': 'LINES_GROUP',
                            'x': peak_x,
                            'y': peak_y
                        })
            except Exception as e:
                logging.debug(f"处理LINE实体失败: {e}")
        
        # 合并多段线识别结果到主列表
        if grinding_polylines:
            grinding_blocks.extend(grinding_polylines)
        
        # 统计识别到的研磨符号总数
        total_symbols = len(grinding_blocks)
        if total_symbols > 0:
            logging.info(f"✅ 共识别到 {total_symbols} 个研磨符号")
        
        if not grinding_blocks:
            logging.info("ℹ️ 未找到研磨标记（块或多段线），研磨面数=0")
            return 0
        
        # 如果没有尺寸信息，无法判断距离匹配
        if not all([length_mm, width_mm, thickness_mm]):
            logging.warning("⚠️ 缺少尺寸信息，无法判断研磨面数，返回0")
            return 0
        
        # 计算标记块之间的距离，判断研磨的面
        grinding_pairs = identify_grinding_pairs(
            grinding_blocks, length_mm, width_mm, thickness_mm
        )
        
        # 统计研磨面数
        grinding_count = len(grinding_pairs) * 2  # 每对标记代表2个面
        
        # 限制在合理范围内（0, 2, 4, 6）
        if grinding_count > 6:
            grinding_count = 6
        
        logging.info(f"✅ 研磨识别完成: {grinding_count}面研磨")
        
        return grinding_count
            
    except Exception as e:
        logging.error(f"研磨识别失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return 0


def check_block_for_grinding_pattern(block_def, doc=None) -> dict:
    """
    检查块定义中是否包含研磨符号（支持嵌套块）
    
    Args:
        block_def: 块定义对象
        doc: DXF文档对象（用于查找嵌套块）
    
    Returns:
        dict: {'is_grinding': bool, 'direction': str, 'triangles': int, 'first_peak_pos': tuple}
    """
    try:
        # 方法1：查找块内的所有POLYLINE和LWPOLYLINE
        polylines = list(block_def.query('POLYLINE')) + list(block_def.query('LWPOLYLINE'))
        
        for polyline in polylines:
            try:
                points = list(polyline.get_points('xy'))
                
                if len(points) >= 6:
                    # 检查是否是研磨符号
                    grinding_info = is_grinding_symbol_pattern(points)
                    if grinding_info['is_grinding']:
                        return grinding_info
            except Exception as e:
                logging.debug(f"检查块内多段线失败: {e}")
                continue
        
        # 方法2：如果没有找到多段线，尝试从LINE实体构建顶点列表
        lines = list(block_def.query('LINE'))
        
        if len(lines) >= 6:  # 至少需要6条线段才能形成3个三角形
            try:
                # 从LINE实体提取所有端点
                points = extract_points_from_lines(lines)
                
                if len(points) >= 6:
                    # 检查是否是研磨符号
                    grinding_info = is_grinding_symbol_pattern(points)
                    if grinding_info['is_grinding']:
                        logging.debug(f"通过LINE实体识别到研磨符号")
                        return grinding_info
            except Exception as e:
                logging.debug(f"从LINE实体提取顶点失败: {e}")
        
        # 方法3：检查嵌套块（递归）
        if doc:
            inserts = list(block_def.query('INSERT'))
            for insert in inserts:
                try:
                    nested_block_name = insert.dxf.name
                    nested_block_def = doc.blocks.get(nested_block_name)
                    
                    # 递归检查嵌套块
                    nested_result = check_block_for_grinding_pattern(nested_block_def, doc)
                    if nested_result['is_grinding']:
                        logging.debug(f"在嵌套块 {nested_block_name} 中识别到研磨符号")
                        return nested_result
                except Exception as e:
                    logging.debug(f"检查嵌套块失败: {e}")
                    continue
        
        return {'is_grinding': False, 'direction': 'unknown', 'triangles': 0, 'first_peak_pos': None}
        
    except Exception as e:
        logging.debug(f"检查块几何特征失败: {e}")
        return {'is_grinding': False, 'direction': 'unknown', 'triangles': 0, 'first_peak_pos': None}


def extract_points_from_lines(lines: list) -> list:
    """
    从LINE实体列表中提取顶点，构建连续的顶点序列
    
    Args:
        lines: LINE实体列表
    
    Returns:
        list: 顶点列表 [(x1, y1), (x2, y2), ...]
    """
    if not lines:
        return []
    
    try:
        # 收集所有端点
        all_points = []
        for line in lines:
            try:
                start = line.dxf.start
                end = line.dxf.end
                all_points.append((start.x, start.y))
                all_points.append((end.x, end.y))
            except Exception as e:
                logging.debug(f"提取LINE端点失败: {e}")
                continue
        
        if not all_points:
            return []
        
        # 去重：如果两个点非常接近（距离<0.01），认为是同一个点
        unique_points = []
        tolerance = 0.01
        
        for point in all_points:
            is_duplicate = False
            for existing_point in unique_points:
                dx = abs(point[0] - existing_point[0])
                dy = abs(point[1] - existing_point[1])
                if dx < tolerance and dy < tolerance:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                unique_points.append(point)
        
        # 尝试按连接顺序排序（简化版：按X坐标或Y坐标排序）
        # 判断是水平还是垂直方向
        x_coords = [p[0] for p in unique_points]
        y_coords = [p[1] for p in unique_points]
        x_range = max(x_coords) - min(x_coords)
        y_range = max(y_coords) - min(y_coords)
        
        if x_range > y_range:
            # 水平方向：按X坐标排序
            unique_points.sort(key=lambda p: p[0])
        else:
            # 垂直方向：按Y坐标排序（从上到下）
            unique_points.sort(key=lambda p: -p[1])
        
        return unique_points
        
    except Exception as e:
        logging.debug(f"从LINE实体提取顶点失败: {e}")
        return []


def identify_grinding_pairs(grinding_blocks: list, 
                            length_mm: float, 
                            width_mm: float, 
                            thickness_mm: float) -> list:
    """
    识别研磨标记块对，判断研磨的面（改进版）
    
    规则：
    - 同一水平线（Y坐标相近）上的两个标记，插入点距离 ≈ 长度 → 左右面
    - 同一水平线（Y坐标相近）上的两个标记，插入点距离 ≈ 宽度 → 前后面
    - 同一垂直线（X坐标相近）上的两个标记，插入点距离 ≈ 厚度 → 上下面
    
    改进点：
    - 返回列表而不是字典，支持同一方向的多对研磨符号
    - 避免重复配对（使用已配对标记）
    
    Args:
        grinding_blocks: 研磨标记块列表（包含 x, y 位置）
        length_mm: 零件长度
        width_mm: 零件宽度
        thickness_mm: 零件厚度
    
    Returns:
        list: 研磨对列表，每个元素包含 {'blocks': [...], 'distance': ..., 'dimension': ...}
    """
    tolerance = 1  # 距离匹配容差（1mm）
    alignment_tolerance = 15.0  # 对齐容差（判断是否在同一直线上，15mm）
    
    logging.info(f"🔍 开始识别研磨对: L={length_mm}, W={width_mm}, T={thickness_mm}")
    logging.info(f"   容差设置: 距离匹配={tolerance}mm, 对齐={alignment_tolerance}mm")
    
    grinding_pairs = []
    used_indices = set()  # 记录已配对的研磨符号索引，避免重复配对
    
    # 遍历所有标记块对
    for i, block1 in enumerate(grinding_blocks):
        if i in used_indices:
            continue
            
        for j, block2 in enumerate(grinding_blocks[i+1:], start=i+1):
            if j in used_indices:
                continue
                
            x1, y1 = block1['x'], block1['y']
            x2, y2 = block2['x'], block2['y']
            
            # 计算插入点之间的距离
            dx = abs(x2 - x1)
            dy = abs(y2 - y1)
            
            # 判断是否在同一水平线上（Y坐标相近）
            if dy < alignment_tolerance:
                # 水平方向：使用 dx 作为距离
                distance = dx
                
                # 检查距离是否匹配长度（左右面）
                diff_length = abs(distance - length_mm)
                if diff_length < tolerance:
                    grinding_pairs.append({
                        'blocks': [block1, block2],
                        'distance': distance,
                        'dimension': 'length',
                        'direction': 'left_right'
                    })
                    used_indices.add(i)
                    used_indices.add(j)
                    logging.info(
                        f"   ✓ 识别到左右面研磨: 块对{i}-{j}, 距离={distance:.2f}mm ≈ 长度={length_mm:.2f}mm"
                    )
                    break  # 找到配对后跳出内层循环
                
                # 检查距离是否匹配宽度（前后面）
                diff_width = abs(distance - width_mm)
                if diff_width < tolerance:
                    grinding_pairs.append({
                        'blocks': [block1, block2],
                        'distance': distance,
                        'dimension': 'width',
                        'direction': 'front_back'
                    })
                    used_indices.add(i)
                    used_indices.add(j)
                    logging.info(
                        f"   ✓ 识别到前后面研磨: 块对{i}-{j}, 距离={distance:.2f}mm ≈ 宽度={width_mm:.2f}mm"
                    )
                    break
                
                # 检查距离是否匹配厚度（上下面）
                diff_thickness = abs(distance - thickness_mm)
                if diff_thickness < tolerance:
                    grinding_pairs.append({
                        'blocks': [block1, block2],
                        'distance': distance,
                        'dimension': 'thickness',
                        'direction': 'top_bottom'
                    })
                    used_indices.add(i)
                    used_indices.add(j)
                    logging.info(
                        f"   ✓ 识别到上下面研磨: 块对{i}-{j}, 距离={distance:.2f}mm ≈ 厚度={thickness_mm:.2f}mm"
                    )
                    break
            
            # 判断是否在同一垂直线上（X坐标相近）
            elif dx < alignment_tolerance:
                # 垂直方向：使用 dy 作为距离
                distance = dy
                
                # 检查距离是否匹配厚度（上下面）
                if abs(distance - thickness_mm) < tolerance:
                    grinding_pairs.append({
                        'blocks': [block1, block2],
                        'distance': distance,
                        'dimension': 'thickness',
                        'direction': 'top_bottom'
                    })
                    used_indices.add(i)
                    used_indices.add(j)
                    logging.info(
                        f"   ✓ 识别到上下面研磨: 块对{i}-{j}, 距离={distance:.2f}mm ≈ 厚度={thickness_mm:.2f}mm"
                    )
                    break
                
                # 检查距离是否匹配宽度（前后面）
                if abs(distance - width_mm) < tolerance:
                    grinding_pairs.append({
                        'blocks': [block1, block2],
                        'distance': distance,
                        'dimension': 'width',
                        'direction': 'front_back'
                    })
                    used_indices.add(i)
                    used_indices.add(j)
                    logging.info(
                        f"   ✓ 识别到前后面研磨: 块对{i}-{j}, 距离={distance:.2f}mm ≈ 宽度={width_mm:.2f}mm"
                    )
                    break
                
                # 检查距离是否匹配长度（左右面）
                if abs(distance - length_mm) < tolerance:
                    grinding_pairs.append({
                        'blocks': [block1, block2],
                        'distance': distance,
                        'dimension': 'length',
                        'direction': 'left_right'
                    })
                    used_indices.add(i)
                    used_indices.add(j)
                    logging.info(
                        f"   ✓ 识别到左右面研磨: 块对{i}-{j}, 距离={distance:.2f}mm ≈ 长度={length_mm:.2f}mm"
                    )
                    break
    
    return grinding_pairs


def get_grinding_symbol_reference_point(points: list, direction: str) -> tuple:
    """
    获取研磨符号的代表顶点位置
    
    逻辑：
    1. 研磨符号有两条线：一条顶点多（锯齿线），一条顶点少（基线）
    2. 选择顶点少的那条线
    3. 在这条线上选择：
       - 水平锯齿：选左边的顶点（X最小）
       - 垂直锯齿：选上边的顶点（Y最大）
    
    Args:
        points: 顶点列表 [(x1, y1), (x2, y2), ...]
        direction: 'horizontal' 或 'vertical'
    
    Returns:
        tuple: (x, y) 代表顶点的坐标
    """
    if not points:
        return None
    
    try:
        x_coords = [p[0] for p in points]
        y_coords = [p[1] for p in points]
        
        if direction == 'horizontal':
            # 水平锯齿：顶点分布在Y方向的两条线上
            y_max = max(y_coords)
            y_min = min(y_coords)
            
            # 容差：20%的高度范围
            height = y_max - y_min
            tolerance = max(height * 0.2, 1.0)
            
            # 找到顶部线和底部线上的点
            top_points = [p for p in points if abs(p[1] - y_max) < tolerance]
            bottom_points = [p for p in points if abs(p[1] - y_min) < tolerance]
            
            # 选择顶点少的那条线
            if len(top_points) <= len(bottom_points):
                # 顶部线顶点少，选择左边的点（X最小）
                reference_point = min(top_points, key=lambda p: p[0])
            else:
                # 底部线顶点少，选择左边的点（X最小）
                reference_point = min(bottom_points, key=lambda p: p[0])
            
            return reference_point
            
        else:  # vertical
            # 垂直锯齿：顶点分布在X方向的两条线上
            x_max = max(x_coords)
            x_min = min(x_coords)
            
            # 容差：20%的宽度范围
            width = x_max - x_min
            tolerance = max(width * 0.2, 1.0)
            
            # 找到左侧线和右侧线上的点
            left_points = [p for p in points if abs(p[0] - x_min) < tolerance]
            right_points = [p for p in points if abs(p[0] - x_max) < tolerance]
            
            # 选择顶点少的那条线
            if len(left_points) <= len(right_points):
                # 左侧线顶点少，选择上边的点（Y最大）
                reference_point = max(left_points, key=lambda p: p[1])
            else:
                # 右侧线顶点少，选择上边的点（Y最大）
                reference_point = max(right_points, key=lambda p: p[1])
            
            return reference_point
            
    except Exception as e:
        logging.debug(f"获取研磨符号代表顶点失败: {e}")
        return None


def is_grinding_symbol_pattern(points: list) -> dict:
    """
    基于"三个相同三角形"的几何特征识别研磨符号（改进版）
    
    核心逻辑：
    1. 识别所有三角形（尖角）
    2. 判断三角形是否相似（高度/宽度相近）
    3. 组合判断：
       - 标准情况：至少3个相似的三角形 → 识别
       - 特殊情况：总共有3个三角形，其中至少2个相似 → 也识别
    4. 三角形方向一致
    
    改进点：
    - 解决"2个对齐+1个不对齐"的情况（如PU-04）
    - 不会误识别只有2个三角形的情况
    - 保持对标准研磨符号的识别能力
    
    Args:
        points: 顶点列表 [(x1, y1), (x2, y2), ...]
    
    Returns:
        dict: {
            'is_grinding': bool, 
            'direction': str, 
            'triangles': int,
            'first_peak_pos': tuple  # 第一个三角形顶点的位置 (x, y)
        }
    """
    if len(points) < 6:  # 至少需要6个点（3个三角形的尖角）
        return {'is_grinding': False, 'direction': 'unknown', 'triangles': 0, 'first_peak_pos': None}
    
    try:
        # 检测水平方向的三角形（Y方向的尖角）
        horizontal_triangles = detect_triangles(points, 'horizontal')
        
        # 检测垂直方向的三角形（X方向的尖角）
        vertical_triangles = detect_triangles(points, 'vertical')
        
        # 统计相似三角形数量
        h_similar = count_similar_triangles(horizontal_triangles)
        v_similar = count_similar_triangles(vertical_triangles)
        
        # 统计总三角形数量
        h_total = len(horizontal_triangles)
        v_total = len(vertical_triangles)
        
        # 组合判断逻辑（关键改进）：
        # 1. 标准情况：至少3个相似 → 识别
        # 2. 特殊情况：总共有3个，其中至少2个相似 → 也识别
        # 这样可以识别"2个对齐+1个不对齐"的情况，同时不会误识别只有2个三角形的情况
        h_valid = (h_similar >= 3) or (h_total >= 3 and h_similar >= 2)
        v_valid = (v_similar >= 3) or (v_total >= 3 and v_similar >= 2)
        
        if h_valid and h_similar > v_similar:
            # 获取水平锯齿的代表顶点位置
            reference_point = get_grinding_symbol_reference_point(points, 'horizontal')
            
            return {
                'is_grinding': True,
                'direction': 'horizontal',
                'triangles': h_similar,
                'first_peak_pos': reference_point
            }
        elif v_valid:
            # 获取垂直锯齿的代表顶点位置
            reference_point = get_grinding_symbol_reference_point(points, 'vertical')
            
            return {
                'is_grinding': True,
                'direction': 'vertical',
                'triangles': v_similar,
                'first_peak_pos': reference_point
            }
        
        return {'is_grinding': False, 'direction': 'unknown', 'triangles': 0, 'first_peak_pos': None}
        
    except Exception as e:
        logging.debug(f"识别研磨符号失败: {e}")
        return {'is_grinding': False, 'direction': 'unknown', 'triangles': 0, 'first_peak_pos': None}


def detect_triangles(points: list, direction: str) -> list:
    """
    检测指定方向上的所有三角形
    
    三角形定义：一个尖角点 + 前后两个基准点
    
    Args:
        points: 顶点列表
        direction: 'horizontal' 或 'vertical'
    
    Returns:
        list: 三角形列表，每个三角形包含 {'peak_index', 'height', 'width', 'type'}
    """
    triangles = []
    
    if len(points) < 3:
        return triangles
    
    try:
        x_coords = [p[0] for p in points]
        y_coords = [p[1] for p in points]
        
        if direction == 'horizontal':
            # 水平方向：检测Y方向的尖角
            coords = y_coords
            other_coords = x_coords
        else:
            # 垂直方向：检测X方向的尖角
            coords = x_coords
            other_coords = y_coords
        
        # 查找所有局部极值点（尖角）
        for i in range(1, len(coords) - 1):
            prev_val = coords[i-1]
            curr_val = coords[i]
            next_val = coords[i+1]
            
            # 判断是否是尖角（局部极值）
            is_peak = False
            peak_type = None
            
            # 向上/向右的尖角（局部最大值）
            if curr_val > prev_val and curr_val > next_val:
                is_peak = True
                peak_type = 'max'
                # 三角形高度
                height = min(curr_val - prev_val, curr_val - next_val)
            
            # 向下/向左的尖角（局部最小值）
            elif curr_val < prev_val and curr_val < next_val:
                is_peak = True
                peak_type = 'min'
                # 三角形高度
                height = min(prev_val - curr_val, next_val - curr_val)
            
            if is_peak and height > 0.1:  # 高度至少0.1mm
                # 三角形宽度（基准线长度）
                width = abs(other_coords[i+1] - other_coords[i-1])
                
                triangles.append({
                    'peak_index': i,
                    'height': height,
                    'width': width,
                    'type': peak_type,
                    'peak_value': curr_val
                })
        
        return triangles
        
    except Exception as e:
        logging.debug(f"检测三角形失败: {e}")
        return []


def count_similar_triangles(triangles: list) -> int:
    """
    统计相似三角形的数量
    
    相似标准：
    1. 高度相近（误差 < 30%）
    2. 宽度相近（误差 < 30%）
    3. 类型相同（都是max或都是min）
    
    Args:
        triangles: 三角形列表
    
    Returns:
        int: 最大的相似三角形组的数量
    """
    if len(triangles) < 3:
        return len(triangles)
    
    try:
        # 按类型分组
        max_triangles = [t for t in triangles if t['type'] == 'max']
        min_triangles = [t for t in triangles if t['type'] == 'min']
        
        # 分别统计每组中的相似三角形
        max_similar = find_similar_group(max_triangles)
        min_similar = find_similar_group(min_triangles)
        
        # 返回较大的组
        return max(max_similar, min_similar)
        
    except Exception as e:
        logging.debug(f"统计相似三角形失败: {e}")
        return 0


def find_similar_group(triangles: list) -> int:
    """
    在一组三角形中找到最大的相似组（改进版）
    
    改进点：
    - 不使用所有三角形的平均值（避免异常值污染）
    - 以每个三角形为基准，找与它相似的其他三角形
    - 返回最大的相似组大小
    
    Args:
        triangles: 同类型的三角形列表
    
    Returns:
        int: 最大相似组的数量
    """
    if len(triangles) < 2:
        return len(triangles)
    
    try:
        # 如果只有2个三角形，直接判断它们是否相似
        if len(triangles) == 2:
            t1, t2 = triangles[0], triangles[1]
            height_diff = abs(t1['height'] - t2['height'])
            width_diff = abs(t1['width'] - t2['width'])
            avg_height = (t1['height'] + t2['height']) / 2
            avg_width = (t1['width'] + t2['width']) / 2
            
            # 相似度阈值：30%
            if (height_diff < avg_height * 0.3 and 
                width_diff < avg_width * 0.3):
                return 2
            return 0
        
        # 3个或更多：找最大的相似组
        # 方法：以每个三角形为基准，找与它相似的其他三角形
        max_similar = 0
        
        for i in range(len(triangles)):
            similar_count = 1  # 包括基准三角形自己
            base_height = triangles[i]['height']
            base_width = triangles[i]['width']
            
            for j in range(len(triangles)):
                if i == j:
                    continue
                
                height_diff = abs(triangles[j]['height'] - base_height)
                width_diff = abs(triangles[j]['width'] - base_width)
                
                # 与基准三角形比较（不是与平均值比较）
                # 相似度阈值：30%
                if (height_diff < base_height * 0.3 and 
                    width_diff < base_width * 0.3):
                    similar_count += 1
            
            max_similar = max(max_similar, similar_count)
        
        return max_similar
        
    except Exception as e:
        logging.debug(f"查找相似组失败: {e}")
        return 0

    