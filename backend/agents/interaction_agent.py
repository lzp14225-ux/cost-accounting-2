"""
InteractionAgent - 数据审核和交互Agent (重构版)
负责人：人员B2

职责：
1. 监听 RabbitMQ 消息队列
2. 查询 3 个表（features, job_price_snapshots, subgraphs）
3. 通过 WebSocket 推送数据给前端
4. 接收用户自然语言修改指令
5. 解析自然语言并推送确认
6. 支持多轮修改循环
7. 用户确认后更新数据库

架构：事件驱动（非阻塞）
"""
from typing import Dict, Any, List, Optional
from .base_agent import BaseAgent, OpResult
import logging
import json
from datetime import datetime
import uuid
import hashlib
import os
from shared.timezone_utils import now_shanghai, format_shanghai_time

logger = logging.getLogger(__name__)


class InteractionAgent(BaseAgent):
    """
    数据审核和交互Agent
    
    核心功能：
    1. 启动审核流程（查询数据并推送）
    2. 处理用户修改（解析自然语言）
    3. 确认修改（更新数据库）
    
    设计模式：事件驱动
    - 每个方法独立执行
    - 通过 Redis 管理状态
    - 通过 WebSocket 推送消息
    """
    
    def __init__(self):
        """初始化 InteractionAgent"""
        super().__init__("InteractionAgent")
        
        # 懒加载依赖（避免循环导入）
        self._review_repo = None
        self._redis_client = None
        self._ws_manager = None
        self._nlp_parser = None
        self._persistence_manager = None
        
        logger.info("✅ InteractionAgent 初始化完成（审核模式）")
    
    @property
    def review_repo(self):
        """懒加载 ReviewRepository"""
        if self._review_repo is None:
            from api_gateway.repositories.review_repository import ReviewRepository
            self._review_repo = ReviewRepository()
        return self._review_repo
    
    @property
    def redis_client(self):
        """懒加载 Redis 客户端"""
        if self._redis_client is None:
            from api_gateway.utils.redis_client import redis_client
            self._redis_client = redis_client
        return self._redis_client
    
    @property
    def ws_manager(self):
        """懒加载 WebSocket 管理器"""
        if self._ws_manager is None:
            from api_gateway.websocket import manager
            self._ws_manager = manager
        return self._ws_manager
    
    @property
    def nlp_parser(self):
        """懒加载 NLP 解析器"""
        if self._nlp_parser is None:
            from .nlp_parser import NLPParser
            self._nlp_parser = NLPParser(use_llm=True)
        return self._nlp_parser
    
    @property
    def persistence_manager(self):
        """懒加载持久化管理器"""
        if self._persistence_manager is None:
            from .message_persistence_manager import get_persistence_manager
            self._persistence_manager = get_persistence_manager()
        return self._persistence_manager
    
    # ========== 核心方法 ==========
    
    async def start_review(
        self,
        job_id: str,
        db_session
    ) -> OpResult:
        """
        启动审核流程
        
        流程：
        1. 查询 4 个表的数据
        2. 检查数据完整性
        3. 如果有缺失字段,推送补全请求
        4. 如果数据完整,推送正常审核数据
        
        Args:
            job_id: 任务ID
            db_session: 数据库会话
        
        Returns:
            OpResult: 处理结果
        """
        logger.info(f"🚀 启动审核流程: job_id={job_id}")
        
        try:
            # 1. 获取分布式锁（防止并发）
            lock_key = f"review:lock:{job_id}"
            lock_acquired = await self._acquire_lock(lock_key, timeout=300)
            
            if not lock_acquired:
                return OpResult(
                    status="error",
                    message="该任务正在被其他用户审核中"
                )
            
            # 2. 查询所有数据
            logger.info(f"📊 查询审核数据...")
            raw_data = await self.review_repo.get_all_review_data(db_session, job_id)
            
            # 🆕 3. 构建展示视图
            logger.info(f"🔧 构建展示视图...")
            from agents.data_view_builder import DataViewBuilder
            
            # 添加调试日志
            logger.info(f"📊 原始数据统计: features={len(raw_data.get('features', []))}, "
                       f"subgraphs={len(raw_data.get('subgraphs', []))}, "
                       f"job_price_snapshots={len(raw_data.get('job_price_snapshots', []))}")
            
            display_view = DataViewBuilder.build_display_view(raw_data)
            logger.info(f"✅ 展示视图构建完成: {len(display_view)} 条记录")
            
            # 4. 数据完整性检查
            from shared.validators.completeness_validator import CompletenessValidator
            
            logger.info(f"🔍 检查数据完整性...")
            completeness_result = CompletenessValidator.check_data_completeness(raw_data)
            logger.info(f"📋 完整性检查结果: {completeness_result['summary']}")
            
            # 5. 计算数据版本（乐观锁）
            logger.info(f"🔐 计算数据版本...")
            data_version = self._calculate_data_version(raw_data)
            logger.debug(f"版本哈希数量: {len(data_version)}")
            
            # 🆕 6. 保存双层数据到 Redis
            logger.info(f"💾 保存双层数据到 Redis...")
            from agents.review_status import ReviewStatus
            
            await self._save_review_state(job_id, {
                "status": ReviewStatus.REVIEWING if completeness_result["is_complete"] else "pending_completion",
                "raw_data": raw_data,           # 🔑 原始 4 表数据
                "display_view": display_view,   # 🔑 展示视图
                "data_version": data_version,
                "modifications": [],
                "completeness": completeness_result,
                "created_at": now_shanghai().isoformat()
            })
            
            # 🆕 7. 推送展示视图到前端（而不是原始数据）
            logger.info(f"📤 推送展示视图到前端...")
            await self._push_display_view(job_id, display_view, db_session=db_session)
            
            # 8. 如果有缺失字段,再推送补全请求
            if not completeness_result["is_complete"]:
                logger.info(f"⚠️  发现缺失字段,生成补全建议...")
                
                # 生成 LLM 补全提示
                completion_prompt = CompletenessValidator.generate_completion_prompt(
                    completeness_result["missing_fields"],
                    raw_data
                )
                
                # 调用 LLM 生成补全建议
                completion_suggestion = await self._generate_completion_suggestion(
                    completion_prompt,
                    raw_data
                )
                
                # 推送补全请求到前端
                await self._push_completion_request(
                    job_id,
                    {
                        "missing_fields": completeness_result["missing_fields"],
                        "suggestion": completion_suggestion,
                        "message": "发现部分必填字段为空,请先补全这些字段"
                    },
                    db_session=db_session
                )
                
                logger.info(f"📤 补全请求已推送")
                
                return OpResult(
                    status="pending_completion",
                    message="数据不完整,需要补全必填字段",
                    data={
                        "job_id": job_id,
                        "completeness": completeness_result,
                        "suggestion": completion_suggestion
                    }
                )
            
            # 9. 数据完整,返回成功
            logger.info(f"✅ 审核流程启动成功")
            
            return OpResult(
                status="ok",
                message="审核流程已启动",
                data={
                    "job_id": job_id,
                    "features_count": len(raw_data["features"]),
                    "job_price_snapshots_count": len(raw_data.get("job_price_snapshots") or raw_data.get("price_snapshots", [])),
                    "subgraphs_count": len(raw_data["subgraphs"])
                }
            )
        
        except Exception as e:
            logger.error(f"❌ 启动审核失败: {e}", exc_info=True)
            return OpResult(
                status="error",
                message=f"启动审核失败: {str(e)}"
            )

    
    async def handle_modification(
        self,
        job_id: str,
        modification_text: str,
        user_id: str,
        db_session=None
    ) -> OpResult:
        """
        处理用户修改请求（集成意图识别）
        
        流程：
        1. 意图识别（使用 IntentRecognizer）
        2. 获取对应的 Handler
        3. 执行 Handler 处理
        4. 保存到 Redis
        5. 推送确认消息到前端
        
        Args:
            job_id: 任务ID
            modification_text: 用户的自然语言修改描述
            user_id: 用户ID
            db_session: 数据库会话（可选，用于持久化）
        
        Returns:
            OpResult: 处理结果（包含 intent 和 requires_confirmation 字段）
        """
        logger.info(f"🔧 处理修改请求: job_id={job_id}")
        logger.info(f"📝 修改内容: {modification_text}")
        
        try:
            # 1. 检查并续期锁（阶段2：锁自动续期）
            lock_key = f"review:lock:{job_id}"
            
            if not await self._check_lock(lock_key):
                # 锁不存在或已过期，尝试重新获取
                logger.warning(f"⚠️  锁已过期，尝试重新获取: job_id={job_id}")
                if not await self._acquire_lock(lock_key, timeout=300):
                    return OpResult(
                        status="error",
                        message="会话已被其他用户占用或已过期，请重新启动审核"
                    )
            else:
                # 锁存在，续期
                await self._renew_lock(lock_key, timeout=300)
                # 🆕 同时续期数据，防止数据过期但锁还在
                await self._renew_review_state(job_id, timeout=3600)
            
            # 2. 获取当前状态
            logger.info(f"📊 获取审核状态...")
            state = await self._get_review_state(job_id)
            if not state:
                logger.warning(f"⚠️  未找到审核状态")
                # 🆕 数据已过期，但锁还在，说明会话还活跃
                # 这种情况下，肯定没有未确认的修改（因为数据都不存在了）
                # 所以可以安全地重新加载初始数据
                if db_session:
                    logger.info(f"🔄 数据已过期，重新加载初始数据（不释放锁）...")
                    reload_result = await self._reload_initial_data(job_id, db_session)
                    if reload_result.status == "ok":
                        logger.info(f"✅ 初始数据重新加载成功")
                        
                        # 🆕 推送系统提示消息
                        await self._push_system_message(
                            job_id,
                            "已自动重新加载历史数据。",
                            db_session=db_session
                        )
                        
                        state = await self._get_review_state(job_id)
                    else:
                        logger.error(f"❌ 数据重新加载失败: {reload_result.message}")
                        return OpResult(
                            status="error",
                            message="审核会话已过期，请重新启动审核"
                        )
                else:
                    return OpResult(
                        status="error",
                        message="审核会话已过期，请重新启动审核（缺少数据库会话）"
                    )
            logger.info(f"✅ 状态获取成功")
            
            # 🆕 阶段2：检查状态权限
            from agents.review_status import ReviewStatus
            
            current_status = state.get("status")
            logger.info(f"📋 当前状态: {current_status}")
            
            # 🆕 允许在任何状态下修改（移除 COMPLETED 检查）
            # 如果状态是 COMPLETED，会在下面自动恢复为 REVIEWING
            
            # 3. 意图识别
            logger.info(f"🔍 识别意图...")
            from agents.intent_recognizer import IntentRecognizer
            import asyncio
            
            # 从环境变量读取配置
            use_llm = os.getenv("USE_LLM", "false").lower() == "true"
            use_chat_history = os.getenv("USE_CHAT_HISTORY", "true").lower() == "true"
            llm_timeout = float(os.getenv("LLM_TIMEOUT", "300"))  # 默认 5 分钟
            
            recognizer = IntentRecognizer(use_llm=use_llm, use_chat_history=use_chat_history)
            # 🆕 使用 raw_data 进行意图识别（向后兼容）
            # 🆕 添加 None 检查
            context_data = None
            if state:
                context_data = state.get("raw_data") or state.get("data")
            
            # 如果 context_data 仍然是 None，使用空字典
            if context_data is None:
                logger.warning(f"⚠️  context_data 为 None，使用空字典")
                context_data = {}
            
            try:
                # 添加超时控制
                # 🆕 传递 job_id 和 db_session 以支持聊天历史
                intent_result = await asyncio.wait_for(
                    recognizer.recognize(
                        modification_text,
                        context_data,
                        job_id=job_id,
                        db_session=db_session
                    ),
                    timeout=llm_timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"❌ 意图识别超时 ({llm_timeout}s)")
                return OpResult(
                    status="error",
                    message=f"意图识别超时，请稍后重试"
                )
            
            logger.info(f"✅ 意图识别完成: {intent_result.intent_type} (置信度: {intent_result.confidence})")
            
            # 4. 获取 Handler
            from agents.action_handlers import ActionHandlerFactory
            
            handler = ActionHandlerFactory.get_handler(intent_result.intent_type)
            
            if not handler:
                return OpResult(
                    status="error",
                    message=f"未找到对应的处理器: {intent_result.intent_type}"
                )
            
            # 5. 执行 Handler 处理
            logger.info(f"🔧 执行 Handler: {handler.__class__.__name__}")
            
            # ✅ 确保 state 有完整的数据
            # 如果 state 没有 raw_data，尝试从数据库重新加载
            if not state.get("raw_data"):
                logger.warning(f"⚠️  state 中没有 raw_data，尝试从数据库重新加载...")
                if db_session:
                    reload_result = await self._reload_initial_data(job_id, db_session)
                    if reload_result.status == "ok":
                        state = await self._get_review_state(job_id)
                        logger.info(f"✅ 数据重新加载成功")
                    else:
                        logger.error(f"❌ 数据重新加载失败: {reload_result.message}")
                        return OpResult(
                            status="error",
                            message="无法加载审核数据，请重新启动审核"
                        )
            
            # 🆕 构建完整的上下文（包含 raw_data 和 display_view）
            raw_data = state.get("raw_data") or {}
            display_view = state.get("display_view") or []
            
            # ✅ 检查 raw_data 的结构是否正确
            if raw_data:
                raw_data_keys = list(raw_data.keys())
                logger.info(f"🔍 raw_data keys: {raw_data_keys}")
                
                # ✅ 如果 raw_data 是嵌套结构（包含 'raw_data' 键），需要展开
                if "raw_data" in raw_data_keys and "display_view" in raw_data_keys:
                    logger.warning(f"⚠️  检测到嵌套的 raw_data 结构，正在展开...")
                    # 这是嵌套结构，需要获取内层的 raw_data
                    inner_raw_data = raw_data.get("raw_data")
                    if inner_raw_data and isinstance(inner_raw_data, dict):
                        raw_data = inner_raw_data
                        logger.info(f"✅ 展开后的 raw_data keys: {list(raw_data.keys())}")
                    else:
                        logger.error(f"❌ 内层 raw_data 无效: {type(inner_raw_data)}")
                        # 尝试从数据库重新加载
                        if db_session:
                            logger.info(f"🔄 从数据库重新加载完整数据...")
                            reload_result = await self._reload_initial_data(job_id, db_session)
                            if reload_result.status == "ok":
                                state = await self._get_review_state(job_id)
                                raw_data = state.get("raw_data") or {}
                                display_view = state.get("display_view") or []
                                logger.info(f"✅ 重新加载成功: raw_data keys={list(raw_data.keys())}")
            else:
                logger.warning(f"⚠️  raw_data 为空！")
            
            handler_context = {
                "raw_data": raw_data,
                "display_view": display_view,
                "data_version": state.get("data_version"),
                "user_id": user_id
            }
            
            # 获取数据库会话（从 state 中获取或创建新的）
            from shared.database import get_db
            async for db in get_db():
                action_result = await handler.handle(
                    intent_result,
                    job_id,
                    handler_context,  # 🔑 传递完整上下文
                    db
                )
                break
            
            # 6. 检查处理结果
            if action_result.status == "error":
                return OpResult(
                    status="error",
                    message=action_result.message
                )
            
            # 7. 如果需要确认，更新状态
            if action_result.requires_confirmation:
                # 🆕 更新 raw_data 和 display_view（修改后的数据）
                if action_result.data and "modified_data" in action_result.data:
                    logger.info(f"🔄 更新 Redis 中的 raw_data...")
                    state["raw_data"] = action_result.data["modified_data"]
                    logger.info(f"✅ raw_data 已更新")
                
                if action_result.data and "display_view" in action_result.data:
                    state["display_view"] = action_result.data["display_view"]
                    logger.info(f"✅ 展示视图已更新")
                
                # 🆕 重新建立版本基线（查询当前数据库状态）
                logger.info(f"🔐 重新建立版本基线...")
                from shared.database import get_db
                async for db in get_db():
                    current_db_data = await self.review_repo.get_all_review_data(db, job_id)
                    state["data_version"] = self._calculate_data_version(current_db_data)
                    logger.info(f"✅ 版本基线已更新（基于当前数据库状态）")
                    break
                
                # 记录修改历史
                modification_record = {
                    "id": str(uuid.uuid4()),
                    "text": modification_text,
                    "intent": intent_result.intent_type,
                    "user_id": user_id,
                    "timestamp": now_shanghai().isoformat()
                }
                
                # ✅ 确保 modifications 列表存在（向后兼容旧的 state）
                if "modifications" not in state:
                    state["modifications"] = []
                
                state["modifications"].append(modification_record)
                state["last_modified_at"] = now_shanghai().isoformat()
                
                # 保存到 Redis
                await self._save_review_state(job_id, state)
                
                # 🆕 不再推送修改确认消息（前端已通过 HTTP 响应知道操作成功）
                # 前端通过 HTTP 响应知道操作成功：
                # {"status": "ok", "intent": "FEATURE_RECOGNITION", "message": "...", "data": {...}}
                # 不需要再推送 WebSocket 消息
                
                # await self._push_modification_confirmation(
                #     job_id,
                #     modification_record,
                #     action_result.data,
                #     db_session=db_session
                # )
            
            # 8. 关闭 recognizer
            await recognizer.close()
            
            logger.info(f"✅ 修改处理完成")
            
            # 9. 返回结果（增加 intent 和 requires_confirmation 字段）
            return OpResult(
                status="ok",
                message=action_result.message,
                data={
                    "intent": intent_result.intent_type,
                    "requires_confirmation": action_result.requires_confirmation,
                    **action_result.data
                }
            )
        
        except Exception as e:
            logger.error(f"❌ 处理修改失败: {e}", exc_info=True)
            return OpResult(
                status="error",
                message=f"处理修改失败: {str(e)}"
            )
            return OpResult(
                status="error",
                message=f"处理修改失败: {str(e)}"
            )
    
    async def confirm_changes(
        self,
        job_id: str,
        user_id: str,
        db_session
    ) -> OpResult:
        """
        确认修改并更新数据库（使用 ConfirmHandler + 乐观锁）
        
        流程：
        1. 检查锁
        2. 获取 Redis 状态
        3. 🆕 重新查询数据库，检查版本冲突
        4. 使用 ConfirmHandler 处理确认
        5. 释放锁
        6. 清理 Redis 状态
        7. 推送完成消息
        
        Args:
            job_id: 任务ID
            user_id: 用户ID
            db_session: 数据库会话
        
        Returns:
            OpResult: 处理结果
        """
        logger.info(f"✅ 确认修改: job_id={job_id}")
        
        try:
            # 1. 检查锁，如果过期则尝试重新获取
            logger.info(f"🔒 检查分布式锁...")
            lock_key = f"review:lock:{job_id}"
            if not await self._check_lock(lock_key):
                logger.warning(f"⚠️  锁已过期，尝试重新获取")
                if not await self._acquire_lock(lock_key, timeout=300):
                    return OpResult(
                        status="error",
                        message="无法获取审核锁，可能有其他用户正在操作"
                    )
                logger.info(f"✅ 锁重新获取成功")
            else:
                logger.info(f"✅ 锁检查通过")
            
            # 2. 获取当前状态
            logger.info(f"📊 获取审核状态...")
            state = await self._get_review_state(job_id)
            if not state:
                logger.warning(f"⚠️  未找到审核状态")
                return OpResult(
                    status="error",
                    message="未找到审核会话"
                )
            logger.info(f"✅ 状态获取成功")
            
            # 🆕 3. 乐观锁：检查版本冲突（仅检测外部修改）
            logger.info(f"🔐 检查数据版本冲突...")
            
            # 续期锁（确认前）
            await self._renew_lock(lock_key, timeout=300)
            # 🆕 同时续期数据
            await self._renew_review_state(job_id, timeout=3600)
            
            logger.info(f"📊 查询当前数据库数据...")
            current_data = await self.review_repo.get_all_review_data(db_session, job_id)
            logger.info(f"✅ 数据查询完成")
            
            logger.info(f"🔐 计算数据版本...")
            current_version = self._calculate_data_version(current_data)
            logger.info(f"✅ 版本计算完成")
            
            # 对比版本（检测外部修改）
            # ⚠️ 注意：original_version 是审核开始时的数据库版本
            # 如果数据库版本发生变化，说明有外部系统修改了数据
            original_version = state.get("data_version", {})
            conflicts = []
            
            logger.debug(f"🔍 版本对比: original_keys={len(original_version)}, current_keys={len(current_version)}")
            
            for key, original_hash in original_version.items():
                current_hash = current_version.get(key)
                if current_hash and current_hash != original_hash:
                    table, record_id = key.split(":", 1)
                    logger.warning(f"⚠️  版本冲突: {key}, original={original_hash[:8]}, current={current_hash[:8]}")
                    conflicts.append({
                        "table": table,
                        "id": record_id,
                        "message": f"{record_id} 已被其他系统修改"
                    })
            
            # 如果有冲突，拒绝提交
            if conflicts:
                logger.warning(f"⚠️  检测到版本冲突: job_id={job_id}, conflicts={len(conflicts)}")
                return OpResult(
                    status="error",
                    message="数据已被其他系统修改，请重新审核",
                    data={"conflicts": conflicts}
                )
            
            logger.info(f"✅ 版本检查通过，无冲突")
            
            # 4. 使用 ConfirmHandler 处理确认
            logger.info(f"🔧 使用 ConfirmHandler 处理确认...")
            from agents.confirm_handler import ConfirmHandler
            
            confirm_handler = ConfirmHandler()
            result = await confirm_handler.handle_confirmation(
                job_id,
                user_id,
                db_session
            )
            
            # 检查结果
            if result["status"] == "error":
                return OpResult(
                    status="error",
                    message=result["message"]
                )
            
            # 🆕 5. 续期锁（不释放，保持会话活跃）
            await self._renew_lock(lock_key, timeout=300)
            # 🆕 同时续期数据
            await self._renew_review_state(job_id, timeout=3600)
            logger.info(f"🔄 锁和数据已续期，审核会话保持活跃")
            
            # 🆕 6. 保持 REVIEWING 状态（不改为 COMPLETED）
            state["last_confirmed_at"] = now_shanghai().isoformat()
            state["confirm_count"] = state.get("confirm_count", 0) + 1
            
            # 🆕 清空 modifications 列表（已确认的修改）
            state["modifications"] = []
            logger.info(f"✅ 已清空 modifications 列表")
            
            # 保存状态（保持 REVIEWING）
            await self._save_review_state(job_id, state)
            
            logger.info(f"✅ 操作已确认（第 {state['confirm_count']} 次），审核继续")
            
            # ❌ 不再清理状态（阶段2改动）
            # await self._clear_review_state(job_id)
            
            # 🆕 不再推送操作完成消息（前端已通过 HTTP 响应知道操作成功）
            # 前端通过 HTTP 响应知道操作成功：
            # {"status": "ok", "message": "操作已执行，可以继续修改", "data": {...}}
            # 不需要再推送 WebSocket 消息
            
            # await self._push_operation_completed(job_id, result, db_session=db_session)
            
            logger.info(f"✅ 操作确认完成，审核继续")
            
            return OpResult(
                status="ok",
                message="操作已执行，可以继续修改",
                data={
                    "job_id": job_id,
                    "confirm_count": state.get("confirm_count", 1),
                    **result.get("data", {})
                }
            )
        
        except Exception as e:
            logger.error(f"❌ 确认修改失败: {e}", exc_info=True)
            return OpResult(
                status="error",
                message=f"确认修改失败: {str(e)}"
            )

    
    async def refresh_data(
        self,
        job_id: str,
        db_session
    ) -> OpResult:
        """
        刷新审核数据（重新从数据库查询并更新 Redis）
        
        功能：
        1. 检查锁是否存在（必须在审核中）
        2. 重新查询 4 个表的数据
        3. 更新 Redis 中的数据
        4. 推送最新数据到前端
        5. 保持锁和状态不变
        
        Args:
            job_id: 任务ID
            db_session: 数据库会话
        
        Returns:
            OpResult: 处理结果
        """
        logger.info(f"🔄 刷新审核数据: job_id={job_id}")
        
        try:
            # 1. 检查锁是否存在
            lock_key = f"review:lock:{job_id}"
            if not await self._check_lock(lock_key):
                return OpResult(
                    status="error",
                    message="审核会话不存在或已过期，请重新启动审核"
                )
            
            # 2. 获取当前状态
            logger.info(f"📊 获取当前状态...")
            state = await self._get_review_state(job_id)
            if not state:
                return OpResult(
                    status="error",
                    message="未找到审核状态"
                )
            
            # 🆕 2.5. 检查是否有未确认的修改
            modifications = state.get("modifications", [])
            if modifications:
                logger.warning(f"⚠️  存在 {len(modifications)} 个未确认的修改，不能刷新数据")
                return OpResult(
                    status="error",
                    message=f"存在 {len(modifications)} 个未确认的修改，请先确认或取消修改后再刷新"
                )
            
            # 3. 重新查询数据库
            logger.info(f"📊 重新查询数据库...")
            raw_data = await self.review_repo.get_all_review_data(db_session, job_id)
            
            logger.info(f"📊 数据统计: features={len(raw_data.get('features', []))}, "
                       f"subgraphs={len(raw_data.get('subgraphs', []))}, "
                       f"job_price_snapshots={len(raw_data.get('job_price_snapshots') or raw_data.get('price_snapshots', []))}")
            
            # 4. 重新构建展示视图
            logger.info(f"🔧 重新构建展示视图...")
            from agents.data_view_builder import DataViewBuilder
            
            display_view = DataViewBuilder.build_display_view(raw_data)
            logger.info(f"✅ 展示视图构建完成: {len(display_view)} 条记录")
            
            # 5. 重新计算数据版本
            logger.info(f"🔐 重新计算数据版本...")
            data_version = self._calculate_data_version(raw_data)
            
            # 6. 更新 Redis 状态（保留原有的修改历史和确认次数）
            state["raw_data"] = raw_data
            state["display_view"] = display_view
            state["data_version"] = data_version
            state["last_refreshed_at"] = now_shanghai().isoformat()
            state["refresh_count"] = state.get("refresh_count", 0) + 1
            
            # 🆕 6.5. 数据完整性检查（可选）
            from shared.validators.completeness_validator import CompletenessValidator
            
            logger.info(f"🔍 检查数据完整性...")
            completeness_result = CompletenessValidator.check_data_completeness(raw_data)
            logger.info(f"📋 完整性检查结果: {completeness_result['summary']}")
            
            state["completeness"] = completeness_result
            
            await self._save_review_state(job_id, state)
            
            # 7. 续期锁
            await self._renew_lock(lock_key, timeout=300)
            # 🆕 数据已经通过 _save_review_state 重新保存，不需要额外续期
            
            # 8. 推送最新数据到前端
            logger.info(f"📤 推送最新数据到前端...")
            await self._push_display_view(job_id, display_view, db_session=db_session)
            
            # 🆕 9. 如果有缺失字段，推送补全请求
            if not completeness_result["is_complete"]:
                logger.info(f"⚠️  发现缺失字段，生成补全建议...")
                
                # 生成 LLM 补全提示
                completion_prompt = CompletenessValidator.generate_completion_prompt(
                    completeness_result["missing_fields"],
                    raw_data
                )
                
                # 调用 LLM 生成补全建议
                completion_suggestion = await self._generate_completion_suggestion(
                    completion_prompt,
                    raw_data
                )
                
                # 推送补全请求到前端
                await self._push_completion_request(
                    job_id,
                    {
                        "missing_fields": completeness_result["missing_fields"],
                        "suggestion": completion_suggestion,
                        "message": "刷新后发现部分必填字段为空，请补全这些字段"
                    },
                    db_session=db_session
                )
                
                logger.info(f"📤 补全请求已推送")
            
            logger.info(f"✅ 数据刷新完成（第 {state['refresh_count']} 次）")
            
            return OpResult(
                status="ok",
                message="数据已刷新",
                data={
                    "job_id": job_id,
                    "refresh_count": state["refresh_count"],
                    "features_count": len(raw_data["features"]),
                    "subgraphs_count": len(raw_data["subgraphs"]),
                    "job_price_snapshots_count": len(raw_data.get("job_price_snapshots") or raw_data.get("price_snapshots", [])),
                    "is_complete": completeness_result["is_complete"],  # 🆕 完整性状态
                    "missing_fields_count": len(completeness_result["missing_fields"])  # 🆕 缺失字段数量
                }
            )
        
        except Exception as e:
            logger.error(f"❌ 刷新数据失败: {e}", exc_info=True)
            return OpResult(
                status="error",
                message=f"刷新数据失败: {str(e)}"
            )
    
    async def _reload_initial_data(
        self,
        job_id: str,
        db_session
    ) -> OpResult:
        """
        重新加载初始数据（不获取锁，用于数据过期但锁还在的情况）
        
        功能：
        1. 假设锁已经存在（不尝试获取）
        2. 重新查询 4 个表的数据
        3. 构建展示视图
        4. 保存到 Redis（创建新的状态，modifications 为空）
        5. 推送数据到前端
        
        适用场景：
        - 数据已过期（Redis 中没有 state）
        - 但锁还在（说明会话还活跃）
        - 这种情况下肯定没有未确认的修改
        
        Args:
            job_id: 任务ID
            db_session: 数据库会话
        
        Returns:
            OpResult: 处理结果
        """
        logger.info(f"🔄 重新加载初始数据: job_id={job_id}")
        
        try:
            # 1. 查询所有数据
            logger.info(f"📊 查询审核数据...")
            raw_data = await self.review_repo.get_all_review_data(db_session, job_id)
            
            # 2. 构建展示视图
            logger.info(f"🔧 构建展示视图...")
            from agents.data_view_builder import DataViewBuilder
            
            logger.info(f"📊 原始数据统计: features={len(raw_data.get('features', []))}, "
                       f"subgraphs={len(raw_data.get('subgraphs', []))}, "
                       f"job_price_snapshots={len(raw_data.get('job_price_snapshots') or raw_data.get('price_snapshots', []))}")
            
            display_view = DataViewBuilder.build_display_view(raw_data)
            logger.info(f"✅ 展示视图构建完成: {len(display_view)} 条记录")
            
            # 3. 数据完整性检查
            from shared.validators.completeness_validator import CompletenessValidator
            
            logger.info(f"🔍 检查数据完整性...")
            completeness_result = CompletenessValidator.check_data_completeness(raw_data)
            logger.info(f"📋 完整性检查结果: {completeness_result['summary']}")
            
            # 4. 计算数据版本
            logger.info(f"🔐 计算数据版本...")
            data_version = self._calculate_data_version(raw_data)
            
            # 5. 保存到 Redis（创建新的状态）
            logger.info(f"💾 保存数据到 Redis...")
            from agents.review_status import ReviewStatus
            
            await self._save_review_state(job_id, {
                "status": ReviewStatus.REVIEWING if completeness_result["is_complete"] else "pending_completion",
                "raw_data": raw_data,
                "display_view": display_view,
                "data_version": data_version,
                "modifications": [],  # 🔑 空的修改列表
                "completeness": completeness_result,
                "created_at": now_shanghai().isoformat(),
                "reloaded_at": now_shanghai().isoformat()  # 标记为重新加载
            })
            
            # 6. 推送展示视图到前端
            logger.info(f"📤 推送展示视图到前端...")
            await self._push_display_view(job_id, display_view, db_session=db_session)
            
            # 7. 如果有缺失字段，推送补全请求
            if not completeness_result["is_complete"]:
                logger.info(f"⚠️  发现缺失字段，生成补全建议...")
                
                completion_prompt = CompletenessValidator.generate_completion_prompt(
                    completeness_result["missing_fields"],
                    raw_data
                )
                
                completion_suggestion = await self._generate_completion_suggestion(
                    completion_prompt,
                    raw_data
                )
                
                await self._push_completion_request(
                    job_id,
                    {
                        "missing_fields": completeness_result["missing_fields"],
                        "suggestion": completion_suggestion,
                        "message": "数据已重新加载，发现部分必填字段为空，请补全这些字段"
                    },
                    db_session=db_session
                )
            
            logger.info(f"✅ 初始数据重新加载成功")
            
            return OpResult(
                status="ok",
                message="数据已重新加载",
                data={
                    "job_id": job_id,
                    "features_count": len(raw_data["features"]),
                    "subgraphs_count": len(raw_data["subgraphs"]),
                    "job_price_snapshots_count": len(raw_data.get("job_price_snapshots") or raw_data.get("price_snapshots", [])),
                    "is_complete": completeness_result["is_complete"]
                }
            )
        
        except Exception as e:
            logger.error(f"❌ 重新加载数据失败: {e}", exc_info=True)
            return OpResult(
                status="error",
                message=f"重新加载数据失败: {str(e)}"
            )
    
    # ========== 公共查询方法 ==========
    
    async def get_review_state(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        获取审核状态（公共方法）
        
        Args:
            job_id: 任务ID
        
        Returns:
            审核状态字典，如果不存在返回 None
        """
        return await self._get_review_state(job_id)
    
    async def check_lock(self, job_id: str) -> bool:
        """
        检查审核锁状态（公共方法）
        
        Args:
            job_id: 任务ID
        
        Returns:
            是否已锁定
        """
        lock_key = f"review:lock:{job_id}"
        return await self._check_lock(lock_key)
    
    # ========== Redis 状态管理 ==========
    
    def _serialize_to_json(self, data: Any) -> str:
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
    
    def _calculate_data_version(self, data: Dict[str, Any]) -> Dict[str, str]:
        """
        计算数据版本哈希（乐观锁）
        
        为每条记录计算 MD5 哈希值，用于检测数据是否被修改
        
        Args:
            data: 审核数据（包含 4 个表）
        
        Returns:
            版本字典 {table:record_id: hash_value}
        """
        version = {}
        
        for table_name, records in data.items():
            if not isinstance(records, list):
                continue
            
            for record in records:
                # 获取记录 ID
                record_id = (
                    record.get('subgraph_id') or 
                    record.get('feature_id') or 
                    record.get('snapshot_id')
                )
                
                if not record_id:
                    continue
                
                # 计算哈希（使用 JSON 序列化保证一致性）
                record_str = json.dumps(record, sort_keys=True, ensure_ascii=False)
                hash_value = hashlib.md5(record_str.encode('utf-8')).hexdigest()
                
                # 保存版本
                key = f"{table_name}:{record_id}"
                version[key] = hash_value
        
        logger.debug(f"计算了 {len(version)} 条记录的版本哈希")
        return version
    
    async def _save_review_state(self, job_id: str, state: Dict[str, Any], ex: int = 3600):
        """
        保存审核状态到 Redis
        
        Args:
            job_id: 任务ID
            state: 状态数据
            ex: 过期时间（秒），默认 1 小时
            
        注意：
        - 锁的过期时间是 300 秒（5 分钟）
        - 数据的过期时间应该 >= 锁的过期时间
        - 建议使用默认值 3600 秒（1 小时）
        """
        key = f"review:state:{job_id}"
        
        # 🆕 确保过期时间至少是 300 秒（和锁一致）
        if ex < 300:
            logger.warning(f"⚠️  过期时间 {ex}s 小于锁超时 300s，自动调整为 300s")
            ex = 300
        
        await self.redis_client.set(
            key,
            self._serialize_to_json(state),
            ex=ex
        )
        logger.debug(f"💾 状态已保存: {key}, ex={ex}s")
    
    async def _renew_review_state(self, job_id: str, timeout: int = 3600) -> bool:
        """
        续期审核状态（和锁续期配合使用）
        
        每次用户操作时调用，延长数据的有效期，防止数据过期但锁还在
        
        Args:
            job_id: 任务ID
            timeout: 超时时间（秒），默认 1 小时
        
        Returns:
            是否成功续期
        """
        key = f"review:state:{job_id}"
        
        try:
            # 检查数据是否存在
            if await self.redis_client.exists(key):
                # 续期
                await self.redis_client.expire(key, timeout)
                logger.debug(f"🔄 数据续期成功: {key}, timeout={timeout}s")
                return True
            else:
                logger.warning(f"⚠️  数据不存在，无法续期: {key}")
                return False
        
        except Exception as e:
            logger.error(f"❌ 数据续期失败: {e}")
            return False
    
    async def _get_review_state(self, job_id: str) -> Optional[Dict[str, Any]]:
        """从 Redis 获取审核状态"""
        key = f"review:state:{job_id}"
        data = await self.redis_client.get(key)
        
        if data:
            return json.loads(data)
        return None
    
    async def _clear_review_state(self, job_id: str):
        """清理 Redis 中的审核状态"""
        key = f"review:state:{job_id}"
        await self.redis_client.delete(key)
        logger.debug(f"🗑️  状态已清理: {key}")
    
    # ========== 分布式锁管理 ==========
    
    async def _acquire_lock(self, lock_key: str, timeout: int = 300) -> bool:
        """
        获取分布式锁
        
        Args:
            lock_key: 锁的键
            timeout: 超时时间（秒）
        
        Returns:
            是否成功获取锁
        """
        try:
            # 使用 SET NX EX 原子操作
            result = await self.redis_client.set(
                lock_key,
                "locked",
                ex=timeout,
                nx=True
            )
            
            if result:
                logger.info(f"🔒 获取锁成功: {lock_key}")
                return True
            else:
                logger.warning(f"⚠️  锁已被占用: {lock_key}")
                return False
        
        except Exception as e:
            logger.error(f"❌ 获取锁失败: {e}")
            return False
    
    async def _check_lock(self, lock_key: str) -> bool:
        """检查锁是否存在"""
        exists = await self.redis_client.exists(lock_key)
        return exists > 0
    
    async def _release_lock(self, lock_key: str):
        """释放分布式锁"""
        await self.redis_client.delete(lock_key)
        logger.info(f"🔓 释放锁: {lock_key}")
    
    async def _renew_lock(self, lock_key: str, timeout: int = 300) -> bool:
        """
        续期锁（阶段2：锁自动续期）
        
        每次用户操作时调用，延长锁的有效期
        
        Args:
            lock_key: 锁的键
            timeout: 超时时间（秒），默认 5 分钟
        
        Returns:
            是否成功续期
        """
        try:
            # 检查锁是否存在
            if await self.redis_client.exists(lock_key):
                # 续期
                await self.redis_client.expire(lock_key, timeout)
                logger.info(f"🔄 锁续期成功: {lock_key}, timeout={timeout}s")
                return True
            else:
                logger.warning(f"⚠️  锁不存在，无法续期: {lock_key}")
                return False
        except Exception as e:
            logger.error(f"❌ 锁续期失败: {e}", exc_info=True)
            return False
    
    # ========== Redis Pub/Sub 推送（支持多进程）==========
    
    async def _push_review_data(self, job_id: str, data: Dict[str, Any], db_session=None):
        """推送审核数据到前端（通过 Redis Pub/Sub）+ 持久化"""
        message = {
            "type": "review_data",
            "job_id": job_id,
            "timestamp": now_shanghai().isoformat(),
            "data": data
        }
        
        # 发布到 Redis（支持多进程）
        channel = f"job:{job_id}:review"
        await self.redis_client.publish(channel, self._serialize_to_json(message))
        
        logger.info(f"📤 审核数据已发布到 Redis: {channel}")
        
        # 持久化到数据库
        if db_session:
            await self.persistence_manager.push_and_persist(
                job_id=job_id,
                ws_message=message,
                db_session=db_session
            )
    
    async def _push_display_view(self, job_id: str, display_view: List[Dict], db_session=None):
        """
        推送展示视图到前端（通过 Redis Pub/Sub）+ 持久化
        
        Args:
            job_id: 任务ID
            display_view: 展示视图（关联后的数据）
            db_session: 数据库会话（可选）
        """
        message = {
            "type": "review_display_view",
            "job_id": job_id,
            "timestamp": now_shanghai().isoformat(),
            "data": display_view
        }
        
        # 发布到 Redis（支持多进程）
        channel = f"job:{job_id}:review"
        await self.redis_client.publish(channel, self._serialize_to_json(message))
        
        logger.info(f"📤 展示视图已发布到 Redis: {channel}, 记录数: {len(display_view)}")
        
        # 持久化到数据库
        if db_session:
            await self.persistence_manager.push_and_persist(
                job_id=job_id,
                ws_message=message,
                db_session=db_session
            )
    
    async def _push_system_message(self, job_id: str, message_text: str, db_session=None):
        """
        推送系统提示消息到前端（通过 Redis Pub/Sub）+ 持久化
        
        Args:
            job_id: 任务ID
            message_text: 消息内容
            db_session: 数据库会话（可选）
        """
        message = {
            "type": "system_message",
            "job_id": job_id,
            "timestamp": now_shanghai().isoformat(),
            "message": message_text
        }
        
        # 发布到 Redis（支持多进程）
        channel = f"job:{job_id}:review"
        await self.redis_client.publish(channel, self._serialize_to_json(message))
        
        logger.info(f"📤 系统消息已发布到 Redis: {channel}")
        
        # 持久化到数据库
        if db_session:
            await self.persistence_manager.push_and_persist(
                job_id=job_id,
                ws_message=message,
                db_session=db_session
            )
    
    async def _push_completion_request(
        self,
        job_id: str,
        completion_data: Dict[str, Any],
        db_session=None
    ):
        """推送补全请求到前端（通过 Redis Pub/Sub）+ 持久化"""
        message = {
            "type": "completion_request",
            "job_id": job_id,
            "timestamp": now_shanghai().isoformat(),
            "data": completion_data
        }
        
        # 发布到 Redis
        channel = f"job:{job_id}:review"
        await self.redis_client.publish(channel, self._serialize_to_json(message))
        
        logger.info(f"📤 补全请求已发布到 Redis: {channel}")
        
        # 持久化到数据库
        if db_session:
            await self.persistence_manager.push_and_persist(
                job_id=job_id,
                ws_message=message,
                db_session=db_session
            )
    
    async def _push_modification_confirmation(
        self,
        job_id: str,
        modification: Dict[str, Any],
        modified_data: Dict[str, Any],
        db_session=None
    ):
        """推送修改确认消息到前端（通过 Redis Pub/Sub）+ 持久化"""
        message = {
            "type": "modification_confirmation",
            "job_id": job_id,
            "timestamp": now_shanghai().isoformat(),
            "modification": modification,
            "modifications": [modification],  # 兼容格式化器
            "modified_data": modified_data,
            "action_required": "confirm"  # 需要用户确认
        }
        
        # 发布到 Redis（支持多进程）
        channel = f"job:{job_id}:review"
        await self.redis_client.publish(channel, self._serialize_to_json(message))
        
        logger.info(f"📤 修改确认已发布到 Redis: {channel}")
        
        # 持久化到数据库
        if db_session:
            await self.persistence_manager.push_and_persist(
                job_id=job_id,
                ws_message=message,
                db_session=db_session
            )
    
    async def _push_completion_message(
        self,
        job_id: str,
        modifications: List[Dict[str, Any]],
        db_session=None
    ):
        """推送完成消息到前端（通过 Redis Pub/Sub）+ 持久化"""
        message = {
            "type": "review_completed",
            "job_id": job_id,
            "timestamp": now_shanghai().isoformat(),
            "modifications_count": len(modifications),
            "message": "审核已完成，数据已保存"
        }
        
        # 发布到 Redis（支持多进程）
        channel = f"job:{job_id}:review"
        await self.redis_client.publish(channel, self._serialize_to_json(message))
        
        logger.info(f"📤 完成消息已发布到 Redis: {channel}")
        
        # 持久化到数据库
        if db_session:
            await self.persistence_manager.push_and_persist(
                job_id=job_id,
                ws_message=message,
                db_session=db_session
            )
    
    async def _push_operation_completed(
        self,
        job_id: str,
        result: Dict[str, Any],
        db_session=None
    ):
        """推送操作完成消息到前端（通过 Redis Pub/Sub）+ 持久化"""
        message = {
            "type": "operation_completed",
            "job_id": job_id,
            "timestamp": now_shanghai().isoformat(),
            "action_type": result.get("data", {}).get("action_type"),
            "message": "操作已执行，可以继续修改",
            "result": result
        }
        
        # 发布到 Redis（支持多进程）
        channel = f"job:{job_id}:review"
        await self.redis_client.publish(channel, self._serialize_to_json(message))
        
        logger.info(f"📤 操作完成消息已发布到 Redis: {channel}")
        
        # 持久化到数据库
        if db_session:
            await self.persistence_manager.push_and_persist(
                job_id=job_id,
                ws_message=message,
                db_session=db_session
            )
    
    # ========== 自然语言解析（临时实现）==========
    
    def _simple_parse(
        self,
        text: str,
        current_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        简单的规则解析（临时实现）
        
        支持的模式：
        - "将 X 的 Y 改为 Z"
        - "修改 X 表的 Y 字段为 Z"
        
        Args:
            text: 用户输入的自然语言
            current_data: 当前数据
        
        Returns:
            解析后的修改列表
        """
        logger.info(f"🔍 简单解析: {text}")
        
        changes = []
        
        # TODO: 阶段3实现完整的 NLP 解析
        # 这里只是一个占位实现
        
        # 示例：解析 "将 subgraph_id=UP01 的 material 改为 P20"
        if "改为" in text or "修改" in text:
            changes.append({
                "table": "subgraphs",  # 假设修改 subgraphs 表
                "id": "UP01",  # 假设的 ID
                "field": "material",  # 假设的字段
                "value": "P20",  # 假设的值
                "original_text": text
            })
        
        logger.info(f"✅ 解析完成: {len(changes)} 个修改")
        
        return changes
    
    def _apply_changes(
        self,
        data: Dict[str, Any],
        changes: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        应用修改到数据
        
        Args:
            data: 原始数据
            changes: 修改列表
        
        Returns:
            修改后的数据
        """
        logger.info(f"🔧 应用 {len(changes)} 个修改")
        
        # 深拷贝数据
        import copy
        modified_data = copy.deepcopy(data)
        
        for change in changes:
            table = change["table"]
            record_id = change["id"]
            field = change["field"]
            value = change["value"]
            
            # 查找并修改对应的记录
            if table in modified_data:
                for record in modified_data[table]:
                    # 根据表类型判断 ID 字段
                    id_field = self._get_id_field(table)
                    
                    if record.get(id_field) == record_id:
                        record[field] = value
                        logger.info(f"✅ 修改: {table}.{id_field}={record_id}, {field}={value}")
                        break
        
        return modified_data
    
    def _get_id_field(self, table: str) -> str:
        """获取表的 ID 字段名（3表架构）"""
        id_fields = {
            "features": "feature_id",
            "job_price_snapshots": "snapshot_id",
            "subgraphs": "subgraph_id"
        }
        return id_fields.get(table, "id")
    
    # ========== SSE 流式聊天 ==========
    
    async def chat_stream(
        self,
        job_id: str,
        message: str,
        history: List[Dict[str, str]],
        current_data: Dict[str, Any]
    ):
        """
        流式聊天（SSE）
        
        功能：
        1. 接收用户消息
        2. 调用 LLM 生成响应
        3. 逐字流式输出
        
        Args:
            job_id: 任务ID
            message: 用户消息
            history: 历史消息
            current_data: 当前审核数据
        
        Yields:
            str: 响应内容片段
        """
        logger.info(f"💬 流式聊天: job_id={job_id}")
        logger.debug(f"消息: {message}")
        
        try:
            # 构建上下文信息
            context_info = self._build_context_info(current_data)
            
            # 获取当前时间（Asia/Shanghai）
            current_time = format_shanghai_time()
            
            # 构建 Prompt
            system_prompt = f"""你是一个模具数据审核助手。当前时间：{current_time}

当前审核数据概览：
{context_info}

你的职责：
1. 理解用户的修改需求
2. 解析自然语言指令
3. 提供友好的确认和建议
4. 支持多轮对话

重要限制：
- 你只能回答与模具数据核算、审核、修改、价格计算相关的问题
- 对于与核算无关的话题（如闲聊、其他领域问题等），请礼貌地告知用户你只能处理核算相关的问题
- 如果用户询问与核算无关的内容，请引导用户回到核算相关的话题

请用简洁、专业的语言回复用户。"""
            
            # 构建消息列表
            messages = [{"role": "system", "content": system_prompt}]
            
            # 添加历史消息
            for msg in history[-5:]:  # 只保留最近5轮对话
                messages.append(msg)
            
            # 添加当前消息
            messages.append({"role": "user", "content": message})
            
            # 调用 LLM 流式生成
            async for chunk in self._call_llm_stream(messages):
                yield chunk
        
        except Exception as e:
            logger.error(f"❌ 流式聊天失败: {e}", exc_info=True)
            yield f"\n\n抱歉，处理您的消息时出现错误：{str(e)}"
    
    async def chat(
        self,
        job_id: str,
        message: str,
        history: List[Dict[str, str]],
        current_data: Dict[str, Any]
    ) -> str:
        """
        非流式聊天（一次性返回）
        
        Args:
            job_id: 任务ID
            message: 用户消息
            history: 历史消息
            current_data: 当前审核数据
        
        Returns:
            完整响应内容
        """
        logger.info(f"💬 聊天: job_id={job_id}")
        
        # 收集所有流式片段
        response = ""
        async for chunk in self.chat_stream(job_id, message, history, current_data):
            response += chunk
        
        return response
    
    def _build_context_info(self, data: Dict[str, Any]) -> str:
        """构建上下文信息"""
        info_parts = []
        
        # 统计数据
        for table_name, records in data.items():
            if records:
                info_parts.append(f"- {table_name}: {len(records)} 条记录")
        
        # 子图详情（示例）
        if data.get("subgraphs"):
            info_parts.append("\n子图详情：")
            for sg in data["subgraphs"][:3]:  # 只显示前3个
                info_parts.append(
                    f"  - {sg.get('subgraph_id')}: "
                    f"材质={sg.get('material')}, "
                    f"重量={sg.get('weight')}kg"
                )
        
        return "\n".join(info_parts) if info_parts else "暂无数据"
    
    async def _call_llm_stream(self, messages: List[Dict[str, str]]):
        """
        调用 LLM 流式生成
        
        Args:
            messages: 消息列表
        
        Yields:
            str: 生成的文本片段
        """
        try:
            import os
            import httpx
            from openai import AsyncOpenAI
            
            # 从环境变量读取配置
            api_key = os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY
            base_url = os.getenv("OPENAI_BASE_URL") or settings.OPENAI_BASE_URL
            model = os.getenv("OPENAI_MODEL", "Qwen3-30B-A3B-Instruct")
            timeout = float(os.getenv("LLM_TIMEOUT") or settings.LLM_TIMEOUT)
            
            # 创建自定义 HTTP 客户端
            http_client = httpx.AsyncClient(
                timeout=timeout
            )
            
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=http_client,
                default_headers={"User-Agent": "curl/8.0"}
            )
            
            stream = await client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=0.7,
                max_tokens=2000
            )
            
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            
            # 关闭 HTTP 客户端
            await http_client.aclose()
        
        except Exception as e:
            logger.error(f"❌ LLM 调用失败: {e}")
            yield f"\n\n抱歉，AI 服务暂时不可用：{str(e)}"
    
    async def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """
        调用 LLM 非流式生成
        
        Args:
            messages: 消息列表
        
        Returns:
            完整响应内容
        """
        try:
            import os
            import httpx
            from openai import AsyncOpenAI
            
            # 从环境变量读取配置
            api_key = os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY
            base_url = os.getenv("OPENAI_BASE_URL") or settings.OPENAI_BASE_URL
            model = os.getenv("OPENAI_MODEL", "Qwen3-30B-A3B-Instruct")
            timeout = float(os.getenv("LLM_TIMEOUT") or settings.LLM_TIMEOUT)
            
            # 创建自定义 HTTP 客户端，设置 User-Agent
            http_client = httpx.AsyncClient(
                timeout=timeout
            )
            
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=http_client,
                default_headers={"User-Agent": "curl/8.0"}
            )
            
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=2000
            )
            
            # 关闭 HTTP 客户端
            await http_client.aclose()
            
            return response.choices[0].message.content
        
        except Exception as e:
            logger.error(f"❌ LLM 调用失败: {e}")
            return f"抱歉，AI 服务暂时不可用：{str(e)}"
    
    async def _generate_completion_suggestion(
        self,
        prompt: str,
        context_data: Dict[str, Any]
    ) -> str:
        """
        使用 LLM 生成补全建议
        
        Args:
            prompt: 补全提示
            context_data: 上下文数据
        
        Returns:
            LLM 生成的补全建议
        """
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是一个模具制造领域的专家,擅长根据零件信息推理缺失的参数。"
                        "请根据零件编号、加工说明、热处理等信息,推理出合理的尺寸和材质。"
                        "回答要简洁明了,直接给出补全建议。"
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
            
            # 调用 LLM
            response = await self._call_llm(messages)
            
            logger.info(f"✅ LLM 补全建议生成成功")
            return response
        
        except Exception as e:
            logger.error(f"❌ LLM 补全建议生成失败: {e}")
            return "请根据零件信息手动补全缺失的字段"
    
    # ========== 兼容旧接口（保留）==========
    
    async def process(self, context: Dict[str, Any]) -> OpResult:
        """
        兼容旧接口（保留用于向后兼容）
        
        注意：新的审核系统不使用此方法
        """
        logger.warning("⚠️  使用了旧的 process() 接口，建议使用新的审核方法")
        
        return OpResult(
            status="error",
            message="此方法已废弃，请使用 start_review/handle_modification/confirm_changes"
        )
from shared.config import settings
