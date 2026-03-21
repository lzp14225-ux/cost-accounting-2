"""
权限检查工具模块
负责人：人员A

提供基于角色的权限检查功能（RBAC）
"""
from typing import List, Optional
from functools import wraps
from fastapi import HTTPException, status

# 角色定义
class Role:
    ADMIN = "Admin"
    OPERATOR = "Operator"
    VIEWER = "Viewer"

# 角色权限映射
ROLE_PERMISSIONS = {
    Role.ADMIN: [
        "user:create",
        "user:read",
        "user:update",
        "user:delete",
        "job:create",
        "job:read",
        "job:update",
        "job:delete",
        "price:create",
        "price:read",
        "price:update",
        "price:delete",
        "rule:create",
        "rule:read",
        "rule:update",
        "rule:delete",
        "recalc:execute",
        "report:generate",
        "system:config"
    ],
    Role.OPERATOR: [
        "job:create",
        "job:read",
        "job:update",
        "price:read",
        "rule:read",
        "recalc:execute",
        "report:generate"
    ],
    Role.VIEWER: [
        "job:read",
        "price:read",
        "rule:read",
        "report:read"
    ]
}


def has_permission(role: str, permission: str) -> bool:
    """
    检查角色是否有指定权限
    
    Args:
        role: 用户角色
        permission: 权限标识（如 "job:create"）
        
    Returns:
        是否有权限
    """
    if role not in ROLE_PERMISSIONS:
        return False
    return permission in ROLE_PERMISSIONS[role]


def has_any_permission(role: str, permissions: List[str]) -> bool:
    """
    检查角色是否有任意一个指定权限
    
    Args:
        role: 用户角色
        permissions: 权限标识列表
        
    Returns:
        是否有任意一个权限
    """
    if role not in ROLE_PERMISSIONS:
        return False
    return any(perm in ROLE_PERMISSIONS[role] for perm in permissions)


def has_all_permissions(role: str, permissions: List[str]) -> bool:
    """
    检查角色是否有所有指定权限
    
    Args:
        role: 用户角色
        permissions: 权限标识列表
        
    Returns:
        是否有所有权限
    """
    if role not in ROLE_PERMISSIONS:
        return False
    return all(perm in ROLE_PERMISSIONS[role] for perm in permissions)


def require_permission(permission: str):
    """
    权限检查装饰器（用于普通函数）
    
    Args:
        permission: 需要的权限标识
        
    Raises:
        HTTPException: 如果没有权限
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 从kwargs中获取current_user
            current_user = kwargs.get("current_user")
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="未认证"
                )
            
            user_role = current_user.get("role")
            if not has_permission(user_role, permission):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"没有权限: {permission}"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_any_permission(permissions: List[str]):
    """
    权限检查装饰器（需要任意一个权限）
    
    Args:
        permissions: 权限标识列表
        
    Raises:
        HTTPException: 如果没有任何一个权限
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_user = kwargs.get("current_user")
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="未认证"
                )
            
            user_role = current_user.get("role")
            if not has_any_permission(user_role, permissions):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"没有权限: {', '.join(permissions)}"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_role(role: str):
    """
    角色检查装饰器
    
    Args:
        role: 需要的角色
        
    Raises:
        HTTPException: 如果角色不匹配
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_user = kwargs.get("current_user")
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="未认证"
                )
            
            user_role = current_user.get("role")
            if user_role != role:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"需要{role}角色"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_any_role(roles: List[str]):
    """
    角色检查装饰器（需要任意一个角色）
    
    Args:
        roles: 角色列表
        
    Raises:
        HTTPException: 如果角色不匹配
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_user = kwargs.get("current_user")
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="未认证"
                )
            
            user_role = current_user.get("role")
            if user_role not in roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"需要以下角色之一: {', '.join(roles)}"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def check_resource_owner(user_id: str, resource_user_id: str) -> bool:
    """
    检查用户是否是资源的所有者
    
    Args:
        user_id: 当前用户ID
        resource_user_id: 资源所有者ID
        
    Returns:
        是否是所有者
    """
    return user_id == resource_user_id


def can_access_resource(current_user: dict, resource_user_id: str) -> bool:
    """
    检查用户是否可以访问资源
    
    规则：
    - Admin可以访问所有资源
    - Operator和Viewer只能访问自己的资源
    
    Args:
        current_user: 当前用户信息
        resource_user_id: 资源所有者ID
        
    Returns:
        是否可以访问
    """
    user_role = current_user.get("role")
    user_id = current_user.get("user_id")
    
    # Admin可以访问所有资源
    if user_role == Role.ADMIN:
        return True
    
    # 其他角色只能访问自己的资源
    return check_resource_owner(user_id, resource_user_id)


def can_modify_resource(current_user: dict, resource_user_id: str) -> bool:
    """
    检查用户是否可以修改资源
    
    规则：
    - Admin可以修改所有资源
    - Operator只能修改自己的资源
    - Viewer不能修改任何资源
    
    Args:
        current_user: 当前用户信息
        resource_user_id: 资源所有者ID
        
    Returns:
        是否可以修改
    """
    user_role = current_user.get("role")
    user_id = current_user.get("user_id")
    
    # Viewer不能修改任何资源
    if user_role == Role.VIEWER:
        return False
    
    # Admin可以修改所有资源
    if user_role == Role.ADMIN:
        return True
    
    # Operator只能修改自己的资源
    return check_resource_owner(user_id, resource_user_id)


def filter_by_permission(current_user: dict, query):
    """
    根据权限过滤查询结果
    
    规则：
    - Admin可以查看所有数据
    - Operator和Viewer只能查看自己的数据
    
    Args:
        current_user: 当前用户信息
        query: SQLAlchemy查询对象
        
    Returns:
        过滤后的查询对象
    """
    user_role = current_user.get("role")
    user_id = current_user.get("user_id")
    
    # Admin可以查看所有数据
    if user_role == Role.ADMIN:
        return query
    
    # 其他角色只能查看自己的数据
    return query.filter_by(user_id=user_id)
