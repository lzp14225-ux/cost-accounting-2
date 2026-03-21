#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Token自动刷新中间件
实现滑动过期时间机制
"""

from functools import wraps
from flask import request, jsonify, g
import jwt
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class TokenRefreshMiddleware:
    """Token自动刷新中间件"""
    
    def __init__(self, secret_key, algorithm='HS256', expire_minutes=30, refresh_threshold=0.5):
        """
        初始化中间件
        
        Args:
            secret_key: JWT密钥
            algorithm: 加密算法
            expire_minutes: token过期时间（分钟）
            refresh_threshold: 刷新阈值（0-1之间），当剩余时间小于总时间的这个比例时刷新
                              例如：0.5表示当剩余时间小于50%时刷新
        """
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.expire_minutes = expire_minutes
        self.refresh_threshold = refresh_threshold
        self.refresh_window = expire_minutes * 60 * refresh_threshold  # 刷新窗口（秒）
    
    def verify_and_refresh_token(self, token):
        """
        验证token并判断是否需要刷新
        
        Returns:
            tuple: (payload, new_token)
                  - payload: token载荷
                  - new_token: 新token（如果需要刷新），否则为None
        """
        try:
            # 验证token
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            
            # 检查是否需要刷新
            exp = payload.get('exp')
            if not exp:
                return payload, None
            
            # 计算剩余时间
            now = datetime.utcnow()
            exp_time = datetime.utcfromtimestamp(exp)
            remaining = (exp_time - now).total_seconds()
            
            # 如果剩余时间小于刷新窗口，生成新token
            if remaining < self.refresh_window:
                logger.info(f"Token即将过期，剩余{remaining:.0f}秒，生成新token")
                
                # 创建新token（移除旧的exp）
                new_payload = {k: v for k, v in payload.items() if k != 'exp'}
                new_expire = now + timedelta(minutes=self.expire_minutes)
                new_payload['exp'] = new_expire
                
                new_token = jwt.encode(new_payload, self.secret_key, algorithm=self.algorithm)
                return payload, new_token
            
            return payload, None
            
        except jwt.ExpiredSignatureError:
            logger.warning("Token已过期")
            return None, None
        except jwt.JWTError as e:
            logger.warning(f"Token验证失败: {e}")
            return None, None
    
    def require_token(self, f):
        """
        装饰器：要求请求必须包含有效token
        自动刷新即将过期的token
        """
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 从请求头获取token
            auth_header = request.headers.get('Authorization')
            if not auth_header:
                return jsonify({
                    'success': False,
                    'message': '缺少Authorization头'
                }), 401
            
            # 解析Bearer token
            parts = auth_header.split()
            if len(parts) != 2 or parts[0].lower() != 'bearer':
                return jsonify({
                    'success': False,
                    'message': 'Authorization格式错误，应为: Bearer <token>'
                }), 401
            
            token = parts[1]
            
            # 验证并刷新token
            payload, new_token = self.verify_and_refresh_token(token)
            
            if payload is None:
                return jsonify({
                    'success': False,
                    'message': 'Token无效或已过期'
                }), 401
            
            # 将用户信息存储到g对象中
            g.current_user = payload
            g.new_token = new_token
            
            # 调用原函数
            response = f(*args, **kwargs)
            
            # 如果生成了新token，添加到响应头
            if new_token:
                if isinstance(response, tuple):
                    # 如果返回的是(data, status_code)格式
                    data, status_code = response
                    if isinstance(data, dict):
                        # 在响应数据中添加新token
                        data['new_token'] = new_token
                        return jsonify(data), status_code
                    return response
                else:
                    # 如果返回的是Response对象
                    if hasattr(response, 'headers'):
                        response.headers['X-New-Token'] = new_token
                    return response
            
            return response
        
        return decorated_function


def create_token_middleware(app):
    """
    创建token中间件实例
    
    Args:
        app: Flask应用实例
    
    Returns:
        TokenRefreshMiddleware实例
    """
    from config.config import get_config
    config = get_config()
    
    middleware = TokenRefreshMiddleware(
        secret_key=config.JWT_SECRET_KEY,
        algorithm=config.JWT_ALGORITHM,
        expire_minutes=config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
        refresh_threshold=0.5  # 当剩余时间小于50%时刷新
    )
    
    return middleware
