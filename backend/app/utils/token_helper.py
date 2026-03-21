#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Token辅助函数
提供token验证和自动刷新功能
"""

import jwt
from datetime import datetime, timedelta
from flask import request, jsonify
import logging
from config.config import get_config

logger = logging.getLogger(__name__)
config = get_config()


def verify_and_refresh_token(token, refresh_threshold=0.5):
    """
    验证token并判断是否需要刷新
    
    Args:
        token: JWT token字符串
        refresh_threshold: 刷新阈值（0-1），当剩余时间小于总时间的这个比例时刷新
    
    Returns:
        tuple: (payload, new_token, error_message)
            - payload: token载荷（验证失败时为None）
            - new_token: 新token（不需要刷新时为None）
            - error_message: 错误信息（成功时为None）
    """
    try:
        # 验证token
        payload = jwt.decode(token, config.JWT_SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
        
        # 检查是否需要刷新
        exp = payload.get('exp')
        if not exp:
            return payload, None, None
        
        # 计算剩余时间
        now = datetime.utcnow()
        
        # 处理exp可能是datetime对象的情况
        if isinstance(exp, datetime):
            exp_time = exp
        else:
            exp_time = datetime.utcfromtimestamp(exp)
        
        remaining = (exp_time - now).total_seconds()
        
        # 计算刷新窗口
        refresh_window = config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60 * refresh_threshold
        
        # 如果剩余时间小于刷新窗口，生成新token
        if remaining < refresh_window:
            logger.info(f"Token即将过期，剩余{remaining:.0f}秒，生成新token")
            
            # 创建新token（移除旧的exp）
            new_payload = {k: v for k, v in payload.items() if k != 'exp'}
            new_expire = now + timedelta(minutes=config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
            new_payload['exp'] = new_expire
            
            new_token = jwt.encode(new_payload, config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)
            return payload, new_token, None
        
        return payload, None, None
        
    except jwt.ExpiredSignatureError:
        logger.warning("Token已过期")
        return None, None, "Token已过期"
    except jwt.JWTError as e:
        logger.warning(f"Token验证失败: {e}")
        return None, None, f"Token验证失败: {str(e)}"
    except Exception as e:
        logger.error(f"Token处理错误: {e}")
        return None, None, f"Token处理错误: {str(e)}"


def get_token_from_request():
    """
    从请求中获取token
    
    Returns:
        tuple: (token, error_response)
            - token: JWT token字符串（失败时为None）
            - error_response: 错误响应（成功时为None）
    """
    # 从请求头获取token
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return None, (jsonify({
            'success': False,
            'message': '缺少Authorization头'
        }), 401)
    
    # 解析Bearer token
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return None, (jsonify({
            'success': False,
            'message': 'Authorization格式错误，应为: Bearer <token>'
        }), 401)
    
    return parts[1], None


def require_token_with_refresh(f):
    """
    装饰器：要求请求必须包含有效token，并自动刷新即将过期的token
    
    使用方法:
        @require_token_with_refresh
        def my_api():
            # 可以通过 g.current_user 访问用户信息
            # 如果token被刷新，会自动添加到响应中
            pass
    """
    from functools import wraps
    from flask import g
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 获取token
        token, error_response = get_token_from_request()
        if error_response:
            return error_response
        
        # 验证并刷新token
        payload, new_token, error_message = verify_and_refresh_token(token)
        
        if payload is None:
            return jsonify({
                'success': False,
                'message': error_message or 'Token无效'
            }), 401
        
        # 将用户信息存储到g对象中
        g.current_user = payload
        g.new_token = new_token
        
        # 调用原函数
        result = f(*args, **kwargs)
        
        # 如果生成了新token，添加到响应中
        if new_token:
            if isinstance(result, tuple):
                data, status_code = result
                if isinstance(data, dict):
                    data['new_token'] = new_token
                    if 'message' in data:
                        data['message'] = data['message'] + '（token已刷新）'
                    return jsonify(data), status_code
            elif hasattr(result, 'json'):
                # Flask Response对象
                try:
                    data = result.get_json()
                    if isinstance(data, dict):
                        data['new_token'] = new_token
                        if 'message' in data:
                            data['message'] = data['message'] + '（token已刷新）'
                        return jsonify(data), result.status_code
                except:
                    pass
        
        return result
    
    return decorated_function


def add_new_token_to_response(response_data, new_token):
    """
    将新token添加到响应数据中
    
    Args:
        response_data: 响应数据字典
        new_token: 新token（如果为None则不添加）
    
    Returns:
        更新后的响应数据
    """
    if new_token and isinstance(response_data, dict):
        response_data['new_token'] = new_token
        if 'message' in response_data:
            response_data['message'] = response_data['message'] + '（token已刷新）'
    return response_data


def verify_token_from_request():
    """
    从请求中验证token并返回payload
    
    Returns:
        payload: token载荷（验证失败时为None）
    """
    token, error_response = get_token_from_request()
    if error_response:
        return None
    
    payload, new_token, error_message = verify_and_refresh_token(token)
    return payload
