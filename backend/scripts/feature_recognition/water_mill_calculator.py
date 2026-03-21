# -*- coding: utf-8 -*-
"""
水磨数据计算模块
根据备料件或自找料的条件，计算水磨相关数据
"""
import logging
from typing import Optional, Dict, Any, List


def should_calculate_water_mill(has_material_preparation: Optional[str], has_auto_material: bool) -> bool:
    """
    判断是否需要计算水磨数据
    
    Args:
        has_material_preparation: 备料信息（如果有值表示是备料件）
        has_auto_material: 是否是自找料
    
    Returns:
        bool: True表示需要计算水磨数据，False表示不需要
    """
    # 只要是备料件或自找料，就需要计算水磨数据
    is_material_prep = has_material_preparation is not None and has_material_preparation.strip() != ''
    
    if is_material_prep or has_auto_material:
        logging.info(f"✅ 需要计算水磨数据: 备料件={is_material_prep}, 自找料={has_auto_material}")
        return True
    else:
        logging.info("ℹ️ 不需要计算水磨数据: 既不是备料件也不是自找料")
        return False


def calculate_water_mill_data(hanging_table: int = 0,
                             c1_c2_chamfer: int = 0,
                             c3_c5_chamfer: int = 0,
                             r1_r2_chamfer: int = 0,
                             r3_r5_chamfer: int = 0,
                             oil_tank: int = 0,
                             thread_ends: int = 0,
                             bevel: List[float] = None,
                             grinding: int = 2) -> Dict[str, Any]:
    """
    计算水磨数据（所有零件都生成）
    
    Args:
        hanging_table: 挂台个数（0, 1, 2...）
        c1_c2_chamfer: C1-C2倒角个数
        c3_c5_chamfer: C3-C5倒角个数
        r1_r2_chamfer: R1-R2倒角个数
        r3_r5_chamfer: R3-R5倒角个数
        oil_tank: 油槽标识（0=无油槽，1=有油槽）
        thread_ends: 线头件数（0=普通零件，1=备料件/自找料）
        bevel: 斜面长度列表(mm)，例如 [20.5, 15.3]，默认为空列表
        grinding: 研磨面数（通过识别块数量确定），默认2
    
    Returns:
        Dict: 水磨数据，包含以下字段（每个字段作为独立的字典对象）：
            - thread_ends: 线头件数（0或1）
            - hanging_table: 挂台个数（0, 1, 2...）
            - c1_c2_chamfer: C1-C2倒角个数
            - c3_c5_chamfer: C3-C5倒角个数
            - r1_r2_chamfer: R1-R2倒角个数
            - r3_r5_chamfer: R3-R5倒角个数
            - bevel: 斜面长度列表
            - oil_tank: 油槽标识（0或1）
            - grinding: 研磨面数
    """
    if bevel is None:
        bevel = []
    
    # 每个字段作为独立的字典对象
    water_mill_details = [
        {"thread_ends": thread_ends},            # 线头件数（0或1）
        {"hanging_table": hanging_table},        # 挂台个数（0, 1, 2...）
        {"c1_c2_chamfer": c1_c2_chamfer},        # C1-C2倒角个数
        {"c3_c5_chamfer": c3_c5_chamfer},        # C3-C5倒角个数
        {"r1_r2_chamfer": r1_r2_chamfer},        # R1-R2倒角个数
        {"r3_r5_chamfer": r3_r5_chamfer},        # R3-R5倒角个数
        {"bevel": bevel},                        # 斜面长度列表
        {"oil_tank": oil_tank},                  # 油槽标识（0或1）
        {"grinding": grinding}                   # 研磨面数
    ]
    
    # 计算倒角总数
    total_chamfers = c1_c2_chamfer + c3_c5_chamfer + r1_r2_chamfer + r3_r5_chamfer
    
    logging.info("✅ 水磨数据计算完成")
    logging.info(f"   线头件数={thread_ends}, "
                f"挂台={hanging_table}个, "
                f"倒角总数={total_chamfers}个, "
                f"油槽={'有' if oil_tank == 1 else '无'}")
    logging.info(f"   倒角详情: C1-C2={c1_c2_chamfer}个, "
                f"C3-C5={c3_c5_chamfer}个, "
                f"R1-R2={r1_r2_chamfer}个, "
                f"R3-R5={r3_r5_chamfer}个")
    
    # 格式化斜面信息
    if bevel:
        bevel_info = f"{len(bevel)}个斜面，长度={bevel}mm"
    else:
        bevel_info = "无斜面"
    
    logging.info(f"   其他: {bevel_info}, "
                f"研磨={grinding}面")
    
    return {"water_mill_details": water_mill_details}


def get_water_mill_data(hanging_table: int = 0,
                       c1_c2_chamfer: int = 0,
                       c3_c5_chamfer: int = 0,
                       r1_r2_chamfer: int = 0,
                       r3_r5_chamfer: int = 0,
                       oil_tank: int = 0,
                       thread_ends: int = 0,
                       bevel: List[float] = None,
                       grinding: int = 2) -> Dict[str, Any]:
    """
    获取水磨数据（所有零件都生成）
    
    Args:
        hanging_table: 挂台个数（0, 1, 2...）
        c1_c2_chamfer: C1-C2倒角个数
        c3_c5_chamfer: C3-C5倒角个数
        r1_r2_chamfer: R1-R2倒角个数
        r3_r5_chamfer: R3-R5倒角个数
        oil_tank: 油槽标识（0=无油槽，1=有油槽）
        thread_ends: 线头件数（0=普通零件，1=备料件/自找料）
        bevel: 斜面长度列表(mm)，例如 [20.5, 15.3]，默认为空列表
        grinding: 研磨面数（通过识别块数量确定），默认2
    
    Returns:
        Dict: 水磨数据字典（所有零件都返回，不再返回None）
    """
    if bevel is None:
        bevel = []
    
    return calculate_water_mill_data(
        hanging_table=hanging_table,
        c1_c2_chamfer=c1_c2_chamfer,
        c3_c5_chamfer=c3_c5_chamfer,
        r1_r2_chamfer=r1_r2_chamfer,
        r3_r5_chamfer=r3_r5_chamfer,
        oil_tank=oil_tank,
        thread_ends=thread_ends,
        bevel=bevel,
        grinding=grinding
    )
