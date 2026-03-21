#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
作业文件管理模块
提供根据作业ID查询作业文件信息的功能
"""

from flask import Blueprint, request, jsonify
import logging
from datetime import datetime
from app.services.database import db_manager

logger = logging.getLogger(__name__)

# 创建蓝图
jobs_bp = Blueprint('jobs', __name__, url_prefix='/api/jobs')

class JobService:
    """作业服务类"""
    
    def __init__(self):
        self.db = db_manager
    
    def _format_datetime(self, dt):
        """格式化datetime为ISO格式字符串"""
        if dt is None:
            return None
        if isinstance(dt, datetime):
            return dt.strftime('%Y-%m-%dT%H:%M:%S')
        return dt
    
    def _format_job_data(self, job):
        """格式化作业数据，将datetime转换为字符串"""
        if not job:
            return None
        
        formatted_job = dict(job)
        # 格式化所有datetime字段
        for key in formatted_job:
            if isinstance(formatted_job[key], datetime):
                formatted_job[key] = self._format_datetime(formatted_job[key])
        
        return formatted_job
    
    def get_job_by_id(self, job_id):
        """根据作业ID获取作业文件信息"""
        try:
            query = """
            SELECT 
                job_id,
                dwg_file_name,
                dwg_file_size,
                prt_file_name,
                prt_file_size
            FROM jobs
            WHERE job_id = %s
            """
            
            result = self.db.execute_query(query, (job_id,), fetch_one=True)
            
            if result:
                return True, "查询成功", self._format_job_data(result)
            else:
                return False, "作业不存在", None
                
        except Exception as e:
            logger.error(f"查询作业文件信息失败: {e}")
            return False, f"查询失败: {str(e)}", None

# 创建服务实例
job_service = JobService()

# ==================== API路由 ====================

@jobs_bp.route('/<job_id>', methods=['GET'])
def get_job_by_id(job_id):
    """
    根据作业ID获取作业文件信息
    
    路径参数:
    - job_id: 作业ID
    
    返回示例:
    {
        "success": true,
        "message": "查询成功",
        "data": {
            "job_id": "123",
            "dwg_file_name": "drawing.dwg",
            "dwg_file_size": 1024000,
            "prt_file_name": "part.prt",
            "prt_file_size": 512000
        }
    }
    """
    try:
        if not job_id:
            return jsonify({
                'success': False,
                'message': '作业ID不能为空'
            }), 400
        
        success, message, result = job_service.get_job_by_id(job_id)
        
        if success:
            return jsonify({
                'success': True,
                'message': message,
                'data': result
            })
        else:
            return jsonify({
                'success': False,
                'message': message
            }), 404
            
    except Exception as e:
        logger.error(f"获取作业文件信息接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500
