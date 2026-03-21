"""
FeatureRecognitionHandler - 特征识别处理器
负责人：人员B2

处理特征识别意图，准备 API 参数并保存到 Redis
"""
import logging
from typing import Dict, Any

from .base_handler import BaseActionHandler
from agents.intent_types import IntentResult, ActionResult

logger = logging.getLogger(__name__)


class FeatureRecognitionHandler(BaseActionHandler):
    """
    特征识别处理器
    
    功能：
    1. 从意图中提取 subgraph_ids
    2. 准备特征识别 API 的请求参数
    3. 保存 pending_action 到 Redis
    4. 返回确认消息
    
    注意：不在这里调用 API，而是在用户确认后由 ConfirmHandler 调用
    """
    
    def __init__(self):
        """初始化 Handler"""
        super().__init__()
        logger.info("✅ FeatureRecognitionHandler 初始化完成")
    
    async def handle(
        self,
        intent_result: IntentResult,
        job_id: str,
        context: Dict[str, Any],
        db_session
    ) -> ActionResult:
        """
        处理特征识别请求
        
        Args:
            intent_result: 意图识别结果
            job_id: 任务ID
            context: 当前审核数据上下文
            db_session: 数据库会话
        
        Returns:
            ActionResult: 处理结果
        """
        logger.info(f"🔍 处理特征识别: {intent_result.raw_message}")
        
        try:
            # 1. 提取 subgraph_ids 或关键词
            subgraph_ids = intent_result.parameters.get("subgraph_ids")
            keyword = intent_result.parameters.get("keyword")  # 🆕 新增
            
            if keyword:
                # 🆕 使用概念词匹配（支持自动展开）
                logger.info(f"🔍 使用关键词匹配: {keyword}")
                subgraph_ids, match_results = self._match_subgraphs_by_concept(keyword, context)
                
                if not subgraph_ids:
                    return ActionResult(
                        status="error",
                        message=f"未找到包含 '{keyword}' 的零件",
                        data={}
                    )
                
                logger.info(f"✅ 关键词 '{keyword}' 匹配到 {len(subgraph_ids)} 个子图")
                
                # 🆕 生成匹配摘要
                summary = self._format_match_summary(keyword, match_results)
                logger.info(f"📊 匹配摘要: {summary}")
            
            elif not subgraph_ids:
                # 如果未指定，则识别所有子图
                subgraph_ids = self._get_all_subgraph_ids(context)
                logger.info(f"未指定子图，将识别所有 {len(subgraph_ids)} 个子图")
            else:
                logger.info(f"🔍 原始 subgraph_ids: {subgraph_ids}")
                # 🆕 将短名称转换为完整 ID
                subgraph_ids = self._resolve_subgraph_ids(subgraph_ids, context)
                logger.info(f"✅ 转换后 subgraph_ids: {subgraph_ids}")
            
            if not subgraph_ids:
                return ActionResult(
                    status="error",
                    message="当前没有可识别的子图",
                    data={}
                )
            
            # 2. 准备 API 参数
            api_params = {
                "job_id": job_id,
                "subgraph_ids": subgraph_ids,
                "options": {
                    "force_reprocess": True,
                    "update_existing": True
                }
            }
            
            # 3. 保存 pending_action 到 Redis
            await self._save_pending_action(job_id, {
                "action_type": "FEATURE_RECOGNITION",
                "api_params": api_params,
                "subgraph_ids": subgraph_ids
            })
            
            # 4. 格式化确认消息（使用短名称显示）
            display_names = [self._get_short_name(sg_id) for sg_id in subgraph_ids]
            if len(display_names) <= 5:
                message = f"将重新识别以下子图的特征：{', '.join(display_names)}，请确认"
            else:
                message = f"将重新识别 {len(display_names)} 个子图的特征（{', '.join(display_names[:3])} ...），请确认"
            
            logger.info(f"✅ 特征识别请求准备完成")
            
            # 5. 返回确认消息
            return ActionResult(
                status="ok",
                message=message,
                requires_confirmation=True,
                pending_action={
                    "action_type": "FEATURE_RECOGNITION",
                    "subgraph_ids": subgraph_ids
                },
                data={
                    "subgraph_ids": subgraph_ids,
                    "count": len(subgraph_ids)
                }
            )
        
        except Exception as e:
            logger.error(f"❌ 处理特征识别失败: {e}", exc_info=True)
            return ActionResult(
                status="error",
                message=f"处理特征识别请求失败：{str(e)}",
                data={}
            )
    
    def _resolve_subgraph_ids(
        self,
        short_names: list,
        context: Dict[str, Any]
    ) -> list:
        """
        将短名称转换为完整的 subgraph_id
        
        支持：
        - 短名称: "DIE-03" → "uuid_DIE-03"
        - 完整ID: "uuid_DIE-03" → "uuid_DIE-03"
        
        Args:
            short_names: 短名称列表
            context: 数据上下文（包含 raw_data 或 display_view）
        
        Returns:
            完整的 subgraph_id 列表
        """
        # 获取所有子图数据
        raw_data = context.get("raw_data") or context
        subgraphs = raw_data.get("subgraphs", [])
        
        # 构建映射：短名称 → 完整ID
        short_to_full = {}
        for sg in subgraphs:
            full_id = sg.get("subgraph_id")
            if not full_id:
                continue
            
            # 提取短名称（UUID_短名称 → 短名称）
            if "_" in full_id:
                short_name = full_id.split("_", 1)[1]
            else:
                short_name = full_id
            
            short_to_full[short_name] = full_id
            short_to_full[full_id] = full_id  # 也支持完整ID
        
        # 转换
        resolved_ids = []
        for name in short_names:
            full_id = short_to_full.get(name)
            if full_id:
                resolved_ids.append(full_id)
                logger.debug(f"🔄 转换: {name} → {full_id}")
            else:
                logger.warning(f"⚠️  未找到子图: {name}")
                # 如果找不到，保留原名称（可能本身就是完整ID）
                resolved_ids.append(name)
        
        return resolved_ids
    
    def _get_short_name(self, subgraph_id: str) -> str:
        """
        从完整 ID 提取短名称
        
        Args:
            subgraph_id: 完整的 subgraph_id
        
        Returns:
            短名称
        """
        if "_" in subgraph_id:
            return subgraph_id.split("_", 1)[1]
        return subgraph_id
