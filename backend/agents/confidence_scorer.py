"""
Confidence Scorer - 置信度评分器
负责人：人员B2

职责：
计算输入的置信度分数，决定是否触发澄清流程
"""
import logging
import re
from typing import Optional

from .clarification_models import ValidationResult, HistoryMatch, ValidationSeverity, ValidationIssueType

logger = logging.getLogger(__name__)


class ConfidenceScorer:
    """置信度评分器"""
    
    # 评分权重
    WEIGHT_ENTITY_COMPLETENESS = 0.3
    WEIGHT_VALIDITY = 0.4
    WEIGHT_FORMALITY = 0.2
    WEIGHT_HISTORY = 0.1
    
    def calculate_score(
        self,
        validation_result: ValidationResult,
        user_input: str,
        history_match: Optional[HistoryMatch] = None
    ) -> float:
        """
        计算置信度分数（0.0 - 1.0）
        
        评分因素：
        1. 实体提取完整性（0.3权重）
        2. 字段/值有效性（0.4权重）
        3. 输入规范性（0.2权重）
        4. 历史匹配度（0.1权重）
        
        Args:
            validation_result: 验证结果
            user_input: 用户输入
            history_match: 历史匹配结果（可选）
        
        Returns:
            置信度分数，越高表示越确定
        """
        logger.info(f"📊 计算置信度分数...")
        
        # 1. 实体完整性评分
        entity_score = self._score_entity_completeness(validation_result.extracted_entities)
        logger.debug(f"实体完整性评分: {entity_score:.2f}")
        
        # 2. 有效性评分
        validity_score = self._score_validity(validation_result)
        logger.debug(f"有效性评分: {validity_score:.2f}")
        
        # 3. 规范性评分
        formality_score = self._score_input_formality(user_input)
        logger.debug(f"规范性评分: {formality_score:.2f}")
        
        # 4. 历史匹配评分
        history_score = self._score_history_match(history_match)
        logger.debug(f"历史匹配评分: {history_score:.2f}")
        
        # 5. 加权计算总分
        total_score = (
            entity_score * self.WEIGHT_ENTITY_COMPLETENESS +
            validity_score * self.WEIGHT_VALIDITY +
            formality_score * self.WEIGHT_FORMALITY +
            history_score * self.WEIGHT_HISTORY
        )
        
        logger.info(f"✅ 总置信度分数: {total_score:.2f}")
        
        return total_score
    
    def _score_entity_completeness(self, extracted_entities: dict) -> float:
        """
        评分：实体提取完整性
        
        必需实体：
        - part_code: 零件代码（批量操作或价格修改时可为 None）
        - field: 要修改的字段
        - value: 新值（可选，但有更好）
        
        特殊情况：
        - 批量操作（part_code=None 但有批量关键词）视为完整
        - 价格修改（field 为 *_unit_price）不需要 part_code
        """
        score = 0.0
        
        # 检查是否是批量操作
        is_batch_operation = self._is_batch_operation(extracted_entities)
        
        # 检查是否是价格修改（修改单价字段）
        field = extracted_entities.get("field", "")
        is_price_modification = field and "unit_price" in field
        
        # part_code 是必需的（0.4分）
        # 但批量操作或价格修改时，part_code=None 也视为有效
        if extracted_entities.get("part_code"):
            score += 0.4
        elif is_batch_operation:
            # 批量操作，part_code 为 None 是正常的
            score += 0.4
            logger.debug("检测到批量操作，part_code=None 视为有效")
        elif is_price_modification:
            # 价格修改，part_code 为 None 是正常的（修改价格表）
            score += 0.4
            logger.debug("检测到价格修改操作，part_code=None 视为有效")
        
        # field 是必需的（0.4分）
        if extracted_entities.get("field"):
            score += 0.4
        
        # value 是可选的，但有更好（0.2分）
        if extracted_entities.get("value"):
            score += 0.2
        
        return score
    
    def _is_batch_operation(self, extracted_entities: dict) -> bool:
        """
        检测是否是批量操作
        
        批量操作特征：
        1. part_code 为 None
        2. action 为 "data_modification"
        3. reasoning 中包含批量操作关键词或模式
        
        Returns:
            True 如果是批量操作
        """
        # 必须是数据修改操作
        if extracted_entities.get("action") != "data_modification":
            return False
        
        # part_code 必须为 None
        if extracted_entities.get("part_code") is not None:
            return False
        
        # 检查 reasoning 中是否包含批量操作关键词或模式
        reasoning = extracted_entities.get("reasoning", "")
        
        # 标准批量关键词
        batch_keywords = [
            "全部", "所有", "全体", "整体", "批量",
            "all", "batch", "全局", "统一"
        ]
        
        for keyword in batch_keywords:
            if keyword in reasoning:
                logger.debug(f"在 reasoning 中检测到批量关键词: {keyword}")
                return True
        
        # 条件筛选模式（如"B2开头"、"DIE类型"、"某某零件"）
        pattern_keywords = [
            "开头", "类型", "一类", "这类", "该类",
            "批量", "范围", "筛选", "条件", "隐含"
        ]
        
        for keyword in pattern_keywords:
            if keyword in reasoning:
                logger.debug(f"在 reasoning 中检测到批量模式关键词: {keyword}")
                return True
        
        return False
    
    def _score_validity(self, validation_result: ValidationResult) -> float:
        """
        评分：字段和值的有效性
        
        基于验证结果中的问题数量和严重程度
        
        🆕 特殊处理：
        - INVALID_VALUE（工艺值无效）：扣 0.5 分（更严重）
        - 其他 ERROR：扣 0.3 分
        - WARNING：扣 0.1 分
        """
        if validation_result.is_valid:
            return 1.0
        
        # 计算不同类型的问题数量
        invalid_value_count = 0
        other_error_count = 0
        warning_count = 0
        
        for issue in validation_result.issues:
            if issue.severity == ValidationSeverity.ERROR:
                # 🆕 区分 INVALID_VALUE 和其他错误
                if issue.type == ValidationIssueType.INVALID_VALUE:
                    invalid_value_count += 1
                else:
                    other_error_count += 1
            elif issue.severity == ValidationSeverity.WARNING:
                warning_count += 1
        
        # 🆕 INVALID_VALUE 扣更多分（0.5），因为这通常意味着用户输入不明确
        penalty = (
            invalid_value_count * 0.5 +  # 工艺值无效：扣 0.5 分
            other_error_count * 0.3 +     # 其他错误：扣 0.3 分
            warning_count * 0.1           # 警告：扣 0.1 分
        )
        
        score = max(0.0, 1.0 - penalty)
        
        logger.debug(f"有效性评分详情: invalid_value={invalid_value_count}, other_error={other_error_count}, warning={warning_count}, penalty={penalty:.2f}, score={score:.2f}")
        
        return score
    
    def _score_input_formality(self, user_input: str) -> float:
        """
        评分：输入规范性
        
        检查：
        - 是否包含明确的动词（修改、改为、设置等）
        - 是否使用完整的字段名
        - 是否使用标准术语
        - 输入长度是否合理
        - 是否是批量操作（给予额外加分）
        """
        score = 0.0
        
        # 1. 检查是否包含明确的动词（0.3分）
        action_verbs = ["修改", "改为", "改成", "设置", "更新", "调整", "变更"]
        if any(verb in user_input for verb in action_verbs):
            score += 0.3
        
        # 2. 检查是否使用完整的字段名（0.3分）
        complete_field_names = [
            "工艺代码", "process_code", "工艺",
            "材质", "material", "材料",
            "长度", "length", "宽度", "width", "厚度", "thickness"
        ]
        if any(field in user_input for field in complete_field_names):
            score += 0.3
        
        # 3. 检查输入长度（0.2分）
        # 太短（<5字符）或太长（>100字符）都不好
        input_length = len(user_input)
        if 10 <= input_length <= 50:
            score += 0.2
        elif 5 <= input_length < 10 or 50 < input_length <= 100:
            score += 0.1
        
        # 4. 检查是否使用标准工艺术语（0.2分）
        standard_process_terms = [
            "慢丝割一修三", "慢丝割一修二", "慢丝割一修一", "慢丝割一刀",
            "中丝割一修一", "快丝割一刀"
        ]
        if any(term in user_input for term in standard_process_terms):
            score += 0.2
        else:
            # 检查是否使用了简略术语（扣分）
            abbreviated_terms = ["慢丝", "中丝", "快丝", "割一刀", "割一修一"]
            if any(term in user_input for term in abbreviated_terms):
                # 使用简略术语，降低置信度
                score -= 0.1
        
        # 5. 检查是否是批量操作（额外加分 0.2）
        # 标准批量关键词
        batch_keywords = ["全部", "所有", "全体", "整体", "批量", "all", "全局", "统一"]
        if any(keyword in user_input for keyword in batch_keywords):
            score += 0.2
            logger.debug(f"检测到批量操作关键词，规范性评分 +0.2")
        else:
            # 条件筛选模式（如"B2开头"、"DIE类型"、"XX零件"）
            pattern_keywords = ["开头", "类型", "这类", "该类", "这些", "那些", "这套", "那套"]
            if any(keyword in user_input for keyword in pattern_keywords):
                score += 0.2
                logger.debug(f"检测到批量筛选模式，规范性评分 +0.2")
        
        return max(0.0, min(1.0, score))
    
    def _score_history_match(self, history_match: Optional[HistoryMatch]) -> float:
        """
        评分：历史匹配度
        
        如果有历史匹配，使用匹配的相似度作为分数
        """
        if history_match:
            return history_match.similarity
        
        return 0.0
