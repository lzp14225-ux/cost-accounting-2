"""
批量更新助手模块
负责人：李志鹏

提供通用的批量数据库更新函数，供各个计算脚本使用

优化说明：
- 使用 PostgreSQL 原生 ON CONFLICT 实现 UPSERT
- 在数据库中处理 JSONB 合并，减少数据库往返次数
- 性能提升约 50%
"""
import json
import logging
import asyncio
from typing import List, Dict, Any

from api_gateway.database import db

logger = logging.getLogger(__name__)


# PostgreSQL 原生 UPSERT SQL 模板
# 使用 ON CONFLICT 实现一次性 UPSERT，避免先 SELECT 再 UPDATE/INSERT
UPSERT_SQL_TEMPLATES = {
    # 材料费
    "material_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, material_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            material_cost = EXCLUDED.material_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 热处理费
    "heat_treatment_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, heat_treatment_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            heat_treatment_cost = EXCLUDED.heat_treatment_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 线割基础价格
    "basic_processing_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, basic_processing_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            basic_processing_cost = EXCLUDED.basic_processing_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 线割特殊价格
    "special_base_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, special_base_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            special_base_cost = EXCLUDED.special_base_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 线割标准基本费
    "standard_base_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, standard_base_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            standard_base_cost = EXCLUDED.standard_base_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 自找料材料费
    "material_additional_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, material_additional_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            material_additional_cost = EXCLUDED.material_additional_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 重量
    "weight": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, weight, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            weight = EXCLUDED.weight,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 水磨线头费
    "thread_ends_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, thread_ends_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            thread_ends_cost = EXCLUDED.thread_ends_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 水磨挂台费
    "hanging_table_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, hanging_table_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            hanging_table_cost = EXCLUDED.hanging_table_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 水磨倒角费
    "chamfer_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, chamfer_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            chamfer_cost = EXCLUDED.chamfer_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 水磨斜面耗时费
    "bevel_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, bevel_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            bevel_cost = EXCLUDED.bevel_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 水磨油槽耗时费
    "oil_tank_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, oil_tank_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            oil_tank_cost = EXCLUDED.oil_tank_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 水磨高度费
    "high_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, high_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            high_cost = EXCLUDED.high_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 水磨磨削费
    "grinding_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, grinding_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            grinding_cost = EXCLUDED.grinding_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 水磨板费
    "plate_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, plate_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            plate_cost = EXCLUDED.plate_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 水磨长条费
    "long_strip_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, long_strip_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            long_strip_cost = EXCLUDED.long_strip_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 水磨零件费
    "component_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, component_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            component_cost = EXCLUDED.component_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 牙孔费用
    "tooth_hole_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, tooth_hole_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            tooth_hole_cost = EXCLUDED.tooth_hole_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 牙孔放电时间费用
    "tooth_hole_time_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, tooth_hole_time_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            tooth_hole_time_cost = EXCLUDED.tooth_hole_time_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # NC时间费用
    "nc_time_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, nc_time_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            nc_time_cost = EXCLUDED.nc_time_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # NC开粗费用
    "nc_roughing_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, nc_roughing_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            nc_roughing_cost = EXCLUDED.nc_roughing_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # NC精铣费用
    "nc_milling_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, nc_milling_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            nc_milling_cost = EXCLUDED.nc_milling_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # NC钻床费用
    "nc_drilling_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, nc_drilling_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            nc_drilling_cost = EXCLUDED.nc_drilling_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # NC开粗基本费用
    "nc_base_roughing_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, nc_base_roughing_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            nc_base_roughing_cost = EXCLUDED.nc_base_roughing_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # NC精铣基本费用
    "nc_base_milling_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, nc_base_milling_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            nc_base_milling_cost = EXCLUDED.nc_base_milling_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # NC钻床基本费用
    "nc_base_drilling_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, nc_base_drilling_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            nc_base_drilling_cost = EXCLUDED.nc_base_drilling_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # NC基本费用（保留旧字段以兼容）
    "nc_base_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, nc_base_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            nc_base_cost = EXCLUDED.nc_base_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # NC主视图时间
    "nc_z_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, nc_z_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            nc_z_cost = EXCLUDED.nc_z_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # NC背面时间
    "nc_b_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, nc_b_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            nc_b_cost = EXCLUDED.nc_b_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # NC侧面正面时间
    "nc_c_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, nc_c_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            nc_c_cost = EXCLUDED.nc_c_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # NC侧背时间
    "nc_c_b_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, nc_c_b_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            nc_c_b_cost = EXCLUDED.nc_c_b_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # NC正面时间
    "nc_z_view_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, nc_z_view_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            nc_z_view_cost = EXCLUDED.nc_z_view_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # NC正面的背面时间
    "nc_b_view_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, nc_b_view_cost, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, $3::text, 
             jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            nc_b_view_cost = EXCLUDED.nc_b_view_cost,
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $4::text
            ) || jsonb_build_array(jsonb_build_object('category', $4::text, 'steps', $5::jsonb))
    """,
    
    # 总价（最终总价计算）- 只更新计算步骤，不更新字段值
    "total_cost": """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, 
             jsonb_build_array(jsonb_build_object('category', $3::text, 'steps', $4::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $3::text
            ) || jsonb_build_array(jsonb_build_object('category', $3::text, 'steps', $4::jsonb))
    """,
    
    # 特殊情况：只更新 calculation_steps，不更新字段值（如 weight）
    None: """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, calculation_steps)
        VALUES 
            ($1::uuid, $2::text, 
             jsonb_build_array(jsonb_build_object('category', $3::text, 'steps', $4::jsonb)))
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            calculation_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.calculation_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != $3::text
            ) || jsonb_build_array(jsonb_build_object('category', $3::text, 'steps', $4::jsonb))
    """
}


async def batch_upsert_with_steps(
    updates: List[Dict[str, Any]],
    category: str,
    field_name: str
):
    """
    批量 UPSERT 计算结果到 processing_cost_calculation_details 表
    
    Args:
        updates: 更新数据列表
            [
                {
                    "job_id": "...",
                    "subgraph_id": "...",
                    "value": 100.5,  # 要更新的字段值
                    "steps": [...]    # 计算步骤
                },
                ...
            ]
        category: 步骤分类（如 "material", "heat", "wire_base" 等）
        field_name: 数据库字段名（如 "material_cost", "heat_treatment_cost" 等）
    """
    if not updates:
        return
    
    logger.info(f"Batch updating {len(updates)} records for category: {category}")
    
    # 并发执行所有 UPSERT
    tasks = []
    for data in updates:
        tasks.append(_upsert_single_record(
            data["job_id"],
            data["subgraph_id"],
            field_name,
            data["value"],
            category,
            data["steps"]
        ))
    
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success_count = sum(1 for r in results if r is True)
        logger.info(f"Successfully batch updated {success_count}/{len(updates)} records")
    except Exception as e:
        logger.error(f"Batch update failed: {e}")
        raise


async def _upsert_single_record(
    job_id: str,
    subgraph_id: str,
    field_name: str,
    field_value: Any,
    category: str,
    steps: List[Dict]
) -> bool:
    """
    使用 PostgreSQL 原生 ON CONFLICT 实现 UPSERT
    
    优化说明：
    - 从原来的 2 次数据库往返（SELECT + UPDATE/INSERT）减少到 1 次
    - 在数据库中使用 JSONB 函数处理 calculation_steps 合并
    - 性能提升约 50%
    
    Returns:
        bool: 是否成功
    """
    try:
        # 获取对应的 SQL 模板
        sql_template = UPSERT_SQL_TEMPLATES.get(field_name)
        if sql_template is None:
            logger.error(f"No SQL template found for field_name: {field_name}")
            return False
        
        # 序列化 steps 为 JSON 字符串
        steps_json = json.dumps(steps, default=str)
        
        # 水磨相关字段需要转换为字符串（数据库中是 varchar 类型）
        water_mill_fields = [
            "thread_ends_cost",
            "hanging_table_cost",
            "chamfer_cost",
            "bevel_cost",
            "oil_tank_cost",
            "high_cost",
            "grinding_cost",
            "plate_cost",
            "long_strip_cost",
            "component_cost",
        ]
        
        # NC相关字段需要转换为字符串（数据库中是 varchar 类型）
        nc_fields = [
            "nc_base_cost",
            "nc_z_cost",
            "nc_b_cost",
            "nc_c_cost",
            "nc_c_b_cost",
            "nc_z_view_cost",
            "nc_b_view_cost",
        ]
        
        # 牙孔相关字段（数据库中是 varchar 类型，需要转换）
        # tooth_hole_cost 存储费用（元），数据库类型是 varchar
        # tooth_hole_time_cost 存储时间（小时），数据库类型是 varchar
        tooth_hole_fields = [
            "tooth_hole_cost",
            "tooth_hole_time_cost",
        ]
        
        if field_name in water_mill_fields or field_name in nc_fields or field_name in tooth_hole_fields:
            field_value = str(field_value)
        
        # 执行 UPSERT（1 次数据库往返）
        if field_name is None or field_name == "total_cost":
            # 只更新 calculation_steps（如 weight 或 total_cost）
            await db.execute(sql_template, job_id, subgraph_id, category, steps_json)
        else:
            # 更新字段值和 calculation_steps
            await db.execute(sql_template, job_id, subgraph_id, field_value, category, steps_json)
        
        return True
    
    except Exception as e:
        logger.error(f"Failed to upsert record for {subgraph_id}: {e}")
        logger.error(f"  field_name: {field_name}, category: {category}")
        return False
