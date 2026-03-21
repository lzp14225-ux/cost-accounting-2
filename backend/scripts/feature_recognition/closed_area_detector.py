# -*- coding: utf-8 -*-
"""
封闭区域检测模块
检测线割实线形成的封闭空间个数
"""
import logging
import math
from typing import List, Dict, Tuple
from collections import defaultdict


class ClosedAreaDetector:
    """封闭区域检测器 - 检测线割实线形成的封闭空间个数"""
    
    def __init__(self):
        """初始化封闭区域检测器"""
        pass
    
    def detect_closed_areas(
        self, 
        red_lines: List[Dict], 
        expected_count: int = None,
        tolerance: float = 1.0  # 增大容差到 1mm，忽略肉眼看不到的小缺口
    ) -> int:
        """
        检测线割实线形成的封闭空间个数
        
        Args:
            red_lines: 线割实线列表 [{'entity': ..., 'length': ..., 'center': (x, y)}]
            expected_count: 工艺的期望数量（仅用于日志对比，不限制实际检测结果）
            tolerance: 端点连接容差（mm）
        
        Returns:
            封闭空间的实际个数
        """
        if not red_lines:
            return 0
        
        try:
            # 调试日志：记录输入的线割实线数量和类型
            entity_types = {}
            for line_info in red_lines:
                entity_type = line_info['entity'].dxftype()
                entity_types[entity_type] = entity_types.get(entity_type, 0) + 1
            
            logging.debug(f"📊 输入 {len(red_lines)} 条线割实线: {entity_types}")
            
            # 提取所有线段的端点
            segments = []
            for line_info in red_lines:
                entity = line_info['entity']
                entity_type = entity.dxftype()
                
                if entity_type == 'LINE':
                    start = entity.dxf.start
                    end = entity.dxf.end
                    segments.append(((start.x, start.y), (end.x, end.y)))
                
                elif entity_type == 'CIRCLE':
                    # 圆本身就是一个封闭空间
                    segments.append(('CIRCLE', entity))
                
                elif entity_type == 'ARC':
                    # 圆弧作为线段处理
                    center = entity.dxf.center
                    radius = entity.dxf.radius
                    start_angle = math.radians(entity.dxf.start_angle)
                    end_angle = math.radians(entity.dxf.end_angle)
                    
                    start_x = center.x + radius * math.cos(start_angle)
                    start_y = center.y + radius * math.sin(start_angle)
                    end_x = center.x + radius * math.cos(end_angle)
                    end_y = center.y + radius * math.sin(end_angle)
                    
                    segments.append(((start_x, start_y), (end_x, end_y)))
                
                elif entity_type in ['LWPOLYLINE', 'POLYLINE']:
                    # 多段线处理逻辑：统一炸开成线段，用于后续封闭环检测
                    # 使用 virtual_entities() 方法炸开多段线（自动处理闭合和bulge）
                    try:
                        exploded_entities = list(entity.virtual_entities())
                        
                        if not exploded_entities:
                            logging.warning(f"    ⚠️ 多段线炸开后无实体，跳过")
                            continue
                        
                        # 将炸开后的实体转换为线段格式（用于后续检测）
                        for sub_entity in exploded_entities:
                            sub_type = sub_entity.dxftype()
                            if sub_type == 'LINE':
                                start = sub_entity.dxf.start
                                end = sub_entity.dxf.end
                                segments.append(((start.x, start.y), (end.x, end.y)))
                            elif sub_type == 'ARC':
                                center = sub_entity.dxf.center
                                radius = sub_entity.dxf.radius
                                start_angle = math.radians(sub_entity.dxf.start_angle)
                                end_angle = math.radians(sub_entity.dxf.end_angle)
                                start_x = center.x + radius * math.cos(start_angle)
                                start_y = center.y + radius * math.sin(start_angle)
                                end_x = center.x + radius * math.cos(end_angle)
                                end_y = center.y + radius * math.sin(end_angle)
                                segments.append(((start_x, start_y), (end_x, end_y)))
                        
                        logging.debug(f"    多段线炸开为 {len(exploded_entities)} 条线段")
                    
                    except Exception as e:
                        logging.warning(f"    ⚠️ 多段线炸开失败: {e}，使用备用方法")
                        # 备用方法：手动炸开
                        points = list(entity.get_points('xy'))
                        if len(points) >= 2:
                            for i in range(len(points) - 1):
                                p1, p2 = points[i], points[i + 1]
                                segments.append(((p1[0], p1[1]), (p2[0], p2[1])))
            
            # 统计封闭空间
            closed_count = 0
            
            # 1. 统计圆形
            circle_count = 0
            for seg in segments:
                if seg[0] == 'CIRCLE':
                    circle_count += 1
                    closed_count += 1
            
            logging.debug(f"  - 圆形: {circle_count} 个")
            
            # 2. 检测由线段和圆弧组成的封闭环
            line_segments = [seg for seg in segments if isinstance(seg[0], tuple)]
            
            logging.debug(f"  - 待检测线段: {len(line_segments)} 条")
            
            if len(line_segments) >= 3:
                # 使用并查集检测封闭环
                closed_loops = self._find_closed_loops(line_segments, tolerance)
                logging.debug(f"  - 线段形成的封闭环: {closed_loops} 个")
                closed_count += closed_loops
            
            # 3. 记录期望数量与实际检测数量的差异（仅用于日志）
            if expected_count is not None and expected_count > 0:
                if closed_count != expected_count:
                    logging.info(
                        f"ℹ️ 检测到 {closed_count} 个封闭空间，工艺期望数量为 {expected_count}"
                    )
            
            logging.info(f"🔍 检测到 {closed_count} 个封闭空间")
            return closed_count
            
        except Exception as e:
            logging.error(f"检测封闭空间失败: {str(e)}")
            return 0
    
    def _find_closed_loops(self, segments: List[Tuple], tolerance: float) -> int:
        """
        查找线段形成的封闭环
        
        使用连通分量分析：统计有多少个连通的封闭图形
        
        Args:
            segments: 线段列表 [((x1, y1), (x2, y2)), ...]
            tolerance: 端点连接容差
        
        Returns:
            封闭环的个数
        """
        if len(segments) < 3:
            return 0
        
        try:
            def points_equal(p1, p2, tol):
                """判断两个点是否相等（在容差范围内）"""
                return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2) < tol
            
            # 将所有端点归一化
            points = []
            point_map = {}  # 原始点 -> 归一化点索引
            
            for seg in segments:
                for pt in [seg[0], seg[1]]:
                    # 查找是否已有相近的点
                    found = False
                    for i, existing_pt in enumerate(points):
                        if points_equal(pt, existing_pt, tolerance):
                            point_map[pt] = i
                            found = True
                            break
                    
                    if not found:
                        point_map[pt] = len(points)
                        points.append(pt)
            
            # 构建图（邻接表）并统计每个点的度数
            graph = defaultdict(list)
            degree = defaultdict(int)
            
            for seg in segments:
                p1_idx = point_map[seg[0]]
                p2_idx = point_map[seg[1]]
                graph[p1_idx].append(p2_idx)
                graph[p2_idx].append(p1_idx)
                degree[p1_idx] += 1
                degree[p2_idx] += 1
            
            # 使用并查集统计连通分量
            parent = {i: i for i in range(len(points))}
            
            def find(x):
                if parent[x] != x:
                    parent[x] = find(parent[x])
                return parent[x]
            
            def union(x, y):
                px, py = find(x), find(y)
                if px != py:
                    parent[px] = py
            
            # 合并所有连接的点
            for seg in segments:
                p1_idx = point_map[seg[0]]
                p2_idx = point_map[seg[1]]
                union(p1_idx, p2_idx)
            
            # 统计连通分量
            components = defaultdict(list)
            for i in range(len(points)):
                root = find(i)
                components[root].append(i)
            
            # 检查每个连通分量是否形成封闭环
            # 封闭环的特征：所有点的度数都 >= 2
            closed_loops = 0
            for root, nodes in components.items():
                if len(nodes) >= 3:  # 至少3个点才能形成环
                    # 检查是否所有点的度数都 >= 2
                    all_closed = all(degree[node] >= 2 for node in nodes)
                    if all_closed:
                        closed_loops += 1
                        logging.debug(f"    发现封闭环: {len(nodes)} 个点")
            
            return closed_loops
            
        except Exception as e:
            logging.error(f"查找封闭环失败: {str(e)}")
            return 0
    
    def get_closed_area_summary(self, closed_count: int, expected_count: int = None) -> str:
        """
        生成封闭区域统计摘要
        
        Args:
            closed_count: 检测到的封闭空间个数
            expected_count: 工艺的期望数量（仅用于对比参考）
        
        Returns:
            str: 摘要文本
        """
        if closed_count == 0:
            return "无封闭区域"
        
        summary = f"{closed_count}个封闭区域"
        
        if expected_count is not None and expected_count > 0:
            if closed_count == expected_count:
                summary += f" (与期望数量一致)"
            elif closed_count < expected_count:
                summary += f" (期望{expected_count}个，少{expected_count - closed_count}个)"
            else:
                summary += f" (期望{expected_count}个，多{closed_count - expected_count}个)"
        
        return summary
