"""
安全工具模块
负责人：人员A

提供密码加密、Token生成、Token验证等安全相关功能
基于JWT_GUIDE.md标准实现
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from passlib.context import CryptContext
import os
import logging
from shared.timezone_utils import now_shanghai
from shared.config import settings

# 使用标准的jwt库（PyJWT）
try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    logging.warning("PyJWT库未安装，JWT功能不可用")

logger = logging.getLogger(__name__)

# 密码加密上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT配置
SECRET_KEY = settings.JWT_SECRET_KEY
ALGORITHM = settings.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = 7  # 7天


def hash_password(password: str) -> str:
    """
    使用bcrypt加密密码
    
    Args:
        password: 明文密码
        
    Returns:
        加密后的密码哈希
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码是否正确
    
    Args:
        plain_password: 明文密码
        hashed_password: 加密后的密码哈希
        
    Returns:
        密码是否匹配
    """
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    创建访问Token (Access Token)
    
    按照JWT_GUIDE.md标准实现：
    - 添加 exp (过期时间)
    - 添加 iat (签发时间)
    - 添加 sub (主题/用户名)
    
    Args:
        data: 要编码到Token中的数据，应包含：
            - sub: 用户名（必需）
            - user_id: 用户ID
            - role: 用户角色
            - email: 用户邮箱
            - real_name: 真实姓名
        expires_delta: Token过期时间，默认30分钟
        
    Returns:
        JWT Token字符串
        
    Example:
        >>> token = create_access_token({
        ...     "sub": "admin",
        ...     "user_id": "123",
        ...     "role": "admin",
        ...     "email": "admin@example.com",
        ...     "real_name": "管理员"
        ... })
    """
    if not JWT_AVAILABLE:
        logger.error("JWT库未安装，无法生成token")
        return None
    
    try:
        to_encode = data.copy()
        
        # 计算过期时间（Asia/Shanghai）
        if expires_delta:
            expire = now_shanghai() + expires_delta
        else:
            expire = now_shanghai() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        # 添加标准JWT声明
        to_encode.update({
            "exp": expire,                    # 过期时间
            "iat": now_shanghai(),           # 签发时间
            "type": "access"                  # Token类型
        })
        
        # 确保有sub字段（JWT标准）
        if "sub" not in to_encode and "username" in to_encode:
            to_encode["sub"] = to_encode["username"]
        
        # 编码JWT
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        
        logger.debug(f"✅ Access token已生成: sub={to_encode.get('sub')}")
        return encoded_jwt
    
    except Exception as e:
        logger.error(f"❌ JWT token生成失败: {e}")
        return None


def create_refresh_token(data: Dict[str, Any]) -> str:
    """
    创建刷新Token (Refresh Token)
    
    Args:
        data: 要编码到Token中的数据（通常只包含user_id和sub）
        
    Returns:
        JWT Token字符串
    """
    if not JWT_AVAILABLE:
        logger.error("JWT库未安装，无法生成token")
        return None
    
    try:
        to_encode = data.copy()
        expire = now_shanghai() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        
        to_encode.update({
            "exp": expire,
            "iat": now_shanghai(),
            "type": "refresh"
        })
        
        # 确保有sub字段
        if "sub" not in to_encode and "username" in to_encode:
            to_encode["sub"] = to_encode["username"]
        
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        
        logger.debug(f"✅ Refresh token已生成: sub={to_encode.get('sub')}")
        return encoded_jwt
    
    except Exception as e:
        logger.error(f"❌ Refresh token生成失败: {e}")
        return None


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """
    解码并验证Token
    
    Args:
        token: JWT Token字符串
        
    Returns:
        Token中的数据，如果Token无效则返回None
    """
    if not JWT_AVAILABLE:
        logger.error("JWT库未安装，无法验证token")
        return None
    
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
            }
        )
        return payload
    
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token已过期")
        return None
    
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT token无效: {e}")
        return None
    
    except Exception as e:
        logger.error(f"JWT验证异常: {e}")
        return None


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    验证访问Token
    
    Args:
        token: JWT Token字符串
        
    Returns:
        Token中的数据，如果Token无效或类型不对则返回None
    """
    payload = decode_token(token)
    if payload and payload.get("type") == "access":
        return payload
    return None


def verify_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    """
    验证刷新Token
    
    Args:
        token: JWT Token字符串
        
    Returns:
        Token中的数据，如果Token无效或类型不对则返回None
    """
    payload = decode_token(token)
    if payload and payload.get("type") == "refresh":
        return payload
    return None


def generate_token_pair(user_id: str, username: str, role: str, 
                       email: str = None, real_name: str = None) -> Dict[str, str]:
    """
    生成访问Token和刷新Token对
    
    Args:
        user_id: 用户ID
        username: 用户名
        role: 用户角色
        email: 用户邮箱（可选）
        real_name: 真实姓名（可选）
        
    Returns:
        包含access_token和refresh_token的字典
        
    Example:
        >>> tokens = generate_token_pair(
        ...     user_id="123",
        ...     username="admin",
        ...     role="admin",
        ...     email="admin@example.com",
        ...     real_name="管理员"
        ... )
        >>> print(tokens["access_token"])
    """
    # 构建token数据
    token_data = {
        "sub": username,
        "user_id": user_id,
        "role": role
    }
    
    if email:
        token_data["email"] = email
    if real_name:
        token_data["real_name"] = real_name
    
    # 生成token对
    access_token = create_access_token(data=token_data)
    refresh_token = create_refresh_token(data={
        "sub": username,
        "user_id": user_id
    })
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60  # 秒
    }


def extract_user_from_token(token: str) -> Optional[Dict[str, Any]]:
    """
    从Token中提取用户信息
    
    Args:
        token: JWT Token字符串
        
    Returns:
        用户信息字典，包含user_id, username, role, email, real_name
    """
    payload = verify_access_token(token)
    if payload:
        return {
            "user_id": payload.get("user_id"),
            "username": payload.get("sub") or payload.get("username"),
            "role": payload.get("role"),
            "email": payload.get("email"),
            "real_name": payload.get("real_name")
        }
    return None
