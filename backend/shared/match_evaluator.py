"""
MatchEvaluator - 匹配结果评估器

职责：
1. 评估匹配结果的质量
2. 计算置信度
3. 决定是否需要用户确认
4. 生成建议信息
"""
import logging
from dataclasses import dataclass
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """匹配结果"""
    status: str  # "unique", "multiple", "none", "ambiguous"
    matches: List[Dict]
    confidence: float
    suggestion: str
    reasoning: str = ""


class MatchEvaluator:
    """匹配结果评估器"""
    
    # 配置参数
    MAX_DISPLAY_CANDIDATES = 10  # 最多展示的候选项数量（用于日志）
    # AMBIGUOUS_THRESHOLD = 10  # 🔧 移除限制：不再限制匹配数量
    
    @staticmethod
    def evaluate(
        matches: List[Dict],
        user_input: str,
        context: Dict[str, Any]
    ) -> MatchResult:
        """
        评估匹配结果
        
        Args:
            matches: 匹配到的零件列表
            user_input: 用户原始输入
            context: 上下文信息
        
        Returns:
            评估结果
        """
        match_count = len(matches)
        
        logger.info(f"📊 评估匹配结果: {match_count} 个匹配项")
        
        # 1. 无匹配
        if match_count == 0:
            return MatchResult(
                status="none",
                matches=[],
                confidence=0.0,
                suggestion="未找到匹配的零件，请检查输入是否正确",
                reasoning="没有找到任何匹配的零件"
            )
        
        # 2. 唯一匹配
        elif match_count == 1:
            return MatchResult(
                status="unique",
                matches=matches,
                confidence=1.0,
                suggestion="找到唯一匹配，将直接执行操作",
                reasoning="只有一个匹配项，可以直接执行"
            )
        
        # 3. 多个匹配（直接批量修改，不限制数量）
        else:
            # 计算置信度（基于匹配数量）
            confidence = MatchEvaluator._calculate_confidence(match_count)
            
            return MatchResult(
                status="multiple",
                matches=matches,
                confidence=confidence,
                suggestion=f"找到 {match_count} 个匹配的零件，将批量修改",
                reasoning=f"找到 {match_count} 个匹配项，直接批量修改"
            )
    
    @staticmethod
    def _calculate_confidence(match_count: int) -> float:
        """
        计算置信度
        
        基于匹配数量计算置信度：
        - 2个匹配: 0.9
        - 3个匹配: 0.8
        - 4-5个匹配: 0.7
        - 6-10个匹配: 0.6
        
        Args:
            match_count: 匹配数量
        
        Returns:
            置信度 (0.0-1.0)
        """
        if match_count == 1:
            return 1.0
        elif match_count == 2:
            return 0.9
        elif match_count == 3:
            return 0.8
        elif match_count <= 5:
            return 0.7
        elif match_count <= 10:
            return 0.6
        else:
            return 0.3
    
    @staticmethod
    def should_confirm(match_result: MatchResult) -> bool:
        """
        判断是否需要用户确认
        
        Args:
            match_result: 匹配结果
        
        Returns:
            是否需要确认
        """
        # 唯一匹配不需要确认
        if match_result.status == "unique":
            return False
        
        # 多个匹配或模糊匹配需要确认
        if match_result.status in ["multiple", "ambiguous"]:
            return True
        
        # 无匹配不需要确认（直接报错）
        return False
    
    @staticmethod
    def format_match_summary(matches: List[Dict]) -> str:
        """
        格式化匹配摘要
        
        Args:
            matches: 匹配的零件列表
        
        Returns:
            格式化的摘要文本
        """
        if not matches:
            return "无匹配"
        
        if len(matches) == 1:
            item = matches[0]
            source = item.get("_source", {})
            sg_id = source.get("subgraph_id", "N/A")
            part_name = item.get("part_name", "N/A")
            return f"唯一匹配: {sg_id} ({part_name})"
        
        return f"{len(matches)} 个匹配项"
    
    @staticmethod
    def extract_match_info(match: Dict) -> Dict[str, Any]:
        """
        提取匹配项的关键信息
        
        Args:
            match: 匹配的零件
        
        Returns:
            关键信息字典
        """
        source = match.get("_source", {})
        
        # 提取尺寸
        length = match.get("length_mm", "")
        width = match.get("width_mm", "")
        thickness = match.get("thickness_mm", "")
        dimensions = f"{length}*{width}*{thickness}" if all([length, width, thickness]) else "N/A"
        
        return {
            "subgraph_id": source.get("subgraph_id", "N/A"),
            "part_name": match.get("part_name", "N/A"),
            "part_code": match.get("part_code", "N/A"),
            "material": match.get("material", "N/A"),
            "dimensions": dimensions,
            "process_code": match.get("process_code", "N/A")
        }
