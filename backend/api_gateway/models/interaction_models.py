"""
交互数据模型
负责人：ZZH
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class InputField(BaseModel):
    """输入字段定义"""
    key: str = Field(..., description="字段key，格式：subgraph_id.param_name")
    label: str = Field(..., description="字段标签，显示给用户")
    component: str = Field(..., description="组件类型: number/text/select/date")
    required: bool = Field(True, description="是否必填")
    default: Optional[Any] = Field(None, description="默认值")
    min: Optional[float] = Field(None, description="最小值（number类型）")
    max: Optional[float] = Field(None, description="最大值（number类型）")
    options: Optional[List[str]] = Field(None, description="选项列表（select类型）")
    placeholder: Optional[str] = Field(None, description="占位符")
    help_text: Optional[str] = Field(None, description="帮助文本")
    
    class Config:
        json_schema_extra = {
            "example": {
                "key": "UP01.thickness_mm",
                "label": "UP01 - 厚度(mm)",
                "component": "number",
                "required": True,
                "default": 10,
                "min": 1,
                "max": 500,
                "placeholder": "请输入厚度",
                "help_text": "单位：毫米(mm)"
            }
        }

class InteractionCard(BaseModel):
    """交互卡片"""
    card_id: str = Field(..., description="卡片唯一ID")
    card_type: str = Field(..., description="卡片类型: missing_input/choice/review")
    title: str = Field(..., description="卡片标题")
    message: str = Field(..., description="卡片消息")
    severity: str = Field("error", description="严重程度: error/warning/info")
    fields: List[InputField] = Field(..., description="输入字段列表")
    subgraphs: List[str] = Field(..., description="相关子图ID列表")
    buttons: List[str] = Field(
        default=["submit", "re_recognize"],
        description="按钮列表"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "card_id": "card-uuid-123",
                "card_type": "missing_input",
                "title": "缺少必要参数",
                "message": "以下2个子图缺少必要参数，请补充：",
                "severity": "error",
                "fields": [
                    {
                        "key": "UP01.thickness_mm",
                        "label": "UP01 - 厚度(mm)",
                        "component": "number",
                        "required": True,
                        "default": 10
                    }
                ],
                "subgraphs": ["UP01", "UP02"],
                "buttons": ["submit", "re_recognize"]
            }
        }

class UserResponse(BaseModel):
    """用户响应"""
    card_id: str = Field(..., description="卡片ID")
    action: str = Field(..., description="用户操作: submit/re_recognize/skip")
    inputs: Dict[str, Any] = Field(default={}, description="用户输入的参数")
    comment: Optional[str] = Field(None, description="用户备注")
    
    class Config:
        json_schema_extra = {
            "example": {
                "card_id": "card-uuid-123",
                "action": "submit",
                "inputs": {
                    "UP01.thickness_mm": 10,
                    "UP02.thickness_mm": 15
                },
                "comment": "已确认参数"
            }
        }

class InteractionRecord(BaseModel):
    """交互记录（数据库模型）"""
    interaction_id: str
    job_id: str
    card_id: str
    card_type: str
    card_data: dict
    user_response: Optional[dict] = None
    action: Optional[str] = None
    status: str  # pending/responded/expired
    created_at: datetime
    responded_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
