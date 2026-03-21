#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聊天会话服务层
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from app.services.database import db_manager
from app.models.chat_session import ChatSession

logger = logging.getLogger(__name__)


class ChatSessionService:
    """聊天会话服务"""
    
    def __init__(self):
        self.db = db_manager
    
    def get_session_by_id(self, session_id: str) -> Optional[ChatSession]:
        """根据会话ID获取会话信息"""
        try:
            query = """
            SELECT session_id, job_id, user_id, name, status, metadata,
                   created_at, updated_at
            FROM chat_sessions
            WHERE session_id = %s
            """
            result = self.db.execute_query(query, (session_id,), fetch_one=True)
            
            if result:
                return ChatSession.from_dict(result)
            return None
            
        except Exception as e:
            logger.error(f"获取会话信息失败: {e}")
            return None
    
    def get_session_by_job_id(self, job_id: str, user_id: Optional[str] = None) -> Optional[ChatSession]:
        """根据任务ID获取会话信息"""
        try:
            if user_id:
                query = """
                SELECT session_id, job_id, user_id, name, status, metadata,
                       created_at, updated_at
                FROM chat_sessions
                WHERE job_id = %s AND user_id = %s
                """
                result = self.db.execute_query(query, (job_id, user_id), fetch_one=True)
            else:
                query = """
                SELECT session_id, job_id, user_id, name, status, metadata,
                       created_at, updated_at
                FROM chat_sessions
                WHERE job_id = %s
                """
                result = self.db.execute_query(query, (job_id,), fetch_one=True)
            
            if result:
                return ChatSession.from_dict(result)
            return None
            
        except Exception as e:
            logger.error(f"根据job_id获取会话信息失败: {e}")
            return None
    
    def update_session_name_by_job_id(
        self,
        job_id: str,
        name: str,
        user_id: Optional[str] = None
    ) -> tuple[bool, str, Optional[ChatSession]]:
        """
        根据任务ID更新会话名称
        
        Args:
            job_id: 任务ID
            name: 新的会话名称
            user_id: 用户ID（可选，用于权限验证）
        
        Returns:
            (成功标志, 消息, 更新后的会话对象)
        """
        try:
            # 验证输入
            if not job_id or not job_id.strip():
                return False, "任务ID不能为空", None
            
            if not name or not name.strip():
                return False, "会话名称不能为空", None
            
            name = name.strip()
            
            # 检查名称长度
            if len(name) > 255:
                return False, "会话名称不能超过255个字符", None
            
            # 检查会话是否存在
            session = self.get_session_by_job_id(job_id, user_id)
            if not session:
                return False, "会话不存在或无权访问", None
            
            # 更新会话名称
            if user_id:
                query = """
                UPDATE chat_sessions
                SET name = %s, updated_at = %s
                WHERE job_id = %s AND user_id = %s
                RETURNING session_id, job_id, user_id, name, status, metadata,
                          created_at, updated_at
                """
                result = self.db.execute_query(
                    query,
                    (name, datetime.now(), job_id, user_id),
                    fetch_one=True
                )
            else:
                query = """
                UPDATE chat_sessions
                SET name = %s, updated_at = %s
                WHERE job_id = %s
                RETURNING session_id, job_id, user_id, name, status, metadata,
                          created_at, updated_at
                """
                result = self.db.execute_query(
                    query,
                    (name, datetime.now(), job_id),
                    fetch_one=True
                )
            
            if result:
                updated_session = ChatSession.from_dict(result)
                logger.info(f"任务 {job_id} 的会话名称已更新为: {name}")
                return True, "会话名称更新成功", updated_session
            else:
                return False, "更新失败", None
                
        except Exception as e:
            logger.error(f"更新会话名称失败: {e}")
            return False, f"系统错误: {str(e)}", None
    
    def update_session_name(
        self,
        session_id: str,
        name: str,
        user_id: Optional[str] = None
    ) -> tuple[bool, str, Optional[ChatSession]]:
        """
        更新会话名称（根据session_id）
        
        Args:
            session_id: 会话ID
            name: 新的会话名称
            user_id: 用户ID（可选，用于权限验证）
        
        Returns:
            (成功标志, 消息, 更新后的会话对象)
        """
        try:
            # 验证输入
            if not session_id or not session_id.strip():
                return False, "会话ID不能为空", None
            
            if not name or not name.strip():
                return False, "会话名称不能为空", None
            
            name = name.strip()
            
            # 检查名称长度
            if len(name) > 255:
                return False, "会话名称不能超过255个字符", None
            
            # 检查会话是否存在
            session = self.get_session_by_id(session_id)
            if not session:
                return False, "会话不存在", None
            
            # 如果提供了user_id，验证权限
            if user_id and session.user_id != user_id:
                return False, "无权修改此会话", None
            
            # 更新会话名称
            query = """
            UPDATE chat_sessions
            SET name = %s, updated_at = %s
            WHERE session_id = %s
            RETURNING session_id, job_id, user_id, name, status, metadata,
                      created_at, updated_at
            """
            result = self.db.execute_query(
                query,
                (name, datetime.now(), session_id),
                fetch_one=True
            )
            
            if result:
                updated_session = ChatSession.from_dict(result)
                logger.info(f"会话 {session_id} 名称已更新为: {name}")
                return True, "会话名称更新成功", updated_session
            else:
                return False, "更新失败", None
                
        except Exception as e:
            logger.error(f"更新会话名称失败: {e}")
            return False, f"系统错误: {str(e)}", None
    
    def delete_session_by_job_id(
        self,
        job_id: str,
        user_id: Optional[str] = None
    ) -> tuple[bool, str]:
        """
        根据任务ID删除会话及相关数据（级联删除）- 优化版本
        
        Args:
            job_id: 任务ID
            user_id: 用户ID（可选，用于权限验证）
        
        Returns:
            (成功标志, 消息)
        """
        import time
        start_time = time.time()
        
        try:
            # 验证输入
            if not job_id or not job_id.strip():
                return False, "任务ID不能为空"
            
            # 检查会话是否存在
            session = self.get_session_by_job_id(job_id, user_id)
            if not session:
                return False, "会话不存在或无权访问"
            
            # 准备所有删除查询（按正确的依赖顺序）
            # 注意：删除顺序很重要，需要先删除子表，再删除父表
            delete_queries = []
            table_names = []
            
            # 1. 删除聊天消息 (chat_messages)
            delete_queries.append((
                "DELETE FROM chat_messages WHERE session_id IN (SELECT session_id FROM chat_sessions WHERE job_id = %s)",
                (job_id,)
            ))
            table_names.append('chat_messages')
            
            # 2. 删除引用subgraphs的子表 - 必须在subgraphs之前删除
            # 通过subgraph_id删除features
            delete_queries.append((
                "DELETE FROM features WHERE subgraph_id IN (SELECT subgraph_id FROM subgraphs WHERE job_id = %s)",
                (job_id,)
            ))
            table_names.append('features')
            
            # 通过subgraph_id删除processing_cost_calculation_details
            delete_queries.append((
                "DELETE FROM processing_cost_calculation_details WHERE subgraph_id IN (SELECT subgraph_id FROM subgraphs WHERE job_id = %s)",
                (job_id,)
            ))
            table_names.append('processing_cost_calculation_details')
            
            # 3. 删除子图数据 (subgraphs)
            delete_queries.append(("DELETE FROM subgraphs WHERE job_id = %s", (job_id,)))
            table_names.append('subgraphs')
            
            # 4-16. 删除其他表
            delete_queries.append(("DELETE FROM job_price_snapshots WHERE job_id = %s", (job_id,)))
            table_names.append('job_price_snapshots')
            
            delete_queries.append(("DELETE FROM job_process_snapshots WHERE job_id = %s", (job_id,)))
            table_names.append('job_process_snapshots')
            
            delete_queries.append(("DELETE FROM operation_logs WHERE job_id = %s", (job_id,)))
            table_names.append('operation_logs')
            
            delete_queries.append(("DELETE FROM price_histories WHERE job_id = %s", (job_id,)))
            table_names.append('price_histories')
            
            delete_queries.append(("DELETE FROM recalculations WHERE job_id = %s", (job_id,)))
            table_names.append('recalculations')
            
            delete_queries.append(("DELETE FROM batch_recalculations WHERE job_id = %s", (job_id,)))
            table_names.append('batch_recalculations')
            
            delete_queries.append(("DELETE FROM process_changes WHERE job_id = %s", (job_id,)))
            table_names.append('process_changes')
            
            delete_queries.append(("DELETE FROM nc_calculations WHERE job_id = %s", (job_id,)))
            table_names.append('nc_calculations')
            
            delete_queries.append(("DELETE FROM user_interactions WHERE job_id = %s", (job_id,)))
            table_names.append('user_interactions')
            
            delete_queries.append(("DELETE FROM report_summary WHERE job_id = %s", (job_id,)))
            table_names.append('report_summary')
            
            delete_queries.append(("DELETE FROM reports WHERE job_id = %s", (job_id,)))
            table_names.append('reports')
            
            delete_queries.append(("DELETE FROM archives WHERE job_id = %s", (job_id,)))
            table_names.append('archives')
            
            delete_queries.append((
                "DELETE FROM audit_logs WHERE resource_type = 'job' AND resource_id = %s",
                (job_id,)
            ))
            table_names.append('audit_logs')
            
            # 17. 删除任务主表 (jobs)
            delete_queries.append(("DELETE FROM jobs WHERE job_id = %s", (job_id,)))
            table_names.append('jobs')
            
            # 18. 最后删除聊天会话 (chat_sessions)
            delete_queries.append(("DELETE FROM chat_sessions WHERE job_id = %s", (job_id,)))
            table_names.append('chat_sessions')
            
            # 使用批量执行（单个连接和事务）
            deleted_counts_list = self.db.execute_batch(delete_queries)
            
            # 构建统计信息
            deleted_counts = dict(zip(table_names, deleted_counts_list))
            total_deleted = sum(deleted_counts.values())
            
            # 记录性能
            elapsed = time.time() - start_time
            logger.info(f"删除任务 {job_id} 完成，耗时: {elapsed:.3f}秒")
            logger.info(f"删除统计: {deleted_counts}")
            
            if elapsed > 1.0:
                logger.warning(f"删除操作较慢: {elapsed:.3f}秒, job_id={job_id}")
            
            if deleted_counts['chat_sessions'] > 0:
                # 构建删除摘要消息
                summary_parts = []
                for table, count in deleted_counts.items():
                    if count > 0:
                        summary_parts.append(f"{table}({count}条)")
                
                summary = f"会话删除成功，共删除 {total_deleted} 条记录: " + ", ".join(summary_parts)
                return True, summary
            else:
                return False, "删除失败，未找到匹配的记录"
                
        except Exception as e:
            logger.error(f"删除会话失败: {e}")
            return False, f"系统错误: {str(e)}"
    
    def delete_session_by_id(
        self,
        session_id: str,
        user_id: Optional[str] = None
    ) -> tuple[bool, str]:
        """
        根据会话ID删除会话及相关数据 - 优化版本
        
        Args:
            session_id: 会话ID
            user_id: 用户ID（可选，用于权限验证）
        
        Returns:
            (成功标志, 消息)
        """
        import time
        start_time = time.time()
        
        try:
            # 验证输入
            if not session_id or not session_id.strip():
                return False, "会话ID不能为空"
            
            # 检查会话是否存在
            session = self.get_session_by_id(session_id)
            if not session:
                return False, "会话不存在"
            
            # 验证权限
            if user_id and session.user_id != user_id:
                return False, "无权删除此会话"
            
            job_id = session.job_id
            
            # 准备所有删除查询（按正确的依赖顺序）
            delete_queries = []
            table_names = []
            
            # 1. 删除聊天消息 (chat_messages)
            delete_queries.append(("DELETE FROM chat_messages WHERE session_id = %s", (session_id,)))
            table_names.append('chat_messages')
            
            # 2. 删除引用subgraphs的子表
            # 通过subgraph_id删除features
            delete_queries.append((
                "DELETE FROM features WHERE subgraph_id IN (SELECT subgraph_id FROM subgraphs WHERE job_id = %s)",
                (job_id,)
            ))
            table_names.append('features')
            
            # 通过subgraph_id删除processing_cost_calculation_details
            delete_queries.append((
                "DELETE FROM processing_cost_calculation_details WHERE subgraph_id IN (SELECT subgraph_id FROM subgraphs WHERE job_id = %s)",
                (job_id,)
            ))
            table_names.append('processing_cost_calculation_details')
            
            # 3. 删除子图数据
            delete_queries.append(("DELETE FROM subgraphs WHERE job_id = %s", (job_id,)))
            table_names.append('subgraphs')
            
            # 4-16. 删除其他表
            delete_queries.append(("DELETE FROM job_price_snapshots WHERE job_id = %s", (job_id,)))
            table_names.append('job_price_snapshots')
            
            delete_queries.append(("DELETE FROM job_process_snapshots WHERE job_id = %s", (job_id,)))
            table_names.append('job_process_snapshots')
            
            delete_queries.append(("DELETE FROM operation_logs WHERE job_id = %s", (job_id,)))
            table_names.append('operation_logs')
            
            delete_queries.append(("DELETE FROM price_histories WHERE job_id = %s", (job_id,)))
            table_names.append('price_histories')
            
            delete_queries.append(("DELETE FROM recalculations WHERE job_id = %s", (job_id,)))
            table_names.append('recalculations')
            
            delete_queries.append(("DELETE FROM batch_recalculations WHERE job_id = %s", (job_id,)))
            table_names.append('batch_recalculations')
            
            delete_queries.append(("DELETE FROM process_changes WHERE job_id = %s", (job_id,)))
            table_names.append('process_changes')
            
            delete_queries.append(("DELETE FROM nc_calculations WHERE job_id = %s", (job_id,)))
            table_names.append('nc_calculations')
            
            delete_queries.append(("DELETE FROM user_interactions WHERE job_id = %s", (job_id,)))
            table_names.append('user_interactions')
            
            delete_queries.append(("DELETE FROM report_summary WHERE job_id = %s", (job_id,)))
            table_names.append('report_summary')
            
            delete_queries.append(("DELETE FROM reports WHERE job_id = %s", (job_id,)))
            table_names.append('reports')
            
            delete_queries.append(("DELETE FROM archives WHERE job_id = %s", (job_id,)))
            table_names.append('archives')
            
            delete_queries.append((
                "DELETE FROM audit_logs WHERE resource_type = 'job' AND resource_id = %s",
                (job_id,)
            ))
            table_names.append('audit_logs')
            
            # 17. 删除任务主表
            delete_queries.append(("DELETE FROM jobs WHERE job_id = %s", (job_id,)))
            table_names.append('jobs')
            
            # 18. 最后删除聊天会话
            delete_queries.append(("DELETE FROM chat_sessions WHERE session_id = %s", (session_id,)))
            table_names.append('chat_sessions')
            
            # 使用批量执行（单个连接和事务）
            deleted_counts_list = self.db.execute_batch(delete_queries)
            
            # 构建统计信息
            deleted_counts = dict(zip(table_names, deleted_counts_list))
            total_deleted = sum(deleted_counts.values())
            
            # 记录性能
            elapsed = time.time() - start_time
            logger.info(f"删除会话 {session_id} (任务 {job_id}) 完成，耗时: {elapsed:.3f}秒")
            logger.info(f"删除统计: {deleted_counts}")
            
            if elapsed > 1.0:
                logger.warning(f"删除操作较慢: {elapsed:.3f}秒, session_id={session_id}")
            
            if deleted_counts['chat_sessions'] > 0:
                # 构建删除摘要消息
                summary_parts = []
                for table, count in deleted_counts.items():
                    if count > 0:
                        summary_parts.append(f"{table}({count}条)")
                
                summary = f"会话删除成功，共删除 {total_deleted} 条记录: " + ", ".join(summary_parts)
                return True, summary
            else:
                return False, "删除失败，未找到匹配的记录"
                
        except Exception as e:
            logger.error(f"删除会话失败: {e}")
            return False, f"系统错误: {str(e)}"
    
    def delete_sessions_by_job_ids_batch(
        self,
        job_ids: List[str],
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        批量删除多个任务的会话及相关数据（优化版本 - 单次事务）
        
        Args:
            job_ids: 任务ID列表
            user_id: 用户ID（可选，用于权限验证）
        
        Returns:
            {
                'total': 总任务数,
                'success_count': 成功删除数,
                'failed_count': 失败数,
                'total_deleted': 总删除记录数,
                'elapsed_seconds': 耗时秒数,
                'results': [详细结果]
            }
        """
        import time
        start_time = time.time()
        
        try:
            # 验证输入
            if not job_ids:
                return {
                    'total': 0,
                    'success_count': 0,
                    'failed_count': 0,
                    'total_deleted': 0,
                    'elapsed_seconds': 0,
                    'results': []
                }
            
            # 如果提供了user_id，先验证权限
            if user_id:
                # 查询这些job_id对应的会话，验证权限
                placeholders = ','.join(['%s'] * len(job_ids))
                check_query = f"""
                SELECT job_id, session_id
                FROM chat_sessions
                WHERE job_id IN ({placeholders}) AND user_id = %s
                """
                valid_sessions = self.db.execute_query(
                    check_query,
                    tuple(job_ids) + (user_id,),
                    fetch_all=True
                )
                
                if not valid_sessions:
                    return {
                        'total': len(job_ids),
                        'success_count': 0,
                        'failed_count': len(job_ids),
                        'total_deleted': 0,
                        'elapsed_seconds': round(time.time() - start_time, 3),
                        'results': [
                            {
                                'job_id': jid,
                                'success': False,
                                'message': '会话不存在或无权访问',
                                'deleted_count': 0
                            }
                            for jid in job_ids
                        ]
                    }
                
                # 只删除有权限的job_ids
                valid_job_ids = [row['job_id'] for row in valid_sessions]
                invalid_job_ids = set(job_ids) - set(valid_job_ids)
            else:
                valid_job_ids = job_ids
                invalid_job_ids = set()
            
            # 准备批量删除查询（使用 IN 子句）
            placeholders = ','.join(['%s'] * len(valid_job_ids))
            delete_queries = []
            table_names = []
            
            # 1. 删除聊天消息
            delete_queries.append((
                f"DELETE FROM chat_messages WHERE session_id IN (SELECT session_id FROM chat_sessions WHERE job_id IN ({placeholders}))",
                tuple(valid_job_ids)
            ))
            table_names.append('chat_messages')
            
            # 2. 删除引用subgraphs的子表
            delete_queries.append((
                f"DELETE FROM features WHERE subgraph_id IN (SELECT subgraph_id FROM subgraphs WHERE job_id IN ({placeholders}))",
                tuple(valid_job_ids)
            ))
            table_names.append('features')
            
            delete_queries.append((
                f"DELETE FROM processing_cost_calculation_details WHERE subgraph_id IN (SELECT subgraph_id FROM subgraphs WHERE job_id IN ({placeholders}))",
                tuple(valid_job_ids)
            ))
            table_names.append('processing_cost_calculation_details')
            
            # 3. 删除子图数据
            delete_queries.append((
                f"DELETE FROM subgraphs WHERE job_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('subgraphs')
            
            # 4-16. 删除其他表
            delete_queries.append((
                f"DELETE FROM job_price_snapshots WHERE job_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('job_price_snapshots')
            
            delete_queries.append((
                f"DELETE FROM job_process_snapshots WHERE job_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('job_process_snapshots')
            
            delete_queries.append((
                f"DELETE FROM operation_logs WHERE job_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('operation_logs')
            
            delete_queries.append((
                f"DELETE FROM price_histories WHERE job_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('price_histories')
            
            delete_queries.append((
                f"DELETE FROM recalculations WHERE job_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('recalculations')
            
            delete_queries.append((
                f"DELETE FROM batch_recalculations WHERE job_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('batch_recalculations')
            
            delete_queries.append((
                f"DELETE FROM process_changes WHERE job_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('process_changes')
            
            delete_queries.append((
                f"DELETE FROM nc_calculations WHERE job_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('nc_calculations')
            
            delete_queries.append((
                f"DELETE FROM user_interactions WHERE job_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('user_interactions')
            
            delete_queries.append((
                f"DELETE FROM report_summary WHERE job_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('report_summary')
            
            delete_queries.append((
                f"DELETE FROM reports WHERE job_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('reports')
            
            delete_queries.append((
                f"DELETE FROM archives WHERE job_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('archives')
            
            delete_queries.append((
                f"DELETE FROM audit_logs WHERE resource_type = 'job' AND resource_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('audit_logs')
            
            # 17. 删除任务主表
            delete_queries.append((
                f"DELETE FROM jobs WHERE job_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('jobs')
            
            # 18. 最后删除聊天会话
            delete_queries.append((
                f"DELETE FROM chat_sessions WHERE job_id IN ({placeholders})",
                tuple(valid_job_ids)
            ))
            table_names.append('chat_sessions')
            
            # 使用批量执行（单个连接和事务）
            deleted_counts_list = self.db.execute_batch(delete_queries)
            
            # 构建统计信息
            deleted_counts = dict(zip(table_names, deleted_counts_list))
            total_deleted = sum(deleted_counts.values())
            
            # 记录性能
            elapsed = time.time() - start_time
            logger.info(f"批量删除 {len(valid_job_ids)} 个任务完成，耗时: {elapsed:.3f}秒")
            logger.info(f"删除统计: {deleted_counts}")
            
            # 构建结果
            results = []
            
            # 成功删除的
            for job_id in valid_job_ids:
                results.append({
                    'job_id': job_id,
                    'success': True,
                    'message': '删除成功',
                    'deleted_count': total_deleted // len(valid_job_ids)  # 平均分配
                })
            
            # 无权限的
            for job_id in invalid_job_ids:
                results.append({
                    'job_id': job_id,
                    'success': False,
                    'message': '会话不存在或无权访问',
                    'deleted_count': 0
                })
            
            return {
                'total': len(job_ids),
                'success_count': len(valid_job_ids),
                'failed_count': len(invalid_job_ids),
                'total_deleted': total_deleted,
                'elapsed_seconds': round(elapsed, 3),
                'results': results
            }
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"批量删除失败: {e}")
            return {
                'total': len(job_ids),
                'success_count': 0,
                'failed_count': len(job_ids),
                'total_deleted': 0,
                'elapsed_seconds': round(elapsed, 3),
                'results': [
                    {
                        'job_id': jid,
                        'success': False,
                        'message': f'系统错误: {str(e)}',
                        'deleted_count': 0
                    }
                    for jid in job_ids
                ]
            }
    
    def get_user_sessions(
        self,
        user_id: str,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> tuple[List[ChatSession], int]:
        """
        获取用户的会话列表
        
        Args:
            user_id: 用户ID
            status: 会话状态过滤（可选）
            limit: 返回数量限制
            offset: 偏移量
        
        Returns:
            (会话列表, 总数)
        
        Raises:
            Exception: 数据库查询失败时抛出异常
        """
        # 构建查询条件
        conditions = ["user_id = %s"]
        params = [user_id]
        
        if status:
            conditions.append("status = %s")
            params.append(status)
        
        where_clause = " AND ".join(conditions)
        
        # 查询总数
        count_query = f"""
        SELECT COUNT(*) as total
        FROM chat_sessions
        WHERE {where_clause}
        """
        count_result = self.db.execute_query(count_query, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0
        
        # 查询列表
        query = f"""
        SELECT session_id, job_id, user_id, name, status, metadata,
               created_at, updated_at
        FROM chat_sessions
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])
        
        results = self.db.execute_query(query, tuple(params), fetch_all=True)
        sessions = [ChatSession.from_dict(row) for row in results] if results else []
        
        return sessions, total


# 全局服务实例
chat_session_service = ChatSessionService()
