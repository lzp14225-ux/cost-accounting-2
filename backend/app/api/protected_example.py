#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
受保护的API示例
展示如何使用token自动刷新中间件
"""

from flask import Blueprint, jsonify, g
from app.middleware import create_token_middleware

# 创建蓝图
protected_bp = Blueprint('protected', __name__, url_prefix='/api')

# 注意：token_middleware需要在应用初始化时创建
# 这里只是示例，实际使用时应该从app中获取
token_middleware = None

def init_protected_routes(app):
    """初始化受保护的路由"""
    global token_middleware
    token_middleware = create_token_middleware(app)
    app.register_blueprint(protected_bp)


@protected_bp.route('/user/profile', methods=['GET'])
def get_user_profile():
    """
    获取用户信息（需要token）
    自动刷新即将过期的token
    """
    # 手动验证token（如果没有使用装饰器）
    from flask import request
    from app.middleware import create_token_middleware
    from config.config import get_config
    
    config = get_config()
    middleware = create_token_middleware(None)
    
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({
            'success': False,
            'message': '缺少Authorization头'
        }), 401
    
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return jsonify({
            'success': False,
            'message': 'Authorization格式错误'
        }), 401
    
    token = parts[1]
    payload, new_token = middleware.verify_and_refresh_token(token)
    
    if payload is None:
        return jsonify({
            'success': False,
            'message': 'Token无效或已过期'
        }), 401
    
    # 构建响应
    response_data = {
        'success': True,
        'message': '获取成功',
        'data': {
            'user_id': payload.get('user_id'),
            'username': payload.get('sub'),
            'role': payload.get('role'),
            'email': payload.get('email'),
            'real_name': payload.get('real_name')
        }
    }
    
    # 如果生成了新token，添加到响应中
    if new_token:
        response_data['new_token'] = new_token
        response_data['message'] = '获取成功，token已刷新'
    
    return jsonify(response_data)


@protected_bp.route('/data/list', methods=['GET'])
def get_data_list():
    """
    获取数据列表（需要token）
    """
    from flask import request
    from app.middleware import create_token_middleware
    
    middleware = create_token_middleware(None)
    
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({'success': False, 'message': '缺少Authorization头'}), 401
    
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return jsonify({'success': False, 'message': 'Authorization格式错误'}), 401
    
    token = parts[1]
    payload, new_token = middleware.verify_and_refresh_token(token)
    
    if payload is None:
        return jsonify({'success': False, 'message': 'Token无效或已过期'}), 401
    
    # 模拟数据
    data = {
        'success': True,
        'message': '获取成功',
        'data': {
            'items': [
                {'id': 1, 'name': '数据1'},
                {'id': 2, 'name': '数据2'},
                {'id': 3, 'name': '数据3'}
            ],
            'total': 3
        }
    }
    
    if new_token:
        data['new_token'] = new_token
        data['message'] = '获取成功，token已刷新'
    
    return jsonify(data)
