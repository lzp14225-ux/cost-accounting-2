from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
import uuid

class LoginRequest(BaseModel):
    """登录请求模型"""
    username: str
    password: str

class LoginResponse(BaseModel):
    """登录响应模型"""
    success: bool
    message: str
    token: Optional[str] = None
    user_info: Optional[dict] = None

class UserInfo(BaseModel):
    """用户信息模型"""
    user_id: str
    username: str
    email: Optional[str] = None
    real_name: Optional[str] = None
    role: str
    department: Optional[str] = None
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime