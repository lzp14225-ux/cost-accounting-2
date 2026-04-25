"""
价格加权路由
负责人：李志鹏

提供 price_wg 接口

计算流程：
1. 根据 job_id 和 subgraph_id 从 subgraphs 表查询 part_name，并从 features 表查询尺寸和材料
2. 对 part_name 做关键词模糊匹配，默认只处理：模座、托板、垫脚
3. 根据 job_id 从 job_price_snapshots 表查询 category 为 rule 和 density 的数据
4. 根据 material 匹配 density 数据计算重量：weight(kg) = length_mm * width_mm * thickness_mm * density
5. 根据 weight 匹配 rule 数据获取价格系数
6. 计算加权价格：weight_price = weight * rule_price
7. 更新 subgraphs 表的 separate_item_cost 字段
8. 更新 processing_cost_calculation_details 表的 weight_price_steps 字段
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from pydantic_settings import BaseSettings
from typing import Optional, Dict, Any, List
from decimal import Decimal, ROUND_HALF_UP
import logging
import json
import os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/price_wg", tags=["weight_price"])


# ========== 配置类 ==========

class PriceWgSettings(BaseSettings):
    """Price WG 服务配置"""
    
    model_config = ConfigDict(
        env_file=".env",
        extra="ignore"
    )
    
    # Price WG 服务配置
    price_wg_rule_weight_unit: str = Field(default="kg", description="Rule 数据的重量单位: kg 或 g")
    price_wg_part_name_keywords: str = Field(default="模座,托板,垫脚", description="按重量计价的零件名称关键词，逗号分隔")


# 全局配置实例
settings = PriceWgSettings()


def _get_part_name_keywords() -> List[str]:
    """读取按重量计价的零件名关键词配置。"""
    return [
        keyword.strip()
        for keyword in settings.price_wg_part_name_keywords.split(",")
        if keyword.strip()
    ]


def _match_part_name_keyword(part_name: str) -> Optional[str]:
    """对零件名称做关键词模糊匹配，返回命中的关键词。"""
    if not part_name:
        return None

    for keyword in _get_part_name_keywords():
        if keyword in part_name:
            return keyword
    return None


# ========== 请求/响应模型 ==========

class PriceWgBatchRequest(BaseModel):
    """批量价格加权请求模型"""
    job_id: str = Field(..., description="任务ID (UUID格式)")
    subgraph_ids: List[str] = Field(..., description="子图ID列表", min_length=1)
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "job_id": "a5e716aa-3d3a-409f-afff-36cba63f57ec",
                "subgraph_ids": [
                    "9a61b497-bf0e-402e-8bf8-e4117ca76334_PH2-04",
                    "9a61b497-bf0e-402e-8bf8-e4117ca76334_LP-02",
                    "9a61b497-bf0e-402e-8bf8-e4117ca76334_DIE-03"
                ]
            }
        }
    )


class PriceWgResponse(BaseModel):
    """价格加权响应模型"""
    status: str
    message: str
    data: Optional[Dict[str, Any]] = None


# ========== API 接口 ==========

@router.post("", response_model=PriceWgResponse)
async def price_wg_root(request: PriceWgBatchRequest):
    """
    批量价格加权计算接口（根路径）
    
    路径: POST /api/price_wg
    
    这是为了兼容独立 price_add_weight.py 服务的路由
    实际调用 /calculate 端点的逻辑
    """
    return await calculate_weight_price(request)


@router.post("/calculate", response_model=PriceWgResponse)
async def calculate_weight_price(request: PriceWgBatchRequest):
    """
    批量价格加权计算接口
    
    优势：
    - rule 和 density 数据只查询一次，所有零件共享
    - 多个零件的计算并发执行
    - 数据库更新使用真正的批量操作(性能最优)
    - 支持单个或多个零件处理
    
    Args:
        request: 包含 job_id 和 subgraph_ids 列表
        
    Returns:
        PriceWgResponse: 批量计算结果
        
    Example:
        ```json
        {
            "job_id": "a5e716aa-3d3a-409f-afff-36cba63f57ec",
            "subgraph_ids": [
                "9a61b497-bf0e-402e-8bf8-e4117ca76334_PH2-04",
                "9a61b497-bf0e-402e-8bf8-e4117ca76334_LP-02"
            ]
        }
        ```
    """
    try:
        import time
        start_time = time.time()
        
        logger.info(f"Batch calculating weight price for job_id: {request.job_id}, {len(request.subgraph_ids)} parts")
        
        # Step 1: 并发查询所有零件数据和共享的 rule/density 数据
        import asyncio
        
        # 构建所有查询任务
        feature_tasks = [
            _get_feature_data(request.job_id, subgraph_id)
            for subgraph_id in request.subgraph_ids
        ]
        
        # 并发执行所有查询（features + rule + density）
        results = await asyncio.gather(
            *feature_tasks,
            _get_rule_data(request.job_id),
            _get_density_data(request.job_id)
        )
        
        # 分离结果
        feature_data_list = results[:-2]  # 前 N 个是 features
        rule_data = results[-2]           # 倒数第二个是 rule
        density_data = results[-1]        # 最后一个是 density
        
        query_time = time.time() - start_time
        logger.info(f"Query completed in {query_time:.3f}s")
        
        # 调试：显示 rule 数据
        logger.info(f"Found {len(rule_data)} rule records:")
        for rule in rule_data:
            logger.info(f"  - sub_category: {rule.get('sub_category')}, price: {rule.get('price')}, min_num: {rule.get('min_num')}")
        
        # Step 2: 先按 part_name 关键词过滤，只计算模座/托板/垫脚等目标零件
        calc_start = time.time()
        calc_tasks = []
        valid_subgraph_ids = []
        skipped_results = []
        skipped_subgraph_ids = []
        
        for i, subgraph_id in enumerate(request.subgraph_ids):
            feature_data = feature_data_list[i]
            if feature_data:
                part_name = feature_data.get("part_name", "")
                matched_keyword = _match_part_name_keyword(part_name)
                if not matched_keyword:
                    logger.info(
                        f"[按重量计价] 跳过: subgraph_id='{subgraph_id}', "
                        f"part_name='{part_name}', keywords={_get_part_name_keywords()}"
                    )
                    skipped_subgraph_ids.append(subgraph_id)
                    skipped_results.append({
                        "job_id": request.job_id,
                        "subgraph_id": subgraph_id,
                        "part_name": part_name,
                        "weight_price": None,
                        "matched_keyword": None,
                        "note": f"零件名称未匹配按重量计价关键词: {', '.join(_get_part_name_keywords())}"
                    })
                    continue

                logger.info(
                    f"[按重量计价] 命中: subgraph_id='{subgraph_id}', "
                    f"part_name='{part_name}', matched_keyword='{matched_keyword}'"
                )
                feature_data["matched_keyword"] = matched_keyword
                calc_tasks.append(
                    _calculate_weight_price_no_update(
                        request.job_id,
                        subgraph_id,
                        feature_data,
                        rule_data,
                        density_data
                    )
                )
                valid_subgraph_ids.append(subgraph_id)
            else:
                logger.warning(f"No feature data for subgraph_id: {subgraph_id}")

        if skipped_subgraph_ids:
            await _clear_skipped_weight_price(request.job_id, skipped_subgraph_ids)
            logger.info(
                f"Skipped {len(skipped_subgraph_ids)} parts for weight price because part_name did not match keywords"
            )

        if not calc_tasks:
            total_time = time.time() - start_time
            return PriceWgResponse(
                status="success",
                message=f"没有匹配按重量计价关键词的零件，已跳过: {len(skipped_results)} 个",
                data={
                    "job_id": request.job_id,
                    "total": len(request.subgraph_ids),
                    "success": 0,
                    "skipped": len(skipped_results),
                    "error": 0,
                    "matched_keywords": _get_part_name_keywords(),
                    "performance": {
                        "query_time": f"{query_time:.3f}s",
                        "calc_time": "0.000s",
                        "update_time": "0.000s",
                        "total_time": f"{total_time:.3f}s",
                        "avg_per_part": f"{total_time/len(request.subgraph_ids):.4f}s"
                    },
                    "results": [],
                    "skipped_results": skipped_results[:10]
                }
            )

        # 只有存在命中关键词的零件时，才要求重量规则和密度数据存在
        if not rule_data:
            return PriceWgResponse(
                status="error",
                message=f"未找到 rule 数据: job_id={request.job_id}"
            )
        
        if not density_data:
            return PriceWgResponse(
                status="error",
                message=f"未找到 density 数据: job_id={request.job_id}"
            )
        
        # 并发执行所有计算
        calc_results = await asyncio.gather(*calc_tasks, return_exceptions=True)
        
        calc_time = time.time() - calc_start
        logger.info(f"Calculation completed in {calc_time:.3f}s")
        
        # Step 3: 批量更新数据库（真正的批量操作）
        update_start = time.time()
        
        # 收集成功的计算结果
        success_results = []
        error_count = 0
        
        for result in calc_results:
            if isinstance(result, Exception):
                error_count += 1
                logger.error(f"Calculation error: {result}")
            else:
                success_results.append(result)
        
        # 批量更新数据库
        if success_results:
            await _batch_update_database(success_results)
        
        update_time = time.time() - update_start
        total_time = time.time() - start_time
        
        logger.info(
            f"Batch update completed: {len(success_results)} success, {error_count} errors, "
            f"query={query_time:.3f}s, calc={calc_time:.3f}s, update={update_time:.3f}s, total={total_time:.3f}s"
        )
        
        return PriceWgResponse(
            status="success",
            message=f"批量计算完成: {len(success_results)} 成功, {error_count} 失败",
            data={
                "job_id": request.job_id,
                "total": len(request.subgraph_ids),
                "success": len(success_results),
                "skipped": len(skipped_results),
                "error": error_count,
                "matched_keywords": _get_part_name_keywords(),
                "performance": {
                    "query_time": f"{query_time:.3f}s",
                    "calc_time": f"{calc_time:.3f}s",
                    "update_time": f"{update_time:.3f}s",
                    "total_time": f"{total_time:.3f}s",
                    "avg_per_part": f"{total_time/len(request.subgraph_ids):.4f}s"
                },
                "results": success_results[:10],  # 只返回前10个结果，避免响应过大
                "skipped_results": skipped_results[:10]
            }
        )
        
    except Exception as e:
        logger.error(f"Batch price WG calculation failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"批量价格加权计算失败: {str(e)}"
        )


# ========== 业务逻辑函数 ==========

async def _get_feature_data(job_id: str, subgraph_id: str) -> Optional[Dict[str, Any]]:
    """
    从 subgraphs / features 表查询零件信息
    
    Returns:
        Dict: {part_name, length_mm, width_mm, thickness_mm, material}
    """
    from api_gateway.database import db
    
    sql = """
        SELECT
            s.part_name,
            f.length_mm,
            f.width_mm,
            f.thickness_mm,
            f.material
        FROM subgraphs s
        LEFT JOIN features f
          ON f.job_id = s.job_id
         AND f.subgraph_id = s.subgraph_id
        WHERE s.job_id = $1::uuid AND s.subgraph_id = $2
    """
    
    row = await db.fetch_one(sql, job_id, subgraph_id)
    if not row:
        logger.warning(f"No feature data found for job_id={job_id}, subgraph_id={subgraph_id}")
        return None
    
    return {
        "part_name": row["part_name"],
        "length_mm": row["length_mm"],
        "width_mm": row["width_mm"],
        "thickness_mm": row["thickness_mm"],
        "material": row["material"]
    }


async def _get_rule_data(job_id: str) -> List[Dict[str, Any]]:
    """
    从 job_price_snapshots 表查询 rule 数据
    
    Returns:
        List[Dict]: [{sub_category, price, unit, min_num}, ...]
    """
    from api_gateway.database import db
    
    sql = """
        SELECT sub_category, price, unit, min_num
        FROM job_price_snapshots
        WHERE job_id = $1::uuid 
          AND category = 'rule'
          AND sub_category = 'other'
        ORDER BY min_num
    """
    
    rows = await db.fetch_all(sql, job_id)
    return [dict(row) for row in rows]


async def _get_density_data(job_id: str) -> List[Dict[str, Any]]:
    """
    从 job_price_snapshots 表查询 density 数据
    
    Returns:
        List[Dict]: [{sub_category, price, unit}, ...]
    """
    from api_gateway.database import db
    
    sql = """
        SELECT sub_category, price, unit
        FROM job_price_snapshots
        WHERE job_id = $1::uuid AND category = 'density'
    """
    
    rows = await db.fetch_all(sql, job_id)
    return [dict(row) for row in rows]


def _parse_min_num_range(min_num_str: str) -> tuple[float, float]:
    """
    解析 min_num 字符串为范围
    
    Examples:
        "[5000,9999999)" -> (5000, 9999999)
        "[2000,5000)" -> (2000, 5000)
        "(0,500)" -> (0, 500)
    
    Returns:
        (min_value, max_value)
    """
    # 去除空格
    min_num_str = min_num_str.strip()
    
    # 判断左边界是否包含
    left_inclusive = min_num_str.startswith('[')
    
    # 判断右边界是否包含
    right_inclusive = min_num_str.endswith(']')
    
    # 提取数字部分
    content = min_num_str.strip('[]()').split(',')
    min_val = float(content[0])
    max_val = float(content[1])
    
    # 如果不包含边界，稍微调整一下（避免边界问题）
    if not left_inclusive:
        min_val += 0.001
    if not right_inclusive:
        max_val -= 0.001
    
    return min_val, max_val


def _match_rule_price(weight: Decimal, rule_data: List[Dict[str, Any]], weight_unit: str = "kg") -> Optional[Dict[str, Any]]:
    """
    根据重量匹配 rule 数据获取价格系数
    
    Args:
        weight: 重量（kg）
        rule_data: rule 数据列表
        weight_unit: 重量单位，"kg" 或 "g"。如果 rule 数据的 min_num 是克(g)，则传入 "g"
        
    Returns:
        Dict: {sub_category, price, unit, min_num, matched_range}
    """
    weight_float = float(weight)
    
    # 如果 rule 数据的单位是克(g)，需要将 kg 转换为 g
    if weight_unit == "g":
        weight_float = weight_float * 1000
        logger.info(f"Converting weight from kg to g: {float(weight)} kg = {weight_float} g")
    
    for rule in rule_data:
        min_num_str = rule["min_num"]
        if not min_num_str:
            continue
        
        try:
            min_val, max_val = _parse_min_num_range(min_num_str)
            
            # 检查重量是否在范围内
            if min_val <= weight_float <= max_val:
                logger.info(f"Matched rule: weight={weight_float}, range={min_num_str}, price={rule['price']}")
                return {
                    "sub_category": rule["sub_category"],
                    "price": rule["price"],
                    "unit": rule["unit"],
                    "min_num": min_num_str,
                    "matched_range": f"[{min_val}, {max_val}]"
                }
        except Exception as e:
            logger.error(f"Failed to parse min_num: {min_num_str}, error: {e}")
            continue
    
    logger.warning(f"No matching rule found for weight: {weight_float}")
    return None


def _match_density(material: str, density_data: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    根据材料匹配 density 数据
    
    Args:
        material: 材料名称
        density_data: density 数据列表
        
    Returns:
        Dict: {sub_category, price (density), unit}
    """
    if not material:
        logger.warning("Material is empty")
        return None
    
    # 不区分大小写匹配
    material_upper = material.upper()
    
    for density in density_data:
        sub_category = density["sub_category"]
        if sub_category and sub_category.upper() == material_upper:
            logger.info(f"Matched density: material={material}, density={density['price']}")
            return density
    
    logger.warning(f"No matching density found for material: {material}")
    return None


async def _calculate_weight_price_no_update(
    job_id: str,
    subgraph_id: str,
    feature_data: Dict[str, Any],
    rule_data: List[Dict[str, Any]],
    density_data: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    计算加权价格（不更新数据库，用于批量处理）
    
    Returns:
        Dict: 计算结果
    """
    # 提取零件信息
    length_mm = feature_data["length_mm"]
    width_mm = feature_data["width_mm"]
    thickness_mm = feature_data["thickness_mm"]
    material = feature_data["material"]
    part_name = feature_data.get("part_name")
    matched_keyword = feature_data.get("matched_keyword")
    
    # 检查必需字段
    if not all([length_mm, width_mm, thickness_mm]):
        missing = []
        if not length_mm:
            missing.append("length_mm")
        if not width_mm:
            missing.append("width_mm")
        if not thickness_mm:
            missing.append("thickness_mm")
        
        weight_price_steps = [{
            "step": "数据验证",
            "status": "failed",
            "reason": f"缺少必需字段: {', '.join(missing)}",
            "missing_fields": missing,
            "weight_price": 0.0
        }]
        
        # 更新数据库
        await _update_database(job_id, subgraph_id, 0.0, weight_price_steps)
        
        return {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "weight_price": 0.0,
            "note": f"缺少必需字段: {', '.join(missing)}"
        }
    
    # 匹配 density
    density_match = _match_density(material, density_data)
    if not density_match:
        weight_price_steps = [{
            "step": "匹配材料密度",
            "status": "failed",
            "material": material,
            "reason": f"未找到材料对应的密度: {material}",
            "weight_price": 0.0
        }]
        
        # 更新数据库
        await _update_database(job_id, subgraph_id, 0.0, weight_price_steps)
        
        return {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "material": material,
            "weight_price": 0.0,
            "note": f"未找到材料对应的密度: {material}"
        }
    
    density = Decimal(str(density_match["price"]))
    
    # 计算重量：weight(kg) = length_mm * width_mm * thickness_mm * density
    length = Decimal(str(length_mm))
    width = Decimal(str(width_mm))
    thickness = Decimal(str(thickness_mm))
    
    weight = (length * width * thickness * density).quantize(
        Decimal("0.0001"), ROUND_HALF_UP
    )
    
    # 匹配 rule（使用配置的单位）
    rule_match = _match_rule_price(weight, rule_data, settings.price_wg_rule_weight_unit)
    if not rule_match:
        weight_price_steps = [{
            "step": "匹配重量规则",
            "status": "failed",
            "weight": float(weight),
            "reason": f"未找到重量对应的规则: {weight} kg",
            "weight_price": 0.0
        }]
        
        # 更新数据库
        await _update_database(job_id, subgraph_id, 0.0, weight_price_steps)
        
        return {
            "job_id": job_id,
            "subgraph_id": subgraph_id,
            "part_name": part_name,
            "weight": float(weight),
            "weight_price": 0.0,
            "note": f"未找到重量对应的规则: {weight} kg"
        }
    
    rule_price = Decimal(str(rule_match["price"]))
    
    # 计算加权价格：weight_price = weight * rule_price
    weight_price = (weight * rule_price).quantize(
        Decimal("0.01"), ROUND_HALF_UP
    )
    
    # 构建计算步骤
    weight_price_steps = [
        {
            "step": "获取零件信息",
            "part_name": part_name,
            "matched_keyword": matched_keyword,
            "length_mm": float(length_mm),
            "width_mm": float(width_mm),
            "thickness_mm": float(thickness_mm),
            "material": material
        },
        {
            "step": "匹配材料密度",
            "material": material,
            "matched_sub_category": density_match["sub_category"],
            "density": float(density),
            "unit": density_match["unit"]
        },
        {
            "step": "计算重量",
            "formula": f"{length_mm} * {width_mm} * {thickness_mm} * {density}",
            "weight": float(weight),
            "unit": "kg"
        },
        {
            "step": "匹配重量规则",
            "weight": float(weight),
            "matched_range": rule_match["matched_range"],
            "rule_price": float(rule_price),
            "sub_category": rule_match["sub_category"]
        },
        {
            "step": "计算加权价格",
            "formula": f"{weight} * {rule_price}",
            "weight_price": float(weight_price),
            "unit": "元"
        }
    ]
    
    logger.info(
        f"[{subgraph_id}] weight={weight} kg, rule_price={rule_price}, "
        f"weight_price={weight_price} 元"
    )
    
    return {
        "job_id": job_id,
        "subgraph_id": subgraph_id,
        "part_name": part_name,
        "matched_keyword": matched_keyword,
        "material": material,
        "length_mm": float(length_mm),
        "width_mm": float(width_mm),
        "thickness_mm": float(thickness_mm),
        "density": float(density),
        "weight": float(weight),
        "rule_price": float(rule_price),
        "weight_price": float(weight_price),
        "weight_price_steps": weight_price_steps
    }


async def _update_database(job_id: str, subgraph_id: str, weight_price: float, weight_price_steps: List[Dict[str, Any]]):
    """单个更新数据库（用于错误情况）"""
    from api_gateway.database import db
    
    # 更新 subgraphs 表
    sql_subgraphs = """
        UPDATE subgraphs
        SET separate_item_cost = $3,
            updated_at = NOW()
        WHERE job_id = $1::uuid AND subgraph_id = $2
    """
    
    # 更新 processing_cost_calculation_details 表
    sql_details = """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, weight_price_steps)
        VALUES ($1::uuid, $2, $3::jsonb)
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            weight_price_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.weight_price_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != 'weight_price'
            ) || jsonb_build_array(
                jsonb_build_object(
                    'category', 'weight_price',
                    'steps', $3::jsonb
                )
            )
    """
    
    steps_json = json.dumps([{
        "category": "weight_price",
        "steps": weight_price_steps
    }], default=str)
    
    await db.execute(sql_subgraphs, job_id, subgraph_id, weight_price)
    await db.execute(sql_details, job_id, subgraph_id, steps_json)


async def _clear_skipped_weight_price(job_id: str, subgraph_ids: List[str]):
    """清理未命中关键词零件的按重量计价结果，避免旧数据残留进总价。"""
    if not subgraph_ids:
        return

    from api_gateway.database import db
    import asyncio

    sql_subgraphs = """
        UPDATE subgraphs
        SET separate_item_cost = NULL,
            updated_at = NOW()
        WHERE job_id = $1::uuid AND subgraph_id = ANY($2::text[])
    """

    sql_details = """
        UPDATE processing_cost_calculation_details
        SET weight_price_steps = (
            SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
            FROM jsonb_array_elements(
                COALESCE(weight_price_steps, '[]'::jsonb)
            ) AS elem
            WHERE elem->>'category' != 'weight_price'
        )
        WHERE job_id = $1::uuid AND subgraph_id = ANY($2::text[])
    """

    await asyncio.gather(
        db.execute(sql_subgraphs, job_id, subgraph_ids),
        db.execute(sql_details, job_id, subgraph_ids)
    )


async def _batch_update_database(results: List[Dict[str, Any]]):
    """
    批量更新数据库（真正的批量操作，性能最优）
    
    使用 PostgreSQL 的 unnest 和 CASE WHEN 实现真正的批量更新
    
    Args:
        results: 计算结果列表，每项包含 job_id, subgraph_id, weight_price, weight_price_steps
    """
    if not results:
        return
    
    from api_gateway.database import db
    import asyncio
    
    logger.info(f"Batch updating database for {len(results)} records")
    
    # 准备批量数据
    subgraph_ids = []
    weight_prices = []
    steps_list = []
    
    for result in results:
        subgraph_ids.append(result["subgraph_id"])
        weight_prices.append(result["weight_price"])
        steps_list.append(json.dumps(result["weight_price_steps"], default=str))
    
    job_id = results[0]["job_id"]  # 所有结果的 job_id 相同
    
    # 批量更新 subgraphs 表
    sql_subgraphs = """
        UPDATE subgraphs
        SET separate_item_cost = data.weight_price,
            updated_at = NOW()
        FROM (
            SELECT 
                unnest($2::text[]) as subgraph_id,
                unnest($3::numeric[]) as weight_price
        ) as data
        WHERE subgraphs.job_id = $1::uuid 
          AND subgraphs.subgraph_id = data.subgraph_id
    """
    
    # 批量更新 processing_cost_calculation_details 表
    sql_details = """
        INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, weight_price_steps)
        SELECT 
            $1::uuid,
            unnest($2::text[]),
            jsonb_build_array(
                jsonb_build_object(
                    'category', 'weight_price',
                    'steps', unnest($3::jsonb[])
                )
            )
        ON CONFLICT (job_id, subgraph_id) 
        DO UPDATE SET
            weight_price_steps = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements(
                    COALESCE(processing_cost_calculation_details.weight_price_steps, '[]'::jsonb)
                ) AS elem
                WHERE elem->>'category' != 'weight_price'
            ) || jsonb_build_array(
                jsonb_build_object(
                    'category', 'weight_price',
                    'steps', EXCLUDED.weight_price_steps->0->'steps'
                )
            )
    """
    
    # 并发执行两个批量更新
    try:
        await asyncio.gather(
            db.execute(sql_subgraphs, job_id, subgraph_ids, weight_prices),
            db.execute(sql_details, job_id, subgraph_ids, steps_list)
        )
        logger.info(f"Successfully batch updated {len(results)} records")
    except Exception as e:
        logger.error(f"Batch update failed: {e}")
        raise
