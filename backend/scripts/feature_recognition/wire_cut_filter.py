# -*- coding: utf-8 -*-
"""
线割过滤模块
基于加工说明的线割实线过滤功能
"""
import logging
import math
import re
from typing import Dict, List, Tuple, Optional


class WireCutFilter:
    """线割过滤器 - 根据加工说明过滤线割实线"""
    
    def __init__(self, proximity_threshold: float = 50.0, text_search_expand_margin: float = 10.0):
        """
        Args:
            proximity_threshold: 邻近阈值（单位：mm），实线中心与文本的距离小于此值则认为配对
            text_search_expand_margin: 文本搜索边界扩展量（单位：mm），用于查找可能在视图边界外的工艺编号
        """
        self.proximity_threshold = proximity_threshold
        self.text_search_expand_margin = text_search_expand_margin
    
    def extract_wire_cut_codes(self, processing_instructions: Optional[Dict[str, str]]) -> List[str]:
        """
        从加工说明中提取包含'割'字的工艺编号
        
        Args:
            processing_instructions: 加工说明字典 {code: instruction}
        
        Returns:
            包含'割'字的工艺编号列表，如 ['ZA', 'ZB']
        """
        if not processing_instructions:
            return []
        
        wire_cut_codes = []
        for code, instruction in processing_instructions.items():
            if '割' in instruction:
                wire_cut_codes.append(code)
                logging.debug(f"线割工艺: {code} - {instruction}")
        
        return wire_cut_codes
    
    def extract_wire_cut_codes_with_count(self, processing_instructions: Optional[Dict[str, str]]) -> Dict[str, int]:
        """
        从加工说明中提取包含'割'字的工艺编号及其数量
        
        Args:
            processing_instructions: 加工说明字典 {code: instruction}
            格式示例: "ZA :2 -线割加工" 表示 ZA 工艺有 2 个
        
        Returns:
            字典 {code: count}，如 {'ZA': 2, 'ZB': 1}
        """
        if not processing_instructions:
            return {}
        
        wire_cut_info = {}
        
        for code, instruction in processing_instructions.items():
            if '割' not in instruction:
                continue
            
            # 解析数量：可能的格式
            # 格式1: ":2 -Ø8.00割++0.005" (冒号在instruction中)
            # 格式2: "2 -Ø8.00割++0.005" (冒号被正则吃掉了)
            # 格式3: "2-Ø8.00割++0.005" (无空格)
            count = 1  # 默认数量为 1
            
            import re
            
            # 先尝试匹配 :数字 格式
            match = re.search(r':(\d+)', instruction)
            if match:
                count = int(match.group(1))
            else:
                # 尝试匹配开头的数字（可能前面有空格）
                # 例如: "2 -Ø8.00割" 或 "2-Ø8.00割"
                match = re.match(r'^\s*(\d+)\s*[-\-]', instruction)
                if match:
                    count = int(match.group(1))
            
            wire_cut_info[code] = count
            logging.info(f"线割工艺: {code} - 数量: {count} - 指令: {instruction}")
        
        return wire_cut_info
    
    def extract_additional_wire_cut_texts(
        self, 
        all_texts: Optional[List[str]], 
        processing_instructions: Optional[Dict[str, str]] = None
    ) -> List[str]:
        """
        从所有文字中提取包含'割'字或'快丝拉断'但不在加工说明中的文字，作为额外的线割工艺编号
        
        Args:
            all_texts: 图纸中所有文字列表
            processing_instructions: 加工说明字典 {code: instruction}
        
        Returns:
            额外的线割工艺编号列表，如 ['实数线割', '慢走丝线割', '快丝拉断']
        """
        if not all_texts:
            logging.debug("all_texts 为空，无法提取额外线割工艺")
            return []
        
        # 获取加工说明中已有的编号
        existing_codes = set(processing_instructions.keys()) if processing_instructions else set()
        
        # 提取包含"割"字或"快丝拉断"的文字
        additional_codes = []
        seen = set()  # 去重
        
        # 统计包含"割"字或"快丝拉断"的文本数量（用于调试）
        texts_with_cut = [t for t in all_texts if '割' in t or '快丝拉断' in t]
        if texts_with_cut:
            logging.debug(f"在 {len(all_texts)} 条文本中找到 {len(texts_with_cut)} 条包含'割'字或'快丝拉断'的文本")
        
        for text in all_texts:
            text = text.strip()
            
            # 跳过空文本
            if not text:
                continue
            
            # 必须包含"割"字或"快丝拉断"
            if '割' not in text and '快丝拉断' not in text:
                continue
            
            # 跳过已在加工说明中的编号
            if text in existing_codes:
                logging.debug(f"跳过已在加工说明中的文本: '{text}'")
                continue
            
            # 跳过包含加工说明格式的文本（如 "L :2 -%%C12.00割,单+0.008(合销)"）
            # 这些文本通常以编号开头，后面跟着冒号和详细说明
            import re
            if re.match(r'^[A-Z][A-Z0-9]?\s*:', text):
                logging.debug(f"跳过加工说明格式的文本: '{text}'")
                continue
            
            # 跳过以冒号开头的文本（如 ":2 -线割加工"），这些是加工说明的一部分
            if text.startswith(':'):
                logging.debug(f"跳过以冒号开头的文本: '{text}'")
                continue
            
            # 跳过已经添加过的
            if text in seen:
                logging.debug(f"跳过重复的文本: '{text}'")
                continue
            
            # 跳过太长的文本（可能是完整的说明文字，不是编号）
            # "实数线割"是4个字，"慢走丝线割"是5个字，"快丝拉断"是4个字
            # "外形红色线实数线割"是10个字，"外形红色线实数线割,背面按3D精铣"是17个字
            # 设置合理的上限为20个字符，避免将整段说明文字误识别为工艺编号
            if len(text) > 20:
                logging.debug(f"跳过太长的文本 ({len(text)}字符): '{text}'")
                continue
            
            # 跳过只有一个"割"字的
            if text == '割':
                logging.debug("跳过单独的'割'字")
                continue
            
            additional_codes.append(text)
            seen.add(text)
            logging.info(f"发现额外的线割工艺文字: '{text}'")
        
        return additional_codes
    
    def find_text_positions_in_bounds(
        self, 
        msp, 
        bounds: Dict, 
        target_texts: List[str],
        expand_margin: float = 0.0
    ) -> Dict[str, List[Tuple[float, float]]]:
        """
        在指定边界内查找目标文本的所有位置（支持同一编号多次出现）
        
        Args:
            msp: modelspace
            bounds: 边界范围 {'min_x': float, 'max_x': float, 'min_y': float, 'max_y': float}
            target_texts: 要查找的文本列表（工艺编号）
            expand_margin: 边界扩展量（单位：mm），用于查找可能在边界外的文本
        
        Returns:
            字典 {text: [(x1, y1), (x2, y2), ...]} 文本及其所有位置
        """
        text_positions = {text: [] for text in target_texts}
        
        # 扩展边界用于查找文本
        expanded_bounds = {
            'min_x': bounds['min_x'] - expand_margin,
            'max_x': bounds['max_x'] + expand_margin,
            'min_y': bounds['min_y'] - expand_margin,
            'max_y': bounds['max_y'] + expand_margin
        }
        
        if expand_margin > 0:
            logging.debug(
                f"扩展边界用于查找文本: "
                f"原始 [{bounds['min_x']:.1f}, {bounds['max_x']:.1f}] x [{bounds['min_y']:.1f}, {bounds['max_y']:.1f}], "
                f"扩展后 [{expanded_bounds['min_x']:.1f}, {expanded_bounds['max_x']:.1f}] x "
                f"[{expanded_bounds['min_y']:.1f}, {expanded_bounds['max_y']:.1f}]"
            )
        
        try:
            for entity in msp.query('TEXT MTEXT'):
                try:
                    # 获取文本内容
                    if entity.dxftype() == 'MTEXT':
                        content = entity.text if hasattr(entity, 'text') else entity.dxf.text
                    else:
                        content = entity.dxf.text
                    
                    if not content:
                        continue
                    
                    content = content.strip()
                    
                    # 检查是否是目标文本
                    if content not in target_texts:
                        continue
                    
                    # 获取文本位置
                    if hasattr(entity.dxf, 'insert'):
                        pos = entity.dxf.insert
                        x, y = pos.x, pos.y
                    elif hasattr(entity.dxf, 'position'):
                        pos = entity.dxf.position
                        x, y = pos.x, pos.y
                    else:
                        continue
                    
                    # 检查是否在扩展边界内
                    if (expanded_bounds['min_x'] <= x <= expanded_bounds['max_x'] and 
                        expanded_bounds['min_y'] <= y <= expanded_bounds['max_y']):
                        text_positions[content].append((x, y))
                        
                        # 判断是否在原始边界内
                        in_original = (bounds['min_x'] <= x <= bounds['max_x'] and 
                                      bounds['min_y'] <= y <= bounds['max_y'])
                        location_info = "边界内" if in_original else "扩展区域"
                        logging.debug(f"找到文本 '{content}' 在位置 ({x:.2f}, {y:.2f}) [{location_info}]")
                
                except Exception as e:
                    logging.debug(f"处理文本实体失败: {e}")
                    continue
        
        except Exception as e:
            logging.error(f"查找文本位置失败: {e}")
        
        # 移除没有找到的编号
        text_positions = {k: v for k, v in text_positions.items() if v}
        
        return text_positions
    
    def match_lines_to_codes(
        self, 
        red_lines: List[Dict], 
        text_positions: Dict[str, List[Tuple[float, float]]]
    ) -> List[Dict]:
        """
        将线割实线与工艺编号配对（支持一个编号多次出现）
        
        Args:
            red_lines: 线割实线列表 [{'entity': ..., 'length': ..., 'center': (x, y)}]
            text_positions: 工艺编号位置 {code: [(x1, y1), (x2, y2), ...]}
        
        Returns:
            配对成功的线割实线列表
        """
        matched_lines = []
        used_codes = set()
        
        # 为每条线割实线找最近的工艺编号
        for line in red_lines:
            if not line['center']:
                continue
            
            line_x, line_y = line['center']
            min_distance = float('inf')
            closest_code = None
            
            # 查找最近的工艺编号（考虑所有位置）
            for code, positions in text_positions.items():
                for text_x, text_y in positions:
                    distance = math.sqrt((line_x - text_x)**2 + (line_y - text_y)**2)
                    
                    if distance < min_distance:
                        min_distance = distance
                        closest_code = code
            
            # 如果距离在阈值内，认为配对成功
            if closest_code and min_distance <= self.proximity_threshold:
                matched_lines.append(line)
                used_codes.add(closest_code)
                logging.debug(
                    f"线割实线 (中心: {line_x:.1f}, {line_y:.1f}) "
                    f"与工艺编号 '{closest_code}' 配对成功, 距离: {min_distance:.2f}mm"
                )
        
        # 报告未配对的工艺编号
        unmatched_codes = set(text_positions.keys()) - used_codes
        if unmatched_codes:
            logging.warning(f"以下工艺编号未找到配对的线割实线: {unmatched_codes}")
        
        return matched_lines
    
    def _calculate_min_distance_to_entity(
        self,
        entity,
        text_x: float,
        text_y: float
    ) -> float:
        """
        计算文本位置到实体的最近距离
        
        Args:
            entity: DXF 实体
            text_x: 文本 x 坐标
            text_y: 文本 y 坐标
        
        Returns:
            最近距离
        """
        try:
            entity_type = entity.dxftype()
            
            if entity_type == 'LINE':
                # 计算点到线段的最短距离
                start = entity.dxf.start
                end = entity.dxf.end
                return self._point_to_line_distance(
                    text_x, text_y,
                    start.x, start.y,
                    end.x, end.y
                )
            
            elif entity_type == 'CIRCLE':
                # 计算点到圆的最短距离（圆周）
                center = entity.dxf.center
                radius = entity.dxf.radius
                center_dist = math.sqrt((text_x - center.x)**2 + (text_y - center.y)**2)
                return abs(center_dist - radius)
            
            elif entity_type == 'ARC':
                # 计算点到圆弧的最短距离
                center = entity.dxf.center
                radius = entity.dxf.radius
                start_angle = math.radians(entity.dxf.start_angle)
                end_angle = math.radians(entity.dxf.end_angle)
                
                # 计算点到圆心的距离和角度
                dx = text_x - center.x
                dy = text_y - center.y
                point_dist = math.sqrt(dx**2 + dy**2)
                point_angle = math.atan2(dy, dx)
                
                # 规范化角度到 [0, 2π)
                if point_angle < 0:
                    point_angle += 2 * math.pi
                
                # 检查点的角度是否在圆弧范围内
                if start_angle <= end_angle:
                    in_arc = start_angle <= point_angle <= end_angle
                else:
                    in_arc = point_angle >= start_angle or point_angle <= end_angle
                
                if in_arc:
                    # 点在圆弧角度范围内，距离是到圆弧的径向距离
                    return abs(point_dist - radius)
                else:
                    # 点不在圆弧角度范围内，计算到两个端点的距离
                    start_x = center.x + radius * math.cos(start_angle)
                    start_y = center.y + radius * math.sin(start_angle)
                    end_x = center.x + radius * math.cos(end_angle)
                    end_y = center.y + radius * math.sin(end_angle)
                    
                    dist_to_start = math.sqrt((text_x - start_x)**2 + (text_y - start_y)**2)
                    dist_to_end = math.sqrt((text_x - end_x)**2 + (text_y - end_y)**2)
                    
                    return min(dist_to_start, dist_to_end)
            
            elif entity_type in ['LWPOLYLINE', 'POLYLINE']:
                # 计算点到多段线的最短距离
                points = list(entity.get_points('xy'))
                if len(points) < 2:
                    return float('inf')
                
                min_dist = float('inf')
                
                # 计算到每条线段的距离
                for i in range(len(points) - 1):
                    p1 = points[i]
                    p2 = points[i + 1]
                    dist = self._point_to_line_distance(
                        text_x, text_y,
                        p1[0], p1[1],
                        p2[0], p2[1]
                    )
                    min_dist = min(min_dist, dist)
                
                # 如果是闭合多段线，计算到最后一条边的距离
                if getattr(entity.dxf, 'closed', False) and len(points) > 2:
                    p1 = points[-1]
                    p2 = points[0]
                    dist = self._point_to_line_distance(
                        text_x, text_y,
                        p1[0], p1[1],
                        p2[0], p2[1]
                    )
                    min_dist = min(min_dist, dist)
                
                return min_dist
            
            else:
                # 不支持的实体类型，返回无穷大
                return float('inf')
        
        except Exception as e:
            logging.debug(f"计算到实体的距离失败: {e}")
            return float('inf')
    
    def _point_to_line_distance(
        self,
        px: float, py: float,
        x1: float, y1: float,
        x2: float, y2: float
    ) -> float:
        """
        计算点到线段的最短距离
        
        Args:
            px, py: 点坐标
            x1, y1: 线段起点
            x2, y2: 线段终点
        
        Returns:
            最短距离
        """
        # 线段长度的平方
        line_len_sq = (x2 - x1)**2 + (y2 - y1)**2
        
        if line_len_sq == 0:
            # 线段退化为点
            return math.sqrt((px - x1)**2 + (py - y1)**2)
        
        # 计算投影参数 t
        t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / line_len_sq))
        
        # 计算投影点
        proj_x = x1 + t * (x2 - x1)
        proj_y = y1 + t * (y2 - y1)
        
        # 返回点到投影点的距离
        return math.sqrt((px - proj_x)**2 + (py - proj_y)**2)
    
    def find_connected_entities(
        self,
        red_lines: List[Dict],
        start_indices: List[int],
        tolerance: float = 0.5
    ) -> Tuple[set, float]:
        """
        从起始实体开始，找到所有首尾相连的实体（连通性分析）
        
        Args:
            red_lines: 所有红色实体列表 [{'entity': ..., 'length': ..., 'center': (x, y), 'start': (x, y), 'end': (x, y), 'type': str}]
            start_indices: 起始实体的索引列表
            tolerance: 端点连接容差（mm）
        
        Returns:
            (connected_indices, total_length): 连通的实体索引集合和总长度
        """
        connected = set(start_indices)
        to_check = list(start_indices)
        
        while to_check:
            current_idx = to_check.pop(0)
            current = red_lines[current_idx]
            
            # 获取当前实体的端点
            current_endpoints = []
            if current.get('start'):
                current_endpoints.append(current['start'])
            if current.get('end'):
                current_endpoints.append(current['end'])
            
            # 检查所有其他实体
            for i, line in enumerate(red_lines):
                if i in connected:
                    continue
                
                # 获取候选实体的端点
                candidate_endpoints = []
                if line.get('start'):
                    candidate_endpoints.append(line['start'])
                if line.get('end'):
                    candidate_endpoints.append(line['end'])
                
                # 检查是否有端点相连（容差 0.5mm）
                is_connected = False
                for cp in current_endpoints:
                    for ep in candidate_endpoints:
                        distance = math.sqrt((cp[0] - ep[0])**2 + (cp[1] - ep[1])**2)
                        if distance <= tolerance:
                            is_connected = True
                            break
                    if is_connected:
                        break
                
                if is_connected:
                    connected.add(i)
                    to_check.append(i)
        
        # 计算总长度
        total_length = sum(red_lines[i]['length'] for i in connected)
        
        return connected, total_length
    
    def _fallback_to_head_to_tail(
        self,
        candidate_lines: List[Dict],
        positions: List[Tuple[float, float]],
        matched_lines: List[Dict],
        code_matched_lines: Dict[str, List[Dict]],
        code: str
    ):
        """
        备用方法：使用首尾相连分析
        
        Args:
            candidate_lines: 候选线段列表
            positions: 编号位置列表
            matched_lines: 匹配的线段列表（会被修改）
            code_matched_lines: 编号对应的线段字典（会被修改）
            code: 工艺编号
        """
        connected_groups = self._connect_lines_head_to_tail(candidate_lines)
        
        if len(connected_groups) == 1:
            # 所有线段都连接成一组
            logging.info(f"  所有 {len(candidate_lines)} 条线段首尾相连成一组")
            matched_lines.extend(candidate_lines)
            code_matched_lines[code] = candidate_lines
        else:
            # 分成多组，选择离编号最近的一组
            logging.info(f"  线段分为 {len(connected_groups)} 组，选择离编号最近的一组")
            
            best_group = None
            best_distance = float('inf')
            
            for group in connected_groups:
                group_min_distance = float('inf')
                for line in group:
                    if not line['center']:
                        continue
                    line_x, line_y = line['center']
                    for text_x, text_y in positions:
                        distance = math.sqrt((line_x - text_x)**2 + (line_y - text_y)**2)
                        group_min_distance = min(group_min_distance, distance)
                
                if group_min_distance < best_distance:
                    best_distance = group_min_distance
                    best_group = group
            
            if best_group:
                matched_lines.extend(best_group)
                code_matched_lines[code] = best_group
                logging.info(
                    f"  选择了包含 {len(best_group)} 条线段的组，"
                    f"距离编号 {best_distance:.2f}mm"
                )
            else:
                # 兜底：使用所有候选线段
                matched_lines.extend(candidate_lines)
                code_matched_lines[code] = candidate_lines
    
    def _connect_lines_head_to_tail(
        self,
        lines: List[Dict],
        tolerance: float = 1.0
    ) -> List[List[Dict]]:
        """
        将多条线割实线进行首尾相连，返回连接后的线段组
        
        Args:
            lines: 线割实线列表 [{'entity': ..., 'length': ..., 'center': (x, y)}]
            tolerance: 首尾连接的容差（单位：mm）
        
        Returns:
            连接后的线段组列表，每组包含首尾相连的线段
        """
        if not lines:
            return []
        
        # 获取每条线的端点
        line_endpoints = []
        for line in lines:
            entity = line['entity']
            entity_type = entity.dxftype()
            
            try:
                if entity_type == 'LINE':
                    start = entity.dxf.start
                    end = entity.dxf.end
                    line_endpoints.append({
                        'line': line,
                        'start': (start.x, start.y),
                        'end': (end.x, end.y)
                    })
                elif entity_type in ['LWPOLYLINE', 'POLYLINE']:
                    points = list(entity.get_points('xy'))
                    if len(points) >= 2:
                        line_endpoints.append({
                            'line': line,
                            'start': (points[0][0], points[0][1]),
                            'end': (points[-1][0], points[-1][1])
                        })
                # CIRCLE 和 ARC 不参与首尾相连
            except Exception as e:
                logging.debug(f"获取线段端点失败: {e}")
                continue
        
        if not line_endpoints:
            return [[line] for line in lines]
        
        # 使用并查集进行分组
        groups = []
        used = set()
        
        for i, line_info in enumerate(line_endpoints):
            if i in used:
                continue
            
            # 开始一个新组
            group = [line_info['line']]
            used.add(i)
            current_endpoints = [line_info['start'], line_info['end']]
            
            # 尝试连接其他线段
            changed = True
            while changed:
                changed = False
                for j, other_info in enumerate(line_endpoints):
                    if j in used:
                        continue
                    
                    other_start = other_info['start']
                    other_end = other_info['end']
                    
                    # 检查是否可以连接
                    can_connect = False
                    for endpoint in current_endpoints:
                        dist_to_start = math.sqrt(
                            (endpoint[0] - other_start[0])**2 + 
                            (endpoint[1] - other_start[1])**2
                        )
                        dist_to_end = math.sqrt(
                            (endpoint[0] - other_end[0])**2 + 
                            (endpoint[1] - other_end[1])**2
                        )
                        
                        if dist_to_start <= tolerance or dist_to_end <= tolerance:
                            can_connect = True
                            break
                    
                    if can_connect:
                        group.append(other_info['line'])
                        used.add(j)
                        # 更新当前组的端点
                        current_endpoints = [other_start, other_end]
                        changed = True
            
            groups.append(group)
        
        # 添加未参与首尾相连的线段（如圆、圆弧）
        for line in lines:
            if line not in [l for group in groups for l in group]:
                groups.append([line])
        
        logging.debug(f"首尾相连结果: {len(lines)} 条线段分为 {len(groups)} 组")
        for idx, group in enumerate(groups):
            if len(group) > 1:
                total_length = sum(l['length'] for l in group)
                logging.debug(f"  组 {idx+1}: {len(group)} 条线段，总长度 {total_length:.2f}mm")
        
        return groups
    
    def _is_hole_process(self, instruction: str) -> bool:
        """
        判断指令是否为孔工艺
        
        孔工艺的特征：
        1. 以直径符号（'Φ' 或 '∅'）+ 数字开头，或以 数字 -Φ/∅ 开头
        2. 包含"割"字（表示线割工艺）
        
        Args:
            instruction: 工艺指令文本
        
        Returns:
            True 如果是孔工艺，False 否则
        """
        if not instruction or '割' not in instruction:
            return False
        
        # 匹配模式：以 Φ或∅ + 数字（可选小数）开头，或者以 数字 -Φ/∅ 开头
        boring_pattern = re.compile(r'^(?:\d+\s*[-\-]\s*)?[Φ∅]\d+(?:\.\d+)?')
        return boring_pattern.match(instruction) is not None
    
    def match_lines_to_codes_with_count(
        self, 
        red_lines: List[Dict], 
        text_positions: Dict[str, List[Tuple[float, float]]],
        wire_cut_info: Dict[str, int],
        processing_instructions: Optional[Dict[str, str]] = None
    ) -> Tuple[List[Dict], List[Dict], Dict[str, List[Dict]]]:
        """
        将线割实线与工艺编号配对，并验证数量是否匹配（支持一个编号多次出现）
        
        新策略：基于位置的一对一匹配
        - 当一个编号在图纸中出现多次时（如 2 个 L），为每个位置独立匹配线割实线
        - 优先使用连通性分析识别由多个实体组成的轮廓
        - 包含兜底机制：当使用中心点配对失败时，使用最近距离配对
        - 孔工艺限制：如果是孔工艺（以Φ或∅开头且包含"割"），只能匹配圆形（CIRCLE）实体
        
        Args:
            red_lines: 线割实线列表 [{'entity': ..., 'length': ..., 'center': (x, y), 'start': ..., 'end': ..., 'type': ...}]
            text_positions: 工艺编号位置 {code: [(x1, y1), (x2, y2), ...]}
            wire_cut_info: 工艺编号及数量 {code: count}
            processing_instructions: 加工说明字典 {code: instruction}，用于判断是否为孔工艺
        
        Returns:
            (配对成功的线割实线列表, 数量不匹配的异常列表, 每个编号对应的线割实线字典)
        """
        matched_lines = []
        code_matched_lines = {code: [] for code in wire_cut_info.keys()}
        used_line_indices = set()  # 记录已使用的线割实线索引
        
        logging.info("🔍 基于位置的一对一匹配策略")
        
        # 判断每个编号是否为孔工艺
        hole_process_codes = {}
        if processing_instructions:
            for code in wire_cut_info.keys():
                instruction = processing_instructions.get(code, '')
                is_hole = self._is_hole_process(instruction)
                hole_process_codes[code] = is_hole
                if is_hole:
                    logging.info(f"🔵 编号 '{code}' 识别为孔工艺，只能匹配圆形（CIRCLE）实体")
        
        # 为每个编号的每个位置独立匹配线割实线
        for code, positions in text_positions.items():
            expected_count = wire_cut_info.get(code, 1)
            is_hole_process = hole_process_codes.get(code, False)
            
            if len(positions) != expected_count:
                logging.warning(
                    f"⚠️ 编号 '{code}' 在图纸中出现 {len(positions)} 次，"
                    f"但期望数量为 {expected_count}"
                )
            
            # 为每个位置匹配线割实线
            for pos_idx, (text_x, text_y) in enumerate(positions):
                logging.debug(f"为编号 '{code}' 的第 {pos_idx + 1} 个位置 ({text_x:.1f}, {text_y:.1f}) 匹配线割实线")
                
                # 找到距离该位置最近的未使用线割实线
                best_line = None
                best_line_idx = None
                best_distance = float('inf')
                
                for idx, line in enumerate(red_lines):
                    if idx in used_line_indices:
                        continue
                    
                    if not line['center']:
                        continue
                    
                    # 孔工艺限制：只能匹配圆形实体
                    if is_hole_process:
                        entity_type = line['entity'].dxftype()
                        if entity_type != 'CIRCLE':
                            continue
                    
                    line_x, line_y = line['center']
                    distance = math.sqrt((line_x - text_x)**2 + (line_y - text_y)**2)
                    
                    if distance < best_distance:
                        best_distance = distance
                        best_line = line
                        best_line_idx = idx
                
                # 如果找到了符合条件的线割实线
                if best_line and best_distance <= self.proximity_threshold:
                    # 检查是否需要连通性分析
                    should_try_connectivity = (
                        best_line['length'] < 30.0 and 
                        best_line.get('type') in ['LINE', 'ARC']
                    )
                    
                    if should_try_connectivity:
                        logging.debug(
                            f"  找到小实体 ({best_line['length']:.2f}mm)，"
                            f"尝试连通性分析"
                        )
                        
                        # 从该实体开始查找连通组
                        connected_indices, total_length = self.find_connected_entities(
                            red_lines, [best_line_idx], tolerance=0.5
                        )
                        
                        # 检查连通的实体是否都未被使用
                        all_unused = all(i not in used_line_indices for i in connected_indices)
                        
                        if len(connected_indices) > 1 and all_unused:
                            # 找到了连通组，且都未被使用
                            # 为连通组中的每条线添加连通组标记（使用位置索引作为组ID）
                            connectivity_group_id = f"{code}_pos{pos_idx + 1}"
                            connected_lines = []
                            for i in connected_indices:
                                line_copy = red_lines[i].copy()
                                line_copy['connectivity_group_id'] = connectivity_group_id
                                connected_lines.append(line_copy)
                            
                            matched_lines.extend(connected_lines)
                            code_matched_lines[code].extend(connected_lines)
                            used_line_indices.update(connected_indices)
                            
                            logging.info(
                                f"✅ 编号 '{code}' 位置 {pos_idx + 1} 通过连通性分析匹配到 "
                                f"{len(connected_indices)} 个连通实体，总长度 {total_length:.2f}mm"
                            )
                        else:
                            # 没有找到连通组或已被使用，使用单个实体
                            matched_lines.append(best_line)
                            code_matched_lines[code].append(best_line)
                            used_line_indices.add(best_line_idx)
                            
                            logging.info(
                                f"✅ 编号 '{code}' 位置 {pos_idx + 1} 匹配到 1 条线割实线，"
                                f"长度 {best_line['length']:.2f}mm，距离 {best_distance:.2f}mm"
                            )
                    else:
                        # 正常大小的实体，直接使用
                        matched_lines.append(best_line)
                        code_matched_lines[code].append(best_line)
                        used_line_indices.add(best_line_idx)
                        
                        logging.info(
                            f"✅ 编号 '{code}' 位置 {pos_idx + 1} 匹配到 1 条线割实线，"
                            f"长度 {best_line['length']:.2f}mm，距离 {best_distance:.2f}mm"
                        )
                else:
                    # 没有找到符合条件的线割实线
                    if best_line:
                        logging.warning(
                            f"⚠️ 编号 '{code}' 位置 {pos_idx + 1} 最近的线割实线距离 "
                            f"{best_distance:.2f}mm 超过阈值 {self.proximity_threshold}mm"
                        )
                    else:
                        logging.warning(
                            f"⚠️ 编号 '{code}' 位置 {pos_idx + 1} 未找到可用的线割实线"
                        )
        
        # 兜底机制：对于未匹配成功的编号位置，使用最近点距离进行二次匹配
        unmatched_positions = []
        for code, positions in text_positions.items():
            matched_count = len(code_matched_lines.get(code, []))
            if matched_count < len(positions):
                # 有位置未匹配成功
                unmatched_positions.append((code, positions))
        
        if unmatched_positions:
            logging.info("🔄 启动兜底机制：使用最近点距离进行二次匹配")
            
            for code, positions in unmatched_positions:
                # 获取当前编号的孔工艺状态
                is_hole_process_current = hole_process_codes.get(code, False)
                
                for pos_idx, (text_x, text_y) in enumerate(positions):
                    # 检查这个位置是否已经匹配过（通过检查是否有对应的匹配记录）
                    # 简化判断：如果该编号的匹配数量已经足够，跳过
                    if len(code_matched_lines.get(code, [])) >= wire_cut_info.get(code, 1):
                        continue
                    
                    logging.debug(f"兜底匹配：为编号 '{code}' 的第 {pos_idx + 1} 个位置 ({text_x:.1f}, {text_y:.1f}) 使用最近点距离")
                    
                    # 使用最近点距离查找线割实线
                    best_line = None
                    best_line_idx = None
                    best_min_distance = float('inf')
                    
                    for idx, line in enumerate(red_lines):
                        if idx in used_line_indices:
                            continue
                        
                        # 孔工艺限制：只能匹配圆形实体
                        if is_hole_process_current:
                            entity_type = line['entity'].dxftype()
                            if entity_type != 'CIRCLE':
                                continue
                        
                        # 计算文本位置到实体的最近距离
                        min_distance = self._calculate_min_distance_to_entity(
                            line['entity'], text_x, text_y
                        )
                        
                        if min_distance < best_min_distance:
                            best_min_distance = min_distance
                            best_line = line
                            best_line_idx = idx
                    
                    # 如果找到了符合条件的线割实线
                    if best_line and best_min_distance <= self.proximity_threshold:
                        # 检查是否需要连通性分析
                        should_try_connectivity = (
                            best_line['length'] < 30.0 and 
                            best_line.get('type') in ['LINE', 'ARC']
                        )
                        
                        if should_try_connectivity:
                            logging.debug(
                                f"  找到小实体 ({best_line['length']:.2f}mm)，"
                                f"尝试连通性分析"
                            )
                            
                            # 从该实体开始查找连通组
                            connected_indices, total_length = self.find_connected_entities(
                                red_lines, [best_line_idx], tolerance=0.5
                            )
                            
                            # 检查连通的实体是否都未被使用
                            all_unused = all(i not in used_line_indices for i in connected_indices)
                            
                            if len(connected_indices) > 1 and all_unused:
                                # 找到了连通组，且都未被使用
                                # 为连通组中的每条线添加连通组标记（使用位置索引作为组ID）
                                connectivity_group_id = f"{code}_fallback_pos{pos_idx + 1}"
                                connected_lines = []
                                for i in connected_indices:
                                    line_copy = red_lines[i].copy()
                                    line_copy['connectivity_group_id'] = connectivity_group_id
                                    connected_lines.append(line_copy)
                                
                                matched_lines.extend(connected_lines)
                                code_matched_lines[code].extend(connected_lines)
                                used_line_indices.update(connected_indices)
                                
                                logging.info(
                                    f"✅ [兜底] 编号 '{code}' 位置 {pos_idx + 1} 通过连通性分析匹配到 "
                                    f"{len(connected_indices)} 个连通实体，总长度 {total_length:.2f}mm，最近点距离 {best_min_distance:.2f}mm"
                                )
                            else:
                                # 没有找到连通组或已被使用，使用单个实体
                                matched_lines.append(best_line)
                                code_matched_lines[code].append(best_line)
                                used_line_indices.add(best_line_idx)
                                
                                logging.info(
                                    f"✅ [兜底] 编号 '{code}' 位置 {pos_idx + 1} 匹配到 1 条线割实线，"
                                    f"长度 {best_line['length']:.2f}mm，最近点距离 {best_min_distance:.2f}mm"
                                )
                        else:
                            # 正常大小的实体，直接使用
                            matched_lines.append(best_line)
                            code_matched_lines[code].append(best_line)
                            used_line_indices.add(best_line_idx)
                            
                            logging.info(
                                f"✅ [兜底] 编号 '{code}' 位置 {pos_idx + 1} 匹配到 1 条线割实线，"
                                f"长度 {best_line['length']:.2f}mm，最近点距离 {best_min_distance:.2f}mm"
                            )
                    else:
                        # 仍然没有找到符合条件的线割实线
                        if best_line:
                            logging.warning(
                                f"⚠️ [兜底] 编号 '{code}' 位置 {pos_idx + 1} 最近点距离 "
                                f"{best_min_distance:.2f}mm 仍超过阈值 {self.proximity_threshold}mm"
                            )
        
        # 检查数量是否匹配
        # 注意：需要考虑连通组，同一个连通组的多个实体算作1个
        count_mismatches = []
        for code, expected_count in wire_cut_info.items():
            matched_items = code_matched_lines.get(code, [])
            
            # 统计连通组数量：有 connectivity_group_id 的实体按组计数，没有的按单个计数
            connectivity_groups = set()
            individual_count = 0
            
            for item in matched_items:
                if 'connectivity_group_id' in item:
                    connectivity_groups.add(item['connectivity_group_id'])
                else:
                    individual_count += 1
            
            # 实际数量 = 连通组数量 + 独立实体数量
            actual_count = len(connectivity_groups) + individual_count
            
            if actual_count != expected_count:
                mismatch = {
                    'code': code,
                    'expected_count': expected_count,
                    'actual_count': actual_count
                }
                count_mismatches.append(mismatch)
                
                # 注释掉详细的警告日志，避免日志过多
                # if actual_count == 0:
                #     logging.warning(
                #         f"⚠️ 工艺编号 '{code}' 期望 {expected_count} 个线割实线，但未找到任何配对"
                #     )
                # else:
                #     logging.warning(
                #         f"⚠️ 工艺编号 '{code}' 期望 {expected_count} 个线割实线，实际找到 {actual_count} 个"
                #     )
            else:
                logging.debug(
                    f"✅ 工艺编号 '{code}' 配对成功: {actual_count}/{expected_count} 个线割实线"
                )
        
        return matched_lines, count_mismatches, code_matched_lines
    
    def filter_red_lines_by_codes(
        self,
        msp,
        bounds: Dict,
        red_lines: List[Dict],
        wire_cut_codes: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        根据线割工艺编号过滤线割实线
        
        Args:
            msp: modelspace
            bounds: 边界范围
            red_lines: 线割实线列表（已通过初步筛选）
            wire_cut_codes: 线割工艺编号列表，如果为 None 则不过滤
        
        Returns:
            过滤后的线割实线列表
        """
        # 如果没有提供线割工艺编号，返回所有线割实线
        if not wire_cut_codes:
            logging.debug(f"未提供线割编号，保留所有 {len(red_lines)} 条线割实线")
            return red_lines
        
        # 查找线割工艺编号的位置（扩展边界以查找可能在边界外的文本）
        text_positions = self.find_text_positions_in_bounds(
            msp, bounds, wire_cut_codes, expand_margin=self.text_search_expand_margin
        )
        
        if not text_positions:
            logging.warning(f"在视图边界内未找到线割工艺编号 {wire_cut_codes}，返回空列表")
            return []
        
        logging.info(f"在视图中找到 {len(text_positions)} 个线割工艺编号")
        
        # 将线割实线与工艺编号配对
        matched_lines = self.match_lines_to_codes(red_lines, text_positions)
        
        logging.info(
            f"配对结果: {len(matched_lines)}/{len(red_lines)} 条线割实线与工艺编号配对成功"
        )
        
        return matched_lines
    
    def filter_red_lines_by_codes_with_count(
        self,
        msp,
        bounds: Dict,
        red_lines: List[Dict],
        wire_cut_info: Optional[Dict[str, int]] = None,
        processing_instructions: Optional[Dict[str, str]] = None
    ) -> Tuple[List[Dict], List[Dict], Dict[str, List[Dict]]]:
        """
        根据线割工艺编号及数量过滤线割实线，并检测数量不匹配的异常
        
        Args:
            msp: modelspace
            bounds: 边界范围
            red_lines: 线割实线列表（已通过初步筛选）
            wire_cut_info: 线割工艺编号及数量 {code: count}，如果为 None 则不过滤
            processing_instructions: 加工说明字典 {code: instruction}，用于判断是否为孔工艺
        
        Returns:
            (过滤后的线割实线列表, 数量不匹配的异常列表, 每个编号对应的线割实线字典)
        """
        # 如果没有提供线割工艺信息，返回所有线割实线
        if not wire_cut_info:
            logging.debug(f"未提供线割编号，保留所有 {len(red_lines)} 条线割实线")
            return red_lines, [], {}
        
        # 查找线割工艺编号的位置（扩展边界以查找可能在边界外的文本）
        wire_cut_codes = list(wire_cut_info.keys())
        text_positions = self.find_text_positions_in_bounds(
            msp, bounds, wire_cut_codes, expand_margin=self.text_search_expand_margin
        )
        
        if not text_positions:
            logging.warning(f"在视图边界内未找到线割工艺编号 {wire_cut_codes}，返回空列表")
            # 如果在这个视图中没有找到任何工艺编号文本，不生成数量不匹配异常
            # 因为这可能是正常的（工艺编号可能在其他视图中）
            return [], [], {}
        
        logging.info(f"在视图中找到 {len(text_positions)} 个线割工艺编号")
        
        # 将线割实线与工艺编号配对，并验证数量
        matched_lines, count_mismatches, code_matched_lines = self.match_lines_to_codes_with_count(
            red_lines, text_positions, wire_cut_info, processing_instructions
        )
        
        logging.info(
            f"配对结果: {len(matched_lines)}/{len(red_lines)} 条线割实线与工艺编号配对成功"
        )
        
        if count_mismatches:
            logging.warning(f"发现 {len(count_mismatches)} 个数量不匹配的工艺编号")
        
        return matched_lines, count_mismatches, code_matched_lines
    
    def filter_red_lines_and_count_occurrences(
        self,
        msp,
        bounds: Dict,
        red_lines: List[Dict],
        wire_cut_info: Optional[Dict[str, int]] = None,
        processing_instructions: Optional[Dict[str, str]] = None
    ) -> Tuple[List[Dict], Dict[str, int], List[Dict], Dict[str, List[Dict]]]:
        """
        根据线割工艺编号过滤线割实线，并统计每个编号在视图中出现的次数
        
        Args:
            msp: modelspace
            bounds: 边界范围
            red_lines: 线割实线列表（已通过初步筛选）
            wire_cut_info: 线割工艺编号及数量 {code: count}，如果为 None 则不过滤
            processing_instructions: 加工说明字典 {code: instruction}，用于判断是否为孔工艺
        
        Returns:
            (过滤后的线割实线列表, 编号出现次数字典 {code: occurrence_count}, 配对失败的异常列表, 每个编号对应的线割实线字典)
        """
        # 如果没有提供线割工艺信息，返回空列表（未匹配的线割实线将在额外工艺匹配阶段处理）
        if not wire_cut_info:
            logging.debug(f"未提供线割编号，返回空列表（线割实线将在额外工艺匹配阶段处理）")
            return [], {}, [], {}
        
        # 查找线割工艺编号的位置（支持同一编号多次出现，扩展边界以查找可能在边界外的文本）
        wire_cut_codes = list(wire_cut_info.keys())
        text_positions = self.find_text_positions_in_bounds(
            msp, bounds, wire_cut_codes, expand_margin=self.text_search_expand_margin
        )
        
        if not text_positions:
            logging.warning(f"在视图边界内未找到线割工艺编号 {wire_cut_codes}，返回空列表")
            # 如果在这个视图中没有找到任何工艺编号文本，返回空的出现次数
            return [], {}, [], {}
        
        # 统计每个编号在视图中出现的次数
        code_occurrences = {code: len(positions) for code, positions in text_positions.items()}
        total_occurrences = sum(code_occurrences.values())
        
        logging.info(f"在视图中找到 {len(text_positions)} 个线割工艺编号，共 {total_occurrences} 个实例")
        for code, count in code_occurrences.items():
            logging.info(f"  编号 '{code}' 在此视图中出现 {count} 次")
        
        # 将线割实线与工艺编号配对（使用带兜底机制的方法）
        matched_lines, count_mismatches, code_matched_lines = self.match_lines_to_codes_with_count(
            red_lines, text_positions, wire_cut_info, processing_instructions
        )
        
        logging.info(
            f"配对结果: {len(matched_lines)}/{len(red_lines)} 条线割实线与工艺编号配对成功"
        )
        
        # 统计每个编号匹配到的线割实线数量
        # 从 count_mismatches 获取实际配对数量
        code_line_counts = {}
        for code in wire_cut_info.keys():
            # 查找该编号的配对信息
            mismatch = next((m for m in count_mismatches if m['code'] == code), None)
            if mismatch:
                # 如果有配对信息（无论是否匹配），使用 actual_count
                code_line_counts[code] = mismatch['actual_count']
            else:
                # 如果没有配对信息，说明完全匹配，使用 expected_count
                code_line_counts[code] = wire_cut_info[code]
        
        for code in text_positions.keys():
            line_count = code_line_counts.get(code, 0)
            logging.info(f"  编号 '{code}' 在此视图中匹配到 {line_count} 条线割实线")
        
        return matched_lines, code_occurrences, count_mismatches, code_matched_lines


# 便捷函数
def create_wire_cut_filter(proximity_threshold: float = 50.0, text_search_expand_margin: float = 10.0) -> WireCutFilter:
    """
    创建线割过滤器实例
    
    Args:
        proximity_threshold: 邻近阈值（单位：mm）
        text_search_expand_margin: 文本搜索边界扩展量（单位：mm）
    
    Returns:
        WireCutFilter 实例
    """
    return WireCutFilter(
        proximity_threshold=proximity_threshold,
        text_search_expand_margin=text_search_expand_margin
    )
