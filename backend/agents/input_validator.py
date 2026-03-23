"""
Input Validator - 输入验证器
负责人：人员B2

职责：
1. 验证用户输入的规范性
2. 基于实际数据（Display View）和静态映射（ProcessCodeMapping）进行验证
3. 处理 Redis 数据过期和降级策略
"""
import logging
import json
from typing import Dict, List, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from .clarification_models import (
    ValidationResult,
    ValidationIssue,
    ValidationIssueType,
    ValidationSeverity,
    ValueValidationResult,
    DataSource
)
from shared.process_code_mapping import PROCESS_DETAIL_MAPPING, resolve_process_code

logger = logging.getLogger(__name__)


class InputValidator:
    """输入验证器"""
    
    def __init__(self):
        self._redis_client = None
    
    @property
    def redis_client(self):
        """懒加载 Redis 客户端"""
        if self._redis_client is None:
            from api_gateway.utils.redis_client import redis_client
            self._redis_client = redis_client
        return self._redis_client
    
    async def validate(
        self,
        user_input: str,
        job_id: str,
        db: AsyncSession
    ) -> ValidationResult:
        """
        验证用户输入
        
        检查项：
        1. 实体提取（零件代码、字段名、值）
        2. 字段名有效性（基于 Display View schema）
        3. 零件代码存在性（基于 Display View data）
        4. 值有效性（基于 ProcessCodeMapping + Display View）
        5. 完整性检查（是否缺少关键信息）
        
        Args:
            user_input: 用户输入的自然语言
            job_id: 任务ID
            db: 数据库会话
        
        Returns:
            ValidationResult: 验证结果
        """
        logger.info(f"🔍 开始验证输入: {user_input[:50]}...")
        
        issues = []
        suggestions = []
        extracted_entities = {}
        
        try:
            # 1. 获取 Display View（带降级策略）
            display_view, data_source = await self._get_display_view_with_fallback(job_id, db)
            
            if not display_view:
                logger.warning(f"⚠️  无法获取 Display View，跳过数据验证")
                issues.append(ValidationIssue(
                    type=ValidationIssueType.INCOMPLETE,
                    field=None,
                    message="无法获取当前任务数据，将跳过数据验证",
                    severity=ValidationSeverity.WARNING
                ))
                # 返回部分验证结果
                return ValidationResult(
                    is_valid=False,
                    extracted_entities=extracted_entities,
                    issues=issues,
                    suggestions=["请确保任务数据已加载"]
                )
            
            logger.info(f"✅ Display View 获取成功: {len(display_view)} 条记录, 来源: {data_source}")
            
            # 2. 使用 LLM 提取实体（替代正则表达式）
            logger.info(f"🤖 使用 LLM 提取实体")
            from agents.llm_entity_extractor import LLMEntityExtractor
            
            try:
                llm_extractor = LLMEntityExtractor()
                
                # 获取可用字段列表
                available_fields = list(display_view[0].keys()) if display_view else []
                
                # 使用 LLM 提取实体
                extracted_entities = await llm_extractor.extract_entities(
                    user_input=user_input,
                    available_fields=available_fields
                )
                extracted_entities = extracted_entities or {}
                
                logger.info(f"✅ LLM 提取的实体: {extracted_entities}")
                
            except Exception as llm_error:
                logger.error(f"❌ LLM 实体提取失败: {llm_error}, 使用简单提取")
                # Fallback: 使用简单的正则提取
                extracted_entities = self._extract_entities_simple(user_input)
            
            extracted_entities = extracted_entities or {}
            
            # 3. 验证零件代码
            if "part_code" in extracted_entities and extracted_entities["part_code"]:
                part_code = extracted_entities["part_code"]
                if not self._check_part_code_existence(part_code, display_view):
                    issues.append(ValidationIssue(
                        type=ValidationIssueType.UNKNOWN_PART_CODE,
                        field="part_code",
                        message=f"未找到零件代码: {part_code}",
                        severity=ValidationSeverity.ERROR
                    ))
                    # 提供建议
                    similar_codes = self._find_similar_part_codes(part_code, display_view)
                    if similar_codes:
                        suggestions.append(f"您是否想要修改: {', '.join(similar_codes[:3])}")
            
            # 4. 验证字段名
            if "field" in extracted_entities and extracted_entities["field"]:
                field_name = extracted_entities["field"]
                if not self._check_field_validity(field_name, display_view):
                    issues.append(ValidationIssue(
                        type=ValidationIssueType.UNKNOWN_FIELD,
                        field=field_name,
                        message=f"未知的字段名: {field_name}",
                        severity=ValidationSeverity.ERROR
                    ))
            
            # 5. 验证值（工艺代码、材质等）
            if ("value" in extracted_entities and extracted_entities["value"] and 
                "field" in extracted_entities and extracted_entities["field"]):
                field_name = extracted_entities["field"]
                value = extracted_entities["value"]
                
                value_result = self._check_value_validity(field_name, value, display_view)
                
                if not value_result.is_valid:
                    issues.append(ValidationIssue(
                        type=ValidationIssueType.INVALID_VALUE,
                        field=field_name,
                        message=f"无效的值: {value}",
                        severity=ValidationSeverity.ERROR
                    ))
                    
                    if value_result.alternatives:
                        suggestions.append(f"可能的值: {', '.join(value_result.alternatives[:5])}")
                        # 🆕 将建议添加到实体中，供确认消息使用
                        extracted_entities["_suggestions"] = value_result.alternatives[:5]
                    
                    # 🆕 如果有模糊匹配的最佳值，使用它
                    if value_result.matched_value:
                        extracted_entities["_best_match"] = value_result.matched_value
                        extracted_entities["value"] = value_result.matched_value
            
            # 🆕 5.5. 特殊验证：价格修改时，验证工艺/材质是否存在于数据中
            field_value = extracted_entities.get("field") or ""
            if field_value and "unit_price" in field_value:
                # 从 reasoning 中提取工艺/材质名称
                reasoning = extracted_entities.get("reasoning", "")
                process_exists = self._check_process_exists_in_data(reasoning, display_view)
                
                if not process_exists:
                    issues.append(ValidationIssue(
                        type=ValidationIssueType.INVALID_VALUE,
                        field=field_value,
                        message=f"当前数据中不存在该工艺",
                        severity=ValidationSeverity.ERROR
                    ))
                    # 提供当前数据中存在的工艺列表
                    existing_processes = self._get_existing_processes(display_view)
                    if existing_processes:
                        suggestions.append(f"当前数据中的工艺: {', '.join(existing_processes[:5])}")

            
            # 6. 检查完整性
            if not extracted_entities.get("part_code"):
                issues.append(ValidationIssue(
                    type=ValidationIssueType.MISSING_FIELD,
                    field="part_code",
                    message="缺少零件代码",
                    severity=ValidationSeverity.ERROR
                ))
            
            if not extracted_entities.get("field"):
                issues.append(ValidationIssue(
                    type=ValidationIssueType.MISSING_FIELD,
                    field="field",
                    message="缺少要修改的字段",
                    severity=ValidationSeverity.ERROR
                ))
            
            # 7. 判断是否有效
            is_valid = not any(issue.severity == ValidationSeverity.ERROR for issue in issues)
            
            logger.info(f"✅ 验证完成: is_valid={is_valid}, issues={len(issues)}")
            
            return ValidationResult(
                is_valid=is_valid,
                extracted_entities=extracted_entities,
                issues=issues,
                suggestions=suggestions
            )
        
        except Exception as e:
            logger.error(f"❌ 验证失败: {e}", exc_info=True)
            issues.append(ValidationIssue(
                type=ValidationIssueType.INCOMPLETE,
                field=None,
                message=f"验证过程出错: {str(e)}",
                severity=ValidationSeverity.ERROR
            ))
            
            return ValidationResult(
                is_valid=False,
                extracted_entities=extracted_entities,
                issues=issues,
                suggestions=[]
            )
    
    async def _get_display_view_with_fallback(
        self,
        job_id: str,
        db: AsyncSession
    ) -> tuple[List[Dict], str]:
        """
        获取展示视图，带完整的降级策略
        
        策略：
        1. 尝试从 Redis 获取缓存
        2. Redis 缓存未命中，从数据库重建
        3. Redis 不可用，直接使用数据库
        4. 所有方法都失败，返回空列表
        
        Returns:
            (display_view, data_source)
            data_source: "redis_cache" | "database_rebuild" | "database_direct" | "empty_fallback"
        """
        try:
            # 1. 尝试从 Redis 获取
            cached_data = await self._get_display_view_from_redis(job_id)
            if cached_data:
                logger.info(f"✅ Display view from Redis cache: {job_id}")
                return cached_data, "redis_cache"
            
            # 2. Redis 缓存未命中，从数据库重建
            logger.warning(f"⚠️  Redis cache miss for job {job_id}, rebuilding from database")
            display_view = await self._rebuild_display_view_from_db(job_id, db)
            
            if display_view:
                # 3. 重建成功，更新 Redis 缓存
                await self._save_display_view_to_redis(job_id, display_view, ttl=3600)
                logger.info(f"✅ Display view rebuilt and cached: {job_id}")
                return display_view, "database_rebuild"
            else:
                logger.error(f"❌ Failed to rebuild display view from database")
                return [], "empty_fallback"
        
        except Exception as e:
            # 4. Redis 不可用或其他错误，直接使用数据库
            logger.error(f"❌ Error in display view retrieval: {e}, using database directly")
            try:
                display_view = await self._rebuild_display_view_from_db(job_id, db)
                if display_view:
                    return display_view, "database_direct"
                else:
                    return [], "empty_fallback"
            except Exception as db_error:
                logger.error(f"❌ Database query also failed: {db_error}")
                return [], "empty_fallback"
    
    async def _get_display_view_from_redis(self, job_id: str) -> Optional[List[Dict]]:
        """从 Redis 获取缓存的展示视图"""
        try:
            key = f"review:state:{job_id}"
            data = await self.redis_client.get(key)
            
            if data:
                state = json.loads(data)
                display_view = state.get("display_view")
                if display_view:
                    return display_view
            
            return None
        
        except Exception as e:
            logger.error(f"❌ Failed to get display view from Redis: {e}")
            return None
    
    async def _rebuild_display_view_from_db(
        self,
        job_id: str,
        db: AsyncSession
    ) -> Optional[List[Dict]]:
        """
        从数据库重建展示视图
        
        调用 DataViewBuilder.build_display_view()
        """
        try:
            from api_gateway.repositories.review_repository import ReviewRepository
            from agents.data_view_builder import DataViewBuilder
            
            # 查询原始数据
            review_repo = ReviewRepository()
            raw_data = await review_repo.get_all_review_data(db, job_id)
            
            # 构建展示视图
            display_view = DataViewBuilder.build_display_view(raw_data)
            
            return display_view
        
        except Exception as e:
            logger.error(f"❌ Failed to rebuild display view from database: {e}")
            return None
    
    async def _save_display_view_to_redis(
        self,
        job_id: str,
        display_view: List[Dict],
        ttl: int = 3600
    ):
        """保存展示视图到 Redis"""
        try:
            key = f"review:state:{job_id}"
            
            # 获取现有状态
            existing_data = await self.redis_client.get(key)
            if existing_data:
                state = json.loads(existing_data)
            else:
                state = {}
            
            # 更新 display_view
            state["display_view"] = display_view
            
            # 保存回 Redis
            await self.redis_client.set(key, json.dumps(state), ex=ttl)
            logger.info(f"✅ Display view saved to Redis: {job_id}")
        
        except Exception as e:
            logger.error(f"❌ Failed to save display view to Redis: {e}")
    
    def _extract_entities_simple(self, user_input: str) -> Dict[str, Any]:
        """
        简单的实体提取（基于规则）
        
        后续可以用 LLM 增强
        """
        entities = {}
        
        # 提取零件代码（如 DIE-01, PU-01 等）
        import re
        part_code_pattern = r'([A-Z]{2,4}[-_]?\d{1,3})'
        part_codes = re.findall(part_code_pattern, user_input, re.IGNORECASE)
        if part_codes:
            entities["part_code"] = part_codes[0].upper()
        
        # 提取工艺关键词
        process_keywords = ["工艺", "process", "慢丝", "中丝", "快丝"]
        for keyword in process_keywords:
            if keyword in user_input:
                entities["field"] = "process_code"
                # 🆕 同时尝试提取工艺值（简略形式）
                if "慢丝" in user_input:
                    entities["value"] = "慢丝"
                elif "中丝" in user_input:
                    entities["value"] = "中丝"
                elif "快丝" in user_input:
                    entities["value"] = "快丝"
                break
        
        # 提取材质关键词
        material_keywords = ["材质", "material", "材料"]
        for keyword in material_keywords:
            if keyword in user_input:
                entities["field"] = "material"
                break
        
        # 提取完整工艺名称（优先级更高）
        for process_name in PROCESS_DETAIL_MAPPING.keys():
            if process_name in user_input:
                entities["value"] = process_name
                entities["field"] = "process_code"
                break
        
        return entities
    
    def _check_field_validity(
        self,
        field_name: str,
        display_view: List[Dict]
    ) -> bool:
        """检查字段名是否有效"""
        if not display_view:
            return False
        
        # 获取第一条记录的所有字段
        valid_fields = set(display_view[0].keys()) if display_view else set()
        
        # 移除内部字段
        valid_fields.discard("_source")
        
        return field_name in valid_fields
    
    def _check_part_code_existence(
        self,
        part_code: str,
        display_view: List[Dict]
    ) -> bool:
        """检查零件代码是否存在"""
        for item in display_view:
            if item.get("part_code") == part_code:
                return True
        return False
    
    def _find_similar_part_codes(
        self,
        part_code: str,
        display_view: List[Dict],
        max_results: int = 5
    ) -> List[str]:
        """查找相似的零件代码"""
        if not part_code:  # 🆕 处理 None 或空字符串
            return []
        
        similar_codes = []
        part_code_lower = part_code.lower()
        
        for item in display_view:
            code = item.get("part_code", "")
            if code and part_code_lower in code.lower():
                similar_codes.append(code)
                if len(similar_codes) >= max_results:
                    break
        
        return similar_codes
    
    def _check_value_validity(
        self,
        field_name: str,
        value: str,
        display_view: List[Dict]
    ) -> ValueValidationResult:
        """
        检查值的有效性
        
        优先级：
        1. ProcessCodeMapping（静态映射）
        2. Display View 中的实际值（动态数据）
        3. 🆕 模糊匹配（如果精确匹配失败）
        4. 🆕 价格字段特殊处理（验证工艺是否存在于数据中）
        """
        # 🆕 特殊处理：价格字段（如 process_unit_price, material_unit_price）
        if "unit_price" in field_name:
            # 对于价格字段，value 实际上是数字，不需要验证
            # 但需要验证用户输入中提到的工艺/材质是否存在于数据中
            # 这个验证应该在上层逻辑中处理（通过 reasoning 提取工艺名称）
            return ValueValidationResult(
                is_valid=True,
                matched_value=value,
                source=DataSource.NONE,
                confidence=1.0
            )
        
        # 1. 检查 ProcessCodeMapping（精确匹配）
        if field_name == "process_code":
            process_info = resolve_process_code(value)
            if process_info:
                return ValueValidationResult(
                    is_valid=True,
                    matched_value=process_info["sub_category"],
                    source=DataSource.PROCESS_MAPPING,
                    confidence=1.0
                )
            
            # 🆕 2. 模糊匹配工艺代码
            fuzzy_matches = self._fuzzy_match_process_code(value)
            if fuzzy_matches:
                # 返回最佳匹配
                best_match = fuzzy_matches[0]
                return ValueValidationResult(
                    is_valid=False,  # 不是精确匹配
                    matched_value=best_match["full_name"],
                    source=DataSource.PROCESS_MAPPING,
                    alternatives=[m["full_name"] for m in fuzzy_matches[:5]],
                    confidence=best_match["confidence"]
                )
        
        # 3. 检查 Display View 中的实际值
        existing_values = set()
        for item in display_view:
            if field_name in item and item[field_name]:
                existing_values.add(str(item[field_name]))
        
        if value in existing_values:
            return ValueValidationResult(
                is_valid=True,
                matched_value=value,
                source=DataSource.DISPLAY_VIEW,
                confidence=0.9
            )
        
        # 4. 未找到，返回替代值
        return ValueValidationResult(
            is_valid=False,
            matched_value=None,
            source=DataSource.NONE,
            alternatives=list(existing_values)[:10],
            confidence=0.0
        )
    
    def _fuzzy_match_process_code(self, value: str) -> List[Dict[str, Any]]:
        """
        模糊匹配工艺代码
        
        Args:
            value: 用户输入的值（如 "中丝"）
        
        Returns:
            匹配结果列表，按置信度排序
        """
        matches = []
        
        # 简略形式映射
        abbreviation_map = {
            "慢丝": ["慢丝割一修三", "慢丝割一修二", "慢丝割一修一", "慢丝割一刀"],
            "中丝": ["中丝割一修一"],
            "快丝": ["快丝割一刀"]
        }
        
        # 检查是否是简略形式
        if value in abbreviation_map:
            for full_name in abbreviation_map[value]:
                if full_name in PROCESS_DETAIL_MAPPING:
                    process_info = PROCESS_DETAIL_MAPPING[full_name]
                    matches.append({
                        "full_name": full_name,
                        "sub_category": process_info["sub_category"],
                        "note": process_info["note"],
                        "confidence": 0.9  # 高置信度，因为是已知的简略形式
                    })
        
        # 如果没有找到简略形式匹配，尝试部分匹配
        if not matches:
            for process_name, process_info in PROCESS_DETAIL_MAPPING.items():
                if value in process_name or value in process_info["note"]:
                    matches.append({
                        "full_name": process_name,
                        "sub_category": process_info["sub_category"],
                        "note": process_info["note"],
                        "confidence": 0.7  # 中等置信度
                    })
        
        # 按置信度排序
        matches.sort(key=lambda x: x["confidence"], reverse=True)
        
        return matches

    
    def _check_process_exists_in_data(self, reasoning: str, display_view: List[Dict]) -> bool:
        """
        检查 reasoning 中提到的工艺是否存在于数据中
        
        Args:
            reasoning: LLM 的推理说明（包含工艺名称）
            display_view: 展示视图数据
        
        Returns:
            True 如果工艺存在于数据中
        """
        # 从 reasoning 中提取工艺名称
        # 常见模式："线割慢丝割一修二"、"慢丝割一修一"等
        process_keywords = [
            "慢丝割一修三", "慢丝割一修二", "慢丝割一修一", "慢丝割一刀",
            "中丝割一修一", "快丝割一刀",
            "线割", "NC", "铣床", "磨床", "车床", "钻床"
        ]
        
        # 提取 reasoning 中提到的工艺
        mentioned_process = None
        for keyword in process_keywords:
            if keyword in reasoning:
                mentioned_process = keyword
                break
        
        if not mentioned_process:
            # 无法提取工艺名称，跳过验证
            return True
        
        # 检查数据中是否存在使用该工艺的零件
        for item in display_view:
            process_name = item.get("process_name", "")
            if mentioned_process in process_name:
                return True
        
        return False
    
    def _get_existing_processes(self, display_view: List[Dict]) -> List[str]:
        """
        获取数据中存在的所有工艺
        
        Args:
            display_view: 展示视图数据
        
        Returns:
            工艺名称列表
        """
        processes = set()
        for item in display_view:
            process_name = item.get("process_name", "")
            if process_name:
                processes.add(process_name)
        
        return sorted(list(processes))
