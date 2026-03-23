from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

try:
    import jwt

    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False


logger = logging.getLogger(__name__)
security = HTTPBearer()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    if not JWT_AVAILABLE:
        logger.error("PyJWT 未安装，无法创建 token")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT 服务不可用",
        )

    to_encode = data.copy()
    expire = now_utc() + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    if "sub" not in to_encode and "username" in to_encode:
        to_encode["sub"] = to_encode["username"]

    to_encode.update(
        {
            "exp": expire,
            "iat": now_utc(),
        }
    )

    try:
        return jwt.encode(
            to_encode,
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
    except Exception as exc:
        logger.error("创建 JWT token 失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token 创建失败",
        ) from exc


def verify_token(token: str) -> dict:
    if not JWT_AVAILABLE:
        logger.error("PyJWT 未安装，无法校验 token")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT 服务不可用",
        )

    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            leeway=60,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
            },
        )
    except jwt.ExpiredSignatureError as exc:
        logger.warning("JWT token 已过期")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 已过期",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        logger.warning("JWT token 无效: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 Token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except Exception as exc:
        logger.error("JWT 校验失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 校验失败",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    payload = verify_token(credentials.credentials)
    user_id = payload.get("user_id")
    username = payload.get("sub") or payload.get("username")

    if not user_id:
        logger.warning("JWT token 缺少 user_id")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 缺少用户信息",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "user_id": user_id,
        "username": username,
        "role": payload.get("role"),
        "email": payload.get("email"),
        "real_name": payload.get("real_name"),
        "_payload": payload,
    }


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict | None:
    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None


async def get_current_user_dev(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    if not settings.DEBUG:
        return await get_current_user(credentials)

    logger.warning("DEBUG 模式启用开发用户兜底")
    return {
        "user_id": "dev_user_001",
        "username": "dev_user",
        "role": "admin",
        "email": "dev@example.com",
        "real_name": "开发用户",
    }
