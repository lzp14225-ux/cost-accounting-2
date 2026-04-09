"""
DataViewBuilder - 数据视图构建器
负责人：人员B2

职责：
1. 构建前端展示视图（关联 4 个表）
2. 反向映射（展示层修改 → 存储层修改）
3. 查找和验证

设计思想：
- 存储层：保持 4 表独立（用于版本控制和回写）
- 展示层：构建关联视图（用于前端展示和用户输入）
- 映射层：双向转换
"""
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class DataViewBuilder:
    """数据视图构建器"""
    
    @staticmethod
    def build_display_view(raw_data: Dict[str, List[Dict]]) -> List[Dict]:
        """
        构建前端展示视图（4表架构）
        
        关联规则：
        1. subgraphs 作为主表
        2. features 通过 job_id + subgraph_id 关联
        3. price_snapshots 通过 job_id + category + sub_category 关联（不区分大小写）
        4. 🆕 processing_cost_calculation_details 通过 job_id + subgraph_id 关联（只查询 weight 字段）
        
        Args:
            raw_data: 原始 4 表数据
                {
                    "features": [...],
                    "price_snapshots": [...],
                    "subgraphs": [...],
                    "processing_cost_calculation_details": [...]  # 🆕 新增
                }
        
        Returns:
            展示视图列表
                [
                    {
                        "part_code": "P001",
                        "part_name": "零件1",
                        "material": "45钢",
                        "weight": 2.5,  # 🆕 新增
                        ...
                        "_source": {
                            "subgraph_id": "sg_001",
                            "feature_id": "ft_001",
                            "processing_cost_detail_id": 123,  # 🆕 新增
                            ...
                        }
                    }
                ]
        """
        logger.info("🔧 构建展示视图（4表架构）...")
        
        display_items = []
        
        subgraphs = raw_data.get("subgraphs", [])
        features = raw_data.get("features", [])
        # 🔑 支持两种键名（向后兼容）
        price_snapshots = raw_data.get("job_price_snapshots") or raw_data.get("price_snapshots", [])
        # 🆕 获取成本计算详情（向后兼容：如果不存在则为空列表）
        cost_details = raw_data.get("processing_cost_calculation_details", [])
        nc_failed_code_map = DataViewBuilder._build_nc_failed_code_map(
            raw_data.get("nc_failed_itemcodes", [])
        )
        
        for subgraph in subgraphs:
            job_id = subgraph.get("job_id")
            subgraph_id = subgraph.get("subgraph_id")
            
            # 1. 查找对应的 feature（通过 job_id + subgraph_id）
            feature = DataViewBuilder._find_feature(
                features,
                job_id=job_id,
                subgraph_id=subgraph_id
            )

            # 2. 🆕 直接从 subgraph 获取 wire_process
            wire_process_code = subgraph.get("wire_process")
            
            # 3. 查找对应的 wire price（使用 job_id + wire_process，不区分大小写）
            wire_price = None
            if wire_process_code:
                wire_price = DataViewBuilder._find_price_snapshot(
                    price_snapshots,
                    job_id=job_id,
                    category="wire",
                    sub_category=wire_process_code
                )
            
            # 4. 查找对应的 material price（使用 job_id + material，不区分大小写）
            material_price = None
            if feature:
                material_price = DataViewBuilder._find_price_snapshot(
                    price_snapshots,
                    job_id=job_id,
                    category="material",
                    sub_category=feature.get("material")
                )
            
            # 🆕 5. 查找对应的 cost detail（使用 job_id + subgraph_id）
            cost_detail = DataViewBuilder._find_processing_cost_detail(
                cost_details,
                job_id=job_id,
                subgraph_id=subgraph_id
            )
            
            # 6. 构建展示项
            display_item = {
                # 基础信息（来自 subgraph）
                "part_code": subgraph.get("part_code"),
                "part_name": subgraph.get("part_name"),
                "subgraph_file_url": subgraph.get("subgraph_file_url"),
                "process_description": subgraph.get("process_description"),  # 工艺说明
                
                # 特征信息（来自 feature）- ❌ 移除了4个不需要的字段
                "material": feature.get("material") if feature else None,
                "length_mm": feature.get("length_mm") if feature else None,
                "width_mm": feature.get("width_mm") if feature else None,
                "thickness_mm": feature.get("thickness_mm") if feature else None,
                "quantity": feature.get("quantity") if feature else None,
                # ❌ 移除: calculated_weight_kg, top_view_wire_length, front_view_wire_length, side_view_wire_length
                
                # 🆕 features 表新增字段
                "heat_treatment": feature.get("heat_treatment") if feature else None,
                "abnormal_situation": DataViewBuilder._merge_abnormal_situation(feature.get("abnormal_situation") if feature else None, subgraph.get("part_code"), subgraph_id, nc_failed_code_map),  # NC???????????
                
                # 🆕 subgraphs 表新增字段（时间）
                "drilling_time": subgraph.get("drilling_time"),
                "nc_roughing_time": subgraph.get("nc_roughing_time"),
                "nc_milling_time": subgraph.get("nc_milling_time"),
                "edm_time": subgraph.get("edm_time"),
                
                # 🆕 subgraphs 表新增字段（长度 - COALESCE）
                "wire_length": (
                    subgraph.get("slow_wire_length") or
                    subgraph.get("mid_wire_length") or
                    subgraph.get("fast_wire_length") or
                    (feature.get("top_view_wire_length") if feature else None) or
                    (feature.get("front_view_wire_length") if feature else None) or
                    (feature.get("side_view_wire_length") if feature else None)
                ),
                "grinding_time": (
                    subgraph.get("large_grinding_time") or
                    subgraph.get("small_grinding_time")
                ),
                
                # 工艺信息（来自 subgraph.wire_process）
                "process_code": wire_process_code,
                "process_note": subgraph.get("wire_process_note"),
                
                # 价格信息（来自 price_snapshots）
                "process_unit_price": wire_price.get("price") if wire_price else None,
                "material_unit_price": material_price.get("price") if material_price else None,
                
                # 🆕 成本信息（来自 processing_cost_calculation_details）- 只有 weight
                "weight": cost_detail.get("weight") if cost_detail else None,
                
                # 元数据：记录来源（用于反向映射）
                "_source": {
                    "job_id": job_id,
                    "subgraph_id": subgraph_id,
                    "feature_id": feature.get("feature_id") if feature else None,
                    "feature_version": feature.get("version") if feature else None,
                    "created_at": subgraph.get("created_at"),
                    "wire_price_snapshot_id": wire_price.get("snapshot_id") if wire_price else None,
                    "material_price_snapshot_id": material_price.get("snapshot_id") if material_price else None,
                    # 🆕 成本记录 ID
                    "processing_cost_detail_id": cost_detail.get("detail_id") if cost_detail else None
                }
            }
            
            display_items.append(display_item)
        
        # 6. 排序：按 created_at DESC, subgraph_id, version
        display_items.sort(
            key=lambda x: (
                x.get("_source", {}).get("created_at") or "",
                x.get("_source", {}).get("subgraph_id") or "",
                x.get("_source", {}).get("feature_version") or 0
            ),
            reverse=True  # created_at 降序
        )
        
        logger.info(f"✅ 展示视图构建完成（4表架构）: {len(display_items)} 条记录")
        return display_items
    
    @staticmethod
    def _find_feature(features: List[Dict], job_id: str, subgraph_id: str) -> Optional[Dict]:
        """
        查找对应的 feature
        
        关联条件：
        - feature.job_id == subgraph.job_id
        - feature.subgraph_id == subgraph.subgraph_id
        """
        for feature in features:
            if (feature.get("job_id") == job_id and 
                feature.get("subgraph_id") == subgraph_id):
                return feature
        return None
    
    @staticmethod
    def _find_price_snapshot(
        price_snapshots: List[Dict],
        job_id: str,
        category: str,
        sub_category: Optional[str]
    ) -> Optional[Dict]:
        """
        查找对应的 price_snapshot
        
        关联条件：
        - job_id 匹配
        - category 匹配（不区分大小写）
        - sub_category 匹配（不区分大小写，例如 Cr12 和 CR12 能匹配）
        """
        if not sub_category:
            return None
        
        category_lower = category.lower().strip()
        sub_category_lower = sub_category.lower().strip()  # 🆕 转小写比较
        
        for price in price_snapshots:
            # 🔑 检查 job_id
            if price.get("job_id") != job_id:
                continue
            
            # 🔑 安全地获取 category,处理 None 值
            price_category = price.get("category")
            if price_category is None:
                continue
            
            price_category = price_category.lower().strip()
            
            # 🔑 安全地获取 sub_category,处理 None 值
            price_sub_category = price.get("sub_category")
            if price_sub_category is None:
                continue
            
            price_sub_category = price_sub_category.lower().strip()  # 🆕 转小写比较
            
            if (price_category == category_lower and 
                price_sub_category == sub_category_lower):
                return price
        
        return None
    
    @staticmethod
    def _find_processing_cost_detail(
        details: List[Dict],
        job_id: str,
        subgraph_id: str
    ) -> Optional[Dict]:
        """
        查找对应的 processing_cost_calculation_detail
        
        关联条件：
        - detail.job_id == subgraph.job_id
        - detail.subgraph_id == subgraph.subgraph_id
        
        Args:
            details: processing_cost_calculation_details 列表
            job_id: 任务ID
            subgraph_id: 子图ID
        
        Returns:
            匹配的成本记录，如果不存在返回 None
        """
        for detail in details:
            if (detail.get("job_id") == job_id and 
                detail.get("subgraph_id") == subgraph_id):
                return detail
        return None
    
    @staticmethod
    def _build_nc_failed_code_map(nc_failed_itemcodes: List[Any]) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for raw_code in nc_failed_itemcodes or []:
            code = str(raw_code).strip()
            if not code:
                continue
            result[code] = {
                "type": "nc_recognition_failed",
                "description": "NC\u8bc6\u522b\u5931\u8d25"
            }
        return result

    @staticmethod
    def _merge_abnormal_situation(
        abnormal_situation: Optional[Dict[str, Any]],
        part_code: Optional[str],
        subgraph_id: Optional[str],
        nc_failed_code_map: Dict[str, Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        merged: Dict[str, Any] = dict(abnormal_situation) if isinstance(abnormal_situation, dict) else {}

        normalized_part_code = str(part_code or "").strip()
        normalized_subgraph_id = str(subgraph_id or "").strip()
        nc_anomaly = (
            nc_failed_code_map.get(normalized_part_code)
            or nc_failed_code_map.get(normalized_subgraph_id)
        )

        if nc_anomaly:
            existing = merged.get("nc_anomalies")
            if not isinstance(existing, list):
                existing = []
            existing = [item for item in existing if isinstance(item, dict)]
            if not any(item.get("type") == nc_anomaly["type"] for item in existing):
                existing.append(nc_anomaly)
            merged["nc_anomalies"] = existing

        return merged or None

    @staticmethod
    def map_display_to_tables(
        display_changes: List[Dict],
        raw_data: Dict[str, List[Dict]]
    ) -> List[Dict]:
        """
        反向映射：展示层修改 → 存储层修改
        
        Args:
            display_changes: 展示层修改
                [
                    {
                        "part_code": "P001",
                        "field": "material",
                        "value": "45钢"
                    }
                ]
            raw_data: 原始 4 表数据
        
        Returns:
            存储层修改
                [
                    {
                        "table": "features",
                        "id": "ft_001",
                        "field": "material",
                        "value": "45钢"
                    },
                    {
                        "table": "subgraphs",
                        "id": "sg_001",
                        "field": "material",
                        "value": "45钢"
                    }
                ]
        """
        logger.info(f"🔄 反向映射: {len(display_changes)} 个修改")
        
        table_changes = []
        
        # 构建展示视图（用于查找 _source）
        display_view = DataViewBuilder.build_display_view(raw_data)
        
        for change in display_changes:
            part_code = change.get("part_code")
            field = change.get("field")
            value = change.get("value")
            
            # 查找对应的展示项
            display_item = DataViewBuilder.find_by_part_code(
                display_view,
                part_code
            )
            
            if not display_item:
                logger.warning(f"⚠️  未找到 part_code: {part_code}")
                continue
            
            # 根据字段映射到对应的表
            source = display_item.get("_source", {})
            mapped_changes = DataViewBuilder._map_field_to_tables(
                field,
                value,
                source
            )
            
            table_changes.extend(mapped_changes)
        
        logger.info(f"✅ 反向映射完成: {len(table_changes)} 个表修改")
        return table_changes

    
    @staticmethod
    def _map_field_to_tables(
        field: str,
        value: Any,
        source: Dict[str, str]
    ) -> List[Dict]:
        """
        将字段映射到对应的表（4表架构）
        
        映射规则：
        - material, length_mm, width_mm, thickness_mm, quantity, heat_treatment → features
        - process_code → subgraphs.wire_process
        - process_unit_price → job_price_snapshots.price (wire)
        - material_unit_price → job_price_snapshots.price (material)
        - weight → processing_cost_calculation_details.weight (🆕 新增)
        
        ❌ 已移除字段（不再支持修改）：
        - calculated_weight_kg?????
        - top/front/side_view_wire_length ??? wire_length ???????
        """
        changes = []
        
        # 特征字段 → features 表（❌ 移除了4个不需要的字段）
        feature_fields = [
            "material", "length_mm", "width_mm", 
            "thickness_mm", "quantity", "heat_treatment"
        ]
        
        if field in feature_fields:
            feature_id = source.get("feature_id")
            if feature_id:
                changes.append({
                    "table": "features",
                    "id": feature_id,
                    "field": field,
                    "value": value
                })
            else:
                logger.warning(f"⚠️  无法修改字段 {field}：缺少 feature_id")
        
        # 🆕 成本字段 → processing_cost_calculation_details 表（只有 weight）
        elif field in ["weight"]:
            detail_id = source.get("processing_cost_detail_id")
            if detail_id:
                changes.append({
                    "table": "processing_cost_calculation_details",
                    "id": detail_id,
                    "field": field,
                    "value": value
                })
            else:
                logger.warning(f"⚠️  无法修改字段 {field}：缺少 processing_cost_detail_id")
        
        # 工艺代码 → subgraphs 表
        elif field == "process_code":
            subgraph_id = source.get("subgraph_id")
            if subgraph_id:
                changes.append({
                    "table": "subgraphs",
                    "id": subgraph_id,
                    "field": "wire_process",
                    "value": value
                })
        
        # 工艺单价 → job_price_snapshots 表 (wire)
        elif field == "process_unit_price":
            wire_price_snapshot_id = source.get("wire_price_snapshot_id")
            if wire_price_snapshot_id:
                changes.append({
                    "table": "job_price_snapshots",
                    "id": wire_price_snapshot_id,
                    "field": "price",
                    "value": value
                })
        
        # 材料单价 → job_price_snapshots 表 (material)
        elif field == "material_unit_price":
            material_price_snapshot_id = source.get("material_price_snapshot_id")
            if material_price_snapshot_id:
                changes.append({
                    "table": "job_price_snapshots",
                    "id": material_price_snapshot_id,
                    "field": "price",
                    "value": value
                })
        
        # 基础信息 → subgraphs 表
        elif field in ["part_code", "part_name"]:
            subgraph_id = source.get("subgraph_id")
            if subgraph_id:
                changes.append({
                    "table": "subgraphs",
                    "id": subgraph_id,
                    "field": field,
                    "value": value
                })
        
        return changes
    
    @staticmethod
    def find_by_part_code(
        display_view: List[Dict],
        part_code: str
    ) -> Optional[Dict]:
        """
        通过 part_code 查找展示项
        
        Args:
            display_view: 展示视图
            part_code: 零件编码
        
        Returns:
            展示项，如果不存在返回 None
        """
        for item in display_view:
            if item.get("part_code") == part_code:
                return item
        return None
    
    @staticmethod
    def find_by_subgraph_id(
        display_view: List[Dict],
        subgraph_id: str
    ) -> Optional[Dict]:
        """
        通过 subgraph_id 查找展示项
        
        Args:
            display_view: 展示视图
            subgraph_id: 子图ID
        
        Returns:
            展示项，如果不存在返回 None
        """
        for item in display_view:
            source = item.get("_source", {})
            if source.get("subgraph_id") == subgraph_id:
                return item
        return None
    
    @staticmethod
    def find_all_by_part_name(
        display_view: List[Dict],
        part_name: str
    ) -> List[Dict]:
        """
        通过 part_name 查找所有匹配的展示项（支持批量修改）
        
        Args:
            display_view: 展示视图
            part_name: 零件名称
        
        Returns:
            匹配的展示项列表
        """
        matches = []
        for item in display_view:
            if item.get("part_name") == part_name:
                matches.append(item)
        return matches
    
    @staticmethod
    def find_all_by_identifier(
        display_view: List[Dict],
        identifier: str
    ) -> List[Dict]:
        """
        通过标识符查找所有匹配的展示项（支持 part_code 或 part_name，支持模糊匹配）
        
        Args:
            display_view: 展示视图
            identifier: 标识符（可以是 part_code 或 part_name）
        
        Returns:
            匹配的展示项列表
        """
        from shared.input_normalizer import InputNormalizer
        
        matches = []
        
        # 🆕 标准化输入标识符（支持模糊匹配）
        input_variants = InputNormalizer.normalize_subgraph_id(identifier)
        
        for item in display_view:
            part_code = item.get("part_code", "")
            part_name = item.get("part_name", "")
            
            # 🆕 模糊匹配 part_code
            if part_code:
                code_variants = InputNormalizer.normalize_subgraph_id(part_code)
                if set(input_variants) & set(code_variants):
                    matches.append(item)
                    continue
            
            # 精确匹配 part_name
            if part_name == identifier:
                matches.append(item)
        
        return matches
    
    @staticmethod
    def validate_mapping(display_item: Dict) -> Dict[str, Any]:
        """
        验证映射完整性（4表架构）
        
        Args:
            display_item: 展示项
        
        Returns:
            验证结果
                {
                    "is_valid": True/False,
                    "missing_sources": [...],
                    "warnings": [...]
                }
        """
        source = display_item.get("_source", {})
        missing_sources = []
        warnings = []
        
        # 检查必需的 source
        if not source.get("subgraph_id"):
            missing_sources.append("subgraph_id")
        
        if not source.get("feature_id"):
            warnings.append("缺少 feature_id，无法修改特征字段")
        
        if not source.get("wire_price_snapshot_id"):
            warnings.append("缺少 wire_price_snapshot_id，无法修改工艺单价")
        
        if not source.get("material_price_snapshot_id"):
            warnings.append("缺少 material_price_snapshot_id，无法修改材料单价")
        
        # 🆕 检查成本记录 ID（4表架构）
        if not source.get("processing_cost_detail_id"):
            warnings.append("缺少 processing_cost_detail_id，无法修改成本字段（weight）")
        
        return {
            "is_valid": len(missing_sources) == 0,
            "missing_sources": missing_sources,
            "warnings": warnings
        }
