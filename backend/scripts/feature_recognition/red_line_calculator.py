# -*- coding: utf-8 -*-
"""
线割实线计算模块
计算指定边界内线割工艺实线的长度（支持001/220/190色号）
"""
import logging
import math
from typing import Optional, Dict, List, Tuple

# 导入封闭区域检测器
from .closed_area_detector import ClosedAreaDetector


class RedLineCalculator:
    """线割实线计算器 - 计算边界内线割工艺实线的总长度（支持001/220/190色号）"""
    
    # 线割工艺颜色列表（001=红色, 220=黄色, 190=橙色）
    WIRE_CUT_COLORS = [1, 220, 190]
    
    def __init__(self):
        """初始化线割实线计算器"""
        # 初始化封闭区域检测器
        self.closed_area_detector = ClosedAreaDetector()
    
    def detect_closed_areas(
        self, 
        red_lines: List[Dict], 
        expected_count: int = None,
        tolerance: float = 1.0  # 增大容差到 1mm
    ) -> int:
        """
        检测线割实线形成的封闭空间个数
        
        注意：此方法已迁移到 ClosedAreaDetector 模块，这里保留是为了向后兼容
        
        Args:
            red_lines: 线割实线列表 [{'entity': ..., 'length': ..., 'center': (x, y)}]
            expected_count: 工艺的期望数量（仅用于日志对比，不限制实际检测结果）
            tolerance: 端点连接容差（mm）
        
        Returns:
            封闭空间的实际个数
        """
        return self.closed_area_detector.detect_closed_areas(
            red_lines, 
            expected_count=expected_count,
            tolerance=tolerance
        )
    
    def _get_all_red_lines_in_bounds(
        self, 
        msp, 
        bounds: Dict
    ) -> List[Dict]:
        """
        获取指定边界内的所有线割工艺实线（不进行过滤）
        
        Args:
            msp: modelspace
            bounds: 边界范围
        
        Returns:
            线割实线列表 [{'entity': ..., 'length': ..., 'center': (x, y), 'start': (x, y), 'end': (x, y), 'type': str}]
        """
        red_lines = []
        
        try:
            for entity in msp:
                try:
                    # 检查颜色（1=红色, 220=黄色, 190=橙色 - 线割工艺）
                    entity_color = getattr(entity.dxf, 'color', 256)
                    if entity_color not in self.WIRE_CUT_COLORS:
                        continue
                    
                    # 检查线型
                    linetype = getattr(entity.dxf, 'linetype', 'ByLayer')
                    if linetype.lower() not in ['continuous', 'bylayer']:
                        continue
                    
                    # 检查实体是否在边界内
                    if not self._is_entity_in_bounds(entity, bounds):
                        continue
                    
                    # 计算长度和端点
                    entity_type = entity.dxftype()
                    length = 0.0
                    start_point = None
                    end_point = None
                    
                    if entity_type == 'LINE':
                        length = self._calculate_line_length(entity)
                        start = entity.dxf.start
                        end = entity.dxf.end
                        start_point = (start.x, start.y)
                        end_point = (end.x, end.y)
                        
                    elif entity_type == 'CIRCLE':
                        length = self._calculate_circle_length(entity)
                        # 圆没有起点和终点
                        start_point = None
                        end_point = None
                        
                    elif entity_type == 'ARC':
                        length = self._calculate_arc_length(entity)
                        # 弧线的起点和终点
                        center = entity.dxf.center
                        radius = entity.dxf.radius
                        start_angle = math.radians(entity.dxf.start_angle)
                        end_angle = math.radians(entity.dxf.end_angle)
                        start_point = (
                            center.x + radius * math.cos(start_angle),
                            center.y + radius * math.sin(start_angle)
                        )
                        end_point = (
                            center.x + radius * math.cos(end_angle),
                            center.y + radius * math.sin(end_angle)
                        )
                        
                    elif entity_type in ['LWPOLYLINE', 'POLYLINE']:
                        length = self._calculate_polyline_length(entity)
                        points = list(entity.get_points('xy'))
                        if points:
                            start_point = (points[0][0], points[0][1])
                            end_point = (points[-1][0], points[-1][1])
                    
                    if length > 0:
                        center = self._get_entity_center(entity)
                        red_lines.append({
                            'entity': entity,
                            'length': length,
                            'center': center,
                            'start': start_point,
                            'end': end_point,
                            'type': entity_type
                        })
                        
                except Exception:
                    continue
            
        except Exception as e:
            logging.error(f"获取边界内线割实线失败: {str(e)}")
        
        return red_lines
    
    def calculate_red_lines_in_bounds(
        self, 
        msp, 
        bounds: Dict, 
        wire_cut_filter,
        wire_cut_info: Optional[Dict[str, int]] = None,
        processing_instructions: Optional[Dict[str, str]] = None,
        return_count: bool = False
    ) -> any:
        """
        计算指定边界内的线割工艺实线总长度
        
        Args:
            msp: modelspace
            bounds: 边界范围
            wire_cut_filter: 线割过滤器实例
            wire_cut_info: 线割工艺编号及数量 {code: count}，如果提供则只计算与这些编号配对的线割实线
            processing_instructions: 加工说明字典 {code: instruction}，用于判断是否为孔工艺
            return_count: 是否返回线割实线数量和编号出现次数
        
        Returns:
            如果 return_count=False: 返回线割实线总长度 (float)
            如果 return_count=True: 返回 (总长度, 线割实线数量, 编号出现次数字典, 配对失败列表, 每个编号对应的线割实线字典) (tuple)
        """
        # 1. 收集所有符合初步条件的线割工艺实线（包含起点和终点信息）
        red_lines = []
        
        try:
            for entity in msp:
                try:
                    # 检查颜色（1=红色, 220=黄色, 190=橙色 - 线割工艺）
                    entity_color = getattr(entity.dxf, 'color', 256)
                    if entity_color not in self.WIRE_CUT_COLORS:
                        continue
                    
                    # 检查线型
                    linetype = getattr(entity.dxf, 'linetype', 'ByLayer')
                    if linetype.lower() not in ['continuous', 'bylayer']:
                        continue
                    
                    # 检查实体是否在边界内
                    if not self._is_entity_in_bounds(entity, bounds):
                        continue
                    
                    # 计算长度和端点
                    entity_type = entity.dxftype()
                    length = 0.0
                    start_point = None
                    end_point = None
                    
                    if entity_type == 'LINE':
                        length = self._calculate_line_length(entity)
                        start = entity.dxf.start
                        end = entity.dxf.end
                        start_point = (start.x, start.y)
                        end_point = (end.x, end.y)
                        
                    elif entity_type == 'CIRCLE':
                        length = self._calculate_circle_length(entity)
                        # 圆没有起点和终点
                        start_point = None
                        end_point = None
                        
                    elif entity_type == 'ARC':
                        length = self._calculate_arc_length(entity)
                        # 弧线的起点和终点
                        center_pt = entity.dxf.center
                        radius = entity.dxf.radius
                        start_angle = math.radians(entity.dxf.start_angle)
                        end_angle = math.radians(entity.dxf.end_angle)
                        start_point = (
                            center_pt.x + radius * math.cos(start_angle),
                            center_pt.y + radius * math.sin(start_angle)
                        )
                        end_point = (
                            center_pt.x + radius * math.cos(end_angle),
                            center_pt.y + radius * math.sin(end_angle)
                        )
                        
                    elif entity_type in ['LWPOLYLINE', 'POLYLINE']:
                        length = self._calculate_polyline_length(entity)
                        points = list(entity.get_points('xy'))
                        if points:
                            start_point = (points[0][0], points[0][1])
                            end_point = (points[-1][0], points[-1][1])
                    
                    if length > 0:
                        center = self._get_entity_center(entity)
                        red_lines.append({
                            'entity': entity,
                            'length': length,
                            'center': center,
                            'start': start_point,
                            'end': end_point,
                            'type': entity_type
                        })
                        
                except Exception:
                    continue
            
            logging.debug(f"边界内找到 {len(red_lines)} 条线割实线（初步筛选）")
            
            # 2. 使用线割过滤器进行过滤（统计编号出现次数和配对失败信息）
            filtered_lines, code_occurrences, count_mismatches, code_matched_lines = wire_cut_filter.filter_red_lines_and_count_occurrences(
                msp, bounds, red_lines, wire_cut_info, processing_instructions
            )
            
            # 3. 计算过滤后的线割实线总长度
            total_length = sum(line['length'] for line in filtered_lines)
            red_line_count = len(filtered_lines)
            
            logging.debug(f"最终计算: {red_line_count} 条线割实线, 总长度: {total_length:.2f}mm")
            
            if return_count:
                return float(total_length), red_line_count, code_occurrences, count_mismatches, code_matched_lines
            else:
                return float(total_length)
            
        except Exception as e:
            logging.error(f"计算边界内线割实线长度失败: {str(e)}")
            if return_count:
                return 0.0, 0, {}, [], {}
            else:
                return 0.0
    
    def _is_entity_in_bounds(self, entity, bounds: Dict) -> bool:
        """判断实体是否在边界内"""
        try:
            center = self._get_entity_center(entity)
            if not center:
                return False
            
            x, y = center
            return (bounds['min_x'] <= x <= bounds['max_x'] and 
                    bounds['min_y'] <= y <= bounds['max_y'])
        except Exception:
            return False

    def _get_entity_center(self, entity) -> Optional[Tuple[float, float]]:
        """获取实体中心点"""
        try:
            entity_type = entity.dxftype()
            
            if entity_type == 'LINE':
                start = entity.dxf.start
                end = entity.dxf.end
                return ((start.x + end.x) / 2, (start.y + end.y) / 2)
            
            elif entity_type in ['CIRCLE', 'ARC']:
                center = entity.dxf.center
                return (center.x, center.y)
            
            elif entity_type in ['LWPOLYLINE', 'POLYLINE']:
                points = list(entity.get_points('xy'))
                if points:
                    xs = [p[0] for p in points]
                    ys = [p[1] for p in points]
                    return (sum(xs) / len(xs), sum(ys) / len(ys))
            
        except Exception:
            pass
        
        return None

    def _calculate_line_length(self, entity) -> float:
        """计算直线长度"""
        try:
            start = entity.dxf.start
            end = entity.dxf.end
            return math.sqrt(
                (end.x - start.x)**2 + 
                (end.y - start.y)**2 + 
                (end.z - start.z)**2
            )
        except Exception:
            return 0.0
    
    def _calculate_circle_length(self, entity) -> float:
        """计算圆周长"""
        try:
            radius = entity.dxf.radius
            return 2 * math.pi * radius
        except Exception:
            return 0.0
    
    def _calculate_arc_length(self, entity) -> float:
        """
        计算圆弧长度
        
        公式: r × angle_diff (角度需转换为弧度)
        
        注意: 正确处理跨越 0° 的弧线（如从 90° 到 -180°）
        """
        try:
            radius = entity.dxf.radius
            start_angle = entity.dxf.start_angle  # 度数
            end_angle = entity.dxf.end_angle      # 度数
            
            # 计算角度差（度数）
            angle_diff = end_angle - start_angle
            
            # 处理跨越 0° 的情况
            if angle_diff < 0:
                angle_diff += 360
            
            # 转换为弧度并计算弧长
            angle_rad = math.radians(angle_diff)
            length = radius * angle_rad
            return length
        except Exception:
            return 0.0
    
    def _calculate_polyline_length(self, entity) -> float:
        """
        计算多段线长度
        
        策略：
        1. 优先使用 virtual_entities() 炸开法（最准确，自动处理闭合和bulge）
        2. 如果炸开失败，使用手动计算法（兼容性备用）
        """
        try:
            # 方法1：炸开法（推荐）
            return self._calculate_polyline_by_explode(entity)
        except Exception as e:
            logging.debug(f"[多段线长度] 炸开法失败，使用手动计算: {e}")
            # 方法2：手动计算法（备用）
            return self._calculate_polyline_by_vertices(entity)
    
    def _calculate_polyline_by_explode(self, entity) -> float:
        """使用 virtual_entities() 炸开多段线并计算长度"""
        exploded_entities = list(entity.virtual_entities())
        
        if not exploded_entities:
            return 0.0
        
        total_length = 0.0
        
        for sub_entity in exploded_entities:
            sub_type = sub_entity.dxftype()
            
            if sub_type == 'LINE':
                length = sub_entity.dxf.start.distance(sub_entity.dxf.end)
            elif sub_type == 'ARC':
                radius = sub_entity.dxf.radius
                angle_diff = sub_entity.dxf.end_angle - sub_entity.dxf.start_angle
                if angle_diff < 0:
                    angle_diff += 360
                length = radius * math.radians(angle_diff)
            else:
                length = 0.0
            
            total_length += length
        
        return total_length
    
    def _calculate_polyline_by_vertices(self, entity) -> float:
        """手动计算多段线长度（备用方法）"""
        entity_type = entity.dxftype()
        
        if entity_type == 'LWPOLYLINE':
            return self._calculate_lwpolyline_manual(entity)
        else:
            return self._calculate_polyline_manual(entity)
    
    def _calculate_lwpolyline_manual(self, entity) -> float:
        """手动计算 LWPOLYLINE 长度"""
        points_with_bulge = list(entity.get_points('xyseb'))
        
        if len(points_with_bulge) < 2:
            return 0.0
        
        total_length = 0.0
        
        for i in range(len(points_with_bulge) - 1):
            p1 = points_with_bulge[i]
            p2 = points_with_bulge[i + 1]
            
            x1, y1 = p1[0], p1[1]
            x2, y2 = p2[0], p2[1]
            bulge = p1[4] if len(p1) > 4 else 0.0
            
            if abs(bulge) < 1e-6:
                seg_len = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
            else:
                angle = 4 * math.atan(abs(bulge))
                chord_length = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
                
                if chord_length < 1e-6:
                    seg_len = 0.0
                else:
                    radius = chord_length / (2 * math.sin(angle / 2))
                    seg_len = radius * angle
            
            total_length += seg_len
        
        # 检查闭合边
        is_closed = getattr(entity.dxf, 'closed', False)
        last_bulge = points_with_bulge[-1][4] if len(points_with_bulge[-1]) > 4 else 0.0
        
        if is_closed or abs(last_bulge) > 1e-6:
            p1 = points_with_bulge[-1]
            p2 = points_with_bulge[0]
            
            x1, y1 = p1[0], p1[1]
            x2, y2 = p2[0], p2[1]
            
            if abs(last_bulge) < 1e-6:
                seg_len = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
            else:
                angle = 4 * math.atan(abs(last_bulge))
                chord_length = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
                
                if chord_length >= 1e-6:
                    radius = chord_length / (2 * math.sin(angle / 2))
                    seg_len = radius * angle
                else:
                    seg_len = 0.0
            
            total_length += seg_len
        
        return total_length
    
    def _calculate_polyline_manual(self, entity) -> float:
        """手动计算普通 POLYLINE 长度"""
        points = list(entity.get_points('xyz'))
        
        if len(points) < 2:
            return 0.0
        
        total_length = 0.0
        
        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i + 1]
            
            if isinstance(p1, tuple):
                x1, y1, z1 = p1[0], p1[1], p1[2] if len(p1) > 2 else 0
                x2, y2, z2 = p2[0], p2[1], p2[2] if len(p2) > 2 else 0
            else:
                x1, y1, z1 = p1.x, p1.y, getattr(p1, 'z', 0)
                x2, y2, z2 = p2.x, p2.y, getattr(p2, 'z', 0)
            
            segment_length = math.sqrt(
                (x2 - x1)**2 + (y2 - y1)**2 + (z2 - z1)**2
            )
            total_length += segment_length
        
        # 检查闭合边
        is_closed = getattr(entity.dxf, 'closed', False)
        
        if is_closed and len(points) > 2:
            p1, p2 = points[-1], points[0]
            
            if isinstance(p1, tuple):
                x1, y1, z1 = p1[0], p1[1], p1[2] if len(p1) > 2 else 0
                x2, y2, z2 = p2[0], p2[1], p2[2] if len(p2) > 2 else 0
            else:
                x1, y1, z1 = p1.x, p1.y, getattr(p1, 'z', 0)
                x2, y2, z2 = p2.x, p2.y, getattr(p2, 'z', 0)
            
            segment_length = math.sqrt(
                (x2 - x1)**2 + 
                (y2 - y1)**2 + 
                (z2 - z1)**2
            )
            total_length += segment_length
        
        return total_length
