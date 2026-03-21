"""
ConfirmationHandler - 确认处理器

职责：
1. 管理用户确认流程
2. 创建和保存确认上下文
3. 格式化确认消息
4. 解析用户响应
5. 应用操作到选中的零件
"""
import os
import uuid
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from shared.timezone_utils import now_shanghai
from shared.match_evaluator import MatchResult, MatchEvaluator
from agents.intent_types import ActionResult

logger = logging.getLogger(__name__)


@dataclass
class ConfirmationContext:
    """确认上下文"""
    confirmation_id: str
    job_id: str
    original_message: str
    parsed_intent: Dict[str, Any]
    candidates: List[Dict]
    created_at: str  # ISO格式字符串
    expires_at: str  # ISO格式字符串


class ConfirmationHandler:
    """确认处理器"""
    
    def __init__(self, redis_client=None):
        """
        初始化确认处理器
        
        Args:
            redis_client: Redis 客户端（可选，懒加载）
        """
        self._redis_client = redis_client
        self._chat_history_repo = None
        self.ttl = int(os.getenv("CONFIRMATION_TTL", "300"))  # 默认5分钟
        self.max_display = int(os.getenv("MAX_CANDIDATES_DISPLAY", "10"))
        
        logger.info(f"✅ ConfirmationHandler 初始化完成 (TTL={self.ttl}s, max_display={self.max_display})")
    
    @property
    def redis_client(self):
        """懒加载 Redis 客户端"""
        if self._redis_client is None:
            from api_gateway.utils.redis_client import redis_client
            self._redis_client = redis_client
        return self._redis_client
    
    @property
    def chat_history_repo(self):
        """懒加载 ChatHistoryRepository"""
        if self._chat_history_repo is None:
            from api_gateway.repositories.chat_history_repository import ChatHistoryRepository
            self._chat_history_repo = ChatHistoryRepository()
        return self._chat_history_repo
    
    async def create_confirmation(
        self,
        job_id: str,
        match_result: MatchResult,
        original_intent: Dict[str, Any],
        db_session=None
    ) -> ConfirmationContext:
        """
        创建确认上下文（混合存储：Redis + 数据库）
        
        Args:
            job_id: 任务ID
            match_result: 匹配结果
            original_intent: 原始意图
            db_session: 数据库会话（可选，用于保存历史记录）
        
        Returns:
            确认上下文
        """
        confirmation_id = str(uuid.uuid4())
        now = now_shanghai()
        expires = now + timedelta(seconds=self.ttl)
        
        # 限制候选项数量
        candidates = match_result.matches[:self.max_display]
        
        ctx = ConfirmationContext(
            confirmation_id=confirmation_id,
            job_id=job_id,
            original_message=original_intent.get("raw_message", ""),
            parsed_intent=original_intent,
            candidates=candidates,
            created_at=now.isoformat(),
            expires_at=expires.isoformat()
        )
        
        # 1️⃣ 保存到 Redis（临时状态，用于快速查询）
        redis_key = f"confirmation:{job_id}"
        
        try:
            await self.redis_client.setex(
                redis_key,
                self.ttl,
                json.dumps(asdict(ctx), ensure_ascii=False, default=str)
            )
            logger.info(f"✅ 确认上下文已保存到 Redis: {redis_key} (TTL={self.ttl}s)")
        except Exception as e:
            logger.error(f"❌ 保存确认上下文到 Redis 失败: {e}", exc_info=True)
            raise
        
        # 2️⃣ 保存到数据库（历史记录，用于审计）
        if db_session:
            try:
                await self.chat_history_repo.save_message(
                    db_session,
                    session_id=job_id,
                    role="system",
                    content=f"找到 {len(match_result.matches)} 个匹配的零件，请选择",
                    message_type="confirmation_request",
                    metadata={
                        "confirmation_id": confirmation_id,
                        "candidates_count": len(match_result.matches),
                        "candidates": [
                            {
                                "subgraph_id": c.get("_source", {}).get("subgraph_id"),
                                "part_code": c.get("part_code"),
                                "part_name": c.get("part_name")
                            }
                            for c in candidates[:10]  # 只保存前10个，避免数据过大
                        ]
                    }
                )
                logger.info(f"✅ 确认请求已保存到数据库")
            except Exception as e:
                logger.warning(f"⚠️  保存确认请求到数据库失败: {e}")
                # 不抛出异常，因为 Redis 已保存成功
        
        return ctx
    
    def format_confirmation_message(
        self,
        candidates: List[Dict],
        operation: str
    ) -> str:
        """
        格式化确认消息
        
        Args:
            candidates: 候选零件列表
            operation: 操作描述
        
        Returns:
            格式化的确认消息
        """
        # 限制展示数量
        display_candidates = candidates[:self.max_display]
        total_count = len(candidates)
        
        lines = [f"找到 {total_count} 个匹配的零件，请选择：\n"]
        
        for i, candidate in enumerate(display_candidates, 1):
            # 提取关键信息
            info = MatchEvaluator.extract_match_info(candidate)
            
            lines.append(
                f"{i}. {info['subgraph_id']} ({info['part_name']}) - "
                f"材质: {info['material']} - 尺寸: {info['dimensions']}"
            )
        
        # 如果候选项过多，提示用户
        if total_count > self.max_display:
            lines.append(f"\n... 还有 {total_count - self.max_display} 个零件未显示")
            lines.append("建议缩小匹配范围以获得更精确的结果")
        
        lines.append('\n请输入序号选择（如 "1" 或 "1,3" 或 "全部"），或输入"取消"放弃操作')
        
        return "\n".join(lines)
    
    async def get_pending_confirmation(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        获取待确认的上下文（只从 Redis 查询，快速）
        
        Args:
            job_id: 任务ID
        
        Returns:
            确认上下文字典，如果不存在返回 None
        """
        redis_key = f"confirmation:{job_id}"
        
        try:
            ctx_json = await self.redis_client.get(redis_key)
            
            if not ctx_json:
                return None
            
            ctx_dict = json.loads(ctx_json)
            logger.debug(f"✅ 找到待确认上下文: {redis_key}")
            return ctx_dict
        
        except Exception as e:
            logger.error(f"❌ 获取待确认上下文失败: {e}", exc_info=True)
            return None
    
    async def handle_confirmation_response(
        self,
        job_id: str,
        user_response: str,
        db_session=None
    ) -> ActionResult:
        """
        处理用户的确认响应（混合存储：Redis + 数据库）
        
        Args:
            job_id: 任务ID
            user_response: 用户响应
            db_session: 数据库会话（可选，用于保存历史记录）
        
        Returns:
            操作结果
        """
        logger.info(f"🔍 处理确认响应: job_id={job_id}, response='{user_response}'")
        
        # 从 Redis 获取上下文
        ctx_dict = await self.get_pending_confirmation(job_id)
        
        if not ctx_dict:
            logger.warning(f"⚠️  确认上下文不存在或已过期")
            return ActionResult(
                status="error",
                message="确认已过期（超过5分钟），请重新输入原始指令",
                data={}
            )
        
        confirmation_id = ctx_dict["confirmation_id"]
        candidates = ctx_dict["candidates"]
        original_message = ctx_dict["original_message"]
        parsed_intent = ctx_dict["parsed_intent"]
        
        logger.info(f"✅ 找到确认上下文: confirmation_id={confirmation_id}, {len(candidates)} 个候选项")
        
        # 解析用户选择
        selected_indices = self._parse_user_selection(user_response, len(candidates))
        
        if selected_indices is None:
            # 用户取消
            logger.info(f"❌ 用户取消操作")
            
            # 1️⃣ 删除 Redis 中的临时状态
            redis_key = f"confirmation:{job_id}"
            await self.redis_client.delete(redis_key)
            
            # 2️⃣ 保存用户响应到数据库
            if db_session:
                try:
                    await self.chat_history_repo.save_message(
                        db_session,
                        session_id=job_id,
                        role="user",
                        content=user_response,
                        message_type="confirmation_response",
                        metadata={
                            "confirmation_id": confirmation_id,
                            "result": "cancelled"
                        }
                    )
                except Exception as e:
                    logger.warning(f"⚠️  保存取消响应到数据库失败: {e}")
            
            return ActionResult(
                status="cancelled",
                message="操作已取消",
                data={}
            )
        
        # 过滤候选项
        selected_candidates = [candidates[i] for i in selected_indices]
        logger.info(f"✅ 用户选择了 {len(selected_candidates)} 个零件")
        
        # 1️⃣ 删除 Redis 中的临时状态（已处理完成）
        redis_key = f"confirmation:{job_id}"
        await self.redis_client.delete(redis_key)
        
        # 2️⃣ 保存用户响应到数据库
        if db_session:
            try:
                await self.chat_history_repo.save_message(
                    db_session,
                    session_id=job_id,
                    role="user",
                    content=user_response,
                    message_type="confirmation_response",
                    metadata={
                        "confirmation_id": confirmation_id,
                        "selection_indices": selected_indices,
                        "selected_count": len(selected_candidates),
                        "result": "confirmed"
                    }
                )
            except Exception as e:
                logger.warning(f"⚠️  保存确认响应到数据库失败: {e}")
        
        # 返回选中的候选项（由调用方应用操作）
        return ActionResult(
            status="confirmed",
            message=f"已选择 {len(selected_candidates)} 个零件",
            data={
                "selected_candidates": selected_candidates,
                "original_message": original_message,
                "parsed_intent": parsed_intent
            }
        )
    def _parse_user_selection(
        self,
        response: str,
        max_count: int
    ) -> Optional[List[int]]:
        """
        解析用户选择
        
        支持的格式：
        - 单个序号: "1"
        - 多选: "1,3,5"
        - 范围: "1-5"
        - 全选: "全部", "所有", "all"
        - 取消: "取消", "不是", "cancel"
        
        Args:
            response: 用户响应
            max_count: 最大候选项数量
        
        Returns:
            选中的索引列表（0-based），如果取消返回 None
        """
        response = response.strip()
        
        logger.debug(f"🔍 解析用户选择: '{response}' (max_count={max_count})")
        
        # 取消
        if response.lower() in ["取消", "不是", "cancel", "no"]:
            logger.debug(f"❌ 用户取消")
            return None
        
        # 全选
        if response.lower() in ["全部", "所有", "all", "全选"]:
            logger.debug(f"✅ 用户选择全部")
            return list(range(max_count))
        
        # 单个序号
        if response.isdigit():
            idx = int(response) - 1  # 转换为0-based
            if 0 <= idx < max_count:
                logger.debug(f"✅ 用户选择单个: {idx}")
                return [idx]
            else:
                logger.warning(f"⚠️  序号超出范围: {response}")
                return []
        
        # 多选（逗号分隔）
        if "," in response:
            indices = []
            for part in response.split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < max_count:
                        indices.append(idx)
                    else:
                        logger.warning(f"⚠️  序号超出范围: {part}")
            
            if indices:
                logger.debug(f"✅ 用户选择多个: {indices}")
                return indices
            else:
                logger.warning(f"⚠️  无有效序号")
                return []
        
        # 范围（如 "1-5"）
        if "-" in response and response.count("-") == 1:
            parts = response.split("-")
            if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
                start = int(parts[0].strip()) - 1  # 转换为0-based
                end = int(parts[1].strip())  # end 是1-based，range 会自动处理
                
                if 0 <= start < end <= max_count:
                    indices = list(range(start, end))
                    logger.debug(f"✅ 用户选择范围: {indices}")
                    return indices
                else:
                    logger.warning(f"⚠️  范围超出边界: {response}")
                    return []
        
        # 无法解析
        logger.warning(f"⚠️  无法解析用户选择: '{response}'")
        return []
    
    async def get_confirmation_context(
        self,
        job_id: str,
        confirmation_id: str
    ) -> Optional[ConfirmationContext]:
        """
        获取确认上下文
        
        Args:
            job_id: 任务ID
            confirmation_id: 确认ID
        
        Returns:
            确认上下文，如果不存在返回 None
        """
        key = f"confirmation:{job_id}:{confirmation_id}"
        
        try:
            ctx_json = await self.redis_client.get(key)
            
            if not ctx_json:
                return None
            
            ctx_dict = json.loads(ctx_json)
            return ConfirmationContext(**ctx_dict)
        
        except Exception as e:
            logger.error(f"❌ 获取确认上下文失败: {e}", exc_info=True)
            return None
    
    async def cleanup_expired_confirmations(self, job_id: str):
        """
        清理过期的确认上下文
        
        Args:
            job_id: 任务ID
        """
        pattern = f"confirmation:{job_id}:*"
        
        try:
            # 获取所有匹配的键
            keys = await self.redis_client.keys(pattern)
            
            if keys:
                # Redis 的 TTL 会自动清理，这里只是记录日志
                logger.info(f"📊 当前有 {len(keys)} 个确认上下文")
        
        except Exception as e:
            logger.error(f"❌ 清理确认上下文失败: {e}", exc_info=True)
