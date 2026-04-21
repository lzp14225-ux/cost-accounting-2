"""
PricingAgent - 价格计算Agent

职责：
1. 并发调用 price-search-mcp 检索所有数据
2. 合并搜索结果
3. 并发调用 price-search-mcp 计算所有费用
4. 汇总总成本

设计原则：
- Agent 层面实现并发（asyncio.gather）
- 支持分批处理（避免大量子图时连接池耗尽）
- MCP 服务只负责单一工具执行
- 支持部分失败的优雅降级
"""
from typing import Dict, Any, List, Optional
import logging
from datetime import datetime
import asyncio
import os

from .base_agent import BaseAgent, OpResult

logger = logging.getLogger(__name__)

# 从环境变量读取批次大小配置
PRICING_BATCH_SIZE = int(os.getenv('PRICING_BATCH_SIZE', '50'))


class PricingAgent(BaseAgent):
    """
    价格计算Agent - Agent 层并发模式
    
    工作流程：
    1. 阶段1: 并发搜索所有数据（price-search-mcp）
    2. 阶段2: 并发计算所有费用（price-search-mcp）
    3. 阶段3: 成本明细检索（从 processing_cost_calculation_details 表读取）
    4. 阶段4: 线割总价计算（单价 × 数量，更新 subgraphs 表）
    5. 阶段5: 水磨总价计算（更新 subgraphs 表）
    6. 阶段6: 成本汇总检索（从 subgraphs 表读取各项成本）
    7. 阶段7: 最终总价计算（汇总所有成本项，更新 subgraphs 表的 total_cost 字段）
    8. 阶段8: 数据清理和校验（根据物料实际情况清理不应该存在的计算数据）
    """
    
    def __init__(self, price_search_mcp_client, progress_publisher=None):
        super().__init__("PricingAgent")
        if price_search_mcp_client is None:
            raise ValueError("price_search_mcp_client 不能为空")
        
        self.price_search_mcp = price_search_mcp_client
        self.progress_publisher = progress_publisher
    
    async def process(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理价格计算请求（供编排器调用）
        
        支持分批处理：
        - 子图数量 <= PRICING_BATCH_SIZE: 直接处理
        - 子图数量 > PRICING_BATCH_SIZE: 分批处理（避免连接池耗尽）
        
        工作流程：
        1. 并发搜索所有数据
        2. 并发计算所有费用
        3. 成本明细检索（从 processing_cost_calculation_details 表读取）
        4. 线割总价计算（单价 × 数量，更新 subgraphs 表）
        5. 水磨总价计算（更新 subgraphs 表）
        6. 成本汇总检索（从 subgraphs 表读取各项成本）
        7. 最终总价计算（汇总所有成本项，更新 subgraphs 表的 total_cost 字段）
        8. 数据清理和校验（根据物料实际情况清理不应该存在的计算数据）
        
        Args:
            context: {
                "job_id": str,                  # 任务ID（必填）
                "subgraph_ids": List[str]       # 子图ID列表（必填）
            }
        
        Returns:
            {
                "status": "ok",
                "message": "价格计算完成",
                "total_cost": 420.0,
                "breakdown": {...}
            }
        """
        import time  # 导入time模块用于性能监控
        
        job_id = context.get("job_id")
        subgraph_ids = context.get("subgraph_ids", [])
        
        if not job_id:
            return {
                "status": "error",
                "message": "缺少job_id参数",
                "error_code": "MISSING_JOB_ID"
            }
        
        if not subgraph_ids:
            return {
                "status": "error",
                "message": "缺少subgraph_ids参数",
                "error_code": "MISSING_SUBGRAPH_IDS"
            }
        
        self.logger.info(f"[价格计算] job_id={job_id}, 子图数量={len(subgraph_ids)}")
        
        # 判断是否需要分批处理
        if len(subgraph_ids) <= PRICING_BATCH_SIZE:
            # 子图数量少，直接处理
            self.logger.info(f"[价格计算] 子图数量 {len(subgraph_ids)} <= {PRICING_BATCH_SIZE}，直接处理")
            return await self._process_single_batch(job_id, subgraph_ids)
        else:
            # 子图数量多，分批处理
            self.logger.info(
                f"[价格计算] 子图数量 {len(subgraph_ids)} > {PRICING_BATCH_SIZE}，"
                f"启用分批处理（批次大小={PRICING_BATCH_SIZE}）"
            )
            return await self._process_multiple_batches(job_id, subgraph_ids)
    
    async def _process_single_batch(self, job_id: str, subgraph_ids: List[str], update_job_total: bool = True, publish_progress: bool = True) -> Dict[str, Any]:
        """
        处理单个批次（原有的处理逻辑）
        
        Args:
            job_id: 任务ID
            subgraph_ids: 子图ID列表
            update_job_total: 是否更新 jobs.total_cost（分批处理时只在最后更新）
            publish_progress: 是否发布进度通知（分批处理时只在最外层发布）
        
        Returns:
            处理结果
        """
        import time
        
        # 性能监控：记录各阶段耗时
        timings = {}
        total_start = time.time()
        
        try:
            # 发布进度：价格计算开始（仅在 publish_progress=True 时发送）
            if self.progress_publisher and publish_progress:
                from shared.progress_stages import ProgressStage, ProgressPercent
                self.progress_publisher.publish_progress(
                    job_id=job_id,
                    stage=ProgressStage.PRICING_STARTED,
                    progress=ProgressPercent.PRICING_STARTED,
                    message="正在计算价格...",
                    details={"source": "pricing_agent", "subgraph_count": len(subgraph_ids)}
                )
                self.logger.info(f"[SEND] 发布进度: 价格计算开始 (job_id={job_id})")
            
            # 阶段1: 并发搜索所有数据
            stage_start = time.time()
            search_data = await self._concurrent_search(job_id, subgraph_ids)
            timings["stage1_concurrent_search"] = time.time() - stage_start
            self.logger.info(f"[性能] 阶段1-并发搜索: {timings['stage1_concurrent_search']*1000:.0f}ms")
            
            # 阶段2: 并发计算所有费用
            stage_start = time.time()
            calc_results = await self._concurrent_calculate(search_data, subgraph_ids)
            timings["stage2_concurrent_calculate"] = time.time() - stage_start
            self.logger.info(f"[性能] 阶段2-并发计算: {timings['stage2_concurrent_calculate']*1000:.0f}ms")
            
            # 阶段3: 汇总搜索（从 processing_cost_calculation_details 表读取所有计算结果）
            stage_start = time.time()
            self.logger.info(f"[汇总搜索] 开始")
            total_search_result = await self.price_search_mcp.call_tool(
                "unified-mcp",
                "search_total",
                {"job_id": job_id, "subgraph_ids": subgraph_ids}
            )
            
            if total_search_result.get("status") == "error":
                self.logger.error(f"[汇总搜索] 失败: {total_search_result.get('message')}")
                return {
                    "status": "error",
                    "message": f"汇总搜索失败: {total_search_result.get('message')}",
                    "error_code": "TOTAL_SEARCH_ERROR"
                }
            timings["stage3_total_search"] = time.time() - stage_start
            self.logger.info(f"[汇总搜索] 完成")
            self.logger.info(f"[性能] 阶段3-汇总搜索: {timings['stage3_total_search']*1000:.0f}ms")
            
            # 阶段4-6: 并发执行（优化性能）
            stage_start = time.time()
            self.logger.info(f"[并发执行] 阶段4-6开始")
            stage_4_6_tasks = [
                # 阶段4: 线割总价计算
                self.price_search_mcp.call_tool(
                    "unified-mcp",
                    "calculate_wire_total_cost",
                    {"job_id": job_id, "subgraph_ids": subgraph_ids}
                ),
                # 阶段5: 水磨总价计算
                self.price_search_mcp.call_tool(
                    "unified-mcp",
                    "calculate_water_mill_total_cost",
                    {"job_id": job_id, "subgraph_ids": subgraph_ids}
                ),
                # 阶段6: 成本汇总检索（独立查询，可以并发）
                self.price_search_mcp.call_tool(
                    "unified-mcp",
                    "search_subgraphs_cost",
                    {"job_id": job_id, "subgraph_ids": subgraph_ids}
                )
            ]
            
            # 并发执行阶段4-6
            stage_4_6_results = await asyncio.gather(*stage_4_6_tasks, return_exceptions=True)
            timings["stage4_6_concurrent"] = time.time() - stage_start
            self.logger.info(f"[性能] 阶段4-6-并发执行: {timings['stage4_6_concurrent']*1000:.0f}ms")
            
            # 检查结果
            wire_total_calc_result = stage_4_6_results[0]
            water_mill_total_result = stage_4_6_results[1]
            subgraphs_cost_result = stage_4_6_results[2]
            
            # 处理异常
            for i, (result, stage_name) in enumerate([
                (wire_total_calc_result, "线割总价计算"),
                (water_mill_total_result, "水磨总价计算"),
                (subgraphs_cost_result, "成本汇总检索")
            ]):
                if isinstance(result, Exception):
                    self.logger.error(f"[{stage_name}] 异常: {result}")
                    return {
                        "status": "error",
                        "message": f"{stage_name}失败: {str(result)}",
                        "error_code": f"STAGE_{i+4}_ERROR"
                    }
                elif result.get("status") == "error":
                    self.logger.error(f"[{stage_name}] 失败: {result.get('message')}")
                    return {
                        "status": "error",
                        "message": f"{stage_name}失败: {result.get('message')}",
                        "error_code": f"STAGE_{i+4}_ERROR"
                    }
            
            self.logger.info(f"[并发执行] 阶段4-6完成")
            
            # 阶段7: 数据清理和校验（judgment.py）
            stage_start = time.time()
            self.logger.info(f"[数据清理和校验] 开始")
            judgment_result = await self.price_search_mcp.call_tool(
                "unified-mcp",
                "judgment_cleanup",
                {
                    "job_id": job_id,
                    "subgraph_ids": subgraph_ids
                }
            )
            
            if judgment_result.get("status") == "error":
                self.logger.error(f"[数据清理和校验] 失败: {judgment_result.get('message')}")
                # 数据清理失败不影响整体流程，只记录警告
                self.logger.warning(f"[数据清理和校验] 失败但继续执行: {judgment_result.get('message')}")
            else:
                self.logger.info(f"[数据清理和校验] 完成")
            timings["stage7_judgment"] = time.time() - stage_start
            self.logger.info(f"[性能] 阶段7-数据清理: {timings['stage7_judgment']*1000:.0f}ms")
            
            # 阶段8: 最终总价计算（依赖阶段4、5、6，在数据清理后执行）
            stage_start = time.time()
            self.logger.info(f"[最终总价计算] 开始")
            final_total_result = await self.price_search_mcp.call_tool(
                "unified-mcp",
                "calculate_final_total_cost",
                {
                    "job_id": job_id, 
                    "subgraph_ids": subgraph_ids,
                    "update_job_total": update_job_total  # 根据参数决定是否更新 jobs.total_cost
                }
            )
            
            if final_total_result.get("status") == "error":
                self.logger.error(f"[最终总价计算] 失败: {final_total_result.get('message')}")
                return {
                    "status": "error",
                    "message": f"最终总价计算失败: {final_total_result.get('message')}",
                    "error_code": "FINAL_TOTAL_CALC_ERROR"
                }
            timings["stage8_final_total"] = time.time() - stage_start
            self.logger.info(f"[最终总价计算] 完成（已更新 jobs.total_cost）")
            self.logger.info(f"[性能] 阶段8-最终总价: {timings['stage8_final_total']*1000:.0f}ms")
            
            # 阶段9: 线割工时计算（展示字段，最后执行）
            stage_start = time.time()
            self.logger.info(f"[线割工时计算] 开始")
            wire_time_result = await self.price_search_mcp.call_tool(
                "unified-mcp",
                "calculate_wire_time",
                {
                    "job_id": job_id,
                    "subgraph_ids": subgraph_ids
                }
            )
            if wire_time_result.get("status") == "error":
                self.logger.warning(f"[线割工时计算] 失败但继续执行: {wire_time_result.get('message')}")
            else:
                self.logger.info(f"[线割工时计算] 完成")
            timings["stage9_wire_time"] = time.time() - stage_start
            self.logger.info(f"[性能] 阶段9-线割工时: {timings['stage9_wire_time']*1000:.0f}ms")

            # 阶段10: 汇总结果
            stage_start = time.time()
            final_result = self._aggregate_results(calc_results)
            
            # 必须使用数据库中的实际 total_cost（从 final_total_result 获取）
            # 注意：price_total.py 返回的字段名是 job_total_cost
            if final_total_result.get("job_total_cost") is not None:
                final_result["total_cost"] = final_total_result.get("job_total_cost")
                self.logger.info(f"[汇总结果] 使用数据库中的实际 total_cost: {final_result['total_cost']:.2f}")
            elif final_total_result.get("total_cost") is not None:
                # 兼容旧版本字段名
                final_result["total_cost"] = final_total_result.get("total_cost")
                self.logger.info(f"[汇总结果] 使用数据库中的实际 total_cost: {final_result['total_cost']:.2f}")
            else:
                # 如果没有从数据库获取到 total_cost（不应该发生），设置为 0
                final_result["total_cost"] = 0.0
                self.logger.warning(f"[汇总结果] 未从数据库获取到 total_cost，设置为 0")
            
            timings["stage10_aggregate"] = time.time() - stage_start
            self.logger.info(f"[性能] 阶段10-汇总结果: {timings['stage10_aggregate']*1000:.0f}ms")
            
            # 计算总耗时
            total_duration = time.time() - total_start
            timings["total"] = total_duration
            
            # 输出性能汇总（避免除零错误）
            if total_duration > 0:
                self.logger.info("=" * 80)
                self.logger.info("[性能汇总] 价格计算各阶段耗时:")
                self.logger.info(f"  阶段1-并发搜索:     {timings['stage1_concurrent_search']*1000:6.0f}ms ({timings['stage1_concurrent_search']/total_duration*100:5.1f}%)")
                self.logger.info(f"  阶段2-并发计算:     {timings['stage2_concurrent_calculate']*1000:6.0f}ms ({timings['stage2_concurrent_calculate']/total_duration*100:5.1f}%)")
                self.logger.info(f"  阶段3-汇总搜索:     {timings['stage3_total_search']*1000:6.0f}ms ({timings['stage3_total_search']/total_duration*100:5.1f}%)")
                self.logger.info(f"  阶段4-6-并发执行:   {timings['stage4_6_concurrent']*1000:6.0f}ms ({timings['stage4_6_concurrent']/total_duration*100:5.1f}%)")
                self.logger.info(f"  阶段7-数据清理:     {timings['stage7_judgment']*1000:6.0f}ms ({timings['stage7_judgment']/total_duration*100:5.1f}%)")
                self.logger.info(f"  阶段8-最终总价:     {timings['stage8_final_total']*1000:6.0f}ms ({timings['stage8_final_total']/total_duration*100:5.1f}%)")
                self.logger.info(f"  阶段9-线割工时:     {timings['stage9_wire_time']*1000:6.0f}ms ({timings['stage9_wire_time']/total_duration*100:5.1f}%)")
                self.logger.info(f"  阶段10-汇总结果:    {timings['stage10_aggregate']*1000:6.0f}ms ({timings['stage10_aggregate']/total_duration*100:5.1f}%)")
                self.logger.info(f"  总耗时:            {total_duration*1000:6.0f}ms")
                self.logger.info("=" * 80)
            
            # 发布进度：价格计算完成（仅在 publish_progress=True 时发送）
            if self.progress_publisher and publish_progress and final_result.get("status") in ["ok", "partial"]:
                total_cost = final_result.get("total_cost", 0)
                total_cost_display = f"{float(total_cost):.2f}"
                currency = "CNY"
                
                self.progress_publisher.publish_progress(
                    job_id=job_id,
                    stage=ProgressStage.PRICING_COMPLETED,
                    progress=ProgressPercent.PRICING_COMPLETED,
                    message=f"价格计算完成，总成本: {total_cost_display} {currency}",
                    details={
                        "source": "pricing_agent",
                        "total_cost": total_cost,
                        "currency": currency,
                        "breakdown": final_result.get("breakdown", {})
                    }
                )
                self.logger.info(f"[SEND] 发布进度: 价格计算完成 (job_id={job_id}, 总成本={total_cost})")
            elif self.progress_publisher and publish_progress:
                # 价格计算失败
                self.progress_publisher.publish_progress(
                    job_id=job_id,
                    stage=ProgressStage.PRICING_FAILED,
                    progress=ProgressPercent.PRICING_STARTED,
                    message=f"价格计算失败: {final_result.get('message', '未知错误')}",
                    details={
                        "source": "pricing_agent",
                        "error": final_result.get("message"),
                        "errors": final_result.get("errors")
                    }
                )
                self.logger.info(f"[SEND] 发布进度: 价格计算失败 (job_id={job_id})")
            
            self.logger.info(
                f"[价格计算] 完成，总成本={final_result.get('total_cost', 0):.2f}"
            )
            
            return final_result
            
        except Exception as e:
            self.logger.error(f"[价格计算] 失败: {e}", exc_info=True)
            
            # 发布进度：价格计算失败（仅在 publish_progress=True 时发送）
            if self.progress_publisher and publish_progress:
                from shared.progress_stages import ProgressStage, ProgressPercent
                self.progress_publisher.publish_progress(
                    job_id=job_id,
                    stage=ProgressStage.PRICING_FAILED,
                    progress=ProgressPercent.PRICING_STARTED,
                    message=f"价格计算失败: {str(e)}",
                    details={"source": "pricing_agent", "error": str(e)}
                )
                self.logger.info(f"[SEND] 发布进度: 价格计算失败 (job_id={job_id})")
            
            return {
                "status": "error",
                "message": f"价格计算失败: {str(e)}",
                "error_code": "PRICING_ERROR"
            }
    

    
    async def _concurrent_search(self, job_id: str, subgraph_ids: List[str]) -> Dict[str, Any]:
        """
        阶段1: 并发调用所有搜索工具
        
        Args:
            job_id: 任务ID
            subgraph_ids: 子图ID列表
        
        Returns:
            合并后的搜索数据
        """
        self.logger.info(f"[并发搜索] 开始，子图数量={len(subgraph_ids)}")
        
        # 并发调用所有搜索工具
        search_tasks = [
            self.price_search_mcp.call_tool("unified-mcp", "search_base_itemcode", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "search_material", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "search_density", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "search_heat", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "search_tooth_hole", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "search_water_mill", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "search_wire_base", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "search_wire_special", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "search_wire_standard", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "search_nc", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
        ]
        
        # 并发执行，捕获异常
        results = await asyncio.gather(*search_tasks, return_exceptions=True)
        
        # 合并结果
        merged = self._merge_search_results(results, job_id)
        
        self.logger.info(f"[并发搜索] 完成")
        return merged
    
    def _merge_search_results(self, results: List, job_id: str) -> Dict[str, Any]:
        """
        合并搜索结果
        
        Args:
            results: 搜索结果列表
            job_id: 任务ID
        
        Returns:
            合并后的数据
        """
        merged = {
            "job_id": job_id,
            "base_itemcode": {},
            "material": {},
            "density": {},
            "heat": {},
            "tooth_hole": {},
            "water_mill": {},
            "wire_base": {},
            "wire_special": {},
            "wire_standard": {},
            "nc": {}
        }
        
        tool_names = [
            "base_itemcode", "material", "density", "heat", "tooth_hole", "water_mill",
            "wire_base", "wire_special", "wire_standard", "nc"
        ]
        
        for i, result in enumerate(results):
            tool_name = tool_names[i]
            
            if isinstance(result, Exception):
                self.logger.error(f"[搜索失败] {tool_name}: {result}")
                # 非关键数据失败，记录警告但继续
                if tool_name not in ["base_itemcode", "material"]:
                    self.logger.warning(f"[搜索失败] 非关键数据 {tool_name} 失败，使用空数据")
                    merged[tool_name] = {"status": "error", "data_type": tool_name}
                else:
                    # 关键数据失败，抛出异常
                    raise ValueError(f"关键数据 {tool_name} 搜索失败: {result}")
            else:
                if result.get("status") == "error":
                    self.logger.warning(f"[搜索失败] {tool_name}: {result.get('message')}")
                    # 非关键数据失败，使用空数据
                    if tool_name not in ["base_itemcode", "material"]:
                        merged[tool_name] = result
                    else:
                        raise ValueError(f"关键数据 {tool_name} 搜索失败: {result.get('message')}")
                else:
                    merged[tool_name] = result
        
        return merged
    
    async def _concurrent_calculate(self, search_data: Dict, subgraph_ids: List[str] = None) -> List[Dict]:
        """
        阶段2: 并发调用所有计算工具
        
        Args:
            search_data: 搜索结果
            subgraph_ids: 可选，subgraph_id数组
        
        Returns:
            计算结果列表
        """
        self.logger.info(f"[并发计算] 开始")
        
        job_id = search_data.get("job_id")
        
        # 并发调用所有计算工具（使用 MCP 服务实际注册的工具名称）
        calc_tasks = [
            # 基础计算
            self.price_search_mcp.call_tool("unified-mcp", "calculate_material_cost", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "calculate_heat_treatment_cost", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "calculate_weight", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            # 牙孔计算
            self.price_search_mcp.call_tool("unified-mcp", "calculate_tooth_hole_cost", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            # 线割计算
            self.price_search_mcp.call_tool("unified-mcp", "calculate_wire_base_price", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "calculate_wire_special_price", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "calculate_wire_standard_price", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "calculate_add_auto_material_cost", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            # NC计算（3个）
            self.price_search_mcp.call_tool("unified-mcp", "calculate_nc_base_cost", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "calculate_nc_time_cost", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            # nc_total 依赖 nc_base / nc_time 的落库结果，这里延后执行
            
            # 水磨计算（9个）
            self.price_search_mcp.call_tool("unified-mcp", "calculate_water_mill_bevel_cost", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "calculate_water_mill_chamfer_cost", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "calculate_water_mill_component_price", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "calculate_water_mill_hanging_table_price", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "calculate_water_mill_high_cost", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "calculate_water_mill_long_strip_price", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "calculate_water_mill_oil_tank_cost", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "calculate_water_mill_plate_price", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
            
            self.price_search_mcp.call_tool("unified-mcp", "calculate_water_mill_thread_ends_price", 
                {"job_id": job_id, "subgraph_ids": subgraph_ids}),
        ]
        
        # 并发执行，捕获异常
        results = await asyncio.gather(*calc_tasks, return_exceptions=True)
        
        self.logger.info(f"[并发计算] 完成")
        self.logger.info("[并发计算] NC base 和 NC time 已完成，开始执行 NC total")
        nc_total_result = await self.price_search_mcp.call_tool(
            "unified-mcp",
            "calculate_nc_total_cost",
            {"job_id": job_id, "subgraph_ids": subgraph_ids}
        )
        results.insert(10, nc_total_result)
        return results
    
    def _aggregate_results(self, calc_results: List) -> Dict[str, Any]:
        """
        汇总所有计算结果（只汇总 breakdown，不计算 total_cost）
        
        注意：total_cost 应该从数据库读取，不应该从 breakdown 累加计算
        
        Args:
            calc_results: 计算结果列表
        
        Returns:
            汇总结果（不包含 total_cost，需要从数据库获取）
        """
        breakdown = {}
        errors = []
        success_count = 0
        failed_count = 0
        
        calculator_names = [
            "material_cost", "heat_treatment_cost", "weight", "tooth_hole_cost",
            "wire_base_price", "wire_special_price", "wire_standard_price",
            "add_auto_material_cost",
            "nc_base_cost", "nc_time_cost", "nc_total_cost",
            "water_mill_bevel_cost", "water_mill_chamfer_cost", "water_mill_component_price",
            "water_mill_hanging_table_price", "water_mill_high_cost", "water_mill_long_strip_price",
            "water_mill_oil_tank_cost", "water_mill_plate_price", "water_mill_thread_ends_price"
        ]
        
        # 每个计算器对应的成本字段名
        cost_field_map = {
            "material_cost": "material_cost",
            "heat_treatment_cost": "heat_treatment_cost",
            "weight": "weight",  # weight 不是成本，跳过
            "tooth_hole_cost": "tooth_hole_cost",
            "wire_base_price": "wire_base_price",
            "wire_special_price": "wire_special_price",
            "wire_standard_price": "wire_standard_price",
            "add_auto_material_cost": "material_additional_cost",
            "nc_base_cost": "nc_base_cost",
            "nc_time_cost": "nc_time_cost",
            "nc_total_cost": "nc_total_cost",
            "water_mill_bevel_cost": "bevel_cost",
            "water_mill_chamfer_cost": "chamfer_cost",
            "water_mill_component_price": "component_cost",
            "water_mill_hanging_table_price": "hanging_table_cost",
            "water_mill_high_cost": "high_cost",
            "water_mill_long_strip_price": "long_strip_cost",
            "water_mill_oil_tank_cost": "oil_tank_cost",
            "water_mill_plate_price": "plate_cost",
            "water_mill_thread_ends_price": "thread_ends_cost"
        }
        
        for i, result in enumerate(calc_results):
            calculator = calculator_names[i]
            cost_field = cost_field_map.get(calculator)
            
            if isinstance(result, Exception):
                self.logger.error(f"[计算失败] {calculator}: {result}")
                errors.append(f"{calculator}: {str(result)}")
                failed_count += 1
                breakdown[calculator] = {"status": "error", "cost": 0.0}
            else:
                if result.get("status") in ["ok", "partial"]:
                    # 提取成本数据
                    results_list = result.get("results", [])
                    
                    # weight 和 tooth_hole_cost 计算器不计入总成本
                    if calculator in ["weight", "tooth_hole_cost"]:
                        breakdown[calculator] = {
                            "status": result.get("status"),
                            "cost": 0.0,
                            "count": len([r for r in results_list if not r.get("error")])
                        }
                        success_count += 1
                        continue
                    
                    # 从结果中提取对应的成本字段（仅用于 breakdown 展示）
                    calculator_cost = sum(
                        float(r.get(cost_field, 0) or 0)
                        for r in results_list
                        if not r.get("error")  # 没有错误的记录
                    )
                    
                    breakdown[calculator] = {
                        "status": result.get("status"),
                        "cost": round(calculator_cost, 2),
                        "count": len([r for r in results_list if not r.get("error")])
                    }
                    
                    success_count += 1
                    
                    self.logger.info(
                        f"[汇总] {calculator}: cost={calculator_cost:.2f}, "
                        f"count={breakdown[calculator]['count']}"
                    )
                else:
                    self.logger.warning(f"[计算失败] {calculator}: {result.get('message')}")
                    errors.append(f"{calculator}: {result.get('message')}")
                    failed_count += 1
                    breakdown[calculator] = {"status": "error", "cost": 0.0}
        
        status = "ok" if failed_count == 0 else ("partial" if success_count > 0 else "error")
        
        self.logger.info(f"[汇总完成] 成功={success_count}, 失败={failed_count}")
        self.logger.info(f"[汇总完成] 注意：total_cost 将从数据库获取，不从 breakdown 累加")
        
        return {
            "status": status,
            "message": f"价格计算完成: 成功{success_count}个, 失败{failed_count}个",
            # 不返回 total_cost，由调用方从数据库获取
            "breakdown": breakdown,
            "errors": errors if errors else None
        }
    
    async def calculate_batch(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        批量重新计算价格（复用 process 方法）
        
        Args:
            context: {
                "job_id": str,
                "subgraph_ids": List[str]
            }
        
        Returns:
            计算结果
        """
        # 直接复用 process 方法
        return await self.process(context)
    
    async def _process_multiple_batches(self, job_id: str, subgraph_ids: List[str]) -> Dict[str, Any]:
        """
        分批处理大量子图
        
        Args:
            job_id: 任务ID
            subgraph_ids: 子图ID列表
        
        Returns:
            处理结果
        """
        import time
        
        total_start = time.time()
        total_batches = (len(subgraph_ids) + PRICING_BATCH_SIZE - 1) // PRICING_BATCH_SIZE
        
        self.logger.info(
            f"[分批处理] 开始，总子图数={len(subgraph_ids)}, "
            f"批次大小={PRICING_BATCH_SIZE}, 总批次数={total_batches}"
        )
        
        try:
            # 发布进度：价格计算开始（只推送1次）
            if self.progress_publisher:
                from shared.progress_stages import ProgressStage, ProgressPercent
                self.progress_publisher.publish_progress(
                    job_id=job_id,
                    stage=ProgressStage.PRICING_STARTED,
                    progress=ProgressPercent.PRICING_STARTED,
                    message=f"正在计算价格（共{len(subgraph_ids)}个子图）...",
                    details={
                        "source": "pricing_agent",
                        "subgraph_count": len(subgraph_ids),
                        "batch_size": PRICING_BATCH_SIZE,
                        "total_batches": total_batches
                    }
                )
            
            # 分批处理（中间不推送进度到 Redis）
            all_batch_results = []
            for i in range(0, len(subgraph_ids), PRICING_BATCH_SIZE):
                batch = subgraph_ids[i:i+PRICING_BATCH_SIZE]
                batch_num = i // PRICING_BATCH_SIZE + 1
                
                self.logger.info(
                    f"[分批处理] 处理批次 {batch_num}/{total_batches}，"
                    f"子图数量: {len(batch)}"
                )
                
                # 处理当前批次（分批处理时不更新 jobs.total_cost，也不发布进度）
                batch_start = time.time()
                # 修改参数，告诉 calculate_final_total_cost 不要更新 jobs.total_cost
                # 同时设置 publish_progress=False，避免每个批次都发送进度通知
                batch_result = await self._process_single_batch(job_id, batch, update_job_total=False, publish_progress=False)
                batch_time = time.time() - batch_start
                
                if batch_result.get("status") == "error":
                    self.logger.error(
                        f"[分批处理] 批次 {batch_num} 失败: {batch_result.get('message')}"
                    )
                    # 批次失败，返回错误
                    return batch_result
                
                all_batch_results.append(batch_result)
                
                self.logger.info(
                    f"[分批处理] 批次 {batch_num}/{total_batches} 完成，"
                    f"耗时: {batch_time:.2f}s"
                )
            
            # 合并所有批次的结果
            final_result = self._merge_batch_results(all_batch_results, job_id)
            
            # 所有批次完成后，统一更新 jobs.total_cost
            self.logger.info(f"[分批处理] 所有批次完成，开始更新 jobs.total_cost")
            update_result = await self.price_search_mcp.call_tool(
                "unified-mcp",
                "update_job_total_cost_only",
                {"job_id": job_id}
            )
            
            if update_result.get("status") == "ok":
                final_result["total_cost"] = update_result.get("total_cost", 0)
                self.logger.info(f"[分批处理] jobs.total_cost 更新完成: {final_result['total_cost']:.2f}")
            else:
                self.logger.warning(f"[分批处理] jobs.total_cost 更新失败: {update_result.get('message')}")
            
            total_duration = time.time() - total_start
            self.logger.info(
                f"[分批处理] 全部完成，总耗时: {total_duration:.2f}s, "
                f"平均每批: {total_duration/total_batches:.2f}s"
            )
            
            # 发布进度：价格计算完成（只推送1次）
            if self.progress_publisher and final_result.get("status") in ["ok", "partial"]:
                total_cost = final_result.get("total_cost", 0)
                total_cost_display = f"{float(total_cost):.2f}"
                currency = "CNY"
                
                self.progress_publisher.publish_progress(
                    job_id=job_id,
                    stage=ProgressStage.PRICING_COMPLETED,
                    progress=ProgressPercent.PRICING_COMPLETED,
                    message=f"价格计算完成，总成本: {total_cost_display} {currency}",
                    details={
                        "source": "pricing_agent",
                        "total_cost": total_cost,
                        "currency": currency,
                        "subgraph_count": len(subgraph_ids),
                        "total_batches": total_batches,
                        "total_duration": total_duration
                    }
                )
            
            return final_result
            
        except Exception as e:
            self.logger.error(f"[分批处理] 失败: {e}", exc_info=True)
            
            # 发布进度：价格计算失败
            if self.progress_publisher:
                from shared.progress_stages import ProgressStage, ProgressPercent
                self.progress_publisher.publish_progress(
                    job_id=job_id,
                    stage=ProgressStage.PRICING_FAILED,
                    progress=ProgressPercent.PRICING_STARTED,
                    message=f"价格计算失败: {str(e)}",
                    details={"source": "pricing_agent", "error": str(e)}
                )
            
            return {
                "status": "error",
                "message": f"分批处理失败: {str(e)}",
                "error_code": "BATCH_PROCESSING_ERROR"
            }
    
    def _merge_batch_results(self, batch_results: List[Dict], job_id: str) -> Dict[str, Any]:
        """
        合并多个批次的结果（不计算 total_cost，由调用方从数据库获取）
        
        Args:
            batch_results: 批次结果列表
            job_id: 任务ID
        
        Returns:
            合并后的结果（不包含 total_cost）
        """
        # 合并 breakdown（累加各项成本）
        merged_breakdown = {}
        for result in batch_results:
            breakdown = result.get("breakdown", {})
            for key, value in breakdown.items():
                if key not in merged_breakdown:
                    merged_breakdown[key] = {
                        "status": value.get("status", "ok"),
                        "cost": 0.0,
                        "count": 0
                    }
                merged_breakdown[key]["cost"] += value.get("cost", 0)
                merged_breakdown[key]["count"] += value.get("count", 0)
        
        # 合并错误信息
        all_errors = []
        for result in batch_results:
            errors = result.get("errors")
            if errors:
                all_errors.extend(errors)
        
        # 判断整体状态
        statuses = [result.get("status") for result in batch_results]
        if all(s == "ok" for s in statuses):
            status = "ok"
        elif any(s == "ok" or s == "partial" for s in statuses):
            status = "partial"
        else:
            status = "error"
        
        self.logger.info(
            f"[合并结果] 批次数={len(batch_results)}, 状态={status}"
        )
        self.logger.info(f"[合并结果] 注意：total_cost 将从数据库获取，不从批次累加")
        
        return {
            "status": status,
            "message": f"价格计算完成（分{len(batch_results)}批处理）",
            # 不返回 total_cost，由调用方从数据库获取
            "breakdown": merged_breakdown,
            "errors": all_errors if all_errors else None,
            "batch_count": len(batch_results)
        }


