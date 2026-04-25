"""
ConfirmHandler - 确认处理器
负责人：人员B2

处理用户确认操作，根据 action_type 执行不同的操作
"""
import logging
import json
import os
from typing import Dict, Any, Optional, List, Set
from datetime import datetime
import httpx
from shared.config import settings

logger = logging.getLogger(__name__)


class ConfirmHandler:
    """
    确认处理器
    
    功能：
    1. 从 Redis 获取 pending_action
    2. 根据 action_type 执行不同操作：
       - DATA_MODIFICATION → 保存到数据库
       - FEATURE_RECOGNITION → 调用特征识别 API
       - PRICE_CALCULATION → 调用价格计算 API
    3. 清理 Redis 中的 pending_action
    """
    
    def __init__(self):
        """初始化 ConfirmHandler"""
        self._redis_client = None
        self._review_repo = None
        self.api_timeout = float(os.getenv("API_TIMEOUT", "60"))  # 外部API超时，默认60秒
        logger.info("✅ ConfirmHandler 初始化完成")
    
    @property
    def redis_client(self):
        """懒加载 Redis 客户端"""
        if self._redis_client is None:
            from api_gateway.utils.redis_client import redis_client
            self._redis_client = redis_client
        return self._redis_client
    
    @property
    def review_repo(self):
        """懒加载 ReviewRepository"""
        if self._review_repo is None:
            from api_gateway.repositories.review_repository import ReviewRepository
            self._review_repo = ReviewRepository()
        return self._review_repo
    
    async def handle_confirmation(
        self,
        job_id: str,
        user_id: str,
        db_session
    ) -> Dict[str, Any]:
        """
        处理确认操作
        
        Args:
            job_id: 任务ID
            user_id: 用户ID
            db_session: 数据库会话
        
        Returns:
            处理结果字典
        """
        logger.info(f"✅ 处理确认: job_id={job_id}")
        
        try:
            # 1. 获取 pending_action
            logger.info(f"📊 获取 pending_action...")
            pending_action = await self._get_pending_action(job_id)
            
            if not pending_action:
                logger.warning(f"⚠️  未找到 pending_action")
                return {
                    "status": "error",
                    "message": "未找到待确认的操作"
                }
            
            action_type = pending_action.get("action_type")
            logger.info(f"📋 操作类型: {action_type}")
            
            # 2. 根据类型执行操作
            if action_type == "DATA_MODIFICATION":
                result = await self._confirm_data_modification(
                    job_id,
                    pending_action,
                    db_session
                )
            elif action_type == "FEATURE_RECOGNITION":
                result = await self._confirm_feature_recognition(
                    job_id,
                    pending_action
                )
            elif action_type == "PRICE_CALCULATION":
                result = await self._confirm_price_calculation(
                    job_id,
                    pending_action
                )
            elif action_type == "WEIGHT_PRICE_CALCULATION":
                result = await self._confirm_weight_price_calculation(
                    job_id,
                    pending_action
                )
            else:
                return {
                    "status": "error",
                    "message": f"未知的操作类型: {action_type}"
                }
            
            # 3. 只有操作成功时才清理 pending_action
            if result.get("status") == "ok":
                await self._clear_pending_action(job_id)
                logger.info(f"✅ pending_action 已清理")
            else:
                logger.warning(f"⚠️  操作失败，保留 pending_action 以便重试")
            
            logger.info(f"✅ 确认处理完成: {result.get('status')}")
            return result
        
        except Exception as e:
            logger.error(f"❌ 处理确认失败: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"处理确认失败: {str(e)}"
            }
    
    def _convert_datetime_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        转换数据中的 ISO 字符串为 datetime 对象
        
        Args:
            data: 包含多个表数据的字典
        
        Returns:
            转换后的数据
        """
        datetime_fields = ["modified_at", "created_at", "updated_at"]
        
        for table_name, records in data.items():
            if not isinstance(records, list):
                continue
            
            for record in records:
                for field in datetime_fields:
                    if field in record and isinstance(record[field], str):
                        try:
                            record[field] = datetime.fromisoformat(record[field])
                        except (ValueError, TypeError):
                            pass  # 保持原值
        
        return data

    def _extract_all_subgraph_ids(self, modified_data: Dict[str, Any]) -> List[str]:
        """从修改后的审核数据中提取全部子图 ID。"""
        subgraph_ids: List[str] = []
        seen: Set[str] = set()

        for record in modified_data.get("subgraphs", []) or []:
            subgraph_id = record.get("subgraph_id")
            if not subgraph_id:
                continue
            subgraph_id = str(subgraph_id)
            if subgraph_id in seen:
                continue
            seen.add(subgraph_id)
            subgraph_ids.append(subgraph_id)

        return subgraph_ids

    def _collect_recalculation_subgraph_ids(self, pending_action: Dict[str, Any]) -> List[str]:
        """
        自动重算与原先“重新计算”指令保持一致，一律按整单所有物料重算。
        """
        modified_data = pending_action.get("modified_data") or {}
        all_subgraph_ids = self._extract_all_subgraph_ids(modified_data)
        logger.info("🔄 自动重新计算按整单执行，子图数量=%s", len(all_subgraph_ids))
        return all_subgraph_ids

    async def _trigger_auto_recalculation(
        self,
        job_id: str,
        subgraph_ids: List[str]
    ) -> Dict[str, Any]:
        """提交自动重算任务，但不影响已落库的数据修改结果。"""
        if not subgraph_ids:
            return {
                "attempted": False,
                "submitted": False,
                "message": "未找到可重算的子图",
                "subgraph_ids": []
            }

        try:
            recalc_result = await self._confirm_price_calculation(
                job_id,
                {
                    "api_params": {
                        "job_id": job_id,
                        "subgraph_ids": subgraph_ids,
                        "user_params": {}
                    }
                }
            )

            return {
                "attempted": True,
                "submitted": recalc_result.get("status") == "ok",
                "message": recalc_result.get("message"),
                "subgraph_ids": subgraph_ids,
                "task_id": recalc_result.get("data", {}).get("task_id"),
                "api_response": recalc_result.get("data", {}).get("api_response"),
                "details": recalc_result.get("details")
            }
        except Exception as e:
            logger.error(f"❌ 自动提交重新计算异常: {e}", exc_info=True)
            return {
                "attempted": True,
                "submitted": False,
                "message": f"自动重新计算提交异常: {str(e)}",
                "subgraph_ids": subgraph_ids
            }
    
    async def _confirm_data_modification(
        self,
        job_id: str,
        pending_action: Dict[str, Any],
        db_session
    ) -> Dict[str, Any]:
        """
        确认数据修改
        
        Args:
            job_id: 任务ID
            pending_action: 待确认的操作
            db_session: 数据库会话
        
        Returns:
            处理结果
        """
        logger.info(f"💾 确认数据修改...")
        
        try:
            # 获取修改后的数据
            modified_data = pending_action.get("modified_data")
            
            if not modified_data:
                return {
                    "status": "error",
                    "message": "未找到修改后的数据"
                }
            
            # 🆕 转换 ISO 字符串为 datetime 对象
            modified_data = self._convert_datetime_fields(modified_data)
            
            # 更新数据库
            await self.review_repo.update_all_review_data(
                db_session,
                job_id,
                modified_data
            )
            
            # 提交事务
            await db_session.commit()
            
            logger.info(f"✅ 数据修改已保存到数据库")

            auto_recalculation_result = {
                "attempted": False,
                "submitted": False,
                "message": "未触发自动重新计算",
                "subgraph_ids": []
            }

            recalculation_subgraph_ids = self._collect_recalculation_subgraph_ids(pending_action)
            if recalculation_subgraph_ids:
                logger.info(
                    "🔄 数据修改确认完成，开始自动提交重新计算: job_id=%s, subgraph_count=%s",
                    job_id,
                    len(recalculation_subgraph_ids)
                )
                auto_recalculation_result = await self._trigger_auto_recalculation(
                    job_id,
                    recalculation_subgraph_ids
                )
            else:
                logger.warning("⚠️  数据修改已保存，但未解析出可重算的子图范围: job_id=%s", job_id)

            message = "数据修改已保存"
            if auto_recalculation_result.get("submitted"):
                message = "数据修改已保存，已自动提交重新计算"
            elif auto_recalculation_result.get("attempted"):
                message = "数据修改已保存，但自动重新计算提交失败，请手动重新计算"
            
            return {
                "status": "ok",
                "message": message,
                "data": {
                    "action_type": "DATA_MODIFICATION",
                    "changes_count": len(pending_action.get("changes", [])),
                    "auto_recalculation_attempted": auto_recalculation_result.get("attempted", False),
                    "auto_recalculation_submitted": auto_recalculation_result.get("submitted", False),
                    "auto_recalculation_message": auto_recalculation_result.get("message"),
                    "auto_recalculation_subgraph_ids": auto_recalculation_result.get("subgraph_ids", []),
                    "auto_recalculation_task_id": auto_recalculation_result.get("task_id")
                }
            }
        
        except Exception as e:
            # 回滚事务
            await db_session.rollback()
            logger.error(f"❌ 数据修改失败: {e}")
            raise
    
    async def _confirm_feature_recognition(
        self,
        job_id: str,
        pending_action: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        确认特征识别
        
        Args:
            job_id: 任务ID
            pending_action: 待确认的操作
        
        Returns:
            处理结果
        """
        logger.info(f"🔍 确认特征识别...")
        
        try:
            # 获取 API 参数
            api_params = pending_action.get("api_params")
            
            if not api_params:
                return {
                    "status": "error",
                    "message": "未找到 API 参数"
                }
            
            # 调用特征识别 API
            api_url = settings.FEATURE_REPROCESS_API_URL
            
            logger.info(f"📤 调用特征识别 API: {api_url}")
            logger.info(f"📋 请求参数: {api_params}")
            
            # 🆕 根据服务管理员建议：使用 60 秒超时 + 重试机制
            headers = {
                "Content-Type": "application/json"
            }
            
            # 重试配置
            max_retries = 3
            retry_delay = 5  # 秒
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    if attempt > 0:
                        logger.info(f"🔄 第 {attempt + 1} 次重试...")
                        import asyncio
                        await asyncio.sleep(retry_delay)
                    
                    async with httpx.AsyncClient(timeout=self.api_timeout) as client:
                        response = await client.post(
                            api_url,
                            json=api_params,
                            headers=headers
                        )
                        response.raise_for_status()
                        result = response.json()
                        
                        # 成功，跳出重试循环
                        break
                        
                except httpx.HTTPStatusError as e:
                    last_error = e
                    # 502/503 可能是服务器忙，值得重试
                    if e.response.status_code in [502, 503] and attempt < max_retries - 1:
                        logger.warning(f"⚠️  服务器返回 {e.response.status_code}，{retry_delay}秒后重试...")
                        continue
                    else:
                        raise
                        
                except httpx.TimeoutException as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        logger.warning(f"⚠️  请求超时，{retry_delay}秒后重试...")
                        continue
                    else:
                        raise
            
            # 如果所有重试都失败，抛出最后一个错误
            if last_error and 'result' not in locals():
                raise last_error
            
            logger.info(f"✅ 特征识别 API 调用成功")
            logger.info(f"📋 响应: {result}")
            
            return {
                "status": "ok",
                "message": "特征识别任务已提交",
                "data": {
                    "action_type": "FEATURE_RECOGNITION",
                    "task_id": result.get("data", {}).get("task_id"),
                    "subgraph_ids": api_params.get("subgraph_ids"),
                    "api_response": result
                }
            }
        
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ API 调用失败: {e.response.status_code} - {e.response.text}")
            
            # 根据不同的错误码返回更友好的消息
            if e.response.status_code == 502:
                error_msg = "特征识别服务暂时不可用（502 Bad Gateway），请稍后重试或联系管理员检查服务状态"
            elif e.response.status_code == 503:
                error_msg = "特征识别服务正在维护中（503 Service Unavailable），请稍后重试"
            elif e.response.status_code == 504:
                error_msg = "特征识别服务响应超时（504 Gateway Timeout），请稍后重试"
            else:
                error_msg = f"特征识别 API 调用失败: HTTP {e.response.status_code}"
            
            return {
                "status": "error",
                "message": error_msg,
                "details": {
                    "status_code": e.response.status_code,
                    "response": e.response.text[:200]
                }
            }
        except httpx.TimeoutException as e:
            logger.error(f"❌ API 调用超时: {e}")
            return {
                "status": "error",
                "message": "特征识别服务响应超时，请稍后重试"
            }
        except Exception as e:
            logger.error(f"❌ 特征识别失败: {e}")
            raise
    
    async def _confirm_price_calculation(
        self,
        job_id: str,
        pending_action: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        确认价格计算
        
        Args:
            job_id: 任务ID
            pending_action: 待确认的操作
        
        Returns:
            处理结果
        """
        logger.info(f"💰 确认价格计算...")
        
        try:
            # 获取 API 参数
            api_params = pending_action.get("api_params")
            
            if not api_params:
                return {
                    "status": "error",
                    "message": "未找到 API 参数"
                }
            
            # 调用价格计算 API
            api_url = settings.PRICING_RECALCULATE_API_URL
            
            logger.info(f"📤 调用价格计算 API: {api_url}")
            logger.info(f"📋 请求参数: {api_params}")
            
            # 🆕 根据服务管理员建议：
            # 1. 使用 60 秒超时（不是 300 秒）
            # 2. 明确设置 Content-Type
            # 3. 添加重试机制（服务器可能正在处理其他请求）
            headers = {
                "Content-Type": "application/json"
            }
            
            # 重试配置
            max_retries = 3
            retry_delay = 5  # 秒
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    if attempt > 0:
                        logger.info(f"🔄 第 {attempt + 1} 次重试...")
                        import asyncio
                        await asyncio.sleep(retry_delay)
                    
                    async with httpx.AsyncClient(timeout=self.api_timeout) as client:
                        response = await client.post(
                            api_url,
                            json=api_params,
                            headers=headers
                        )
                        response.raise_for_status()
                        result = response.json()
                        
                        # 成功，跳出重试循环
                        break
                        
                except httpx.HTTPStatusError as e:
                    last_error = e
                    # 502/503 可能是服务器忙，值得重试
                    if e.response.status_code in [502, 503] and attempt < max_retries - 1:
                        logger.warning(f"⚠️  服务器返回 {e.response.status_code}，{retry_delay}秒后重试...")
                        continue
                    else:
                        # 其他错误或最后一次重试失败，抛出异常
                        raise
                        
                except httpx.TimeoutException as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        logger.warning(f"⚠️  请求超时，{retry_delay}秒后重试...")
                        continue
                    else:
                        raise
            
            # 如果所有重试都失败，抛出最后一个错误
            if last_error and 'result' not in locals():
                raise last_error
            
            logger.info(f"✅ 价格计算 API 调用成功")
            logger.info(f"📋 响应: {result}")
            
            return {
                "status": "ok",
                "message": "价格计算任务已提交",
                "data": {
                    "action_type": "PRICE_CALCULATION",
                    "task_id": result.get("data", {}).get("task_id"),
                    "subgraph_ids": api_params.get("subgraph_ids"),
                    "api_response": result
                }
            }
        
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ API 调用失败（已重试 {max_retries} 次）: {e.response.status_code} - {e.response.text}")
            
            # 根据不同的错误码返回更友好的消息
            if e.response.status_code == 502:
                error_msg = "价格计算服务暂时不可用（502 Bad Gateway）。可能原因：服务器正在处理其他请求。建议：等待几分钟后重试，或联系管理员检查服务状态"
            elif e.response.status_code == 503:
                error_msg = "价格计算服务正在维护中（503 Service Unavailable），请稍后重试"
            elif e.response.status_code == 504:
                error_msg = "价格计算服务响应超时（504 Gateway Timeout），请稍后重试"
            else:
                error_msg = f"价格计算 API 调用失败: HTTP {e.response.status_code}"
            
            return {
                "status": "error",
                "message": error_msg,
                "details": {
                    "status_code": e.response.status_code,
                    "response": e.response.text[:200],
                    "retries": max_retries
                }
            }
        except httpx.TimeoutException as e:
            logger.error(f"❌ API 调用超时（已重试 {max_retries} 次）: {e}")
            return {
                "status": "error",
                "message": f"价格计算服务响应超时（已重试 {max_retries} 次），服务器可能正在处理其他请求，请稍后重试"
            }
        except Exception as e:
            logger.error(f"❌ 价格计算失败: {e}")
            raise
    
    async def _confirm_weight_price_calculation(
        self,
        job_id: str,
        pending_action: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        确认按重量计算价格
        
        Args:
            job_id: 任务ID
            pending_action: 待确认的操作
        
        Returns:
            处理结果
        """
        logger.info(f"⚖️  确认按重量计算价格...")
        
        try:
            # 获取 API 参数和 URL
            api_params = pending_action.get("api_params")
            api_url = pending_action.get("api_url") or settings.WEIGHT_PRICE_API_URL
            
            if not api_params:
                return {
                    "status": "error",
                    "message": "未找到 API 参数"
                }
            
            logger.info(f"📤 调用按重量计算 API: {api_url}")
            logger.info(f"📋 请求参数: {api_params}")
            
            headers = {
                "Content-Type": "application/json"
            }
            
            # 重试配置
            max_retries = 3
            retry_delay = 5  # 秒
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    if attempt > 0:
                        logger.info(f"🔄 第 {attempt + 1} 次重试...")
                        import asyncio
                        await asyncio.sleep(retry_delay)
                    
                    async with httpx.AsyncClient(timeout=self.api_timeout) as client:
                        response = await client.post(
                            api_url,
                            json=api_params,
                            headers=headers
                        )
                        response.raise_for_status()
                        result = response.json()
                        
                        # 成功，跳出重试循环
                        break
                        
                except httpx.HTTPStatusError as e:
                    last_error = e
                    # 502/503 可能是服务器忙，值得重试
                    if e.response.status_code in [502, 503] and attempt < max_retries - 1:
                        logger.warning(f"⚠️  服务器返回 {e.response.status_code}，{retry_delay}秒后重试...")
                        continue
                    else:
                        raise
                        
                except httpx.TimeoutException as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        logger.warning(f"⚠️  请求超时，{retry_delay}秒后重试...")
                        continue
                    else:
                        raise
            
            # 如果所有重试都失败，抛出最后一个错误
            if last_error and 'result' not in locals():
                raise last_error
            
            logger.info(f"✅ 按重量计算 API 调用成功")
            logger.info(f"📋 响应: {result}")
            
            return {
                "status": "ok",
                "message": "按重量计算任务已提交",
                "data": {
                    "action_type": "WEIGHT_PRICE_CALCULATION",
                    "task_id": result.get("data", {}).get("task_id"),
                    "subgraph_ids": api_params.get("subgraph_ids"),
                    "api_response": result
                }
            }
        
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ API 调用失败（已重试 {max_retries} 次）: {e.response.status_code} - {e.response.text}")
            
            # 根据不同的错误码返回更友好的消息
            if e.response.status_code == 502:
                error_msg = "按重量计算服务暂时不可用（502 Bad Gateway）。可能原因：服务器正在处理其他请求。建议：等待几分钟后重试，或联系管理员检查服务状态"
            elif e.response.status_code == 503:
                error_msg = "按重量计算服务正在维护中（503 Service Unavailable），请稍后重试"
            elif e.response.status_code == 504:
                error_msg = "按重量计算服务响应超时（504 Gateway Timeout），请稍后重试"
            else:
                error_msg = f"按重量计算 API 调用失败: HTTP {e.response.status_code}"
            
            return {
                "status": "error",
                "message": error_msg,
                "details": {
                    "status_code": e.response.status_code,
                    "response": e.response.text[:200],
                    "retries": max_retries
                }
            }
        except httpx.TimeoutException as e:
            logger.error(f"❌ API 调用超时（已重试 {max_retries} 次）: {e}")
            return {
                "status": "error",
                "message": f"按重量计算服务响应超时（已重试 {max_retries} 次），服务器可能正在处理其他请求，请稍后重试"
            }
        except Exception as e:
            logger.error(f"❌ 按重量计算失败: {e}")
            raise
    
    async def _get_pending_action(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        从 Redis 获取 pending_action
        
        Args:
            job_id: 任务ID
        
        Returns:
            pending_action 字典，如果不存在返回 None
        """
        key = f"review:pending_action:{job_id}"
        data = await self.redis_client.get(key)
        
        if data:
            return json.loads(data)
        return None
    
    async def _clear_pending_action(self, job_id: str):
        """
        清理 Redis 中的 pending_action
        
        Args:
            job_id: 任务ID
        """
        key = f"review:pending_action:{job_id}"
        await self.redis_client.delete(key)
        logger.debug(f"🗑️  pending_action 已清理: {key}")
