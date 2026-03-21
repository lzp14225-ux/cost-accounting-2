"""
交互业务逻辑层
负责人：ZZH
"""
from typing import List, Dict, Any
from ..models.interaction_models import InteractionCard, InputField, UserResponse
from ..repositories.interaction_repository import InteractionRepository
from ..websocket import manager
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class InteractionService:
    """交互业务逻辑层"""
    
    def __init__(self):
        self.repo = InteractionRepository()
    
    async def create_missing_input_card(
        self,
        db: AsyncSession,
        job_id: str,
        missing_params: List[Dict[str, Any]]
    ) -> InteractionCard:
        """
        创建缺失参数输入卡片
        
        Args:
            job_id: 任务ID
            missing_params: 缺失参数列表
                [
                    {
                        "subgraph_id": "UP01",
                        "param_name": "thickness_mm",
                        "param_label": "厚度(mm)"
                    }
                ]
        
        Returns:
            InteractionCard: 交互卡片
        """
        card_id = str(uuid.uuid4())
        
        # 构建输入字段
        fields = []
        subgraphs = []
        
        for param in missing_params:
            subgraph_id = param["subgraph_id"]
            param_name = param["param_name"]
            param_label = param.get("param_label", param_name)
            
            subgraphs.append(subgraph_id)
            
            # 根据参数类型创建不同的输入字段
            if param_name == "thickness_mm":
                field = InputField(
                    key=f"{subgraph_id}.{param_name}",
                    label=f"{subgraph_id} - {param_label}",
                    component="number",
                    required=True,
                    default=10,
                    min=1,
                    max=500,
                    placeholder="请输入厚度",
                    help_text="单位：毫米(mm)"
                )
            elif param_name == "material":
                field = InputField(
                    key=f"{subgraph_id}.{param_name}",
                    label=f"{subgraph_id} - {param_label}",
                    component="select",
                    required=True,
                    options=["45#", "Cr12MoV", "SKD11", "NAK80", "S136"],
                    placeholder="请选择材质"
                )
            elif param_name == "wire_length_mm":
                field = InputField(
                    key=f"{subgraph_id}.{param_name}",
                    label=f"{subgraph_id} - {param_label}",
                    component="number",
                    required=True,
                    default=0,
                    min=0,
                    max=100000,
                    placeholder="请输入线割长度",
                    help_text="单位：毫米(mm)"
                )
            else:
                # 默认文本输入
                field = InputField(
                    key=f"{subgraph_id}.{param_name}",
                    label=f"{subgraph_id} - {param_label}",
                    component="text",
                    required=True,
                    placeholder=f"请输入{param_label}"
                )
            
            fields.append(field)
        
        # 创建卡片
        card = InteractionCard(
            card_id=card_id,
            card_type="missing_input",
            title="缺少必要参数",
            message=f"以下{len(set(subgraphs))}个子图缺少必要参数，请补充：",
            severity="error",
            fields=fields,
            subgraphs=list(set(subgraphs)),  # 去重
            buttons=["submit", "re_recognize"]
        )
        
        # 保存到数据库
        await self.repo.create_interaction(
            db=db,
            job_id=job_id,
            card_id=card_id,
            card_type="missing_input",
            card_data=card.dict()
        )
        
        logger.info(f"✅ 交互卡片已创建: job_id={job_id}, card_id={card_id}, fields={len(fields)}")
        
        return card
    
    async def push_card_to_websocket(
        self,
        job_id: str,
        card: InteractionCard
    ):
        """
        推送卡片到WebSocket
        
        Args:
            job_id: 任务ID
            card: 交互卡片
        """
        message = {
            "type": "need_user_input",
            "job_id": job_id,
            "timestamp": datetime.now().isoformat(),
            "data": card.dict()
        }
        
        await manager.broadcast(job_id, message)
        
        logger.info(f"✅ 交互卡片已推送到WebSocket: job_id={job_id}, card_id={card.card_id}")
        print(f"📤 交互卡片已推送: job_id={job_id}, card_id={card.card_id}")
    
    async def handle_user_response(
        self,
        db: AsyncSession,
        job_id: str,
        response: UserResponse
    ) -> Dict[str, Any]:
        """
        处理用户响应
        
        Args:
            db: 数据库会话
            job_id: 任务ID
            response: 用户响应
        
        Returns:
            处理结果，包含解析后的参数
        """
        # 1. 验证card_id存在
        interaction = await self.repo.get_interaction_by_card_id(
            db, response.card_id
        )
        
        if not interaction:
            raise ValueError(f"交互卡片不存在: {response.card_id}")
        
        if interaction.status != "pending":
            raise ValueError(f"交互卡片已处理: {response.card_id}, 状态: {interaction.status}")
        
        # 2. 验证输入参数
        if response.action == "submit":
            import json
            card_data = json.loads(interaction.card_data) if isinstance(interaction.card_data, str) else interaction.card_data
            validated_inputs = self._validate_inputs(
                response.inputs,
                card_data
            )
        else:
            validated_inputs = {}
        
        # 3. 更新数据库
        await self.repo.update_interaction_response(
            db=db,
            card_id=response.card_id,
            action=response.action,
            user_response=response.dict()
        )
        
        # 4. 推送确认消息到WebSocket
        await manager.broadcast(job_id, {
            "type": "interaction_response_received",
            "job_id": job_id,
            "timestamp": datetime.now().isoformat(),
            "data": {
                "card_id": response.card_id,
                "action": response.action,
                "message": "用户响应已接收，继续处理..."
            }
        })
        
        logger.info(f"✅ 用户响应已处理: job_id={job_id}, card_id={response.card_id}, action={response.action}")
        
        # 5. 返回处理结果
        return {
            "action": response.action,
            "inputs": validated_inputs,
            "card_id": response.card_id
        }
    
    def _validate_inputs(
        self,
        inputs: Dict[str, Any],
        card_data: dict
    ) -> Dict[str, Any]:
        """
        验证用户输入
        
        Args:
            inputs: 用户输入
            card_data: 卡片数据
        
        Returns:
            验证后的输入
        """
        validated = {}
        fields = card_data.get("fields", [])
        
        for field in fields:
            key = field["key"]
            value = inputs.get(key)
            
            # 检查必填项
            if field.get("required") and value is None:
                raise ValueError(f"缺少必填参数: {field['label']}")
            
            # 验证数字范围
            if field["component"] == "number" and value is not None:
                min_val = field.get("min")
                max_val = field.get("max")
                
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    raise ValueError(f"{field['label']} 必须是数字")
                
                if min_val is not None and value < min_val:
                    raise ValueError(f"{field['label']} 不能小于 {min_val}")
                
                if max_val is not None and value > max_val:
                    raise ValueError(f"{field['label']} 不能大于 {max_val}")
            
            # 验证选择项
            if field["component"] == "select" and value is not None:
                options = field.get("options", [])
                if options and value not in options:
                    raise ValueError(f"{field['label']} 必须是以下选项之一: {', '.join(options)}")
            
            validated[key] = value
        
        logger.info(f"✅ 输入验证通过: {len(validated)} 个参数")
        
        return validated
