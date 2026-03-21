# -*- coding: utf-8 -*-
"""
板料线视图识别模块
通过识别252号色、dashed线形的矩形（板料线）来确定视图位置
"""
import logging
import math
from typing import Optional, Dict, List, Tuple


class PlateLineViewIdentifier:
    """板料线视图识别器 - 通过板料线的相对位置识别视图"""
    
    def __init__(self, tolerance: float = 5.0):
        """
        Args:
            tolerance: 尺寸匹配容差（单位：mm）
        """
        self.tolerance = tolerance
    
    def identify_views_by_plate_lines(self, msp, dimensions: Optional[Dict] = None) -> tuple:
        """
        通过板料线（252号色、dashed线形）识别三个视图的边框
        
        识别规则：
        1. 优先根据零件尺寸（L×W×T）匹配视图
        2. 如果尺寸匹配失败，则根据相对位置分配：
           - 左上角的是俯视图（top_view）
           - 左下角的是正视图（front_view）
           - 右上角的是侧视图（side_view）
        
        Args:
            msp: modelspace
            dimensions: 零件尺寸字典，包含 'L', 'W', 'T' 键（可选）
        
        Returns:
            tuple: (views_dict, anomaly_dict)
                views_dict: {
                    'top_view': {'bounds': {...}},     # 俯视图
                    'front_view': {'bounds': {...}},   # 正视图
                    'side_view': {'bounds': {...}}     # 侧视图
                }
                anomaly_dict: 异常信息字典，如果有异常则包含异常详情，否则为 None
            如果未识别到板料线，返回 ({}, anomaly)
        """
        print("DEBUG: identify_views_by_plate_lines 被调用")
        try:
            logging.info("=" * 80)
            logging.info("🔍 尝试通过板料线识别视图")
            logging.info("=" * 80)
            print("DEBUG: 开始查找板料线矩形...")
            
            # 查找所有板料线矩形
            plate_rectangles = self._find_plate_line_rectangles(msp)
            
            print(f"DEBUG: 找到 {len(plate_rectangles)} 个板料线矩形")
            
            if not plate_rectangles:
                logging.info("❌ 未找到板料线矩形，将使用传统方法识别视图")
                print("DEBUG: 未找到板料线矩形")
                
                # 记录异常信息
                anomaly = {
                    'type': 'plate_line_not_found',
                    'description': '板料线识别失败: 未找到板料线矩形',
                    'found_count': 0,
                    'required_count': 3
                }
                
                return {}, anomaly
            
            if len(plate_rectangles) < 2:
                logging.warning(f"⚠️ 只找到 {len(plate_rectangles)} 个板料线矩形，至少需要2个才能确定视图位置")
                print(f"DEBUG: 只找到 {len(plate_rectangles)} 个板料线矩形")
                
                # 记录异常信息
                anomaly = {
                    'type': 'plate_line_insufficient',
                    'description': f'板料线识别失败: 只找到 {len(plate_rectangles)} 个板料线矩形',
                    'found_count': len(plate_rectangles),
                    'required_count': 2
                }
                
                return {}, anomaly
            
            logging.info(f"✅ 找到 {len(plate_rectangles)} 个板料线矩形")
            
            # 优先根据尺寸匹配视图
            views = None
            if dimensions and all(k in dimensions for k in ['L', 'W', 'T']):
                logging.info("🔍 尝试根据零件尺寸匹配视图")
                views = self._assign_views_by_dimensions(plate_rectangles, dimensions)
            
            # 如果尺寸匹配失败，则根据相对位置分配视图
            if not views:
                if dimensions:
                    logging.info("⚠️ 尺寸匹配失败，使用相对位置分配视图")
                else:
                    logging.info("🔍 使用相对位置分配视图")
                views = self._assign_views_by_position(plate_rectangles)
            
            if views:
                # 检查是否识别到全部3个视图
                expected_views = {'top_view', 'front_view', 'side_view'}
                found_views = set(views.keys())
                missing_views = expected_views - found_views
                
                if missing_views:
                    # 只识别到部分视图
                    missing_view_names = []
                    if 'top_view' in missing_views:
                        missing_view_names.append('俯视图')
                    if 'front_view' in missing_views:
                        missing_view_names.append('正视图')
                    if 'side_view' in missing_views:
                        missing_view_names.append('侧视图')
                    
                    logging.warning(f"⚠️ 板料线只识别到部分视图: {list(found_views)}, 缺失: {list(missing_views)}")
                    
                    anomaly = {
                        'type': 'plate_line_partial',
                        'description': f'板料线识别不全: 缺少{", ".join(missing_view_names)}',
                        'found_count': len(found_views),
                        'required_count': 3,
                        'missing_views': missing_view_names
                    }
                    
                    # 打印已识别的视图信息
                    logging.info("✅ 通过板料线识别到部分视图:")
                    for view_name, view_info in views.items():
                        bounds = view_info['bounds']
                        width = bounds['max_x'] - bounds['min_x']
                        height = bounds['max_y'] - bounds['min_y']
                        logging.info(
                            f"  {view_name}: {width:.1f}×{height:.1f}mm, "
                            f"位置=[X: {bounds['min_x']:.1f}~{bounds['max_x']:.1f}, "
                            f"Y: {bounds['min_y']:.1f}~{bounds['max_y']:.1f}]"
                        )
                    
                    return views, anomaly
                else:
                    # 识别到全部3个视图
                    logging.info("✅ 成功通过板料线识别视图:")
                    for view_name, view_info in views.items():
                        bounds = view_info['bounds']
                        width = bounds['max_x'] - bounds['min_x']
                        height = bounds['max_y'] - bounds['min_y']
                        logging.info(
                            f"  {view_name}: {width:.1f}×{height:.1f}mm, "
                            f"位置=[X: {bounds['min_x']:.1f}~{bounds['max_x']:.1f}, "
                            f"Y: {bounds['min_y']:.1f}~{bounds['max_y']:.1f}]"
                        )
                    
                    return views, None
            else:
                # 找到了板料线矩形但无法分配视图
                logging.warning("⚠️ 无法根据板料线位置分配视图")
                
                anomaly = {
                    'type': 'plate_line_assignment_failed',
                    'description': f'板料线识别失败: 找到 {len(plate_rectangles)} 个矩形但无法分配视图',
                    'found_count': len(plate_rectangles),
                    'required_count': 3
                }
                
                return {}, anomaly
            
        except Exception as e:
            logging.error(f"板料线视图识别失败: {str(e)}")
            print(f"DEBUG: 异常 - {e}")
            import traceback
            logging.error(traceback.format_exc())
            traceback.print_exc()
            return {}, None
    
    def _find_plate_line_rectangles(self, msp) -> List[Dict]:
        """
        查找所有板料线矩形（252号色、dashed线形）
        
        Returns:
            List[Dict]: 矩形列表，每个矩形包含 bounds, width, height, center
        """
        rectangles = []
        
        try:
            # 方法1: 查找 LWPOLYLINE 类型的板料线矩形
            lwpolyline_rects = self._find_plate_line_lwpolylines(msp)
            rectangles.extend(lwpolyline_rects)
            
            # 方法2: 查找由4条 LINE 组成的板料线矩形
            line_rects = self._find_plate_line_from_lines(msp)
            rectangles.extend(line_rects)
            
            logging.info(f"找到 {len(rectangles)} 个板料线矩形")
            
            return rectangles
            
        except Exception as e:
            logging.error(f"查找板料线矩形失败: {str(e)}")
            return []

    def _find_plate_line_lwpolylines(self, msp) -> List[Dict]:
        """查找 LWPOLYLINE 类型的板料线矩形"""
        rectangles = []
        
        try:
            all_lwpolylines = list(msp.query('LWPOLYLINE'))
            logging.info(f"检查 {len(all_lwpolylines)} 个 LWPOLYLINE 实体")
            
            plate_line_count = 0
            
            for idx, entity in enumerate(all_lwpolylines):
                # 检查颜色和线型
                color = getattr(entity.dxf, 'color', 256)
                linetype = getattr(entity.dxf, 'linetype', 'ByLayer')
                
                # 必须是 252 号色且为 dashed 线型
                if color != 252:
                    continue
                
                if linetype.lower() not in ['dashed', 'acad_iso02w100', 'acad_iso10w100']:
                    continue
                
                logging.debug(
                    f"  LWPOLYLINE {idx + 1}: 颜色={color}, 线型={linetype} ✓ 是板料线"
                )
                
                # 检查是否为矩形
                is_rect, reason = self._is_rectangle_polyline_with_reason(entity)
                
                if is_rect:
                    bounds = self._get_polyline_bounds(entity)
                    if bounds:
                        width = bounds['max_x'] - bounds['min_x']
                        height = bounds['max_y'] - bounds['min_y']
                        center = (
                            (bounds['min_x'] + bounds['max_x']) / 2,
                            (bounds['min_y'] + bounds['max_y']) / 2
                        )
                        
                        logging.info(f"    ✅ 识别为板料线矩形: {width:.1f}×{height:.1f}mm")
                        
                        rectangles.append({
                            'bounds': bounds,
                            'width': width,
                            'height': height,
                            'center': center
                        })
                        plate_line_count += 1
                else:
                    logging.debug(f"    ❌ 不是矩形: {reason}")
            
            logging.info(f"从 LWPOLYLINE 中识别到 {plate_line_count} 个板料线矩形")
            
            return rectangles
            
        except Exception as e:
            logging.error(f"查找 LWPOLYLINE 板料线失败: {str(e)}")
            return []
    
    def _find_plate_line_from_lines(self, msp) -> List[Dict]:
        """查找由4条 LINE 组成的板料线矩形"""
        rectangles = []
        
        try:
            # 收集所有板料线（252号色、dashed线型）
            plate_lines = []
            
            for entity in msp.query('LINE'):
                color = getattr(entity.dxf, 'color', 256)
                linetype = getattr(entity.dxf, 'linetype', 'ByLayer')
                
                # 必须是 252 号色且为 dashed 线型
                if color != 252:
                    continue
                
                if linetype.lower() not in ['dashed', 'acad_iso02w100', 'acad_iso10w100']:
                    continue
                
                start = entity.dxf.start
                end = entity.dxf.end
                
                dx = abs(end.x - start.x)
                dy = abs(end.y - start.y)
                
                plate_lines.append({
                    'start': (start.x, start.y),
                    'end': (end.x, end.y),
                    'dx': dx,
                    'dy': dy,
                    'entity': entity
                })
            
            if not plate_lines:
                logging.debug("未找到板料线 LINE 实体")
                return []
            
            logging.info(f"找到 {len(plate_lines)} 条板料线 LINE")
            
            # 分类为水平线和垂直线
            horizontal_lines = []
            vertical_lines = []
            line_tolerance = 2.0
            
            for line in plate_lines:
                if line['dy'] < line_tolerance and line['dx'] > 10:  # 水平线
                    horizontal_lines.append({
                        'y': (line['start'][1] + line['end'][1]) / 2,
                        'x1': min(line['start'][0], line['end'][0]),
                        'x2': max(line['start'][0], line['end'][0]),
                        'length': line['dx']
                    })
                elif line['dx'] < line_tolerance and line['dy'] > 10:  # 垂直线
                    vertical_lines.append({
                        'x': (line['start'][0] + line['end'][0]) / 2,
                        'y1': min(line['start'][1], line['end'][1]),
                        'y2': max(line['start'][1], line['end'][1]),
                        'length': line['dy']
                    })
            
            logging.info(f"板料线: {len(horizontal_lines)} 条水平线, {len(vertical_lines)} 条垂直线")
            
            # 查找矩形：平行且长度相近的水平线和垂直线
            for i, h1 in enumerate(horizontal_lines):
                for h2 in horizontal_lines[i+1:]:
                    # 检查两条水平线是否平行且长度相近
                    if abs(h1['length'] - h2['length']) > self.tolerance:
                        continue
                    
                    # 检查 x 范围是否对齐
                    if abs(h1['x1'] - h2['x1']) > self.tolerance or \
                       abs(h1['x2'] - h2['x2']) > self.tolerance:
                        continue
                    
                    height = abs(h1['y'] - h2['y'])
                    
                    # 查找匹配的垂直线对
                    for j, v1 in enumerate(vertical_lines):
                        for v2 in vertical_lines[j+1:]:
                            # 检查两条垂直线是否平行且长度相近
                            if abs(v1['length'] - v2['length']) > self.tolerance:
                                continue
                            
                            # 检查长度是否匹配高度
                            if abs(v1['length'] - height) > self.tolerance:
                                continue
                            
                            # 检查 y 范围是否对齐
                            if abs(v1['y1'] - v2['y1']) > self.tolerance or \
                               abs(v1['y2'] - v2['y2']) > self.tolerance:
                                continue
                            
                            width = abs(v1['x'] - v2['x'])
                            
                            # 检查宽度是否匹配水平线长度
                            if abs(width - h1['length']) > self.tolerance:
                                continue
                            
                            # 构建矩形
                            bounds = {
                                'min_x': min(h1['x1'], h2['x1']),
                                'max_x': max(h1['x2'], h2['x2']),
                                'min_y': min(h1['y'], h2['y']),
                                'max_y': max(h1['y'], h2['y'])
                            }
                            
                            center = (
                                (bounds['min_x'] + bounds['max_x']) / 2,
                                (bounds['min_y'] + bounds['max_y']) / 2
                            )
                            
                            rectangles.append({
                                'bounds': bounds,
                                'width': width,
                                'height': height,
                                'center': center
                            })
                            
                            logging.info(
                                f"✅ 从 LINE 识别到板料线矩形: {width:.1f}×{height:.1f}mm"
                            )
            
            return rectangles
            
        except Exception as e:
            logging.error(f"从 LINE 查找板料线矩形失败: {str(e)}")
            return []

    def _is_rectangle_polyline_with_reason(self, polyline) -> Tuple[bool, str]:
        """判断多段线是否为矩形，并返回原因"""
        try:
            # 获取顶点
            points = list(polyline.get_points('xy'))
            
            # 检查是否闭合
            is_closed = getattr(polyline.dxf, 'closed', False)
            
            if not is_closed and len(points) >= 2:
                # 检查首尾顶点是否接近
                first_point = points[0]
                last_point = points[-1]
                distance = math.sqrt(
                    (first_point[0] - last_point[0])**2 + 
                    (first_point[1] - last_point[1])**2
                )
                
                if distance < 5.0:
                    is_closed = True
                    if distance < 0.1:
                        points = points[:-1]
            
            if not is_closed:
                if len(points) == 4:
                    is_closed = True
                else:
                    return False, f"未闭合且顶点数={len(points)}"
            
            # 检查顶点数量
            if len(points) != 4:
                return False, f"顶点数={len(points)}，需要4个顶点"
            
            # 检查是否有4个直角
            angles = []
            for i in range(4):
                p1 = points[i]
                p2 = points[(i + 1) % 4]
                p3 = points[(i + 2) % 4]
                
                v1 = (p2[0] - p1[0], p2[1] - p1[1])
                v2 = (p3[0] - p2[0], p3[1] - p2[1])
                
                dot = v1[0] * v2[0] + v1[1] * v2[1]
                len1 = math.sqrt(v1[0]**2 + v1[1]**2)
                len2 = math.sqrt(v2[0]**2 + v2[1]**2)
                
                if len1 > 0 and len2 > 0:
                    cos_angle = dot / (len1 * len2)
                    angle = math.degrees(math.acos(max(-1, min(1, cos_angle))))
                    angles.append(angle)
                else:
                    return False, "存在长度为0的边"
            
            # 放宽角度容差到 15 度
            non_right_angles = [a for a in angles if abs(a - 90) >= 15]
            if non_right_angles:
                angles_str = ", ".join([f"{a:.1f}°" for a in angles])
                return False, f"角度偏离90度过大: [{angles_str}]"
            
            return True, "符合矩形条件"
            
        except Exception as e:
            return False, f"检查失败: {str(e)}"
    
    def _get_polyline_bounds(self, polyline) -> Optional[Dict]:
        """获取多段线边界"""
        try:
            points = list(polyline.get_points('xy'))
            if not points:
                return None
            
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            
            return {
                'min_x': min(xs),
                'max_x': max(xs),
                'min_y': min(ys),
                'max_y': max(ys)
            }
        except Exception:
            return None
    
    def _assign_views_by_dimensions(self, rectangles: List[Dict], dimensions: Dict) -> Optional[Dict[str, Dict]]:
        """
        根据零件尺寸（L×W×T）匹配视图
        
        匹配规则：
        - 俯视图: L×W 或 W×L
        - 正视图: L×T 或 T×L
        - 侧视图: W×T 或 T×W
        
        Args:
            rectangles: 矩形列表
            dimensions: 零件尺寸字典 {'L': float, 'W': float, 'T': float}
        
        Returns:
            Dict: {view_name: {'bounds': ...}} 或 None（匹配失败）
        """
        try:
            L = dimensions['L']
            W = dimensions['W']
            T = dimensions['T']
            
            logging.info(f"零件尺寸提取完成: L={L}, W={W}, T={T}")
            logging.info(f"期望视图尺寸 - 俯视图: {L}×{W} 或 {W}×{L}")
            logging.info(f"期望视图尺寸 - 正视图: {L}×{T} 或 {T}×{L}")
            logging.info(f"期望视图尺寸 - 侧视图: {W}×{T} 或 {T}×{W}")
            
            # 尺寸匹配容差（5mm）
            size_tolerance = self.tolerance
            
            views = {}
            matched_indices = set()
            
            # 匹配俯视图 (L×W 或 W×L)
            for idx, rect in enumerate(rectangles):
                width = rect['width']
                height = rect['height']
                
                # 检查是否匹配 L×W
                if (abs(width - L) <= size_tolerance and abs(height - W) <= size_tolerance) or \
                   (abs(width - W) <= size_tolerance and abs(height - L) <= size_tolerance):
                    views['top_view'] = {'bounds': rect['bounds']}
                    matched_indices.add(idx)
                    logging.info(f"✅ 俯视图匹配成功: 矩形{idx+1} ({width:.1f}×{height:.1f}mm)")
                    break
            
            # 匹配正视图 (L×T 或 T×L)
            for idx, rect in enumerate(rectangles):
                if idx in matched_indices:
                    continue
                
                width = rect['width']
                height = rect['height']
                
                # 检查是否匹配 L×T
                if (abs(width - L) <= size_tolerance and abs(height - T) <= size_tolerance) or \
                   (abs(width - T) <= size_tolerance and abs(height - L) <= size_tolerance):
                    views['front_view'] = {'bounds': rect['bounds']}
                    matched_indices.add(idx)
                    logging.info(f"✅ 正视图匹配成功: 矩形{idx+1} ({width:.1f}×{height:.1f}mm)")
                    break
            
            # 匹配侧视图 (W×T 或 T×W)
            for idx, rect in enumerate(rectangles):
                if idx in matched_indices:
                    continue
                
                width = rect['width']
                height = rect['height']
                
                # 检查是否匹配 W×T
                if (abs(width - W) <= size_tolerance and abs(height - T) <= size_tolerance) or \
                   (abs(width - T) <= size_tolerance and abs(height - W) <= size_tolerance):
                    views['side_view'] = {'bounds': rect['bounds']}
                    matched_indices.add(idx)
                    logging.info(f"✅ 侧视图匹配成功: 矩形{idx+1} ({width:.1f}×{height:.1f}mm)")
                    break
            
            # 检查匹配结果
            if len(views) == 3:
                logging.info("✅ 根据尺寸成功匹配全部3个视图")
                return views
            elif len(views) >= 1:
                logging.warning(f"⚠️ 根据尺寸只匹配到 {len(views)} 个视图: {list(views.keys())}")
                # 部分匹配也返回，可以与位置匹配结合
                return views
            else:
                logging.warning("⚠️ 根据尺寸未匹配到任何视图")
                return None
            
        except Exception as e:
            logging.error(f"根据尺寸匹配视图失败: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None
    
    def _assign_views_by_position(self, rectangles: List[Dict]) -> Dict[str, Dict]:
        """
        根据矩形的相对位置分配视图
        
        规则：
        - 左上角的是俯视图（top_view）
        - 左下角的是正视图（front_view）
        - 右上角的是侧视图（side_view）
        
        Args:
            rectangles: 矩形列表
        
        Returns:
            Dict: {view_name: {'bounds': ...}}
        """
        if len(rectangles) < 2:
            return {}
        
        try:
            # 计算所有矩形的中心点范围
            centers = [rect['center'] for rect in rectangles]
            xs = [c[0] for c in centers]
            ys = [c[1] for c in centers]
            
            # 使用平均值而不是中位数，避免极端情况
            avg_x = sum(xs) / len(xs)
            avg_y = sum(ys) / len(ys)
            
            # 设置容差，处理浮点数精度问题
            tolerance = 0.01  # 0.01mm 的容差
            
            logging.info(f"矩形中心点范围: X=[{min(xs):.1f}, {max(xs):.1f}], Y=[{min(ys):.1f}, {max(ys):.1f}]")
            logging.info(f"平均值: X={avg_x:.1f}, Y={avg_y:.1f}")
            
            # 分类矩形
            left_top = []      # 左上角
            left_bottom = []   # 左下角
            right_top = []     # 右上角
            right_bottom = []  # 右下角
            
            for idx, rect in enumerate(rectangles):
                cx, cy = rect['center']
                
                # 当等于平均值时，左边和上面的优先级更高
                # 使用 INFO 级别确保日志可见
                logging.info(f"🔍 矩形{idx+1}分类: 中心=({cx:.2f}, {cy:.2f}), 平均值=({avg_x:.2f}, {avg_y:.2f})")
                
                # 使用容差比较，处理浮点数精度问题
                # 当差值在容差范围内时，认为相等，优先分配到左边和上面
                is_left = (cx < avg_x - tolerance) or (abs(cx - avg_x) <= tolerance)
                is_top = (cy > avg_y + tolerance) or (abs(cy - avg_y) <= tolerance)
                
                if is_left:  # 左侧（包括容差范围内）
                    if is_top:  # 上方（包括容差范围内）
                        left_top.append(rect)
                        logging.info(f"  ✅ 矩形{idx+1}: 左侧 且 上方 → 左上")
                    else:  # 下方
                        left_bottom.append(rect)
                        logging.info(f"  ✅ 矩形{idx+1}: 左侧 且 下方 → 左下")
                else:  # 右侧
                    if is_top:  # 上方（包括容差范围内）
                        right_top.append(rect)
                        logging.info(f"  ✅ 矩形{idx+1}: 右侧 且 上方 → 右上")
                    else:  # 下方
                        right_bottom.append(rect)
                        logging.info(f"  ✅ 矩形{idx+1}: 右侧 且 下方 → 右下")
            
            logging.info(
                f"矩形分布: 左上={len(left_top)}, 左下={len(left_bottom)}, "
                f"右上={len(right_top)}, 右下={len(right_bottom)}"
            )
            
            views = {}
            
            # 分配俯视图（左上角）
            if left_top:
                # 如果有多个，选择最大的
                top_view_rect = max(left_top, key=lambda r: r['width'] * r['height'])
                views['top_view'] = {'bounds': top_view_rect['bounds']}
                logging.info(f"✅ 俯视图（左上）: {top_view_rect['width']:.1f}×{top_view_rect['height']:.1f}mm")
            
            # 分配正视图（左下角）
            if left_bottom:
                front_view_rect = max(left_bottom, key=lambda r: r['width'] * r['height'])
                views['front_view'] = {'bounds': front_view_rect['bounds']}
                logging.info(f"✅ 正视图（左下）: {front_view_rect['width']:.1f}×{front_view_rect['height']:.1f}mm")
            
            # 分配侧视图（右上角）
            if right_top:
                side_view_rect = max(right_top, key=lambda r: r['width'] * r['height'])
                views['side_view'] = {'bounds': side_view_rect['bounds']}
                logging.info(f"✅ 侧视图（右上）: {side_view_rect['width']:.1f}×{side_view_rect['height']:.1f}mm")
            
            # 检查识别结果
            if len(views) == 3:
                logging.info("✅ 成功识别到全部3个视图")
                return views
            elif len(views) >= 1:
                logging.warning(f"⚠️ 只识别到 {len(views)} 个视图，将返回部分结果供传统方法补充")
                return views
            else:
                logging.warning("⚠️ 未识别到任何视图")
                return {}
            
        except Exception as e:
            logging.error(f"根据位置分配视图失败: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return {}
