      
"""
文件内容：读取DXF文件，识别视图轮廓并创建板料线、（0，0）坐标
最后修改时间：2026-04-20
修改人：王霞、佟坤远
修改内容：
    修改根据位置判断视图位置时的排序精度
"""

from __future__ import annotations
import ezdxf
import math
import os
import datetime
import networkx as nx
import itertools
import pandas as pd
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from collections import Counter
import json

@dataclass
class ViewInfo:
    """视图信息"""
    name: str
    entity: any
    bbox: Tuple[float, float, float, float]  # (x_min, y_min, x_max, y_max)
    area: float
    center: Tuple[float, float]
    vertices: List[Tuple[float, float]]
    layer: str
@dataclass
class LineInfo:
    """线段信息"""
    entity: any
    start: Tuple[float, float]
    end: Tuple[float, float]
    angle: float  # 角度，0-180度
    length: float
    layer: str

# ==============================全局变量============================
IS_POINT_OVERLAP_TOLERANCE = 1e-3  # 点重合容差


# ===================================================================
# ========================提取并解析lwt===============================
def read_lwt_from_csv(csv_path: str, filename: str):
    """
    从CSV读取该零件的L、W、T、是否需要分中
    :param csv_path: CSV文件路径
    :param filename: 当前文件名
    :return: 一个字典，包含错误信息、L、W、T值和是否需要分中
    """
    csv_info = {}
    try:
        if not os.path.exists(csv_path):
            csv_info['error_info'] = 'CSV文件路径不存在'
            return csv_info

        # 尝试不同编码读取CSV
        try:
            df = pd.read_csv(csv_path, encoding='utf-8')
        except UnicodeDecodeError:
            try:
                df = pd.read_csv(csv_path, encoding='gbk')
            except UnicodeDecodeError:
                df = pd.read_csv(csv_path, encoding='gb18030')
        
        # 尝试匹配文件名，去除扩展名进行比较
        base_name = os.path.splitext(os.path.basename(filename))[0]
        
        # 清理列名空格
        df.columns = df.columns.str.strip()      
        if '零件名' not in df.columns:
             csv_info['error_info'] = 'dxf图纸信息汇总表中无"零件名"列'
             return csv_info

        matched_row = df[df['零件名'].astype(str).str.strip() == base_name]
        
        if matched_row.empty:
            # 尝试直接匹配（万一CSV里带扩展名）
            matched_row = df[df['零件名'].astype(str).str.strip() == os.path.basename(filename)]
            
        if matched_row.empty:
            csv_info['error_info'] = 'dxf图纸信息汇总表中未找到匹配行'
            return csv_info
            
        row = matched_row.iloc[0]  

        l = row.get('L', None)
        w = row.get('W', None)
        t = row.get('T', None)
        if not l or not w or not t or l == '0' or w == '0' or t == '0':
            csv_info['error_info'] = 'dxf图纸信息汇总表中L/W/T存在缺失'
            return csv_info
        
        csv_info['L'] = float(l)
        csv_info['W'] = float(w)
        csv_info['T'] = float(t)

        need_centering = row.get('是否分中', 'None')
        if not need_centering:
            print("  dxf图纸信息汇总表中未找到是否分中信息，默认不分中")
            csv_info['need_centering'] = False
        elif need_centering == '是':
            csv_info['need_centering'] = True
        else:
            csv_info['need_centering'] = False

        return csv_info
    
    except Exception as e:
        csv_info['error_info'] = f"读取dxf图纸信息汇总表出错: {e}"
        return csv_info

# ===================================================================
# ===========================寻找坐标点相关============================
def find_ordinate_points(doc):
    """
    遍历指定图层，查找所有坐标标注点
    """
    msp = doc.modelspace()
    dimension_entities = list(msp.query('DIMENSION'))
    zero_points = extract_and_validate_zero_point(dimension_entities)
    if not zero_points:
        print("未找到有效零点坐标标注")
    else:
        print(">>过滤后的零点标注:", zero_points)
    return zero_points

def filter_zero_points_with_two_zeros(zero_points):
    """
    Args : zero_points (list): 点的列表，每个点是一个包含 x, y, z 坐标的元组。
    Returns : list: 仅包含重复率大于等于 2 的点的列表。
    """
    rounded_points = [(round(x, 3), round(y, 3), round(z, 3)) for x, y, z in zero_points]
    # 统计每个点的出现次数
    point_counts = Counter(rounded_points)
    # 保留重复率大于等于 2 的点
    filtered_points = [point for point, count in point_counts.items() if count >= 2]
    return filtered_points

def extract_and_validate_zero_point(dimension_entities: list):
    zero_points = []
    for entity in dimension_entities:
        if hasattr(entity.dxf, 'actual_measurement') and entity.dxf.actual_measurement == 0.0:
            point = get_dimension_point(entity)
            if point:
                zero_points.append(point)
    zero_points = filter_zero_points_with_two_zeros(zero_points)
    return zero_points

def get_dimension_point(entity):
    try:
        return (entity.dxf.defpoint.x, entity.dxf.defpoint.y, entity.dxf.defpoint.z)
    except AttributeError:
        return None
    
def are_points_same(points):
    return all(round_point(point) == round_point(points[0]) for point in points)

def round_point(point):
    return tuple(round(coord, 2) for coord in point)


# ===================================================================
# ====================判断闭合区域用到的工具===========================
def is_points_in_matched_region(points: List[Tuple[float, float]], regions, tolerance=IS_POINT_OVERLAP_TOLERANCE) -> bool:
    """
    判断一组点是否全部在指定闭合区域内（包含边界），允许一定容差
    :param points: 点列表 [(x1, y1), (x2, y2), ...]
    :param regions: 闭合区域列表
    :param tolerance: 容差
    :return: True/False
    """
    count = len(regions)
    if count == 0:
        return False  # 没有区域可供判断
    
    for p in points:
        x, y = p
        in_counter = 0
        for r in regions:
            min_x, min_y, max_x, max_y = r.bbox        
            if (min_x - tolerance < x < max_x + tolerance
                and min_y - tolerance < y < max_y + tolerance):
                in_counter += 1
        if in_counter < count:
            return False  # 存在不在所有区域内的点
    return True

def get_spline_points(spline):
    """
    获取样条曲线的采样点列表（共5个点，含起点和终点）
    :param spline: ezdxf SPLINE实体
    :return: 点列表 [(x1, y1), (x2, y2), ...]
    """
    cps = []
    try:
        if hasattr(spline, 'control_points'):
            cps = [tuple(map(float, p)) for p in spline.control_points]
    except Exception:
        cps = []
	# fit points
    fps = []
    try:
        if hasattr(spline, 'fit_points'):
            fps = [tuple(map(float, p)) for p in spline.fit_points]
    except Exception:
        fps = []

    # 优先使用拟合点，其次使用控制点
    pts = fps if fps else cps
    if not pts:
        return []
    
    # 如果点数少于等于5个，直接全部返回
    if len(pts) <= 5:
        return [(p[0], p[1]) for p in pts]
    
    # 抽取5个点：起点、终点及中间均匀分布的3个点
    indices = [0, len(pts)//4, len(pts)//2, (3*len(pts))//4, len(pts)-1]
    # 去重
    unique_indices = []
    for idx in indices:
        if idx not in unique_indices:
            unique_indices.append(idx)
            
    return [(pts[i][0], pts[i][1]) for i in unique_indices]

def get_ellipse_points(ellipse):
    """
    获取椭圆的采样点列表（含起点和终点）
    :param ellipse: ezdxf ELLIPSE实体
    :return: 点列表 [(x1, y1), (x2, y2), ...]
    """
    start = end = None
    def to_tuple(v):
        try:
            return (float(v[0]), float(v[1]), float(v[2]))
        except Exception:
            return (float(v.x), float(v.y), float(v.z))

    def add(u, v):
        return (u[0] + v[0], u[1] + v[1], u[2] + v[2])

    def mul(u, s):
        return (u[0] * s, u[1] * s, u[2] * s)

    def cross(u, v):
        return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])

    def norm(u):
        return math.sqrt(u[0] * u[0] + u[1] * u[1] + u[2] * u[2])

    C = to_tuple(ellipse.dxf.center)
    A = to_tuple(ellipse.dxf.major_axis)
    a = norm(A)
    if a == 0:
        raise ValueError("ellipse major axis has zero length")

    ratio = float(getattr(ellipse.dxf, 'ratio', 1.0))
    b = a * ratio

    # 外挤向量（法向量），用于构造椭圆平面上的次轴方向
    N = to_tuple(getattr(ellipse.dxf, 'extrusion', (0, 0, 1)))
    minor_dir = cross(N, A)
    minor_norm = norm(minor_dir)
    if minor_norm == 0:
        # 退化：在 XY 平面上使用旋转90度作为次轴方向
        minor_dir = (-A[1], A[0], 0.0)
        minor_norm = norm(minor_dir)
        if minor_norm == 0:
            # 最后退化，使用 (0,0,0)
            minor_dir = (0.0, 0.0, 0.0)

    start_param = float(getattr(ellipse.dxf, 'start_param', 0.0))
    end_param = float(getattr(ellipse.dxf, 'end_param', 2 * math.pi))

    def point_at(t):
        major_term = mul(A, math.cos(t))
        if minor_norm != 0:
            minor_term = mul(minor_dir, (b / minor_norm) * math.sin(t))
        else:
            minor_term = (0.0, 0.0, 0.0)
        return add(add(C, major_term), minor_term)

    # 拟合点数：增加采样点，特别是对于大的椭圆弧，需要更多点才能保持闭合识别精度
    # 默认值
    num_pts = 10
    
    # 根据起始参数计算步长
    diff = end_param - start_param
    # 处理闭合或近闭合
    if diff >= 2 * math.pi:
        diff = 2 * math.pi
    
    result = []
    for i in range(num_pts + 1):
        t = start_param + diff * (i / num_pts)
        pt = point_at(t)
        result.append((pt[0], pt[1]))

    return result

def merge_edges(edges: List[Tuple[Tuple[float, float], Tuple[float, float]]], tolerance=IS_POINT_OVERLAP_TOLERANCE) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """
    拼接在同一条直线上并有共同端点或有重合区域的edge
    :param edges: 列表，保存线的起点和终点 [((x1, y1), (x2, y2)), ...]
    :param tolerance: 合并的容差
    :return: 拼接后的edges列表
    """
    if not edges:
        return []

    # 1. Group edges by line equation
    # 按照 (ux, uy, dist) 分组
    line_groups = {} 

    for p1, p2 in edges:
        x1, y1 = p1
        x2, y2 = p2
        
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        
        if length < 1e-9:
            continue # 忽略极短的线段
            
        # 归一化方向向量
        ux = dx / length
        uy = dy / length
        
        # 规范化方向：保证在 [0, pi) 范围内
        # 即保证 uy > 0, 或者 if uy=0 then ux > 0
        if uy < -1e-9 or (abs(uy) < 1e-9 and ux < -1e-9):
            ux = -ux
            uy = -uy
            
        # 计算原点到直线的有向距离 (叉积: x1*uy - y1*ux)
        # 该距离对于同一条直线上的点应该是常数
        dist = x1 * uy - y1 * ux
        
        # 使用简单的遍历查找来处理浮点数容差，避免直接用float做key
        found_group = False
        for key in line_groups.keys():
            k_ux, k_uy, k_dist = key
            
            # 检查方向是否平行 (点积接近1)
            dot = ux * k_ux + uy * k_uy
            if abs(dot) > 0.9999: 
                # 检查是否共线 (距离差在容差内)
                if abs(dist - k_dist) < tolerance:
                    line_groups[key].append((p1, p2))
                    found_group = True
                    break
        
        if not found_group:
             line_groups[(ux, uy, dist)] = [(p1, p2)]

    merged_edges = []
    
    for key, group_edges in line_groups.items():
        ux, uy, dist = key
        
        # 2. 投影到 1D 参数 t
        # p = t * U + dist * V (V is rotated U)
        # t = p . U
        intervals = []
        for p1, p2 in group_edges:
            t1 = p1[0] * ux + p1[1] * uy
            t2 = p2[0] * ux + p2[1] * uy
            intervals.append(sorted((t1, t2)))
            
        # 3. 合并 1D 区间
        intervals.sort(key=lambda x: x[0])
        
        if not intervals:
            continue
            
        merged_intervals = []
        current_start, current_end = intervals[0]
        
        for next_start, next_end in intervals[1:]:
            # 如果重叠或首尾相接 (gap < tolerance)
            if next_start <= current_end + tolerance:
                current_end = max(current_end, next_end)
            else:
                merged_intervals.append((current_start, current_end))
                current_start, current_end = next_start, next_end
        merged_intervals.append((current_start, current_end))
        
        # 4. 重建 2D 线段
        # x = t * ux + dist * uy
        # y = t * uy - dist * ux
        for t_start, t_end in merged_intervals:
            p_start = (t_start * ux + dist * uy, t_start * uy - dist * ux)
            p_end = (t_end * ux + dist * uy, t_end * uy - dist * ux)
            merged_edges.append((p_start, p_end))
            
    return merged_edges

def _is_point_in_region(x, y, matched_region):
    # 检查点 (x, y) 是否在 matched_region 中
    for region in matched_region:
        min_x, min_y, max_x, max_y = region.bbox
        if min_x - coordinate_point_tolerance < x < max_x + coordinate_point_tolerance and min_y - coordinate_point_tolerance < y < max_y + coordinate_point_tolerance:
            return True
    return False

def _is_polyline_in_matched_region(poly, matched_region):
    # 获取 POLYLINE 的所有点
    if poly.dxftype() == 'LWPOLYLINE':
        points = poly.get_points(format='xy')
    else:
        try:
            points = list(poly.points())
        except:
            return True  # 如果无法获取点，默认认为在 matched_region 中

    # 检查每个点是否在 matched_region 中
    for point in points:
        x, y = point[0], point[1]  # 取前两个坐标
        if _is_point_in_region(x, y, matched_region):
            return True
    return False

def _is_line_in_matched_region(line, matched_region):
    # 获取 LINE 的起点和终点
    start = (line.dxf.start.x, line.dxf.start.y)
    end = (line.dxf.end.x, line.dxf.end.y)
    
    # 检查起点和终点是否在 matched_region 中
    if (_is_point_in_region(start[0], start[1], matched_region)
        or _is_point_in_region(end[0], end[1], matched_region)):
        return True
    return False

def _get_arc_discretized_points(arc) -> List[Tuple[float, float]]:
    """
    将圆弧离散化为点序列
    为了精确计算面积和边界框，将圆弧近似为多段短直线
    """
    c = arc.dxf.center
    r = arc.dxf.radius
    start_angle = arc.dxf.start_angle
    end_angle = arc.dxf.end_angle
    
    # 处理跨越0度的情况
    if end_angle <= start_angle:
        end_angle += 360.0
        
    span = end_angle - start_angle
    
    # 估算分段数：每10度一段，或者基于精度
    # 这里的策略：每 10 度一段，且至少 4 段（如果是大圆弧），或者根据跨度决定
    segments = max(2, int(span / 10))
    if segments > 50: segments = 50 # 限制上限防止过密
    
    points = []
    for i in range(segments + 1):
        angle_deg = start_angle + (span * i / segments)
        angle_rad = math.radians(angle_deg)
        x = c.x + r * math.cos(angle_rad)
        y = c.y + r * math.sin(angle_rad)
        points.append((x, y))
        
    return points

def _is_arc_in_matched_region(arc_points, matched_region):
    for point in arc_points:
        x, y = point
        # 检查点是否在 matched_region 中
        if _is_point_in_region(x, y, matched_region):
            return True
    return False

def is_point_in_polygon(point: Tuple[float, float], 
                        polygon: List[Tuple[float, float]]) -> bool:
    """判断点是否在多边形内部（射线法）"""
    x, y = point
    n = len(polygon)
    inside = False
    
    p1x, p1y = polygon[0]
    for i in range(1, n + 1):
        p2x, p2y = polygon[i % n]
        
        # 改进：更鲁棒的射线法判断
        # 判断点是否在边的Y范围之间
        if ((p1y > y) != (p2y > y)):
            # 计算交点的X坐标
            xinters = (p2x - p1x) * (y - p1y) / (p2y - p1y) + p1x
            
            # 射线向右发射，如果点在交点左侧，则计数
            if x < xinters:
                inside = not inside
                
        p1x, p1y = p2x, p2y
    
    return inside

def is_region_inside(inner: ViewInfo, outer: ViewInfo) -> bool:
    """
    判断一个区域是否在另一个区域内部（包含嵌套或部分重合）
    """
    # 1. 边界框检查（宽松筛选，允许一定的误差）
    inner_bbox = inner.bbox
    outer_bbox = outer.bbox
    tolerance = 5.0 # 扩大容差，处理边缘重合的情况
    
    bbox_inside = (
        inner_bbox[0] >= outer_bbox[0] - tolerance and  # x_min
        inner_bbox[1] >= outer_bbox[1] - tolerance and  # y_min
        inner_bbox[2] <= outer_bbox[2] + tolerance and  # x_max
        inner_bbox[3] <= outer_bbox[3] + tolerance      # y_max
    )
    
    if not bbox_inside:
        return False
    
    # 2. 中心点检查（准确判断）
    # 即使中心点不在（例如凹形状），只要面积比例悬殊且BBox包含，极大概率是嵌套细节
    
    # 如果面积相比外轮廓很小 (< 50%) 且 BBox 在内部，直接视为嵌套
    # 这样可以处理形状奇特导致中心点在外部的情况
    area_ratio = inner.area / outer.area
    if area_ratio < 0.5:
            # 如果中心在内部，肯定是
            if is_point_in_polygon(inner.center, outer.vertices):
                return True
            
            # 如果中心不在，检查所有顶点是否大部分在BBox范围内（已由步骤1保证）
            # 进一步检查：是否所有顶点都在外轮廓多边形内（或边界上）
            # 采样检查顶点
            inside_count = 0
            total_check = 0
            step = max(1, len(inner.vertices) // 20) # 采样20个点
            
            for i in range(0, len(inner.vertices), step):
                pt = inner.vertices[i]
                # 这里使用简单的点在多边形内判断
                if is_point_in_polygon(pt, outer.vertices):
                    inside_count += 1
                total_check += 1
            
            # 如果超过一半的顶点在内部，视为嵌套
            if total_check > 0 and (inside_count / total_check) > 0.5:
                return True

    return is_point_in_polygon(inner.center, outer.vertices)

def get_arc_midpoint(p1, p2, bulge):
    """
    根据起点、终点和凸度计算圆弧中点
    :param p1: 起点 (x, y)
    :param p2: 终点 (x, y)
    :param bulge: 凸度
    :return: 中点 (x, y)
    """
    x1, y1 = p1
    x2, y2 = p2
    
    # 弦的中点
    mx = (x1 + x2) / 2
    my = (y1 + y2) / 2
    
    # 弦的向量 (dx, dy)
    dx = x2 - x1
    dy = y2 - y1
    
    # 根据 DXF 凸度定义计算中点偏移
    # 凸度 b = 2h / L，其中 h 为拱高，L 为弦长
    # 正凸度(b > 0)表示逆时针方向，圆弧向左弹出
    xm = mx + (bulge * dy) / 2
    ym = my - (bulge * dx) / 2
    
    return (xm, ym)

def extract_polyline_info(polyline) -> Optional[ViewInfo]:
    """提取多段线信息（包含圆弧处理）"""
    try:
        vertices = []
        # LWPOLYLINE
        if polyline.dxftype() == 'LWPOLYLINE':
            # 获取点和凸度 (x, y, bulge)
            points = polyline.get_points(format='xyb')
            is_closed = polyline.closed
            count = len(points)
            
            for i in range(count):
                p1 = points[i][:2]
                vertices.append(p1)
                
                # 如果有下一个点（或是闭合的），检查凸度
                if i < count - 1 or is_closed:
                    p2_idx = (i + 1) % count
                    p2 = points[p2_idx][:2]
                    bulge = points[i][2]
                    
                    if bulge != 0:
                        mid = get_arc_midpoint(p1, p2, bulge)
                        vertices.append(mid)

        # POLYLINE (2D)
        else:
            # POLYLINE: vertices 是 DXFVertex 对象列表
            # 需要手动处理
            pts = list(polyline.vertices)
            is_closed = polyline.is_closed
            count = len(pts)
            
            for i in range(count):
                v1 = pts[i]
                p1 = (v1.dxf.location.x, v1.dxf.location.y)
                vertices.append(p1)
                
                if i < count - 1 or is_closed:
                    v2 = pts[(i + 1) % count]
                    p2 = (v2.dxf.location.x, v2.dxf.location.y)
                    # POLYLINE的凸度在起点中
                    bulge = getattr(v1.dxf, 'bulge', 0)
                    
                    if bulge != 0:
                        mid = get_arc_midpoint(p1, p2, bulge)
                        vertices.append(mid)
        
        if len(vertices) < 3:
            return None
        
        # 计算边界框
        x_coords = [v[0] for v in vertices]
        y_coords = [v[1] for v in vertices]
        bbox = (min(x_coords), min(y_coords), max(x_coords), max(y_coords))
        
        # 计算中心点
        center_x = sum(x_coords) / len(x_coords)
        center_y = sum(y_coords) / len(y_coords)
        
        # 计算面积（使用鞋带公式）
        area = 0
        n = len(vertices)
        for i in range(n):
            x1, y1 = vertices[i]
            x2, y2 = vertices[(i + 1) % n]
            area += x1 * y2 - x2 * y1
        area = abs(area) / 2
        
        return ViewInfo(
            name=f"Region_{len(vertices)}pts",
            entity=polyline,
            bbox=bbox,
            area=area,
            center=(center_x, center_y),
            vertices=vertices,
            layer=polyline.dxf.layer
        )
    except Exception as e:
        print(f"  提取多段线信息失败: {e}")
        return None

def remove_duplicate_lines(lines):
    """
    添加一个函数对lines去重
    :param lines: 说明
    """
    unique_lines = []
    for line in lines:
        s = (line.dxf.start.x, line.dxf.start.y)
        e = (line.dxf.end.x, line.dxf.end.y)
        is_duplicate = False
        for unique_line in unique_lines:
            us = (unique_line.dxf.start.x, unique_line.dxf.start.y)
            ue = (unique_line.dxf.end.x, unique_line.dxf.end.y)
            if (abs(s[0] - us[0]) < 1e-3 and abs(s[1] - us[1]) < 1e-3 and
                abs(e[0] - ue[0]) < 1e-3 and abs(e[1] - ue[1]) < 1e-3):
                is_duplicate = True
                break
        if not is_duplicate:
            unique_lines.append(line)
    return unique_lines

# 图论方法识别闭合区域
def find_closed_regions_by_graph_theory_methods(G, min_area):
    """
    通过图论方法寻找闭合区域。

    参数：
        G (networkx.Graph): 输入的图。
        min_area (float): 最小闭合区域的面积。
    返回：
        list[ViewInfo]: 闭合区域的列表。
    """
    # remove nodes with degree < 2 iteratively
    core_g = nx.k_core(G, k=2) 
    if len(core_g.nodes) < 3:
        return []

    cycles = nx.cycle_basis(core_g)

    regions = []
    for cycle in cycles:
        if len(cycle) < 3:
            continue

        # 获取顶点坐标
        vertices = []
        for node_id in cycle:
            if node_id in G.nodes:  # use original G to get pos
                pos = G.nodes[node_id]['pos']
                vertices.append(pos)

        # 计算属性
        # 计算面积
        area = 0
        n = len(vertices)
        x_coords = []
        y_coords = []
        for i in range(n):
            x_coords.append(vertices[i][0])
            y_coords.append(vertices[i][1])
            x1, y1 = vertices[i]
            x2, y2 = vertices[(i + 1) % n]
            area += x1 * y2 - x2 * y1
        area = abs(area) / 2

        if area < min_area:
            continue

        center_x = sum(x_coords) / n
        center_y = sum(y_coords) / n
        bbox = (min(x_coords), min(y_coords), max(x_coords), max(y_coords))

        regions.append(ViewInfo(
            name=f"Loop_{len(cycle)}",
            entity=None,  # 虚拟实体
            bbox=bbox,
            area=area,
            center=(center_x, center_y),
            vertices=vertices,
            layer="Constructed"
        ))

    return regions

# 贪心算法寻找闭合区域
def find_closed_regions_by_greedy_angle(edges, min_area) -> List[ViewInfo]:
    """
    使用贪心最小转角策略，从所有线段出发构建可能的闭合回路。
    目标：补充那些由相邻多条线段组合但未被标记为闭合的区域（尤其是矩形/多边形轮廓被拆成多段单独线段的情况）。
    算法概述：
    - 对每条未访问的边作为起点，尝试沿着与当前边形成最小转角的相连边前进，直到回到起点或失败
    - 若构造出合法闭合回路，计算面积并作为区域返回（过滤最小面积）
    - 最后去重相似回路
    参数：
        edges (list of (start_pt, end_pt)): 输入的线段列表
        min_area (float): 过滤掉的最小闭合区域面积
    """

    def key(pt):
        # 使用粗略网格化以匹配微小误差的端点，保留2位小数(与后面的1e-2容差匹配)
        return (round(pt[0], 3), round(pt[1], 3))

    adj = {}  # key(pt) -> list of (neighbor_pt, original_pt)
    for s, e in edges:
        ks = key(s); ke = key(e)
        adj.setdefault(ks, set()).add(ke)
        adj.setdefault(ke, set()).add(ks)

    # 辅助：向量与角度计算
    def vec(a, b):
        return (b[0]-a[0], b[1]-a[1])

    def angle_between(v1, v2):
        # 返回 0..180 的夹角（度）
        ax, ay = v1; bx, by = v2
        la = math.hypot(ax, ay); lb = math.hypot(bx, by)
        if la < 1e-3 or lb < 1e-3:
            return 180.0
        dot = ax*bx + ay*by
        cosv = max(-1.0, min(1.0, dot / (la*lb)))
        return math.degrees(math.acos(cosv))

    # 贪心从每条边两端尝试构造回路
    found_loops = []
    visited_edges = set()

    # 标准化边的表示用于去重（有向）
    def edge_id(a, b):
        return (round(a[0],3), round(a[1],3), round(b[0],3), round(b[1],3))

    for s, e in edges:
        for start_dir in [(s,e), (e,s)]:
            a0, a1 = start_dir
            eid0 = edge_id(a0, a1)
            if eid0 in visited_edges:
                continue

            path = [a0, a1]
            visited_local = set([eid0])
            max_steps = 2000
            steps = 0
            success = False

            while steps < max_steps:
                steps += 1
                cur = path[-1]
                prev = path[-2]
                kcur = key(cur)
                neighbors = adj.get(kcur, set())

                # 构造候选向量并选择与入射向量转角最小的下一个点（排除回到上一点）
                in_vec = vec(prev, cur)
                best = None
                best_ang = 361.0
                tolerance = IS_POINT_OVERLAP_TOLERANCE
                # print(f"当前点: {cur}, 入射向量: {in_vec}, 邻居数量: {len(neighbors)}")
                for nb in neighbors:
                    # 排除与上一点相同
                    if abs(nb[0]-prev[0]) < tolerance and abs(nb[1]-prev[1]) < tolerance:
                        continue
                    cand_vec = vec(cur, nb)
                    ang = angle_between(in_vec, cand_vec)
                    # print(f"    邻居: {nb}, 角度: {ang}")

                    if ang < best_ang:
                        best_ang = ang
                        best = nb

                if best is None:
                    break

                # print(f"    最终选择: {best}, 角度: {best_ang}")

                # 若回到起点且路径长度 >=3 则闭合
                if abs(best[0]-path[0][0]) < tolerance and abs(best[1]-path[0][1]) < tolerance and len(path) >= 3:
                    # 闭合成功
                    success = True
                    break

                # 防止循环重复点
                if any(abs(best[0]-p[0])<tolerance and abs(best[1]-p[1])<tolerance for p in path):
                    break

                # 继续延伸
                path.append(best)
                visited_local.add(edge_id(prev, cur))

            if success:
                # 计算面积并过滤
                verts = path[:]
                n = len(verts)
                area = 0
                xs = [v[0] for v in verts]
                ys = [v[1] for v in verts]
                for i in range(n):
                    x1, y1 = verts[i]
                    x2, y2 = verts[(i+1)%n]
                    area += x1*y2 - x2*y1
                area = abs(area)/2
                if area >= min_area:
                    center_x = sum(xs)/n
                    center_y = sum(ys)/n
                    bbox = (min(xs), min(ys), max(xs), max(ys))
                    found_loops.append(ViewInfo(
                        name=f"GreedyLoop_{len(verts)}",
                        entity=None,
                        bbox=bbox,
                        area=area,
                        center=(center_x, center_y),
                        vertices=verts,
                        layer="Greedy"
                    ))
                    # 标记访问过的边
                    for i in range(len(verts)-1):
                        visited_edges.add(edge_id(verts[i], verts[i+1]))

    # 去重：按中心和面积去重
    unique = []
    for r in found_loops:
        dup = False
        for u in unique:
            dist = math.hypot(r.center[0]-u.center[0], r.center[1]-u.center[1])
            if dist < 1.0 and abs(r.area - u.area) / max(u.area, 1.0) < 0.1:
                dup = True
                break
        if not dup:
            unique.append(r)

    return unique



coordinate_point_tolerance = 0.1

# ===================================================================
# ====================生成板料线的主类=================================
class MaterialLineProjector:
    def __init__(self, dxf_path: str, lwt_info: any = None, log_file_dir: str = None):
        """
        初始化投影器
        :param lwt_info: 包含 L, W, T 信息的字典，或控制字符串 (如 "SKIP_KEYWORD_DETECTED")
        """
        self.doc = ezdxf.readfile(dxf_path)
        self.msp = self.doc.modelspace()
        self.lwt_info = lwt_info # 存储板料信息字典
        self.log_file_dir = log_file_dir      
        self.need_centering = False # 是否需要分中处理
        # 配置参数
        self.config = {
            'min_area': 1.0,  # 最小面积阈值 (设置为较小值，依靠后续相对阈值过滤)
            'min_area_ratio': 0.6,  # 最小相对面积阈值（相对于最大闭合区域）
            'max_area_ratio': 1.1,  # 最大面积比（过滤过大区域）
            'angle_tolerance': 5,  # 角度容差（度）
            'alignment_tolerance': 0.3,  # 对齐容差（比例）
            'material_layer_color': 241,  # 红色 (Red)
            'material_linetype': 'DASHED',
            'new_layer_prefix': 'PROJ_',
            'radius_threshold': 2.0,  # 最小等腰直角三角形边长阈值  
            'tolerance': 0.01,  # 判断是否相同的容差
            'material_line_tolerance': 0.6,  # 板料线与注释长度的容差 # 坐标标注点容差
            'classify_area_tolerance': 5.0,  # 面积分类容差
            'overlap_area_tolerance': 1e-2,  # 面积容差
        }        
        # 存储结果
        self.views = {}  # 识别的视图
        self.material_lines = []  # 板料线
        self.projected_lines = []  # 投影的线
        self.is_valid_material_line = False
        self._ensure_resources()
    def _ensure_resources(self):
        """确保必要的资源（线型、图层）存在"""
        # 确保线型存在
        lt_name = self.config['material_linetype']
        if lt_name not in self.doc.linetypes:
            try:
                # 定义 DASHED 线型: 0.5 draw, -0.25 gap
                self.doc.linetypes.new(lt_name, dxfattribs={
                    'description': 'Dashed',
                    'pattern': [0.5, -0.25],
                })
            except Exception as e:
                print(f"警告: 创建线型失败 {e}, 将使用 CONTINUOUS")
                self.config['material_linetype'] = 'CONTINUOUS'

    def get_all_entities(self, types=None):
        """
        获取所有指定类型的实体
        :param types: 可选的实体类型列表，如 ['LINE', 'LWPOLYLINE']
        :return: 实体列表
        """
        if types is None:
            return []

        all_entities = []
        for t in types:
            try:
                all_entities.extend(self.msp.query(t))
            except Exception as e:
                print(f"查询 {t} 类型实体失败: {e}")
        return all_entities

    def find_regions_by_bbox(self):
        """
        将所有实体的边界框进行聚类：若两个 bbox 相连或有重合则归为一类。
        对每个簇扩充 bbox 范围并保证最终返回的每个 bbox 至少包含 4 个实体。
        返回：独立的 bbox 列表 [(min_x, min_y, max_x, max_y), ...]
        """
        try:
            all_entities = self.msp.query('LINE LWPOLYLINE POLYLINE ARC CIRCLE ELLIPSE SPLINE')

            items = []
            for entity in all_entities:
                try:
                    entity_layer = getattr(entity.dxf, 'layer', '')
                    entity_color = getattr(entity.dxf, 'color', None)
                    if entity_layer.lower() == 'dim' and entity_color in (256, 4):
                        continue

                    from ezdxf import bbox
                    entity_bbox = bbox.extents([entity])
                    xmin, ymin, _ = entity_bbox.extmin
                    xmax, ymax, _ = entity_bbox.extmax
                except Exception as e:
                    print(f"获取实体边界框失败: {e}, 实体类型: {entity.dxftype()}")
                    # 某些实体可能没有 bbox 属性或出现异常，跳过
                    continue
                items.append({
                    'entity': entity,
                    'bbox': (float(xmin), float(ymin), float(xmax), float(ymax))
                })
        except Exception as e:
            print(f"查询实体失败: {e}")
            return []

        n = len(items)
        if n == 0:
            print("未查询到任何实体进行边界框聚类")
            return []
        
        print(f"总共查询到 {n} 个实体进行边界框聚类")

        # 并查集用于聚类
        parent = list(range(n))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        # bbox 相连或重合判定
        def bbox_connected(b1, b2, tol=1e-3):
            a_minx, a_miny, a_maxx, a_maxy = b1
            b_minx, b_miny, b_maxx, b_maxy = b2
            # 若两个 bbox 在 x 或 y 轴上没有间隙，则视为重合或相连
            if a_maxx < b_minx - tol or a_minx > b_maxx + tol:
                return False
            if a_maxy < b_miny - tol or a_miny > b_maxy + tol:
                return False
            return True

        # 初始按重合/相连做聚类
        for i in range(n):
            for j in range(i + 1, n):
                if bbox_connected(items[i]['bbox'], items[j]['bbox']):
                    union(i, j)

        clusters = {}
        for i in range(n):
            r = find(i)
            clusters.setdefault(r, []).append(i)

        # 构建簇信息
        clusters_list = []
        for idxs in clusters.values():
            min_x = min(items[i]['bbox'][0] for i in idxs)
            min_y = min(items[i]['bbox'][1] for i in idxs)
            max_x = max(items[i]['bbox'][2] for i in idxs)
            max_y = max(items[i]['bbox'][3] for i in idxs)
            bbox = (min_x, min_y, max_x, max_y)
            clusters_list.append({
                'bbox': bbox,
                'entities': [items[i]['entity'] for i in idxs]
            })

        # 过滤出实体数 >= 2 的簇，并构造 ViewInfo 列表返回
        regions = []
        for c in clusters_list:
            if len(c['entities']) >= 2:
                bx0 = float(c['bbox'][0])
                by0 = float(c['bbox'][1])
                bx1 = float(c['bbox'][2])
                by1 = float(c['bbox'][3])
                bbox = (bx0, by0, bx1, by1)

                # 使用 bbox 近似计算面积、中心和矩形顶点
                area = abs((bx1 - bx0) * (by1 - by0))
                center = ((bx0 + bx1) / 2.0, (by0 + by1) / 2.0)
                vertices = [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]

                regions.append(ViewInfo(
                    name=f"Cluster_{len(c['entities'])}",
                    entity=None,
                    bbox=bbox,
                    area=area,
                    center=center,
                    vertices=vertices,
                    layer="Cluster"
                ))

        return regions
    
    def find_regions_by_closed_polyline(self):
        """
        查找所有闭合多段线区域，返回 ViewInfo 列表
        """     
        polylines = self.msp.query('LWPOLYLINE POLYLINE')
        
        regions = []
        for polyline in polylines:
            if polyline.dxf.layer.lower() == 'text':
                continue
            region = None
            is_closed = False

            if polyline.dxftype() == 'LWPOLYLINE':
                # 检查 closed 标志
                if polyline.closed:
                    is_closed = True
                # 检查几何闭合 (首尾点重合)
                elif len(polyline) > 2:
                    start_pt = polyline[0]
                    end_pt = polyline[-1]
                    dist = math.sqrt((start_pt[0]-end_pt[0])**2 + (start_pt[1]-end_pt[1])**2)
                    if dist < 1e-2:
                        is_closed = True

            elif polyline.dxftype() == 'POLYLINE':
                if polyline.is_closed:
                    is_closed = True
                else:
                    try:
                        pts = list(polyline.points())
                        if len(pts) > 2:
                            start_pt = pts[0]
                            end_pt = pts[-1]
                            dist = math.sqrt((start_pt[0]-end_pt[0])**2 + (start_pt[1]-end_pt[1])**2)
                            if dist < 1:
                                is_closed = True
                    except:
                        pass
            
            if is_closed:
                region = extract_polyline_info(polyline)
                regions.append(region)

        return regions

    def get_matching_regions(self, regions: List[ViewInfo], l, w, t) -> List[ViewInfo]:
        """
        从候选区域中筛选出与板料面积匹配的区域
        """    
        matched = []
        length_tolerance = self.config.get('material_line_tolerance', 0.6)

        for region in regions:
            x_range = region.bbox[2] - region.bbox[0]
            y_range = region.bbox[3] - region.bbox[1]

            matched_flag = False
            # 匹配规则：
            # 1) x_range 与 l、y_range 与 w 同时匹配，视为匹配
            # 2) 或者任一维度能匹配上 t，也视为匹配
            if not matched_flag:
                # 情形1: 同时匹配 l 和 w（顺序不限）
                if (abs(x_range - l) < length_tolerance and abs(y_range - w) < length_tolerance):
                    matched_flag = True

            if not matched_flag:
                # 情形2: 任一维度匹配 values[2]
                if abs(x_range - t) < length_tolerance or abs(y_range - t) < length_tolerance:
                    matched_flag = True

            if matched_flag:
                matched.append(region)

        return matched

    def dedupe_regions(self, regions: List[ViewInfo], center_tol: float = 1e-2, area_rel_tol: float = 1e-3) -> List[ViewInfo]:
        """
        根据中心点距离和相对面积差对区域列表去重。
        - regions: 待去重的 ViewInfo 列表
        - center_tol: 中心点欧几里得距离阈值
        - area_rel_tol: 相对面积差阈值（以已有区域面积为基准）
        返回去重后的区域列表，保持原始出现顺序。
        """
        def _bbox_relation(b1, b2, eps=1e-6):
            """比较两个 bbox 的包含/相等关系。
            返回值：
                'equal' - 坐标完全相同（允许 eps）
                'b1_contains_b2' - b1 完全包含 b2
                'b2_contains_b1' - b2 完全包含 b1
                None - 既不包含也不相等（可能部分相交或分离）
            bbox 形式为 (xmin, ymin, xmax, ymax)
            """
            x1_min, y1_min, x1_max, y1_max = b1
            x2_min, y2_min, x2_max, y2_max = b2

            # 完全相同（考虑浮点误差）
            if (abs(x1_min - x2_min) <= eps and abs(y1_min - y2_min) <= eps and
                abs(x1_max - x2_max) <= eps and abs(y1_max - y2_max) <= eps):
                return 'equal'

            # b1 包含 b2
            if (x1_min <= x2_min + eps and y1_min <= y2_min + eps and x1_max >= x2_max - eps and y1_max >= y2_max - eps):
                return 'b1_contains_b2'

            # b2 包含 b1
            if (x2_min <= x1_min + eps and y2_min <= y1_min + eps and x2_max >= x1_max - eps and y2_max >= y1_max - eps):
                return 'b2_contains_b1'

            return None

        # 使用新列表构建的方式，避免在原列表上原地修改带来的副作用
        new_unique: List[ViewInfo] = []
        for region in regions:
            skip_region = False
            replace_indices: List[int] = []

            for idx, u in enumerate(new_unique):
                rel = _bbox_relation(region.bbox, u.bbox)
                if rel == 'equal' or rel == 'b2_contains_b1':
                    # 已存在相同或更大的区域，跳过当前 region
                    skip_region = True
                    break
                elif rel == 'b1_contains_b2':
                    # 当前 region 更大，需替换掉已存在的较小项（可能有多个）
                    replace_indices.append(idx)

            if skip_region:
                continue

            # 若有要替换的索引，按降序删除已有项以保持索引有效性
            if replace_indices:
                for i in sorted(replace_indices, reverse=True):
                    try:
                        del new_unique[i]
                    except Exception:
                        pass

            new_unique.append(region)

        return new_unique

    def find_view_contours_with_filtering(self) -> List[ViewInfo]:
        """
        查找面积前4的闭合区域（排除嵌套）
        支持：闭合多段线、首尾相连的直线/弧线
        """        
        all_regions = []
        l, w, t = float(self.lwt_info.get('L', 0)), float(self.lwt_info.get('W', 0)), float(self.lwt_info.get('T', 0))     
        matched_regions = []

        # 1. 通过连通性获取匹配区域
        regions_find_by_bbox = self.find_regions_by_bbox()
        print(f"  连通性方法初步识别出 {len(regions_find_by_bbox)} 个闭合区域")
        for r in regions_find_by_bbox:
            print(f"    区域: Area={r.area:.0f}, Center={r.center}, BBox={r.bbox}")
        matched_regions.extend(self.get_matching_regions(regions_find_by_bbox, l, w, t))

        # 2. 通过闭合多段线获取匹配区域
        regions_find_by_closed_polyline = self.find_regions_by_closed_polyline()
        print(f"  闭合多段线方法初步识别出 {len(regions_find_by_closed_polyline)} 个闭合区域")
        matched_regions.extend(self.get_matching_regions(regions_find_by_closed_polyline, l, w, t))
  

        # 3. 对matched_regions进行去重，中心点和面积都非常接近的只保留一个
        unique_matched = self.dedupe_regions(matched_regions)
        print(f"  多段线和连通性方法识别出 {len(unique_matched)} 个闭合区域匹配板料面积")

        if len(unique_matched) >= 4:
            return unique_matched[:4]
        
        # 通过图论和贪心算法获得更多闭合区域（排除已识别区域内的线段）
        remind_regions = self._find_closed_loops_from_lines(unique_matched)
        if remind_regions:
            all_regions.extend(remind_regions)

        # 1.5 统一过滤过大或过小区域（关键修正）
        if all_regions:
            # 使用 L, W, T 两两组合面积的最大值作为基准面积
            max_area_by_lwt = max(l*w, l*t, w*t)
            max_rel_ratio = self.config['max_area_ratio']
            max_area_threshold = max_area_by_lwt * max_rel_ratio
            
            # 使用 L, W, T 两两组合面积的最小值作为基准面积
            # 正常视图的面积应该不小于 min(L*W, L*T, W*T) 的某个比例
            min_area_by_lwt = min(l*w, l*t, w*t)
            
            # 过滤掉小于基准面积 * ratio 的区域
            min_rel_ratio = self.config['min_area_ratio']
            min_area_threshold = min_area_by_lwt * min_rel_ratio 
            
            print(f"  过滤过大或过小区域: 最小基准面积={min_area_by_lwt:.0f}, 最小阈值={min_area_threshold:.0f} 最大基准面积={max_area_by_lwt:.0f}, 最大阈值={max_area_threshold:.0f}")
            filtered_regions = []
            for r in all_regions:
                # 保留面积在阈值之上的区域
                if r.area > min_area_threshold:
                     # 同时也限制不能过大
                    if r.area < max_area_threshold:
                        filtered_regions.append(r)
            all_regions = filtered_regions

        # 2. 按面积降序排序
        all_regions.sort(key=lambda r: r.area, reverse=True)

        # 2.5 全局去重：中心点和面积都非常接近的只保留一个
        unique_regions = []
        for region in all_regions:
            is_duplicate = False
            for u in unique_regions:
                dist = math.hypot(region.center[0] - u.center[0], region.center[1] - u.center[1])
                area_diff = abs(region.area - u.area) / max(u.area, 1.0)
                if dist < 1e-2 and area_diff < self.config['overlap_area_tolerance']:
                    is_duplicate = True
                    break
            if not is_duplicate:
                unique_regions.append(region)

        print(f"  图论和贪心总计提取到 {len(unique_regions)} 个闭合区域（去重后）")
        # 依次打印这些区域
        # for region in unique_regions:
        #     print(f"    区域: Area={region.area:.0f}, Center={region.center}, BBox={region.bbox}")

        selected_regions = []
        # 3. 筛选前4个非嵌套区域(去掉通过闭合多段线识别到的区域数量)
        for region in unique_regions:
            if len(selected_regions) >= 4 - len(unique_matched):
                break
            # 检查是否在已选区域内部
            is_inside_any = False
            for selected in selected_regions:
                if is_region_inside(region, selected):
                    is_inside_any = True
                    break
            # 简单去重：如果两个区域中心非常接近且面积接近，视为同一个
            for selected in selected_regions:
                dist = math.sqrt((region.center[0]-selected.center[0])**2 + (region.center[1]-selected.center[1])**2)
                area_diff = abs(region.area - selected.area) / selected.area
                if dist < 10.0 and area_diff < 0.1: # 阈值可调
                    is_inside_any = True # 视为重复
                    break
            if not is_inside_any:
                selected_regions.append(region)
                print(f"  选中区域: Area={region.area:.0f}\n "
                      f"        x_range = [{region.bbox[0], region.bbox[2]}, y_range = [{region.bbox[1], region.bbox[3]}]]\n")
            else:
                pass # print(f"  跳过嵌套或重复区域")   

        for region in unique_matched:
            selected_regions.append(region)
        return selected_regions
    
    # 通过图论和贪心算法获得更多闭合区域（排除已识别区域内的线段）
    def _find_closed_loops_from_lines(self, matched_regions: List[ViewInfo]) -> List[ViewInfo]:
        """
        通过图论和贪心算法获得更多闭合区域（排除已识别区域内的线段）
        param matched_regions: 已识别的区域列表，用于排除区域内的线段
        return: 识别出的闭合区域列表
        """
        try:
            import networkx as nx
        except ImportError:
            print("警告: 缺少 networkx 库，无法进行拓扑分析。请运行 pip install networkx")
            return []
        
        G = nx.Graph() # 图论的图
        pos_map = {}  # 坐标 -> 节点ID
        next_node_id = 0
        
        def get_node_id(x, y):
            nonlocal next_node_id
            # 简单的网格化以处理浮点误差
            key = (round(x, 3), round(y, 3)) 
            if key not in pos_map:
                pos_map[key] = next_node_id
                G.add_node(next_node_id, pos=(x, y))
                next_node_id += 1
            return pos_map[key]
        
        # 为贪心识别边，保存边的起点和终点
        edges = [] # 未拼接的边

        # 获取所有不在 matched_regions 内的LINE, ARC, POLYLINE(不闭合)
        # 1. 收集所有 LINE
        original_lines = self.msp.query('LINE')
        lines = []
        l, w, t = float(self.lwt_info.get('L', 0)), float(self.lwt_info.get('W', 0)), float(self.lwt_info.get('T', 0))
        for line in original_lines:
            # 如果线在TEXT图层上，则跳过
            if line.dxf.layer.lower() == 'text':
                continue
            # 检查 LINE 是否在 matched_region 中或其边上
            if not _is_line_in_matched_region(line, matched_regions):
                # 线的类型为DASHED且长度不接近板料边长，则跳过
                # 如果line的类型是DASHED，则计算line的长度，如果line的长度不接近LWT任意一个长度，则跳过
                if line.dxf.linetype == 'DASHED':
                    line_length = math.hypot(line.dxf.end.x - line.dxf.start.x, line.dxf.end.y - line.dxf.start.y)
                    lwt_lengths = [self.lwt_info.get(key) for key in ['L', 'W', 'T'] if self.lwt_info.get(key) is not None]
                    if not any(abs(line_length - lwt_length) < self.config['material_line_tolerance'] for lwt_length in lwt_lengths):
                        continue
                lines.append(line)        

        # 对lines进行去重
        lines = remove_duplicate_lines(lines)
        for line in lines:
            s = (line.dxf.start.x, line.dxf.start.y)
            e = (line.dxf.end.x, line.dxf.end.y)
            edges.append((s, e))
            u = get_node_id(s[0], s[1])
            v = get_node_id(e[0], e[1])
            if u != v:
                length = math.sqrt((s[0] - e[0])**2 + (s[1] - e[1])**2)
                G.add_edge(u, v, weight=length, entity=None)  # 合并后的线段没有具体实体                
        
        # 2. 收集不闭合的 LWPOLYLINE 和 POLYLINE (炸开成边)
        polylines = self.msp.query('LWPOLYLINE POLYLINE')
        for poly in polylines:
            # 如果多段线在TEXT图层上，则跳过
            if poly.dxf.layer.lower() == 'text' or poly.dxf.linetype == 'DASHED':
                continue
            # 检查 POLYLINE 是否在 matched_regions 中或其边上
            if not _is_polyline_in_matched_region(poly, matched_regions):
                pts = []
                
                if poly.dxftype() == 'LWPOLYLINE':
                    pts = poly.get_points(format='xy')
                else: # POLYLINE
                    try:
                        pts = list(poly.points())
                    except:
                        continue
                    
                # 优化：检查多段线是否共线。如果所有点都在起终点连线上，则简化为单条线段
                is_all_collinear = True
                if len(pts) > 2:
                    p0 = pts[0]
                    pn = pts[-1]
                    dx = pn[0] - p0[0]
                    dy = pn[1] - p0[1]
                    dist_sq = dx*dx + dy*dy
                    if dist_sq < 1e-4:
                        is_all_collinear = False # 长度极短或重叠点
                    else:
                        for k in range(1, len(pts)-1):
                            pk = pts[k]
                            # 点到直线距离。分子为叉积，分母为底边长
                            area2 = abs((pk[0]-p0[0])*dy - (pk[1]-p0[1])*dx)
                            if (area2**2 / dist_sq) > 1e-3: # 距离阈值 0.1
                                is_all_collinear = False
                                break
                
                if is_all_collinear and len(pts) >= 2:
                    # 简化：只取起终点组成的直线段
                    simplified_segments = [((pts[0][0], pts[0][1]), (pts[-1][0], pts[-1][1]))]
                else:
                    # 不共线或点数少：保留所有原始段
                    simplified_segments = []
                    for i in range(len(pts)-1):
                        simplified_segments.append(((pts[i][0], pts[i][1]), (pts[i+1][0], pts[i+1][1])))

                for p1, p2 in simplified_segments:
                    edges.append((p1, p2))
                    u = get_node_id(p1[0], p1[1])
                    v = get_node_id(p2[0], p2[1])
                    if u != v:
                        length = math.hypot(p1[0]-p2[0], p1[1]-p2[1])
                        G.add_edge(u, v, weight=length, entity=poly)

        # 3. 收集所有 ARC (离散化处理)
        arcs = self.msp.query('ARC')
        for arc in arcs:
            # 如果ARC在TEXT图层上，则跳过
            if arc.dxf.layer.lower() == 'text' or arc.dxf.linetype == 'DASHED':
                continue

            # 检查 ARC 是否在 matched_region 中或其边上
            pts = _get_arc_discretized_points(arc)
            if not _is_arc_in_matched_region(pts, matched_regions):
                for i in range(len(pts) - 1):
                    p1 = pts[i]
                    p2 = pts[i+1]
                    edges.append((p1, p2))
                    u = get_node_id(p1[0], p1[1])
                    v = get_node_id(p2[0], p2[1])
                    if u != v:
                        length = math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)
                        G.add_edge(u, v, weight=length, entity=arc)

        # 4. 收集所有 SPLINE 和 ELLIPSE (起点和终点)
        splines = self.msp.query('SPLINE')
        for spline in splines:
            # 如果SPLINE在TEXT图层上，则跳过
            if spline.dxf.layer.lower() == 'text' or spline.dxf.linetype == 'DASHED':
                continue
            points = get_spline_points(spline)
            # 检查 SPLINE 是否在 matched_region 中或其边上
            if not is_points_in_matched_region(points, matched_regions):
                for i in range(len(points) - 1):
                    p1 = points[i]
                    p2 = points[i+1]
                    edges.append((p1, p2))
                    u = get_node_id(p1[0], p1[1])
                    v = get_node_id(p2[0], p2[1])
                    if u != v:
                        length = math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)
                        G.add_edge(u, v, weight=length, entity=spline)
        ellipses = self.msp.query('ELLIPSE')
        for ellipse in ellipses:
            # 如果ELLIPSE在TEXT图层上，则跳过
            if ellipse.dxf.layer.lower() == 'text' or ellipse.dxf.linetype == 'DASHED':
                continue
            points = get_ellipse_points(ellipse)
            # 检查 ELLIPSE 是否在 matched_region 中或其边上
            if not is_points_in_matched_region(points, matched_regions):
                for i in range(len(points) - 1):
                    p1 = points[i]
                    p2 = points[i+1]
                    edges.append((p1, p2))
                    u = get_node_id(p1[0], p1[1])
                    v = get_node_id(p2[0], p2[1])
                    if u != v:
                        length = math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)
                        G.add_edge(u, v, weight=length, entity=ellipse)

        # 合并所有在一条直线上的边
        merged_edges = merge_edges(edges)
        print(f"合并后的边数: {len(merged_edges)}")
        for edge in merged_edges:
            print(f"合并后的边: {edge}")

        result_regions = []
        # 5. 查找闭合回路 (Cycle Basis)
        # 5.1 通过图论算法:# 拓扑构建（合并散碎线段）
        regions_found_by_graph_theory = find_closed_regions_by_graph_theory_methods(G, self.config['min_area'])
        if regions_found_by_graph_theory:
            result_regions.extend(regions_found_by_graph_theory)
            print(f"  图论方法识别出 {len(regions_found_by_graph_theory)} 个闭合区域")
        else:
            print("  图论方法未识别出闭合区域")

        # 5.2 通过贪心算法（遍历未拼接的边）
        if edges != []:
            regions_found_by_greedy_1 = find_closed_regions_by_greedy_angle(edges, self.config['min_area'])
            if regions_found_by_greedy_1:
                result_regions.extend(regions_found_by_greedy_1)
                print(f"  贪心方法（遍历未拼接的边）识别出 {len(regions_found_by_greedy_1)} 个闭合区域")

            else:
                print("  贪心方法（遍历未拼接的边）未识别出闭合区域")
        # 5.2 通过贪心算法（遍历拼接过的边）
        if merged_edges != []:
            regions_found_by_greedy_2 = find_closed_regions_by_greedy_angle(merged_edges, self.config['min_area'])
            if regions_found_by_greedy_2:
                result_regions.extend(regions_found_by_greedy_2)
                print(f"  贪心方法（遍历拼接过的边）识别出 {len(regions_found_by_greedy_2)} 个闭合区域")
            else:
                print("  贪心方法（遍历拼接过的边）未识别出闭合区域")

        return result_regions
     
    def _identify_view_by_lwt(self, region: ViewInfo):
        """
        根据LWT信息判断闭合区域的视图类型（模糊匹配）
        判据：
        1. 对应L和W -> 主视图
        2. x差值对应T -> 侧视图
        3. y差值对应T -> 正视图
        """
        if not self.lwt_info:
            return None
            
        l = self.lwt_info.get('L')
        w = self.lwt_info.get('W')
        t = self.lwt_info.get('T')
        
        if l is None or w is None or t is None:
            return None
            
        dx = region.bbox[2] - region.bbox[0]
        dy = region.bbox[3] - region.bbox[1]
        
        tolerance = 5.0
        
        result = []
        # 1. 主视图判断 (L x W)
        if (abs(dx - l) < tolerance and abs(dy - w) < tolerance) or \
           (abs(dx - w) < tolerance and abs(dy - l) < tolerance):
           result.append('main_view')
           
        # 2. 侧视图判断 (x差值对应T)
        # if abs(dx - t) < tolerance and abs(dy - w) < tolerance:
        if abs(dx - t) < tolerance:
            result.append('side_view')
            
        # 3. 正视图判断 (y差值对应T)
        # if abs(dy - t) < tolerance and abs(dx - l) < tolerance:
        if abs(dy - t) < tolerance:
            result.append('front_view')
            
        return result

    def identify_views_with_alignment(self, regions: List[ViewInfo]):
        """
        识别视图（基于LWT和位置关系）
        """
        num_regions = len(regions)
        if num_regions == 0:
            raise ValueError("未找到任何闭合区域")

        self.views = {}

        # 遍历所有闭合区域，尝试基于LWT信息识别
        for region in regions:
            view_types = self._identify_view_by_lwt(region)
            # view_type 存在且未被识别过（self.views 中没有该类型）
            if view_types != []:
                for view_type in view_types:
                    if view_type not in self.views:
                        self.views[view_type] = []
                    self.views[view_type].append(region)

        # 筛选视图，按左上角点位置排序，主视图选择匹配的视图中最左上角，侧视图选择最右侧的，正视图选择最下侧的
        main_view, side_view, front_view = None, None, None
        if 'main_view' not in self.views:
            return False
        print(f"  识别到主视图数量: {len(self.views['main_view'])}")
        self.views['main_view'].sort(key=lambda r: (round(r.bbox[0], 0), round(-r.bbox[1], 0)))  # 按 x_min 从小到大排序，再按 y_min 从大到小排序
        main_view = self.views['main_view'][0]
        print(f"主视图区域x_range={main_view.bbox[0], main_view.bbox[2]}")
        if 'side_view' in self.views:
            for view in self.views['side_view'][:]:
                if view == main_view:
                    self.views['side_view'].remove(view)
                elif view.bbox[0] < main_view.bbox[2]:  # 侧视图应在主视图右侧
                    self.views['side_view'].remove(view)
            if len(self.views['side_view']) == 0:
                del self.views['side_view']
            else:
                self.views['side_view'].sort(key=lambda r: r.bbox[0], reverse=True)  # 按 x_min 从大到小排序
                side_view = self.views['side_view'][0]
        if 'front_view' in self.views:
            for view in self.views['front_view'][:]:
                if view == main_view:
                    self.views['front_view'].remove(view)
                elif view.bbox[3] > main_view.bbox[1]:  # 正视图应在主视图下方
                    self.views['front_view'].remove(view)
            if len(self.views['front_view']) == 0:
                del self.views['front_view']
            else:
                self.views['front_view'].sort(key=lambda r: r.bbox[1])  # 按 y_min 从小到大排序
                front_view = self.views['front_view'][0]

        try:
            for key, view in self.views.items():
                if side_view:
                    if side_view in view and side_view != view[0]:
                        view.remove(side_view)
                if front_view:
                    if front_view in view and front_view != view[0]:
                        view.remove(front_view)
        except Exception as e:
            print(f'{e}')

        return True

    def _bbox_size(self, bbox: Tuple[float, float, float, float]) -> Tuple[float, float]:
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _bbox_gap(self, base_bbox: Tuple[float, float, float, float], reference_bbox: Tuple[float, float, float, float], axis: str) -> float:
        """计算两个 bbox 在指定方向上的空白间距。"""
        if axis == 'x':
            if reference_bbox[0] >= base_bbox[2]:
                return reference_bbox[0] - base_bbox[2]
            if base_bbox[0] >= reference_bbox[2]:
                return base_bbox[0] - reference_bbox[2]
        else:
            if reference_bbox[1] >= base_bbox[3]:
                return reference_bbox[1] - base_bbox[3]
            if base_bbox[1] >= reference_bbox[3]:
                return base_bbox[1] - reference_bbox[3]
        return 0.0

    def _build_virtual_view(self, name: str, main_view: ViewInfo, reference_view: Optional[ViewInfo], direction: str) -> ViewInfo:
        """
        基于主视图与已匹配视图的间距，构造缺失的虚拟视图。
        direction: 'down' 表示放在主视图下方，'right' 表示放在主视图右侧。
        """
        main_width, main_height = self._bbox_size(main_view.bbox)
        fallback_span = float(self.lwt_info.get('T', 0) or 0)

        if direction == 'down':
            gap = self._bbox_gap(main_view.bbox, reference_view.bbox, 'x') if reference_view else fallback_span
            ref_width = self._bbox_size(reference_view.bbox)[0] if reference_view else 0.0
            height = ref_width if ref_width > self.config['tolerance'] else fallback_span
            if height <= 0:
                height = max(main_height, fallback_span, 1.0)
            x_min, x_max = main_view.bbox[0], main_view.bbox[2]
            y_max = main_view.bbox[1] - gap
            y_min = y_max - height
        elif direction == 'right':
            gap = self._bbox_gap(main_view.bbox, reference_view.bbox, 'y') if reference_view else fallback_span
            ref_height = self._bbox_size(reference_view.bbox)[1] if reference_view else 0.0
            width = ref_height if ref_height > self.config['tolerance'] else fallback_span
            if width <= 0:
                width = max(main_width, fallback_span, 1.0)
            x_min = main_view.bbox[2] + gap
            x_max = x_min + width
            y_min, y_max = main_view.bbox[1], main_view.bbox[3]
        else:
            raise ValueError(f"未知虚拟视图方向: {direction}")

        if direction == 'down':
            x_max = main_view.bbox[2]
        else:
            y_min, y_max = main_view.bbox[1], main_view.bbox[3]

        bbox = (float(x_min), float(y_min), float(x_max), float(y_max))
        area = abs((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
        center = ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
        vertices = [(bbox[0], bbox[1]), (bbox[2], bbox[1]), (bbox[2], bbox[3]), (bbox[0], bbox[3])]
        return ViewInfo(
            name=f"{name}_virtual",
            entity=None,
            bbox=bbox,
            area=area,
            center=center,
            vertices=vertices,
            layer='virtual_view'
        )
    
    def _calculate_line_angle(self, start: Tuple[float, float], 
                            end: Tuple[float, float]) -> float:
        """计算线的角度（0-180度）"""
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        
        if abs(dx) < 1e-2:  # 垂直线
            return 90.0
        
        angle_rad = math.atan2(abs(dy), abs(dx))
        angle_deg = math.degrees(angle_rad)
        
        # 处理水平线
        if abs(dy) < 1e-2:
            return 0.0 if dx > 0 else 180.0
        
        return angle_deg
    
    def generate_material_lines_from_bbox(self):
        """
        通过闭合区域的边界框生成板料线
        """
        main_views = self.views.get('main_view', [])
        side_views = self.views.get('side_view', [])
        front_views = self.views.get('front_view', [])
               
        # 使用相同的板料线图层名称
        material_layer_name = f"{self.config['new_layer_prefix']}MATERIAL"
        if material_layer_name not in self.doc.layers:
            self.doc.layers.new(name=material_layer_name, dxfattribs={
                    'color': self.config['material_layer_color'],
                    'linetype': self.config['material_linetype']
                    })

        main_view = main_views[0]
        mx_min, my_min, mx_max, my_max = main_view.bbox

        # 1. 生成主视图板料线
        p1 = (mx_min, my_min)
        p2 = (mx_max, my_min)
        p3 = (mx_max, my_max)
        p4 = (mx_min, my_max)
        self._draw_box(p1, p2, p3, p4, material_layer_name)
        # 更新main_view的region信息为板料线区域
        self.views['main_view'][0] = ViewInfo(
                name='main_view_material',
                entity=None,
                bbox=(mx_min, my_min, mx_max, my_max),
                area=(mx_max - mx_min) * (my_max - my_min),
                center=((mx_min + mx_max) / 2, (my_min + my_max) / 2),
                vertices=[p1, p2, p3, p4],
                layer='material_layer'
                )

        # 只存在主视图时，直接用T值同时构造侧视图和前视图：
        # 侧视图横向=T，前视图纵向=T
        if (not side_views) and (not front_views):
            virtual_side_view = self._build_virtual_view('side_view', main_view, None, 'right')
            virtual_front_view = self._build_virtual_view('front_view', main_view, None, 'down')
            self.views['side_view'] = [virtual_side_view]
            self.views['front_view'] = [virtual_front_view]
            side_views = self.views['side_view']
            front_views = self.views['front_view']
            print(f"  仅识别到主视图，已按T值虚构侧视图: BBox={virtual_side_view.bbox}")
            print(f"  仅识别到主视图，已按T值虚构前视图: BBox={virtual_front_view.bbox}")

        # 缺失侧视图/前视图时，根据另一个已匹配视图的空白间距构造虚拟区域
        if 'side_view' not in self.views or not self.views.get('side_view'):
            if front_views:
                virtual_side_view = self._build_virtual_view('side_view', main_view, front_views[0], 'right')
                self.views['side_view'] = [virtual_side_view]
                side_views = self.views['side_view']
                print(f"  侧视图未匹配到区域，已根据前视图间距虚构侧视图: BBox={virtual_side_view.bbox}")
        if 'front_view' not in self.views or not self.views.get('front_view'):
            if side_views:
                virtual_front_view = self._build_virtual_view('front_view', main_view, side_views[0], 'down')
                self.views['front_view'] = [virtual_front_view]
                front_views = self.views['front_view']
                print(f"  前视图未匹配到区域，已根据侧视图间距虚构前视图: BBox={virtual_front_view.bbox}")

        # 2. 生成侧视图板料线
        # y范围 = 主视图y范围 (my_min, my_max)
        # x范围 = 侧视图x范围
        if side_views:
            side_view = side_views[0]
            sx_min, sy_min, sx_max, sy_max = side_view.bbox
                
            p1 = (sx_min, my_min)
            p2 = (sx_max, my_min)
            p3 = (sx_max, my_max)
            p4 = (sx_min, my_max)
                
            self._draw_box(p1, p2, p3, p4, material_layer_name)
            # 更新side_view的region信息为板料线区域
            self.views['side_view'][0] = ViewInfo(
                    name='side_view_material',
                    entity=None,
                    bbox=(sx_min, my_min, sx_max, my_max),
                    area=(sx_max - sx_min) * (my_max - my_min),
                    center=((sx_min + sx_max) / 2, (my_min + my_max) / 2),
                    vertices=[p1, p2, p3, p4],
                    layer='material_layer'
                    )

        # 3. 生成正视图板料线
        # x范围 = 主视图x范围 (mx_min, mx_max)
        # y范围 = 正视图y范围
        if front_views:
            front_view = front_views[0]
            fx_min, fy_min, fx_max, fy_max = front_view.bbox

            p1 = (mx_min, fy_min)
            p2 = (mx_max, fy_min)
            p3 = (mx_max, fy_max)
            p4 = (mx_min, fy_max)
                
            self._draw_box(p1, p2, p3, p4, material_layer_name)
            # 更新front_view的region信息为板料线区域
            self.views['front_view'][0] = ViewInfo(
                name='front_view_material',
                entity=None,
                bbox=(mx_min, fy_min, mx_max, fy_max),
                area=(mx_max - mx_min) * (fy_max - fy_min),
                center=((mx_min + mx_max) / 2, (fy_min + fy_max) / 2),
                vertices=[p1, p2, p3, p4],
                layer='material_layer'
                )
        
    def _draw_box(self, p1, p2, p3, p4, layer_name):
        points = [p1, p2, p3, p4, p1] # 闭合
        self.msp.add_lwpolyline(points, dxfattribs={
            'layer': layer_name,
            'color': self.config['material_layer_color'], 
            'linetype': self.config['material_linetype'],
            'closed': True
        })

    def _write_log(self, message: str):
        """写入错误日志"""
        try:
            if self.log_file_dir:
                log_file = os.path.join(self.log_file_dir, os.path.basename(self.doc.filename))
                log_file = os.path.splitext(log_file)[0] + ".log"
                if not os.path.exists(self.log_file_dir):
                    os.makedirs(self.log_file_dir)
            else:
                # 获取当前文件所在目录
                current_dir = os.path.dirname(os.path.abspath(__file__))
                log_dir = os.path.join(current_dir, "logs")

                if not os.path.exists(log_dir):
                    os.makedirs(log_dir)

                log_file = os.path.splitext(os.path.basename(self.doc.filename))[0] + ".log"
                log_file = os.path.join(log_dir, log_file)

            with open(log_file, 'a', encoding='utf-8') as f:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # 假设我们可以获取到文件名，或者就记录消息
                f.write(f"[{timestamp}] {message}\n")
            print(f"  日志写入成功: {log_file}")
        except PermissionError as pe:
            print(f"  日志写入权限错误: {pe}")
        except Exception as e:
            print(f"  日志写入失败: {e}")

    def generate_ordinate_dimension(self, x_range, y_range, quadrant='左下角') :
        """
        生成指定点的坐标标注
        """
        try:
            # 如果不存在则创建图层 U1
            if 'U1' not in self.doc.layers:
                self.doc.layers.add(name='U1', color=7)  # 颜色 7 表示白色/按背景反色

            # 设置标注的图层、颜色与线型（示例图显示在 0 图层、连续线型）
            attribs = {
                'layer': self.config['new_layer_prefix'] + 'ORDINATE_DIMENSION',
                'color': 256,  # 256 表示 ByLayer
                'linetype': 'CONTINUOUS',
            }


            offset = 10.0
            # 依据象限决定引线与文字的偏移方向
            quadrant_offsets = {
                '右上角': ((offset, 0.0), (0.0, offset)),
                '左上角': ((-offset, 0.0), (0.0, offset)),
                '左下角': ((-offset, 0.0), (0.0, -offset)),
                '右下角': ((offset, 0.0), (0.0, -offset)),
                '中间分中': ((-offset, 0.0), (0.0, -offset)),
                '上侧分中': ((-offset, 0.0), (0.0, -offset)),
                '左侧分中': ((-offset, 0.0), (0.0, -offset)),
            }

            target_point = {
                '右上角': (x_range[1], y_range[1]),
                '左上角': (x_range[0], y_range[1]),
                '左下角': (x_range[0], y_range[0]),
                '右下角': (x_range[1], y_range[0]),
                '中间分中': ((x_range[0] + x_range[1]) / 2, (y_range[0] + y_range[1]) / 2),
                '上侧分中': ((x_range[0] + x_range[1]) / 2, y_range[1]),
                '左侧分中': (x_range[0], (y_range[0] + y_range[1]) / 2),
            }

            offset_vector_x, offset_vector_y = quadrant_offsets[quadrant]
            point = target_point[quadrant]

            # 添加 Y 方向坐标标注并显示 Y 坐标值
            dim_y = self.msp.add_ordinate_dim(
                feature_location=point,
                offset=offset_vector_y,
                dtype=1,
                text="0",
                dxfattribs=attribs
            )
            dim_y.render()  # 生成 Y 坐标标注

            # 添加 X 方向坐标标注并显示 X 坐标值
            dim_x = self.msp.add_ordinate_dim(
                feature_location=point,
                offset=offset_vector_x,
                dtype=0,
                text="0",
                dxfattribs=attribs
            )
            dim_x.render()  # 生成 X 坐标标注
            return point
        except Exception as e:
            print(f"Error creating DXF: {e}")
            return None

    def point_in_bbox(self, point, region):
        # 判断三视图区域内是否已有坐标标注点
            x, y = point[0], point[1]
            min_x , min_y, max_x, max_y = region.bbox
            return (min_x - coordinate_point_tolerance <= x <= max_x + coordinate_point_tolerance 
                    and min_y - coordinate_point_tolerance <= y <= max_y + coordinate_point_tolerance)
     
    def collect_circles(self, container,x_range=None, y_range=None) -> None:
        # 在指定图元容器中收集半径小于阈值的圆与其圆心
        small_circles: list[tuple[ezdxf.entities.Circle, tuple[float, float, float]]] = []
        for entity in container.query("CIRCLE"):
            radius = entity.dxf.radius
            if radius is None or radius >= self.config['radius_threshold']:
                continue
            center = entity.dxf.center
            if x_range is not None and not (x_range[0] <= center.x <= x_range[1]):
                continue
            if y_range is not None and not (y_range[0] <= center.y <= y_range[1]):
                continue
            small_circles.append((entity, (center[0], center[1], center[2])))
    def squared_distance(self, a: tuple[float, float, float], b: tuple[float, float, float]) :
        dx = a[0] - b[0]
        dy = a[1] - b[1]
        dz = a[2] - b[2]
        return dx * dx + dy * dy + dz * dz
    def classify_quadrant(self, dx: float, dy: float) -> str:
        if dx > 0 and dy > 0:
            return "第一象限"
        if dx < 0 and dy > 0:
            return "第二象限"
        if dx < 0 and dy < 0:
            return "第三象限"
        elif dx > 0 and dy < 0:
            return "第四象限"
    
    def find_minimal_iso_triangle(self, region):

        bbox = region.bbox  # (min_x, min_y, max_x, max_y)
        x_range = (bbox[0], bbox[2])
        y_range = (bbox[1], bbox[3])

        # 在指定图元容器中收集半径小于阈值的圆与其圆心
        small_circles: list[tuple[ezdxf.entities.Circle, tuple[float, float, float]]] = []
        
        self.collect_circles(self.doc.modelspace(), x_range, y_range)
        for layout in self.doc.layouts:
            if layout.name == "Model":
                continue
            self.collect_circles(layout, x_range, y_range)
        for block in self.doc.blocks:
            self.collect_circles(block, x_range, y_range)

        minimal_area: float | None = None
        best_combinations: list[tuple[ezdxf.entities.Circle, ezdxf.entities.Circle, ezdxf.entities.Circle]] = []
        # 检查任意三个小圆圆心是否能组成等腰直角三角形并计算面积
        for triplet in itertools.combinations(small_circles, 3):
            (circle_a, center_a), (circle_b, center_b), (circle_c, center_c) = triplet
            d_ab = self.squared_distance(center_a, center_b)
            d_ac = self.squared_distance(center_a, center_c)
            d_bc = self.squared_distance(center_b, center_c)
            distances = sorted((d_ab, d_ac, d_bc))
            if distances[0] <= self.config['tolerance'] or distances[1] <= self.config['tolerance']:
                continue  # 忽略重合圆心
            if (
                abs(distances[0] - distances[1]) <= self.config['tolerance']
                and abs(distances[2] - (distances[0] + distances[1])) <= self.config['tolerance']
            ):
                area = 0.5 * distances[0]
                if minimal_area is None or area + self.config['tolerance'] < minimal_area:
                    minimal_area = area
                    best_combinations = [(circle_a, circle_b, circle_c)]
                elif minimal_area is not None and abs(area - minimal_area) <= self.config['tolerance']:
                    best_combinations.append((circle_a, circle_b, circle_c))
        multiple_minima = False
        orientations: set[str] = set()
        if minimal_area is not None:
            seen_keys: set[str] = set()
            for combo in best_combinations:
                circle_a, circle_b, circle_c = combo
                centers = [circle_a.dxf.center, circle_b.dxf.center, circle_c.dxf.center]
                dists = {
                    ("ab", self.squared_distance(centers[0], centers[1])),
                    ("ac", self.squared_distance(centers[0], centers[2])),
                    ("bc", self.squared_distance(centers[1], centers[2])),
                }
                pairs = list(dists)
                pairs.sort(key=lambda item: item[1])
                short_edges = pairs[:2]
                long_edge = pairs[2]
                if abs(short_edges[0][1] - short_edges[1][1]) <= self.config['tolerance'] and abs(
                    long_edge[1] - (short_edges[0][1] + short_edges[1][1])
                ) <= self.config['tolerance']:
                    if long_edge[0] == "ab":
                        right = centers[2]
                        h1, h2 = centers[0], centers[1]
                    elif long_edge[0] == "ac":
                        right = centers[1]
                        h1, h2 = centers[0], centers[2]
                    else:
                        right = centers[0]
                        h1, h2 = centers[1], centers[2]
                    midpoint = ((h1[0] + h2[0]) * 0.5, (h1[1] + h2[1]) * 0.5)
                    vector = (right[0] - midpoint[0], right[1] - midpoint[1])
                    orientations.add(self.classify_quadrant(vector[0], vector[1]))
                for circle in combo:
                    handle = circle.dxf.handle or str(id(circle))
                    if handle in seen_keys:
                        continue
                    seen_keys.add(handle)
            selected_total = len(seen_keys)
            multiple_minima = len(best_combinations) > 1
            return (
                len(small_circles),
                minimal_area,
                multiple_minima,
                tuple(sorted(orientations))
                )
        # 如果没有找到任何等腰直角三角形组合，返回默认值，防止 NoneType 解包错误
        return (len(small_circles), None, False, ())

    def determine_point_position_in_view(self, point, view_bbox):
        """
        判断点在视图的哪个象限（左上角、左下角、右上角、右下角）。
        """
        x, y = point[0], point[1]
        x_min, y_min, x_max, y_max = view_bbox

        if abs(x - x_min) < coordinate_point_tolerance:  # 左侧
            if abs(y - y_max) < coordinate_point_tolerance:  # 上方
                return "左上角"
            elif abs(y - y_min) < coordinate_point_tolerance:  # 下方
                return "左下角"
            elif abs(y - (y_min + y_max) / 2) < coordinate_point_tolerance:
                return "左侧分中"
            else:  # 错误
                return "(0,0)点位置有误"
        elif abs(x - x_max) < coordinate_point_tolerance:  # 右侧
            if abs(y - y_max) < coordinate_point_tolerance:  # 上方
                return "右上角"
            elif abs(y - y_min) < coordinate_point_tolerance:  # 下方
                return "右下角"
            else:  # 错误
                return "(0,0)点位置有误"
        elif abs(x - (x_min + x_max) / 2) < coordinate_point_tolerance:
            if abs(y - (y_min + y_max) / 2) < coordinate_point_tolerance:
                return "中间分中"
            elif abs(y - y_max) < coordinate_point_tolerance:
                return "上侧分中"
            else:
                return "(0,0)点位置有误"
        else:   
            return "(0,0)点位置有误"
            
    def ordinate_dimension_0_0(self, ordinate_points=None):
        """
        生成视图的（0,0）标注
        说明：该方法会在DXF文件中查找最小等腰直角三角形组合，并在其顶点方向标注原点位置(0,0)
        """
        # 创建成员变量0，0坐标字典
        self.ordinate_0_0 = {}
        main_view = self.views['main_view'][0]

        # 判断视图中是否已存在0，0标注，若没有0，0标注，判断是否有最小等腰直角三角形组合
        if ordinate_points != None:
            for point in ordinate_points:
                if self.point_in_bbox(point, main_view):
                    if 'main_view' in self.ordinate_0_0:
                        # 通过日志报错：该视图存在多个0，0坐标点
                        msg = f"main_view 存在多个 (0, 0) 坐标点，跳过处理"
                        return False, msg
                    else:
                        # 判断点在视图的哪个象限（左上角、左下角、右上角、右下角、中间分中、上侧分中、左侧分中）。
                        point_position = self.determine_point_position_in_view(point, main_view.bbox)
                        if point_position == '(0,0)点位置有误':
                            msg = f"main_view 中的 (0, 0) 坐标点位置有误，跳过处理"
                            return False, msg
                        self.ordinate_0_0['main_view'] = [point_position]

        # 若不存在0，0坐标，则查找最小等腰直角三角形组合
        if 'main_view' not in self.ordinate_0_0:
            area_num, minimal_area, multiple_minima, orientations = self.find_minimal_iso_triangle(main_view)
            # if minimal_area is not None and multiple_minima:
            #     msp = self.doc.modelspace()
            #     origin_exists = False
            #     for point in msp.query("POINT"):
            #         location = point.dxf.location
            #         if (
            #             abs(location.x) <= self.config['tolerance']
            #             and abs(location.y) <= self.config['tolerance']
            #             and abs(location.z) <= self.config['tolerance']
            #         ):
            #             origin_exists = True
            #             break
            # if not origin_exists:
            #     # 若存在面积相同的多组，使用左下角点标记作为提示
            #     msp.add_point((bbox[0], bbox[1], 0.0), dxfattribs={"layer": '0'}) 
            if minimal_area is None:
                print(f">>视图main_view：共找到 {area_num:.0f} 个半径小圈，但未检测到等腰直角三角形组合。")
            else:
                orientation_msg = "、".join(orientations) if orientations else "方向无法判定"
                print(
                f">>视图main_view：共找到 {area_num:.0f} 个半径小圈，最小等腰直角三角形面积为 {minimal_area:.6f}，指向象限：{orientation_msg}"
            )
        
            if multiple_minima:
                msg = f"视图 main_view ：存在多个最小等腰直角三角形组合，跳过处理"
                return False, msg
            elif orientations != ():
                orientation = ''
                if orientations[0] == "第一象限":
                    orientation = "右上角"
                elif orientations[0] == "第二象限":
                    orientation = "左上角"
                elif orientations[0] == "第三象限":
                    orientation = "左下角"
                elif orientations[0] == "第四象限":
                    orientation = "右下角"
                self.ordinate_0_0['main_view'] = [orientation, None]


        # 正确的0，0坐标点所在的方向对应为：
        # 主视图坐标方向：[侧视图坐标方向，正视图坐标方向]
        correct_orientations = {
            '右上角': ['左上角', '右上角'],
            '左上角': ['左上角', '左上角'],
            '左下角': ['左下角', '左上角'], 
            '右下角': ['左下角', '右上角'],
            '中间分中': ['左侧分中', '上侧分中']
        }

        # 对视图中已有的方向进行判断
        if self.need_centering:
                self.ordinate_0_0['main_view'] = ['中间分中']
        if 'main_view' not in self.ordinate_0_0:
            self.ordinate_0_0['main_view'] = ['左下角']
        if 'main_view' in self.ordinate_0_0:
            main_view_orientation = self.ordinate_0_0.get('main_view', [None])[0]
            print(f"主视图0，0坐标方向：{main_view_orientation}")
        
            # 最终生成0，0坐标标注
            for key, view in self.views.items():
                if key in self.views:
                    if key not in self.ordinate_0_0:
                        if key == 'side_view':
                            self.ordinate_0_0[key] = [correct_orientations[main_view_orientation][0]]
                        elif key == 'front_view':
                            self.ordinate_0_0[key] = [correct_orientations[main_view_orientation][1]]
                    self.ordinate_0_0[key].append(self.generate_ordinate_dimension(
                        (view[0].bbox[0], view[0].bbox[2]),
                        (view[0].bbox[1], view[0].bbox[3]),
                        self.ordinate_0_0[key][0]
                    ))
        
        return True, ''

    # ===================================================================
    # =================生成板料线和（0，0）标注的主程序=====================
    def run(self, output_path: str = "output_with_material.dxf", fail_file_path: str = "fail_file.dxf", json_0_0_dir = '') -> bool:
        """
        运行完整流程

        :param output_path: 输出DXF文件路径
        :param fail_file_path: 失败文件保存路径
        :param json_0_0_dir: 0，0坐标json文件保存路径
        """
        file_name = os.path.basename(self.doc.filename) if self.doc.filename else "Unknown_File"
        try:
            print("\n>>步骤1：查找所有闭合区域，通过多段线直接识别、图论和贪心算法")
            regions = self.find_view_contours_with_filtering()
            print(f"  步骤1共识别到 {len(regions)} 个闭合区域")
            
            if len(regions) < 1:
                print(f"错误：未找到任何有效闭合区域")
                self._write_log(f"{file_name}未找到任何有效闭合区域")
                # 未处理的图纸保存至fail_file文件夹
                self.doc.saveas(fail_file_path)
                return False           

            print("\n>>步骤2：对步骤1识别出的所有闭合区域进行判别，识别主视图、侧视图和正视图")
            self.identify_views_with_alignment(regions)
            if not self.views or 'main_view' not in self.views:
                print(f"错误：未能识别主视图，请检查主视图是否符合规范要求")
                self._write_log(f"{file_name} 未能识别主视图，请检查主视图是否符合规范要求")
                # 未处理的图纸保存至fail_file文件夹
                self.doc.saveas(fail_file_path)
                return False
            for key, view in self.views.items():
                if len(view) > 1 and abs(view[0].area - view[1].area) < self.config['overlap_area_tolerance']:
                    msg = f"{file_name}识别到多个 {key}，判定为多零件图，跳过处理"
                    print(msg)
                    self._write_log(msg)
                    self.doc.saveas(fail_file_path)
                    return False
                else:
                    tolerance = self.config['material_line_tolerance']  # 最小尺寸容差
                    # 进行精确匹配
                    region = view[0]
                    bbox = region.bbox  # (min_x, min_y, max_x, max_y)
                    region_width = bbox[2] - bbox[0]
                    region_height = bbox[3] - bbox[1]
                    l, w, t = [self.lwt_info['L'], self.lwt_info['W'], self.lwt_info['T']]
 
                    msg = '' 
                    if key == 'main_view':
                        if abs(region_width - l) > tolerance or abs(region_height - w) > tolerance:
                            msg = f"{file_name}[视图 {key}]：{region_width} 、{region_height}尺寸与L/W不匹配，L/W：{l}/{w}，跳过处理"
                    elif key == 'side_view':
                        if abs(region_width - t) > tolerance:
                            msg = f"{file_name}[视图 {key}]：{region_width}尺寸与T不匹配，T：{t}，跳过处理"    
                    else:  # front_view
                        if abs(region_height - self.lwt_info['T']) > tolerance:
                            msg = f"{file_name}[视图 {key}]：{region_height}尺寸与T不匹配，T：{t}，跳过处理"
                    if msg != '':
                        print(msg)
                        self._write_log(msg)
                        self.doc.saveas(fail_file_path)
                        return False
            

            print("\n>>步骤3：基于识别出的视图闭合区域边界生成板料线")
            self.generate_material_lines_from_bbox()     

            print("\n>>步骤4：寻找视图中已存在的0，0标注，并为不存在标注的视图创建0，0标注")
            ordinate_points = find_ordinate_points(self.doc)
            is_ordinate_success, msg = self.ordinate_dimension_0_0(ordinate_points)
            if is_ordinate_success is False:
                print(f"{file_name}:{msg}")
                self._write_log(f"{file_name}:{msg}")
                self.doc.saveas(fail_file_path)
                return False
            
            print("\n>>步骤5：把三个视图的0，0坐标输出到json文件里")
            if json_0_0_dir and not os.path.exists(json_0_0_dir):
                os.makedirs(json_0_0_dir)
            json_0_0_file_name = os.path.join(json_0_0_dir, os.path.splitext(file_name)[0] + ".json")
            self.ordinate_0_0['main_view_bottom_left'] = (self.views['main_view'][0].bbox[0], self.views['main_view'][0].bbox[1])
            self.ordinate_0_0['main_view_top_right'] = (self.views['main_view'][0].bbox[2], self.views['main_view'][0].bbox[3])
            with open(json_0_0_file_name, 'w', encoding='utf-8') as json_file:
                json.dump(self.ordinate_0_0, json_file, ensure_ascii=False, indent=4)

                   
            # 步骤6：保存结果
            self.doc.saveas(output_path)   
            return True    
        except Exception as e:
            print(f"\n处理过程中出错: {e}")
            import traceback
            traceback.print_exc()
            return False
    

# ===================================================================
# ============================主程序=================================
# =======================处理单个dxf文件==============================
# ===================================================================
def process_single_dxf(dxf_file_path: str, output_dir: str, log_file_dir: str = None, csv_path: str = None, json_0_0_dir = '') -> bool:
    """
    封装的处理函数
    :param dxf_file_path: 输入DXF文件路径
    :param output_dir: 输出DXF文件夹路径
    :param log_file_dir: 日志文件夹路径
    :param csv_path: CSV文件路径（包含L/W/T信息）
    :param json_0_0_dir: 生成的0,0坐标JSON文件夹路径（传递给钻孔）
    :return: 是否成功（True/False）
    """

    print(f"开始处理文件: {dxf_file_path}")

    # 检查输出目录是否存在，不存在则创建
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    # 在输出目录下新建失败文件夹：fail_file
    fail_dir = os.path.join(output_dir, "fail_file")
    if not os.path.exists(fail_dir):
        os.makedirs(fail_dir)
    # 构建输出文件路径
    file_name = os.path.basename(dxf_file_path)
    output_file_path = os.path.join(output_dir, file_name)
    fail_file_path = os.path.join(fail_dir, file_name)
    projector = MaterialLineProjector(dxf_file_path, lwt_info=None, log_file_dir=log_file_dir)

    # 1.从csv中读取当前文件的信息
    csv_info = read_lwt_from_csv(csv_path, file_name)
    if 'error_info' in csv_info:
        projector._write_log(f"{file_name}：{csv_info['error_info']}")
        projector.doc.saveas(fail_file_path)
        return False
    
    l_val, w_val, t_val = csv_info['L'], csv_info['W'], csv_info['T']
    print(f"从csv文件中读取到L/W/T信息：{l_val}/{w_val}/{t_val}")
    projector.lwt_info = {'L': l_val, 'W': w_val, 'T': t_val}
    projector.need_centering = csv_info.get('need_centering', False)

    # 2. 运行投影
    success = projector.run(output_file_path, fail_file_path, json_0_0_dir)
    return success


# ===================================================================
# ===========================使用示例=================================
if __name__ == "__main__":

    # 输入文件夹
    input_dir = r"C:\Users\admin\Desktop\测试_input\M250239-P3.2026.4.1"
    dxf_file = os.path.join(input_dir, "PU-04-M250239-P3.dxf")
    csv_path = os.path.join(input_dir, "dxf图纸信息汇总表.csv")
    # 输出文件夹
    output_dir = r"C:\Users\admin\Desktop\测试_output"
    

    # 定义日志路径
    log_file = os.path.join(output_dir, "logs")
    # 定义0，0坐标json文件保存路径为输出文件夹下的json_0_0文件夹
    json_0_0_dir = os.path.join(output_dir, "json_0_0")
    
    if process_single_dxf(dxf_file, output_dir, log_file, csv_path, json_0_0_dir):
        print("处理成功！")
    else:
        print("处理失败")


    