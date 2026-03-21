# -*- coding: utf-8 -*-
"""
视图识别模块
根据长宽厚（L W T）识别三个视图的边框
"""
import logging
import math
from typing import Optional, Dict, List, Tuple
from .plate_line_view_identifier import PlateLineViewIdentifier


class ViewIdentifier:
    """视图识别器 - 识别俯视图、正视图、侧视图的边框"""
    
    def __init__(self, tolerance: float = 10.0):
        """
        Args:
            tolerance: 尺寸匹配容差（单位：mm）
        """
        self.tolerance = tolerance
        self.plate_line_identifier = PlateLineViewIdentifier(tolerance=5.0)
    
    def identify_views(
        self, 
        msp, 
        length: float, 
        width: float, 
        thickness: float
    ) -> tuple:
        """
        识别三个视图的边框
        
        优先级：
        1. 首先尝试通过板料线（252号色、dashed线形）识别视图
        2. 如果板料线识别失败，使用传统的基于长宽厚的识别方法
        
        Args:
            msp: modelspace
            length: 长度 L（单位：mm）
            width: 宽度 W（单位：mm）
            thickness: 厚度 T（单位：mm）
        
        Returns:
            tuple: (views_dict, anomalies_list)
                views_dict: {
                    'top_view': {'bounds': {...}},     # 俯视图 L×W
                    'front_view': {'bounds': {...}},   # 正视图 L×T
                    'side_view': {'bounds': {...}}     # 侧视图 W×T
                }
                anomalies_list: 视图识别过程中的异常列表
        """
        try:
            view_anomalies = []
            
            # 构建尺寸字典
            dimensions = {
                'L': length,
                'W': width,
                'T': thickness
            }
            
            # 优先尝试通过板料线识别视图（传入尺寸信息）
            views, plate_line_anomaly = self.plate_line_identifier.identify_views_by_plate_lines(msp, dimensions)
            
            # 如果板料线识别产生了异常，记录下来
            if plate_line_anomaly:
                view_anomalies.append(plate_line_anomaly)
                logging.info("⚠️ 板料线识别未成功，使用传统的基于长宽厚的识别方法")
            
            # 只有识别到全部3个视图时才跳过传统方法
            if views and len(views) >= 3:
                logging.info(f"✅ 成功通过板料线识别到全部 {len(views)} 个视图，跳过传统识别方法")
                return views, view_anomalies
            elif views and len(views) >= 1:
                logging.warning(f"⚠️ 板料线只识别到 {len(views)} 个视图（需要3个），将使用传统方法补充识别其他视图")
                # 保存已识别的视图，后续与传统方法的结果合并
                plate_line_views = views
            else:
                if not plate_line_anomaly:
                    logging.info("⚠️ 板料线识别未成功，使用传统的基于长宽厚的识别方法")
                plate_line_views = {}
            
            logging.info("")
            
            # 查找所有矩形边框
            rectangles = self._find_rectangles(msp)
            
            # 定义视图尺寸（考虑两种方向）
            view_dimensions = {
                'top_view': [(length, width), (width, length)],
                'front_view': [(length, thickness), (thickness, length)],
                'side_view': [(width, thickness), (thickness, width)]
            }
            
            logging.info(f"期望视图尺寸 - 俯视图: {length:.1f}×{width:.1f} 或 {width:.1f}×{length:.1f}")
            logging.info(f"期望视图尺寸 - 正视图: {length:.1f}×{thickness:.1f} 或 {thickness:.1f}×{length:.1f}")
            logging.info(f"期望视图尺寸 - 侧视图: {width:.1f}×{thickness:.1f} 或 {thickness:.1f}×{width:.1f}")
            logging.info(f"匹配容差: {self.tolerance * 2:.1f}mm")
            
            # 从板料线识别的结果开始（如果有的话）
            views = plate_line_views.copy() if plate_line_views else {}
            
            if views:
                logging.info(f"📌 保留板料线识别的 {len(views)} 个视图: {list(views.keys())}")
            
            used_rectangles = set()
            
            # 如果找到矩形，尝试匹配视图
            if rectangles:
                # 只匹配还未识别的视图
                missing_view_names = [name for name in view_dimensions.keys() if name not in views]
                
                if missing_view_names:
                    logging.info(f"🔍 使用传统方法识别缺失的视图: {missing_view_names}")
                    missing_view_dims = {name: view_dimensions[name] for name in missing_view_names}
                    
                    # 尝试全局最优匹配算法
                    optimal_views = self._find_optimal_view_assignment(rectangles, missing_view_dims)
                    
                    if optimal_views:
                        views.update(optimal_views)
                        logging.info(f"✅ 使用全局最优匹配算法成功识别缺失视图: {list(optimal_views.keys())}")
                    else:
                        # 如果全局最优失败，降级到贪心算法
                        logging.warning("⚠️ 全局最优匹配失败，降级到贪心算法")
                        greedy_views = self._greedy_view_assignment(rectangles, missing_view_dims)
                        views.update(greedy_views)
                        if greedy_views:
                            logging.info(f"✅ 使用贪心算法成功识别缺失视图: {list(greedy_views.keys())}")
                else:
                    logging.info("✅ 所有视图已通过板料线识别，无需传统方法补充")
            else:
                logging.warning("未找到任何矩形边框，将直接使用兜底机制")
            
            # 兜底机制：对于未识别到的视图，尝试通过平行线对构建边界
            missing_views = [name for name in view_dimensions.keys() if name not in views]
            
            if missing_views:
                logging.info(f"🔍 启动兜底机制1，尝试通过平行线对识别未找到的视图: {missing_views}")
                
                # 获取已使用的边界区域（避免重叠）
                used_bounds = [views[view_name]['bounds'] for view_name in views.keys()]
                
                # 尝试全局最优匹配（收集所有候选边界，选择最优组合）
                missing_view_dims = {name: view_dimensions[name] for name in missing_views}
                optimal_fallback = self._find_optimal_fallback_assignment(
                    msp, missing_view_dims, used_bounds
                )
                
                if optimal_fallback:
                    for view_name, bounds in optimal_fallback.items():
                        views[view_name] = {'bounds': bounds}
                        used_bounds.append(bounds)
                        width = bounds['max_x'] - bounds['min_x']
                        height = bounds['max_y'] - bounds['min_y']
                        logging.info(
                            f"✅ 通过平行线对识别到{view_name}: "
                            f"{width:.1f}×{height:.1f}mm"
                        )
                    
                    # 更新 missing_views，移除已识别的视图
                    missing_views = [name for name in missing_views if name not in optimal_fallback]
                else:
                    logging.warning(f"⚠️ 兜底机制1全局最优匹配失败，尝试贪心匹配")
                    
                    # 降级到贪心匹配
                    for view_name in missing_views:
                        dim_pairs = view_dimensions[view_name]
                        fallback_bounds = self._find_view_by_parallel_lines(
                            msp, dim_pairs, used_bounds
                        )
                        
                        if fallback_bounds:
                            views[view_name] = {'bounds': fallback_bounds}
                            used_bounds.append(fallback_bounds)
                            width = fallback_bounds['max_x'] - fallback_bounds['min_x']
                            height = fallback_bounds['max_y'] - fallback_bounds['min_y']
                            logging.info(
                                f"✅ 通过平行线对识别到{view_name}: "
                                f"{width:.1f}×{height:.1f}mm"
                            )
                        else:
                            logging.warning(f"⚠️ 兜底机制1未能识别 {view_name}")
                
                # 第二层兜底机制：通过单边线段+垂直线构建边界
                still_missing = [name for name in missing_views if name not in views]
                
                if still_missing:
                    logging.info(f"🔍 启动兜底机制2，尝试通过单边线段+垂直线识别: {still_missing}")
                    
                    for view_name in still_missing:
                        dim_pairs = view_dimensions[view_name]
                        fallback_bounds = self._find_view_by_single_edge_with_perpendiculars(
                            msp, dim_pairs, used_bounds
                        )
                        
                        if fallback_bounds:
                            views[view_name] = {'bounds': fallback_bounds}
                            used_bounds.append(fallback_bounds)
                            width = fallback_bounds['max_x'] - fallback_bounds['min_x']
                            height = fallback_bounds['max_y'] - fallback_bounds['min_y']
                            logging.info(
                                f"✅ 通过单边线段+垂直线识别到{view_name}: "
                                f"{width:.1f}×{height:.1f}mm"
                            )
                        else:
                            logging.warning(f"⚠️ 兜底机制2也未能识别 {view_name}")
                
                # 第三层兜底机制：通过红色实线的分布范围识别视图
                still_missing = [name for name in missing_views if name not in views]
                
                if still_missing:
                    logging.info(f"🔍 启动兜底机制3，尝试通过红色实线分布识别: {still_missing}")
                    
                    for view_name in still_missing:
                        dim_pairs = view_dimensions[view_name]
                        fallback_bounds = self._find_view_by_red_line_distribution(
                            msp, dim_pairs, used_bounds
                        )
                        
                        if fallback_bounds:
                            views[view_name] = {'bounds': fallback_bounds}
                            used_bounds.append(fallback_bounds)
                            width = fallback_bounds['max_x'] - fallback_bounds['min_x']
                            height = fallback_bounds['max_y'] - fallback_bounds['min_y']
                            logging.info(
                                f"✅ 通过红色实线分布识别到{view_name}: "
                                f"{width:.1f}×{height:.1f}mm"
                            )
                        else:
                            logging.warning(f"⚠️ 兜底机制3也未能识别 {view_name}")
            
            # 如果板料线识别到了部分视图，与传统方法的结果合并
            if plate_line_views:
                for view_name, view_info in plate_line_views.items():
                    if view_name not in views:
                        views[view_name] = view_info
                        logging.info(f"✅ 使用板料线识别的 {view_name}")
            
            return views, view_anomalies
            
        except Exception as e:
            logging.error(f"视图识别失败: {str(e)}")
            return {}, []

    def _find_rectangles(self, msp) -> List[Dict]:
        """查找所有矩形边框（优化版：只使用 LWPOLYLINE 方法）"""
        rectangles = []
        
        try:
            # 查询所有 LWPOLYLINE 实体
            all_lwpolylines = list(msp.query('LWPOLYLINE'))
            logging.info(f"图纸中共有 {len(all_lwpolylines)} 个 LWPOLYLINE 实体")
            
            # 查找闭合的 LWPOLYLINE 矩形
            polyline_rect_count = 0
            for idx, entity in enumerate(all_lwpolylines):
                # 获取基本信息
                points = list(entity.get_points('xy'))
                closed = getattr(entity.dxf, 'closed', False)
                color = getattr(entity.dxf, 'color', 256)
                layer = getattr(entity.dxf, 'layer', 'Unknown')
                
                logging.debug(
                    f"  LWPOLYLINE {idx + 1}: "
                    f"顶点数={len(points)}, "
                    f"闭合={closed}, "
                    f"颜色={color}, "
                    f"图层={layer}"
                )
                
                # 检查是否为矩形
                is_rect, reason = self._is_rectangle_polyline_with_reason(entity)
                
                if is_rect:
                    bounds = self._get_polyline_bounds(entity)
                    if bounds:
                        width = bounds['max_x'] - bounds['min_x']
                        height = bounds['max_y'] - bounds['min_y']
                        
                        logging.info(f"    ✅ 识别为矩形: {width:.1f}×{height:.1f}mm")
                        
                        rectangles.append({
                            'bounds': bounds,
                            'width': width,
                            'height': height
                        })
                        polyline_rect_count += 1
                else:
                    logging.debug(f"    ❌ 不是矩形: {reason}")
            
            logging.info(f"从 LWPOLYLINE 中识别到 {polyline_rect_count} 个矩形")
            
            # 过滤掉太小的矩形
            rectangles = [r for r in rectangles if r['width'] > 10 and r['height'] > 10]
            
            logging.info(f"找到 {len(rectangles)} 个有效矩形边框")
            
            # 详细打印每个矩形的信息
            for idx, rect in enumerate(rectangles):
                logging.info(
                    f"  矩形 {idx + 1}: "
                    f"宽度={rect['width']:.2f}mm, "
                    f"高度={rect['height']:.2f}mm, "
                    f"边界=[X: {rect['bounds']['min_x']:.2f}~{rect['bounds']['max_x']:.2f}, "
                    f"Y: {rect['bounds']['min_y']:.2f}~{rect['bounds']['max_y']:.2f}]"
                )
            
            return rectangles
            
        except Exception as e:
            logging.error(f"查找矩形失败: {str(e)}")
            return []

    def _is_rectangle_polyline(self, polyline) -> bool:
        """判断多段线是否为矩形"""
        is_rect, _ = self._is_rectangle_polyline_with_reason(polyline)
        return is_rect
    
    def _is_rectangle_polyline_with_reason(self, polyline) -> tuple:
        """判断多段线是否为矩形，并返回原因"""
        try:
            # 获取顶点
            points = list(polyline.get_points('xy'))
            
            # 检查是否闭合（标记为闭合 或 首尾顶点接近）
            is_closed = getattr(polyline.dxf, 'closed', False)
            
            if not is_closed and len(points) >= 2:
                # 检查首尾顶点是否接近（放宽容差到 5mm）
                first_point = points[0]
                last_point = points[-1]
                distance = math.sqrt(
                    (first_point[0] - last_point[0])**2 + 
                    (first_point[1] - last_point[1])**2
                )
                
                logging.debug(f"      首尾顶点距离: {distance:.3f}mm")
                
                if distance < 5.0:  # 放宽到 5mm
                    is_closed = True
                    logging.debug(f"      首尾接近，视为闭合")
                    # 如果首尾接近，移除最后一个点避免重复
                    if distance < 0.1:
                        points = points[:-1]
            
            if not is_closed:
                # 对于4个顶点的情况，即使不闭合也尝试识别
                if len(points) == 4:
                    logging.debug(f"      虽未闭合但有4个顶点，尝试识别为矩形")
                    is_closed = True
                else:
                    return False, f"未闭合且顶点数={len(points)}"
            
            # 检查顶点数量
            if len(points) != 4:
                return False, f"顶点数={len(points)}，需要4个顶点"
            
            # 打印顶点坐标（用于调试）
            logging.debug(f"      顶点坐标: {[(f'{p[0]:.2f}', f'{p[1]:.2f}') for p in points]}")
            
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
            
            logging.debug(f"      四个角度: {[f'{a:.1f}°' for a in angles]}")
            
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

    def _find_view_by_parallel_lines(
        self, 
        msp, 
        dim_pairs: List[Tuple[float, float]], 
        used_bounds: List[Dict]
    ) -> Optional[Dict]:
        """
        通过平行线对查找视图边界（兜底机制）
        
        Args:
            msp: modelspace
            dim_pairs: 期望的尺寸对 [(width1, height1), (width2, height2)]
            used_bounds: 已使用的边界列表（避免重叠）
        
        Returns:
            Dict: 边界 {'min_x', 'max_x', 'min_y', 'max_y'} 或 None
        """
        try:
            # 收集所有 LINE 实体
            lines = list(msp.query('LINE'))
            
            if not lines:
                logging.debug("未找到任何 LINE 实体")
                return None
            
            # 按水平和垂直分类
            horizontal_lines = []
            vertical_lines = []
            line_tolerance = 2.0
            
            for line in lines:
                start = line.dxf.start
                end = line.dxf.end
                
                dx = abs(end.x - start.x)
                dy = abs(end.y - start.y)
                
                if dy < line_tolerance and dx > 10:  # 水平线
                    horizontal_lines.append({
                        'y': (start.y + end.y) / 2,
                        'x1': min(start.x, end.x),
                        'x2': max(start.x, end.x),
                        'length': dx
                    })
                elif dx < line_tolerance and dy > 10:  # 垂直线
                    vertical_lines.append({
                        'x': (start.x + end.x) / 2,
                        'y1': min(start.y, end.y),
                        'y2': max(start.y, end.y),
                        'length': dy
                    })
            
            logging.debug(f"找到 {len(horizontal_lines)} 条水平线, {len(vertical_lines)} 条垂直线")
            
            # 尝试每个尺寸对
            for expected_w, expected_h in dim_pairs:
                # 尝试方案1：水平线对（距离为 height）+ 垂直线对（距离为 width）
                bounds = self._try_find_bounds_from_lines(
                    horizontal_lines, vertical_lines, 
                    expected_w, expected_h, 
                    used_bounds
                )
                
                if bounds:
                    return bounds
                
                # 尝试方案2：垂直线对（距离为 height）+ 水平线对（距离为 width）
                bounds = self._try_find_bounds_from_lines(
                    vertical_lines, horizontal_lines, 
                    expected_h, expected_w, 
                    used_bounds,
                    swap_axes=True
                )
                
                if bounds:
                    return bounds
            
            return None
            
        except Exception as e:
            logging.error(f"通过平行线对查找视图失败: {e}")
            return None

    def _try_find_bounds_from_lines(
        self,
        primary_lines: List[Dict],
        secondary_lines: List[Dict],
        primary_distance: float,
        secondary_distance: float,
        used_bounds: List[Dict],
        swap_axes: bool = False
    ) -> Optional[Dict]:
        """
        尝试从平行线对构建边界
        
        Args:
            primary_lines: 主方向的线（用于确定主距离）
            secondary_lines: 次方向的线（用于确定次距离）
            primary_distance: 主方向的期望距离
            secondary_distance: 次方向的期望距离
            used_bounds: 已使用的边界
            swap_axes: 是否交换 x/y 轴（用于垂直/水平线的不同组合）
        
        Returns:
            边界字典或 None
        """
        try:
            # 查找长度匹配的主方向线对
            for i, line1 in enumerate(primary_lines):
                # 检查线1的长度是否匹配次距离
                if abs(line1['length'] - secondary_distance) > self.tolerance:
                    continue
                
                for line2 in primary_lines[i+1:]:
                    # 检查线2的长度是否匹配次距离
                    if abs(line2['length'] - secondary_distance) > self.tolerance:
                        continue
                    
                    # 检查两条线是否平行且距离匹配主距离
                    if not swap_axes:
                        # 水平线：检查 y 方向距离
                        distance = abs(line1['y'] - line2['y'])
                        if abs(distance - primary_distance) > self.tolerance:
                            continue
                        
                        # 检查 x 范围是否对齐
                        if abs(line1['x1'] - line2['x1']) > self.tolerance or \
                           abs(line1['x2'] - line2['x2']) > self.tolerance:
                            continue
                        
                        # 构建边界
                        bounds = {
                            'min_x': min(line1['x1'], line2['x1']),
                            'max_x': max(line1['x2'], line2['x2']),
                            'min_y': min(line1['y'], line2['y']),
                            'max_y': max(line1['y'], line2['y'])
                        }
                    else:
                        # 垂直线：检查 x 方向距离
                        distance = abs(line1['x'] - line2['x'])
                        if abs(distance - primary_distance) > self.tolerance:
                            continue
                        
                        # 检查 y 范围是否对齐
                        if abs(line1['y1'] - line2['y1']) > self.tolerance or \
                           abs(line1['y2'] - line2['y2']) > self.tolerance:
                            continue
                        
                        # 构建边界
                        bounds = {
                            'min_x': min(line1['x'], line2['x']),
                            'max_x': max(line1['x'], line2['x']),
                            'min_y': min(line1['y1'], line2['y1']),
                            'max_y': max(line1['y2'], line2['y2'])
                        }
                    
                    # 检查是否与已使用的边界重叠
                    if self._bounds_overlaps_any(bounds, used_bounds):
                        continue
                    
                    # 验证边界尺寸
                    width = bounds['max_x'] - bounds['min_x']
                    height = bounds['max_y'] - bounds['min_y']
                    
                    logging.debug(
                        f"找到候选边界: {width:.1f}×{height:.1f}mm, "
                        f"期望: {secondary_distance:.1f}×{primary_distance:.1f}mm"
                    )
                    
                    # 检查尺寸是否匹配（考虑两种方向）
                    if (abs(width - secondary_distance) <= self.tolerance and 
                        abs(height - primary_distance) <= self.tolerance):
                        return bounds
                    elif (abs(width - primary_distance) <= self.tolerance and 
                          abs(height - secondary_distance) <= self.tolerance):
                        return bounds
            
            return None
            
        except Exception as e:
            logging.debug(f"构建边界失败: {e}")
            return None
    
    def _bounds_overlaps_any(self, bounds: Dict, used_bounds: List[Dict]) -> bool:
        """检查边界是否与任何已使用的边界重叠"""
        for used in used_bounds:
            # 检查是否有重叠区域
            if not (bounds['max_x'] < used['min_x'] or 
                    bounds['min_x'] > used['max_x'] or
                    bounds['max_y'] < used['min_y'] or 
                    bounds['min_y'] > used['max_y']):
                return True
        return False

    def _find_view_by_single_edge_with_perpendiculars(
        self,
        msp,
        dim_pairs: List[Tuple[float, float]],
        used_bounds: List[Dict]
    ) -> Optional[Dict]:
        """
        通过单边线段+垂直线构建视图边界（第二层兜底机制）
        
        查找逻辑：
        1. 找到长度匹配的直线（如长度为 530 或 30）
        2. 检查该直线的两端是否有垂直线
        3. 检查垂直线是否只出现在直线的一侧
        4. 在同侧确定符合视图尺寸的范围
        
        Args:
            msp: modelspace
            dim_pairs: 期望的尺寸对 [(width1, height1), (width2, height2)]
            used_bounds: 已使用的边界列表（避免重叠）
        
        Returns:
            Dict: 边界 {'min_x', 'max_x', 'min_y', 'max_y'} 或 None
        """
        try:
            # 收集所有 LINE 实体
            lines = list(msp.query('LINE'))
            
            if not lines:
                logging.debug("未找到任何 LINE 实体")
                return None
            
            # 按水平和垂直分类
            horizontal_lines = []
            vertical_lines = []
            line_tolerance = 2.0
            min_length = 3.0  # 降低最小长度阈值，以识别短垂直线
            
            for line in lines:
                start = line.dxf.start
                end = line.dxf.end
                
                dx = abs(end.x - start.x)
                dy = abs(end.y - start.y)
                
                if dy < line_tolerance and dx > min_length:  # 水平线
                    horizontal_lines.append({
                        'y': (start.y + end.y) / 2,
                        'x1': min(start.x, end.x),
                        'x2': max(start.x, end.x),
                        'length': dx,
                        'entity': line
                    })
                elif dx < line_tolerance and dy > min_length:  # 垂直线
                    vertical_lines.append({
                        'x': (start.x + end.x) / 2,
                        'y1': min(start.y, end.y),
                        'y2': max(start.y, end.y),
                        'length': dy,
                        'entity': line
                    })
            
            logging.info(f"兜底机制2: 找到 {len(horizontal_lines)} 条水平线, {len(vertical_lines)} 条垂直线")
            
            # 打印期望的尺寸
            for expected_w, expected_h in dim_pairs:
                logging.info(f"兜底机制2: 尝试匹配尺寸 {expected_w:.1f}×{expected_h:.1f}mm")
            
            # 尝试每个尺寸对
            for expected_w, expected_h in dim_pairs:
                logging.debug(f"尝试匹配尺寸: {expected_w:.1f}×{expected_h:.1f}mm")
                
                # 尝试方案1：水平线作为主边，垂直线在两端
                bounds = self._try_build_bounds_from_single_edge(
                    horizontal_lines, vertical_lines,
                    expected_w, expected_h,
                    used_bounds,
                    is_horizontal=True
                )
                
                if bounds:
                    return bounds
                
                # 尝试方案2：垂直线作为主边，水平线在两端
                bounds = self._try_build_bounds_from_single_edge(
                    vertical_lines, horizontal_lines,
                    expected_h, expected_w,
                    used_bounds,
                    is_horizontal=False
                )
                
                if bounds:
                    return bounds
            
            logging.warning("兜底机制2: 所有尺寸对都未能匹配")
            return None
            
        except Exception as e:
            logging.error(f"通过单边线段+垂直线查找视图失败: {e}")
            return None

    def _try_build_bounds_from_single_edge(
        self,
        main_lines: List[Dict],
        perp_lines: List[Dict],
        main_length: float,
        perp_length: float,
        used_bounds: List[Dict],
        is_horizontal: bool
    ) -> Optional[Dict]:
        """
        尝试从单边线段+垂直线构建边界
        
        Args:
            main_lines: 主边线段列表（水平或垂直）
            perp_lines: 垂直线段列表（与主边垂直）
            main_length: 主边的期望长度
            perp_length: 垂直方向的期望长度
            used_bounds: 已使用的边界
            is_horizontal: 主边是否为水平线
        
        Returns:
            边界字典或 None
        """
        try:
            direction = "水平" if is_horizontal else "垂直"
            logging.debug(
                f"尝试从{direction}线构建边界: 主边长度={main_length:.1f}mm, 垂直长度={perp_length:.1f}mm"
            )
            
            # 统计长度匹配的主边线段数量
            matching_main_lines = [
                line for line in main_lines 
                if abs(line['length'] - main_length) <= self.tolerance
            ]
            
            logging.debug(
                f"找到 {len(matching_main_lines)} 条长度匹配的{direction}线 "
                f"(期望长度: {main_length:.1f}mm, 容差: {self.tolerance}mm)"
            )
            
            if not matching_main_lines:
                logging.debug(f"没有找到长度匹配的{direction}线")
                return None
            
            # 查找长度匹配的主边线段
            for idx, main_line in enumerate(matching_main_lines):
                logging.debug(
                    f"检查第 {idx + 1}/{len(matching_main_lines)} 条{direction}线: "
                    f"长度={main_line['length']:.1f}mm"
                )
                
                # 查找主边两端的垂直线
                if is_horizontal:
                    # 主边是水平线，查找两端的垂直线
                    left_x = main_line['x1']
                    right_x = main_line['x2']
                    main_y = main_line['y']
                    
                    # 查找左端和右端的垂直线
                    left_perps = []
                    right_perps = []
                    
                    for perp in perp_lines:
                        # 检查垂直线是否在左端附近
                        if abs(perp['x'] - left_x) < self.tolerance:
                            # 检查垂直线是否与主边相交或接近
                            if perp['y1'] <= main_y <= perp['y2'] or \
                               abs(perp['y1'] - main_y) < self.tolerance or \
                               abs(perp['y2'] - main_y) < self.tolerance:
                                left_perps.append(perp)
                        
                        # 检查垂直线是否在右端附近
                        if abs(perp['x'] - right_x) < self.tolerance:
                            if perp['y1'] <= main_y <= perp['y2'] or \
                               abs(perp['y1'] - main_y) < self.tolerance or \
                               abs(perp['y2'] - main_y) < self.tolerance:
                                right_perps.append(perp)
                    
                    # 检查是否至少有一端有垂直线
                    if not left_perps and not right_perps:
                        continue
                    
                    # 新策略：检查主边一端的两侧是否都有垂直线
                    # 如果一端的某一侧没有垂直线，则视图在另一侧
                    
                    # 统计左端的垂直线分布
                    left_above = [p for p in left_perps if p['y2'] > main_y + self.tolerance]
                    left_below = [p for p in left_perps if p['y1'] < main_y - self.tolerance]
                    
                    # 统计右端的垂直线分布
                    right_above = [p for p in right_perps if p['y2'] > main_y + self.tolerance]
                    right_below = [p for p in right_perps if p['y1'] < main_y - self.tolerance]
                    
                    logging.debug(
                        f"主边 y={main_y:.1f}, "
                        f"左端: 上方{len(left_above)}条/下方{len(left_below)}条, "
                        f"右端: 上方{len(right_above)}条/下方{len(right_below)}条"
                    )
                    
                    # 确定视图在哪一侧
                    # 优先检查左端
                    if len(left_above) > 0 and len(left_below) == 0:
                        # 左端只有上方有垂直线，视图在上方
                        min_y = main_y
                        max_y = main_y + perp_length
                        logging.debug(f"左端只有上方有垂直线 → 视图在主边上方")
                    elif len(left_above) == 0 and len(left_below) > 0:
                        # 左端只有下方有垂直线，视图在下方
                        min_y = main_y - perp_length
                        max_y = main_y
                        logging.debug(f"左端只有下方有垂直线 → 视图在主边下方")
                    # 如果左端两侧都有或都没有，检查右端
                    elif len(right_above) > 0 and len(right_below) == 0:
                        # 右端只有上方有垂直线，视图在上方
                        min_y = main_y
                        max_y = main_y + perp_length
                        logging.debug(f"右端只有上方有垂直线 → 视图在主边上方")
                    elif len(right_above) == 0 and len(right_below) > 0:
                        # 右端只有下方有垂直线，视图在下方
                        min_y = main_y - perp_length
                        max_y = main_y
                        logging.debug(f"右端只有下方有垂直线 → 视图在主边下方")
                    else:
                        # 两端都无法确定方向，跳过
                        logging.debug(f"无法确定视图方向（两端的垂直线分布不明确）")
                        continue
                    
                    # 构建边界
                    bounds = {
                        'min_x': left_x,
                        'max_x': right_x,
                        'min_y': min_y,
                        'max_y': max_y
                    }
                    
                else:
                    # 主边是垂直线，查找两端的水平线
                    top_y = main_line['y2']
                    bottom_y = main_line['y1']
                    main_x = main_line['x']
                    
                    # 查找顶端和底端的水平线
                    top_perps = []
                    bottom_perps = []
                    
                    for perp in perp_lines:
                        # 检查水平线是否在顶端附近
                        if abs(perp['y'] - top_y) < self.tolerance:
                            if perp['x1'] <= main_x <= perp['x2'] or \
                               abs(perp['x1'] - main_x) < self.tolerance or \
                               abs(perp['x2'] - main_x) < self.tolerance:
                                top_perps.append(perp)
                        
                        # 检查水平线是否在底端附近
                        if abs(perp['y'] - bottom_y) < self.tolerance:
                            if perp['x1'] <= main_x <= perp['x2'] or \
                               abs(perp['x1'] - main_x) < self.tolerance or \
                               abs(perp['x2'] - main_x) < self.tolerance:
                                bottom_perps.append(perp)
                    
                    # 检查是否至少有一端有水平线
                    if not top_perps and not bottom_perps:
                        continue
                    
                    # 新策略：检查主边一端的两侧是否都有水平线
                    # 如果一端的某一侧没有水平线，则视图在另一侧
                    
                    # 统计顶端的水平线分布
                    top_left = [p for p in top_perps if p['x1'] < main_x - self.tolerance]
                    top_right = [p for p in top_perps if p['x2'] > main_x + self.tolerance]
                    
                    # 统计底端的水平线分布
                    bottom_left = [p for p in bottom_perps if p['x1'] < main_x - self.tolerance]
                    bottom_right = [p for p in bottom_perps if p['x2'] > main_x + self.tolerance]
                    
                    logging.debug(
                        f"主边 x={main_x:.1f}, "
                        f"顶端: 左侧{len(top_left)}条/右侧{len(top_right)}条, "
                        f"底端: 左侧{len(bottom_left)}条/右侧{len(bottom_right)}条"
                    )
                    
                    # 确定视图在哪一侧
                    # 优先检查顶端
                    if len(top_right) > 0 and len(top_left) == 0:
                        # 顶端只有右侧有水平线，视图在右侧
                        min_x = main_x
                        max_x = main_x + perp_length
                        logging.debug(f"顶端只有右侧有水平线 → 视图在主边右侧")
                    elif len(top_right) == 0 and len(top_left) > 0:
                        # 顶端只有左侧有水平线，视图在左侧
                        min_x = main_x - perp_length
                        max_x = main_x
                        logging.debug(f"顶端只有左侧有水平线 → 视图在主边左侧")
                    # 如果顶端两侧都有或都没有，检查底端
                    elif len(bottom_right) > 0 and len(bottom_left) == 0:
                        # 底端只有右侧有水平线，视图在右侧
                        min_x = main_x
                        max_x = main_x + perp_length
                        logging.debug(f"底端只有右侧有水平线 → 视图在主边右侧")
                    elif len(bottom_right) == 0 and len(bottom_left) > 0:
                        # 底端只有左侧有水平线，视图在左侧
                        min_x = main_x - perp_length
                        max_x = main_x
                        logging.debug(f"底端只有左侧有水平线 → 视图在主边左侧")
                    else:
                        # 两端都无法确定方向，跳过
                        logging.debug(f"无法确定视图方向（两端的水平线分布不明确）")
                        continue
                    
                    # 构建边界
                    bounds = {
                        'min_x': min_x,
                        'max_x': max_x,
                        'min_y': bottom_y,
                        'max_y': top_y
                    }
                
                # 检查是否与已使用的边界重叠
                if self._bounds_overlaps_any(bounds, used_bounds):
                    continue
                
                # 验证边界尺寸
                width = bounds['max_x'] - bounds['min_x']
                height = bounds['max_y'] - bounds['min_y']
                
                logging.debug(
                    f"找到候选边界（单边+垂直线）: {width:.1f}×{height:.1f}mm, "
                    f"期望: {main_length:.1f}×{perp_length:.1f}mm"
                )
                
                # 检查尺寸是否匹配
                if (abs(width - main_length) <= self.tolerance and 
                    abs(height - perp_length) <= self.tolerance):
                    return bounds
                elif (abs(width - perp_length) <= self.tolerance and 
                      abs(height - main_length) <= self.tolerance):
                    return bounds
            
            return None
            
        except Exception as e:
            logging.debug(f"从单边线段构建边界失败: {e}")
            return None
    
    def _find_view_by_red_line_distribution(
        self,
        msp,
        dim_pairs: List[Tuple[float, float]],
        used_bounds: List[Dict]
    ) -> Optional[Dict]:
        """
        通过红色实线的分布范围识别视图（第三层兜底机制）
        
        适用场景：
        - 视图边框是红色实线（如圆角矩形）
        - 没有标准的矩形LWPOLYLINE
        - 没有明显的平行线对
        
        查找逻辑：
        1. 收集所有红色实线（颜色=1）
        2. 计算红色实线的分布范围
        3. 检查范围是否与期望尺寸匹配
        
        Args:
            msp: modelspace
            dim_pairs: 期望的尺寸对 [(width1, height1), (width2, height2)]
            used_bounds: 已使用的边界列表（避免重叠）
        
        Returns:
            Dict: 边界 {'min_x', 'max_x', 'min_y', 'max_y'} 或 None
        """
        try:
            # 收集所有红色实线
            red_entities = []
            
            for entity in msp:
                try:
                    # 检查颜色（1=红色, 220=黄色, 190=橙色 - 线割工艺）
                    entity_color = getattr(entity.dxf, 'color', 256)
                    if entity_color not in [1, 220, 190]:
                        continue
                    
                    # 检查线型（排除虚线等）
                    linetype = getattr(entity.dxf, 'linetype', 'ByLayer')
                    if linetype.lower() not in ['continuous', 'bylayer']:
                        continue
                    
                    entity_type = entity.dxftype()
                    
                    # 获取实体的边界点
                    points = []
                    
                    if entity_type == 'LINE':
                        start = entity.dxf.start
                        end = entity.dxf.end
                        points = [(start.x, start.y), (end.x, end.y)]
                    
                    elif entity_type in ['CIRCLE', 'ARC']:
                        center = entity.dxf.center
                        radius = entity.dxf.radius
                        # 圆/弧的边界框
                        points = [
                            (center.x - radius, center.y - radius),
                            (center.x + radius, center.y + radius)
                        ]
                    
                    elif entity_type in ['LWPOLYLINE', 'POLYLINE']:
                        pts = list(entity.get_points('xy'))
                        points = [(p[0], p[1]) for p in pts]
                    
                    if points:
                        red_entities.append({
                            'type': entity_type,
                            'points': points
                        })
                
                except Exception:
                    continue
            
            if not red_entities:
                logging.debug("兜底机制3: 未找到任何红色实线")
                return None
            
            logging.info(f"兜底机制3: 找到 {len(red_entities)} 个红色实体")
            
            # 计算所有红色实线的总体分布范围
            all_x = []
            all_y = []
            
            for entity in red_entities:
                for x, y in entity['points']:
                    all_x.append(x)
                    all_y.append(y)
            
            if not all_x or not all_y:
                logging.debug("兜底机制3: 红色实线没有有效坐标")
                return None
            
            # 计算边界
            min_x = min(all_x)
            max_x = max(all_x)
            min_y = min(all_y)
            max_y = max(all_y)
            
            width = max_x - min_x
            height = max_y - min_y
            
            logging.info(
                f"兜底机制3: 红色实线分布范围: {width:.1f}×{height:.1f}mm, "
                f"边界=[X: {min_x:.1f}~{max_x:.1f}, Y: {min_y:.1f}~{max_y:.1f}]"
            )
            
            # 尝试每个尺寸对
            for expected_w, expected_h in dim_pairs:
                logging.debug(
                    f"兜底机制3: 尝试匹配尺寸 {expected_w:.1f}×{expected_h:.1f}mm"
                )
                
                # 检查尺寸是否匹配（考虑两种方向，放宽容差到 20mm）
                tolerance = self.tolerance * 2  # 放宽容差
                
                if (abs(width - expected_w) <= tolerance and 
                    abs(height - expected_h) <= tolerance):
                    
                    bounds = {
                        'min_x': min_x,
                        'max_x': max_x,
                        'min_y': min_y,
                        'max_y': max_y
                    }
                    
                    # 检查是否与已使用的边界重叠
                    if self._bounds_overlaps_any(bounds, used_bounds):
                        logging.debug("兜底机制3: 边界与已使用的边界重叠")
                        continue
                    
                    logging.info(
                        f"兜底机制3: 尺寸匹配成功! "
                        f"实际: {width:.1f}×{height:.1f}mm, "
                        f"期望: {expected_w:.1f}×{expected_h:.1f}mm, "
                        f"差异: {abs(width - expected_w):.1f}×{abs(height - expected_h):.1f}mm"
                    )
                    
                    return bounds
                
                elif (abs(width - expected_h) <= tolerance and 
                      abs(height - expected_w) <= tolerance):
                    
                    bounds = {
                        'min_x': min_x,
                        'max_x': max_x,
                        'min_y': min_y,
                        'max_y': max_y
                    }
                    
                    # 检查是否与已使用的边界重叠
                    if self._bounds_overlaps_any(bounds, used_bounds):
                        logging.debug("兜底机制3: 边界与已使用的边界重叠")
                        continue
                    
                    logging.info(
                        f"兜底机制3: 尺寸匹配成功（交换方向）! "
                        f"实际: {width:.1f}×{height:.1f}mm, "
                        f"期望: {expected_h:.1f}×{expected_w:.1f}mm, "
                        f"差异: {abs(width - expected_h):.1f}×{abs(height - expected_w):.1f}mm"
                    )
                    
                    return bounds
            
            logging.debug("兜底机制3: 所有尺寸对都未能匹配")
            return None
            
        except Exception as e:
            logging.error(f"兜底机制3失败: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return None


    def _find_optimal_view_assignment(
        self,
        rectangles: List[Dict],
        view_dimensions: Dict[str, List[Tuple[float, float]]]
    ) -> Optional[Dict[str, Dict]]:
        """
        全局最优匹配算法 - 尝试所有可能的矩形-视图分配组合，选择总差异最小的方案
        
        Args:
            rectangles: 矩形列表
            view_dimensions: 视图尺寸字典 {view_name: [(w1, h1), (w2, h2)]}
        
        Returns:
            Dict: {view_name: {'bounds': ...}} 或 None
        """
        try:
            from itertools import combinations, permutations
            
            view_names = list(view_dimensions.keys())
            n_views = len(view_names)
            n_rects = len(rectangles)
            
            logging.info(f"全局最优匹配: {n_rects} 个矩形, {n_views} 个视图")
            
            # 如果没有矩形，直接返回
            if n_rects == 0:
                logging.warning("没有矩形可用于匹配")
                return None
            
            # 如果矩形数量少于视图数量，只匹配部分视图
            n_to_match = min(n_rects, n_views)
            
            # 1. 计算每个矩形与每个视图的匹配分数（最小差异）
            match_scores = {}  # {rect_idx: {view_name: (diff, dim_pair)}}
            
            for rect_idx, rect in enumerate(rectangles):
                match_scores[rect_idx] = {}
                
                for view_name, dim_pairs in view_dimensions.items():
                    best_diff = float('inf')
                    best_dim_pair = None
                    
                    for expected_w, expected_h in dim_pairs:
                        diff = abs(rect['width'] - expected_w) + abs(rect['height'] - expected_h)
                        
                        if diff < best_diff:
                            best_diff = diff
                            best_dim_pair = (expected_w, expected_h)
                    
                    match_scores[rect_idx][view_name] = (best_diff, best_dim_pair)
            
            # 2. 尝试所有可能的矩形-视图分配组合
            best_assignment = None
            best_total_diff = float('inf')
            tolerance = self.tolerance * 2
            
            # 遍历所有可能的视图组合（选择 n_to_match 个视图）
            from itertools import combinations as view_combinations
            
            for selected_views in view_combinations(view_names, n_to_match):
                # 遍历所有可能的矩形组合（选择 n_to_match 个矩形）
                for rect_combination in combinations(range(n_rects), n_to_match):
                    # 遍历这些矩形的所有排列（对应不同的视图分配）
                    for rect_permutation in permutations(rect_combination):
                        # 计算这个排列的总差异
                        total_diff = 0
                        assignment = {}
                        all_valid = True
                        
                        for view_idx, view_name in enumerate(selected_views):
                            rect_idx = rect_permutation[view_idx]
                            diff, dim_pair = match_scores[rect_idx][view_name]
                            
                            # 检查差异是否在容差内
                            if diff > tolerance:
                                all_valid = False
                                break
                            
                            total_diff += diff
                            assignment[view_name] = {
                                'rect_idx': rect_idx,
                                'rect': rectangles[rect_idx],
                                'diff': diff,
                                'dim_pair': dim_pair
                            }
                        
                        # 如果所有差异都在容差内，且总差异更小，记录这个方案
                        if all_valid and total_diff < best_total_diff:
                            best_total_diff = total_diff
                            best_assignment = assignment
            
            # 3. 返回最优分配
            if best_assignment:
                views = {}
                
                logging.info(f"✅ 找到最优分配方案，总差异={best_total_diff:.2f}mm:")
                
                for view_name, info in best_assignment.items():
                    views[view_name] = {'bounds': info['rect']['bounds']}
                    
                    logging.info(
                        f"  {view_name}: "
                        f"矩形 {info['rect_idx'] + 1} "
                        f"({info['rect']['width']:.1f}×{info['rect']['height']:.1f}mm), "
                        f"差异={info['diff']:.2f}mm, "
                        f"期望={info['dim_pair'][0]:.1f}×{info['dim_pair'][1]:.1f}mm"
                    )
                
                return views
            else:
                logging.warning("未找到有效的全局最优分配方案")
                return None
            
        except Exception as e:
            logging.error(f"全局最优匹配失败: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return None
    
    def _greedy_view_assignment(
        self,
        rectangles: List[Dict],
        view_dimensions: Dict[str, List[Tuple[float, float]]]
    ) -> Dict[str, Dict]:
        """
        贪心算法 - 按顺序为每个视图找到最佳匹配的矩形（原算法，作为后备）
        
        Args:
            rectangles: 矩形列表
            view_dimensions: 视图尺寸字典 {view_name: [(w1, h1), (w2, h2)]}
        
        Returns:
            Dict: {view_name: {'bounds': ...}}
        """
        views = {}
        used_rectangles = set()
        
        for view_name, dim_pairs in view_dimensions.items():
            best_match = None
            best_score = float('inf')
            best_idx = -1
            
            for idx, rect in enumerate(rectangles):
                if idx in used_rectangles:
                    continue
                
                rect_width = rect['width']
                rect_height = rect['height']
                
                # 尝试匹配每个尺寸对
                for expected_w, expected_h in dim_pairs:
                    diff = abs(rect_width - expected_w) + abs(rect_height - expected_h)
                    
                    if diff < best_score and diff <= self.tolerance * 2:
                        best_score = diff
                        best_match = rect
                        best_idx = idx
            
            if best_match:
                views[view_name] = {'bounds': best_match['bounds']}
                used_rectangles.add(best_idx)
                logging.info(
                    f"✅ 识别到{view_name}: "
                    f"矩形 {best_idx + 1} ({best_match['width']:.1f}×{best_match['height']:.1f}mm), "
                    f"差异={best_score:.2f}mm"
                )
            else:
                logging.warning(f"⚠️ 未找到匹配的 {view_name}")
        
        return views


    def _find_optimal_fallback_assignment(
        self,
        msp,
        view_dimensions: Dict[str, List[Tuple[float, float]]],
        used_bounds: List[Dict]
    ) -> Optional[Dict[str, Dict]]:
        """
        兜底机制的全局最优匹配 - 收集所有候选边界，尝试所有不重叠的组合，选择总差异最小的方案
        
        Args:
            msp: modelspace
            view_dimensions: 视图尺寸字典 {view_name: [(w1, h1), (w2, h2)]}
            used_bounds: 已使用的边界列表
        
        Returns:
            Dict: {view_name: bounds} 或 None
        """
        try:
            from itertools import combinations, permutations
            
            # 1. 收集所有可能的候选边界
            all_candidates = self._find_all_views_by_parallel_lines(msp, view_dimensions, used_bounds)
            
            if not all_candidates:
                logging.warning("未找到任何候选边界")
                return None
            
            # 统计候选数量
            total_candidates = sum(len(candidates) for candidates in all_candidates.values())
            logging.info(f"找到 {total_candidates} 个候选边界，使用全局最优匹配")
            
            # 2. 尝试所有可能的视图-边界分配组合
            view_names = list(view_dimensions.keys())
            n_views = len(view_names)
            
            best_assignment = None
            best_total_diff = float('inf')
            tolerance = self.tolerance * 2
            
            # 遍历所有可能的视图组合（如果候选不足，可能只能匹配部分视图）
            for n_to_match in range(n_views, 0, -1):
                for selected_views in combinations(view_names, n_to_match):
                    # 检查这些视图是否都有候选
                    if not all(view_name in all_candidates and all_candidates[view_name] for view_name in selected_views):
                        continue
                    
                    # 为每个视图选择一个候选边界的所有可能组合
                    candidate_lists = [all_candidates[view_name] for view_name in selected_views]
                    
                    # 使用笛卡尔积生成所有可能的候选组合
                    from itertools import product
                    for candidate_combination in product(*candidate_lists):
                        # 提取边界对象（candidate_combination 中每个元素是 {'bounds': ..., 'diff': ..., 'expected': ...}）
                        bounds_only = [candidate['bounds'] for candidate in candidate_combination]
                        
                        # 检查这些边界是否不重叠
                        if not self._bounds_no_overlap(bounds_only, used_bounds):
                            continue
                        
                        # 计算总差异
                        total_diff = sum(
                            candidate['diff'] 
                            for candidate in candidate_combination
                        )
                        
                        # 检查所有差异是否在容差内
                        all_valid = all(
                            candidate['diff'] <= tolerance 
                            for candidate in candidate_combination
                        )
                        
                        # 如果所有差异都在容差内，且总差异更小，记录这个方案
                        if all_valid and total_diff < best_total_diff:
                            best_total_diff = total_diff
                            best_assignment = {
                                view_name: candidate['bounds']
                                for view_name, candidate in zip(selected_views, candidate_combination)
                            }
            
            # 3. 返回最优分配
            if best_assignment:
                logging.info(f"✅ 找到最优兜底分配方案，总差异={best_total_diff:.2f}mm:")
                for view_name, bounds in best_assignment.items():
                    width = bounds['max_x'] - bounds['min_x']
                    height = bounds['max_y'] - bounds['min_y']
                    logging.info(f"  {view_name}: {width:.1f}×{height:.1f}mm")
                
                return best_assignment
            else:
                logging.warning("未找到有效的兜底分配方案")
                return None
                
        except Exception as e:
            logging.error(f"兜底机制全局最优匹配失败: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return None
    
    def _find_all_views_by_parallel_lines(
        self,
        msp,
        view_dimensions: Dict[str, List[Tuple[float, float]]],
        used_bounds: List[Dict]
    ) -> Dict[str, List[Dict]]:
        """
        查找所有可能的候选边界（不只是第一个）
        
        Args:
            msp: modelspace
            view_dimensions: 视图尺寸字典 {view_name: [(w1, h1), (w2, h2)]}
            used_bounds: 已使用的边界列表
        
        Returns:
            Dict: {view_name: [{'bounds': ..., 'diff': ...}, ...]}
        """
        try:
            # 收集所有 LINE 实体
            lines = list(msp.query('LINE'))
            
            if not lines:
                logging.debug("未找到任何 LINE 实体")
                return {}
            
            # 按水平和垂直分类
            horizontal_lines = []
            vertical_lines = []
            line_tolerance = 2.0
            
            for line in lines:
                start = line.dxf.start
                end = line.dxf.end
                
                dx = abs(end.x - start.x)
                dy = abs(end.y - start.y)
                
                if dy < line_tolerance and dx > 10:  # 水平线
                    horizontal_lines.append({
                        'y': (start.y + end.y) / 2,
                        'x1': min(start.x, end.x),
                        'x2': max(start.x, end.x),
                        'length': dx
                    })
                elif dx < line_tolerance and dy > 10:  # 垂直线
                    vertical_lines.append({
                        'x': (start.x + end.x) / 2,
                        'y1': min(start.y, end.y),
                        'y2': max(start.y, end.y),
                        'length': dy
                    })
            
            logging.debug(f"找到 {len(horizontal_lines)} 条水平线, {len(vertical_lines)} 条垂直线")
            
            # 为每个视图收集所有候选边界
            all_candidates = {}
            
            for view_name, dim_pairs in view_dimensions.items():
                candidates = []
                
                # 尝试每个尺寸对
                for expected_w, expected_h in dim_pairs:
                    # 尝试方案1：水平线对（距离为 height）+ 垂直线对（距离为 width）
                    bounds_list = self._try_find_all_bounds_from_lines(
                        horizontal_lines, vertical_lines,
                        expected_w, expected_h,
                        used_bounds
                    )
                    
                    for bounds in bounds_list:
                        width = bounds['max_x'] - bounds['min_x']
                        height = bounds['max_y'] - bounds['min_y']
                        diff = abs(width - expected_w) + abs(height - expected_h)
                        candidates.append({
                            'bounds': bounds,
                            'diff': diff,
                            'expected': (expected_w, expected_h)
                        })
                    
                    # 尝试方案2：垂直线对（距离为 height）+ 水平线对（距离为 width）
                    bounds_list = self._try_find_all_bounds_from_lines(
                        vertical_lines, horizontal_lines,
                        expected_h, expected_w,
                        used_bounds,
                        swap_axes=True
                    )
                    
                    for bounds in bounds_list:
                        width = bounds['max_x'] - bounds['min_x']
                        height = bounds['max_y'] - bounds['min_y']
                        diff = abs(width - expected_w) + abs(height - expected_h)
                        candidates.append({
                            'bounds': bounds,
                            'diff': diff,
                            'expected': (expected_w, expected_h)
                        })
                
                # 按差异排序，保留最好的候选
                candidates.sort(key=lambda x: x['diff'])
                all_candidates[view_name] = candidates[:10]  # 最多保留10个候选
                
                logging.debug(f"{view_name}: 找到 {len(candidates)} 个候选边界")
            
            return all_candidates
            
        except Exception as e:
            logging.error(f"查找所有候选边界失败: {e}")
            return {}
    
    def _try_find_all_bounds_from_lines(
        self,
        primary_lines: List[Dict],
        secondary_lines: List[Dict],
        primary_distance: float,
        secondary_distance: float,
        used_bounds: List[Dict],
        swap_axes: bool = False
    ) -> List[Dict]:
        """
        尝试从平行线对构建所有可能的边界（不只是第一个）
        
        Args:
            primary_lines: 主方向的线（用于确定主距离）
            secondary_lines: 次方向的线（用于确定次距离）
            primary_distance: 主方向的期望距离
            secondary_distance: 次方向的期望距离
            used_bounds: 已使用的边界
            swap_axes: 是否交换 x/y 轴
        
        Returns:
            List[Dict]: 所有可能的边界列表
        """
        all_bounds = []
        
        try:
            # 查找长度匹配的主方向线对
            for i, line1 in enumerate(primary_lines):
                # 检查线1的长度是否匹配次距离
                if abs(line1['length'] - secondary_distance) > self.tolerance:
                    continue
                
                for line2 in primary_lines[i+1:]:
                    # 检查线2的长度是否匹配次距离
                    if abs(line2['length'] - secondary_distance) > self.tolerance:
                        continue
                    
                    # 检查两条线是否平行且距离匹配主距离
                    if not swap_axes:
                        # 水平线：检查 y 方向距离
                        distance = abs(line1['y'] - line2['y'])
                        
                        if abs(distance - primary_distance) <= self.tolerance:
                            # 构建边界
                            bounds = {
                                'min_x': min(line1['x1'], line2['x1']),
                                'max_x': max(line1['x2'], line2['x2']),
                                'min_y': min(line1['y'], line2['y']),
                                'max_y': max(line1['y'], line2['y'])
                            }
                            
                            # 检查是否与已使用的边界重叠
                            if not self._bounds_overlaps_any(bounds, used_bounds):
                                all_bounds.append(bounds)
                    else:
                        # 垂直线：检查 x 方向距离
                        distance = abs(line1['x'] - line2['x'])
                        
                        if abs(distance - primary_distance) <= self.tolerance:
                            # 构建边界
                            bounds = {
                                'min_x': min(line1['x'], line2['x']),
                                'max_x': max(line1['x'], line2['x']),
                                'min_y': min(line1['y1'], line2['y1']),
                                'max_y': max(line1['y2'], line2['y2'])
                            }
                            
                            # 检查是否与已使用的边界重叠
                            if not self._bounds_overlaps_any(bounds, used_bounds):
                                all_bounds.append(bounds)
            
            return all_bounds
            
        except Exception as e:
            logging.error(f"构建所有边界失败: {e}")
            return []
    
    def _bounds_no_overlap(
        self,
        bounds_list: List[Dict],
        used_bounds: List[Dict]
    ) -> bool:
        """
        检查边界列表中的所有边界是否互不重叠，且不与已使用的边界重叠
        
        Args:
            bounds_list: 要检查的边界列表
            used_bounds: 已使用的边界列表
        
        Returns:
            bool: True 如果所有边界都不重叠
        """
        # 检查与已使用边界的重叠
        for bounds in bounds_list:
            if self._bounds_overlaps_any(bounds, used_bounds):
                return False
        
        # 检查边界列表内部的重叠
        for i, bounds1 in enumerate(bounds_list):
            for bounds2 in bounds_list[i+1:]:
                # 检查两个边界是否重叠
                if not (bounds1['max_x'] < bounds2['min_x'] or 
                        bounds2['max_x'] < bounds1['min_x'] or
                        bounds1['max_y'] < bounds2['min_y'] or 
                        bounds2['max_y'] < bounds1['min_y']):
                    return False
        
        return True
