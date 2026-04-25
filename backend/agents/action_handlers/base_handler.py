"""
BaseActionHandler - 动作处理器基类
负责人：人员B2

定义动作处理器的接口和公共方法
"""
import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime
from shared.timezone_utils import now_shanghai

from agents.intent_types import IntentResult, ActionResult, IntentType

logger = logging.getLogger(__name__)


class BaseActionHandler(ABC):
    """
    动作处理器基类
    
    所有具体的 Handler 都应继承此类并实现 handle() 方法
    """
    
    # 🆕 概念词映射表（概念词 → 关键词列表）
    # 所有关键词都使用模糊匹配（包含匹配）
    CONCEPT_KEYWORD_MAPPING = {
        "冲头": ["切边冲头", "切冲冲头", "冲子", "废料刀", "冲头"],
        "冲头类": ["切边冲头", "切冲冲头", "冲子", "废料刀", "冲头"],  # "冲头类"作为"冲头"的同义词
        "刀口入块": ["刀口入子", "切边入子", "冲孔入子", "凹模"],
        "模架": ["模座", "垫脚", "托板"],
    }
    
    def __init__(self):
        """初始化 Handler"""
        self._redis_client = None
    
    @property
    def redis_client(self):
        """懒加载 Redis 客户端"""
        if self._redis_client is None:
            from api_gateway.utils.redis_client import redis_client
            self._redis_client = redis_client
        return self._redis_client
    
    @abstractmethod
    async def handle(
        self,
        intent_result: IntentResult,
        job_id: str,
        context: Dict[str, Any],
        db_session
    ) -> ActionResult:
        """
        处理意图
        
        Args:
            intent_result: 意图识别结果
            job_id: 任务ID
            context: 当前审核数据上下文
            db_session: 数据库会话
        
        Returns:
            ActionResult: 处理结果
        """
        pass
    
    # ========== Redis 状态管理辅助方法 ==========
    
    def _serialize_for_redis(self, data: Any) -> str:
        """
        序列化数据为 JSON（处理 datetime 对象）
        
        Args:
            data: 要序列化的数据
        
        Returns:
            JSON 字符串
        """
        def default_handler(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
        
        return json.dumps(data, ensure_ascii=False, default=default_handler)
    
    async def _save_pending_action(
        self,
        job_id: str,
        pending_action: Dict[str, Any]
    ):
        """
        保存待确认的操作到 Redis
        
        Args:
            job_id: 任务ID
            pending_action: 待确认的操作数据
        """
        key = f"review:pending_action:{job_id}"
        
        # 添加时间戳
        pending_action["created_at"] = now_shanghai().isoformat()
        
        await self.redis_client.set(
            key,
            self._serialize_for_redis(pending_action),
            ex=3600  # 1小时过期
        )
        
        logger.debug(f"💾 pending_action 已保存: {key}")
    
    async def _get_pending_action(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        从 Redis 获取待确认的操作
        
        Args:
            job_id: 任务ID
        
        Returns:
            待确认的操作数据，如果不存在返回 None
        """
        key = f"review:pending_action:{job_id}"
        data = await self.redis_client.get(key)
        
        if data:
            return json.loads(data)
        return None
    
    async def _clear_pending_action(self, job_id: str):
        """
        清理 Redis 中的待确认操作
        
        Args:
            job_id: 任务ID
        """
        key = f"review:pending_action:{job_id}"
        await self.redis_client.delete(key)
        logger.debug(f"🗑️  pending_action 已清理: {key}")
    
    # ========== 辅助方法 ==========
    
    def _get_all_subgraph_ids(self, context: Dict[str, Any]) -> list[str]:
        """
        获取所有子图的 ID
        
        Args:
            context: 数据上下文（支持两种格式）
                - 格式1: {"subgraphs": [...]}  # 直接包含 subgraphs
                - 格式2: {"raw_data": {"subgraphs": [...]}}  # 嵌套在 raw_data 中
        
        Returns:
            subgraph_ids 列表
        """
        # 兼容两种数据结构
        if "raw_data" in context:
            # 格式2: 嵌套结构
            subgraphs = context.get("raw_data", {}).get("subgraphs", [])
            logger.debug(f"📊 从 raw_data 中获取子图: {len(subgraphs)} 个")
        else:
            # 格式1: 直接结构
            subgraphs = context.get("subgraphs", [])
            logger.debug(f"📊 从 context 中直接获取子图: {len(subgraphs)} 个")
        
        subgraph_ids = [sg.get("subgraph_id") for sg in subgraphs if sg.get("subgraph_id")]
        logger.debug(f"✅ 提取到 {len(subgraph_ids)} 个 subgraph_id")
        
        return subgraph_ids
    
    # ========== 🆕 包含匹配工具（多关键词模糊匹配） ==========
    
    def _match_subgraphs_by_keyword(
        self,
        keyword: str,
        context: Dict[str, Any]
    ) -> list[str]:
        """
        通过关键词匹配子图（包含匹配）
        
        Args:
            keyword: 零件关键词（如"模板"、"冲头"）
            context: 数据上下文（包含 display_view）
        
        Returns:
            匹配的 subgraph_id 列表
        """
        display_view = context.get("display_view", [])
        matched_ids = []
        
        logger.info(f"🔍 开始包含匹配: 关键词='{keyword}', display_view 记录数={len(display_view)}")
        
        for item in display_view:
            part_name = item.get("part_name", "")
            if keyword in part_name:
                source = item.get("_source", {})
                subgraph_id = source.get("subgraph_id")
                if subgraph_id:
                    matched_ids.append(subgraph_id)
                    logger.info(
                        f"✅ 包含匹配: keyword='{keyword}', "
                        f"part_name='{part_name}', subgraph_id='{subgraph_id}'"
                    )
        
        logger.info(f"✅ 关键词 '{keyword}' 匹配到 {len(matched_ids)} 个子图")
        return matched_ids
    
    def _match_subgraphs_by_keywords(
        self,
        keywords: list[str],
        context: Dict[str, Any]
    ) -> Dict[str, list[str]]:
        """
        通过多个关键词匹配子图（包含匹配）
        
        Args:
            keywords: 关键词列表
            context: 数据上下文
        
        Returns:
            字典：{keyword: [subgraph_ids]}
        """
        results = {}
        all_matched_ids = set()  # 用于去重
        
        for keyword in keywords:
            matched_ids = self._match_subgraphs_by_keyword(keyword, context)
            results[keyword] = matched_ids
            all_matched_ids.update(matched_ids)
        
        logger.info(f"✅ 多关键词匹配完成: 共 {len(all_matched_ids)} 个子图（去重后）")
        return results
    
    # ========== 🆕 概念词映射（多关键词模糊匹配扩展） ==========
    
    def _expand_concept_to_keywords(self, concept: str) -> list[str]:
        """
        将概念词展开为关键词列表
        
        Args:
            concept: 概念词（如"冲头"、"刀口入块"、"模架"）
        
        Returns:
            关键词列表，如果不是概念词则返回 [concept]
        """
        keywords = self.CONCEPT_KEYWORD_MAPPING.get(concept)
        
        if keywords:
            logger.info(f"✅ 概念词映射: {concept} → {keywords}")
            return keywords
        else:
            logger.info(f"📋 非概念词，作为普通关键词处理: {concept}")
            return [concept]
    
    def _match_subgraphs_by_concept(
        self,
        concept: str,
        context: Dict[str, Any]
    ) -> tuple[list[str], Dict[str, list[str]]]:
        """
        通过概念词匹配子图（支持概念词自动展开）
        
        Args:
            concept: 概念词或普通关键词
            context: 数据上下文
        
        Returns:
            (所有匹配的 subgraph_ids, 详细匹配结果)
        """
        # 1. 展开概念词
        keywords = self._expand_concept_to_keywords(concept)
        
        # 2. 多关键词匹配
        match_results = self._match_subgraphs_by_keywords(keywords, context)
        
        # 3. 合并所有匹配的 subgraph_ids（去重）
        all_subgraph_ids = []
        seen = set()
        for kw, ids in match_results.items():
            for sg_id in ids:
                if sg_id not in seen:
                    seen.add(sg_id)
                    all_subgraph_ids.append(sg_id)
        
        logger.info(f"✅ 概念词 '{concept}' 匹配到 {len(all_subgraph_ids)} 个子图（去重后）")
        
        return all_subgraph_ids, match_results
    
    def _format_match_summary(
        self,
        original_keyword: str,
        match_results: Dict[str, list[str]]
    ) -> str:
        """
        格式化匹配摘要
        
        Args:
            original_keyword: 原始关键词（可能是概念词）
            match_results: 匹配结果 {keyword: [subgraph_ids]}
        
        Returns:
            格式化的摘要字符串
        """
        total_count = sum(len(ids) for ids in match_results.values())
        
        # 如果是概念词（多个关键词）
        if len(match_results) > 1:
            details = []
            for kw, ids in match_results.items():
                if len(ids) == 0:
                    details.append(f"{kw}: 0个（未找到）")
                else:
                    details.append(f"{kw}: {len(ids)}个")
            
            return f"{original_keyword} {total_count} 个零件（{', '.join(details)}）"
        
        # 如果是普通关键词（单个）
        else:
            return f"{total_count} 个零件"


class ActionHandlerFactory:
    """
    动作处理器工厂
    
    根据意图类型创建相应的 Handler
    """
    
    _handlers: Dict[str, BaseActionHandler] = {}
    
    @classmethod
    def register_handler(cls, intent_type: str, handler: BaseActionHandler):
        """
        注册 Handler
        
        Args:
            intent_type: 意图类型
            handler: Handler 实例
        """
        cls._handlers[intent_type] = handler
        logger.info(f"✅ 注册 Handler: {intent_type} -> {handler.__class__.__name__}")
    
    @classmethod
    def get_handler(cls, intent_type: str) -> Optional[BaseActionHandler]:
        """
        获取 Handler
        
        Args:
            intent_type: 意图类型
        
        Returns:
            Handler 实例，如果未注册返回 None
        """
        handler = cls._handlers.get(intent_type)
        
        if not handler:
            logger.warning(f"⚠️  未找到 Handler: {intent_type}")
        
        return handler
    
    @classmethod
    def initialize_handlers(cls):
        """
        初始化所有 Handler
        
        这个方法会在应用启动时调用，注册所有的 Handler
        """
        from .data_modification_handler import DataModificationHandler
        from .feature_recognition_handler import FeatureRecognitionHandler
        from .price_calculation_handler import PriceCalculationHandler
        from .query_details_handler import QueryDetailsHandler
        from .general_chat_handler import GeneralChatHandler
        from .weight_price_calculation_handler import WeightPriceCalculationHandler
        from .weight_price_query_handler import WeightPriceQueryHandler
        from .confirmation_response_handler import ConfirmationResponseHandler
        
        # 注册所有 Handler
        cls.register_handler(IntentType.DATA_MODIFICATION, DataModificationHandler())
        cls.register_handler(IntentType.FEATURE_RECOGNITION, FeatureRecognitionHandler())
        cls.register_handler(IntentType.PRICE_CALCULATION, PriceCalculationHandler())
        cls.register_handler(IntentType.QUERY_DETAILS, QueryDetailsHandler())
        cls.register_handler(IntentType.GENERAL_CHAT, GeneralChatHandler())
        cls.register_handler(IntentType.WEIGHT_PRICE_CALCULATION, WeightPriceCalculationHandler())
        cls.register_handler(IntentType.WEIGHT_PRICE_QUERY, WeightPriceQueryHandler())
        cls.register_handler(IntentType.CONFIRMATION_RESPONSE, ConfirmationResponseHandler())
        
        logger.info(f"✅ 所有 Handler 已注册，共 {len(cls._handlers)} 个")
