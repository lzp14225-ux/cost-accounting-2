# -*- coding: utf-8 -*-
"""
空间线割分析器
基于几何特征识别描述性线割工艺（如"两头"、"四周"、"外形"等）
不依赖预设尺寸，通过连通性分析和几何特征提取实现智能识别
"""
import logging
import math
from typing import List, Dict, Optional, Tuple


class SpatialWireCutAnalyzer:
    """空间线割分析器 - 识别描述性线割工艺"""
    
    # 空间关键词映射
    SPATIAL_KEYWORDS = {
        '两头': 'two_ends',
        '四周': 'perimeter',
        '外形': 'outline',
        '中间': 'center',
        '左': 'left',
        '右': 'right',
        '上': 'top',
        '下': 'bottom'
    }
    
    def __init__(self, connection_tolerance: float = 0.5):
        """
        Args:
            connection_tolerance: 线段连接容差（mm）
        """
        self.connection_tolerance = connection_tolerance
    
    def parse_spatial_description(self, instruction: str) -> Optional[str]:
        """
        解析工艺说明中的空间描述
        
        Args:
            instruction: 工艺说明，如 "两头红色线线割"
        
        Returns:
            spatial_type: 'two_ends' | 'perimeter' | 'outline' | None
        """
        for keyword, spatial_type in self.SPATIAL_KEYWORDS.items():
            if keyword in instruction:
                return spatial_type
        return None
    
    def analyze_additional_wire_cut(
        self,
        instruction: str,
        unmatched_red_lines: List[Dict],
        view_bounds: Dict,
        view_name: str,
        length: float = None,
        width: float = None,
        thickness: float = None
    ) -> Optional[Dict]:
        """
        分析额外的线割工艺（描述性工艺）
        
        Args:
            instruction: 工艺说明，如 "两头红色线线割"
            unmatched_red_lines: 未匹配的红色线段列表
            view_bounds: 视图边界
            view_name: 视图名称
            length: 零件长度 L（可选，用于优化两头线割识别）
            width: 零件宽度 W（可选，用于优化两头线割识别）
            thickness: 零件厚度 T（可选，用于优化两头线割识别）
        
        Returns:
            wire_cut_detail: 工艺详情字典，如果无法识别则返回 None
        """
        if not unmatched_red_lines:
            return None
        
        # 解析空间描述
        spatial_type = self.parse_spatial_description(instruction)
        
        if not spatial_type:
            # 无空间描述，返回 None，使用原有逻辑处理
            return None
        
        logging.info(f"检测到空间描述性工艺: '{instruction}' -> {spatial_type}")
        
        # 根据空间类型选择处理方法
        if spatial_type == 'two_ends':
            return self._analyze_two_ends(
                instruction, unmatched_red_lines, view_bounds, view_name,
                length, width, thickness
            )
        elif spatial_type == 'perimeter':
            return self._analyze_perimeter(instruction, unmatched_red_lines, view_bounds, view_name)
        elif spatial_type == 'outline':
            return self._analyze_outline(instruction, unmatched_red_lines, view_bounds, view_name)
        else:
            return None
    
    def _analyze_two_ends(
        self,
        instruction: str,
        unmatched_red_lines: List[Dict],
        view_bounds: Dict,
        view_name: str,
        length: float = None,
        width: float = None,
        thickness: float = None
    ) -> Optional[Dict]:
        """
        分析"两头"线割工艺
        
        策略：
        1. 连通性分析：合并首尾相连的线段
        2. 几何特征提取：分析方向、长度、直线度、纯净度
        3. 过滤高质量的线：直线度高、纯净度高
        4. 根据零件尺寸优先选择主方向
        5. 选择空间上最分离的两条线
        
        Args:
            instruction: 工艺说明
            unmatched_red_lines: 未匹配的红色线段列表
            view_bounds: 视图边界
            view_name: 视图名称
            length: 零件长度 L（可选）
            width: 零件宽度 W（可选）
            thickness: 零件厚度 T（可选）
        """
        logging.info(f"开始分析'两头'线割工艺，未匹配线段数: {len(unmatched_red_lines)}")
        
        # 步骤1：连通性分析
        merged_lines = self._merge_connected_lines(unmatched_red_lines)
        logging.info(f"连通性分析完成，合并后线段数: {len(merged_lines)}")
        
        if len(merged_lines) < 2:
            logging.warning("合并后线段数少于2，无法识别'两头'")
            return None
        
        # 步骤2：识别"两头"的线（传入零件尺寸）
        two_end_lines = self._identify_two_ends_lines(
            merged_lines, view_bounds, length, width, thickness
        )
        
        if len(two_end_lines) != 2:
            logging.warning(f"未能识别出2条'两头'线，实际识别: {len(two_end_lines)}")
            return None
        
        # 步骤3：构建工艺详情
        wire_cut_detail = self._build_two_ends_detail(
            two_end_lines, instruction, view_name
        )
        
        logging.info(
            f"✅ '两头'识别成功: 总长度={wire_cut_detail['total_length']:.2f}mm, "
            f"单条长度={wire_cut_detail['single_length']:.2f}mm"
        )
        
        return wire_cut_detail
    
    def _merge_connected_lines(self, red_lines: List[Dict]) -> List[Dict]:
        """
        将首尾相连的红色线段合并成完整的线
        
        Args:
            red_lines: 红色线段列表
        
        Returns:
            merged_lines: 合并后的线列表，每条线包含几何特征
        """
        merged_lines = []
        visited = set()
        
        for i, line in enumerate(red_lines):
            if i in visited:
                continue
            
            # 开始一条新的合并线
            current_group = [line]
            visited.add(i)
            
            # 使用队列进行广度优先搜索
            queue = [i]
            
            while queue:
                current_idx = queue.pop(0)
                current_line = red_lines[current_idx]
                
                # 查找与当前线连通的其他线
                for j, other_line in enumerate(red_lines):
                    if j in visited:
                        continue
                    
                    if self._are_lines_connected(current_line, other_line):
                        current_group.append(other_line)
                        visited.add(j)
                        queue.append(j)
            
            # 分析合并后的线组
            merged_line = self._analyze_line_group(current_group)
            if merged_line:
                merged_lines.append(merged_line)
        
        return merged_lines
    
    def _are_lines_connected(self, line1: Dict, line2: Dict) -> bool:
        """
        判断两条线段是否连通（端点接近）
        
        Args:
            line1, line2: 线段字典
        
        Returns:
            是否连通
        """
        endpoints1 = []
        endpoints2 = []
        
        # 提取端点
        if line1.get('start'):
            endpoints1.append(line1['start'])
        if line1.get('end'):
            endpoints1.append(line1['end'])
        
        if line2.get('start'):
            endpoints2.append(line2['start'])
        if line2.get('end'):
            endpoints2.append(line2['end'])
        
        # 检查任意端点对是否接近
        for ep1 in endpoints1:
            for ep2 in endpoints2:
                distance = math.sqrt((ep1[0] - ep2[0])**2 + (ep1[1] - ep2[1])**2)
                if distance <= self.connection_tolerance:
                    return True
        
        return False
    
    def _analyze_line_group(self, line_group: List[Dict]) -> Optional[Dict]:
        """
        分析线段组的几何特征
        
        提取：方向、长度、边界框、直线度、纯净度等特征
        
        Args:
            line_group: 线段列表
        
        Returns:
            analyzed_line: 包含几何特征的字典
        """
        # 收集所有端点
        all_points = []
        total_length = 0
        
        for line in line_group:
            if line.get('start'):
                all_points.append(line['start'])
            if line.get('end'):
                all_points.append(line['end'])
            total_length += line['length']
        
        if not all_points:
            return None
        
        # 计算边界框
        xs = [p[0] for p in all_points]
        ys = [p[1] for p in all_points]
        
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        
        bbox_width = max_x - min_x
        bbox_height = max_y - min_y
        
        # 计算中心点
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        
        # 判断主方向
        if bbox_height > bbox_width * 2:
            direction = 'vertical'
            main_length = bbox_height
            cross_length = bbox_width
        elif bbox_width > bbox_height * 2:
            direction = 'horizontal'
            main_length = bbox_width
            cross_length = bbox_height
        else:
            direction = 'diagonal'
            main_length = max(bbox_width, bbox_height)
            cross_length = min(bbox_width, bbox_height)
        
        # 计算直线度（线段总长 / 边界框主方向长度）
        # 1.0 = 完美直线，> 1.0 = 有弯曲
        straightness = total_length / main_length if main_length > 0 else 0
        
        # 计算线的"纯净度"（主方向长度 / 交叉方向长度）
        # 越大越接近单一方向
        purity = main_length / cross_length if cross_length > 0 else float('inf')
        
        return {
            'segments': line_group,
            'segment_count': len(line_group),
            'total_length': total_length,
            'direction': direction,
            'main_length': main_length,      # 主方向的跨度
            'cross_length': cross_length,    # 交叉方向的跨度
            'straightness': straightness,    # 直线度
            'purity': purity,                # 纯净度
            'center': (center_x, center_y),
            'bbox': {
                'min_x': min_x, 'max_x': max_x,
                'min_y': min_y, 'max_y': max_y
            }
        }
    
    def _identify_two_ends_lines(
        self,
        merged_lines: List[Dict],
        view_bounds: Dict,
        length: float = None,
        width: float = None,
        thickness: float = None
    ) -> List[Dict]:
        """
        识别"两头"的线（优化版：考虑零件尺寸）
        
        策略：
        1. 过滤出方向一致的线（都是竖直或都是水平）
        2. 过滤出直线度高的线（straightness > 0.9）
        3. 过滤出纯净度高的线（purity > 3.0）
        4. 根据零件尺寸优先选择主方向（长条形优先选长度方向）
        5. 选择空间上最分离的两条线（最左+最右 或 最上+最下）
        6. 验证两条线的长度相似性
        
        Args:
            merged_lines: 合并后的线列表
            view_bounds: 视图边界
            length: 零件长度 L（可选）
            width: 零件宽度 W（可选）
            thickness: 零件厚度 T（可选）
        
        Returns:
            two_end_lines: 两头的线（2条）
        """
        if not merged_lines:
            return []
        
        # 步骤1：过滤高质量的线（直线度高、纯净度高）
        quality_lines = [
            line for line in merged_lines
            if line['straightness'] > 0.9 and  # 接近直线
               line['purity'] > 3.0 and        # 方向纯净
               line['segment_count'] >= 1      # 至少1个线段
        ]
        
        logging.debug(f"高质量线段数（straightness>0.9, purity>3.0）: {len(quality_lines)}")
        
        if len(quality_lines) < 2:
            # 放宽条件
            quality_lines = [
                line for line in merged_lines
                if line['straightness'] > 0.8 and
                   line['purity'] > 2.0
            ]
            logging.debug(f"放宽条件后的高质量线段数（straightness>0.8, purity>2.0）: {len(quality_lines)}")
        
        if len(quality_lines) < 2:
            return []
        
        # 步骤2：按方向分组
        vertical_lines = [l for l in quality_lines if l['direction'] == 'vertical']
        horizontal_lines = [l for l in quality_lines if l['direction'] == 'horizontal']
        
        logging.debug(f"竖直线: {len(vertical_lines)}, 水平线: {len(horizontal_lines)}")
        
        # 步骤3：根据零件尺寸优先选择方向（新增逻辑）
        if length is not None and width is not None:
            # 判断零件的主方向
            if length > width * 1.5:
                # 长条形零件（L >> W），优先选择长度方向（水平线）
                logging.info(f"零件为长条形（L={length} >> W={width}），优先选择水平方向")
                if len(horizontal_lines) >= 2:
                    candidate_lines = horizontal_lines
                    position_key = 'y'  # 按 y 坐标排序（上下）
                    logging.debug("选择水平线作为候选")
                elif len(vertical_lines) >= 2:
                    candidate_lines = vertical_lines
                    position_key = 'x'  # 按 x 坐标排序（左右）
                    logging.debug("水平线不足，退回选择竖直线")
                else:
                    return []
            elif width > length * 1.5:
                # 宽扁形零件（W >> L），优先选择宽度方向（竖直线）
                logging.info(f"零件为宽扁形（W={width} >> L={length}），优先选择竖直方向")
                if len(vertical_lines) >= 2:
                    candidate_lines = vertical_lines
                    position_key = 'x'  # 按 x 坐标排序（左右）
                    logging.debug("选择竖直线作为候选")
                elif len(horizontal_lines) >= 2:
                    candidate_lines = horizontal_lines
                    position_key = 'y'  # 按 y 坐标排序（上下）
                    logging.debug("竖直线不足，退回选择水平线")
                else:
                    return []
            else:
                # 接近正方形，使用原有逻辑（选择数量更多的方向）
                logging.debug(f"零件接近正方形（L={length}, W={width}），使用数量优先策略")
                if len(vertical_lines) >= len(horizontal_lines) and len(vertical_lines) >= 2:
                    candidate_lines = vertical_lines
                    position_key = 'x'
                elif len(horizontal_lines) >= 2:
                    candidate_lines = horizontal_lines
                    position_key = 'y'
                else:
                    return []
        else:
            # 没有尺寸信息，使用原有逻辑（选择数量更多的方向）
            logging.debug("未提供零件尺寸，使用数量优先策略")
            if len(vertical_lines) >= len(horizontal_lines) and len(vertical_lines) >= 2:
                candidate_lines = vertical_lines
                position_key = 'x'
            elif len(horizontal_lines) >= 2:
                candidate_lines = horizontal_lines
                position_key = 'y'
            else:
                return []
        
        # 步骤4：选择空间上最分离的两条线
        # 按位置排序
        if position_key == 'x':
            sorted_lines = sorted(candidate_lines, key=lambda l: l['center'][0])
        else:
            sorted_lines = sorted(candidate_lines, key=lambda l: l['center'][1])
        
        # 选择最左/最上 和 最右/最下
        left_or_top = sorted_lines[0]
        right_or_bottom = sorted_lines[-1]
        
        # 步骤5：验证两条线的相似性（长度应该接近）
        length_ratio = min(
            left_or_top['main_length'] / right_or_bottom['main_length'],
            right_or_bottom['main_length'] / left_or_top['main_length']
        )
        
        logging.debug(
            f"两条线的长度比: {length_ratio:.2f} "
            f"({left_or_top['main_length']:.2f} / {right_or_bottom['main_length']:.2f})"
        )
        
        if length_ratio < 0.7:
            # 长度差异太大，可能不是"两头"
            # 尝试找到长度更接近的组合
            logging.debug("长度差异太大，尝试寻找更接近的组合")
            for i in range(len(sorted_lines) - 1):
                for j in range(i + 1, len(sorted_lines)):
                    line1 = sorted_lines[i]
                    line2 = sorted_lines[j]
                    ratio = min(
                        line1['main_length'] / line2['main_length'],
                        line2['main_length'] / line1['main_length']
                    )
                    if ratio >= 0.8:
                        left_or_top = line1
                        right_or_bottom = line2
                        logging.debug(f"找到更好的组合，长度比: {ratio:.2f}")
                        break
        
        return [left_or_top, right_or_bottom]
    
    def _build_two_ends_detail(
        self,
        two_end_lines: List[Dict],
        instruction: str,
        view_name: str
    ) -> Dict:
        """
        构建"两头红色线线割"的工艺详情
        
        Args:
            two_end_lines: 识别出的两条线
            instruction: 工艺说明
            view_name: 视图名称
        
        Returns:
            wire_cut_detail: 工艺详情字典
        """
        line1, line2 = two_end_lines
        
        # 判断是左右还是上下
        if line1['direction'] == 'vertical':
            region_names = ['left_end', 'right_end']
        else:
            region_names = ['top_end', 'bottom_end']
        
        # 按位置排序
        if line1['center'][0] < line2['center'][0] or line1['center'][1] < line2['center'][1]:
            sorted_lines = [line1, line2]
        else:
            sorted_lines = [line2, line1]
        
        # 收集所有匹配的线段ID
        all_matched_line_ids = []
        for line in sorted_lines:
            for seg in line['segments']:
                all_matched_line_ids.append(id(seg['entity']))
        
        # 构建详情
        wire_cut_detail = {
            'code': instruction,
            'view': view_name,
            'area_num': 2,
            'instruction': instruction,
            'total_length': round(sorted_lines[0]['main_length'] + sorted_lines[1]['main_length'], 2),
            'is_additional': True,
            'matched_count': 2,  # 2条线
            'single_length': round((sorted_lines[0]['main_length'] + sorted_lines[1]['main_length']) / 2, 2),
            'expected_count': 2,
            'matched_line_ids': all_matched_line_ids,
            'area_details': [
                {
                    'region_name': region_names[0],
                    'segment_count': sorted_lines[0]['segment_count'],
                    'total_length': round(sorted_lines[0]['main_length'], 2),
                    'straightness': round(sorted_lines[0]['straightness'], 2),
                    'purity': round(sorted_lines[0]['purity'], 2),
                    'direction': sorted_lines[0]['direction']
                },
                {
                    'region_name': region_names[1],
                    'segment_count': sorted_lines[1]['segment_count'],
                    'total_length': round(sorted_lines[1]['main_length'], 2),
                    'straightness': round(sorted_lines[1]['straightness'], 2),
                    'purity': round(sorted_lines[1]['purity'], 2),
                    'direction': sorted_lines[1]['direction']
                }
            ],
            'geometry_features': {
                'direction': sorted_lines[0]['direction'],
                'avg_straightness': round((sorted_lines[0]['straightness'] + sorted_lines[1]['straightness']) / 2, 2),
                'avg_purity': round((sorted_lines[0]['purity'] + sorted_lines[1]['purity']) / 2, 2),
                'length_consistency': round(min(
                    sorted_lines[0]['main_length'] / sorted_lines[1]['main_length'],
                    sorted_lines[1]['main_length'] / sorted_lines[0]['main_length']
                ), 2)
            },
            'cone': 'f',
            'slider_angle': 0
        }
        
        return wire_cut_detail
    
    def _analyze_perimeter(
        self,
        instruction: str,
        unmatched_red_lines: List[Dict],
        view_bounds: Dict,
        view_name: str
    ) -> Optional[Dict]:
        """
        分析"四周"线割工艺
        
        TODO: 实现四周识别逻辑
        """
        logging.info("'四周'识别功能待实现")
        return None
    
    def _analyze_outline(
        self,
        instruction: str,
        unmatched_red_lines: List[Dict],
        view_bounds: Dict,
        view_name: str
    ) -> Optional[Dict]:
        """
        严格验证的外形线割识别（方案D）
        
        验证层级：
        1. 明确的外形线割关键词组合
        2. 排除其他工艺类型
        3. 验证线段特征合理性
        4. 几何分布验证
        
        Args:
            instruction: 工艺说明，如 "外形红色线实数线割"
            unmatched_red_lines: 未匹配的红色线段列表
            view_bounds: 视图边界
            view_name: 视图名称
        
        Returns:
            wire_cut_detail: 工艺详情字典，如果验证失败则返回 None
        """
        
        # === 第1层：明确的外形线割标识验证 ===
        explicit_outline_patterns = [
            '外形红色线实数线割',      # PH-01的确切描述
            '外形实数线割',
            '外形线割',
            '红色线实数线割',
            '轮廓线割',
            '外轮廓线割',
            '外形红色线',
            '实数线割外形'
        ]
        
        # 必须完全匹配或包含明确的外形线割描述
        is_explicit_outline = any(pattern in instruction for pattern in explicit_outline_patterns)
        
        if not is_explicit_outline:
            logging.debug(f"'{instruction}' 不包含明确的外形线割标识")
            return None
        
        # === 第2层：排除其他工艺类型 ===
        exclusion_keywords = [
            '两头', '四周', '中间',           # 空间位置描述
            '钻', '攻', '沉头', '铣',         # 其他加工工艺
            '背面', '正面',                   # 面向描述
            '让位', '倒角',                   # 其他工艺
            '螺丝', '合销'                    # 具体零件描述
        ]
        
        has_exclusion = any(keyword in instruction for keyword in exclusion_keywords)
        if has_exclusion:
            logging.info(f"'{instruction}' 包含排除关键词，不识别为外形线割")
            return None
        
        # === 第3层：基于置信度的动态验证 ===
        if not unmatched_red_lines:
            logging.info(f"'{instruction}' 没有未匹配的线割实线")
            return None
        
        # 计算外形线割置信度
        confidence = self._calculate_outline_confidence(instruction, unmatched_red_lines, view_bounds)
        logging.info(f"🎯 外形线割置信度评估: {confidence:.3f}")
        
        # 根据置信度获取动态阈值
        thresholds = self._get_dynamic_thresholds(confidence)
        if thresholds is None:
            logging.info(f"置信度过低({confidence:.3f})，拒绝识别为外形线割")
            return None
        
        # 应用动态阈值验证
        total_length = sum(line['length'] for line in unmatched_red_lines)
        line_count = len(unmatched_red_lines)
        
        # 线段数量验证
        if line_count < thresholds['min_line_count']:
            logging.info(f"线段数量({line_count})少于动态阈值({thresholds['min_line_count']})，置信度={confidence:.3f}")
            return None
        
        # 总长度验证
        if total_length < thresholds['min_total_length']:
            logging.info(f"总长度({total_length:.1f}mm)少于动态阈值({thresholds['min_total_length']}mm)，置信度={confidence:.3f}")
            return None
        
        # === 第4层：几何分布验证 ===
        # 外形线割的线段应该分布在视图的不同区域
        line_positions = []
        for line in unmatched_red_lines:
            start_x, start_y = line['start']
            end_x, end_y = line['end']
            mid_x = (start_x + end_x) / 2
            mid_y = (start_y + end_y) / 2
            line_positions.append((mid_x, mid_y))
        
        # 计算线段分布的离散程度
        x_range = 0
        y_range = 0
        if len(line_positions) >= 3:
            x_coords = [pos[0] for pos in line_positions]
            y_coords = [pos[1] for pos in line_positions]
            
            x_range = max(x_coords) - min(x_coords)
            y_range = max(y_coords) - min(y_coords)
            
            # 外形线割应该有一定的空间分布
            min_distribution = 20  # 至少20mm的分布范围
            if x_range < min_distribution and y_range < min_distribution:
                logging.info(f"线段分布过于集中(X:{x_range:.1f}, Y:{y_range:.1f})，不符合外形线割特征")
                return None
        
        # === 通过所有验证，识别为外形线割 ===
        logging.info(f"🎯 通过严格验证，识别为外形线割: '{instruction}'")
        logging.info(f"   验证结果: 明确标识✓, 无排除词✓, 线段数{len(unmatched_red_lines)}✓, 总长度{total_length:.1f}mm✓")
        if x_range > 0 or y_range > 0:
            logging.info(f"   几何分布: X范围{x_range:.1f}mm, Y范围{y_range:.1f}mm ✓")
        
        matched_count = len(unmatched_red_lines)
        single_length = total_length / matched_count if matched_count > 0 else 0.0
        
        return {
            'matched_count': matched_count,
            'single_length': round(single_length, 2),
            'total_length': round(total_length, 2),
            'matched_line_ids': [id(line['entity']) for line in unmatched_red_lines],
            'skip_plate_overlap_check': True,  # 标记跳过板料线重合检测
            'geometry_features': {
                'is_outline': True,
                'verification_passed': True,
                'line_distribution': f'X:{x_range:.1f}mm, Y:{y_range:.1f}mm',
                'validation_layers': {
                    'explicit_pattern': True,
                    'exclusion_check': True,
                    'feature_validation': True,
                    'distribution_check': True
                }
            }
        }
    
    # ==================== 置信度计算和动态阈值系统 ====================
    
    def _calculate_outline_confidence(self, instruction: str, unmatched_lines: List[Dict], 
                                    view_bounds: Dict) -> float:
        """
        计算外形线割置信度 (0.0 - 1.0)
        
        评分维度：
        1. 文本语义置信度 (0-0.5)
        2. 几何特征置信度 (0-0.3) 
        3. 分布特征置信度 (0-0.2)
        """
        
        text_confidence = self._calculate_text_confidence(instruction)
        geometry_confidence = self._calculate_geometry_confidence(unmatched_lines)
        distribution_confidence = self._calculate_distribution_confidence(unmatched_lines, view_bounds)
        
        total_confidence = text_confidence + geometry_confidence + distribution_confidence
        
        logging.debug(f"   置信度分解: 文本={text_confidence:.3f}, 几何={geometry_confidence:.3f}, 分布={distribution_confidence:.3f}")
        
        return min(total_confidence, 1.0)
    
    def _calculate_text_confidence(self, instruction: str) -> float:
        """文本语义置信度 (0-0.5)"""
        
        confidence = 0.0
        
        # 核心关键词权重
        core_keywords = {
            '外形红色线实数线割': 0.5,    # 完整描述，最高权重
            '外形实数线割': 0.4,
            '红色线实数线割': 0.35,
            '外形线割': 0.3,
            '轮廓线割': 0.3,
            '外轮廓线割': 0.35,
            '实数线割': 0.2,
            '外形': 0.15,
            '轮廓': 0.15
        }
        
        # 修饰词权重（累加）
        modifiers = {
            '红色线': 0.1,
            '红色': 0.05,
            '实数': 0.05,
            '完整': 0.03,
            '全部': 0.03,
            '整体': 0.03
        }
        
        # 负面词汇（降低置信度）
        negative_keywords = {
            '两头': -0.3,
            '四周': -0.2,
            '中间': -0.2,
            '部分': -0.1,
            '局部': -0.1,
            '钻': -0.4,
            '攻': -0.4,
            '沉头': -0.4,
            '铣': -0.3
        }
        
        # 计算核心关键词得分（取最高分，不累加）
        max_core_score = 0.0
        for keyword, weight in core_keywords.items():
            if keyword in instruction:
                max_core_score = max(max_core_score, weight)
        
        confidence += max_core_score
        
        # 计算修饰词得分（累加）
        for modifier, weight in modifiers.items():
            if modifier in instruction:
                confidence += weight
        
        # 计算负面得分（累加惩罚）
        for negative, penalty in negative_keywords.items():
            if negative in instruction:
                confidence += penalty
        
        return max(0.0, min(confidence, 0.5))
    
    def _calculate_geometry_confidence(self, unmatched_lines: List[Dict]) -> float:
        """几何特征置信度 (0-0.3)"""
        
        if not unmatched_lines:
            return 0.0
        
        confidence = 0.0
        
        # 线段数量评分 (0-0.15)
        line_count = len(unmatched_lines)
        if line_count >= 5:
            confidence += 0.15
        elif line_count == 4:
            confidence += 0.12
        elif line_count == 3:
            confidence += 0.09
        elif line_count == 2:
            confidence += 0.06
        elif line_count == 1:
            confidence += 0.03
        
        # 总长度评分 (0-0.15)
        total_length = sum(line['length'] for line in unmatched_lines)
        if total_length >= 300:
            confidence += 0.15
        elif total_length >= 200:
            confidence += 0.12
        elif total_length >= 100:
            confidence += 0.09
        elif total_length >= 50:
            confidence += 0.06
        elif total_length >= 20:
            confidence += 0.03
        
        return min(confidence, 0.3)
    
    def _calculate_distribution_confidence(self, unmatched_lines: List[Dict], 
                                         view_bounds: Dict) -> float:
        """分布特征置信度 (0-0.2)"""
        
        if len(unmatched_lines) < 2:
            return 0.0
        
        confidence = 0.0
        
        # 计算线段分布范围
        line_positions = []
        for line in unmatched_lines:
            start_x, start_y = line['start']
            end_x, end_y = line['end']
            mid_x = (start_x + end_x) / 2
            mid_y = (start_y + end_y) / 2
            line_positions.append((mid_x, mid_y))
        
        x_coords = [pos[0] for pos in line_positions]
        y_coords = [pos[1] for pos in line_positions]
        
        x_range = max(x_coords) - min(x_coords)
        y_range = max(y_coords) - min(y_coords)
        
        # 分布范围评分 (0-0.1)
        max_range = max(x_range, y_range)
        if max_range >= 100:
            confidence += 0.1
        elif max_range >= 50:
            confidence += 0.07
        elif max_range >= 20:
            confidence += 0.05
        elif max_range >= 10:
            confidence += 0.03
        
        # 分布均匀性评分 (0-0.1)
        if len(line_positions) >= 3:
            # 简单的分布均匀性检查：线段是否分散在不同象限
            view_center_x = (view_bounds['min_x'] + view_bounds['max_x']) / 2
            view_center_y = (view_bounds['min_y'] + view_bounds['max_y']) / 2
            
            quadrants = set()
            for x, y in line_positions:
                quad = (1 if x > view_center_x else 0, 1 if y > view_center_y else 0)
                quadrants.add(quad)
            
            # 分布在多个象限得分更高
            if len(quadrants) >= 3:
                confidence += 0.1
            elif len(quadrants) == 2:
                confidence += 0.05
        
        return min(confidence, 0.2)
    
    def _get_dynamic_thresholds(self, confidence: float) -> Optional[Dict[str, float]]:
        """
        根据置信度计算动态阈值
        
        置信度区间：
        - 0.7-1.0: 高置信度，最宽松阈值
        - 0.5-0.7: 中高置信度，适中阈值  
        - 0.3-0.5: 中等置信度，标准阈值
        - 0.15-0.3: 低置信度，严格阈值
        - 0.0-0.15: 极低置信度，拒绝识别
        """
        
        if confidence >= 0.7:
            thresholds = {
                'min_line_count': 1,
                'min_total_length': 10,
                'min_distribution': 5
            }
            logging.info(f"   高置信度阈值: 线段≥{thresholds['min_line_count']}, 长度≥{thresholds['min_total_length']}mm")
            return thresholds
            
        elif confidence >= 0.5:
            thresholds = {
                'min_line_count': 1,
                'min_total_length': 20,
                'min_distribution': 10
            }
            logging.info(f"   中高置信度阈值: 线段≥{thresholds['min_line_count']}, 长度≥{thresholds['min_total_length']}mm")
            return thresholds
            
        elif confidence >= 0.3:
            thresholds = {
                'min_line_count': 2,
                'min_total_length': 30,
                'min_distribution': 15
            }
            logging.info(f"   中等置信度阈值: 线段≥{thresholds['min_line_count']}, 长度≥{thresholds['min_total_length']}mm")
            return thresholds
            
        elif confidence >= 0.15:
            thresholds = {
                'min_line_count': 3,
                'min_total_length': 50,
                'min_distribution': 20
            }
            logging.info(f"   低置信度阈值: 线段≥{thresholds['min_line_count']}, 长度≥{thresholds['min_total_length']}mm")
            return thresholds
            
        else:
            logging.info(f"   极低置信度({confidence:.3f})，拒绝识别")
            return None