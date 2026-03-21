# -*- coding: utf-8 -*-
"""
线长计算模块
计算 DXF 文件中线割工艺实线的总长度（支持001/220/190色号）
"""
import logging
import math
from typing import Optional

logging.basicConfig(level=logging.INFO)

# 线割工艺颜色列表（001=红色, 220=黄色, 190=橙色）
WIRE_CUT_COLORS = [1, 220, 190]


def calculate_red_line_length(doc) -> float:
    """
    计算线割工艺实线的总长度
    
    Args:
        doc: ezdxf Document 对象
    
    Returns:
        float: 线割实线总长度（单位：mm）
    
    筛选条件:
        - 颜色: entity.dxf.color in [1, 220, 190] (红色/黄色/橙色 - 线割工艺)
        - 线型: Continuous 或 ByLayer (排除虚线、点划线等)
    
    支持的实体类型:
        - LINE: 直线
        - CIRCLE: 圆
        - ARC: 圆弧
        - LWPOLYLINE: 轻量多段线
        - POLYLINE: 多段线
    """
    try:
        msp = doc.modelspace()
        total_length = 0.0
        red_entity_count = 0
        
        for entity in msp:
            try:
                # 检查颜色（1=红色, 220=黄色, 190=橙色 - 线割工艺）
                entity_color = getattr(entity.dxf, 'color', 256)
                if entity_color not in WIRE_CUT_COLORS:
                    continue
                
                # 检查线型（排除虚线等）
                linetype = getattr(entity.dxf, 'linetype', 'ByLayer')
                if linetype.lower() not in ['continuous', 'bylayer']:
                    continue
                
                # 根据实体类型计算长度
                entity_type = entity.dxftype()
                
                logging.debug(f"\n{'='*60}")
                logging.debug(f"[线割实线 色号:{entity_color}] 处理实体 #{red_entity_count + 1}: {entity_type}")
                
                if entity_type == 'LINE':
                    length = _calculate_line_length(entity)
                    
                elif entity_type == 'CIRCLE':
                    length = _calculate_circle_length(entity)
                    
                elif entity_type == 'ARC':
                    length = _calculate_arc_length(entity)
                    
                elif entity_type in ['LWPOLYLINE', 'POLYLINE']:
                    length = _calculate_polyline_length(entity)
                    
                else:
                    continue
                
                if length > 0:
                    total_length += length
                    red_entity_count += 1
                    logging.debug(f"[线割实线 色号:{entity_color}] 实体长度: {length:.4f}mm, 累计: {total_length:.4f}mm")
                else:
                    logging.debug(f"[线割实线 色号:{entity_color}] 实体长度为 0，跳过")
                    
            except Exception as e:
                logging.debug(f"处理实体时出错: {e}")
                continue
        
        logging.info(f"线割实线计算完成 - 实体数: {red_entity_count}, 总长度: {total_length:.2f}mm")
        # 确保返回 Python 原生 float 类型
        return float(total_length)
        
    except Exception as e:
        logging.error(f"计算线割实线长度失败: {str(e)}")
        return 0.0


def _calculate_line_length(entity) -> float:
    """
    计算直线长度
    
    公式: √[(x2-x1)² + (y2-y1)² + (z2-z1)²]
    """
    try:
        start = entity.dxf.start
        end = entity.dxf.end
        length = math.sqrt(
            (end.x - start.x)**2 + 
            (end.y - start.y)**2 + 
            (end.z - start.z)**2
        )
        return length
    except Exception:
        return 0.0


def _calculate_circle_length(entity) -> float:
    """
    计算圆周长
    
    公式: 2πr
    """
    try:
        radius = entity.dxf.radius
        length = 2 * math.pi * radius
        return length
    except Exception:
        return 0.0


def _calculate_arc_length(entity) -> float:
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


def _calculate_polyline_length(entity) -> float:
    """
    计算多段线长度
    
    策略：
    1. 优先使用 virtual_entities() 炸开法（最准确，自动处理闭合和bulge）
    2. 如果炸开失败，使用手动计算法（兼容性备用）
    
    优点：
    - 自动处理闭合判断（不需要检查 closed 标志）
    - 自动处理 bulge 弧线（不需要手动计算弧长）
    - 结果与 CAD 软件完全一致
    """
    try:
        # 方法1：炸开法（推荐）
        return _calculate_polyline_by_explode(entity)
    except Exception as e:
        logging.debug(f"[多段线长度] 炸开法失败，使用手动计算: {e}")
        # 方法2：手动计算法（备用）
        return _calculate_polyline_by_vertices(entity)


def _calculate_polyline_by_explode(entity) -> float:
    """
    使用 virtual_entities() 炸开多段线并计算长度
    
    工作原理：
    1. 将多段线分解为基本实体（LINE 和 ARC）
    2. 计算每个基本实体的长度
    3. 累加得到总长度
    
    优点：
    - ezdxf 自动处理所有复杂逻辑（闭合、bulge等）
    - 结果与 CAD 软件一致
    """
    entity_type = entity.dxftype()
    logging.debug(f"[多段线长度-炸开法] 实体类型: {entity_type}")
    
    # 炸开多段线
    exploded_entities = list(entity.virtual_entities())
    
    if not exploded_entities:
        logging.debug(f"[多段线长度-炸开法] 炸开后无实体")
        return 0.0
    
    logging.debug(f"[多段线长度-炸开法] 炸开后实体数: {len(exploded_entities)}")
    
    total_length = 0.0
    
    # 遍历炸开后的每个实体
    for i, sub_entity in enumerate(exploded_entities):
        sub_type = sub_entity.dxftype()
        
        if sub_type == 'LINE':
            # 计算直线长度
            length = _calculate_line_from_exploded(sub_entity)
            logging.debug(f"  边 {i+1}: LINE, 长度={length:.4f}mm")
            
        elif sub_type == 'ARC':
            # 计算弧线长度
            length = _calculate_arc_from_exploded(sub_entity)
            radius = sub_entity.dxf.radius
            logging.debug(f"  边 {i+1}: ARC, 长度={length:.4f}mm, 半径={radius:.2f}mm")
            
        else:
            # 其他类型（理论上不应该出现）
            logging.warning(f"  边 {i+1}: 未知类型 {sub_type}")
            length = 0.0
        
        total_length += length
    
    logging.debug(f"[多段线长度-炸开法] 总长度: {total_length:.4f}mm")
    return total_length


def _calculate_line_from_exploded(line_entity) -> float:
    """
    计算炸开后的直线长度
    
    Args:
        line_entity: LINE 实体
    
    Returns:
        float: 直线长度
    """
    try:
        start = line_entity.dxf.start
        end = line_entity.dxf.end
        
        # 使用 ezdxf 内置的距离计算方法
        length = start.distance(end)
        
        return length
    except Exception as e:
        logging.debug(f"计算直线长度失败: {e}")
        return 0.0


def _calculate_arc_from_exploded(arc_entity) -> float:
    """
    计算炸开后的弧线长度
    
    Args:
        arc_entity: ARC 实体
    
    Returns:
        float: 弧线长度
    
    公式：弧长 = 半径 × 角度（弧度）
    """
    try:
        radius = arc_entity.dxf.radius
        start_angle = arc_entity.dxf.start_angle  # 度数
        end_angle = arc_entity.dxf.end_angle      # 度数
        
        # 计算角度差（度数）
        angle_diff = end_angle - start_angle
        
        # 处理跨越 0° 的情况（如从 350° 到 10°）
        if angle_diff < 0:
            angle_diff += 360
        
        # 转换为弧度并计算弧长
        angle_rad = math.radians(angle_diff)
        arc_length = radius * angle_rad
        
        return arc_length
    except Exception as e:
        logging.debug(f"计算弧线长度失败: {e}")
        return 0.0


def _calculate_polyline_by_vertices(entity) -> float:
    """
    手动计算多段线长度（备用方法）
    
    当 virtual_entities() 不可用时使用此方法
    
    注意：此方法可能无法正确处理某些闭合情况
    """
    try:
        entity_type = entity.dxftype()
        logging.debug(f"[多段线长度-手动法] 实体类型: {entity_type}")
        
        if entity_type == 'LWPOLYLINE':
            return _calculate_lwpolyline_manual(entity)
        else:
            return _calculate_polyline_manual(entity)
            
    except Exception as e:
        logging.debug(f"手动计算多段线长度失败: {e}")
        return 0.0


def _calculate_lwpolyline_manual(entity) -> float:
    """手动计算 LWPOLYLINE 长度（带 bulge 支持）"""
    points_with_bulge = list(entity.get_points('xyseb'))
    
    if len(points_with_bulge) < 2:
        return 0.0
    
    logging.debug(f"[手动法-LWPOLYLINE] 顶点数: {len(points_with_bulge)}")
    
    total_length = 0.0
    
    # 计算相邻顶点之间的边
    for i in range(len(points_with_bulge) - 1):
        p1 = points_with_bulge[i]
        p2 = points_with_bulge[i + 1]
        
        x1, y1 = p1[0], p1[1]
        x2, y2 = p2[0], p2[1]
        bulge = p1[4] if len(p1) > 4 else 0.0
        
        if abs(bulge) < 1e-6:
            # 直线段
            seg_len = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
        else:
            # 弧线段
            angle = 4 * math.atan(abs(bulge))
            chord_length = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
            
            if chord_length < 1e-6:
                seg_len = 0.0
            else:
                radius = chord_length / (2 * math.sin(angle / 2))
                seg_len = radius * angle
        
        total_length += seg_len
    
    # 检查是否需要添加闭合边
    is_closed = getattr(entity.dxf, 'closed', False)
    last_bulge = points_with_bulge[-1][4] if len(points_with_bulge[-1]) > 4 else 0.0
    
    if is_closed or abs(last_bulge) > 1e-6:
        # 添加闭合边
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
        logging.debug(f"[手动法-LWPOLYLINE] 添加闭合边: {seg_len:.4f}mm")
    
    logging.debug(f"[手动法-LWPOLYLINE] 总长度: {total_length:.4f}mm")
    return total_length


def _calculate_polyline_manual(entity) -> float:
    """手动计算普通 POLYLINE 长度"""
    points = list(entity.get_points('xyz'))
    
    if len(points) < 2:
        return 0.0
    
    logging.debug(f"[手动法-POLYLINE] 顶点数: {len(points)}")
    
    total_length = 0.0
    
    # 计算相邻顶点之间的边
    for i in range(len(points) - 1):
        p1, p2 = points[i], points[i + 1]
        
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
    
    # 检查是否需要添加闭合边
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
        logging.debug(f"[手动法-POLYLINE] 添加闭合边: {segment_length:.4f}mm")
    
    logging.debug(f"[手动法-POLYLINE] 总长度: {total_length:.4f}mm")
    return total_length


def calculate_wire_length_by_color(doc, color_code: int = 1) -> float:
    """
    计算指定颜色实线的总长度（通用接口）
    
    Args:
        doc: ezdxf Document 对象
        color_code: 颜色代码（默认 1 = 红色）
    
    Returns:
        float: 指定颜色实线总长度（单位：mm）
    
    颜色代码参考:
        1 = 红色
        2 = 黄色
        3 = 绿色
        4 = 青色
        5 = 蓝色
        6 = 洋红色
        7 = 白色/黑色
    """
    try:
        msp = doc.modelspace()
        total_length = 0.0
        entity_count = 0
        
        for entity in msp:
            try:
                # 检查颜色
                entity_color = getattr(entity.dxf, 'color', 256)
                if entity_color != color_code:
                    continue
                
                # 检查线型
                linetype = getattr(entity.dxf, 'linetype', 'ByLayer')
                if linetype.lower() not in ['continuous', 'bylayer']:
                    continue
                
                # 根据实体类型计算长度
                entity_type = entity.dxftype()
                
                if entity_type == 'LINE':
                    length = _calculate_line_length(entity)
                elif entity_type == 'CIRCLE':
                    length = _calculate_circle_length(entity)
                elif entity_type == 'ARC':
                    length = _calculate_arc_length(entity)
                elif entity_type in ['LWPOLYLINE', 'POLYLINE']:
                    length = _calculate_polyline_length(entity)
                else:
                    continue
                
                if length > 0:
                    total_length += length
                    entity_count += 1
                    
            except Exception:
                continue
        
        logging.info(f"颜色 {color_code} 实线计算完成 - 实体数: {entity_count}, 总长度: {total_length:.2f}mm")
        return float(total_length)
        
    except Exception as e:
        logging.error(f"计算颜色 {color_code} 实线长度失败: {str(e)}")
        return 0.0


if __name__ == "__main__":
    """测试代码"""
    import ezdxf
    
    # 测试示例
    print("线长计算模块测试")
    print("=" * 50)
    
    # 这里可以添加测试代码
    # doc = ezdxf.readfile("test.dxf")
    # red_length = calculate_red_line_length(doc)
    # print(f"红色实线总长度: {red_length:.2f} mm")
    
    # 计算其他颜色
    # yellow_length = calculate_wire_length_by_color(doc, color_code=2)
    # print(f"黄色实线总长度: {yellow_length:.2f} mm")
