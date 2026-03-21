# -*- coding: utf-8 -*-
"""
线割实线与板料线重合过滤模块
在计算完线割工艺长度后，检测线割实线与板料线的重合部分，
将重合的线段从线割长度中扣除，更新工艺长度
"""
import logging
import math
from typing import Dict, List, Tuple, Optional


class WirePlateOverlapFilter:
    """线割实线与板料线重合过滤器"""
    
    PLATE_LINE_COLOR = 252
    WIRE_CUT_COLORS = [1, 220, 190]
    
    def __init__(self, overlap_tolerance: float = 0.5):
        self.overlap_tolerance = overlap_tolerance
    
    def filter_overlapping_wire_cuts(self, doc, wire_cut_details: List[Dict], views: Dict[str, Dict], 
                                    has_auto_material: bool = False, has_material_preparation: str = None) -> Tuple[List[Dict], Dict[str, float]]:
        """
        过滤线割实线与板料线重合的部分，更新工艺长度
        
        Args:
            doc: DXF文档对象
            wire_cut_details: 线割工艺详情列表
            views: 视图信息字典
            has_auto_material: 是否是自找料
            has_material_preparation: 备料信息（如果有值表示是备料件）
        
        Returns:
            Tuple[List[Dict], Dict[str, float]]: 更新后的工艺详情和视图长度调整
        """
        try:
            # 前置判断：如果是自找料或备料件，跳过重合检测
            is_material_prep = has_material_preparation is not None and has_material_preparation.strip() != ''
            
            if has_auto_material or is_material_prep:
                logging.info("")
                logging.info("=" * 80)
                logging.info("🔍 【阶段7.5】线割实线与板料线重合检测")
                logging.info("=" * 80)
                
                if has_auto_material:
                    logging.info("⏭️ 跳过重合检测: 该零件是自找料")
                if is_material_prep:
                    logging.info(f"⏭️ 跳过重合检测: 该零件是备料件（备料于{has_material_preparation}）")
                
                logging.info("✅ 保持原始线割长度，无需扣除重合部分")
                return wire_cut_details, {}
            
            msp = doc.modelspace()
            logging.info("")
            logging.info("=" * 80)
            logging.info("🔍 【阶段7.5】线割实线与板料线重合检测")
            logging.info("=" * 80)
            
            plate_lines = self._collect_plate_lines(msp)
            if not plate_lines:
                logging.info("未找到板料线，跳过重合检测")
                return wire_cut_details, {}
            
            logging.info(f"找到 {len(plate_lines)} 条板料线")
            
            view_length_adjustments = {
                'top_view_wire_length': 0.0,
                'front_view_wire_length': 0.0,
                'side_view_wire_length': 0.0
            }
            
            updated_details = []
            
            for detail in wire_cut_details:
                code = detail['code']
                view_name = detail.get('view')
                
                if not view_name or view_name not in views:
                    updated_details.append(detail)
                    continue
                
                bounds = views[view_name]['bounds']
                
                # 获取该工艺匹配的线割实线ID列表
                matched_line_ids = detail.get('matched_line_ids', [])
                
                if not matched_line_ids:
                    # 如果没有匹配的线割实线ID，跳过
                    logging.debug(f"   工艺 '{code}' 没有匹配的线割实线ID，跳过重合检测")
                    updated_details.append(detail)
                    continue
                
                # 只收集该工艺匹配的线割实线
                wire_lines = self._collect_wire_lines_by_ids(msp, bounds, matched_line_ids)
                
                if not wire_lines:
                    logging.debug(f"   工艺 '{code}' 没有收集到线割实线，跳过重合检测")
                    updated_details.append(detail)
                    continue
                
                logging.info(f"🔍 检测工艺 '{code}' 在 {view_name} 中的线割实线与板料线是否重合")
                logging.debug(f"   工艺 '{code}' 有 {len(matched_line_ids)} 个匹配的线割实线ID，收集到 {len(wire_lines)} 条线段")
                
                overlapping_length = self._calculate_overlapping_length(wire_lines, plate_lines, code)
                
                if overlapping_length > 0:
                    # 限制重合长度不超过工艺的原始长度
                    overlapping_length = min(overlapping_length, detail['total_length'])
                    
                    # 更新工艺长度
                    new_total_length = max(0.0, detail['total_length'] - overlapping_length)
                    matched_count = detail.get('matched_count', 1)
                    new_single_length = new_total_length / matched_count if matched_count > 0 else 0.0
                    
                    updated_detail = detail.copy()
                    updated_detail['total_length'] = round(new_total_length, 2)
                    updated_detail['single_length'] = round(new_single_length, 2)
                    updated_detail['overlapping_length'] = round(overlapping_length, 2)
                    
                    updated_details.append(updated_detail)
                    
                    view_field = f"{view_name}_wire_length"
                    if view_field in view_length_adjustments:
                        view_length_adjustments[view_field] -= overlapping_length
                    
                    logging.info(
                        f"✅ 工艺 '{code}' 在 {view_name} 中扣除重合长度 {overlapping_length:.2f}mm, "
                        f"原长度 {detail['total_length']:.2f}mm → 新长度 {new_total_length:.2f}mm"
                    )
                else:
                    # 没有重合，保持原样，不输出日志
                    updated_details.append(detail)
            
            total_adjustment = sum(abs(v) for v in view_length_adjustments.values())
            if total_adjustment > 0:
                logging.info("")
                logging.info("📊 视图线割长度调整汇总:")
                for view_field, adjustment in view_length_adjustments.items():
                    if adjustment != 0:
                        logging.info(f"   {view_field}: {adjustment:.2f}mm")
            else:
                logging.info("✅ 所有工艺均无重合，无需调整")
            
            return updated_details, view_length_adjustments
            
        except Exception as e:
            logging.error(f"线割实线与板料线重合检测失败: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return wire_cut_details, {}
    
    def _collect_plate_lines(self, msp) -> List[Dict]:
        plate_lines = []
        try:
            for entity in msp:
                try:
                    entity_color = getattr(entity.dxf, 'color', 256)
                    if entity_color != self.PLATE_LINE_COLOR:
                        continue
                    linetype = getattr(entity.dxf, 'linetype', 'ByLayer')
                    if linetype.lower() not in ['dashed', 'acad_iso02w100', 'acad_iso10w100']:
                        continue
                    segments = self._extract_line_segments(entity)
                    if segments:
                        plate_lines.extend(segments)
                except Exception:
                    continue
        except Exception as e:
            logging.error(f"收集板料线失败: {str(e)}")
        return plate_lines
    
    def _collect_wire_lines_by_ids(self, msp, bounds: Dict, matched_line_ids: List[int]) -> List[Dict]:
        """
        收集指定ID的线割实线
        
        Args:
            msp: modelspace
            bounds: 视图边界
            matched_line_ids: 匹配的线割实线实体ID列表
        
        Returns:
            List[Dict]: 线割实线列表
        """
        wire_lines = []
        matched_line_ids_set = set(matched_line_ids)
        
        try:
            for entity in msp:
                try:
                    # 检查实体ID是否在匹配列表中
                    if id(entity) not in matched_line_ids_set:
                        continue
                    
                    # 检查颜色（线割工艺颜色）
                    entity_color = getattr(entity.dxf, 'color', 256)
                    if entity_color not in self.WIRE_CUT_COLORS:
                        continue
                    
                    # 检查线型（实线）
                    linetype = getattr(entity.dxf, 'linetype', 'ByLayer')
                    if linetype.lower() not in ['continuous', 'bylayer']:
                        continue
                    
                    # 检查是否在视图边界内
                    if not self._is_entity_in_bounds(entity, bounds):
                        continue
                    
                    # 提取线段
                    segments = self._extract_line_segments(entity)
                    
                    if segments:
                        wire_lines.extend(segments)
                        
                except Exception:
                    continue
            
        except Exception as e:
            logging.error(f"收集指定ID的线割实线失败: {str(e)}")
        
        return wire_lines
    
    def _collect_wire_lines_in_view(self, msp, bounds: Dict) -> List[Dict]:
        wire_lines = []
        try:
            for entity in msp:
                try:
                    entity_color = getattr(entity.dxf, 'color', 256)
                    if entity_color not in self.WIRE_CUT_COLORS:
                        continue
                    linetype = getattr(entity.dxf, 'linetype', 'ByLayer')
                    if linetype.lower() not in ['continuous', 'bylayer']:
                        continue
                    if not self._is_entity_in_bounds(entity, bounds):
                        continue
                    segments = self._extract_line_segments(entity)
                    if segments:
                        wire_lines.extend(segments)
                except Exception:
                    continue
        except Exception as e:
            logging.error(f"收集视图中的线割实线失败: {str(e)}")
        return wire_lines
    
    def _extract_line_segments(self, entity) -> List[Dict]:
        segments = []
        entity_type = entity.dxftype()
        try:
            if entity_type == 'LINE':
                start = entity.dxf.start
                end = entity.dxf.end
                length = math.sqrt((end.x - start.x)**2 + (end.y - start.y)**2)
                segments.append({'start': (start.x, start.y), 'end': (end.x, end.y), 'length': length, 'type': 'LINE'})
            elif entity_type in ['LWPOLYLINE', 'POLYLINE']:
                try:
                    exploded_entities = list(entity.virtual_entities())
                    for sub_entity in exploded_entities:
                        sub_type = sub_entity.dxftype()
                        if sub_type == 'LINE':
                            start = sub_entity.dxf.start
                            end = sub_entity.dxf.end
                            length = start.distance(end)
                            segments.append({'start': (start.x, start.y), 'end': (end.x, end.y), 'length': length, 'type': 'LINE'})
                except Exception as e:
                    logging.debug(f"炸开多段线失败: {e}")
        except Exception as e:
            logging.debug(f"提取线段失败: {e}")
        return segments
    
    def _calculate_overlapping_length(self, wire_lines: List[Dict], plate_lines: List[Dict], code: str) -> float:
        total_overlapping_length = 0.0
        for wire_line in wire_lines:
            for plate_line in plate_lines:
                overlap_length = self._calculate_segment_overlap(wire_line, plate_line)
                if overlap_length > 0:
                    total_overlapping_length += overlap_length
                    logging.debug(f"   工艺 '{code}' 的线段 {wire_line['start']} → {wire_line['end']} 与板料线 {plate_line['start']} → {plate_line['end']} 重合 {overlap_length:.2f}mm")
        return total_overlapping_length
    
    def _calculate_segment_overlap(self, seg1: Dict, seg2: Dict) -> float:
        if seg1['type'] != 'LINE' or seg2['type'] != 'LINE':
            return 0.0
        p1_start = seg1['start']
        p1_end = seg1['end']
        p2_start = seg2['start']
        p2_end = seg2['end']
        if not self._are_segments_collinear(p1_start, p1_end, p2_start, p2_end):
            return 0.0
        dx1 = abs(p1_end[0] - p1_start[0])
        dy1 = abs(p1_end[1] - p1_start[1])
        if dx1 > dy1:
            seg1_min = min(p1_start[0], p1_end[0])
            seg1_max = max(p1_start[0], p1_end[0])
            seg2_min = min(p2_start[0], p2_end[0])
            seg2_max = max(p2_start[0], p2_end[0])
        else:
            seg1_min = min(p1_start[1], p1_end[1])
            seg1_max = max(p1_start[1], p1_end[1])
            seg2_min = min(p2_start[1], p2_end[1])
            seg2_max = max(p2_start[1], p2_end[1])
        overlap_min = max(seg1_min, seg2_min)
        overlap_max = min(seg1_max, seg2_max)
        if overlap_max > overlap_min:
            return overlap_max - overlap_min
        else:
            return 0.0
    
    def _are_segments_collinear(self, p1_start: Tuple[float, float], p1_end: Tuple[float, float], p2_start: Tuple[float, float], p2_end: Tuple[float, float]) -> bool:
        dx = p1_end[0] - p1_start[0]
        dy = p1_end[1] - p1_start[1]
        length = math.sqrt(dx**2 + dy**2)
        if length < 1e-6:
            return False
        dx /= length
        dy /= length
        dist1 = self._point_to_line_distance(p2_start, p1_start, dx, dy)
        dist2 = self._point_to_line_distance(p2_end, p1_start, dx, dy)
        return dist1 < self.overlap_tolerance and dist2 < self.overlap_tolerance
    
    def _point_to_line_distance(self, point: Tuple[float, float], line_point: Tuple[float, float], line_dx: float, line_dy: float) -> float:
        vx = point[0] - line_point[0]
        vy = point[1] - line_point[1]
        distance = abs(vx * line_dy - vy * line_dx)
        return distance
    
    def _is_entity_in_bounds(self, entity, bounds: Dict) -> bool:
        try:
            center = self._get_entity_center(entity)
            if not center:
                return False
            x, y = center
            return (bounds['min_x'] <= x <= bounds['max_x'] and bounds['min_y'] <= y <= bounds['max_y'])
        except Exception:
            return False
    
    def _get_entity_center(self, entity) -> Optional[Tuple[float, float]]:
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
