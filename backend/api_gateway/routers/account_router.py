import hashlib
from datetime import datetime
from typing import Any, Optional

import bcrypt
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api_gateway.auth import create_access_token, get_current_user, verify_token
from app.api.jobs import JobService as AccountJobService
from app.api.price_items import PriceItemService
from app.api.process_rules import ProcessRuleService
from app.services.chat_session_service import chat_session_service
from app.services.database import db_manager


router = APIRouter(tags=["account"])

process_rule_service = ProcessRuleService()
price_item_service = PriceItemService()
account_job_service = AccountJobService()


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenRequest(BaseModel):
    token: str


class ChangePasswordRequest(BaseModel):
    new_password: str = Field(min_length=6)


class RenameSessionRequest(BaseModel):
    job_id: str
    name: str


class DeleteByJobRequest(BaseModel):
    job_id: str


class BatchDeleteByJobRequest(BaseModel):
    job_ids: list[str]


class BatchIdsRequest(BaseModel):
    ids: list[str]


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _verify_password(plain_password: str, stored_hash: str) -> bool:
    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        return bcrypt.checkpw(plain_password.encode("utf-8"), stored_hash.encode("utf-8"))
    return hashlib.sha256(plain_password.encode()).hexdigest() == stored_hash


def _get_user_by_username(username: str) -> Optional[dict[str, Any]]:
    query = """
    SELECT user_id, username, password_hash, email, real_name, role,
           department, is_active, is_locked, failed_login_attempts,
           last_login_at, created_at
    FROM users
    WHERE username = %s
    """
    return db_manager.execute_query(query, (username,), fetch_one=True)


def _get_user_by_id(user_id: str) -> Optional[dict[str, Any]]:
    query = """
    SELECT user_id, username, password_hash, email, real_name, role,
           department, is_active, is_locked, failed_login_attempts,
           last_login_at, created_at
    FROM users
    WHERE user_id = %s
    """
    return db_manager.execute_query(query, (user_id,), fetch_one=True)


def _update_login_info(user_id: str, client_ip: str, success: bool) -> None:
    if success:
        query = """
        UPDATE users
        SET last_login_at = %s, last_login_ip = %s,
            failed_login_attempts = 0, is_locked = false,
            updated_at = %s
        WHERE user_id = %s
        """
        params = (datetime.now(), client_ip, datetime.now(), user_id)
    else:
        query = """
        UPDATE users
        SET failed_login_attempts = failed_login_attempts + 1,
            is_locked = CASE WHEN failed_login_attempts + 1 >= %s THEN true ELSE is_locked END,
            updated_at = %s
        WHERE user_id = %s
        """
        params = (5, datetime.now(), user_id)
    db_manager.execute_query(query, params)


def _format_user_info(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": str(user["user_id"]),
        "username": user["username"],
        "email": user.get("email"),
        "real_name": user.get("real_name"),
        "role": user.get("role"),
        "department": user.get("department"),
        "is_active": user.get("is_active"),
        "last_login_at": user["last_login_at"].isoformat() if user.get("last_login_at") else None,
        "created_at": user["created_at"].isoformat() if user.get("created_at") else None,
    }


def _authenticate_user(username: str, password: str, client_ip: str):
    user = _get_user_by_username(username)
    if not user:
        return False, "用户名或密码错误", None
    if not user.get("is_active"):
        return False, "用户已停用", None
    if user.get("is_locked"):
        return False, "用户已被锁定", None
    if not _verify_password(password, user["password_hash"]):
        _update_login_info(str(user["user_id"]), client_ip, False)
        return False, "用户名或密码错误", None

    _update_login_info(str(user["user_id"]), client_ip, True)
    return True, "登录成功", _format_user_info(user)


def _change_password(user_id: str, new_password: str):
    user = _get_user_by_id(user_id)
    if not user:
        return False, "用户不存在"
    if _verify_password(new_password, user["password_hash"]):
        return False, "新密码不能与当前密码相同"

    password_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    query = """
    UPDATE users
    SET password_hash = %s, updated_at = %s
    WHERE user_id = %s
    """
    db_manager.execute_query(query, (password_hash, datetime.now(), user_id))
    return True, "密码修改成功"


@router.options("/api/login")
async def login_options():
    return {"message": "OK"}


@router.post("/api/login")
async def login(payload: LoginRequest, request: Request):
    success, message, user_info = _authenticate_user(payload.username.strip(), payload.password, _get_client_ip(request))
    if not success:
        return {"success": False, "message": message}

    token = create_access_token(
        {
            "sub": user_info["username"],
            "user_id": user_info["user_id"],
            "role": user_info.get("role"),
            "email": user_info.get("email"),
            "real_name": user_info.get("real_name"),
        }
    )
    return {"success": True, "message": message, "token": token, "user_info": user_info}


@router.post("/api/verify-token")
async def verify_token_endpoint(payload: TokenRequest):
    try:
        token_payload = verify_token(payload.token)
        return {"success": True, "message": "token有效", "payload": token_payload}
    except HTTPException as exc:
        return {"success": False, "message": exc.detail}


@router.post("/api/user/info")
async def user_info(current_user: dict = Depends(get_current_user)):
    user = _get_user_by_id(current_user["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"success": True, "user_info": _format_user_info(user)}


@router.post("/api/change-password")
@router.post("/api/user/change-password")
async def change_password(payload: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    success, message = _change_password(current_user["user_id"], payload.new_password.strip())
    return {"success": success, "message": message}


@router.post("/api/process-rules")
async def create_process_rule(payload: dict = Body(...)):
    success, message, data = process_rule_service.create_rule(payload)
    return {"success": success, "message": message, "data": data}


@router.get("/api/process-rules/{rule_id}")
async def get_process_rule(rule_id: str):
    success, message, data = process_rule_service.get_rule_by_id(rule_id)
    return {"success": success, "message": message, "data": data}


@router.get("/api/process-rules")
async def list_process_rules(
    version_id: Optional[str] = None,
    feature_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    name: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    filters = {
        key: value
        for key, value in {
            "version_id": version_id,
            "feature_type": feature_type,
            "is_active": is_active,
            "name": name,
        }.items()
        if value is not None
    }
    success, message, data = process_rule_service.get_rules(filters=filters, page=page, page_size=page_size)
    return {"success": success, "message": message, "data": data}


@router.put("/api/process-rules/{rule_id}")
async def update_process_rule(rule_id: str, payload: dict = Body(...)):
    success, message, data = process_rule_service.update_rule(rule_id, payload)
    return {"success": success, "message": message, "data": data}


@router.put("/api/process-rules/{rule_id}/soft-delete")
@router.patch("/api/process-rules/{rule_id}/soft-delete")
async def soft_delete_process_rule(rule_id: str):
    success, message, data = process_rule_service.soft_delete_rule(rule_id)
    return {"success": success, "message": message, "data": data}


@router.post("/api/process-rules/batch-soft-delete")
async def batch_soft_delete_process_rules(payload: BatchIdsRequest):
    success, message, data = process_rule_service.batch_soft_delete_rules(payload.ids)
    return {"success": success, "message": message, "data": data}


@router.get("/api/process-rules/by-version-type")
async def get_process_rules_by_version_type(version_id: str, feature_type: str, active_only: bool = True):
    success, message, data = process_rule_service.get_rules_by_version_and_type(version_id, feature_type, active_only)
    return {"success": success, "message": message, "data": data}


@router.post("/api/price-items")
async def create_price_item(payload: dict = Body(...)):
    success, message, data = price_item_service.create_item(payload)
    return {"success": success, "message": message, "data": data}


@router.get("/api/price-items/{item_id}")
async def get_price_item(item_id: str):
    success, message, data = price_item_service.get_item_by_id(item_id)
    return {"success": success, "message": message, "data": data}


@router.get("/api/price-items")
async def list_price_items(
    version_id: Optional[str] = None,
    category: Optional[str] = None,
    sub_category: Optional[str] = None,
    is_active: Optional[bool] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    filters = {
        key: value
        for key, value in {
            "version_id": version_id,
            "category": category,
            "sub_category": sub_category,
            "is_active": is_active,
        }.items()
        if value is not None
    }
    success, message, data = price_item_service.get_items(filters=filters, page=page, page_size=page_size)
    return {"success": success, "message": message, "data": data}


@router.put("/api/price-items/{item_id}")
async def update_price_item(item_id: str, payload: dict = Body(...)):
    success, message, data = price_item_service.update_item(item_id, payload)
    return {"success": success, "message": message, "data": data}


@router.put("/api/price-items/{item_id}/soft-delete")
@router.patch("/api/price-items/{item_id}/soft-delete")
async def soft_delete_price_item(item_id: str):
    success, message, data = price_item_service.soft_delete_item(item_id)
    return {"success": success, "message": message, "data": data}


@router.post("/api/price-items/batch-soft-delete")
async def batch_soft_delete_price_items(payload: BatchIdsRequest):
    success, message, data = price_item_service.batch_soft_delete_items(payload.ids)
    return {"success": success, "message": message, "data": data}


@router.get("/api/price-items/by-version-category")
async def get_price_items_by_version_category(version_id: str, category: str, active_only: bool = True):
    success, message, data = price_item_service.get_items_by_version_and_category(version_id, category, active_only)
    return {"success": success, "message": message, "data": data}


@router.get("/api/chat-sessions/")
async def list_chat_sessions(
    limit: int = Query(5, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    sessions, total = chat_session_service.get_user_sessions(
        user_id=current_user["user_id"],
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "success": True,
        "data": {"sessions": [session.to_dict() for session in sessions], "total": total},
    }


@router.put("/api/chat-sessions/update-name")
async def rename_chat_session(payload: RenameSessionRequest, current_user: dict = Depends(get_current_user)):
    success, message, session = chat_session_service.update_session_name_by_job_id(
        job_id=payload.job_id,
        name=payload.name,
        user_id=current_user["user_id"],
    )
    return {"success": success, "message": message, "data": session.to_dict() if session else None}


@router.delete("/api/chat-sessions/delete-by-job")
async def delete_chat_session_by_job(payload: DeleteByJobRequest, current_user: dict = Depends(get_current_user)):
    success, message = chat_session_service.delete_session_by_job_id(
        job_id=payload.job_id,
        user_id=current_user["user_id"],
    )
    return {"success": success, "message": message}


@router.post("/api/chat-sessions/batch-delete-by-job")
async def batch_delete_chat_sessions(payload: BatchDeleteByJobRequest, current_user: dict = Depends(get_current_user)):
    result = chat_session_service.delete_sessions_by_job_ids_batch(
        job_ids=payload.job_ids,
        user_id=current_user["user_id"],
    )
    return {"success": True, "message": "批量删除执行完成", "data": result}


@router.get("/api/chat-sessions/{session_id}")
async def get_chat_session(session_id: str, current_user: dict = Depends(get_current_user)):
    session = chat_session_service.get_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if str(session.user_id) != str(current_user["user_id"]):
        raise HTTPException(status_code=403, detail="无权限访问该会话")
    return {"success": True, "data": session.to_dict()}


@router.get("/api/jobs/{job_id}")
async def get_account_job(job_id: str, current_user: dict = Depends(get_current_user)):
    success, message, data = account_job_service.get_job_by_id(job_id)
    return {"success": success, "message": message, "data": data}
