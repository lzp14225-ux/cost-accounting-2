#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聊天会话API路由
"""

from flask import Blueprint, request, jsonify
import logging
from app.services.chat_session_service import chat_session_service
from app.utils.token_helper import verify_token_from_request

logger = logging.getLogger(__name__)

# 创建蓝图
chat_sessions_bp = Blueprint('chat_sessions', __name__, url_prefix='/api/chat-sessions')


@chat_sessions_bp.route('/update-name', methods=['PUT'])
def update_session_name_by_job():
    """
    根据任务ID更新会话名称
    
    请求方法: PUT
    路径: /api/chat-sessions/update-name
    
    请求头:
        Authorization: Bearer <token>
    
    请求体:
        {
            "job_id": "任务ID",
            "name": "新的会话名称"
        }
    
    响应:
        {
            "success": true,
            "message": "会话名称更新成功",
            "data": {
                "session_id": "xxx",
                "job_id": "xxx",
                "user_id": "xxx",
                "name": "新的会话名称",
                "status": "active",
                "metadata": {},
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00"
            }
        }
    """
    try:
        # 验证token
        payload = verify_token_from_request()
        if not payload:
            return jsonify({
                'success': False,
                'message': 'Token无效或已过期'
            }), 401
        
        user_id = payload.get('user_id')
        
        # 获取请求数据
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': '请求数据格式错误'
            }), 400
        
        job_id = data.get('job_id', '').strip()
        name = data.get('name', '').strip()
        
        if not job_id:
            return jsonify({
                'success': False,
                'message': '任务ID不能为空'
            }), 400
        
        # 更新会话名称
        success, message, session = chat_session_service.update_session_name_by_job_id(
            job_id=job_id,
            name=name,
            user_id=user_id  # 传入user_id进行权限验证
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': message,
                'data': session.to_dict() if session else None
            })
        else:
            status_code = 404 if '不存在' in message or '无权访问' in message else 400
            return jsonify({
                'success': False,
                'message': message
            }), status_code
            
    except Exception as e:
        logger.error(f"根据job_id更新会话名称接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500


@chat_sessions_bp.route('/<session_id>/name', methods=['PUT'])
def update_session_name(session_id):
    """
    更新会话名称
    
    请求方法: PUT
    路径: /api/chat-sessions/<session_id>/name
    
    请求头:
        Authorization: Bearer <token>
    
    请求体:
        {
            "name": "新的会话名称"
        }
    
    响应:
        {
            "success": true,
            "message": "会话名称更新成功",
            "data": {
                "session_id": "xxx",
                "job_id": "xxx",
                "user_id": "xxx",
                "name": "新的会话名称",
                "status": "active",
                "metadata": {},
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00"
            }
        }
    """
    try:
        # 验证token
        payload = verify_token_from_request()
        if not payload:
            return jsonify({
                'success': False,
                'message': 'Token无效或已过期'
            }), 401
        
        user_id = payload.get('user_id')
        
        # 获取请求数据
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': '请求数据格式错误'
            }), 400
        
        name = data.get('name', '').strip()
        
        # 更新会话名称
        success, message, session = chat_session_service.update_session_name(
            session_id=session_id,
            name=name,
            user_id=user_id  # 传入user_id进行权限验证
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': message,
                'data': session.to_dict() if session else None
            })
        else:
            status_code = 404 if '不存在' in message else \
                         403 if '无权' in message else \
                         400
            return jsonify({
                'success': False,
                'message': message
            }), status_code
            
    except Exception as e:
        logger.error(f"更新会话名称接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500


@chat_sessions_bp.route('/<session_id>', methods=['GET'])
def get_session(session_id):
    """
    获取会话详情
    
    请求方法: GET
    路径: /api/chat-sessions/<session_id>
    
    请求头:
        Authorization: Bearer <token>
    
    响应:
        {
            "success": true,
            "message": "获取成功",
            "data": {
                "session_id": "xxx",
                "job_id": "xxx",
                "user_id": "xxx",
                "name": "会话名称",
                "status": "active",
                "metadata": {},
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00"
            }
        }
    """
    try:
        # 验证token
        payload = verify_token_from_request()
        if not payload:
            return jsonify({
                'success': False,
                'message': 'Token无效或已过期'
            }), 401
        
        user_id = payload.get('user_id')
        
        # 获取会话信息
        session = chat_session_service.get_session_by_id(session_id)
        
        if not session:
            return jsonify({
                'success': False,
                'message': '会话不存在'
            }), 404
        
        # 验证权限
        if session.user_id != user_id:
            return jsonify({
                'success': False,
                'message': '无权访问此会话'
            }), 403
        
        return jsonify({
            'success': True,
            'message': '获取成功',
            'data': session.to_dict()
        })
        
    except Exception as e:
        logger.error(f"获取会话详情接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500


@chat_sessions_bp.route('/', methods=['GET'])
def get_user_sessions():
    """
    获取当前用户的会话列表
    
    请求方法: GET
    路径: /api/chat-sessions/
    
    请求头:
        Authorization: Bearer <token>
    
    查询参数:
        status: 会话状态过滤（可选）
        limit: 返回数量限制（默认50）
        offset: 偏移量（默认0）
    
    响应:
        {
            "success": true,
            "message": "获取成功",
            "data": {
                "sessions": [...],
                "total": 100,
                "limit": 50,
                "offset": 0
            }
        }
    """
    try:
        # 验证token
        payload = verify_token_from_request()
        if not payload:
            return jsonify({
                'success': False,
                'message': 'Token无效或已过期'
            }), 401
        
        user_id = payload.get('user_id')
        
        # 获取查询参数
        status = request.args.get('status')
        limit = min(int(request.args.get('limit', 50)), 100)  # 最大100
        offset = int(request.args.get('offset', 0))
        
        # 获取会话列表
        sessions, total = chat_session_service.get_user_sessions(
            user_id=user_id,
            status=status,
            limit=limit,
            offset=offset
        )
        
        return jsonify({
            'success': True,
            'message': '获取成功',
            'data': {
                'sessions': [session.to_dict() for session in sessions],
                'total': total,
                'limit': limit,
                'offset': offset
            }
        })
        
    except ValueError as e:
        return jsonify({
            'success': False,
            'message': '参数格式错误'
        }), 400
    except Exception as e:
        logger.error(f"获取会话列表接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500


@chat_sessions_bp.route('/delete-by-job', methods=['DELETE'])
def delete_session_by_job():
    """
    根据任务ID删除会话及所有相关数据（级联删除）
    
    请求方法: DELETE
    路径: /api/chat-sessions/delete-by-job
    
    请求头:
        Authorization: Bearer <token>
    
    请求体:
        {
            "job_id": "任务ID"
        }
    
    响应:
        {
            "success": true,
            "message": "会话删除成功，共删除 X 条记录: ...",
            "data": {
                "job_id": "xxx",
                "deleted_tables": ["chat_sessions", "jobs", "subgraphs", ...],
                "total_deleted": 123
            }
        }
    """
    try:
        # 验证token
        payload = verify_token_from_request()
        if not payload:
            return jsonify({
                'success': False,
                'message': 'Token无效或已过期'
            }), 401
        
        user_id = payload.get('user_id')
        
        # 获取请求数据
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': '请求数据格式错误'
            }), 400
        
        job_id = data.get('job_id', '').strip()
        
        if not job_id:
            return jsonify({
                'success': False,
                'message': '任务ID不能为空'
            }), 400
        
        # 删除会话及相关数据
        success, message = chat_session_service.delete_session_by_job_id(
            job_id=job_id,
            user_id=user_id  # 传入user_id进行权限验证
        )
        
        if success:
            # 解析删除统计信息
            deleted_tables = []
            total_deleted = 0
            
            if "共删除" in message and "条记录:" in message:
                parts = message.split("条记录:")
                if len(parts) > 1:
                    total_part = parts[0].split("共删除")[-1].strip()
                    try:
                        total_deleted = int(total_part)
                    except:
                        pass
                    
                    # 提取表名
                    tables_part = parts[1].strip()
                    import re
                    table_matches = re.findall(r'(\w+)\(\d+条\)', tables_part)
                    deleted_tables = table_matches
            
            return jsonify({
                'success': True,
                'message': message,
                'data': {
                    'job_id': job_id,
                    'deleted_tables': deleted_tables,
                    'total_deleted': total_deleted
                }
            })
        else:
            status_code = 404 if '不存在' in message or '无权访问' in message else 400
            return jsonify({
                'success': False,
                'message': message
            }), status_code
            
    except Exception as e:
        logger.error(f"删除会话接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500


@chat_sessions_bp.route('/batch-delete-by-job', methods=['POST'])
def batch_delete_sessions_by_job():
    """
    批量删除多个任务的会话及相关数据（异步处理）
    
    请求方法: POST
    路径: /api/chat-sessions/batch-delete-by-job
    
    请求头:
        Authorization: Bearer <token>
    
    请求体:
        {
            "job_ids": ["job_id_1", "job_id_2", "job_id_3", ...]
        }
    
    响应:
        {
            "success": true,
            "message": "批量删除完成",
            "data": {
                "total": 10,
                "success_count": 8,
                "failed_count": 2,
                "total_deleted": 1234,
                "elapsed_seconds": 5.678,
                "results": [
                    {
                        "job_id": "xxx",
                        "success": true,
                        "message": "会话删除成功，共删除 123 条记录: ...",
                        "deleted_count": 123
                    },
                    {
                        "job_id": "yyy",
                        "success": false,
                        "message": "会话不存在或无权访问",
                        "deleted_count": 0
                    }
                ]
            }
        }
    """
    try:
        # 验证token
        payload = verify_token_from_request()
        if not payload:
            return jsonify({
                'success': False,
                'message': 'Token无效或已过期'
            }), 401
        
        user_id = payload.get('user_id')
        
        # 获取请求数据
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': '请求数据格式错误'
            }), 400
        
        job_ids = data.get('job_ids', [])
        
        # 验证输入
        if not isinstance(job_ids, list):
            return jsonify({
                'success': False,
                'message': 'job_ids必须是数组'
            }), 400
        
        if not job_ids:
            return jsonify({
                'success': False,
                'message': 'job_ids不能为空'
            }), 400
        
        # 限制批量数量
        if len(job_ids) > 100:
            return jsonify({
                'success': False,
                'message': '单次最多删除100个任务'
            }), 400
        
        # 过滤空字符串
        job_ids = [jid.strip() for jid in job_ids if jid and jid.strip()]
        
        if not job_ids:
            return jsonify({
                'success': False,
                'message': '没有有效的任务ID'
            }), 400
        
        # 执行批量删除
        result = chat_session_service.delete_sessions_by_job_ids_batch(
            job_ids=job_ids,
            user_id=user_id
        )
        
        # 构建响应消息
        message = f"批量删除完成: 总数={result['total']}, 成功={result['success_count']}, 失败={result['failed_count']}"
        
        return jsonify({
            'success': True,
            'message': message,
            'data': result
        })
        
    except Exception as e:
        logger.error(f"批量删除会话接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500


@chat_sessions_bp.route('/<session_id>', methods=['DELETE'])
def delete_session_by_id(session_id):
    """
    根据会话ID删除会话及所有相关数据（级联删除）
    
    请求方法: DELETE
    路径: /api/chat-sessions/<session_id>
    
    请求头:
        Authorization: Bearer <token>
    
    响应:
        {
            "success": true,
            "message": "会话删除成功，共删除 X 条记录: ...",
            "data": {
                "session_id": "xxx",
                "job_id": "xxx",
                "deleted_tables": ["chat_sessions", "jobs", "subgraphs", ...],
                "total_deleted": 123
            }
        }
    """
    try:
        # 验证token
        payload = verify_token_from_request()
        if not payload:
            return jsonify({
                'success': False,
                'message': 'Token无效或已过期'
            }), 401
        
        user_id = payload.get('user_id')
        
        # 删除会话及相关数据
        success, message = chat_session_service.delete_session_by_id(
            session_id=session_id,
            user_id=user_id
        )
        
        if success:
            # 解析删除统计信息
            deleted_tables = []
            total_deleted = 0
            
            if "共删除" in message and "条记录:" in message:
                parts = message.split("条记录:")
                if len(parts) > 1:
                    total_part = parts[0].split("共删除")[-1].strip()
                    try:
                        total_deleted = int(total_part)
                    except:
                        pass
                    
                    # 提取表名
                    tables_part = parts[1].strip()
                    import re
                    table_matches = re.findall(r'(\w+)\(\d+条\)', tables_part)
                    deleted_tables = table_matches
            
            return jsonify({
                'success': True,
                'message': message,
                'data': {
                    'session_id': session_id,
                    'deleted_tables': deleted_tables,
                    'total_deleted': total_deleted
                }
            })
        else:
            status_code = 404 if '不存在' in message else \
                         403 if '无权' in message else 400
            return jsonify({
                'success': False,
                'message': message
            }), status_code
            
    except Exception as e:
        logger.error(f"删除会话接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500
