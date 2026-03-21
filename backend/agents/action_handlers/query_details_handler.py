"""
QueryDetailsHandler - 查询详情处理器
负责人：人员B2

处理查询计算详情的意图，从数据库查询并格式化 calculation_steps
"""
import logging
import json
import os
from typing import Dict, Any, Optional, List
from sqlalchemy import select
import httpx

from .base_handler import BaseActionHandler
from agents.intent_types import IntentResult, ActionResult

logger = logging.getLogger(__name__)


class QueryDetailsHandler(BaseActionHandler):
    """
    查询详情处理器
    
    功能：
    1. 从意图中提取 subgraph_id
    2. 查询 processing_cost_calculation_details 表
    3. 使用 LLM 格式化 calculation_steps JSON 为友好的文本
    4. 直接返回结果（不需要确认）
    """
    
    def __init__(self):
        """初始化 Handler"""
        super().__init__()
        
        # LLM 配置
        self.use_llm = os.getenv("USE_LLM_FOR_QUERY_DETAILS", "true").lower() == "true"
        self.llm_base_url = os.getenv("OPENAI_BASE_URL") or settings.OPENAI_BASE_URL
        self.llm_api_key = os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY
        self.llm_model = os.getenv("OPENAI_MODEL", "Qwen3-30B-A3B-Instruct")
        self.llm_timeout = float(os.getenv("LLM_TIMEOUT") or settings.LLM_TIMEOUT)
        
        # 历史消息配置
        self.use_chat_history = os.getenv("USE_CHAT_HISTORY", "true").lower() == "true"
        self.max_history_messages = int(os.getenv("MAX_HISTORY_MESSAGES", "10"))  # 最多保留10条历史
        
        # HTTP 客户端
        self.http_client = httpx.AsyncClient(
            timeout=self.llm_timeout,
            headers={
                "User-Agent": "curl/8.0"
            }
        )
        
        # 懒加载 ChatHistoryRepository
        self._chat_history_repo = None
        
        logger.info(f"✅ QueryDetailsHandler 初始化完成 (use_llm={self.use_llm}, use_chat_history={self.use_chat_history})")
    
    @property
    def chat_history_repo(self):
        """懒加载 ChatHistoryRepository"""
        if self._chat_history_repo is None:
            from api_gateway.repositories.chat_history_repository import ChatHistoryRepository
            self._chat_history_repo = ChatHistoryRepository()
        return self._chat_history_repo
    
    async def handle(
        self,
        intent_result: IntentResult,
        job_id: str,
        context: Dict[str, Any],
        db_session
    ) -> ActionResult:
        """
        处理查询详情请求
        
        Args:
            intent_result: 意图识别结果
            job_id: 任务ID
            context: 当前审核数据上下文
            db_session: 数据库会话
        
        Returns:
            ActionResult: 处理结果
        """
        logger.info(f"🔍 处理查询详情: {intent_result.raw_message}")
        logger.info(f"📋 接收参数: subgraph_id={intent_result.parameters.get('subgraph_id')}, query_type={intent_result.parameters.get('query_type')}")  # 🆕 添加参数日志
        
        try:
            # 1. 提取 subgraph_id
            subgraph_id = intent_result.parameters.get("subgraph_id")
            
            # 🆕 如果 subgraph_id 为空，或者看起来不对（比如不是最近提到的），尝试从历史消息中推断
            if not subgraph_id and self.use_chat_history:
                logger.info(f"🔍 subgraph_id 为空，尝试从历史消息推断...")
                subgraph_id = await self._infer_subgraph_from_history(db_session, job_id)
                
                if subgraph_id:
                    logger.info(f"✅ 从历史推断出 subgraph_id: {subgraph_id}")
                else:
                    logger.warning(f"⚠️  无法从历史推断 subgraph_id")
            elif subgraph_id and self.use_chat_history:
                # 🆕 双重验证：检查 LLM 提取的 subgraph_id 是否是最近提到的
                # 如果用户使用了代词（"它"、"那个"），我们应该验证 LLM 的推断是否正确
                if intent_result.raw_message and any(pronoun in intent_result.raw_message for pronoun in ["它", "那个", "这个", "那", "这"]):
                    logger.info(f"🔍 检测到代词，验证 LLM 推断的 subgraph_id: {subgraph_id}")
                    verified_id = await self._infer_subgraph_from_history(db_session, job_id)
                    
                    if verified_id and verified_id != subgraph_id:
                        logger.warning(f"⚠️  LLM 推断的 {subgraph_id} 与历史推断的 {verified_id} 不一致，使用历史推断结果")
                        subgraph_id = verified_id
                    else:
                        logger.info(f"✅ LLM 推断验证通过: {subgraph_id}")
            
            if not subgraph_id:
                return ActionResult(
                    status="error",
                    message="请指定要查询的子图，例如：'UP01 的价格怎么算的？'",
                    requires_confirmation=False,
                    data={}  # 🔑 确保 data 不为 None
                )
            
            # 2. 提取查询类型（可选）
            query_type = intent_result.parameters.get("query_type")  # 如: "material", "heat", "weight"
            
            # 3. 查询数据库
            detail = await self._query_calculation_detail(
                db_session,
                job_id,
                subgraph_id
            )
            
            if not detail:
                return ActionResult(
                    status="ok",
                    message=f"{subgraph_id} 未查询到该零件。",
                    requires_confirmation=False,
                    data={}
                )
            
            # 4. 格式化 calculation_steps
            # 优先使用 LLM 格式化
            if self.use_llm:
                try:
                    formatted_message = await self._format_with_llm(
                        job_id,  # 🆕 传递 job_id（用于查询历史）
                        subgraph_id,
                        detail.calculation_steps,
                        intent_result.raw_message,
                        query_type,
                        db_session,  # 🆕 传递 db_session
                        getattr(detail, 'processing_instructions', None)  # 🆕 传递 processing_instructions
                    )
                    logger.info(f"✅ LLM 格式化成功: {subgraph_id}, query_type={query_type}")
                except Exception as e:
                    logger.error(f"❌ LLM 格式化失败: {e}，降级到规则格式化")
                    # Fallback: 使用规则格式化
                    if query_type:
                        formatted_message = self._format_specific_category(
                            subgraph_id,
                            detail.calculation_steps,
                            query_type
                        )
                    else:
                        formatted_message = self._format_calculation_steps(
                            subgraph_id,
                            detail.calculation_steps
                        )
            else:
                # 使用规则格式化
                if query_type:
                    formatted_message = self._format_specific_category(
                        subgraph_id,
                        detail.calculation_steps,
                        query_type
                    )
                else:
                    formatted_message = self._format_calculation_steps(
                        subgraph_id,
                        detail.calculation_steps
                    )
                logger.info(f"✅ 规则格式化完成: {subgraph_id}, query_type={query_type}")
            
            # 5. 直接返回（不需要确认）
            return ActionResult(
                status="ok",
                message=formatted_message,
                requires_confirmation=False,
                data={
                    "subgraph_id": subgraph_id,
                    "query_type": query_type,
                    "calculation_steps": detail.calculation_steps
                }
            )
        
        except Exception as e:
            logger.error(f"❌ 查询详情失败: {e}", exc_info=True)
            return ActionResult(
                status="error",
                message=f"查询详情失败：{str(e)}",
                data={}
            )
    
    async def _query_calculation_detail(
        self,
        db_session,
        job_id: str,
        subgraph_id: str
    ):
        """
        查询计算详情（支持模糊匹配）
        
        Args:
            db_session: 数据库会话
            job_id: 任务ID
            subgraph_id: 子图ID（支持短名称，如 "LP-02"）
        
        Returns:
            ProcessingCostCalculationDetail 或 None（包含 processing_instructions 属性）
        """
        try:
            from shared.models import ProcessingCostCalculationDetail, Feature
            
            # 1. 先尝试精确匹配
            result = await db_session.execute(
                select(ProcessingCostCalculationDetail)
                .where(
                    ProcessingCostCalculationDetail.subgraph_id == subgraph_id,
                    ProcessingCostCalculationDetail.job_id == job_id
                )
            )
            
            detail = result.scalar_one_or_none()
            
            # 2. 如果精确匹配失败，尝试后缀匹配（支持 UUID_短名称 格式）
            if not detail:
                logger.info(f"🔍 精确匹配失败，尝试后缀匹配: {subgraph_id}")
                result = await db_session.execute(
                    select(ProcessingCostCalculationDetail)
                    .where(
                        ProcessingCostCalculationDetail.subgraph_id.like(f'%_{subgraph_id}'),
                        ProcessingCostCalculationDetail.job_id == job_id
                    )
                )
                
                # 🔑 使用 all() 获取所有匹配结果，然后手动选择
                all_matches = result.scalars().all()
                
                if len(all_matches) == 0:
                    logger.warning(f"⚠️  未找到匹配的子图: {subgraph_id}")
                    detail = None
                elif len(all_matches) == 1:
                    detail = all_matches[0]
                    logger.info(f"✅ 后缀匹配成功: {detail.subgraph_id}")
                else:
                    # 多个匹配结果，选择最短的（最可能是正确的）
                    detail = min(all_matches, key=lambda x: len(x.subgraph_id))
                    logger.warning(f"⚠️  找到 {len(all_matches)} 个匹配结果，选择最短的: {detail.subgraph_id}")
                    logger.debug(f"   所有匹配: {[m.subgraph_id for m in all_matches]}")
            
            # 🆕 3. 如果找到了 detail，尝试查询对应的 processing_instructions
            if detail:
                try:
                    # 使用相同的 subgraph_id 查询 features 表
                    feature_result = await db_session.execute(
                        select(Feature)
                        .where(
                            Feature.subgraph_id == detail.subgraph_id,
                            Feature.job_id == job_id
                        )
                    )
                    feature = feature_result.scalar_one_or_none()
                    
                    if feature and hasattr(feature, 'processing_instructions'):
                        detail.processing_instructions = feature.processing_instructions
                        logger.info(f"✅ 已加载 processing_instructions: {detail.subgraph_id}")
                    else:
                        detail.processing_instructions = None
                        logger.debug(f"📭 未找到 processing_instructions: {detail.subgraph_id}")
                except Exception as e:
                    logger.warning(f"⚠️  查询 processing_instructions 失败: {e}")
                    detail.processing_instructions = None
            
            return detail
        
        except Exception as e:
            logger.error(f"❌ 数据库查询失败: {e}", exc_info=True)
            return None
    
    async def _format_with_llm(
        self,
        job_id: str,  # 🆕 新增参数
        subgraph_id: str,
        calculation_steps: Any,
        user_question: str,
        query_type: Optional[str] = None,
        db_session = None,  # 🆕 新增参数
        processing_instructions: Optional[Any] = None  # 🆕 新增参数
    ) -> str:
        """
        使用 LLM 格式化计算步骤（支持历史对话上下文和加工说明）
        
        Args:
            job_id: 任务ID（用于查询历史消息）
            subgraph_id: 子图ID
            calculation_steps: 计算步骤 JSON
            user_question: 用户的原始问题
            query_type: 查询类型（可选）
            db_session: 数据库会话（用于查询历史）
            processing_instructions: 加工说明 JSON（可选）
        
        Returns:
            LLM 生成的友好回答
        """
        logger.info(f"🤖 使用 LLM 格式化计算详情: {subgraph_id}")
        
        # 解析 JSON（如果是字符串）
        if isinstance(calculation_steps, str):
            steps = json.loads(calculation_steps)
        else:
            steps = calculation_steps
        
        # 如果指定了 query_type，只提取对应的 category
        if query_type:
            filtered_steps = []
            for item in steps:
                category = item.get("category", "")
                
                # 🔴 特殊处理：如果 query_type 是 "nc"，包含所有 NC 相关的 category
                if query_type in ["nc", "NC"]:
                    if category.startswith("nc_") or category == "nc":
                        filtered_steps.append(item)
                # 🔴 特殊处理：如果 query_type 是 "water_mill"，包含所有水磨相关的 category
                elif query_type in ["water_mill", "水磨"]:
                    if category.startswith("water_mill_") or category == "water_mill":
                        filtered_steps.append(item)
                # 🔴 特殊处理：如果 query_type 是 "wire"，包含所有线割相关的 category
                elif query_type in ["wire", "线割"]:
                    if category.startswith("wire_") or category == "wire":
                        filtered_steps.append(item)
                # 普通情况：精确匹配
                elif category == query_type:
                    filtered_steps.append(item)
            
            steps = filtered_steps
            logger.info(f"🔍 query_type={query_type}, 过滤后保留 {len(filtered_steps)} 个 category")
        
        # 动态构建字段说明
        field_glossary = self._build_field_glossary(steps)
        
        # 🆕 构建加工说明部分
        processing_instructions_section = ""
        if processing_instructions:
            try:
                # 解析 processing_instructions（如果是字符串）
                if isinstance(processing_instructions, str):
                    instructions = json.loads(processing_instructions)
                else:
                    instructions = processing_instructions
                
                processing_instructions_section = f"""

## 🆕 加工说明（原始工艺文档）

以下是 {subgraph_id} 的加工说明，包含了所有加工工序的详细描述：

```json
{json.dumps(instructions, ensure_ascii=False, indent=2)}
```

### 加工代码说明（重要！）

加工说明中的代码（如 L, W, M, K 等）对应计算详情中的 "code" 字段：

- **L**: 从加工说明中可以看到具体是什么工序（如"L :2 -Φ8.00割,单+0.008(合销)"）
- **W**: 对应加工说明中的 W 工序（如"W :1 -Φ230.00刀口，割，单+0.06"）
- **M**: 对应加工说明中的 M 工序（如"M :6 -Φ8.5背钻,背攻M10xP1.5"）
- **K**: 对应加工说明中的 K 工序（如导柱孔等）
- **外形割**: 外形轮廓线割

**如果用户问"L 的线长"或"W 的费用"等问题**：
1. 先从加工说明中找到对应代码的定义（如"L :2 -Φ8.00割,单+0.008(合销)"）
2. 🔴 **重要**：从 `wire_base` 类别中找到 `code="L"` 的 `total_length` 字段（这是 L 工序的线长）
3. ⚠️ **不要使用** `wire_total` 类别中的 `wire_length` 或 `slow_wire_length`（那是所有工序的总线长）
4. 结合加工说明和计算数据给出完整、准确的回答

**示例**：
- 用户问："L的线长是多少？"
- ✅ 正确：从 `wire_base` 类别中找 `code="L"` 的 `total_length: 158.8`
- ❌ 错误：使用 `wire_total` 类别中的 `slow_wire_length: 3364.15`（这是所有工序的总和）

**注意**：
- 加工代码（L, W, M 等）是工序代码，**不是视图方向**
- 不要把 L 理解成 side_view（侧视图）
- 不要把 W 理解成 width（宽度）
- 每个代码都有明确的工艺说明，请仔细阅读
- `wire_base` 包含每个工序的详细数据（按 code 分组）
- `wire_total` 包含所有工序的汇总数据（总线长、总费用）
"""
            except Exception as e:
                logger.warning(f"⚠️  解析 processing_instructions 失败: {e}")
                processing_instructions_section = ""
        
        # 🆕 P2: 构建增强的 Prompt（包含复杂数据结构、单位精度、视图对应关系说明）
        prompt = f"""你是一个模具成本计算专家。用户询问了以下问题：

"{user_question}"

以下是 {subgraph_id} 的计算详情数据（JSON格式）：

```json
{json.dumps(steps, ensure_ascii=False, indent=2)}
```

🔴🔴🔴 **最重要的规则（必须第一步执行）** 🔴🔴🔴

**在回答任何问题之前，你必须先执行以下操作：**

1. **列出所有 category**：遍历整个 JSON 数组，列出所有的 "category" 字段值
2. **确认数据存在性**：根据用户问题，确认相关的 category 是否存在
3. **只有在确认 category 不存在后**，才能说"数据未提供"

**示例（NC 相关问题）**：
- 用户问："NC是怎么算的？"
- ❌ 错误做法：直接回答"JSON中未提供nc_z数据"
- ✅ 正确做法：
  1. 先在内部检查所有 category（不要输出这个过程）
  2. 确认：nc_z ✓存在、nc_b ✓存在、nc_c ✓存在、nc_total ✓存在
  3. 然后用业务语言回答："PU-02 的 NC 计算包含基础工时和各面加工时间..."
  4. **注意**：不要在回答中说 "我看到以下 category" 或 "nc_z ✓存在"

🔴 **重要提示**：
- JSON 数据中的 `wire_base` 类别包含了所有线割工序的详细信息
- 每个工序都有一个 `"code"` 字段（如 "G", "L", "W", "Z"）
- 如果用户问某个工序（如 G）的线长，请在 `wire_base` 类别的 `steps` 数组中查找 `"code": "G"` 的对象
- 该对象包含了该工序的所有数据，包括 `total_length`（线长）
- ⚠️ **严禁使用 wire_total 类别中的数据回答单个工序的问题**
- `wire_total` 中的 `wire_length` 和 `slow_wire_length` 是**所有工序的总和**，不是单个工序的线长

🔴 **查询步骤**（必须严格遵守）：

**情况 1：用户问整体计算（如 "DIE-05是怎么算的"）**
- 回答整体成本构成：材料费 + 线割费 + 水磨费 + ... = 总价
- 从 `total` 类别中获取总价信息
- 列出主要费用项目及其金额
- 不要只回答单个工序的详细数据

**情况 2：用户问 NC 计算（如 "NC是怎么算的"）**
🔴 **强制要求：必须先列出所有 category，确认 nc_z、nc_b、nc_c、nc_total 是否存在**

1. ✅ **第一步：列出所有 category（内部检查，不要输出）**
   - 遍历整个 JSON 数组
   - 列出所有 "category" 字段的值
   - **注意**：这一步是内部检查，不要在回答中输出 "我看到以下 category：material, wire_base, ..."
   - 直接进入第二步
   
2. ✅ **第二步：确认 NC 相关 category 存在**
   - 检查是否有 nc_base（基础工时）
   - 检查是否有 nc_z（Z面/主视图）
   - 检查是否有 nc_b（B面/背面）
   - 检查是否有 nc_c（C面/侧面）
   - 检查是否有 nc_total（总费用）
   
3. ✅ **第三步：提取 nc_base 信息**
   - 从 nc_base 类别中找到 nc_base_hours（基础工时）
   
4. ✅ **第四步：提取各面的时间信息**
   - 从 nc_z 类别中找 total_hours（Z面/主视图时间）
   - 从 nc_b 类别中找 total_hours（B面/背面时间）
   - 从 nc_c 类别中找 total_hours（C面/侧面时间）
   - 如果某个面的 category 不存在，才说该面无数据
   
5. ✅ **第五步：提取费用信息**
   - 从 nc_total 类别的 final_fees 中提取各面费用
   - 汇总得到 NC 总费用
   
6. ✅ **第六步：组织回答**
   - 说明基础工时
   - 列出各面的实际工时和费用
   - 说明比较取最大值的逻辑
   - 给出总费用

**情况 3：用户问单个工序（如 "L的线长是多少"）**
1. ✅ 定位到 `wire_base` 类别（不是 wire_total）
2. ✅ 在 `steps` 数组中查找 `"code": "L"` 的对象
3. ✅ 从该对象中提取 `"total_length"` 字段的值
4. ✅ 直接使用该值回答，不要计算或推测
5. ❌ **严禁**使用 `wire_total` 类别中的 `wire_length` 或 `slow_wire_length`

**情况 4：用户问特定类型费用（如 "材料费是多少"）**
- 定位到对应的类别（如 `material`）
- 提取该类别中的费用信息

**🔴 常见错误示例（必须避免）**：
- ❌ 错误：用户问 "L的线长"，回答 3364.15（这是 wire_total 中的总线长）
- ✅ 正确：用户问 "L的线长"，回答 158.8（这是 wire_base 中 code="L" 的 total_length）
- ❌ 错误：用户问 "G的线长"，回答"暂无数据"（明明 wire_base 中有 code="G" 的数据）
- ✅ 正确：用户问 "G的线长"，回答 217.63（这是 wire_base 中 code="G" 的 total_length）
- ❌ 错误：用户问 "NC是怎么算的"，回答"JSON中未提供nc_z数据"（明明有完整的 nc_z category）
- ✅ 正确：用户问 "NC是怎么算的"，先列出所有 category，确认 nc_z、nc_b、nc_c 存在，然后提取数据回答
- ❌ 错误：没有检查完所有 category 就说"数据未提供"
- ✅ 正确：必须遍历整个 JSON 数组，检查所有 category 后才能下结论
- 解释计算过程
{processing_instructions_section}

{field_glossary}

## 🆕 复杂数据结构说明

### 数组类型
- **details**: [{{"code": "工序代码", "value": "时间值(分钟)"}}, ...] - NC 工时详情，每个元素包含工序代码和时间
- **multipliers**: [{{"type": "倍率类型", "multiplier": 倍率值, "description": "说明"}}, ...] - 线割倍率列表
- **cone_details**: [{{"view": "视图", "before_cone": 价格, "after_cone": 价格, "multiplier": 倍率}}, ...] - cone 规则详情
- **side_cut_details**: [{{"view": "视图", "total_length": 线长}}, ...] - 侧割详情
- **items**: ["项目1", "项目2", ...] - 费用项目列表

### 对象类型
- **dimensions**: {{"length_mm": 长度, "width_mm": 宽度, "thickness_mm": 厚度}} - 尺寸信息
- **summary**: {{"jing_xi_hours": 精铣工时, "kai_cu_hours": 开粗工时, "drill_hours": 钻床工时}} - 工时汇总
- **view_totals**: {{"top_view": 价格, "front_view": 价格, "side_view": 价格}} - 各视图总价
- **perimeter_by_view**: {{"top_view": 周长, "front_view": 周长, "side_view": 周长}} - 按视图分组的周长

## 🆕 单位和精度说明

### 单位
- **费用/价格**: 元（人民币）
- **长度**: mm（毫米）
- **重量**: kg（千克）
- **时间**: 小时（注意：NC details 中的 value 字段是**分钟**，需要除以 60 转换为小时）

### 精度
- **费用/价格**: 通常保留 2-4 位小数
- **尺寸**: 通常保留 1-2 位小数
- **时间**: 通常保留 2-4 位小数
- **重量**: 通常保留 3-4 位小数

## 🆕 视图与尺寸对应关系（重要！）

这是理解线割和水磨计算的关键：
- **top_view（俯视图）** → 对应 **thickness_mm（厚度）**
- **front_view（主视图）** → 对应 **width_mm（宽度）**
- **side_view（侧视图）** → 对应 **length_mm（长度）**

例如：如果 top_view 的线长是 1200mm，厚度是 50mm，那么计算时使用的尺寸就是 50mm。

## 🆕 线割相关字段说明（重要！避免混淆）

### 线长 vs 面积（必须区分）
- **total_length**: 总线长（单位：毫米 mm）- 用于线割工序
- **area**: 面积（单位：平方毫米 mm²）- 用于水磨工序
- **🔴 严禁混淆**：线割工序使用的是 `total_length`（线长），不是 `area`（面积）

### 滑块相关字段（特殊规则）
- **slider_angle**: 滑块角度（单位：度）
- 如果 `code` 字段的值为 "滑块"，则应该说"面积"而不是"线长"
  - ✅ 正确：说"滑块工序的总面积为 305 平方毫米"
  - ❌ 错误：说"滑块工序的总线长为 305 毫米"
- 如果 `code` 字段的值为其他（如 L, W, G, M 等），则说"线长"
  - ✅ 正确：说"L 工序的总线长为 158.8 毫米"
  - ❌ 错误：说"L 工序的总面积为 158.8 平方毫米"

### 判断规则（重要！）
```
如果 code == "滑块":
    使用术语：面积、平方毫米
    示例：滑块工序的总面积为 305 平方毫米
否则:
    使用术语：线长、毫米
    示例：L 工序的总线长为 158.8 毫米
```

### 常见错误（必须避免）
- ❌ 错误：对滑块工序说"总线长为 305 毫米"（滑块应该说面积）
- ✅ 正确：对滑块工序说"总面积为 305 平方毫米"
- ❌ 错误：对 L/W/G 等工序说"总面积"（普通线割应该说线长）
- ✅ 正确：对 L/W/G 等工序说"总线长为 XXX 毫米"

## 🆕 NC 计算过程说明（重要！）

### NC 面代码含义（用户常用中文说法）
用户通常会用中文询问，需要将中文映射到对应的面代码：

| 用户说法 | 面代码 | category名称 | 说明 |
|---------|--------|-------------|------|
| 主视图、Z面 | Z | nc_z | 主视图加工 |
| 背面、B面 | B | nc_b | 背面加工 |
| 侧面、侧面正面、C面 | C | nc_c | 侧面正面加工 |
| 侧背、C_B面 | C_B | nc_c_b | 侧背加工 |
| 正面、Z_VIEW面 | Z_VIEW | nc_z_view | 正面加工 |
| 正面的背面、B_VIEW面 | B_VIEW | nc_b_view | 正面的背面加工 |

**重要提示**：
- 用户问"主视图的时间"或"Z面的时间"，都是指 nc_z 类别
- 用户问"背面的费用"或"B面的费用"，都是指 nc_total 中的 nc_b_fee
- 用户问"侧面的时间"或"C面的时间"，都是指 nc_c 类别

### NC 计算流程
1. **nc_base**: 计算 NC 基本时间（模板1小时，零件0.5小时）
2. **nc_z, nc_b, nc_c 等**: 按面代码分别计算各面的 NC 时间
   - 从 metadata 中提取各面的工序数据（details 数组）
   - 每个工序有 code（如 ZXZ, C1, M, 开粗, 半精, 全精）和 value（时间，单位：分钟）
   - 按分类汇总：精铣（半精、全精）、开粗、钻床（其他所有 code）
   - 将分钟转换为小时：total_hours = total_minutes / 60
   - **重要**：nc_z、nc_b、nc_c 等 category 包含了实际的加工时间数据
3. **nc_total**: 计算 NC 总费用
   - 判断工时单价（根据零件尺寸）
   - 与 nc_base_cost 比较，取最大值（如果某面时间为0则跳过比较）
   - 乘以数量得到最终时间
   - 乘以工时单价得到最终费用
   - **重要**：nc_total 中的 final_fees 包含了各面的实际费用

### NC 数据结构示例
```json
{{
  "category": "nc_z",
  "steps": [
    {{
      "step": "计算 Z 面",
      "face_code": "Z",
      "details": [
        {{"code": "ZXZ", "value": 1.52, "category": "钻床"}},
        {{"code": "开粗", "value": 172.20, "category": "开粗"}},
        {{"code": "半精", "value": 14.24, "category": "精铣"}}
      ],
      "summary": {{"精铣": 14.24, "开粗": 172.20, "钻床": 1.52}},
      "total_minutes": 187.96,
      "total_hours": 3.13,
      "formula": "(14.24 + 172.20 + 1.52) / 60 = 3.13"
    }}
  ]
}}
```

### 回答 NC 相关问题的要点
- **如果用户问"NC是怎么算的"**：
  1. 先说明 nc_base（基础工时）
  2. 然后列出各面的实际工时（从 nc_z、nc_b、nc_c 等 category 中获取）
  3. 说明与基础工时比较取最大值的逻辑
  4. 最后给出各面费用和总费用（从 nc_total 的 final_fees 中获取）
- **如果用户问"主视图的时间"或"Z面的时间"**：从 `nc_z` 类别中找 `total_hours` 字段
- **如果用户问"背面的时间"或"B面的时间"**：从 `nc_b` 类别中找 `total_hours` 字段
- **如果用户问"侧面的时间"或"C面的时间"**：从 `nc_c` 类别中找 `total_hours` 字段
- **如果用户问"主视图的费用"或"Z面的费用"**：从 `nc_total` 类别的 `final_fees` 中找 `nc_z_fee`
- **如果用户问"背面的费用"或"B面的费用"**：从 `nc_total` 类别的 `final_fees` 中找 `nc_b_fee`
- **如果用户问"侧面的费用"或"C面的费用"**：从 `nc_total` 类别的 `final_fees` 中找 `nc_c_fee`
- 如果用户问"NC总费用"，从 `nc_total` 类别的 `final_fees` 中汇总所有面的费用
- 注意区分时间（小时）和费用（元）
- **重要**：不要说"JSON中未提供nc_z数据"，要仔细检查所有 category
- **重要**：用户可能用中文说"主视图"、"背面"、"侧面"，要能识别并映射到对应的面代码

---

请根据用户的问题，用友好、易懂的语言解释计算过程。要求：

1. **针对性回答**：重点回答用户关心的部分，不要面面俱到
2. **结构清晰**：使用分点、分段，便于阅读
3. **通俗易懂**：避免技术术语，用口语化表达
4. **包含数据**：引用具体的数值和公式，让用户知道是怎么算出来的
5. **🔴 使用实际字段**：只使用 JSON 数据中实际存在的字段名和值，不要编造或推测不存在的字段
6. **🆕 处理复杂结构**：如果数据中包含数组或对象，请清晰地解释每个元素的含义
7. **🆕 单位转换**：如果涉及 NC 工时，记得将分钟转换为小时
8. **🆕 视图说明**：如果涉及视图相关的计算，请说明视图与尺寸的对应关系
9. **结束方式**：回答完成后，以一句话总结即可，不要提供额外的建议、报价模板、或询问用户是否需要其他帮助

**🔴 关键提示（查询单个工序时）**：
- 如果用户问 "L的线长"，直接从 `wire_base` 类别中找 `code="L"` 的步骤
- **必须逐字复制 JSON 中的实际值**，不要根据常识推测或计算
- 使用该步骤中的实际字段：`total_length`, `original_total_length`, `added_length`, `total_length_note`
- 不要编造字段，如果某个字段不存在，就不要提及
- **示例（必须严格遵守）**：
  ```
  根据 wire_base 类别中的计算步骤，L 的线长是 158.8 mm。
  
  详细分解：
  - 原始线长：150.8 mm (original_total_length)
  - 增加长度：8.0 mm (added_length)
  - 总线长：158.8 mm (total_length)
  - 计算说明：150.8 + (4 × 2.0) = 158.8 (total_length_note)
  
  对应加工说明：4 -Φ12.00割,单+0.01(合销) (instruction)
  ```

**🔴 严格禁止**：
- ❌ 不要根据孔径、数量等信息自己计算线长
- ❌ 不要推测或修改 JSON 中的数值
- ❌ 不要编造 `total_length_note` 的内容
- ✅ 必须直接复制 JSON 中的实际值


注意：
- 不要简单地罗列 JSON 数据，要解释背后的逻辑
- 如果有多个步骤，按逻辑顺序解释
- 用户可能不懂专业术语，请用通俗的语言
- 不要生成"小建议"、"如果你以后要报价"等额外内容
- 不要询问"需要吗？"、"还需要什么帮助？"等互动性问题

🔴🔴🔴 **输出格式要求（非常重要）** 🔴🔴🔴

**严禁在回答中输出技术性代码或字段名**，包括但不限于：
- ❌ 不要输出："我看到以下 category：material, wire_base, nc_z, nc_b, nc_c, nc_total, ..."
- ❌ 不要输出："nc_z ✓存在、nc_b ✓存在、nc_c ✓存在"
- ❌ 不要输出："从 nc_base 类别中找到..."
- ❌ 不要输出："category"、"nc_z"、"wire_base"、"total_hours" 等技术字段名
- ❌ 不要输出："Z面"、"B面"、"C面"、"C_B面"、"Z_VIEW面"、"B_VIEW面" 等面代码

**正确的做法**：
- ✅ 直接用中文描述："根据计算数据，PU-02 的 NC 包含以下几个部分..."
- ✅ 用业务术语："基础工时 1.0小时"（不说 "nc_base_hours"）
- ✅ 用中文说明："主视图加工时间 1.36小时"（不说 "nc_z 的 total_hours" 或 "Z面"）
- ✅ 用通俗语言："主视图"、"背面"、"侧面"（不说 "Z面"、"B面"、"C面"）

**示例对比**：

❌ **错误示例（包含技术代码）**：
```
我看到以下 category：material, wire_base, nc_z, nc_b, nc_c, nc_total

✅ 第一步：确认 NC 相关 category 存在性
nc_base ✓ 存在（已提供）
nc_z ✓ 存在
nc_b ✓ 存在
nc_c ✓ 存在
nc_total ✓ 存在

从 nc_base 类别中找到 nc_base_hours = 1.0小时
从 nc_z 类别中找到 total_hours = 1.36小时
```

✅ **正确示例（用户友好）**：
```
PU-02 的 NC（数控铣削）费用计算如下：

1. 基础工时：1.0小时
   零件尺寸 560mm × 560mm × 64.5mm，判定为模板类零件，基础工时为 1小时

2. 各面实际加工时间：
   - 主视图：1.36小时（81.39分钟）
   - 背面：3.75小时（225.17分钟）
   - 侧面：3.37小时（202.35分钟）

3. 计费逻辑：
   每个面与基础工时比较，取较大值作为计费工时

4. 费用计算（工时单价 60元/小时）：
   - 主视图：1.36 × 60 = 81.6元
   - 背面：3.75 × 60 = 225.0元
   - 侧面：3.37 × 60 = 202.2元
   - NC总费用：508.8元
```

**重要提醒**：
- 你的回答对象是业务人员，不是程序员
- 他们不需要知道数据结构、字段名、category 等技术细节
- 他们只需要知道"是什么"、"怎么算的"、"多少钱"
- 保持回答简洁、专业、易懂

请开始回答："""

        # 🆕 构建消息数组（包含历史对话）
        messages = [
            {
                "role": "system",
                "content": """你是一个模具成本计算专家，擅长用通俗易懂的语言解释复杂的计算过程。

🔴 **核心规则（最高优先级）**：
1. **在回答任何问题之前，必须先列出 JSON 中所有的 category**
2. **只有在确认某个 category 不存在后，才能说"数据未提供"**
3. **绝对不允许在没有检查完所有 category 的情况下说"未提供数据"**

🔴 **线割术语规则（非常重要）**：
- 如果 `code` 字段的值为 "滑块"，必须说"面积"（单位：平方毫米）
  - ✅ 正确："滑块工序的总面积为 305 平方毫米"
  - ❌ 错误："滑块工序的总线长为 305 毫米"
- 如果 `code` 字段的值为其他（如 L, W, G, M 等），必须说"线长"（单位：毫米）
  - ✅ 正确："L 工序的总线长为 158.8 毫米"
  - ❌ 错误："L 工序的总面积为 158.8 平方毫米"

🔴 **输出格式规则（非常重要）**：
1. **严禁输出技术性代码**：不要在回答中出现 "category"、"nc_z"、"wire_base"、"total_hours" 等技术字段名
2. **使用业务语言**：用 "基础工时"、"主视图加工时间"、"主视图费用" 等业务术语（不要说 "Z面"、"B面"、"C面"）
3. **面向业务人员**：你的读者是业务人员，不是程序员，他们不需要知道数据结构
4. **直接回答问题**：不要说 "我看到以下 category"、"从 nc_base 类别中找到"，直接说结果

你的回答要专业、准确、简洁。回答完成后以总结结束，不要提供额外的建议或询问用户是否需要其他帮助。"""
            }
        ]
        
        # 🆕 如果启用了历史记忆，加载历史消息
        if self.use_chat_history and db_session:
            try:
                history_messages = await self._load_chat_history(db_session, job_id)
                messages.extend(history_messages)
                logger.info(f"✅ 加载了 {len(history_messages)} 条历史消息")
            except Exception as e:
                logger.warning(f"⚠️  加载历史消息失败: {e}，继续使用无历史模式")
        
        # 添加当前问题
        messages.append({
            "role": "user",
            "content": prompt
        })

        # 调用 LLM
        try:
            response = await self.http_client.post(
                f"{self.llm_base_url}/chat/completions",
                json={
                    "model": self.llm_model,
                    "messages": messages,  # 🔑 使用包含历史的 messages
                    "temperature": 0.3,
                    "max_tokens": 2000
                },
                headers={
                    "Authorization": f"Bearer {self.llm_api_key}",
                    "Content-Type": "application/json"
                }
            )
            
            response.raise_for_status()
            result = response.json()
            
            llm_response = result["choices"][0]["message"]["content"]
            logger.info(f"✅ LLM 格式化成功，响应长度: {len(llm_response)}")
            
            return llm_response
        
        except httpx.TimeoutException as e:
            logger.error(f"❌ LLM API 请求超时: {e}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ LLM API 返回错误状态: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"❌ LLM 格式化异常: {e}", exc_info=True)
            raise
    
    async def _load_chat_history(
        self,
        db_session,
        job_id: str
    ) -> List[Dict[str, str]]:
        """
        加载聊天历史（用于LLM上下文）
        
        Args:
            db_session: 数据库会话
            job_id: 任务ID（作为 session_id）
        
        Returns:
            消息列表，格式: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
        """
        try:
            # 查询最近的历史消息
            history = await self.chat_history_repo.get_session_history(
                db_session,
                session_id=job_id,
                limit=self.max_history_messages
            )
            
            if not history:
                logger.debug(f"📭 没有找到历史消息: job_id={job_id}")
                return []
            
            # 转换为 LLM 消息格式
            messages = []
            for msg in history:
                role = msg["role"]
                content = msg["content"]
                
                # 只保留 user 和 assistant 消息（跳过 system）
                if role in ["user", "assistant"]:
                    messages.append({
                        "role": role,
                        "content": content
                    })
            
            logger.info(f"📚 加载历史消息: job_id={job_id}, 总数={len(history)}, 有效消息={len(messages)}")
            
            return messages
        
        except Exception as e:
            logger.error(f"❌ 加载历史消息失败: {e}", exc_info=True)
            return []
    
    async def _infer_subgraph_from_history(
        self,
        db_session,
        job_id: str
    ) -> Optional[str]:
        """
        从历史消息中推断 subgraph_id
        
        当用户使用代词（如"那"、"它"、"这个"）时，从最近的历史消息中查找提到的子图ID
        
        优先级：
        1. 最近的用户消息（最高优先级）
        2. 最近的助手消息
        3. 最近的系统消息
        
        Args:
            db_session: 数据库会话
            job_id: 任务ID
        
        Returns:
            推断出的 subgraph_id，如果无法推断返回 None
        """
        try:
            logger.info(f"📚 开始从历史推断子图ID: job_id={job_id}")
            
            # 查询最近的历史消息（使用专门的方法获取最近的消息）
            history = await self.chat_history_repo.get_recent_session_history(
                db_session,
                session_id=job_id,
                limit=50  # 获取最近50条消息
            )
            
            logger.info(f"📊 查询到 {len(history)} 条历史消息")
            
            if not history:
                logger.warning(f"📭 没有历史消息")
                return None
            
            # 打印历史消息（调试用）
            for i, msg in enumerate(history):
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                logger.info(f"  [{i}] {role}: {content[:150]}")  # 增加到150字符
            
            import re
            
            # 子图ID模式
            # 支持的前缀格式：
            # 1. 单字母+数字: U1, U2, B1, B2
            # 2. 双字母: UP, LP, PS, PH, UB, PU, LB, EB, EJ, CV, CJ, CB, GU
            # 3. 三字母: PPS, DIE, CAM, BOL
            # 4. 带数字的: ST1, ST2, ST3, TEMP1, TEMP2, DIE2, PS2, PPS2, PH2, LB2
            # 5. 带后缀的: UP_P, PS_P, DIE_P, UP_JIAT, PS_JIAT, LOW_JIAT, UP_ITEM, PSITEM, LOW_ITEM
            # 6. 特殊: STRIP, CV, CJ, CB
            
            # 构建正则表达式（按优先级从长到短）
            subgraph_prefixes = r'(?:' + '|'.join([
                # 带后缀的（最长，优先匹配）
                r'UP_JIAT', r'PS_JIAT', r'LOW_JIAT',
                r'UP_ITEM', r'PSITEM', r'LOW_ITEM',
                r'DIE2_P', r'PS2_P', r'PPS2_P', r'PH2_P', r'LB2_P',
                r'UP_P', r'UB_P', r'PH_P', r'PU_P', r'PPS_P', r'PS_P', r'DIE_P', r'GU_P', r'LB_P',
                
                # 带数字的前缀
                r'TEMP[12]', r'ST[123]',
                r'DIE2', r'PS2', r'PPS2', r'PH2', r'LB2',
                
                # 特殊前缀
                r'STRIP',
                
                # 三字母
                r'PPS', r'DIE', r'CAM', r'BOL',
                
                # 双字母
                r'UP', r'LP', r'PS', r'PH', r'UB', r'PU', r'LB', r'EB', r'EJ', 
                r'CV', r'CJ', r'CB', r'GU', r'RP', r'CP', r'TP', r'BP', r'SP', r'MP', r'PP',
                
                # 单字母+数字
                r'U[12]', r'B[12]',
            ]) + r')'
            
            # 完整模式：前缀 + 可选分隔符 + (2位数字 或 字母+数字组合)
            # 支持格式：
            # - 标准: UP-01, DIE-03, PS-02
            # - 特殊: PU-BL2, UP-A1, DIE-X3 (字母+数字组合)
            # 注意：不使用 \b 因为在中文环境下不工作（如 "PS-02的计算过程"）
            subgraph_pattern = rf'({subgraph_prefixes}[-_]?(?:\d{{2}}|[A-Z]+\d+))'
            
            # 🆕 优先级 1：从最近的用户消息中查找（最高优先级）
            # 过滤掉系统消息，只看用户消息，并且只看最近的几条
            user_messages = [msg for msg in reversed(history) if msg.get("role") == "user"]
            logger.info(f"🔍 找到 {len(user_messages)} 条用户消息（已过滤系统消息）")
            
            # 只检查最近的3条用户消息（不包括当前消息）
            # 因为当前消息本身可能就是用户刚发的，不应该包含在历史中
            for i, msg in enumerate(user_messages[:3]):  # 减少到3条，更精确
                content = msg.get("content", "")
                logger.info(f"  🔍 [{i}] 尝试匹配用户消息: {content[:100]}")
                matches = re.findall(subgraph_pattern, content, re.IGNORECASE)
                logger.info(f"  📋 匹配结果: {matches}")
                
                if matches:
                    # 保持原始格式，只转大写，不替换下划线
                    subgraph_id = matches[0].upper()
                    logger.info(f"✅ 从最近的用户消息推断出子图: {subgraph_id} (第{i}条)")
                    logger.debug(f"   来源消息: {content[:100]}")
                    return subgraph_id
            
            # 🆕 优先级 2：从最近的助手消息中查找
            assistant_messages = [msg for msg in reversed(history) if msg.get("role") == "assistant"]
            logger.info(f"🔍 找到 {len(assistant_messages)} 条助手消息")
            for msg in assistant_messages[:5]:  # 只看最近5条助手消息
                content = msg.get("content", "")
                logger.info(f"  🔍 尝试匹配助手消息: {content[:100]}")
                matches = re.findall(subgraph_pattern, content, re.IGNORECASE)
                logger.info(f"  📋 匹配结果: {matches}")
                
                if matches:
                    # 保持原始格式，只转大写，不替换下划线
                    subgraph_id = matches[0].upper()
                    logger.info(f"✅ 从最近的助手消息推断出子图: {subgraph_id}")
                    logger.debug(f"   来源消息: {content[:100]}")
                    return subgraph_id
            
            # 🆕 优先级 3：从所有消息中查找（最后的备选）
            for msg in reversed(history):
                content = msg.get("content", "")
                role = msg.get("role", "")
                matches = re.findall(subgraph_pattern, content, re.IGNORECASE)
                
                if matches:
                    # 保持原始格式，只转大写，不替换下划线
                    subgraph_id = matches[0].upper()
                    logger.info(f"✅ 从历史消息推断出子图: {subgraph_id} (role={role})")
                    logger.debug(f"   来源消息: {content[:100]}")
                    return subgraph_id
            
            logger.warning(f"⚠️  历史消息中未找到子图ID")
            return None
        
        except Exception as e:
            logger.error(f"❌ 推断子图ID失败: {e}", exc_info=True)
            return None
    
    def _build_field_glossary(self, calculation_steps: Any) -> str:
        """
        根据 calculation_steps 中实际出现的字段，动态构建字段说明
        
        Args:
            calculation_steps: 计算步骤 JSON
        
        Returns:
            字段说明文本
        """
        # 完整的字段说明字典（基于文档）
        field_glossary = {
            # Category 类型
            "weight": "重量计算",
            "material": "材料费计算",
            "heat": "热处理费计算",
            "wire_base": "线割基础加工费",
            "wire_special": "线割特殊工艺费",
            "wire_speci": "线割特殊工艺费",  # wire_special 的别名
            "nc_base": "NC基本费用",
            "nc_roughing": "NC开粗费用",
            "nc_milling": "NC精铣费用",
            "nc_drilling": "NC钻床费用",
            "water_mill_high": "水磨高度费",
            "water_mill_long_strip": "水磨长条费",
            "water_mill_chamfer": "水磨倒角费",
            "add_auto_material": "自找料额外费用",
            "standard": "线割标准基本费计算",  # 更新为更准确的说明
            "tooth_hole_time": "牙孔时间费用",  # 🆕 P0
            "wire_standard": "线割标准基本费",  # 🆕 P0
            "total": "最终总价计算",  # 🆕 P0
            "wire_total": "线割总价计算",  # 🆕 UPDATE (2026-02-03)
            # 🆕 P2 水磨相关 Category
            "water_mill_thread_ends": "水磨螺纹端",
            "water_mill_hanging_table": "水磨挂台",
            "water_mill_bevel": "水磨斜面",
            "water_mill_oil_tank": "水磨油槽",
            "water_mill_high_cost": "水磨高费用",
            "water_mill_plate": "水磨板",
            "water_mill_component": "水磨零件",
            "water_mill_grinding": "水磨磨削",
            
            # 常用字段
            "step": "步骤名称",
            "formula": "计算公式",
            "note": "说明信息",
            "reason": "判断依据",
            "description": "描述",
            
            # 尺寸相关
            "length_mm": "长度(mm)",
            "width_mm": "宽度(mm)",
            "thickness_mm": "厚度(mm)",
            "dimension": "实际计算尺寸(mm，最小15mm)",
            "original_dimension": "原始尺寸(mm)",
            "max_dimension": "最大尺寸(mm)",
            "max_length": "最长边(mm)",
            "dimensions": "尺寸信息对象",
            "template_threshold": "模板阈值(mm，默认400)",
            
            # 费用相关
            "unit_price": "单价",
            "cost_single": "单件费用(元)",
            "cost_total": "总费用(元)",
            "material_cost": "材料费(元)",
            "heat_treatment_cost": "热处理费(元)",
            "basic_processing_cost": "基础加工费(元)",
            "special_base_cost": "特殊工艺费(元)",
            "material_additional_cost": "额外材料费(元)",
            "nc_roughing_cost": "开粗费用(元)",
            "nc_milling_cost": "精铣费用(元)",
            "nc_drilling_cost": "钻床费用(元)",
            "long_strip_cost": "长条费(小时)",
            "base_price": "基础价格(元)",
            "final_price": "最终价格(元)",
            "amount": "费用金额(元)",
            "fee_type": "费用类型",
            
            # 工时相关
            "nc_base_hours": "NC基本工时(小时)",
            "kai_cu_hours": "开粗工时(小时)",
            "jing_xi_hours": "精铣工时(小时)",
            "drill_hours": "钻床工时(小时)",
            "hours": "工时(小时)",
            
            # 材料相关
            "material": "材料名称",
            "matched_sub_category": "匹配到的材料子类别",
            "match_note": "匹配说明",
            "weight": "重量(kg)",
            
            # 类型判断
            "part_type": "零件类型 (template=模板, component=零件)",  # 更新准确性
            "mill_type": "水磨类型 (s_water_mill=小磨床, l_water_mill=大水磨)",
            "wire_type": "线割类型 (slow=慢丝, medium=中丝, fast=快丝)",  # 添加 medium
            "is_template": "是否为模板",
            "has_auto_material": "是否自找料",
            "needs_heat_treatment": "是否需要热处理",
            "has_side_cut": "是否有侧割",
            "has_material_preparation": "是否有备料",
            
            # 线割相关
            "view": "视图 (top_view=俯视图对应厚度, front_view=主视图对应宽度, side_view=侧视图对应长度)",
            "cone": "是否带锥加工 (t=是需要×1.5倍率, f=否)",
            "slider_angle": "滑块角度(度，如果不为0则不乘尺寸)",
            "code": "加工代码 (如M=铣削, L=钻孔, ZXZ=中心钻, 滑块=滑块加工)",
            "instruction": "加工说明",
            "original_total_length": "原始线长(mm)",
            "total_length": "总线长(mm) - 注意：当code='滑块'时应称为'面积'",
            "total_length_note": "总线长计算说明",
            "area_num": "区域数量",
            "added_length": "因area_num增加的线长(mm)",
            "tooth_hole_length": "牙孔周长(mm)",
            "dimension_name": "尺寸名称 (thickness_mm/width_mm/length_mm)",
            "dimension_note": "尺寸说明",
            "calculation_note": "计算说明(常规计算/slider_angle不为空不乘尺寸)",
            "multipliers": "倍率列表 (extra_thick=超厚倍率, slider=斜度倍率)",
            "calculation_formula": "计算公式(不含倍率)",
            "complete_formula": "完整计算公式(含倍率)",
            "base_calculation": "基础价格计算公式",
            "wire_process_note": "线割工艺说明",
            "side_cut_details": "侧割详情数组",
            "wire_process": "工艺代码",  # 🆕 P0 线割标准
            "boring_num": "孔数",  # 🆕 P0
            "hole_cost": "孔类费(元)",  # 🆕 P0
            "base_fee": "基本费(元)",  # 🆕 P0
            "standard_base_cost": "标准基本费(元)",  # 🆕 P0
            "view_dimension_note": "视图与尺寸对应关系说明",  # 🆕 P1
            
            # 牙孔相关 (🆕 P0)
            "size": "孔尺寸",
            "number": "孔数量",
            "is_through": "是否通孔",
            "hole_type": "孔类型(通孔/盲孔)",
            "set_screw": "是否使用止付螺丝",
            "size_number": "孔尺寸数字",
            "time_per_hole": "每个孔的时间(小时)",
            "total_time": "总时间(小时)",
            "hourly_rate": "小时费率(元/小时)",
            "discharge_cost": "放电费用(元)",
            "diameter": "直径(毫米)",
            "perimeter": "周长(毫米)",
            "price_source": "价格来源(screw/stop_screw)",
            "total_discharge_cost": "总放电费用(元)",
            "total_perimeter": "总周长(毫米)",
            "perimeter_by_view": "按视图分组的周长",
            
            # 总价相关 (🆕 P0)
            "large_grinding_cost": "大水磨费用(元)",
            "small_grinding_cost": "小磨床费用(元)",
            "slow_wire_cost": "慢丝费用(元)",
            "slow_wire_side_cost": "慢丝侧割费用(元)",
            "mid_wire_cost": "中丝费用(元)",
            "fast_wire_cost": "快丝费用(元)",
            "edm_cost": "EDM费用(元)",
            "drilling_cost": "钻床费用(元)",
            "processing_cost_total": "加工成本总计(元)",
            "total_cost": "总价(元)",
            "items": "包含的项目数组",
            
            # 线割总价相关 (🆕 UPDATE 2026-02-03)
            "wire_cost_base": "线割基础费用(元)",
            "wire_cost_per_unit": "线割单价(元)",
            "slow_wire_length": "慢丝长度(毫米)",
            "mid_wire_length": "中丝长度(毫米)",
            "fast_wire_length": "快丝长度(毫米)",
            "material_unit_price": "材料单价(元/kg)",
            "heat_treatment_unit_price": "热处理单价(元/kg)",
            "wire_length": "线割总长度(毫米)",
            "selected": "选择的费用类型",
            "weight_kg": "总重量(千克)",
            "material_cost_total": "材料费总价(元)",
            "heat_treatment_cost_total": "热处理费总价(元)",
            "formulas": "计算公式对象",
            
            # 密度相关 (🆕 UPDATE 2026-02-03)
            "matched_material": "匹配到的材料名称",
            "density": "密度值",
            
            # 小磨床相关字段 (🆕 UPDATE 2026-02-03 V3)
            "thread_ends_count": "线头数量",
            "thread_ends_cost": "线头费用(元)",
            "hanging_table_count": "挂台数量",
            "hanging_table_cost": "挂台费用(元)",
            "chamfer_type": "倒角类型(c1_c2/c3_c5/r1_r2/r3_r5)",
            "count": "数量",
            "chamfer_costs": "各类倒角费用明细(对象)",
            "total_chamfer_cost": "倒角总费用(元)",
            "bevel_value": "斜面值",
            "price_rule": "价格规则",
            "bevel_details": "各个斜面的详情(数组)",
            "total_bevel_cost": "斜面总费用(元)",
            "oil_tank_count": "油槽数量",
            "oil_tank_cost": "油槽费用(元)",
            "material_part_code": "备料零件编号",
            "material_thickness": "备料零件厚度(mm)",
            "current_thickness": "当前零件厚度(mm)",
            "thickness_diff": "厚度差异(mm)",
            "high_cost": "高度费用(元)",
            
            # 大水磨相关字段 (🆕 UPDATE 2026-02-03 V3)
            "area": "面积(mm²)",
            "divisor": "除数(mm²)",
            "plate_cost": "板费用(元)",
            "price_type": "价格类型",
            "range": "价格区间",
            "long_strip_cost": "长条费用(小时/件)",
            "grinding": "研磨面数(4或6)",
            "max_length_width": "长宽最大值(mm)",
            "component_cost": "零件费用(元)",
            
            # NC 时间相关 (🆕 P1)
            "classification_rules": "分类规则",
            "value": "时间值(分钟)",
            "face_code": "面代码(Z=主视图/B=背面/C=侧面正面/C_B=侧背/Z_VIEW=正面/B_VIEW=正面的背面)",
            "total_minutes": "总时间(分钟)",
            "total_hours": "总时间(小时)",
            "face_costs": "各面时间(小时)",
            "nc_z_cost": "Z面(主视图)时间(小时)",
            "nc_b_cost": "B面(背面)时间(小时)",
            "nc_c_cost": "C面(侧面正面)时间(小时)",
            "nc_c_b_cost": "C_B面(侧背)时间(小时)",
            "nc_z_view_cost": "Z_VIEW面(正面)时间(小时)",
            "nc_b_view_cost": "B_VIEW面(正面的背面)时间(小时)",
            
            # NC 总费用相关 (🆕 UPDATE 2026-02-07)
            "nc_base_cost": "NC基本时间(小时)",
            "comparisons": "时间比较结果",
            "final_times": "最终时间(小时)",
            "final_fees": "最终费用(元)",
            "nc_z_time": "Z面(主视图)时间(小时)",
            "nc_b_time": "B面(背面)时间(小时)",
            "nc_c_time": "C面(侧面正面)时间(小时)",
            "nc_c_b_time": "C_B面(侧背)时间(小时)",
            "nc_z_view_time": "Z_VIEW面(正面)时间(小时)",
            "nc_b_view_time": "B_VIEW面(正面的背面)时间(小时)",
            "nc_z_fee": "Z面(主视图)费用(元)",
            "nc_b_fee": "B面(背面)费用(元)",
            "nc_c_fee": "C面(侧面正面)费用(元)",
            "nc_c_b_fee": "C_B面(侧背)费用(元)",
            "nc_z_view_fee": "Z_VIEW面(正面)费用(元)",
            "nc_b_view_fee": "B_VIEW面(正面的背面)费用(元)",
            
            # 价格加权相关 (🆕 UPDATE 2026-02-07)
            "weight_price": "加权价格(元)",
            "matched_range": "匹配的重量范围",
            "rule_price": "规则价格系数",
            "sub_category": "规则子类别",
            "missing_fields": "缺少的字段列表",
            "status": "状态(success/failed)",
            
            # 其他
            "quantity": "数量",
            "unit": "单位",
            "range": "范围",
            "threshold": "阈值",
            "details": "详情数组 (包含各个code的工时)",
            "summary": "汇总信息对象 (包含各类工时总计)",
            "view_totals": "各视图的总价对象",
            "view_totals_after_cone": "应用cone规则后各视图的总价",
            "cone_details": "cone规则详情数组",
            "before_cone": "应用cone前的价格",
            "after_cone": "应用cone后的价格",
            "multiplier": "倍率",
            "formula_single": "单件计算公式",
            "formula_total": "总费用计算公式",
        }
        
        # 提取 JSON 中实际出现的字段
        used_fields = set()
        
        def extract_fields(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    used_fields.add(key)
                    extract_fields(value)
            elif isinstance(obj, list):
                for item in obj:
                    extract_fields(item)
        
        extract_fields(calculation_steps)
        
        # 构建字段说明
        glossary_lines = ["## 字段说明"]
        
        # 优先显示 category（如果存在）
        category_fields = [
            "weight", "material", "heat", "wire_base", "wire_special", "wire_speci",
            "nc_base", "nc_z", "nc_b", "nc_c", "nc_c_b", "nc_z_view", "nc_b_view",  # 🆕 UPDATE 2026-02-07: 添加 NC 各面
            "nc_total",  # 🆕 UPDATE 2026-02-07: 添加 NC 总费用
            "nc_roughing", "nc_milling", "nc_drilling",
            "water_mill_high", "water_mill_long_strip", "water_mill_chamfer",
            "add_auto_material", "standard",
            "tooth_hole_time", "wire_standard", "total",  # 🆕 P0
            "wire_total",  # 🆕 UPDATE (2026-02-03)
            # 🆕 P2 水磨相关
            "water_mill_thread_ends", "water_mill_hanging_table", "water_mill_bevel",
            "water_mill_oil_tank", "water_mill_high_cost", "water_mill_plate",
            "water_mill_component", "water_mill_grinding",
            "weight_price",  # 🆕 UPDATE 2026-02-07: 添加价格加权
        ]
        
        found_categories = [f for f in category_fields if f in used_fields]
        if found_categories:
            glossary_lines.append("\n**计算类别 (category):**")
            for field in found_categories:
                glossary_lines.append(f"  - {field}: {field_glossary.get(field, field)}")
        
        # 其他重要字段（按类别分组）
        important_groups = {
            "尺寸相关": ["length_mm", "width_mm", "thickness_mm", "dimension", "max_dimension", "max_length"],
            "费用相关": ["unit_price", "cost_single", "cost_total", "material_cost", "heat_treatment_cost", 
                       "basic_processing_cost", "special_base_cost", "final_price", "base_price",
                       "discharge_cost", "hole_cost", "standard_base_cost", "processing_cost_total", "total_cost",
                       "wire_cost_base", "wire_cost_per_unit", "material_cost_total", "heat_treatment_cost_total",
                       "weight_price"],  # 🆕 UPDATE 2026-02-07: 添加 weight_price
            "工时相关": ["nc_base_hours", "kai_cu_hours", "jing_xi_hours", "drill_hours", "time_per_hole", "total_time",
                       "nc_base_cost", "total_minutes", "total_hours",  # 🆕 UPDATE 2026-02-07: 添加 NC 时间字段
                       "nc_z_time", "nc_b_time", "nc_c_time", "nc_c_b_time", "nc_z_view_time", "nc_b_view_time",
                       "nc_z_fee", "nc_b_fee", "nc_c_fee", "nc_c_b_fee", "nc_z_view_fee", "nc_b_view_fee"],  # 🆕 UPDATE 2026-02-07
            "类型判断": ["part_type", "mill_type", "wire_type", "is_template", "has_auto_material", 
                       "needs_heat_treatment", "has_side_cut", "is_through", "hole_type"],  # 🆕 P0
            "线割相关": ["view", "cone", "slider_angle", "code", "instruction", "total_length", "original_total_length",
                       "area_num", "added_length", "tooth_hole_length", "total_length_note", "dimension", "original_dimension",
                       "dimension_name", "dimension_note", "view_dimension_note", "calculation_note", "unit_price",
                       "base_calculation", "base_price", "multipliers", "calculation_formula", "complete_formula", "final_price",
                       "wire_process", "boring_num", "wire_length", "slow_wire_length", "mid_wire_length", "fast_wire_length"],  # 🆕 UPDATE
            "牙孔相关": ["size", "number", "diameter", "perimeter", "total_discharge_cost", "total_perimeter"],  # 🆕 P0
            "密度相关": ["matched_material", "density"],  # 🆕 UPDATE (2026-02-03)
            "水磨相关": [  # 🆕 UPDATE (2026-02-03 V3)
                # 小磨床
                "thread_ends_count", "thread_ends_cost",
                "hanging_table_count", "hanging_table_cost",
                "chamfer_type", "total_chamfer_cost",
                "bevel_value", "total_bevel_cost",
                "oil_tank_count", "oil_tank_cost",
                "high_cost", "thickness_diff",
                # 大水磨
                "plate_cost", "long_strip_cost", "component_cost",
                "grinding", "mill_type", "area", "max_length"
            ],
            "NC相关": [  # 🆕 UPDATE 2026-02-07: 新增 NC 相关分组
                "face_code", "face_costs", "comparisons", "final_times", "final_fees",
                "nc_z_cost", "nc_b_cost", "nc_c_cost", "nc_c_b_cost", "nc_z_view_cost", "nc_b_view_cost"
            ],
            "价格加权相关": [  # 🆕 UPDATE 2026-02-07: 新增价格加权分组
                "matched_range", "rule_price", "sub_category", "missing_fields", "status"
            ],
        }
        
        for group_name, group_fields in important_groups.items():
            found_fields = [f for f in group_fields if f in used_fields]
            if found_fields:
                glossary_lines.append(f"\n**{group_name}:**")
                for field in found_fields:
                    if field in field_glossary:
                        glossary_lines.append(f"  - {field}: {field_glossary[field]}")
        
        # 其他字段
        other_fields = sorted(used_fields - set(category_fields) - 
                            set([f for group in important_groups.values() for f in group]))
        if other_fields:
            glossary_lines.append("\n**其他字段:**")
            for field in other_fields[:20]:  # 最多显示20个其他字段
                if field in field_glossary:
                    glossary_lines.append(f"  - {field}: {field_glossary[field]}")
        
        return "\n".join(glossary_lines)
    
    async def close(self):
        """关闭 HTTP 客户端"""
        await self.http_client.aclose()
        logger.info("✅ QueryDetailsHandler 已关闭")
    
    def _format_calculation_steps(
        self,
        subgraph_id: str,
        calculation_steps: Any
    ) -> str:
        """
        格式化计算步骤为友好的文本
        
        Args:
            subgraph_id: 子图ID
            calculation_steps: 计算步骤 JSON（可能是字符串或列表）
        
        Returns:
            格式化后的文本
        """
        try:
            # 如果是字符串，先解析为 JSON
            if isinstance(calculation_steps, str):
                steps = json.loads(calculation_steps)
            else:
                steps = calculation_steps
            
            if not steps:
                return f"{subgraph_id} 暂无计算详情"
            
            lines = [f"{subgraph_id} 的成本计算详情：\n"]
            
            # 按 category 分类处理
            category_map = {
                "weight": "重量计算",
                "material": "材料费计算",
                "heat": "热处理费计算",
                "wire_base": "线割基础加工费",
                "wire_special": "线割特殊工艺费",
                "wire_speci": "线割特殊工艺费",  # 别名
                "add_auto_material": "自找料判断",
                "standard": "线割标准基本费计算",
                "tooth_hole_time": "牙孔时间费用",  # 🆕 P0
                "wire_standard": "线割标准基本费",  # 🆕 P0
                "total": "最终总价计算",  # 🆕 P0
                "wire_total": "线割总价计算",  # 🆕 UPDATE (2026-02-03)
                "nc_base": "NC基本时间",  # 🆕 UPDATE 2026-02-07
                "nc_z": "NC Z面时间",  # � UPDATE 2026-02-07
                "nc_b": "NC B面时间",  # 🆕 UPDATE 2026-02-07
                "nc_c": "NC C面时间",  # 🆕 UPDATE 2026-02-07
                "nc_c_b": "NC C_B面时间",  # 🆕 UPDATE 2026-02-07
                "nc_z_view": "NC Z_VIEW面时间",  # 🆕 UPDATE 2026-02-07
                "nc_b_view": "NC B_VIEW面时间",  # 🆕 UPDATE 2026-02-07
                "nc_total": "NC总费用计算",  # 🆕 UPDATE 2026-02-07
                "nc_roughing": "NC开粗费用",  # 🆕 P0
                "nc_milling": "NC精铣费用",  # 🆕 P0
                "nc_drilling": "NC钻床费用",  # 🆕 P0
                # 🆕 P2 水磨相关
                "water_mill_high": "水磨高度费",
                "water_mill_long_strip": "水磨长条费",
                "water_mill_chamfer": "水磨倒角费",
                "water_mill_thread_ends": "水磨螺纹端",
                "water_mill_hanging_table": "水磨挂台",
                "water_mill_bevel": "水磨斜面",
                "water_mill_oil_tank": "水磨油槽",
                "water_mill_high_cost": "水磨高费用",
                "water_mill_plate": "水磨板",
                "water_mill_component": "水磨零件",
                "water_mill_grinding": "水磨磨削",
                "weight_price": "价格加权计算",  # 🆕 UPDATE 2026-02-07
            }
            
            for item in steps:
                category = item.get("category", "unknown")
                category_name = category_map.get(category, f"未知类型({category})")
                
                lines.append(f"\n【{category_name}】")
                
                # 遍历每个步骤
                for step in item.get("steps", []):
                    step_desc = step.get("step", "")
                    
                    # 根据不同的字段格式化输出
                    if "formula" in step:
                        # 有公式的步骤
                        result_key = self._find_result_key(step)
                        if result_key:
                            lines.append(f"  {step_desc}: {step[result_key]}")
                            lines.append(f"    公式: {step['formula']}")
                        else:
                            lines.append(f"  {step_desc}")
                            lines.append(f"    公式: {step['formula']}")
                    
                    elif "note" in step or "reason" in step:
                        # 有说明的步骤
                        note = step.get("note") or step.get("reason")
                        lines.append(f"  {step_desc}: {note}")
                    
                    elif category == "wire_base" and "code" in step:
                        # 线割基础加工的详细步骤
                        code = step.get("code")
                        instruction = step.get("instruction", "")
                        final_price = step.get("final_price", 0)
                        complete_formula = step.get("complete_formula", "")
                        
                        lines.append(f"  [{code}] {instruction}")
                        lines.append(f"    费用: {final_price:.2f} 元")
                        if complete_formula:
                            lines.append(f"    计算: {complete_formula}")
                    
                    elif step_desc:
                        # 普通步骤，显示关键信息
                        lines.append(f"  {step_desc}")
                        
                        # 显示重要的结果字段
                        important_keys = [
                            'weight', 'material_cost', 'heat_treatment_cost',
                            'basic_processing_cost', 'special_base_cost',
                            'material_additional_cost', 'unit_price', 'matched_sub_category',
                            # 🆕 UPDATE (2026-02-03 V3) 水磨相关
                            'thread_ends_count', 'thread_ends_cost',
                            'hanging_table_count', 'hanging_table_cost',
                            'total_chamfer_cost', 'chamfer_type',
                            'total_bevel_cost', 'bevel_value',
                            'oil_tank_count', 'oil_tank_cost',
                            'high_cost', 'thickness_diff',
                            'plate_cost', 'area',
                            'long_strip_cost', 'max_length',
                            'component_cost', 'grinding',
                            'mill_type', 'has_material_preparation',
                            # 🆕 UPDATE 2026-02-07: NC 相关
                            'face_code', 'total_minutes', 'total_hours', 'face_costs',
                            'nc_base_cost', 'comparisons', 'final_times', 'final_fees',
                            'nc_z_time', 'nc_b_time', 'nc_c_time',
                            # 🆕 UPDATE 2026-02-07: 价格加权相关
                            'weight_price', 'matched_range', 'rule_price', 'status',
                        ]
                        
                        for key in important_keys:
                            if key in step:
                                value = step[key]
                                key_name = self._translate_key(key)
                                if isinstance(value, (int, float)):
                                    lines.append(f"    {key_name}: {value}")
                                else:
                                    lines.append(f"    {key_name}: {value}")
            
            return "\n".join(lines)
        
        except Exception as e:
            logger.error(f"❌ 格式化计算步骤失败: {e}", exc_info=True)
            return f"{subgraph_id} 的计算详情格式化失败：{str(e)}"
    
    def _find_result_key(self, step: Dict[str, Any]) -> Optional[str]:
        """
        查找步骤中的结果字段
        
        Args:
            step: 步骤字典
        
        Returns:
            结果字段名，如果没有返回 None
        """
        result_keys = [
            'weight', 'material_cost', 'heat_treatment_cost',
            'basic_processing_cost', 'special_base_cost',
            'material_additional_cost',
            # 🆕 P1 扩展结果字段
            'discharge_cost', 'total_discharge_cost', 'hole_cost',
            'standard_base_cost', 'nc_roughing_cost', 'nc_milling_cost',
            'nc_drilling_cost', 'processing_cost_total', 'total_cost',
            # 🆕 UPDATE (2026-02-03) wire_total 相关
            'wire_cost_base', 'wire_cost_per_unit',
            'material_cost_total', 'heat_treatment_cost_total',
            # 🆕 UPDATE (2026-02-03 V3) 水磨相关结果字段
            'thread_ends_cost', 'hanging_table_cost', 'total_chamfer_cost',
            'total_bevel_cost', 'oil_tank_cost', 'high_cost',
            'plate_cost', 'long_strip_cost', 'component_cost',
            # 🆕 UPDATE 2026-02-07: NC 相关结果字段
            'nc_base_cost', 'total_hours', 'nc_z_time', 'nc_b_time', 'nc_c_time',
            'nc_c_b_time', 'nc_z_view_time', 'nc_b_view_time',
            'nc_z_fee', 'nc_b_fee', 'nc_c_fee', 'nc_c_b_fee', 'nc_z_view_fee', 'nc_b_view_fee',
            # 🆕 UPDATE 2026-02-07: 价格加权结果字段
            'weight_price',
        ]
        
        for key in result_keys:
            if key in step:
                return key
        
        return None
    
    def _translate_key(self, key: str) -> str:
        """
        翻译字段名为中文
        
        Args:
            key: 英文字段名
        
        Returns:
            中文字段名
        """
        translations = {
            'weight': '重量(kg)',
            'material_cost': '材料费(元)',
            'heat_treatment_cost': '热处理费(元)',
            'basic_processing_cost': '基础加工费(元)',
            'special_base_cost': '特殊工艺费(元)',
            'material_additional_cost': '额外材料费(元)',
            'unit_price': '单价',
            'matched_sub_category': '匹配材料',
            # 🆕 P1 扩展翻译
            'discharge_cost': '放电费用(元)',
            'hole_cost': '孔类费(元)',
            'perimeter': '周长(mm)',
            'total_discharge_cost': '总放电费用(元)',
            'nc_base_hours': 'NC基本工时(小时)',
            'kai_cu_hours': '开粗工时(小时)',
            'jing_xi_hours': '精铣工时(小时)',
            'drill_hours': '钻床工时(小时)',
            'nc_roughing_cost': 'NC开粗费用(元)',
            'nc_milling_cost': 'NC精铣费用(元)',
            'nc_drilling_cost': 'NC钻床费用(元)',
            'wire_process': '工艺代码',
            'boring_num': '孔数',
            'standard_base_cost': '标准基本费(元)',
            'total_length': '总线长(mm)',
            'dimension': '实际尺寸(mm)',
            'base_price': '基础价格(元)',
            'final_price': '最终价格(元)',
            'processing_cost_total': '加工成本总计(元)',
            'total_cost': '总价(元)',
            'part_type': '零件类型',
            'has_auto_material': '是否自找料',
            'has_side_cut': '是否有侧割',
            'material': '材料名称',
            'wire_type': '线割类型',
            'is_template': '是否为模板',
            'needs_heat_treatment': '是否需要热处理',
            # 🆕 UPDATE (2026-02-03) wire_total 相关
            'wire_cost_base': '线割基础费用(元)',
            'wire_cost_per_unit': '线割单价(元)',
            'wire_length': '线割总长度(mm)',
            'slow_wire_length': '慢丝长度(mm)',
            'mid_wire_length': '中丝长度(mm)',
            'fast_wire_length': '快丝长度(mm)',
            'material_unit_price': '材料单价(元/kg)',
            'heat_treatment_unit_price': '热处理单价(元/kg)',
            'weight_kg': '总重量(kg)',
            'material_cost_total': '材料费总价(元)',
            'heat_treatment_cost_total': '热处理费总价(元)',
            'selected': '选择的费用类型',
            # 🆕 UPDATE (2026-02-03) 密度相关
            'matched_material': '匹配到的材料名称',
            'density': '密度值',
            # 🆕 UPDATE (2026-02-03 V3) 小磨床相关
            'thread_ends_count': '线头数量',
            'thread_ends_cost': '线头费用(元)',
            'hanging_table_count': '挂台数量',
            'hanging_table_cost': '挂台费用(元)',
            'chamfer_type': '倒角类型',
            'chamfer_costs': '各类倒角费用明细',
            'total_chamfer_cost': '倒角总费用(元)',
            'bevel_value': '斜面值',
            'price_rule': '价格规则',
            'bevel_details': '各个斜面的详情',
            'total_bevel_cost': '斜面总费用(元)',
            'oil_tank_count': '油槽数量',
            'oil_tank_cost': '油槽费用(元)',
            'material_part_code': '备料零件编号',
            'material_thickness': '备料零件厚度(mm)',
            'current_thickness': '当前零件厚度(mm)',
            'thickness_diff': '厚度差异(mm)',
            'high_cost': '高度费用(元)',
            # 🆕 UPDATE (2026-02-03 V3) 大水磨相关
            'area': '面积(mm²)',
            'divisor': '除数(mm²)',
            'plate_cost': '板费用(元)',
            'price_type': '价格类型',
            'range': '价格区间',
            'long_strip_cost': '长条费用(小时/件)',
            'grinding': '研磨面数',
            'max_length_width': '长宽最大值(mm)',
            'component_cost': '零件费用(元)',
            # 🆕 UPDATE 2026-02-07: NC 相关
            'face_code': '面代码(Z=主视图/B=背面/C=侧面正面/C_B=侧背/Z_VIEW=正面/B_VIEW=正面的背面)',
            'total_minutes': '总时间(分钟)',
            'total_hours': '总时间(小时)',
            'face_costs': '各面时间(小时)',
            'nc_base_cost': 'NC基本时间(小时)',
            'comparisons': '时间比较结果',
            'final_times': '最终时间(小时)',
            'final_fees': '最终费用(元)',
            'nc_z_time': 'Z面(主视图)时间(小时)',
            'nc_b_time': 'B面(背面)时间(小时)',
            'nc_c_time': 'C面(侧面正面)时间(小时)',
            'nc_c_b_time': 'C_B面(侧背)时间(小时)',
            'nc_z_view_time': 'Z_VIEW面(正面)时间(小时)',
            'nc_b_view_time': 'B_VIEW面(正面的背面)时间(小时)',
            'nc_z_fee': 'Z面(主视图)费用(元)',
            'nc_b_fee': 'B面(背面)费用(元)',
            'nc_c_fee': 'C面(侧面正面)费用(元)',
            'nc_c_b_fee': 'C_B面(侧背)费用(元)',
            'nc_z_view_fee': 'Z_VIEW面(正面)费用(元)',
            'nc_b_view_fee': 'B_VIEW面(正面的背面)费用(元)',
            # 🆕 UPDATE 2026-02-07: 价格加权相关
            'weight_price': '加权价格(元)',
            'matched_range': '匹配的重量范围',
            'rule_price': '规则价格系数',
            'sub_category': '规则子类别',
            'status': '状态',
        }
        
        return translations.get(key, key)
    
    def _format_specific_category(
        self,
        subgraph_id: str,
        calculation_steps: Any,
        query_type: str
    ) -> str:
        """
        格式化特定类型的计算步骤
        
        支持的查询类型:
        - weight: 重量
        - material: 材料费
        - heat: 热处理费
        - wire_base: 线割基础加工费
        - wire_special: 线割特殊工艺费
        - add_auto_material: 自找料
        - standard: 标准费
        
        Args:
            subgraph_id: 子图ID
            calculation_steps: 计算步骤 JSON
            query_type: 查询类型
        
        Returns:
            格式化后的文本
        """
        try:
            # 解析 JSON
            if isinstance(calculation_steps, str):
                steps = json.loads(calculation_steps)
            else:
                steps = calculation_steps
            
            # 查找对应的 category
            target_item = None
            for item in steps:
                if item.get("category") == query_type:
                    target_item = item
                    break
            
            if not target_item:
                return f"{subgraph_id} 没有 {query_type} 相关的计算详情"
            
            # 格式化该类型的详情
            category_map = {
                "weight": "重量计算",
                "material": "材料费计算",
                "heat": "热处理费计算",
                "wire_base": "线割基础加工费",
                "wire_special": "线割特殊工艺费",
                "wire_speci": "线割特殊工艺费",  # 别名
                "add_auto_material": "自找料判断",
                "standard": "线割标准基本费计算",
                "tooth_hole_time": "牙孔时间费用",  # 🆕 P0
                "wire_standard": "线割标准基本费",  # 🆕 P0
                "total": "最终总价计算",  # 🆕 P0
                "nc_base": "NC基本时间",  # 🆕 UPDATE 2026-02-07
                "nc_z": "NC Z面(主视图)时间",  # 🆕 UPDATE 2026-02-07
                "nc_b": "NC B面(背面)时间",  # 🆕 UPDATE 2026-02-07
                "nc_c": "NC C面(侧面正面)时间",  # 🆕 UPDATE 2026-02-07
                "nc_c_b": "NC C_B面(侧背)时间",  # 🆕 UPDATE 2026-02-07
                "nc_z_view": "NC Z_VIEW面(正面)时间",  # 🆕 UPDATE 2026-02-07
                "nc_b_view": "NC B_VIEW面(正面的背面)时间",  # 🆕 UPDATE 2026-02-07
                "nc_total": "NC总费用计算",  # 🆕 UPDATE 2026-02-07
                "nc_roughing": "NC开粗费用",  # 🆕 P0
                "nc_milling": "NC精铣费用",  # 🆕 P0
                "nc_drilling": "NC钻床费用",  # 🆕 P0
                # 🆕 P2 水磨相关
                "water_mill_high": "水磨高度费",
                "water_mill_long_strip": "水磨长条费",
                "water_mill_chamfer": "水磨倒角费",
                "water_mill_thread_ends": "水磨螺纹端",
                "water_mill_hanging_table": "水磨挂台",
                "water_mill_bevel": "水磨斜面",
                "water_mill_oil_tank": "水磨油槽",
                "water_mill_high_cost": "水磨高费用",
                "water_mill_plate": "水磨板",
                "water_mill_component": "水磨零件",
                "water_mill_grinding": "水磨磨削",
                "wire_total": "线割总价计算",  # 🆕 UPDATE (2026-02-03)
                "weight_price": "价格加权计算",  # 🆕 UPDATE 2026-02-07
            }
            
            category_name = category_map.get(query_type, query_type)
            lines = [f"{subgraph_id} 的{category_name}详情：\n"]
            
            # 遍历步骤
            for step in target_item.get("steps", []):
                step_desc = step.get("step", "")
                
                if "formula" in step:
                    result_key = self._find_result_key(step)
                    if result_key:
                        lines.append(f"  {step_desc}: {step[result_key]}")
                        lines.append(f"    公式: {step['formula']}")
                    else:
                        lines.append(f"  {step_desc}")
                        lines.append(f"    公式: {step['formula']}")
                
                elif "note" in step or "reason" in step:
                    note = step.get("note") or step.get("reason")
                    lines.append(f"  {step_desc}: {note}")
                
                elif query_type == "wire_base" and "code" in step:
                    code = step.get("code")
                    instruction = step.get("instruction", "")
                    final_price = step.get("final_price", 0)
                    complete_formula = step.get("complete_formula", "")
                    
                    lines.append(f"  [{code}] {instruction}")
                    lines.append(f"    费用: {final_price:.2f} 元")
                    if complete_formula:
                        lines.append(f"    计算: {complete_formula}")
                
                elif step_desc:
                    lines.append(f"  {step_desc}")
                    
                    # 显示重要字段
                    important_keys = [
                        'weight', 'material_cost', 'heat_treatment_cost',
                        'basic_processing_cost', 'special_base_cost',
                        'material_additional_cost', 'unit_price', 'matched_sub_category',
                        'material', 'wire_type', 'is_template', 'needs_heat_treatment',
                        # 🆕 P1 扩展 important_keys
                        'discharge_cost', 'hole_cost', 'perimeter', 'total_discharge_cost',
                        'nc_base_hours', 'kai_cu_hours', 'jing_xi_hours', 'drill_hours',
                        'nc_roughing_cost', 'nc_milling_cost', 'nc_drilling_cost',
                        'wire_process', 'boring_num', 'standard_base_cost',
                        'total_length', 'dimension', 'base_price', 'final_price',
                        'processing_cost_total', 'total_cost',
                        'part_type', 'has_auto_material', 'has_side_cut',
                        # 🆕 UPDATE (2026-02-03) wire_total 相关
                        'wire_cost_base', 'wire_cost_per_unit', 'wire_length',
                        'slow_wire_length', 'mid_wire_length', 'fast_wire_length',
                        'material_unit_price', 'heat_treatment_unit_price',
                        'weight_kg', 'material_cost_total', 'heat_treatment_cost_total',
                        'matched_material', 'density',
                        # 🆕 UPDATE (2026-02-03 V3) 水磨相关
                        'thread_ends_count', 'thread_ends_cost',
                        'hanging_table_count', 'hanging_table_cost',
                        'total_chamfer_cost', 'chamfer_type',
                        'total_bevel_cost', 'bevel_value',
                        'oil_tank_count', 'oil_tank_cost',
                        'high_cost', 'thickness_diff',
                        'plate_cost', 'area',
                        'long_strip_cost', 'max_length',
                        'component_cost', 'grinding',
                        'mill_type', 'has_material_preparation',
                        # 🆕 UPDATE 2026-02-07: NC 相关
                        'face_code', 'total_minutes', 'total_hours', 'face_costs',
                        'nc_base_cost', 'comparisons', 'final_times', 'final_fees',
                        'nc_z_time', 'nc_b_time', 'nc_c_time',
                        # 🆕 UPDATE 2026-02-07: 价格加权相关
                        'weight_price', 'matched_range', 'rule_price', 'status',
                    ]
                    
                    for key in important_keys:
                        if key in step:
                            value = step[key]
                            key_name = self._translate_key(key)
                            lines.append(f"    {key_name}: {value}")
            
            return "\n".join(lines)
        
        except Exception as e:
            logger.error(f"❌ 格式化特定类型失败: {e}", exc_info=True)
            return f"{subgraph_id} 的 {query_type} 详情格式化失败：{str(e)}"
from shared.config import settings
