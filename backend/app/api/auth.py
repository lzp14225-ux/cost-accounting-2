import bcrypt
import jwt
from datetime import datetime, timedelta
from typing import Optional
import logging
from database import db_manager
from shared.config import settings

# JWT配置
SECRET_KEY = settings.JWT_SECRET_KEY
ALGORITHM = settings.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES

class AuthService:
    def __init__(self):
        self.max_failed_attempts = 5  # 最大失败尝试次数
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        try:
            return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
        except Exception as e:
            logging.error(f"密码验证错误: {e}")
            return False
    
    def create_access_token(self, data: dict) -> str:
        """创建JWT访问令牌"""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    
    def get_user_by_username(self, username: str) -> Optional[dict]:
        """根据用户名获取用户信息"""
        query = """
        SELECT user_id, username, password_hash, email, real_name, role, 
               department, is_active, is_locked, failed_login_attempts,
               last_login_at, created_at
        FROM users 
        WHERE username = %s
        """
        return db_manager.execute_query(query, (username,), fetch_one=True)
    
    def update_login_info(self, user_id: str, client_ip: str, success: bool = True):
        """更新登录信息"""
        if success:
            # 登录成功，重置失败次数，更新最后登录时间和IP
            query = """
            UPDATE users 
            SET last_login_at = %s, last_login_ip = %s, 
                failed_login_attempts = 0, is_locked = false,
                updated_at = %s
            WHERE user_id = %s
            """
            params = (datetime.now(), client_ip, datetime.now(), user_id)
        else:
            # 登录失败，增加失败次数
            query = """
            UPDATE users 
            SET failed_login_attempts = failed_login_attempts + 1,
                is_locked = CASE 
                    WHEN failed_login_attempts + 1 >= %s THEN true 
                    ELSE is_locked 
                END,
                updated_at = %s
            WHERE user_id = %s
            """
            params = (self.max_failed_attempts, datetime.now(), user_id)
        
        db_manager.execute_query(query, params)
    
    def authenticate_user(self, username: str, password: str, client_ip: str) -> tuple[bool, str, Optional[dict]]:
        """用户认证"""
        try:
            # 获取用户信息
            user = self.get_user_by_username(username)
            if not user:
                return False, "用户名或密码错误", None
            
            # 检查账号状态
            if not user['is_active']:
                return False, "账号已被禁用", None
            
            if user['is_locked']:
                return False, "账号已被锁定，请联系管理员", None
            
            # 验证密码
            if not self.verify_password(password, user['password_hash']):
                # 更新失败登录信息
                self.update_login_info(str(user['user_id']), client_ip, success=False)
                
                # 检查是否需要锁定账号
                failed_attempts = user['failed_login_attempts'] + 1
                if failed_attempts >= self.max_failed_attempts:
                    return False, f"密码错误次数过多，账号已被锁定", None
                else:
                    return False, f"用户名或密码错误，还有{self.max_failed_attempts - failed_attempts}次机会", None
            
            # 登录成功，更新登录信息
            self.update_login_info(str(user['user_id']), client_ip, success=True)
            
            # 准备用户信息（移除敏感信息）
            user_info = {
                'user_id': str(user['user_id']),
                'username': user['username'],
                'email': user['email'],
                'real_name': user['real_name'],
                'role': user['role'],
                'department': user['department'],
                'is_active': user['is_active'],
                'last_login_at': user['last_login_at'].isoformat() if user['last_login_at'] else None,
                'created_at': user['created_at'].isoformat() if user['created_at'] else None
            }
            
            return True, "登录成功", user_info
            
        except Exception as e:
            logging.error(f"用户认证错误: {e}")
            return False, "系统错误，请稍后重试", None

# 全局认证服务实例
auth_service = AuthService()
