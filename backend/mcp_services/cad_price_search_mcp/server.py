"""
CAD 和价格搜索 MCP 服务器 (SSE模式)
整合 CAD 解析和价格计算功能
端口：8200

职责：
1. CAD 处理：DWG 拆图、特征识别
2. 价格搜索：零件信息、价格信息检索
3. 价格计算：材料费、加工费等计算
"""
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
from starlette.responses import JSONResponse
from starlette.applications import Starlette
from starlette.routing import Route
import uvicorn
import json
import sys
import os
from pathlib import Path
import asyncio
from dotenv import load_dotenv
import logging
from decimal import Decimal

# 自定义 JSON 编码器，处理 Decimal 类型
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

# 加载环境变量
load_dotenv()

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts" / "cad_chaitu"))
sys.path.insert(0, str(project_root / "scripts" / "recognition"))
sys.path.insert(0, str(project_root / "scripts"))

# 配置日志（提前配置，以便在导入时使用）
# 创建 logs 目录（如果不存在）
log_dir = project_root / "logs"
log_dir.mkdir(exist_ok=True)

# 日志文件路径
log_file = log_dir / "mcp_service.log"

# 尝试使用 loguru（如果可用）
try:
    from loguru import logger
    
    # 移除默认的 handler
    logger.remove()
    
    # 添加控制台输出
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="DEBUG"  # 显示所有级别的日志
    )
    
    # 添加文件输出（带轮转、保留和压缩）
    logger.add(
        log_file,
        rotation="00:00",      # 每天午夜0点轮转
        retention="30 days",   # 保留30天
        compression="zip",     # 压缩为zip
        encoding="utf-8",
        level="INFO",         # 显示所有级别的日志
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
    )
    
    logger.info(f"日志文件保存位置: {log_file} (使用 loguru，支持轮转和压缩)")
    
except ImportError:
    # 如果没有 loguru，使用标准 logging
    import logging
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),  # 输出到文件
            logging.StreamHandler()  # 输出到控制台
        ]
    )
    logger = logging.getLogger(__name__)
    logger.info(f"日志文件保存位置: {log_file} (使用标准 logging，无轮转功能)")

# ============================================================================
# 导入 CAD 处理模块（可选）
# ============================================================================
try:
    from cad_chaitu import chaitu_process
    from feature_recognition import batch_feature_recognition_process
    CAD_AVAILABLE = True
    logger.info("[OK] CAD 处理模块导入成功")
except ImportError as e:
    CAD_AVAILABLE = False
    logger.warning(f"[WARN] CAD 处理模块导入失败: {e}")
    logger.warning("       CAD 功能将不可用，但价格计算功能仍可正常使用")
    chaitu_process = None
    batch_feature_recognition_process = None

# 导入进度发布器
from shared.progress_publisher import ProgressPublisher
from shared.progress_stages import ProgressStage, ProgressPercent

# ============================================================================
# 导入价格搜索和计算模块
# ============================================================================
from scripts.search import (
    base_itemcode_search,
    material_search,
    heat_search,
    tooth_hole_search,
    water_mill_search,
    wire_base_search,
    wire_special_search,
    wire_standard_search,
    wire_total_search,
    nc_search,
    total_search,
    search,
    density_search  # 新增：密度检索
)

from scripts.calculate import (
    price_material,
    price_heat,
    price_weight,
    price_tooth_hole,
    price_wire_base,
    price_wire_special,
    price_wire_standard,
    price_add_auto_material,
    price_water_mill_bevel_cost,
    price_water_mill_chamfer_cost,
    price_water_mill_component,
    price_water_mill_hanging_table,
    price_water_mill_high_cost,
    price_water_mill_long_strip,
    price_water_mill_oil_tank,
    price_water_mill_plate,
    price_water_mill_thread_ends,
    price_water_mill_total,
    price_wire_total,
    price_nc_base,
    price_nc_time,
    price_nc_total,
    price_total,
    judgment
)

# 创建进度发布器实例
try:
    progress_publisher = ProgressPublisher()
    logger.info("[OK] 进度发布器初始化成功")
except Exception as e:
    logger.warning(f"[WARN] 进度发布器初始化失败: {e}")
    logger.warning("       MCP 服务将继续运行，但不会发布进度")
    progress_publisher = None

# 创建 MCP 服务器
mcp_server = Server("cad-price-search-mcp")

# ============================================================================
# 工具定义
# ============================================================================

@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    """列出所有可用工具 - CAD工具 + 价格工具"""
    tools = []
    
    # ========== CAD 处理工具 ==========
    cad_tools = [
        Tool(
            name="process_cad_and_features",
            description="完整的 CAD 处理流程：下载 DWG → 拆图 → 特征识别",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "任务ID（必填，UUID格式）"
                    },
                    "dwg_url": {
                        "type": "string",
                        "description": "DWG 文件的 URL 或 MinIO 路径（可选）"
                    }
                },
                "required": ["job_id"]
            }
        ),
        Tool(
            name="cad_chaitu",
            description="单独的 CAD 拆图功能：下载 DWG → 拆图 → 上传子图到 MinIO",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "任务ID（必填，UUID格式）"
                    },
                    "dwg_url": {
                        "type": "string",
                        "description": "DWG 文件的 URL 或 MinIO 路径（可选）"
                    }
                },
                "required": ["job_id"]
            }
        ),
        Tool(
            name="feature_recognition",
            description="单独的特征识别功能：从 MinIO 下载子图 DXF → 提取特征 → 保存到数据库",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "任务ID（必填，UUID格式）"
                    },
                    "subgraph_id": {
                        "type": "string",
                        "description": "子图ID（可选，不提供则处理所有子图）"
                    }
                },
                "required": ["job_id"]
            }
        )
    ]
    
    # ========== 价格搜索工具 ==========
    search_tool_configs = [
        ("search_base_itemcode", base_itemcode_search.MCP_TOOL_META),
        ("search_material", material_search.MCP_TOOL_META),
        ("search_heat", heat_search.MCP_TOOL_META),
        ("search_tooth_hole", tooth_hole_search.MCP_TOOL_META),
        ("search_water_mill", water_mill_search.MCP_TOOL_META),
        ("search_wire_base", wire_base_search.MCP_TOOL_META),
        ("search_wire_special", wire_special_search.MCP_TOOL_META),
        ("search_wire_standard", wire_standard_search.MCP_TOOL_META),
        ("search_wire_total", wire_total_search.MCP_TOOL_META),
        ("search_nc", nc_search.MCP_TOOL_META),
        ("search_total", total_search.MCP_TOOL_META),
        ("search_subgraphs_cost", search.MCP_TOOL_META),
        ("search_density", density_search.MCP_TOOL_META),  # 新增：密度检索
    ]
    
    # ========== 价格计算工具 ==========
    calculate_tool_configs = [
        ("calculate_material_cost", price_material.MCP_TOOL_META),
        ("calculate_heat_treatment_cost", price_heat.MCP_TOOL_META),
        ("calculate_weight", price_weight.MCP_TOOL_META),
        ("calculate_tooth_hole_cost", price_tooth_hole.MCP_TOOL_META),
        ("calculate_wire_base_price", price_wire_base.MCP_TOOL_META),
        ("calculate_wire_special_price", price_wire_special.MCP_TOOL_META),
        ("calculate_wire_standard_price", price_wire_standard.MCP_TOOL_META),
        ("calculate_add_auto_material_cost", price_add_auto_material.MCP_TOOL_META),
        ("calculate_water_mill_bevel_cost", price_water_mill_bevel_cost.MCP_TOOL_META),
        ("calculate_water_mill_chamfer_cost", price_water_mill_chamfer_cost.MCP_TOOL_META),
        ("calculate_water_mill_component_price", price_water_mill_component.MCP_TOOL_META),
        ("calculate_water_mill_hanging_table_price", price_water_mill_hanging_table.MCP_TOOL_META),
        ("calculate_water_mill_high_cost", price_water_mill_high_cost.MCP_TOOL_META),
        ("calculate_water_mill_long_strip_price", price_water_mill_long_strip.MCP_TOOL_META),
        ("calculate_water_mill_oil_tank_cost", price_water_mill_oil_tank.MCP_TOOL_META),
        ("calculate_water_mill_plate_price", price_water_mill_plate.MCP_TOOL_META),
        ("calculate_water_mill_thread_ends_price", price_water_mill_thread_ends.MCP_TOOL_META),
        ("calculate_water_mill_total_cost", price_water_mill_total.MCP_TOOL_META),
        ("calculate_wire_total_cost", price_wire_total.MCP_TOOL_META),
        ("calculate_nc_base_cost", price_nc_base.MCP_TOOL_META),
        ("calculate_nc_time_cost", price_nc_time.MCP_TOOL_META),
        ("calculate_nc_total_cost", price_nc_total.MCP_TOOL_META),
        ("calculate_final_total_cost", {
            "name": "calculate_final_total_cost",
            "description": "计算最终总价和加工成本总计：汇总所有成本项，更新 subgraphs 表和 jobs 表（在 judgment_cleanup 之后执行）。如果不传入subgraph_ids，则计算该job_id下的所有零件",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "任务ID (UUID)"
                    },
                    "subgraph_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "子图ID列表（可选，如果为空则计算所有零件）"
                    }
                },
                "required": ["job_id"]
            }
        }),
        ("judgment_cleanup", judgment.MCP_TOOL_META),
        ("update_job_total_cost_only", {
            "name": "update_job_total_cost_only",
            "description": "只更新 jobs.total_cost（从所有子图汇总），不更新 subgraphs",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "任务ID (UUID)"
                    }
                },
                "required": ["job_id"]
            }
        }),
    ]
    
    # 添加 CAD 工具
    tools.extend(cad_tools)
    
    # 生成价格搜索工具
    for tool_name, meta in search_tool_configs:
        tools.append(Tool(
            name=tool_name,
            description=meta["description"],
            inputSchema=meta["inputSchema"]
        ))
    
    # 生成价格计算工具
    for tool_name, meta in calculate_tool_configs:
        tools.append(Tool(
            name=tool_name,
            description=meta["description"],
            inputSchema=meta["inputSchema"]
        ))
    
    return tools

@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """调用工具 - 统一路由"""
    try:
        # ========== CAD 处理工具路由 ==========
        if name == "process_cad_and_features":
            return await handle_process_cad_and_features(arguments)
        elif name == "cad_chaitu":
            return await handle_cad_chaitu(arguments)
        elif name == "feature_recognition":
            return await handle_feature_recognition(arguments)
        
        # ========== 价格工具路由 ==========
        else:
            return await handle_price_tool(name, arguments)
    
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        logger.error(f"[ERROR] 工具执行异常: {e}")
        logger.error(error_detail)
        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "message": f"工具执行异常: {str(e)}",
                "detail": error_detail
            }, ensure_ascii=False, cls=DecimalEncoder)
        )]

# ============================================================================
# CAD 工具处理函数
# ============================================================================

async def handle_process_cad_and_features(arguments: dict) -> list[TextContent]:
    """完整流程：拆图 + 特征识别"""
    if not CAD_AVAILABLE:
        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "message": "CAD 处理功能不可用，请安装 ezdxf 和 minio 依赖包"
            }, ensure_ascii=False)
        )]
    
    job_id = arguments.get("job_id")
    dwg_url = arguments.get("dwg_url")
    
    if not job_id:
        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "message": "job_id 参数必填"
            }, ensure_ascii=False)
        )]
    
    logger.info(f">> 开始处理 CAD 任务: {job_id}")
    
    # 步骤1: CAD 拆图
    logger.info(f"[步骤1] 开始 CAD 拆图...")
    chaitu_result = await chaitu_process(dwg_url, job_id)
    
    if chaitu_result.get("status") != "ok":
        logger.error(f"[ERROR] CAD 拆图失败: {chaitu_result.get('message')}")
        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "message": f"CAD 拆图失败: {chaitu_result.get('message')}",
                "chaitu_result": chaitu_result
            }, ensure_ascii=False)
        )]
    
    logger.info(f"[OK] CAD 拆图完成: {chaitu_result.get('message')}")
    
    # 步骤2: 特征识别
    logger.info(f"[步骤2] 开始特征识别...")
    feature_result = batch_feature_recognition_process(job_id, None)
    
    if not feature_result.get("success"):
        logger.error(f"[ERROR] 特征识别失败: {feature_result.get('message')}")
        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "message": f"特征识别失败: {feature_result.get('message')}",
                "chaitu_result": chaitu_result,
                "feature_result": feature_result
            }, ensure_ascii=False)
        )]
    
    logger.info(f"[OK] 特征识别完成: {feature_result.get('message')}")
    
    # 返回完整结果
    result = {
        "status": "ok",
        "message": "CAD 处理和特征识别完成",
        "job_id": job_id,
        "chaitu": chaitu_result,
        "features": feature_result
    }
    
    logger.info(f"[COMPLETE] 所有处理完成!")
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

async def handle_cad_chaitu(arguments: dict) -> list[TextContent]:
    """单独的拆图功能"""
    if not CAD_AVAILABLE:
        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "message": "CAD 处理功能不可用，请安装 ezdxf 和 minio 依赖包"
            }, ensure_ascii=False)
        )]
    
    job_id = arguments.get("job_id")
    dwg_url = arguments.get("dwg_url")
    
    if not job_id:
        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "message": "job_id 参数必填"
            }, ensure_ascii=False)
        )]
    
    # 发布进度：拆图开始
    if progress_publisher:
        logger.info(f"[DEBUG] 准备发布拆图开始进度: job_id={job_id}")
        progress_publisher.publish_progress(
            job_id=job_id,
            stage=ProgressStage.CAD_SPLIT_STARTED,
            progress=ProgressPercent.CAD_SPLIT_STARTED,
            message="正在拆图...",
            details={"source": "mcp_service"}
        )
        logger.info(f"[SEND] 发布进度: 拆图开始 (job_id={job_id})")
    
    result = await chaitu_process(dwg_url, job_id)
    
    # 发布进度：拆图完成或失败
    if progress_publisher:
        if result.get("status") == "ok":
            data = result.get("data", {})
            total_count = data.get("total_count", 0)
            
            progress_publisher.publish_progress(
                job_id=job_id,
                stage=ProgressStage.CAD_SPLIT_COMPLETED,
                progress=ProgressPercent.CAD_SPLIT_COMPLETED,
                message=f"拆图完成，生成{total_count}个子图",
                details={
                    "source": "mcp_service",
                    "subgraph_count": total_count
                }
            )
            logger.info(f"[SEND] 发布进度: 拆图完成 (job_id={job_id}, 子图数={total_count})")
        else:
            progress_publisher.publish_progress(
                job_id=job_id,
                stage=ProgressStage.CAD_SPLIT_FAILED,
                progress=ProgressPercent.CAD_SPLIT_STARTED,
                message=f"拆图失败: {result.get('message', '未知错误')}",
                details={
                    "source": "mcp_service",
                    "error": result.get("message")
                }
            )
            logger.info(f"[SEND] 发布进度: 拆图失败 (job_id={job_id})")
    
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

async def handle_feature_recognition(arguments: dict) -> list[TextContent]:
    """单独的特征识别功能"""
    if not CAD_AVAILABLE:
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "message": "CAD 处理功能不可用，请安装 ezdxf 和 minio 依赖包"
            }, ensure_ascii=False)
        )]
    
    job_id = arguments.get("job_id")
    subgraph_id = arguments.get("subgraph_id")
    
    if not job_id:
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "message": "job_id 参数必填"
            }, ensure_ascii=False)
        )]
    
    # 调用脚本处理（只负责业务逻辑）
    result = batch_feature_recognition_process(job_id, subgraph_id)
    
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

# ============================================================================
# 价格工具处理函数
# ============================================================================

async def handle_price_tool(name: str, arguments: dict) -> list[TextContent]:
    """处理价格相关工具"""
    job_id = arguments.get("job_id")
    subgraph_ids = arguments.get("subgraph_ids", [])
    
    if not job_id:
        return [TextContent(
            type="text",
            text=json.dumps({"status": "error", "message": "job_id 参数必填"}, ensure_ascii=False)
        )]
    
    logger.info(f"[OK] 调用工具: {name}, job_id={job_id}, subgraph_ids={subgraph_ids}")
    
    # ========== 搜索工具路由 ==========
    if name == "search_base_itemcode":
        result = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
    elif name == "search_material":
        result = await material_search.search_by_job_id(job_id, subgraph_ids)
    elif name == "search_heat":
        result = await heat_search.search_by_job_id(job_id, subgraph_ids)
    elif name == "search_tooth_hole":
        result = await tooth_hole_search.search_by_job_id(job_id, subgraph_ids)
    elif name == "search_water_mill":
        result = await water_mill_search.search_by_job_id(job_id, subgraph_ids)
    elif name == "search_wire_base":
        result = await wire_base_search.search_by_job_id(job_id, subgraph_ids)
    elif name == "search_wire_special":
        result = await wire_special_search.search_by_job_id(job_id, subgraph_ids)
    elif name == "search_wire_standard":
        result = await wire_standard_search.search_by_job_id(job_id, subgraph_ids)
    elif name == "search_wire_total":
        result = await wire_total_search.search_by_job_id(job_id, subgraph_ids)
    elif name == "search_nc":
        result = await nc_search.search_by_job_id(job_id, subgraph_ids)
    elif name == "search_total":
        result = await total_search.search_by_job_id(job_id, subgraph_ids)
    elif name == "search_subgraphs_cost":
        result = await search.search_by_job_id(job_id, subgraph_ids)
    elif name == "search_density":
        result = await density_search.search_by_job_id(job_id, subgraph_ids)
    
    # ========== 计算工具路由 ==========
    elif name == "calculate_material_cost":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        material_data = await material_search.search_by_job_id(job_id, subgraph_ids)
        density_data = await density_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "material": material_data, "density": density_data}
        result = await price_material.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_heat_treatment_cost":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        heat_data = await heat_search.search_by_job_id(job_id, subgraph_ids)
        density_data = await density_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "heat": heat_data, "density": density_data}
        result = await price_heat.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_weight":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        density_data = await density_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "density": density_data}
        result = await price_weight.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_tooth_hole_cost":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        tooth_hole_data = await tooth_hole_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "tooth_hole": tooth_hole_data}
        result = await price_tooth_hole.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_wire_base_price":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        wire_base_data = await wire_base_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "wire_base": wire_base_data}
        result = await price_wire_base.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_wire_special_price":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        wire_special_data = await wire_special_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "wire_special": wire_special_data}
        result = await price_wire_special.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_wire_standard_price":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        wire_standard_data = await wire_standard_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "wire_standard": wire_standard_data}
        result = await price_wire_standard.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_add_auto_material_cost":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        material_data = await material_search.search_by_job_id(job_id, subgraph_ids)
        density_data = await density_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "material": material_data, "density": density_data}
        result = await price_add_auto_material.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_water_mill_bevel_cost":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        water_mill_data = await water_mill_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "water_mill": water_mill_data}
        result = await price_water_mill_bevel_cost.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_water_mill_chamfer_cost":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        water_mill_data = await water_mill_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "water_mill": water_mill_data}
        result = await price_water_mill_chamfer_cost.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_water_mill_component_price":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        water_mill_data = await water_mill_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "water_mill": water_mill_data}
        result = await price_water_mill_component.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_water_mill_hanging_table_price":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        water_mill_data = await water_mill_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "water_mill": water_mill_data}
        result = await price_water_mill_hanging_table.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_water_mill_high_cost":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        water_mill_data = await water_mill_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "water_mill": water_mill_data}
        result = await price_water_mill_high_cost.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_water_mill_long_strip_price":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        water_mill_data = await water_mill_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "water_mill": water_mill_data}
        result = await price_water_mill_long_strip.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_water_mill_oil_tank_cost":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        water_mill_data = await water_mill_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "water_mill": water_mill_data}
        result = await price_water_mill_oil_tank.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_water_mill_plate_price":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        water_mill_data = await water_mill_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "water_mill": water_mill_data}
        result = await price_water_mill_plate.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_water_mill_thread_ends_price":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        water_mill_data = await water_mill_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "water_mill": water_mill_data}
        result = await price_water_mill_thread_ends.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_water_mill_total_cost":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        total_data = await total_search.search_by_job_id(job_id, subgraph_ids)
        water_mill_data = await water_mill_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "total": total_data, "water_mill": water_mill_data}
        result = await price_water_mill_total.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_wire_total_cost":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        total_data = await total_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "total": total_data}
        result = await price_wire_total.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_nc_base_cost":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        nc_data = await nc_search.search_by_job_id(job_id, subgraph_ids)
        wire_base_data = await wire_base_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "nc": nc_data, "wire_base": wire_base_data}
        result = await price_nc_base.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_nc_time_cost":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        nc_data = await nc_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "nc": nc_data}
        result = await price_nc_time.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_nc_total_cost":
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        total_data = await total_search.search_by_job_id(job_id, subgraph_ids)
        nc_data = await nc_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data, "total": total_data, "nc": nc_data}
        result = await price_nc_total.calculate(search_data, job_id, subgraph_ids)
        
    elif name == "calculate_final_total_cost":
        # 如果subgraph_ids为空，则计算该job_id下的所有零件
        if not subgraph_ids:
            logger.info(f"[MCP] calculate_final_total_cost: job_id={job_id} (ALL parts)")
        else:
            logger.info(f"[MCP] calculate_final_total_cost: job_id={job_id}, subgraph_ids={subgraph_ids}")
        
        subgraphs_cost_data = await search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"subgraphs_cost": subgraphs_cost_data}
        result = await price_total.calculate(search_data, job_id, subgraph_ids)
        logger.info(f"[MCP] calculate_final_total_cost completed")
    
    elif name == "judgment_cleanup":
        # 数据清理和校验
        base_data = await base_itemcode_search.search_by_job_id(job_id, subgraph_ids)
        search_data = {"base_itemcode": base_data}
        logger.info(f"[MCP] judgment_cleanup: job_id={job_id}")
        result = await judgment.calculate(search_data, job_id, subgraph_ids)
        logger.info(f"[MCP] judgment_cleanup completed")
    
    elif name == "update_job_total_cost_only":
        # 只更新 jobs.total_cost，从所有子图汇总
        logger.info(f"[MCP] update_job_total_cost_only: job_id={job_id}")
        # 查询所有子图的 total_cost 并汇总
        from api_gateway.database import db
        query_sql = """
            SELECT COALESCE(SUM(total_cost), 0) as total_cost
            FROM subgraphs
            WHERE job_id = $1::uuid
        """
        row = await db.fetch_one(query_sql, job_id)
        total_cost = float(row["total_cost"]) if row else 0.0
        
        # 更新 jobs 表
        update_sql = """
            UPDATE jobs
            SET 
                total_cost = $2,
                updated_at = NOW()
            WHERE job_id = $1::uuid
        """
        await db.execute(update_sql, job_id, total_cost)
        
        result = {"status": "ok", "job_id": job_id, "total_cost": total_cost}
        logger.info(f"[MCP] update_job_total_cost_only completed: {total_cost:.2f}")
        
    else:
        return [TextContent(
            type="text",
            text=json.dumps({"status": "error", "message": f"未知工具: {name}"}, ensure_ascii=False)
        )]
    
    # 添加状态字段
    if "status" not in result:
        result["status"] = "ok"
    
    logger.info(f"[OK] 工具执行完成: {name}")
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, cls=DecimalEncoder))]

# ============================================================================
# HTTP 端点
# ============================================================================

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    HOST = os.getenv("CAD_PRICE_SEARCH_MCP_HOST", "0.0.0.0")
    PORT = int(os.getenv("CAD_PRICE_SEARCH_MCP_PORT", "8200"))
    
    logger.info("=" * 60)
    logger.info("CAD 和价格搜索 MCP 服务启动中...")
    logger.info("=" * 60)
    logger.info(f"地址: http://{HOST}:{PORT}")
    logger.info(f"调用端点: http://{HOST}:{PORT}/call_tool")
    if CAD_AVAILABLE:
        logger.info(f"包含工具: 3个CAD工具 + 12个搜索工具 + 23个计算工具 = 38个工具")
    else:
        logger.info(f"包含工具: 12个搜索工具 + 23个计算工具 = 35个工具")
        logger.info(f"注意: CAD 功能不可用（缺少依赖包）")
    logger.info("=" * 60)
    
    # 创建 SSE 传输层
    sse = SseServerTransport("/messages")
    
    # 健康检查端点
    async def health_check(request):
        return JSONResponse({
            "status": "healthy",
            "service": "cad-price-search-mcp",
            "port": PORT,
            "features": {
                "cad": CAD_AVAILABLE,
                "pricing": True
            },
            "tools": {
                "cad": 3 if CAD_AVAILABLE else 0,
                "search": 12,
                "calculate": 23,
                "total": (3 if CAD_AVAILABLE else 0) + 35
            }
        })
    
    # 直接调用工具的端点
    async def call_tool_http(request):
        try:
            body = await request.json()
            tool_name = body.get("tool_name")
            arguments = body.get("arguments", {})
            
            if not tool_name:
                return JSONResponse({"status": "error", "message": "缺少 tool_name 参数"}, status_code=400)
            
            logger.info(f"[HTTP] 调用工具: {tool_name}")
            
            # 调用 MCP 工具处理函数
            result_list = await call_tool(tool_name, arguments)
            
            # 解析结果
            if result_list and len(result_list) > 0:
                result_text = result_list[0].text
                result = json.loads(result_text)
            else:
                result = {"status": "error", "message": "工具未返回结果"}
            
            logger.info(f"[HTTP] 工具执行完成: {tool_name}")
            return JSONResponse(result)
        except Exception as e:
            import traceback
            logger.error(f"[HTTP] 工具执行失败: {tool_name}, error={e}")
            return JSONResponse({
                "status": "error",
                "message": str(e),
                "traceback": traceback.format_exc()
            }, status_code=500)
    
    # 创建 Starlette 应用
    starlette_app = Starlette(
        routes=[
            Route("/health", health_check),
            Route("/call_tool", call_tool_http, methods=["POST"]),
        ]
    )
    
    # 主应用（合并 SSE 和 HTTP 端点）
    async def main_app(scope, receive, send):
        path = scope.get("path", "")
        
        if path in ["/health", "/call_tool"]:
            await starlette_app(scope, receive, send)
        elif path.startswith("/messages") or path.startswith("/sse"):
            if scope.get("method") == "GET":
                async with sse.connect_sse(scope, receive, send) as streams:
                    read_stream, write_stream = streams
                    await mcp_server.run(read_stream, write_stream, mcp_server.create_initialization_options())
            else:
                await sse.handle_post_message(scope, receive, send)
        else:
            await send({"type": "http.response.start", "status": 404, "headers": [[b"content-type", b"text/plain"]]})
            await send({"type": "http.response.body", "body": b"Not Found"})
    
    uvicorn.run(main_app, host=HOST, port=PORT)
