"""
Pydantic数据模型
负责人：人员A

定义API请求和响应的数据结构
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal


# ==================== 用户相关 ====================

class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: Optional[str] = Field(None, max_length=100)
    role: str = Field(default="Operator")
    department: Optional[str] = Field(None, max_length=100)

class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=50)

class UserUpdate(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    is_active: Optional[bool] = None

class UserResponse(UserBase):
    user_id: str
    is_active: bool
    last_login_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True


# ==================== 认证相关 ====================

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ==================== 任务相关 ====================

class JobCreate(BaseModel):
    dwg_file_id: Optional[str] = None
    dwg_file_name: Optional[str] = None
    prt_file_id: Optional[str] = None
    prt_file_name: Optional[str] = None

class JobResponse(BaseModel):
    job_id: str
    user_id: str
    dwg_file_name: Optional[str]
    prt_file_name: Optional[str]
    status: str
    current_stage: Optional[str]
    progress: int
    total_subgraphs: int
    total_cost: Optional[Decimal]
    currency: str
    created_at: datetime
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True

class JobListResponse(BaseModel):
    total: int
    items: List[JobResponse]


# ==================== 子图相关 ====================

class SubgraphResponse(BaseModel):
    subgraph_id: str
    job_id: str
    part_name: Optional[str]
    part_code: Optional[str]
    material: Optional[str]
    weight_kg: Optional[Decimal]
    total_cost: Optional[Decimal]
    status: str
    
    class Config:
        from_attributes = True

class SubgraphDetailResponse(SubgraphResponse):
    # 加工时间
    nc_z_time: Optional[Decimal]
    nc_b_time: Optional[Decimal]
    nc_c_time: Optional[Decimal]
    nc_c_b_time: Optional[Decimal]
    
    # 线割长度
    slow_wire_length: Optional[Decimal]
    mid_wire_length: Optional[Decimal]
    fast_wire_length: Optional[Decimal]
    
    # 费用明细
    nc_z_fee: Optional[Decimal]
    nc_b_fee: Optional[Decimal]
    nc_c_fee: Optional[Decimal]
    nc_c_b_fee: Optional[Decimal]
    slow_wire_cost: Optional[Decimal]
    mid_wire_cost: Optional[Decimal]
    fast_wire_cost: Optional[Decimal]
    processing_cost_total: Optional[Decimal]
    
    # NC视图时间和费用
    nc_z_view_time: Optional[Decimal]
    nc_b_view_time: Optional[Decimal]
    nc_z_view_fee: Optional[Decimal]
    nc_b_view_fee: Optional[Decimal]
    
    # 小磨数量
    small_grinding_count: Optional[int]


# ==================== 特征相关 ====================

class FeatureResponse(BaseModel):
    feature_id: int
    subgraph_id: str
    job_id: str
    version: int
    length_mm: Optional[Decimal]
    width_mm: Optional[Decimal]
    thickness_mm: Optional[Decimal]
    quantity: int
    is_complete: bool
    missing_params: Optional[List[str]]
    
    class Config:
        from_attributes = True


# ==================== 价格相关 ====================

class PriceItemCreate(BaseModel):
    id: str
    version_id: str
    feature_type: str
    name: str
    description: Optional[str]
    unit_price: Decimal
    unit: str
    param_conditions: Optional[Dict[str, Any]]
    priority: int = 0

class PriceItemUpdate(BaseModel):
    name: Optional[str]
    description: Optional[str]
    unit_price: Optional[Decimal]
    param_conditions: Optional[Dict[str, Any]]
    priority: Optional[int]

class PriceItemResponse(BaseModel):
    id: str
    version_id: str
    feature_type: str
    name: str
    unit_price: Decimal
    unit: str
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


# ==================== 工艺规则相关 ====================

class ProcessRuleCreate(BaseModel):
    id: str
    version_id: str
    feature_type: str
    name: str
    description: Optional[str]
    conditions: Dict[str, Any]
    output_params: Dict[str, Any]
    priority: int = 0

class ProcessRuleUpdate(BaseModel):
    name: Optional[str]
    description: Optional[str]
    conditions: Optional[Dict[str, Any]]
    output_params: Optional[Dict[str, Any]]
    priority: Optional[int]

class ProcessRuleResponse(BaseModel):
    id: str
    version_id: str
    feature_type: str
    name: str
    conditions: Dict[str, Any]
    output_params: Dict[str, Any]
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


# ==================== 重算相关 ====================

class RecalculationRequest(BaseModel):
    subgraph_id: str
    reason: str
    modifications: Dict[str, Any]

class BatchRecalculationRequest(BaseModel):
    subgraph_ids: List[str]
    reason: str

class RecalculationResponse(BaseModel):
    recalc_id: str
    job_id: str
    subgraph_id: str
    status: str
    old_cost: Optional[Decimal]
    new_cost: Optional[Decimal]
    cost_diff: Optional[Decimal]
    created_at: datetime
    
    class Config:
        from_attributes = True


# ==================== 用户交互相关 ====================

class InteractionCardField(BaseModel):
    key: str
    label: str
    component: str  # number/text/select
    required: bool = False
    default: Optional[Any] = None
    options: Optional[List[Dict[str, Any]]] = None
    min: Optional[float] = None
    max: Optional[float] = None

class InteractionCardButton(BaseModel):
    key: str
    label: str
    style: str = "default"  # primary/default/danger

class InteractionCard(BaseModel):
    card_id: str
    type: str  # missing_input/choice/review
    title: str
    message: str
    severity: str  # error/warning/info
    fields: Optional[List[InteractionCardField]] = None
    buttons: List[InteractionCardButton]

class UserInteractionResponse(BaseModel):
    card_id: str
    action: str
    inputs: Dict[str, Any]


# ==================== WebSocket消息 ====================

class WebSocketMessage(BaseModel):
    job_id: str
    status: str
    stage: Optional[str]
    progress: int
    message: str
    data: Optional[Dict[str, Any]] = None
    cards: Optional[List[InteractionCard]] = None


# ==================== 报表相关 ====================

class ReportResponse(BaseModel):
    report_id: str
    job_id: str
    file_type: str
    file_size: int
    download_url: Optional[str]
    url_expires_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True


# ==================== 通用响应 ====================

class SuccessResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[Any] = None

class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[str] = None

class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    
    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size
    
    @property
    def limit(self) -> int:
        return self.page_size
