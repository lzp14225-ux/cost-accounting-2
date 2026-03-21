# -*- coding: utf-8 -*-
"""
滑块工艺长度计算模块
在正常线割工艺计算完成后，检测并计算滑块工艺的长度和角度
"""
import logging
import math
from typing import Optional, Dict, List, Tuple, Any
from ezdxf.math import Vec3


class SliderCalculator:
    """滑块工艺计算器 - 检测并计算滑块工艺的长度和角度"""
    
    # 线割工艺颜色列表（001=红色, 220=黄色, 190=橙色）
    WIRE_CUT_COLORS = [1, 220, 190]
    
    # 角度容差（度）- 用于平行判断
    ANGLE_TOLERANCE = 1.0
    
    # 水平/垂直线排除容差（度）- 用于排除水平和垂直线
    HORIZONTAL_VERTICAL_TOLERANCE = 1.0
    
    def __init__(self):
        """初始化滑块工艺计算器"""
        pass
    
    def has_slider_process(self, wire_cut_details: List[Dict[str, Any]]) -> bool:
        """
        判断是否有滑块工艺
        
        规则：检查 wire_cut_details 中是否有 instruction 包含 '滑' 字的加工说明
        
        Args:
            wire_cut_details: 线割详情列表
        
        Returns:
            bool: 是否有滑块工艺
        """
        if not wire_cut_details:
            return False
        
        for detail in wire_cut_details:
            instruction = detail.get('instruction', '')
            if '滑' in instruction:
                code = detail.get('code', '')
                logging.info(f"检测到滑块工艺: 编号={code}, 说明={instruction}")
                return True
        
        return False
    
    def detect_inclined_parallel_lines(
        self, 
        msp, 
        bounds: Dict[str, float],
        min_length: float = 0.0
    ) -> List[Tuple[Dict, Dict]]:
        """
        检测视图中的倾斜平行线对（实线/虚线，颜色为 [1, 220, 190]）
        
        Args:
            msp: modelspace
            bounds: 视图边界 {'min_x', 'max_x', 'min_y', 'max_y'}
            min_length: 平行线对的最小长度要求（默认为0，不限制）
        
        Returns:
            List[Tuple[Dict, Dict]]: 倾斜平行线对列表，每对包含两条线的信息
                [({'entity': ..., 'angle': ..., 'length': ...}, {...}), ...]
        """
        # 1. 收集所有符合条件的线段（实线和虚线）
        lines = []
        
        try:
            for entity in msp:
                try:
                    # 只处理 LINE 类型
                    if entity.dxftype() != 'LINE':
                        continue
                    
                    # 检查颜色（1=红色, 220=黄色, 190=橙色）
                    entity_color = getattr(entity.dxf, 'color', 256)
                    if entity_color not in self.WIRE_CUT_COLORS:
                        continue
                    
                    # 检查线型（实线或虚线）
                    linetype = getattr(entity.dxf, 'linetype', 'ByLayer')
                    linetype_lower = linetype.lower()
                    
                    # 实线：continuous, bylayer
                    # 虚线：dashed, hidden, dashdot 等
                    is_solid = linetype_lower in ['continuous', 'bylayer']
                    is_dashed = linetype_lower in ['dashed', 'hidden', 'dashdot', 'dashdot2', 'center']
                    
                    if not (is_solid or is_dashed):
                        continue
                    
                    # 检查是否在边界内
                    start = entity.dxf.start
                    end = entity.dxf.end
                    center_x = (start.x + end.x) / 2
                    center_y = (start.y + end.y) / 2
                    
                    if not (bounds['min_x'] <= center_x <= bounds['max_x'] and 
                            bounds['min_y'] <= center_y <= bounds['max_y']):
                        continue
                    
                    # 使用 Vec3 计算角度（相对于水平线）
                    vec = Vec3(end) - Vec3(start)
                    angle_deg = vec.angle_deg
                    
                    # 归一化到 [0, 180) 范围
                    if angle_deg < 0:
                        angle_deg += 180
                    
                    # 转换为相对于水平线的最小角度 [0, 90]
                    # 如果角度 > 90°，则取 180° - angle
                    if angle_deg > 90:
                        angle_deg = 180 - angle_deg
                    
                    # 跳过接近水平或垂直的线（使用更小的容差）
                    if (abs(angle_deg) < self.HORIZONTAL_VERTICAL_TOLERANCE or 
                        abs(angle_deg - 90) < self.HORIZONTAL_VERTICAL_TOLERANCE):
                        logging.debug(f"排除水平/垂直线: 角度={angle_deg:.2f}°")
                        continue
                    
                    # 计算长度
                    length = vec.magnitude
                    
                    logging.debug(
                        f"收集倾斜线段: 角度={angle_deg:.2f}°, 长度={length:.2f}mm, "
                        f"线型={'实线' if is_solid else '虚线'}, 颜色={entity_color}"
                    )
                    
                    lines.append({
                        'entity': entity,
                        'angle': angle_deg,
                        'length': length,
                        'start': (start.x, start.y),
                        'end': (end.x, end.y),
                        'is_solid': is_solid,
                        'is_dashed': is_dashed
                    })
                    
                except Exception as e:
                    logging.debug(f"处理实体时出错: {e}")
                    continue
            
            logging.debug(f"在边界内找到 {len(lines)} 条倾斜线段（实线/虚线）")
            
        except Exception as e:
            logging.error(f"检测倾斜线段失败: {e}")
            return []
        
        # 2. 查找平行线对
        parallel_pairs = []
        filtered_count = 0  # 记录被长度过滤掉的平行线对数量
        
        for i in range(len(lines)):
            for j in range(i + 1, len(lines)):
                line1 = lines[i]
                line2 = lines[j]
                
                # 检查角度是否接近（平行）
                angle_diff = abs(line1['angle'] - line2['angle'])
                if angle_diff > self.ANGLE_TOLERANCE:
                    continue
                
                # 检查长度是否满足最小长度要求
                # 要求两条线中至少有一条的长度大于等于最小长度
                max_length = max(line1['length'], line2['length'])
                if min_length > 0 and max_length < min_length:
                    filtered_count += 1
                    logging.debug(
                        f"过滤短平行线对: 最大长度={max_length:.2f}mm < 最小要求={min_length:.2f}mm"
                    )
                    continue
                
                # 找到一对平行线（可以是实线+实线、虚线+虚线、实线+虚线）
                parallel_pairs.append((line1, line2))
                
                # 判断线型组合
                if line1['is_solid'] and line2['is_solid']:
                    line_type = "实线+实线"
                elif line1['is_dashed'] and line2['is_dashed']:
                    line_type = "虚线+虚线"
                else:
                    line_type = "实线+虚线"
                
                logging.debug(
                    f"找到平行线对({line_type}): 角度={line1['angle']:.2f}°, "
                    f"长度={line1['length']:.2f}mm / {line2['length']:.2f}mm"
                )
        
        if filtered_count > 0:
            logging.info(f"过滤掉 {filtered_count} 对长度不足的平行线对（最小长度要求: {min_length:.2f}mm）")
        
        logging.info(f"检测到 {len(parallel_pairs)} 对倾斜平行线")
        
        return parallel_pairs
    
    def calculate_slider_length(
        self, 
        parallel_pairs: List[Tuple[Dict, Dict]]
    ) -> float:
        """
        计算滑块工艺的总长度
        
        规则：取所有平行线对中较长的那条线的长度之和
        
        Args:
            parallel_pairs: 平行线对列表
        
        Returns:
            float: 滑块工艺总长度
        """
        if not parallel_pairs:
            return 0.0
        
        total_length = 0.0
        
        for line1, line2 in parallel_pairs:
            # 取较长的那条线
            max_length = max(line1['length'], line2['length'])
            total_length += max_length
        
        return total_length
    
    def calculate_slider_angle(
        self, 
        parallel_pairs: List[Tuple[Dict, Dict]]
    ) -> Optional[float]:
        """
        计算滑块工艺的角度
        
        规则：
        1. 取第一对平行线的角度（假设所有滑块平行线角度一致）
        2. 返回与水平线或垂直线的最小角度
        
        Args:
            parallel_pairs: 平行线对列表
        
        Returns:
            Optional[float]: 滑块角度（度），如果没有平行线对则返回 None
        """
        if not parallel_pairs:
            return None
        
        # 取第一对平行线的角度
        line1, _ = parallel_pairs[0]
        angle = line1['angle']
        
        # 计算与水平线或垂直线的最小角度
        # angle 已经在 [0, 90] 范围内
        # 与水平线的角度：angle
        # 与垂直线的角度：90 - angle
        # 取最小值
        angle_to_horizontal = angle
        angle_to_vertical = 90 - angle
        
        min_angle = min(angle_to_horizontal, angle_to_vertical)
        
        return round(min_angle, 2)
    
    def calculate_slider_process(
        self, 
        msp, 
        views: Dict[str, Dict],
        wire_cut_details: List[Dict[str, Any]],
        unmatched_red_lines: Optional[List[Dict]] = None,
        length: float = 0.0,
        width: float = 0.0,
        thickness: float = 0.0
    ) -> tuple:
        """
        计算滑块工艺的详细信息并覆盖原有的线割工艺数据
        
        逻辑：
        1. 检查 instruction 中是否有 '滑' 字的工艺
        2. 在侧视图/正视图中检测倾斜平行线对（用于计算角度）
        3. 平行线对长度必须大于长宽厚中的最小值
        4. 在俯视图中计算未被工艺编号匹配的线割实线总长度的一半（用于计算长度）
        5. 如果检测到平行线对但没有滑块工艺，自动创建一个 code='滑块' 的工艺
        
        Args:
            msp: modelspace
            views: 视图信息 {'top_view': {...}, 'front_view': {...}, 'side_view': {...}}
            wire_cut_details: 原始线割详情列表
            unmatched_red_lines: 【阶段6】工艺编号匹配后的未匹配线割实线列表
                格式: [{'view': 'top_view', 'bounds': {...}, 'lines': [...]}, ...]
                如果为 None，则使用旧逻辑重新计算（向后兼容）
            length: 零件长度（用于过滤平行线对）
            width: 零件宽度（用于过滤平行线对）
            thickness: 零件厚度（用于过滤平行线对）
        
        Returns:
            tuple: (updated_details, slider_anomaly, length_adjustment)
                updated_details: 更新后的线割详情列表（滑块工艺数据已覆盖或新增）
                slider_anomaly: 如果检测到滑块工艺，返回异常信息字典，否则返回 None
                length_adjustment: 俯视图线割长度调整值（新滑块长度 - 原滑块长度）
        """
        logging.info("")
        logging.info("=" * 80)
        logging.info("🔧 【滑块工艺计算】开始")
        logging.info("=" * 80)
        
        # 计算平行线对的最小长度要求（长宽厚中的最小值）
        min_length = 0.0
        if length > 0 and width > 0 and thickness > 0:
            min_length = min(length, width, thickness)
            logging.info(f"零件尺寸: 长={length:.2f}mm, 宽={width:.2f}mm, 厚={thickness:.2f}mm")
            logging.info(f"平行线对最小长度要求: {min_length:.2f}mm")
        else:
            logging.info("未提供零件尺寸，不限制平行线对长度")
        
        # 标记是否检测到滑块
        has_slider = False
        
        # 1. 查找 instruction 包含 '滑' 字的工艺编号
        slider_codes = []
        for detail in wire_cut_details:
            instruction = detail.get('instruction', '')
            if '滑' in instruction:
                code = detail.get('code', '')
                slider_codes.append(code)
                has_slider = True
        
        if slider_codes:
            logging.info(f"找到 {len(slider_codes)} 个滑块工艺编号: {slider_codes}")
        else:
            logging.info("未在 instruction 中找到滑块工艺，将检测倾斜平行线对")
        
        # 2. 在正视图或侧视图中检测倾斜平行线对（用于计算角度）
        # 注意：视图固定为 top_view，但角度从正视图或侧视图获取
        parallel_pairs = []
        angle_source_view = None
        
        # 优先检查侧视图
        if views.get('side_view'):
            bounds = views['side_view']['bounds']
            parallel_pairs = self.detect_inclined_parallel_lines(msp, bounds, min_length)
            if parallel_pairs:
                angle_source_view = 'side_view'
                logging.info(f"在侧视图中检测到 {len(parallel_pairs)} 对倾斜平行线")
        
        # 如果侧视图没有，检查正视图
        if not parallel_pairs and views.get('front_view'):
            bounds = views['front_view']['bounds']
            parallel_pairs = self.detect_inclined_parallel_lines(msp, bounds, min_length)
            if parallel_pairs:
                angle_source_view = 'front_view'
                logging.info(f"在正视图中检测到 {len(parallel_pairs)} 对倾斜平行线")
        
        # 如果都没有平行线对
        if not parallel_pairs:
            if slider_codes:
                logging.warning("未检测到倾斜平行线对，无法计算滑块工艺")
            else:
                logging.info("未检测到倾斜平行线对，无滑块工艺")
            return wire_cut_details, None, 0.0
        
        # 3. 计算滑块角度（与水平线或垂直线的最小角度）
        slider_angle = self.calculate_slider_angle(parallel_pairs)
        
        # 4. 滑块工艺的视图固定为俯视图
        slider_view = 'top_view'
        logging.info(f"滑块角度来源: {angle_source_view}, 角度={slider_angle}°")
        logging.info(f"滑块工艺视图固定为: {slider_view}")
        
        # 4. 计算滑块长度：俯视图中未匹配的线割实线总长度的一半
        slider_length = 0.0
        unmatched_total_length = 0.0  # 用于更新 top_view_wire_length
        
        # 优先使用传入的未匹配线割实线（来自阶段6的匹配结果）
        if unmatched_red_lines is not None:
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                logging.debug(f"收到 unmatched_red_lines，包含 {len(unmatched_red_lines)} 个视图")
                for view_data in unmatched_red_lines:
                    logging.debug(f"  视图 '{view_data['view']}': {len(view_data.get('lines', []))} 条未匹配线割实线")
            
            # 查找俯视图中的未匹配线割实线
            top_view_unmatched = None
            for view_data in unmatched_red_lines:
                if view_data['view'] == 'top_view':
                    top_view_unmatched = view_data
                    break
            
            if top_view_unmatched and top_view_unmatched['lines']:
                # 计算未匹配线割实线总长度
                unmatched_total_length = sum(line['length'] for line in top_view_unmatched['lines'])
                unmatched_count = len(top_view_unmatched['lines'])
                
                # 滑块长度 = 未匹配线割实线总长度的一半
                slider_length = unmatched_total_length / 2.0
                
                logging.info(f"俯视图中未匹配的线割实线: {unmatched_count} 条, 总长度={unmatched_total_length:.2f}mm")
                logging.info(f"滑块长度 = 总长度 / 2 = {slider_length:.2f}mm")
                logging.info(f"将 {unmatched_total_length:.2f}mm 添加到俯视图线割长度")
            else:
                if top_view_unmatched:
                    logging.warning(f"俯视图中没有未匹配的线割实线（lines 列表为空或不存在）")
                else:
                    logging.warning("未找到俯视图的未匹配线割实线数据")
        else:
            # 向后兼容：如果没有传入未匹配线割实线，使用旧逻辑（不推荐）
            logging.warning("⚠️ 未传入未匹配线割实线，使用旧逻辑计算（性能较低）")
            
            if views.get('top_view'):
                from .red_line_calculator import RedLineCalculator
                red_line_calculator = RedLineCalculator()
                
                top_view_bounds = views['top_view']['bounds']
                
                # 获取所有线割实线
                all_red_lines = red_line_calculator._get_all_red_lines_in_bounds(msp, top_view_bounds)
                
                # 从 wire_cut_details 中提取所有已匹配的线割实线ID
                matched_line_ids = set()
                for detail in wire_cut_details:
                    matched_ids = detail.get('matched_line_ids', [])
                    matched_line_ids.update(matched_ids)
                
                # 计算未匹配的线割实线总长度
                unmatched_total_length = 0.0
                unmatched_count = 0
                for line in all_red_lines:
                    if id(line['entity']) not in matched_line_ids:
                        unmatched_total_length += line['length']
                        unmatched_count += 1
                
                # 滑块长度 = 未匹配线割实线总长度的一半
                slider_length = unmatched_total_length / 2.0
                
                logging.info(f"俯视图中未匹配的线割实线: {unmatched_count} 条, 总长度={unmatched_total_length:.2f}mm")
                logging.info(f"滑块长度 = 总长度 / 2 = {slider_length:.2f}mm")
            else:
                logging.warning("无法计算滑块长度：缺少俯视图")
        
        logging.info(f"✅ 滑块工艺计算完成: 长度={slider_length:.2f}mm, 角度={slider_angle}°, 视图={slider_view}")
        
        # 5. 更新或新增滑块工艺数据
        updated_details = []
        slider_updated = False
        old_slider_length = 0.0  # 记录原滑块工艺长度
        
        for detail in wire_cut_details:
            instruction = detail.get('instruction', '')
            code = detail.get('code', '')
            
            if '滑' in instruction:
                # 记录原滑块工艺长度
                old_slider_length = detail.get('total_length', 0.0)
                
                # 覆盖已有的滑块工艺数据
                updated_detail = {
                    'code': code,
                    'cone': detail.get('cone', 'f'),
                    'view': slider_view,
                    'area_num': 0,
                    'instruction': detail.get('instruction', code),
                    'slider_angle': slider_angle,
                    'total_length': round(slider_length, 2),
                    'is_additional': detail.get('is_additional', False),
                    'matched_count': len(parallel_pairs),
                    'single_length': round(slider_length / len(parallel_pairs), 2) if parallel_pairs else 0.0,
                    'expected_count': detail.get('expected_count', 1)
                }
                
                logging.info(
                    f"✅ 更新滑块工艺 '{code}': "
                    f"长度={updated_detail['total_length']}mm, "
                    f"角度={updated_detail['slider_angle']}°, "
                    f"视图={updated_detail['view']}"
                )
                
                updated_details.append(updated_detail)
                slider_updated = True
            else:
                # 保留原有数据
                updated_details.append(detail)
        
        # 6. 如果没有滑块工艺但检测到平行线对，自动创建一个
        if not slider_updated and parallel_pairs:
            has_slider = True  # 标记检测到滑块
            
            new_slider = {
                'code': '滑块',
                'cone': 'f',
                'view': slider_view,
                'area_num': 0,
                'instruction': '滑块',
                'slider_angle': slider_angle,
                'total_length': round(slider_length, 2),
                'is_additional': True,  # 标记为自动检测的额外工艺
                'matched_count': len(parallel_pairs),
                'single_length': round(slider_length / len(parallel_pairs), 2) if parallel_pairs else 0.0,
                'expected_count': 1
            }
            
            updated_details.append(new_slider)
            
            logging.info(
                f"✅ 自动创建滑块工艺 'code=滑块': "
                f"长度={new_slider['total_length']}mm, "
                f"角度={new_slider['slider_angle']}°, "
                f"视图={new_slider['view']}"
            )
        
        logging.info("=" * 80)
        logging.info("✅ 【滑块工艺计算】完成")
        logging.info("=" * 80)
        logging.info("")
        
        # 计算需要添加到俯视图线割长度的差值
        # 差值 = 新滑块长度 - 原滑块长度
        length_adjustment = slider_length - old_slider_length
        
        if length_adjustment != 0:
            logging.info(
                f"📊 俯视图线割长度调整: 原滑块长度={old_slider_length:.2f}mm, "
                f"新滑块长度={slider_length:.2f}mm, 差值={length_adjustment:+.2f}mm"
            )
        
        # 如果检测到滑块，创建异常信息
        slider_anomaly = None
        if has_slider:
            slider_anomaly = {
                'type': 'slider_wire_cut_detected',
                'description': '该零件存在滑块线割工艺'
            }
        
        return updated_details, slider_anomaly, length_adjustment
