"""
水磨计算辅助函数
负责人：李志鹏

提供水磨相关的公共判断逻辑：
1. 判断是大水磨还是小磨床
2. 判断大水磨零件类型（板/长条/零件）
"""


def determine_mill_type(has_auto_material: bool, has_material_preparation: str) -> str:
    """
    判断是大水磨还是小磨床
    
    小磨床：has_auto_material 为 True 或 has_material_preparation 不为 None（任意一个满足）
    大水磨：不满足小磨床条件
    
    Args:
        has_auto_material: 是否自动备料
        has_material_preparation: 材料准备方式
    
    Returns:
        str: "s_water_mill" | "l_water_mill"
    """
    # 如果自己备料（has_auto_material=True）或者备料于其他零件（has_material_preparation不为None），则为小磨床
    if has_auto_material or has_material_preparation:
        return "s_water_mill"
    else:
        # 否则为大水磨
        return "l_water_mill"


def determine_part_type(length_mm: float, width_mm: float, thickness_mm: float) -> str:
    """
    判断大水磨零件类型
    
    规则：
    1. 将尺寸排序，去掉最大值和最小值，中间值如果 > 250 则为板（plate）
    2. 如果最长的是第二长的值的2倍则为长条（long_strip）
    3. 其他为零件（component）
    
    Args:
        length_mm: 长度（mm）
        width_mm: 宽度（mm）
        thickness_mm: 厚度（mm）
    
    Returns:
        str: "plate" | "long_strip" | "component"
    """
    dimensions = sorted([length_mm, width_mm, thickness_mm])
    min_dim = dimensions[0]
    mid_dim = dimensions[1]
    max_dim = dimensions[2]
    
    # 判断是否为板
    if mid_dim > 250:
        return "plate"
    
    # 判断是否为长条
    if max_dim >= mid_dim * 2:
        return "long_strip"
    
    # 其他为零件
    return "component"
