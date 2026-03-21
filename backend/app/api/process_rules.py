#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工艺规则管理模块
提供工艺规则的增删改查功能
"""

from flask import Blueprint, request, jsonify
import logging
from datetime import datetime
from app.services.database import db_manager

logger = logging.getLogger(__name__)

# 创建蓝图
process_rules_bp = Blueprint('process_rules', __name__, url_prefix='/api/process-rules')

class ProcessRuleService:
    """工艺规则服务类"""
    
    # 规则条件映射表
    RULE_MAPPING = {
        '慢丝割一修一': 'slow_and_one',
        '慢丝割一刀': 'slow_cut',
        '快丝割一刀': 'fast_cut',
        '中丝割一修一': 'middle_and_one'
    }
    
    def __init__(self):
        self.db = db_manager
    
    def _format_datetime(self, dt):
        """格式化datetime为ISO格式字符串"""
        if dt is None:
            return None
        if isinstance(dt, datetime):
            return dt.strftime('%Y-%m-%dT%H:%M:%S')
        return dt
    
    def _format_rule_data(self, rule):
        """格式化规则数据，将datetime转换为字符串"""
        if not rule:
            return None
        
        formatted_rule = dict(rule)
        if 'created_at' in formatted_rule:
            formatted_rule['created_at'] = self._format_datetime(formatted_rule['created_at'])
        
        return formatted_rule
    
    def _format_rules_list(self, rules):
        """格式化规则列表"""
        if not rules:
            return []
        return [self._format_rule_data(rule) for rule in rules]
    
    def _parse_description_to_conditions(self, description):
        """
        根据description解析规则条件
        
        Args:
            description: 描述文本
        
        Returns:
            (conditions, output_params, error_message)
        """
        if not description:
            return None, None, "description不能为空"
        
        # 查找匹配的规则
        matched_rule = None
        for rule_text, rule_code in self.RULE_MAPPING.items():
            if rule_text in description:
                matched_rule = rule_code
                break
        
        if not matched_rule:
            # 列出所有支持的规则
            supported_rules = ', '.join(self.RULE_MAPPING.keys())
            return None, None, f"description中的规则条件无法识别。支持的规则: {supported_rules}"
        
        # 生成conditions和output_params
        conditions = matched_rule
        output_params = matched_rule
        
        return conditions, output_params, None
    
    def create_rule(self, rule_data):
        """创建工艺规则"""
        try:
            # 如果没有提供conditions和output_params，从description解析
            if 'conditions' not in rule_data or 'output_params' not in rule_data:
                if 'description' not in rule_data:
                    return False, "缺少description字段或conditions/output_params字段", None
                
                conditions, output_params, error_msg = self._parse_description_to_conditions(
                    rule_data['description']
                )
                
                if error_msg:
                    return False, error_msg, None
                
                rule_data['conditions'] = conditions
                rule_data['output_params'] = output_params
            
            # 如果没有提供version_id，使用默认值 v1.0
            if 'version_id' not in rule_data:
                rule_data['version_id'] = 'v1.0'
            
            query = """
            INSERT INTO process_rules 
            (id, version_id, feature_type, name, description, priority, 
             is_active, conditions, output_params, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, version_id, feature_type, name, description,
                      priority, is_active, conditions, output_params, created_at
            """
            
            params = (
                rule_data['id'],
                rule_data['version_id'],
                rule_data['feature_type'],
                rule_data['name'],
                rule_data.get('description'),
                rule_data.get('priority', 1),
                rule_data.get('is_active', True),
                rule_data['conditions'],
                rule_data['output_params'],
                datetime.now()
            )
            
            result = self.db.execute_query(query, params, fetch_one=True)
            return True, "规则创建成功", self._format_rule_data(result)
            
        except Exception as e:
            logger.error(f"创建规则失败: {e}")
            return False, f"创建规则失败: {str(e)}", None
    
    def get_rule_by_id(self, rule_id):
        """根据ID获取规则"""
        try:
            query = """
            SELECT id, version_id, feature_type, name, description,
                   priority, is_active, conditions, output_params, created_at
            FROM process_rules
            WHERE id = %s
            """
            
            result = self.db.execute_query(query, (rule_id,), fetch_one=True)
            
            if result:
                return True, "获取成功", self._format_rule_data(result)
            else:
                return False, "规则不存在", None
                
        except Exception as e:
            logger.error(f"获取规则失败: {e}")
            return False, f"获取规则失败: {str(e)}", None
    
    def get_rules(self, filters=None, page=1, page_size=20):
        """获取规则列表（支持分页和筛选）"""
        try:
            # 构建查询条件
            conditions = []
            params = []
            
            # 默认只查询激活的规则
            is_active_filter = True
            
            if filters:
                if filters.get('version_id'):
                    conditions.append("version_id = %s")
                    params.append(filters['version_id'])
                
                if filters.get('feature_type'):
                    conditions.append("feature_type = %s")
                    params.append(filters['feature_type'])
                
                if filters.get('is_active') is not None:
                    is_active_filter = filters['is_active']
                
                if filters.get('name'):
                    conditions.append("name ILIKE %s")
                    params.append(f"%{filters['name']}%")
            
            # 添加is_active条件
            conditions.append("is_active = %s")
            params.append(is_active_filter)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            # 查询总数
            count_query = f"SELECT COUNT(*) as total FROM process_rules WHERE {where_clause}"
            count_result = self.db.execute_query(count_query, tuple(params), fetch_one=True)
            total = count_result['total'] if count_result else 0
            
            # 查询数据
            offset = (page - 1) * page_size
            query = f"""
            SELECT id, version_id, feature_type, name, description,
                   priority, is_active, conditions, output_params, created_at
            FROM process_rules
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
                'data': self._format_rules_list(results)
            }
            
        except Exception as e:
            logger.error(f"获取规则列表失败: {e}")
            return False, f"获取规则列表失败: {str(e)}", None
    
    def update_rule(self, rule_id, update_data):
        """更新规则"""
        try:
            # 构建更新字段
            update_fields = []
            params = []
            
            allowed_fields = ['version_id', 'feature_type', 'name', 'description',
                            'priority', 'is_active', 'conditions', 'output_params']
            
            for field in allowed_fields:
                if field in update_data:
                    update_fields.append(f"{field} = %s")
                    params.append(update_data[field])
            
            if not update_fields:
                return False, "没有需要更新的字段", None
            
            params.append(rule_id)
            
            query = f"""
            UPDATE process_rules
            SET {', '.join(update_fields)}
            WHERE id = %s
            RETURNING id, version_id, feature_type, name, description,
                      priority, is_active, conditions, output_params, created_at
            """
            
            result = self.db.execute_query(query, tuple(params), fetch_one=True)
            
            if result:
                return True, "规则更新成功", self._format_rule_data(result)
            else:
                return False, "规则不存在", None
                
        except Exception as e:
            logger.error(f"更新规则失败: {e}")
            return False, f"更新规则失败: {str(e)}", None
    
    def delete_rule(self, rule_id):
        """删除规则（硬删除）"""
        try:
            query = "DELETE FROM process_rules WHERE id = %s RETURNING id"
            result = self.db.execute_query(query, (rule_id,), fetch_one=True)
            
            if result:
                return True, "规则删除成功", None
            else:
                return False, "规则不存在", None
                
        except Exception as e:
            logger.error(f"删除规则失败: {e}")
            return False, f"删除规则失败: {str(e)}", None
    
    def soft_delete_rule(self, rule_id):
        """软删除规则（将is_active设为false）"""
        try:
            query = """
            UPDATE process_rules
            SET is_active = false
            WHERE id = %s
            RETURNING id, version_id, feature_type, name, description,
                      priority, is_active, conditions, output_params, created_at
            """
            result = self.db.execute_query(query, (rule_id,), fetch_one=True)
            
            if result:
                return True, "规则已停用", self._format_rule_data(result)
            else:
                return False, "规则不存在", None
                
        except Exception as e:
            logger.error(f"软删除规则失败: {e}")
            return False, f"软删除规则失败: {str(e)}", None
    
    def batch_delete_rules(self, rule_ids):
        """批量删除规则（硬删除）"""
        try:
            placeholders = ','.join(['%s'] * len(rule_ids))
            query = f"DELETE FROM process_rules WHERE id IN ({placeholders}) RETURNING id"
            results = self.db.execute_query(query, tuple(rule_ids), fetch_all=True)
            
            deleted_count = len(results) if results else 0
            return True, f"成功删除 {deleted_count} 条规则", {'deleted_count': deleted_count}
            
        except Exception as e:
            logger.error(f"批量删除规则失败: {e}")
            return False, f"批量删除规则失败: {str(e)}", None
    
    def batch_soft_delete_rules(self, rule_ids):
        """批量软删除规则（将is_active设为false）"""
        try:
            placeholders = ','.join(['%s'] * len(rule_ids))
            query = f"""
            UPDATE process_rules
            SET is_active = false
            WHERE id IN ({placeholders})
            RETURNING id
            """
            results = self.db.execute_query(query, tuple(rule_ids), fetch_all=True)
            
            updated_count = len(results) if results else 0
            return True, f"成功停用 {updated_count} 条规则", {'updated_count': updated_count}
            
        except Exception as e:
            logger.error(f"批量软删除规则失败: {e}")
            return False, f"批量软删除规则失败: {str(e)}", None
    
    def get_rules_by_version_and_type(self, version_id, feature_type, active_only=True):
        """根据版本和特征类型获取规则"""
        try:
            query = """
            SELECT id, version_id, feature_type, name, description,
                   priority, is_active, conditions, output_params, created_at
            FROM process_rules
            WHERE version_id = %s AND feature_type = %s
            """
            params = [version_id, feature_type]
            
            if active_only:
                query += " AND is_active = true"
            
            query += " ORDER BY created_at DESC"
            
            results = self.db.execute_query(query, tuple(params), fetch_all=True)
            return True, "获取成功", self._format_rules_list(results)
            
        except Exception as e:
            logger.error(f"获取规则失败: {e}")
            return False, f"获取规则失败: {str(e)}", None

# 创建服务实例
rule_service = ProcessRuleService()

# ==================== API路由 ====================

@process_rules_bp.route('', methods=['POST'])
def create_rule():
    """
    创建工艺规则
    
    请求体（简化版）:
    {
        "id": "R001",
        "name": "线割规则1",
        "feature_type": "wire",
        "description": "中丝割一修一"
    }
    
    或完整版:
    {
        "id": "R001",
        "version_id": "v1.0",
        "feature_type": "WIRE",
        "name": "线割规则1",
        "description": "规则描述",
        "priority": 10,
        "is_active": true,
        "conditions": "条件字符串",
        "output_params": "输出参数字符串"
    }
    
    支持的description规则:
    - 慢丝割一修一 -> slow_and_one
    - 慢丝割一刀 -> slow_cut
    - 快丝割一刀 -> fast_cut
    - 中丝割一修一 -> middle_and_one
    """
    try:
        data = request.get_json()
        
        # 验证必填字段
        required_fields = ['id', 'feature_type', 'name', 'description']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'message': f'缺少必填字段: {field}'
                }), 400
        
        # 验证字段长度
        if 'conditions' in data and len(data['conditions']) > 255:
            return jsonify({
                'success': False,
                'message': 'conditions字段长度不能超过255'
            }), 400
        
        if 'output_params' in data and len(data['output_params']) > 255:
            return jsonify({
                'success': False,
                'message': 'output_params字段长度不能超过255'
            }), 400
        
        success, message, result = rule_service.create_rule(data)
        
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
        logger.error(f"创建规则接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@process_rules_bp.route('/<rule_id>', methods=['GET'])
def get_rule(rule_id):
    """获取单个规则详情"""
    try:
        success, message, result = rule_service.get_rule_by_id(rule_id)
        
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
        logger.error(f"获取规则接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@process_rules_bp.route('', methods=['GET'])
def get_rules():
    """
    获取规则列表（支持分页和筛选）
    
    查询参数:
    - page: 页码（默认1）
    - page_size: 每页数量（默认20）
    - version_id: 版本号筛选
    - feature_type: 特征类型筛选
    - is_active: 是否激活筛选
    - name: 名称模糊搜索
    """
    try:
        # 获取分页参数
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))
        
        # 获取筛选参数
        filters = {}
        if request.args.get('version_id'):
            filters['version_id'] = request.args.get('version_id')
        if request.args.get('feature_type'):
            filters['feature_type'] = request.args.get('feature_type')
        if request.args.get('is_active'):
            filters['is_active'] = request.args.get('is_active').lower() == 'true'
        if request.args.get('name'):
            filters['name'] = request.args.get('name')
        
        success, message, result = rule_service.get_rules(filters, page, page_size)
        
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
        logger.error(f"获取规则列表接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@process_rules_bp.route('/<rule_id>', methods=['PUT'])
def update_rule(rule_id):
    """
    更新规则
    
    请求体（所有字段可选）:
    {
        "version_id": "v1.1",
        "feature_type": "NC",
        "name": "更新后的名称",
        "description": "更新后的描述",
        "priority": 20,
        "is_active": false,
        "conditions": "新条件",
        "output_params": "新输出参数"
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'message': '请求体不能为空'
            }), 400
        
        # 验证字段长度
        if 'conditions' in data and len(data['conditions']) > 255:
            return jsonify({
                'success': False,
                'message': 'conditions字段长度不能超过255'
            }), 400
        
        if 'output_params' in data and len(data['output_params']) > 255:
            return jsonify({
                'success': False,
                'message': 'output_params字段长度不能超过255'
            }), 400
        
        success, message, result = rule_service.update_rule(rule_id, data)
        
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
        logger.error(f"更新规则接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@process_rules_bp.route('/<rule_id>', methods=['DELETE'])
def delete_rule(rule_id):
    """删除规则（硬删除）"""
    try:
        success, message, _ = rule_service.delete_rule(rule_id)
        
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
        logger.error(f"删除规则接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@process_rules_bp.route('/<rule_id>/soft-delete', methods=['PUT', 'PATCH'])
def soft_delete_rule(rule_id):
    """
    软删除规则（将is_active设为false）
    
    使用PUT或PATCH方法访问: /api/process-rules/{rule_id}/soft-delete
    """
    try:
        success, message, result = rule_service.soft_delete_rule(rule_id)
        
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
        logger.error(f"软删除规则接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@process_rules_bp.route('/batch-delete', methods=['POST'])
def batch_delete_rules():
    """
    批量删除规则（硬删除）
    
    请求体:
    {
        "ids": ["R001", "R002", "R003"]
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'ids' not in data:
            return jsonify({
                'success': False,
                'message': '缺少ids字段'
            }), 400
        
        rule_ids = data['ids']
        if not isinstance(rule_ids, list) or len(rule_ids) == 0:
            return jsonify({
                'success': False,
                'message': 'ids必须是非空数组'
            }), 400
        
        success, message, result = rule_service.batch_delete_rules(rule_ids)
        
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
        logger.error(f"批量删除规则接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@process_rules_bp.route('/batch-soft-delete', methods=['POST'])
def batch_soft_delete_rules():
    """
    批量软删除规则（将is_active设为false）
    
    请求体:
    {
        "ids": ["R001", "R002", "R003"]
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'ids' not in data:
            return jsonify({
                'success': False,
                'message': '缺少ids字段'
            }), 400
        
        rule_ids = data['ids']
        if not isinstance(rule_ids, list) or len(rule_ids) == 0:
            return jsonify({
                'success': False,
                'message': 'ids必须是非空数组'
            }), 400
        
        success, message, result = rule_service.batch_soft_delete_rules(rule_ids)
        
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
        logger.error(f"批量软删除规则接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@process_rules_bp.route('/by-version-type', methods=['GET'])
def get_rules_by_version_and_type():
    """
    根据版本和特征类型获取规则
    
    查询参数:
    - version_id: 版本号（必填）
    - feature_type: 特征类型（必填）
    - active_only: 是否只返回激活的规则（默认true）
    """
    try:
        version_id = request.args.get('version_id')
        feature_type = request.args.get('feature_type')
        active_only = request.args.get('active_only', 'true').lower() == 'true'
        
        if not version_id or not feature_type:
            return jsonify({
                'success': False,
                'message': '缺少必填参数: version_id 和 feature_type'
            }), 400
        
        success, message, result = rule_service.get_rules_by_version_and_type(
            version_id, feature_type, active_only
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
        logger.error(f"获取规则接口异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500