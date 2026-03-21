"""
BaseAgent基类
负责人：人员A
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime
import logging
from shared.timezone_utils import now_shanghai

logger = logging.getLogger(__name__)

class OpResult:
    """Agent操作结果"""
    def __init__(
        self,
        status: str,  # ok/warning/error
        data: Optional[Dict[str, Any]] = None,
        message: str = "",
        refs: Optional[Dict[str, Any]] = None
    ):
        self.status = status
        self.data = data or {}
        self.message = message
        self.refs = refs or {}
        self.timestamp = now_shanghai()

class BaseAgent(ABC):
    """Agent基类"""
    
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"agent.{name}")
    
    @abstractmethod
    async def process(self, context: Dict[str, Any]) -> OpResult:
        """
        处理任务
        Args:
            context: 执行上下文
        Returns:
            OpResult: 操作结果
        """
        pass
    
    async def validate_input(self, context: Dict[str, Any]) -> bool:
        """验证输入参数"""
        return True
    
    def log_operation(self, action: str, input_data: Any, output_data: Any):
        """记录操作日志"""
        self.logger.info(f"Action: {action}, Input: {input_data}, Output: {output_data}")
