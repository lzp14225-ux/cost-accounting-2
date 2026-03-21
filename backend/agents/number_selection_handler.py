"""
Number Selection Handler - 数字选择处理器
负责人：人员B2

职责：
处理用户通过数字选择澄清选项（如输入"1"选择第一个选项）
"""
import logging
import re
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class NumberSelectionHandler:
    """数字选择处理器"""
    
    def __init__(self):
        pass
    
    def is_number_selection(self, user_input: str) -> bool:
        """
        检测用户输入是否是数字选择
        
        Args:
            user_input: 用户输入
        
        Returns:
            是否是数字选择
        """
        # 去除空格
        user_input = user_input.strip()
        
        # 检查是否是纯数字（1-9）
        if re.match(r'^[1-9]$', user_input):
            return True
        
        # 检查是否是"第X个"、"选X"等格式
        if re.match(r'^(第)?[1-9](个)?$', user_input):
            return True
        
        if re.match(r'^选[1-9]$', user_input):
            return True
        
        return False
    
    def extract_selection_number(self, user_input: str) -> Optional[int]:
        """
        从用户输入中提取选择的数字
        
        Args:
            user_input: 用户输入
        
        Returns:
            选择的数字（1-based），如果无法提取返回 None
        """
        user_input = user_input.strip()
        
        # 纯数字
        match = re.match(r'^([1-9])$', user_input)
        if match:
            return int(match.group(1))
        
        # "第X个"
        match = re.match(r'^第?([1-9])个?$', user_input)
        if match:
            return int(match.group(1))
        
        # "选X"
        match = re.match(r'^选([1-9])$', user_input)
        if match:
            return int(match.group(1))
        
        return None
    
    async def find_recent_clarification(
        self,
        session_id: str,
        db
    ) -> Optional[Dict[str, Any]]:
        """
        从聊天历史中查找最近的澄清消息
        
        Args:
            session_id: 会话ID
            db: 数据库会话
        
        Returns:
            澄清消息数据，如果未找到返回 None
            {
                "message_id": "uuid",
                "content": "检测到您想修改...",
                "metadata": {
                    "action": "clarification_request",
                    "clarification_id": "uuid",
                    "confidence_score": 0.65
                },
                "parsed_entities": {...}
            }
        """
        logger.info(f"🔍 查找最近的澄清消息: session_id={session_id}")
        
        try:
            from api_gateway.repositories.chat_repository import ChatRepository
            
            chat_repo = ChatRepository()
            
            # 获取最近10条消息
            messages = await chat_repo.get_session_messages(
                db=db,
                session_id=session_id,
                limit=10
            )
            
            # 查找最近的澄清消息（role=assistant, action=clarification_request）
            for msg in reversed(messages):  # 从最新的开始找
                metadata = msg.metadata or {}
                
                if (msg.role == "assistant" and 
                    metadata.get("action") == "clarification_request"):
                    
                    clarification_id = metadata.get("clarification_id")
                    
                    if clarification_id:
                        logger.info(f"✅ 找到澄清消息: clarification_id={clarification_id}")
                        
                        # 从 Redis 获取完整的澄清状态
                        from agents.clarification_state import get_state_manager
                        
                        state_manager = get_state_manager()
                        clarification_state = await state_manager.get_clarification_state(
                            clarification_id
                        )
                        
                        if clarification_state:
                            return {
                                "message_id": msg.message_id,
                                "content": msg.content,
                                "metadata": metadata,
                                "clarification_id": clarification_id,
                                "parsed_entities": clarification_state.get("parsed_entities", {}),
                                "job_id": clarification_state.get("job_id"),
                                "session_id": clarification_state.get("session_id")
                            }
                        else:
                            logger.warning(f"⚠️  澄清状态已过期: clarification_id={clarification_id}")
            
            logger.info(f"❌ 未找到有效的澄清消息")
            return None
        
        except Exception as e:
            logger.error(f"❌ 查找澄清消息失败: {e}", exc_info=True)
            return None
    
    def map_number_to_option(
        self,
        selection_number: int,
        parsed_entities: Dict[str, Any]
    ) -> Optional[str]:
        """
        将数字映射到对应的选项值
        
        Args:
            selection_number: 选择的数字（1-based）
            parsed_entities: 解析的实体（包含 _suggestions）
        
        Returns:
            选项值，如果无效返回 None
        """
        suggestions = parsed_entities.get("_suggestions", [])
        
        if not suggestions:
            logger.warning(f"⚠️  没有可选项")
            return None
        
        # 检查索引是否有效
        if selection_number < 1 or selection_number > len(suggestions):
            logger.warning(f"⚠️  无效的选择: {selection_number}, 可选范围: 1-{len(suggestions)}")
            return None
        
        # 获取对应的选项（1-based 转 0-based）
        selected_value = suggestions[selection_number - 1]
        
        logger.info(f"✅ 映射成功: {selection_number} → {selected_value}")
        
        return selected_value
    
    def generate_standardized_input(
        self,
        parsed_entities: Dict[str, Any],
        selected_value: str
    ) -> str:
        """
        生成标准化输入
        
        Args:
            parsed_entities: 解析的实体
            selected_value: 选择的值
        
        Returns:
            标准化输入文本
        """
        part_code = parsed_entities.get("part_code", "")
        field = parsed_entities.get("field", "")
        
        # 根据字段类型生成合适的格式
        if field == "process_code":
            # 工艺代码：使用"用"
            standardized = f"{part_code}用{selected_value}"
        elif field == "material":
            # 材质：使用"改成"
            standardized = f"{part_code}材质改成{selected_value}"
        elif field in ["length_mm", "width_mm", "thickness_mm"]:
            # 尺寸：使用"改成"
            field_mapping = {
                "length_mm": "长度",
                "width_mm": "宽度",
                "thickness_mm": "厚度"
            }
            field_cn = field_mapping.get(field, field)
            standardized = f"{part_code}的{field_cn}改成{selected_value}"
        else:
            # 其他字段：使用通用格式
            standardized = f"{part_code}的{field}改成{selected_value}"
        
        logger.info(f"✅ 生成标准化输入: {standardized}")
        
        return standardized
    
    async def handle_number_selection(
        self,
        user_input: str,
        session_id: str,
        db
    ) -> Optional[Dict[str, Any]]:
        """
        处理数字选择
        
        完整流程：
        1. 检测是否是数字选择
        2. 提取选择的数字
        3. 查找最近的澄清消息
        4. 映射数字到选项值
        5. 生成标准化输入
        
        Args:
            user_input: 用户输入
            session_id: 会话ID
            db: 数据库会话
        
        Returns:
            处理结果：
            {
                "is_number_selection": true,
                "selection_number": 1,
                "selected_value": "慢丝割一修三",
                "standardized_input": "DIE-17用慢丝割一修三",
                "clarification_id": "uuid"
            }
            如果不是数字选择或处理失败，返回 None
        """
        logger.info(f"🔢 处理数字选择: {user_input}")
        
        # 1. 检测是否是数字选择
        if not self.is_number_selection(user_input):
            logger.debug(f"不是数字选择")
            return None
        
        # 2. 提取选择的数字
        selection_number = self.extract_selection_number(user_input)
        
        if selection_number is None:
            logger.warning(f"⚠️  无法提取选择数字")
            return None
        
        logger.info(f"✅ 提取到选择数字: {selection_number}")
        
        # 3. 查找最近的澄清消息
        clarification = await self.find_recent_clarification(session_id, db)
        
        if not clarification:
            logger.warning(f"⚠️  未找到最近的澄清消息")
            return None
        
        # 4. 映射数字到选项值
        parsed_entities = clarification.get("parsed_entities", {})
        selected_value = self.map_number_to_option(selection_number, parsed_entities)
        
        if not selected_value:
            logger.warning(f"⚠️  无法映射到有效选项")
            return None
        
        # 5. 生成标准化输入
        standardized_input = self.generate_standardized_input(
            parsed_entities,
            selected_value
        )
        
        logger.info(f"✅ 数字选择处理成功")
        
        return {
            "is_number_selection": True,
            "selection_number": selection_number,
            "selected_value": selected_value,
            "standardized_input": standardized_input,
            "clarification_id": clarification.get("clarification_id"),
            "parsed_entities": parsed_entities
        }
