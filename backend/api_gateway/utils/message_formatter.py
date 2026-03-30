"""
WebSocket 消息格式化器
负责人：系统架构组

职责：
1. 将 WebSocket 消息转换为人类可读的富文本
2. 构建 metadata 结构
3. 支持多种消息类型的格式化
"""
from typing import Dict, Any, Tuple, List, Optional
import logging

logger = logging.getLogger(__name__)


def format_websocket_message(ws_message: dict) -> Tuple[str, dict]:
    """
    将 WebSocket 消息转换为 chat_messages 格式
    
    Args:
        ws_message: WebSocket 消息
    
    Returns:
        (content, metadata)
        - content: 人类可读的富文本
        - metadata: 结构化数据
    
    Example:
        >>> ws_msg = {"type": "review_completed", "modifications_count": 3}
        >>> content, metadata = format_websocket_message(ws_msg)
        >>> print(content)
        "审核已完成，共 3 处修改已保存"
    """
    message_type = ws_message.get('type')
    
    # 根据消息类型调用对应的格式化函数
    formatters = {
        'need_user_input': format_interaction_card,
        'modification_confirmation': format_modification_confirmation,
        'review_data': format_review_data,
        'review_display_view': format_review_display_view,  # 新增
        'completion_request': format_completion_request,    # 新增
        'review_completed': format_review_completed,
        'operation_completed': format_operation_completed,
        'progress': format_progress,  # 新增
    }
    
    formatter = formatters.get(message_type)
    if not formatter:
        logger.warning(f"未知的消息类型: {message_type}")
        return format_unknown_message(ws_message)
    
    try:
        content = formatter(ws_message)
        metadata = build_metadata(ws_message)
        return content, metadata
    
    except Exception as e:
        logger.error(f"格式化消息失败: {e}", exc_info=True)
        return format_unknown_message(ws_message)


def format_interaction_card(ws_message: dict) -> str:
    """
    格式化交互卡片消息
    
    Args:
        ws_message: WebSocket 消息
    
    Returns:
        人类可读的文本
    
    Example:
        系统请求输入参数（缺少必要参数）：
        - UP01 - 厚度(mm) (单位：毫米)
        - UP01 - 材质
    """
    data = ws_message.get('data', {})
    if isinstance(data, dict) and isinstance(data.get('data'), dict):
        data = data.get('data', {})
    title = data.get('title', '系统请求')
    fields = data.get('fields', [])
    
    content = f"系统请求输入参数（{title}）：\n"
    
    for field in fields:
        label = field.get('label', field.get('key', '未知字段'))
        help_text = field.get('help_text', '')
        
        content += f"- {label}"
        if help_text:
            content += f" ({help_text})"
        content += "\n"
    
    return content.strip()


def format_modification_confirmation(ws_message: dict) -> str:
    """
    格式化修改确认消息
    
    Args:
        ws_message: WebSocket 消息
    
    Returns:
        人类可读的文本
    
    Example:
        待确认的修改：
        - UP01 材质: 45# → 718
        - UP02 厚度: 10mm → 15mm
    """
    modifications = ws_message.get('modifications', [])
    
    # 🆕 兼容处理：如果 modifications 是修改记录（包含 intent），则提取实际的修改数据
    if modifications and isinstance(modifications[0], dict):
        first_mod = modifications[0]
        
        # 如果是修改记录（包含 intent），则从 modified_data 获取实际修改
        if 'intent' in first_mod:
            # 这是一个操作记录，不是实际的数据修改
            intent = first_mod.get('intent', '未知操作')
            text = first_mod.get('text', '')
            
            intent_names = {
                'DATA_MODIFICATION': '数据修改',
                'QUERY_DETAILS': '查询详情',
                'FEATURE_RECOGNITION': '特征识别',
                'PRICE_CALCULATION': '价格计算',
                'GENERAL_CHAT': '普通对话',
            }
            
            intent_display = intent_names.get(intent, intent)
            
            # 从 modified_data 获取影响的子图
            modified_data = ws_message.get('modified_data', {})
            subgraph_ids = modified_data.get('subgraph_ids', [])
            count = modified_data.get('count', len(subgraph_ids))
            
            if subgraph_ids:
                content = f"操作已应用：{intent_display}\n"
                content += f"用户指令：{text}\n"
                content += f"影响的子图：{count} 个"
            else:
                content = f"操作已应用：{intent_display}\n"
                content += f"用户指令：{text}"
            
            return content
    
    # 原有逻辑：处理实际的数据修改列表
    if not modifications:
        return "待确认的修改（无修改项）"
    
    content = "待确认的修改：\n"
    content += format_modifications(modifications)
    
    return content.strip()


def format_modifications(modifications: List[Dict[str, Any]]) -> str:
    """
    格式化修改列表
    
    Args:
        modifications: 修改列表
    
    Returns:
        格式化后的文本
    """
    lines = []
    
    for mod in modifications:
        subgraph_id = mod.get('subgraph_id', '未知')
        field = mod.get('field', '未知字段')
        old_value = mod.get('old_value', '')
        new_value = mod.get('new_value', '')
        
        # 格式化字段名（更友好）
        field_display = format_field_name(field)
        
        # 格式化值（添加单位）
        old_display = format_field_value(field, old_value)
        new_display = format_field_value(field, new_value)
        
        lines.append(f"- {subgraph_id} {field_display}: {old_display} → {new_display}")
    
    return "\n".join(lines)


def format_field_name(field: str) -> str:
    """
    格式化字段名为更友好的显示名称
    
    Args:
        field: 字段名
    
    Returns:
        显示名称
    """
    field_names = {
        'material': '材质',
        'thickness_mm': '厚度',
        'wire_length_mm': '线割长度',
        'process_code': '工艺代码',
        'feature_type': '特征类型',
        'volume_mm3': '体积',
        'surface_area_mm2': '表面积',
    }
    
    return field_names.get(field, field)


def format_field_value(field: str, value: Any) -> str:
    """
    格式化字段值（添加单位）
    
    Args:
        field: 字段名
        value: 字段值
    
    Returns:
        格式化后的值
    """
    if value is None or value == '':
        return '（空）'
    
    # 添加单位
    if field in ['thickness_mm', 'wire_length_mm']:
        return f"{value}mm"
    elif field in ['volume_mm3']:
        return f"{value}mm³"
    elif field in ['surface_area_mm2']:
        return f"{value}mm²"
    
    return str(value)


def format_review_data(ws_message: dict) -> str:
    """
    格式化审核数据推送消息
    
    Args:
        ws_message: WebSocket 消息
    
    Returns:
        人类可读的文本
    
    Example:
        审核数据已加载：
        - 子图: 10 个
        - 特征: 15 个
        - 价格快照: 8 个
    """
    data = ws_message.get('data', {})
    
    subgraphs_count = len(data.get('subgraphs', []))
    features_count = len(data.get('features', []))
    price_snapshots_count = len(data.get('price_snapshots', []))
    
    content = "审核数据已加载：\n"
    content += f"- 子图: {subgraphs_count} 个\n"
    content += f"- 特征: {features_count} 个\n"
    content += f"- 价格快照: {price_snapshots_count} 个"
    
    return content


def format_review_display_view(ws_message: dict) -> str:
    """
    格式化展示视图推送消息
    
    Args:
        ws_message: WebSocket 消息
    
    Returns:
        人类可读的文本
    
    Example:
        展示视图已加载：10 条记录
    """
    data = ws_message.get('data', [])
    count = len(data) if isinstance(data, list) else 0
    
    content = f"展示视图已加载：{count} 条记录"
    
    return content


def format_completion_request(ws_message: dict) -> str:
    """
    格式化补全请求消息
    
    Args:
        ws_message: WebSocket 消息
    
    Returns:
        人类可读的文本
    
    Example:
        系统请求补全缺失字段：
        - UP01 - 材质
        - UP02 - 厚度
        
        建议：根据零件编号推测...
    """
    data = ws_message.get('data', {})
    missing_fields = data.get('missing_fields', [])
    nc_failed_items = data.get('nc_failed_items', [])
    suggestion = data.get('suggestion', '')
    message = data.get('message', '请补全缺失字段')
    
    content = f"{message}\n"
    
    if missing_fields:
        content += "\n缺失字段：\n"
        for field_info in missing_fields[:10]:  # 最多显示10个
            subgraph_id = field_info.get('subgraph_id', '未知')
            field = field_info.get('field', '未知字段')
            field_display = format_field_name(field)
            content += f"- {subgraph_id} - {field_display}\n"
        
        if len(missing_fields) > 10:
            content += f"... 还有 {len(missing_fields) - 10} 个字段\n"
    
    if nc_failed_items:
        content += "\nNC 识别失败物料：\n"
        for failed_item in nc_failed_items[:10]:
            part_code = failed_item.get('part_code') or failed_item.get('record_name', '未知物料')
            part_name = failed_item.get('part_name')
            content += f"- {part_code}"
            if part_name:
                content += f" - {part_name}"
            content += "\n"
        if len(nc_failed_items) > 10:
            content += f"... 还有 {len(nc_failed_items) - 10} 个物料\n"

    if suggestion:
        content += f"\n建议：{suggestion[:200]}"  # 限制长度
        if len(suggestion) > 200:
            content += "..."
    
    return content.strip()


def format_review_completed(ws_message: dict) -> str:
    """
    格式化审核完成消息
    
    Args:
        ws_message: WebSocket 消息
    
    Returns:
        人类可读的文本
    
    Example:
        审核已完成，共 3 处修改已保存
    """
    modifications_count = ws_message.get('modifications_count', 0)
    
    if modifications_count == 0:
        return "审核已完成，无修改"
    
    return f"审核已完成，共 {modifications_count} 处修改已保存"


def format_operation_completed(ws_message: dict) -> str:
    """
    格式化操作完成消息
    
    Args:
        ws_message: WebSocket 消息
    
    Returns:
        人类可读的文本
    
    Example:
        操作已完成：查询详情
    """
    action_type = ws_message.get('action_type', '未知操作')
    
    # 格式化操作类型
    action_names = {
        'QUERY_DETAILS': '查询详情',
        'FEATURE_RECOGNITION': '特征识别',
        'PRICE_CALCULATION': '价格计算',
        'DATA_MODIFICATION': '数据修改',
    }
    
    action_display = action_names.get(action_type, action_type)
    
    return f"操作已完成：{action_display}"


def format_progress(ws_message: dict) -> str:
    """
    格式化进度消息
    
    Args:
        ws_message: WebSocket 消息
    
    Returns:
        人类可读的文本
    
    Example:
        任务进度：CAD 解析 (20%)
        正在解析 CAD 文件...
    """
    data = ws_message.get('data', {})
    stage = data.get('stage', '未知阶段')
    progress = data.get('progress', 0)
    message = data.get('message', '')
    
    # 格式化阶段名称
    stage_names = {
        'initializing': '初始化',
        'cad_parsing': 'CAD 解析',
        'feature_recognition': '特征识别',
        'check_params': '参数检查',
        'waiting_input': '等待用户输入',
        'nc_calculation': 'NC 时间计算',
        'decision': '工艺决策',
        'pricing': '价格计算',
        'report_generation': '报表生成',
        'archiving': '审计归档',
    }
    
    stage_display = stage_names.get(stage, stage)
    
    # 构建内容
    if progress > 0:
        content = f"任务进度：{stage_display} ({progress}%)"
    else:
        content = f"任务进度：{stage_display}"
    
    if message:
        content += f"\n{message}"
    
    return content


def format_unknown_message(ws_message: dict) -> Tuple[str, dict]:
    """
    格式化未知类型的消息
    
    Args:
        ws_message: WebSocket 消息
    
    Returns:
        (content, metadata)
    """
    message_type = ws_message.get('type', 'unknown')
    content = f"系统消息（{message_type}）"
    
    metadata = {
        'message_type': message_type,
        'original_ws_message': ws_message
    }
    
    return content, metadata


def build_metadata(ws_message: dict) -> dict:
    """
    构建 metadata 结构
    
    Args:
        ws_message: WebSocket 消息
    
    Returns:
        metadata 字典
    """
    message_type = ws_message.get('type')
    
    metadata = {
        'message_type': message_type,
        'original_ws_message': ws_message  # 保留原始消息用于调试
    }
    
    # 根据消息类型添加额外的元数据
    if message_type == 'need_user_input':
        data = ws_message.get('data', {})
        metadata['card_id'] = data.get('card_id')
        metadata['fields_count'] = len(data.get('fields', []))
    
    elif message_type == 'modification_confirmation':
        modifications = ws_message.get('modifications', [])
        metadata['modifications_count'] = len(modifications)
    
    elif message_type == 'review_data':
        data = ws_message.get('data', {})
        metadata['subgraphs_count'] = len(data.get('subgraphs', []))
        metadata['features_count'] = len(data.get('features', []))
        metadata['price_snapshots_count'] = len(data.get('price_snapshots', []))
    
    elif message_type == 'review_display_view':
        data = ws_message.get('data', [])
        metadata['records_count'] = len(data) if isinstance(data, list) else 0
    
    elif message_type == 'completion_request':
        data = ws_message.get('data', {})
        metadata['missing_fields_count'] = len(data.get('missing_fields', []))
        metadata['nc_failed_items_count'] = len(data.get('nc_failed_items', []))
    
    elif message_type == 'review_completed':
        metadata['modifications_count'] = ws_message.get('modifications_count', 0)
    
    elif message_type == 'operation_completed':
        metadata['action_type'] = ws_message.get('action_type')
    
    elif message_type == 'progress':
        data = ws_message.get('data', {})
        if isinstance(data, dict) and isinstance(data.get('data'), dict):
            data = data.get('data', {})
        metadata['stage'] = data.get('stage')
        metadata['progress'] = data.get('progress', 0)
    
    return metadata


def format_current_state(state: dict) -> str:
    """
    格式化当前审核状态（用于 LLM 上下文）
    
    Args:
        state: 审核状态
    
    Returns:
        格式化后的状态描述
    
    Example:
        当前审核会话信息：
        - 状态: reviewing
        - 子图数量: 10
        - 特征数量: 15
        - 待确认修改: 2 处
    """
    data = state.get('data', {})
    
    content = "当前审核会话信息：\n"
    content += f"- 状态: {state.get('status', 'unknown')}\n"
    content += f"- 子图数量: {len(data.get('subgraphs', []))}\n"
    content += f"- 特征数量: {len(data.get('features', []))}\n"
    content += f"- 待确认修改: {len(state.get('modifications', []))} 处"
    
    return content
