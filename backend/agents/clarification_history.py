"""
Clarification History - 澄清历史管理器
负责人：人员B2

职责：
管理澄清历史，支持学习用户习惯
"""
import logging
from typing import Dict, List, Optional
from datetime import datetime
from difflib import SequenceMatcher

from .clarification_models import HistoryEntry, HistoryMatch

logger = logging.getLogger(__name__)


class ClarificationHistory:
    """澄清历史管理器"""
    
    def __init__(self):
        # 会话历史：{session_id: [HistoryEntry, ...]}
        self.session_history: Dict[str, List[HistoryEntry]] = {}
    
    def add_entry(
        self,
        session_id: str,
        original_input: str,
        normalized_input: str,
        parsed_entities: Dict
    ):
        """
        添加历史记录
        
        Args:
            session_id: 会话ID
            original_input: 原始输入
            normalized_input: 标准化输入
            parsed_entities: 解析的实体
        """
        logger.info(f"📝 添加历史记录: session_id={session_id}")
        
        entry = HistoryEntry(
            timestamp=datetime.now(),
            original_input=original_input,
            normalized_input=normalized_input,
            parsed_entities=parsed_entities
        )
        
        if session_id not in self.session_history:
            self.session_history[session_id] = []
        
        self.session_history[session_id].append(entry)
        
        logger.debug(f"历史记录数: {len(self.session_history[session_id])}")
    
    def find_similar(
        self,
        session_id: str,
        user_input: str,
        threshold: float = 0.8
    ) -> Optional[HistoryMatch]:
        """
        查找相似的历史记录
        
        使用 SequenceMatcher 计算相似度
        
        Args:
            session_id: 会话ID
            user_input: 用户输入
            threshold: 相似度阈值（0.0-1.0）
        
        Returns:
            HistoryMatch: 最相似的历史记录，如果没有超过阈值的返回 None
        """
        logger.info(f"🔍 查找相似历史: session_id={session_id}, threshold={threshold}")
        
        if session_id not in self.session_history:
            logger.debug(f"会话无历史记录")
            return None
        
        history = self.session_history[session_id]
        
        if not history:
            return None
        
        # 查找最相似的记录
        best_match = None
        best_similarity = 0.0
        
        for entry in history:
            similarity = self._calculate_similarity(user_input, entry.original_input)
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = entry
        
        # 检查是否超过阈值
        if best_similarity >= threshold:
            logger.info(f"✅ 找到相似历史: similarity={best_similarity:.2f}")
            return HistoryMatch(
                entry=best_match,
                similarity=best_similarity
            )
        else:
            logger.debug(f"未找到足够相似的历史: best_similarity={best_similarity:.2f}")
            return None
    
    def clear_session(self, session_id: str):
        """
        清除会话历史
        
        Args:
            session_id: 会话ID
        """
        logger.info(f"🗑️  清除会话历史: session_id={session_id}")
        
        if session_id in self.session_history:
            del self.session_history[session_id]
            logger.debug(f"✅ 会话历史已清除")
        else:
            logger.debug(f"会话无历史记录")
    
    def get_session_history(self, session_id: str) -> List[HistoryEntry]:
        """
        获取会话历史
        
        Args:
            session_id: 会话ID
        
        Returns:
            历史记录列表
        """
        return self.session_history.get(session_id, [])
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        计算两个文本的相似度
        
        使用 SequenceMatcher（基于 Levenshtein 距离）
        
        Args:
            text1: 文本1
            text2: 文本2
        
        Returns:
            相似度（0.0-1.0）
        """
        # 标准化文本（转小写，去除空格）
        text1_normalized = text1.lower().replace(" ", "")
        text2_normalized = text2.lower().replace(" ", "")
        
        # 计算相似度
        matcher = SequenceMatcher(None, text1_normalized, text2_normalized)
        similarity = matcher.ratio()
        
        return similarity
