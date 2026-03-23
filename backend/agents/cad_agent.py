"""
CADAgent - CAD拆图与特征识别Agent (MCP模式)

职责：
1. 通过 MCP 客户端调用 MCP 服务
2. MCP 服务调用底层工具（拆图/特征识别脚本）
3. 支持并发处理多个子图（并发数可通过环境变量配置）
4. 特征识别完成后自动匹配工艺规则

调用链路：
CAD Agent → MCP Client → MCP Service (cad-price-search-mcp) → 底层工具

并发控制：
- 并发数：从环境变量 FEATURE_RECOGNITION_MAX_CONCURRENT 读取（默认25）
- 连接池：从环境变量 MCP_CLIENT_POOL_SIZE 读取（默认30）
- 自适应：从环境变量 FEATURE_RECOGNITION_ADAPTIVE_CONCURRENCY 控制
"""

from typing import Dict, Any, List, Optional
import logging
import asyncio
import os
from dataclasses import dataclass
from datetime import datetime

# 导入工艺规则匹配器
from scripts.process_rule_matcher import match_and_update_process_rules

logger = logging.getLogger(__name__)


@dataclass
class OpResult:
    """操作结果"""
    status: str  # "ok", "warning", "failed", "error"
    message: str
    data: Optional[Dict[str, Any]] = None


class BaseAgent:
    """Agent基类"""
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"Agent.{name}")
    
    async def process(self, context: Dict[str, Any]) -> OpResult:
        """处理请求 - 子类需要实现"""
        raise NotImplementedError


class CADAgent(BaseAgent):
    """
    CAD拆图与特征识别Agent (MCP模式)
    
    通过 MCP 客户端调用 MCP 服务：
    - MCP 服务名称: cad-price-search-mcp
    - 调用链路: CAD Agent → MCP Client → MCP Service → 底层工具（拆图/特征识别脚本）
    
    可用工具：
    - cad_chaitu: CAD 拆图
    - feature_recognition: 特征识别
    - process_cad_and_features: 完整流程（拆图 + 特征识别）
    
    使用示例：
        # 创建 MCP 客户端
        mcp_client = MCPClient(base_url="http://localhost:8200")
        
        # 创建 CAD Agent
        agent = CADAgent(mcp_client=mcp_client, progress_publisher=progress_publisher)
        
        # 调用拆图
        result = await agent.split({"job_id": "xxx"})
        
        # 调用特征识别
        result = await agent.recognize_features({"job_id": "xxx"})
    """
    
    def __init__(self, 
                 mcp_client,  # MCP 客户端（必填）
                 progress_publisher=None):  # 进度发布器（可选）
        super().__init__("CADAgent")
        
        if not mcp_client:
            raise ValueError("mcp_client 参数必填，CAD Agent 只支持 MCP 模式")
        
        self.mcp_client = mcp_client
        self.progress_publisher = progress_publisher
        
        logger.info("CAD Agent 初始化完成 (MCP 模式)")
        
    async def process(self, context: Dict[str, Any]) -> OpResult:
        """
        处理CAD拆图和特征识别请求（通过 MCP 服务）
        
        Args:
            context: 包含以下字段的字典
                - job_id: 任务ID（必填）
                - dwg_url: DWG文件URL（可选，如果不提供则从数据库查询）
                
        Returns:
            OpResult: 操作结果
        """
        job_id = context.get("job_id")
        dwg_url = context.get("dwg_url") or context.get("dwg_file_path")  # 兼容旧参数名
        
        if not job_id:
            return OpResult(
                status="failed",
                message="缺少job_id参数"
            )
        
        self.logger.info(f"开始处理CAD文件 (MCP模式): job_id={job_id}, dwg_url={dwg_url or '从数据库查询'}")
        
        try:
            return await self._process_mcp(context)
        except Exception as e:
            self.logger.error(f"处理失败: {e}", exc_info=True)
            return OpResult(
                status="error",
                message=f"处理失败: {str(e)}"
            )
    
    async def split(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        拆图方法（供编排器调用）
        
        Args:
            context: {"job_id": "xxx", "dwg_url": "xxx"(可选)}
        
        Returns:
            {"status": "ok", "message": "...", "summary": {"subgraph_count": N}}
        """
        job_id = context.get("job_id")
        if not job_id:
            return {"status": "error", "message": "缺少 job_id", "error_code": "MISSING_JOB_ID"}
        
        try:
            self.logger.info(f"[MCP模式] 调用 cad_chaitu 工具")
            
            # 构造参数
            arguments = {"job_id": job_id}
            dwg_url = context.get("dwg_url") or context.get("dwg_file_path")
            if dwg_url:
                arguments["dwg_url"] = dwg_url
            
            # 调用 MCP 服务
            result = await self.mcp_client.call_tool(
                "cad-price-search-mcp",
                "cad_chaitu",
                arguments
            )
            
            if result.get("status") != "ok":
                return {
                    "status": "error",
                    "message": f"拆图失败: {result.get('message', '未知错误')}",
                    "error_code": "CHAITU_FAILED"
                }
            
            # 提取子图数量
            data = result.get("data", {})
            subgraph_count = data.get("total_count", 0)
            
            return {
                "status": "ok",
                "message": f"成功拆分 {subgraph_count} 个子图",
                "summary": {"subgraph_count": subgraph_count}
            }
                
        except Exception as e:
            self.logger.error(f"拆图失败: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"拆图失败: {str(e)}",
                "error_code": "SPLIT_ERROR"
            }
    
    async def recognize_features(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        特征识别方法（供编排器调用）
        
        执行流程：
        1. 查询所有子图
        2. 并发调用 MCP 服务处理每个子图（Agent 层并发）
        3. Agent 层负责写入 Redis 进度（粗粒度）
        4. 特征识别完成后，立即执行工艺规则匹配
        
        Args:
            context: {"job_id": "xxx"}
        
        Returns:
            {"status": "ok", "message": "...", "summary": {"success_count": N, "failed_count": M}}
        """
        import time  # 导入time模块用于性能监控
        
        job_id = context.get("job_id")
        if not job_id:
            return {"status": "error", "message": "缺少 job_id", "error_code": "MISSING_JOB_ID"}
        
        try:
            total_start = time.time()
            self.logger.info(f"[MCP模式 - Agent层并发] 开始特征识别")
            
            # 1. 查询所有子图
            query_start = time.time()
            subgraph_ids = await self._get_subgraph_ids(job_id)
            query_duration = time.time() - query_start
            
            if not subgraph_ids:
                return {
                    "status": "error",
                    "message": "未找到子图",
                    "error_code": "NO_SUBGRAPHS"
                }
            
            self.logger.info(f"找到 {len(subgraph_ids)} 个子图，开始并发处理")
            self.logger.info(f"[性能] 查询子图: {query_duration*1000:.0f}ms")
            
            # 2. 发布开始进度
            total_count = len(subgraph_ids)
            if self.progress_publisher:
                from shared.progress_stages import ProgressStage, ProgressPercent
                self.progress_publisher.publish_progress(
                    job_id=job_id,
                    stage=ProgressStage.FEATURE_RECOGNITION_STARTED,
                    progress=ProgressPercent.FEATURE_RECOGNITION_STARTED,
                    message=f"开始特征识别，共 {total_count} 个子图",
                    details={
                        "total_count": total_count,
                        "completed_count": 0,
                        "source": "agent"
                    }
                )
            
            # 3. 并发处理所有子图（Agent 层并发）
            process_start = time.time()
            results = await self._process_subgraphs_concurrent(
                job_id, 
                subgraph_ids
            )
            process_duration = time.time() - process_start
            
            # 4. 统计结果
            success_count = sum(1 for r in results if r.get("success"))
            failed_count = len(results) - success_count
            
            # 计算平均耗时
            avg_duration = process_duration / len(subgraph_ids) if subgraph_ids else 0
            
            self.logger.info(f"特征识别完成: 成功{success_count}个, 失败{failed_count}个")
            self.logger.info(f"[性能] 并发处理: {process_duration*1000:.0f}ms (平均 {avg_duration*1000:.0f}ms/个)")
            
            # 5. 发布完成进度
            if self.progress_publisher:
                self.progress_publisher.publish_progress(
                    job_id=job_id,
                    stage=ProgressStage.FEATURE_RECOGNITION_COMPLETED,
                    progress=ProgressPercent.FEATURE_RECOGNITION_COMPLETED,
                    message=f"特征识别完成: 成功{success_count}个, 失败{failed_count}个",
                    details={
                        "total_count": total_count,
                        "success_count": success_count,
                        "failed_count": failed_count,
                        "source": "agent"
                    }
                )
            
            # 6. 特征识别完成后，立即执行工艺规则匹配
            match_start = time.time()
            await self._match_process_rules_after_recognition(job_id)
            match_duration = time.time() - match_start
            
            # 计算总耗时
            total_duration = time.time() - total_start
            
            # 输出性能汇总
            self.logger.info("=" * 80)
            self.logger.info("[性能汇总] 特征识别各阶段耗时:")
            self.logger.info(f"  查询子图:         {query_duration*1000:6.0f}ms ({query_duration/total_duration*100:5.1f}%)")
            self.logger.info(f"  并发处理:         {process_duration*1000:6.0f}ms ({process_duration/total_duration*100:5.1f}%)")
            self.logger.info(f"  工艺规则匹配:     {match_duration*1000:6.0f}ms ({match_duration/total_duration*100:5.1f}%)")
            self.logger.info(f"  总耗时:          {total_duration*1000:6.0f}ms")
            self.logger.info(f"  平均耗时/子图:    {avg_duration*1000:.0f}ms")
            self.logger.info("=" * 80)
            
            return {
                "status": "ok",
                "message": f"特征识别完成: 成功{success_count}个, 失败{failed_count}个",
                "summary": {
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "total_count": len(subgraph_ids)
                }
            }
                
        except Exception as e:
            self.logger.error(f"特征识别失败: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"特征识别失败: {str(e)}",
                "error_code": "FEATURE_RECOGNITION_ERROR"
            }
    
    async def _process_subgraphs_concurrent(
        self, 
        job_id: str, 
        subgraph_ids: List[str],
        max_concurrent: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        并发处理多个子图（Agent 层并发，带并发数量控制）
        
        并发数从环境变量读取，支持运行时调整：
        - FEATURE_RECOGNITION_MAX_CONCURRENT: 最大并发数（默认25）
        - FEATURE_RECOGNITION_ADAPTIVE_CONCURRENCY: 是否启用自适应（默认false）
        
        Args:
            job_id: 任务ID
            subgraph_ids: 子图ID列表
            max_concurrent: 最大并发数（可选，默认从环境变量读取）
        
        Returns:
            结果列表
        """
        # 从环境变量读取并发数（支持运行时调整）
        if max_concurrent is None:
            max_concurrent = int(os.getenv('FEATURE_RECOGNITION_MAX_CONCURRENT', '25'))
        
        # 自适应并发控制（实验性功能）
        adaptive_enabled = os.getenv('FEATURE_RECOGNITION_ADAPTIVE_CONCURRENCY', 'false').lower() == 'true'
        if adaptive_enabled:
            min_concurrent = int(os.getenv('FEATURE_RECOGNITION_MIN_CONCURRENT', '10'))
            max_concurrent_limit = int(os.getenv('FEATURE_RECOGNITION_MAX_CONCURRENT_LIMIT', '50'))
            
            # 根据子图数量自适应调整并发数
            # 规则：每20个子图增加5个并发，但不超过上限
            adaptive_concurrent = min(
                max_concurrent_limit,
                max(min_concurrent, len(subgraph_ids) // 20 * 5)
            )
            
            self.logger.info(
                f"🔄 自适应并发: {max_concurrent} → {adaptive_concurrent} "
                f"(子图数: {len(subgraph_ids)})"
            )
            max_concurrent = adaptive_concurrent
        
        # 创建信号量控制并发数
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def process_with_semaphore(subgraph_id: str):
            """使用信号量控制的处理函数"""
            async with semaphore:
                return await self._process_single_subgraph(job_id, subgraph_id)
        
        # 创建并发任务
        tasks = []
        for subgraph_id in subgraph_ids:
            task = process_with_semaphore(subgraph_id)
            tasks.append(task)
        
        # 并发执行（使用 return_exceptions=True 避免单个失败影响整体）
        self.logger.info(
            f"⚡ 开始并发执行 {len(tasks)} 个任务 "
            f"(最大并发数: {max_concurrent})..."
        )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"子图 {subgraph_ids[i]} 处理异常: {result}")
                processed_results.append({
                    "success": False,
                    "subgraph_id": subgraph_ids[i],
                    "message": str(result)
                })
            else:
                processed_results.append(result)
        
        return processed_results
    
    async def _process_single_subgraph(
        self, 
        job_id: str, 
        subgraph_id: str
    ) -> Dict[str, Any]:
        """
        处理单个子图（调用 MCP 服务）
        
        MCP 服务负责：
        1. 调用脚本处理单个子图
        2. 写入 Redis 进度
        
        Args:
            job_id: 任务ID
            subgraph_id: 子图ID
        
        Returns:
            处理结果
        """
        start_time = datetime.utcnow()
        
        try:
            self.logger.debug(f"处理子图: {subgraph_id}")
            
            # 调用 MCP 服务（单个子图）
            # MCP 服务会自动写入 Redis 进度
            result = await self.mcp_client.call_tool(
                "cad-price-search-mcp",
                "feature_recognition",
                {
                    "job_id": job_id,
                    "subgraph_id": subgraph_id  # 指定单个子图
                }
            )
            
            # 计算耗时
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            # 检查结果
            if result.get("success"):
                data = result.get("data", {})
                results_list = data.get("results", [])
                
                if results_list and results_list[0].get("success"):
                    self.logger.info(f"✅ 子图 {subgraph_id} 处理成功 (耗时: {duration_ms}ms)")
                    
                    # 慢查询警告
                    slow_threshold = int(os.getenv('FEATURE_RECOGNITION_SLOW_THRESHOLD', '5000'))
                    if duration_ms > slow_threshold:
                        self.logger.warning(
                            f"⚠️ 子图 {subgraph_id} 处理较慢: {duration_ms}ms "
                            f"(阈值: {slow_threshold}ms)"
                        )
                    
                    return {
                        "success": True,
                        "subgraph_id": subgraph_id,
                        "duration_ms": duration_ms
                    }
                else:
                    error_msg = results_list[0].get("message", "未知错误") if results_list else "未返回结果"
                    self.logger.error(f"❌ 子图 {subgraph_id} 处理失败: {error_msg}")
                    return {
                        "success": False,
                        "subgraph_id": subgraph_id,
                        "message": error_msg,
                        "duration_ms": duration_ms
                    }
            else:
                error_msg = result.get("message", "MCP调用失败")
                self.logger.error(f"❌ 子图 {subgraph_id} MCP调用失败: {error_msg}")
                return {
                    "success": False,
                    "subgraph_id": subgraph_id,
                    "message": error_msg,
                    "duration_ms": duration_ms
                }
                
        except Exception as e:
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            self.logger.error(f"❌ 子图 {subgraph_id} 处理异常: {e}", exc_info=True)
            
            return {
                "success": False,
                "subgraph_id": subgraph_id,
                "message": str(e),
                "duration_ms": duration_ms
            }
    
    async def _get_subgraph_ids(self, job_id: str) -> List[str]:
        """查询任务的所有子图ID"""
        from shared.models import Subgraph
        from shared.database import get_db
        from sqlalchemy import select
        
        async for db in get_db():
            result = await db.execute(
                select(Subgraph.subgraph_id).where(Subgraph.job_id == job_id)
            )
            subgraph_ids = [row[0] for row in result.fetchall()]
            break
        
        return subgraph_ids

    async def recognize_features_batch(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        批量重新执行特征识别（支持指定子图）
        
        用于用户修改参数后重新处理部分子图
        
        Args:
            context: {
                "job_id": str,                  # 任务ID（必填）
                "subgraph_ids": List[str],      # 要处理的子图ID列表（必填）
                "force_reprocess": bool         # 是否强制重新处理（可选，默认True）
            }
        
        Returns:
            {
                "status": "ok",
                "message": "批量特征识别完成",
                "total": 3,
                "success": 2,
                "failed": 1,
                "results": [...]
            }
        """
        job_id = context.get("job_id")
        subgraph_ids = context.get("subgraph_ids", [])
        force_reprocess = context.get("force_reprocess", True)
        
        if not job_id:
            return {"status": "error", "message": "缺少 job_id", "error_code": "MISSING_JOB_ID"}
        
        if not subgraph_ids:
            return {"status": "error", "message": "缺少 subgraph_ids", "error_code": "MISSING_SUBGRAPH_IDS"}
        
        self.logger.info(f"[批量特征识别] job_id={job_id}, 子图数量={len(subgraph_ids)}")
        
        try:
            # 1. 发布开始进度（粗粒度）
            total_count = len(subgraph_ids)
            if self.progress_publisher:
                from shared.progress_stages import ProgressStage, ProgressPercent
                self.progress_publisher.publish_progress(
                    job_id=job_id,
                    stage=ProgressStage.FEATURE_RECOGNITION_STARTED,
                    progress=ProgressPercent.FEATURE_RECOGNITION_STARTED,
                    message=f"开始重新识别特征，共 {total_count} 个子图",
                    details={
                        "total_count": total_count,
                        "source": "agent",
                        "type": "reprocess"
                    }
                )
            
            # 2. 对每个 subgraph_id 并发调用 MCP
            tasks = []
            for subgraph_id in subgraph_ids:
                task = self._process_single_subgraph_features(job_id, subgraph_id, force_reprocess)
                tasks.append(task)
            
            # 并发执行
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 统计结果
            success_count = 0
            failed_count = 0
            processed_results = []
            
            for i, result in enumerate(results):
                subgraph_id = subgraph_ids[i]
                
                if isinstance(result, Exception):
                    self.logger.error(f"[批量特征识别] {subgraph_id} 执行异常: {result}")
                    processed_results.append({
                        "subgraph_id": subgraph_id,
                        "status": "failed",
                        "error": str(result),
                        "duration_ms": 0
                    })
                    failed_count += 1
                elif result.get("status") == "success":
                    processed_results.append(result)
                    success_count += 1
                else:
                    processed_results.append(result)
                    failed_count += 1
            
            self.logger.info(
                f"[批量特征识别] 完成: 成功{success_count}个, 失败{failed_count}个"
            )
            
            # 3. 发布完成进度（粗粒度）
            if self.progress_publisher:
                self.progress_publisher.publish_progress(
                    job_id=job_id,
                    stage=ProgressStage.FEATURE_RECOGNITION_COMPLETED,
                    progress=ProgressPercent.FEATURE_RECOGNITION_COMPLETED,
                    message=f"重新识别完成: 成功{success_count}个, 失败{failed_count}个",
                    details={
                        "total_count": total_count,
                        "success_count": success_count,
                        "failed_count": failed_count,
                        "source": "agent",
                        "type": "reprocess"
                    }
                )
            
            return {
                "status": "ok",
                "message": f"批量特征识别完成: 成功{success_count}个, 失败{failed_count}个",
                "total": len(subgraph_ids),
                "success": success_count,
                "failed": failed_count,
                "results": processed_results
            }
            
        except Exception as e:
            self.logger.error(f"[批量特征识别] 执行失败: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"批量特征识别失败: {str(e)}",
                "error_code": "BATCH_FEATURE_RECOGNITION_ERROR"
            }
    
    async def _process_single_subgraph_features(
        self, 
        job_id: str, 
        subgraph_id: str,
        force_reprocess: bool = True
    ) -> Dict[str, Any]:
        """
        处理单个子图的特征识别
        
        Args:
            job_id: 任务ID
            subgraph_id: 子图ID
            force_reprocess: 是否强制重新处理
        
        Returns:
            {
                "subgraph_id": "sub_001",
                "status": "success",
                "features": {...},
                "duration_ms": 2500
            }
        """
        start_time = datetime.utcnow()
        
        try:
            self.logger.info(f"[特征识别] 处理子图: {subgraph_id}")
            
            # 调用 MCP 服务
            result = await self.mcp_client.call_tool(
                "cad-price-search-mcp",
                "feature_recognition",
                {
                    "job_id": job_id,
                    "subgraph_id": subgraph_id  # 只处理指定子图
                }
            )
            
            # 计算耗时
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            # 处理结果
            if result.get("success"):
                data = result.get("data", {})
                results_list = data.get("results", [])
                
                # 提取该子图的结果
                subgraph_result = None
                if results_list:
                    subgraph_result = results_list[0]  # 只有一个子图
                
                if subgraph_result and subgraph_result.get("success"):
                    features = subgraph_result.get("features", {})
                    
                    return {
                        "subgraph_id": subgraph_id,
                        "status": "success",
                        "features": features,
                        "duration_ms": duration_ms
                    }
                else:
                    error_msg = subgraph_result.get("message", "特征识别失败") if subgraph_result else "未返回结果"
                    
                    return {
                        "subgraph_id": subgraph_id,
                        "status": "failed",
                        "error": error_msg,
                        "duration_ms": duration_ms
                    }
            else:
                error_msg = result.get("message", "MCP调用失败")
                
                return {
                    "subgraph_id": subgraph_id,
                    "status": "failed",
                    "error": error_msg,
                    "duration_ms": duration_ms
                }
                
        except Exception as e:
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            error_msg = f"处理异常: {str(e)}"
            
            self.logger.error(f"[特征识别] {subgraph_id} 失败: {e}", exc_info=True)
            
            return {
                "subgraph_id": subgraph_id,
                "status": "failed",
                "error": error_msg,
                "duration_ms": duration_ms
            }
    
    async def _process_mcp(self, context: Dict[str, Any]) -> OpResult:
        """MCP模式：通过MCP客户端调用服务"""
        job_id = context["job_id"]
        dwg_url = context.get("dwg_url") or context.get("dwg_file_path")
        
        try:
            # 调用 MCP 服务的完整流程工具
            self.logger.info("调用 MCP 服务: process_cad_and_features")
            
            # 构造参数
            arguments = {"job_id": job_id}
            if dwg_url:
                arguments["dwg_url"] = dwg_url
            
            # 调用 MCP 工具
            result = await self.mcp_client.call_tool(
                "cad-price-search-mcp",
                "process_cad_and_features",
                arguments
            )
            
            # 检查结果
            if result.get("status") != "ok":
                return OpResult(
                    status="failed",
                    message=f"MCP 处理失败: {result.get('message', '未知错误')}",
                    data={"mcp_result": result}
                )
            
            # 提取结果
            chaitu_result = result.get("chaitu", {})
            feature_result = result.get("features", {})
            
            # 统计
            chaitu_count = chaitu_result.get("data", {}).get("total_count", 0)
            feature_data = feature_result.get("data", {})
            feature_success = feature_data.get("success_count", 0)
            feature_failed = feature_data.get("failed_count", 0)
            
            return OpResult(
                status="ok" if feature_failed == 0 else "warning",
                message=f"处理完成: 拆图{chaitu_count}个, 特征识别成功{feature_success}个, 失败{feature_failed}个",
                data={
                    "mcp_result": result,
                    "summary": {
                        "total_subgraphs": chaitu_count,
                        "feature_success": feature_success,
                        "feature_failed": feature_failed
                    }
                }
            )
        except Exception as e:
            self.logger.error(f"CAD 处理失败: {str(e)}")
            return OpResult(
                status="failed",
                message=f"CAD 处理异常: {str(e)}",
                data={"error": str(e)}
            )
    
    async def _match_process_rules_after_recognition(self, job_id: str):
        """
        特征识别完成后，自动匹配工艺规则
        
        功能：
        1. 查询该 job 下的所有 subgraph_ids
        2. 调用工艺规则匹配器
        3. 并发更新线割工艺信息
        
        Args:
            job_id: 任务ID
        """
        try:
            self.logger.info(f"[工艺规则匹配] 开始: job_id={job_id}")
            
            # 1. 查询所有 subgraph_ids
            from shared.models import Subgraph
            from shared.database import get_db
            from sqlalchemy import select
            
            subgraph_ids = []
            async for db in get_db():
                result = await db.execute(
                    select(Subgraph.subgraph_id).where(Subgraph.job_id == job_id)
                )
                subgraph_ids = [row[0] for row in result.fetchall()]
                break
            
            if not subgraph_ids:
                self.logger.warning(f"[工艺规则匹配] 未找到子图: job_id={job_id}")
                return
            
            self.logger.info(f"[工艺规则匹配] 找到 {len(subgraph_ids)} 个子图")
            
            # 2. 调用工艺规则匹配器（并发处理）
            match_result = await match_and_update_process_rules(job_id, subgraph_ids)
            
            # 3. 记录结果
            if match_result.get("status") == "ok":
                matched = match_result.get("matched_count", 0)
                skipped = match_result.get("skipped_count", 0)
                updated = match_result.get("updated_count", 0)
                
                self.logger.info(
                    f"[工艺规则匹配] 完成: 匹配={matched}, "
                    f"跳过={skipped}, 更新={updated}"
                )
            else:
                self.logger.error(
                    f"[工艺规则匹配] 失败: {match_result.get('message')}"
                )
        
        except Exception as e:
            # 工艺规则匹配失败不影响主流程
            self.logger.error(
                f"[工艺规则匹配] 异常: {e}",
                exc_info=True
            )


# 使用示例
async def main():
    """使用示例"""
    from shared.mcp_client import MCPClient
    
    # 创建 MCP 客户端
    mcp_client = MCPClient(base_url="http://localhost:8200")
    
    # 创建 CAD Agent
    agent = CADAgent(mcp_client=mcp_client)
    
    # 方式1: 只提供 job_id（推荐）
    context = {
        "job_id": "c5e4cf94-24ff-492e-9106-4cae088a45a2"
    }
    
    # 执行处理
    result = await agent.process(context)
    
    # 输出结果
    print("\n" + "="*60)
    print(f"✅ 处理状态: {result.status.upper()}")
    print(f"📝 消息: {result.message}")
    
    if result.data and result.data.get('summary'):
        summary = result.data['summary']
        print(f"\n📊 处理结果:")
        print(f"   - 拆图数量: {summary['total_subgraphs']} 个")
        print(f"   - 特征识别成功: {summary['feature_success']} 个")
        print(f"   - 特征识别失败: {summary['feature_failed']} 个")
    
    print("="*60 + "\n")


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 运行示例
    asyncio.run(main())
