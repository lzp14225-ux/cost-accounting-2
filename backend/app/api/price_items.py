#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格项管理模块
提供价格项的增删改查功能
"""

from flask import Blueprint, request, jsonify
import logging
from datetime import datetime
from app.services.database import db_manager

logger = logging.getLogger(__name__)

# 创建蓝图
price_items_bp = Blueprint('price_items', __name__, url_prefix='/api/price-items')

class PriceItemService:
    """价格项服务类"""
    
    def __init__(self):
        self.db = db_manager
    
    def _format_datetime(self, dt):
        """格式化datetime为ISO格式字符串"""
        if dt is None:
            return None
        if isinstance(dt, datetime):
            return dt.strftime('%Y-%m-%dT%H:%M:%S')
        return dt
    
    def _format_item_data(self, item):
        """格式化价格项数据，将datetime转换为字符串"""
        if not item:
            return None
        
        formatted_item = dict(item)
        if 'created_at' in formatted_item:
            formatted_item['created_at'] = self._format_datetime(formatted_item['created_at'])
        if 'updated_at' in formatted_item:
            formatted_item['updated_at'] = self._format_datetime(formatted_item['updated_at'])
        
        return formatted_item
    
    def _format_items_list(self, items):
        """格式化价格项列表"""
        if not items:
            return []
        return [self._format_item_data(item) for item in items]
    
    def create_item(self, item_data):
        """创建价格项"""
        try:
            query = """
            INSERT INTO price_items 
            (id, version_id, category, sub_category, price, unit, work_hours, 
             min_num, add_price, weight_num, note, instruction, is_active, 
             created_by, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, version_id, category, sub_category, price, unit, work_hours, 
                      min_num, add_price, weight_num, note, instruction, is_active, 
                      created_by, created_at, updated_at
            """
            
            now = datetime.now()
            params = (
                item_data['id'],
                item_data.get('version_id'),
                item_data.get('category'),
                item_data.get('sub_category'),
                item_data.get('price'),
                item_data.get('unit'),
                item_data.get('work_hours'),
                item_data.get('min_num'),
                item_data.get('add_price'),
                item_data.get('weight_num'),
                item_data.get('note'),
                item_data.get('instruction'),
                item_data.get('is_active', True),
                item_data.get('created_by'),
                now,
                now
            )
            
            result = self.db.execute_query(query, params, fetch_one=True)
            return True, "价格项创建成功", self._format_item_data(result)
            
        except Exception as e:
            logger.error(f"创建价格项失败: {e}")
            return False, f"创建价格项失败: {str(e)}", None
    
    def get_item_by_id(self, item_id):
        """根据ID获取价格项"""
        try:
            query = """
            SELECT id, version_id, category, sub_category, price, unit, work_hours, 
                   min_num, add_price, weight_num, note, instruction, is_active, 
                   created_by, created_at, updated_at
            FROM price_items
            WHERE id = %s
            """
            
            result = self.db.execute_query(query, (item_id,), fetch_one=True)
            
            if result:
                return True, "获取成功", self._format_item_data(result)
            else:
                return False, "价格项不存在", None
                
        except Exception as e:
            logger.error(f"获取价格项失败: {e}")
            return False, f"获取价格项失败: {str(e)}", None
    
    def get_items(self, filters=None, page=1, page_size=20):
        """获取价格项列表（支持分页和筛选）"""
        try:
            # 构建查询条件
            conditions = []
            params = []
            
            # 默认只查询激活的价格项
            is_active_filter = True
            
            if filters:
                if filters.get('version_id'):
                    conditions.append("version_id = %s")
                    params.append(filters['version_id'])
                
                if filters.get('category'):
                    conditions.append("category = %s")
                    params.append(filters['category'])
                
                if filters.get('sub_category'):
                    conditions.append("sub_category ILIKE %s")
                    params.append(f"%{filters['sub_category']}%")
                
                if filters.get('is_active') is not None:
                    is_active_filter = filters['is_active']
            
            # 添加is_active条件
            conditions.append("is_active = %s")
            params.append(is_active_filter)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            # 查询总数
            count_query = f"SELECT COUNT(*) as total FROM price_items WHERE {where_clause}"
            count_result = self.db.execute_query(count_query, tuple(params), fetch_one=True)
            total = count_result['total'] if count_result else 0
            
            # 查询数据
            offset = (page - 1) * page_size
            query = f"""
            SELECT id, version_id, category, sub_category, price, unit, work_hours, 
                   min_num, add_price, weight_num, note, instruction, is_active, 
                   created_by, created_at, updated_at
            FROM price_items
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """
            
            params.extend([page_size, offset])
            results = self.db.execute_query(query, tuple(params), fetch_all=True)
            
            return True, "获取成功", {
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': (total + page_size - 1) // page_size,
                'data': self._format_items_list(results)
            }
            
        except Exception as e:
            logger.error(f"获取价格项列表失败: {e}")
            return False, f"获取价格项列表失败: {str(e)}", None
    
    def update_item(self, item_id, update_data):
        """更新价格项"""
        try:
            # 构建更新字段
            update_fields = []
            params = []
            
            allowed_fields = ['version_id', 'category', 'sub_category', 'price', 'unit', 
                            'work_hours', 'min_num', 'add_price', 'weight_num', 'note', 
                            'instruction', 'is_active', 'created_by']
            
            for field in allowed_fields:
                if field in update_data:
                    update_fields.append(f"{field} = %s")
                    params.append(update_data[field])
            
            if not update_fields:
                return False, "没有需要更新的字段", None
            
            # 添加updated_at字段
            update_fields.append("updated_at = %s")
            params.append(datetime.now())
            
            params.append(item_id)
            
            query = f"""
            UPDATE price_items
            SET {', '.join(update_fields)}
            WHERE id = %s
            RETURNING id, version_id, category, sub_category, price, unit, work_hours, 
                      min_num, add_price, weight_num, note, instruction, is_active, 
                      created_by, created_at, updated_at
            """
            
            result = self.db.execute_query(query, tuple(params), fetch_one=True)
            
            if result:
                return True, "价格项更新成功", self._format_item_data(result)
            else:
                return False, "价格项不存在", None
                
        except Exception as e:
            logger.error(f"更新价格项失败: {e}")
            return False, f"更新价格项失败: {str(e)}", None
    
    def delete_item(self, item_id):
        """删除价格项（硬删除）"""
        try:
            query = "DELETE FROM price_items WHERE id = %s RETURNING id"
            result = self.db.execute_query(query, (item_id,), fetch_one=True)
            
            if result:
                return True, "价格项删除成功", None
            else:
                return False, "价格项不存在", None
                
        except Exception as e:
            logger.error(f"删除价格项失败: {e}")
            return False, f"删除价格项失败: {str(e)}", None
    
    def soft_delete_item(self, item_id):
        """软删除价格项（将is_active设为false）"""
        try:
            query = """
            UPDATE price_items
            SET is_active = false, updated_at = %s
            WHERE id = %s
            RETURNING id, version_id, category, sub_category, price, unit, work_hours, 
                      min_num, add_price, weight_num, note, instruction, is_active, 
                      created_by, created_at, updated_at
            """
            result = self.db.execute_query(query, (datetime.now(), item_id), fetch_one=True)
            
            if result:
                return True, "价格项已停用", self._format_item_data(result)
            else:
                return False, "价格项不存在", None
                
        except Exception as e:
            logger.error(f"软删除价格项失败: {e}")
            return False, f"软删除价格项失败: {str(e)}", None
    
    def batch_delete_items(self, item_ids):
        """批量删除价格项（硬删除）"""
        try:
            placeholders = ','.join(['%s'] * len(item_ids))
            query = f"DELETE FROM price_items WHERE id IN ({placeholders}) RETURNING id"
            results = self.db.execute_query(query, tuple(item_ids), fetch_all=True)
            
            deleted_count = len(results) if results else 0
            return True, f"成功删除 {deleted_count} 条价格项", {'deleted_count': deleted_count}
            
        except Exception as e:
            logger.error(f"批量删除价格项失败: {e}")
            return False, f"批量删除价格项失败: {str(e)}", None
    
    def batch_soft_delete_items(self, item_ids):
        """批量软删除价格项（将is_active设为false）"""
        try:
            placeholders = ','.join(['%s'] * len(item_ids))
            query = f"""
            UPDATE price_items
            SET is_active = false, updated_at = %s
            WHERE id IN ({placeholders})
            RETURNING id
            """
            params = [datetime.now()] + list(item_ids)
            results = self.db.execute_query(query, tuple(params), fetch_all=True)
            
            updated_count = len(results) if results else 0
            return True, f"成功停用 {updated_count} 条价格项", {'updated_count': updated_count}
            
        except Exception as e:
            logger.error(f"批量软删除价格项失败: {e}")
            return False, f"批量软删除价格项失败: {str(e)}", None
    
    def get_items_by_version_and_category(self, version_id, category, active_only=True):
        """根据版本和类别获取价格项"""
        try:
            query = """
            SELECT id, version_id, category, sub_category, price, unit, work_hours, 
                   min_num, add_price, weight_num, note, instruction, is_active, 
                   created_by, created_at, updated_at
            FROM price_items
            WHERE version_id = %s AND category = %s
            """
            params = [version_id, category]
            
            if active_only:
                query += " AND is_active = true"
            
            query += " ORDER BY created_at DESC"
            
            results = self.db.execute_query(query, tuple(params), fetch_all=True)
            return True, "获取成功", self._format_items_list(results)
            
        except Exception as e:
            logger.error(f"获取价格项失败: {e}")
            return False, f"获取价格项失败: {str(e)}", None

# 创建服务实例
item_service = PriceItemService()

# ==================== API路由 ====================

@price_items_bp.route('', methods=['POST'])
def create_item():
    """
    创建价格项
    
    请求体:
    {
        "id": "P001",
        "version_id": "v1.0",
        "category": "wire",
        "sub_category": "线割加工",
        "price": "100.00",
        "unit": "元/小时",
        "work_hours": "1.5",
        "min_num": "50",
        "add_price": "10.00",
        "weight_num": "1.2",
        "note": "备注信息",
        "instruction": "计算说明",
        "is_active": true,
        "created_by": "admin"
    }
    """
    try:
        data = request.get_json()
        
        # 验证必填字段
        if 'id' not in data:
            return jsonify({
                'success': False,
                'message': '缺少必填字段: id'
            }), 400
        
        success, message, result = item_service.create_item(data)
        
        if success:
            return jsonify({
                'success': True,
                'message': message,
                'data': result
            }), 201
        else:
            return jsonify({
                'success': False,
                'message': message
            }), 400
            
    except Exception as e:
        logger.error(f"创建价格项接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@price_items_bp.route('/<item_id>', methods=['GET'])
def get_item(item_id):
    """获取单个价格项详情"""
    try:
        success, message, result = item_service.get_item_by_id(item_id)
        
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
        logger.error(f"获取价格项接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@price_items_bp.route('', methods=['GET'])
def get_items():
    """
    获取价格项列表（支持分页和筛选）
    
    查询参数:
    - page: 页码（默认1）
    - page_size: 每页数量（默认20）
    - version_id: 版本号筛选
    - category: 类别筛选（wire/special/base）
    - sub_category: 子类筛选（模糊搜索）
    - is_active: 是否激活筛选
    """
    try:
        # 获取分页参数
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))
        
        # 获取筛选参数
        filters = {}
        if request.args.get('version_id'):
            filters['version_id'] = request.args.get('version_id')
        if request.args.get('category'):
            filters['category'] = request.args.get('category')
        if request.args.get('sub_category'):
            filters['sub_category'] = request.args.get('sub_category')
        if request.args.get('is_active'):
            filters['is_active'] = request.args.get('is_active').lower() == 'true'
        
        success, message, result = item_service.get_items(filters, page, page_size)
        
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
            }), 400
            
    except Exception as e:
        logger.error(f"获取价格项列表接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@price_items_bp.route('/<item_id>', methods=['PUT'])
def update_item(item_id):
    """
    更新价格项
    
    请求体（所有字段可选）:
    {
        "version_id": "v1.1",
        "category": "special",
        "sub_category": "特殊加工",
        "price": "150.00",
        "unit": "元/件",
        "work_hours": "2.0",
        "min_num": "100",
        "add_price": "20.00",
        "weight_num": "1.5",
        "note": "更新后的备注",
        "instruction": "更新后的说明",
        "is_active": false,
        "created_by": "admin"
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'message': '请求体不能为空'
            }), 400
        
        success, message, result = item_service.update_item(item_id, data)
        
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
            }), 404 if '不存在' in message else 400
            
    except Exception as e:
        logger.error(f"更新价格项接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@price_items_bp.route('/<item_id>', methods=['DELETE'])
def delete_item(item_id):
    """删除价格项（硬删除）"""
    try:
        success, message, _ = item_service.delete_item(item_id)
        
        if success:
            return jsonify({
                'success': True,
                'message': message
            })
        else:
            return jsonify({
                'success': False,
                'message': message
            }), 404
            
    except Exception as e:
        logger.error(f"删除价格项接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@price_items_bp.route('/<item_id>/soft-delete', methods=['PUT', 'PATCH'])
def soft_delete_item(item_id):
    """
    软删除价格项（将is_active设为false）
    
    使用PUT或PATCH方法访问: /api/price-items/{item_id}/soft-delete
    """
    try:
        success, message, result = item_service.soft_delete_item(item_id)
        
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
        logger.error(f"软删除价格项接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@price_items_bp.route('/batch-delete', methods=['POST'])
def batch_delete_items():
    """
    批量删除价格项（硬删除）
    
    请求体:
    {
        "ids": ["P001", "P002", "P003"]
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'ids' not in data:
            return jsonify({
                'success': False,
                'message': '缺少ids字段'
            }), 400
        
        item_ids = data['ids']
        if not isinstance(item_ids, list) or len(item_ids) == 0:
            return jsonify({
                'success': False,
                'message': 'ids必须是非空数组'
            }), 400
        
        success, message, result = item_service.batch_delete_items(item_ids)
        
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
            }), 400
            
    except Exception as e:
        logger.error(f"批量删除价格项接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@price_items_bp.route('/batch-soft-delete', methods=['POST'])
def batch_soft_delete_items():
    """
    批量软删除价格项（将is_active设为false）
    
    请求体:
    {
        "ids": ["P001", "P002", "P003"]
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'ids' not in data:
            return jsonify({
                'success': False,
                'message': '缺少ids字段'
            }), 400
        
        item_ids = data['ids']
        if not isinstance(item_ids, list) or len(item_ids) == 0:
            return jsonify({
                'success': False,
                'message': 'ids必须是非空数组'
            }), 400
        
        success, message, result = item_service.batch_soft_delete_items(item_ids)
        
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
            }), 400
            
    except Exception as e:
        logger.error(f"批量软删除价格项接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@price_items_bp.route('/by-version-category', methods=['GET'])
def get_items_by_version_and_category():
    """
    根据版本和类别获取价格项
    
    查询参数:
    - version_id: 版本号（必填）
    - category: 类别（必填）
    - active_only: 是否只返回激活的价格项（默认true）
    """
    try:
        version_id = request.args.get('version_id')
        category = request.args.get('category')
        active_only = request.args.get('active_only', 'true').lower() == 'true'
        
        if not version_id or not category:
            return jsonify({
                'success': False,
                'message': '缺少必填参数: version_id 和 category'
            }), 400
        
        success, message, result = item_service.get_items_by_version_and_category(
            version_id, category, active_only
        )
        
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
            }), 400
            
    except Exception as e:
        logger.error(f"获取价格项接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500
