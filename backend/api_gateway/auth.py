"""
认证鉴权模块
负责人：ZZH

基于JWT_GUIDE.md标准实现
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timedelta
import logging
from shared.timezone_utils import now_shanghai

# 使用标准的jwt库（PyJWT）
try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    logging.warning("PyJWT库未安装，JWT功能不可用")

from .config import settings

logger = logging.getLogger(__name__)

security = HTTPBearer()


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    """
    创建JWT访问令牌
    
    按照JWT_GUIDE.md标准实现：
    - 添加 exp (过期时间)
    - 添加 iat (签发时间)
    - 添加 sub (主题/用户名)
    
    Args:
        data: 要编码的数据，应包含：
            - sub: 用户名（必需）
            - user_id: 用户ID
            - role: 用户角色
            - email: 用户邮箱
            - real_name: 真实姓名
        expires_delta: 过期时间增量
    
    Returns:
        JWT token字符串
    
    Example:
        >>> token = create_access_token({
        ...     "sub": "admin",
        ...     "user_id": "123",
        ...     "role": "admin",
        ...     "email": "admin@example.com"
        ... })
    """
    if not JWT_AVAILABLE:
        logger.error("JWT库未安装，无法生成token")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT功能不可用"
        )
    
    try:
        to_encode = data.copy()
        
        # 计算过期时间
        if expires_delta:
            expire = now_shanghai() + expires_delta
        else:
            expire = now_shanghai() + timedelta(
                minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
            )
        
        # 添加标准JWT声明
        to_encode.update({
            "exp": expire,                    # 过期时间
            "iat": now_shanghai(),           # 签发时间
        })
        
        # 确保有sub字段（JWT标准）
        if "sub" not in to_encode and "username" in to_encode:
            to_encode["sub"] = to_encode["username"]
        
        # 编码JWT
        encoded_jwt = jwt.encode(
            to_encode,
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM
        )
        
        logger.debug(f"✅ JWT token已生成: sub={to_encode.get('sub')}")
        return encoded_jwt
    
    except Exception as e:
        logger.error(f"❌ JWT token生成失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token生成失败"
        )


def verify_token(token: str) -> dict:
    """
    验证JWT令牌
    
    Args:
        token: JWT token字符串
    
    Returns:
        解码后的payload字典
    
    Raises:
        HTTPException: token无效或过期时抛出401错误
    """
    if not JWT_AVAILABLE:
        logger.error("JWT库未安装，无法验证token")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT功能不可用"
        )
    
    try:
        # 解码并验证JWT
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
            }
        )
        
        logger.debug(f"✅ JWT token验证成功: sub={payload.get('sub')}")
        return payload
    
    except jwt.ExpiredSignatureError:
        logger.warning("❌ JWT token已过期")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    except jwt.InvalidTokenError as e:
        logger.warning(f"❌ JWT token无效: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    except Exception as e:
        logger.error(f"❌ JWT验证异常: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token验证失败",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    验证JWT Token并获取当前用户
    
    从Authorization Header中提取Bearer token并验证
    
    Args:
        credentials: HTTP Bearer认证凭证
    
    Returns:
        用户信息字典，包含：
        - user_id: 用户ID
        - username: 用户名（从sub字段）
        - role: 用户角色
        - email: 用户邮箱
        - real_name: 真实姓名
    
    Raises:
        HTTPException: 认证失败时抛出401错误
    
    Example:
        >>> @app.get("/protected")
        >>> async def protected_route(user: dict = Depends(get_current_user)):
        ...     return {"user_id": user["user_id"]}
    """
    token = credentials.credentials
    
    # 验证token
    payload = verify_token(token)
    
    # 提取用户信息
    user_id = payload.get("user_id")
    username = payload.get("sub") or payload.get("username")
    
    if not user_id:
        logger.warning("JWT token中缺少user_id")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token中缺少用户信息",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    logger.debug(f"✅ 用户认证成功: user_id={user_id}, username={username}")
    
    return {
        "user_id": user_id,
        "username": username,
        "role": payload.get("role"),
        "email": payload.get("email"),
        "real_name": payload.get("real_name"),
        # 保留原始payload供需要时使用
        "_payload": payload
    }


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict | None:
    """
    可选的用户认证（不强制要求token）
    
    如果提供了有效token则返回用户信息，否则返回None
    
    Args:
        credentials: HTTP Bearer认证凭证
    
    Returns:
        用户信息字典或None
    """
    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None


# 开发环境的模拟认证（仅用于测试）
async def get_current_user_dev(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    开发环境的模拟认证（不验证JWT）
    
    ⚠️ 仅用于开发测试，生产环境禁用
    
    Args:
        credentials: HTTP Bearer认证凭证
    
    Returns:
        模拟的用户信息
    """
    if not settings.DEBUG:
        # 生产环境：使用真实认证
        return await get_current_user(credentials)
    
    # 开发环境：返回模拟用户
    logger.warning("⚠️ 使用开发模式认证（不验证JWT）")
    return {
        "user_id": "dev_user_001",
        "username": "dev_user",
        "role": "admin",
        "email": "dev@example.com",
        "real_name": "开发用户"
    }

