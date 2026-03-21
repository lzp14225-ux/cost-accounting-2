#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聊天会话数据模型
"""

from datetime import datetime
from typing import Optional, Dict, Any


class ChatSession:
    """聊天会话模型"""
    
    def __init__(
        self,
        session_id: str,
        job_id: str,
        user_id: str,
        name: Optional[str] = None,
        status: str = 'active',
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None
    ):
        self.session_id = session_id
        self.job_id = job_id
        self.user_id = user_id
        self.name = name
        self.status = status
        self.metadata = metadata or {}
        self.created_at = created_at
        self.updated_at = updated_at
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'session_id': self.session_id,
            'job_id': self.job_id,
            'user_id': self.user_id,
            'name': self.name,
            'status': self.status,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChatSession':
        """从字典创建实例"""
        return cls(
            session_id=data.get('session_id'),
            job_id=data.get('job_id'),
            user_id=data.get('user_id'),
            name=data.get('name'),
            status=data.get('status', 'active'),
            metadata=data.get('metadata'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at')
        )
