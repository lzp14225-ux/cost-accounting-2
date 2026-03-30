"""
ReviewRepository - 审核数据访问层
负责人：人员B2

职责：
1. 查询审核相关的 4 个表
2. 更新审核数据
3. 支持事务操作
"""
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload
from decimal import Decimal
from datetime import datetime
import logging
from shared.timezone_utils import now_shanghai

# 导入模型
from shared.models import Job, Feature, JobPriceSnapshot, JobProcessSnapshot, Subgraph, ProcessingCostCalculationDetail

logger = logging.getLogger(__name__)


class ReviewRepository:
    """审核数据仓储"""
    
    # ========== 查询方法 ==========
    
    async def get_features(
        self, 
        db: AsyncSession, 
        job_id: str
    ) -> List[Dict[str, Any]]:
        """
        查询 features 表（包含 part_code 和 part_name）
        
        Args:
            db: 数据库会话
            job_id: 任务ID
        
        Returns:
            特征列表（包含关联的零件编号和名称）
        """
        logger.info(f"📊 查询 features: job_id={job_id}")
        
        try:
            # 🆕 JOIN subgraphs 表获取 part_code 和 part_name
            query = (
                select(Feature, Subgraph.part_code, Subgraph.part_name)
                .join(Subgraph, Feature.subgraph_id == Subgraph.subgraph_id)
                .where(Feature.job_id == job_id)
            )
            result = await db.execute(query)
            rows = result.all()
            
            # 转换为字典（包含 part_code 和 part_name）
            data = []
            for feature, part_code, part_name in rows:
                feature_dict = self._feature_to_dict(feature)
                feature_dict['part_code'] = part_code
                feature_dict['part_name'] = part_name
                data.append(feature_dict)
            
            logger.info(f"✅ 查询完成: {len(data)} 条记录")
            return data
        
        except Exception as e:
            logger.error(f"❌ 查询 features 失败: {e}")
            raise

    
    async def get_price_snapshots(
        self, 
        db: AsyncSession, 
        job_id: str
    ) -> List[Dict[str, Any]]:
        """查询 price_snapshots 表"""
        logger.info(f"📊 查询 price_snapshots: job_id={job_id}")
        
        try:
            query = select(JobPriceSnapshot).where(
                JobPriceSnapshot.job_id == job_id
            )
            result = await db.execute(query)
            snapshots = result.scalars().all()
            
            data = [self._price_snapshot_to_dict(s) for s in snapshots]
            
            logger.info(f"✅ 查询完成: {len(data)} 条记录")
            return data
        
        except Exception as e:
            logger.error(f"❌ 查询 price_snapshots 失败: {e}")
            raise
    
    # 🔴 已废弃：不再使用 process_snapshots 表（改用 subgraphs.wire_process）
    # async def get_process_snapshots(
    #     self, 
    #     db: AsyncSession, 
    #     job_id: str
    # ) -> List[Dict[str, Any]]:
    #     """查询 process_snapshots 表"""
    #     logger.info(f"📊 查询 process_snapshots: job_id={job_id}")
    #     
    #     try:
    #         query = select(JobProcessSnapshot).where(
    #             JobProcessSnapshot.job_id == job_id
    #         )
    #         result = await db.execute(query)
    #         snapshots = result.scalars().all()
    #         
    #         data = [self._process_snapshot_to_dict(s) for s in snapshots]
    #         
    #         logger.info(f"✅ 查询完成: {len(data)} 条记录")
    #         return data
    #     
    #     except Exception as e:
    #         logger.error(f"❌ 查询 process_snapshots 失败: {e}")
    #         raise
    
    async def get_subgraphs(
        self, 
        db: AsyncSession, 
        job_id: str
    ) -> List[Dict[str, Any]]:
        """查询 subgraphs 表"""
        logger.info(f"📊 查询 subgraphs: job_id={job_id}")
        
        try:
            query = select(Subgraph).where(Subgraph.job_id == job_id)
            result = await db.execute(query)
            subgraphs = result.scalars().all()
            
            data = [self._subgraph_to_dict(s) for s in subgraphs]
            
            logger.info(f"✅ 查询完成: {len(data)} 条记录")
            return data
        
        except Exception as e:
            logger.error(f"❌ 查询 subgraphs 失败: {e}")
            raise
    
    async def get_processing_cost_details(
        self,
        db: AsyncSession,
        job_id: str
    ) -> List[Dict[str, Any]]:
        """
        查询 processing_cost_calculation_details 表（只查询 weight 字段）
        
        Args:
            db: 数据库会话
            job_id: 任务ID
        
        Returns:
            成本计算详情列表
        """
        logger.info(f"📊 查询 processing_cost_calculation_details: job_id={job_id}")
        
        try:
            query = select(ProcessingCostCalculationDetail).where(
                ProcessingCostCalculationDetail.job_id == job_id
            )
            result = await db.execute(query)
            details = result.scalars().all()
            
            data = [self._processing_cost_detail_to_dict(d) for d in details]
            
            logger.info(f"✅ 查询完成: {len(data)} 条记录")
            return data
        
        except Exception as e:
            logger.error(f"❌ 查询 processing_cost_calculation_details 失败: {e}")
            raise

    
    # ========== 更新方法 ==========
    
    async def update_features(
        self,
        db: AsyncSession,
        job_id: str,
        features_data: List[Dict[str, Any]]
    ):
        """
        更新 features 表
        
        Args:
            db: 数据库会话
            job_id: 任务ID
            features_data: 特征数据列表
        """
        logger.info(f"💾 更新 features: job_id={job_id}, count={len(features_data)}")
        
        # Feature 表中实际存在的可更新字段
        allowed_fields = {
            'subgraph_id', 'version', 'length_mm', 'width_mm', 'thickness_mm',
            'quantity', 'material', 'heat_treatment', 'calculated_weight_kg',
            'top_view_wire_length', 'front_view_wire_length', 'side_view_wire_length',
            'has_auto_material', 'needs_heat_treatment', 'boring_length_mm',
            'processing_instructions', 'is_complete', 'missing_params',
            'abnormal_situation', 'created_by', 'meta_data'
        }
        
        try:
            for feature_data in features_data:
                feature_id = feature_data.get("feature_id")
                
                # 只保留允许更新的字段
                update_data = {k: v for k, v in feature_data.items() 
                              if k in allowed_fields}
                
                # 🆕 类型转换：确保数值字段是正确的类型
                update_data = self._convert_feature_types(update_data)
                
                stmt = update(Feature).where(
                    Feature.feature_id == feature_id,
                    Feature.job_id == job_id
                ).values(**update_data)
                
                await db.execute(stmt)
            
            logger.info(f"✅ 更新完成")
        
        except Exception as e:
            logger.error(f"❌ 更新 features 失败: {e}")
            raise
    
    def _convert_feature_types(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        转换 feature 数据的类型
        
        Args:
            data: 原始数据
        
        Returns:
            类型转换后的数据
        """
        converted = data.copy()
        
        # 整数字段
        int_fields = ['version', 'quantity']
        for field in int_fields:
            if field in converted and converted[field] is not None:
                try:
                    converted[field] = int(converted[field])
                except (ValueError, TypeError):
                    logger.warning(f"⚠️  无法转换 {field} 为整数: {converted[field]}")
        
        # 浮点数字段
        float_fields = [
            'length_mm', 'width_mm', 'thickness_mm', 'calculated_weight_kg',
            'top_view_wire_length', 'front_view_wire_length', 'side_view_wire_length',
            'boring_length_mm'
        ]
        for field in float_fields:
            if field in converted and converted[field] is not None:
                try:
                    converted[field] = float(converted[field])
                except (ValueError, TypeError):
                    logger.warning(f"⚠️  无法转换 {field} 为浮点数: {converted[field]}")
        
        # 布尔字段
        bool_fields = ['has_auto_material', 'needs_heat_treatment', 'is_complete']
        for field in bool_fields:
            if field in converted and converted[field] is not None:
                if isinstance(converted[field], str):
                    converted[field] = converted[field].lower() in ('true', '1', 'yes')
                else:
                    converted[field] = bool(converted[field])
        
        return converted
    
    async def update_price_snapshots(
        self,
        db: AsyncSession,
        job_id: str,
        snapshots_data: List[Dict[str, Any]]
    ):
        """更新 price_snapshots 表"""
        logger.info(f"💾 更新 price_snapshots: job_id={job_id}")
        
        try:
            for snapshot_data in snapshots_data:
                snapshot_id = snapshot_data.get("snapshot_id")
                
                # 移除不能更新的字段
                update_data = {k: v for k, v in snapshot_data.items() 
                              if k not in ['snapshot_id', 'job_id', 'snapshot_created_at']}
                
                stmt = update(JobPriceSnapshot).where(
                    JobPriceSnapshot.snapshot_id == snapshot_id,
                    JobPriceSnapshot.job_id == job_id
                ).values(**update_data)
                
                await db.execute(stmt)
            
            logger.info(f"✅ 更新完成")
        
        except Exception as e:
            logger.error(f"❌ 更新 price_snapshots 失败: {e}")
            raise
    
    # 🔴 已废弃：不再使用 process_snapshots 表（改用 subgraphs.wire_process）
    # async def update_process_snapshots(
    #     self,
    #     db: AsyncSession,
    #     job_id: str,
    #     snapshots_data: List[Dict[str, Any]]
    # ):
    #     """更新 process_snapshots 表"""
    #     logger.info(f"💾 更新 process_snapshots: job_id={job_id}")
    #     
    #     try:
    #         for snapshot_data in snapshots_data:
    #             snapshot_id = snapshot_data.get("snapshot_id")
    #             
    #             # 移除不能更新的字段（包括 original_rule_id，这是从 process_rules 复制的原始ID，不应修改）
    #             update_data = {k: v for k, v in snapshot_data.items() 
    #                           if k not in ['snapshot_id', 'job_id', 'snapshot_created_at', 'original_rule_id']}
    #             
    #             stmt = update(JobProcessSnapshot).where(
    #                 JobProcessSnapshot.snapshot_id == snapshot_id,
    #                 JobProcessSnapshot.job_id == job_id
    #             ).values(**update_data)
    #             
    #             await db.execute(stmt)
    #         
    #         logger.info(f"✅ 更新完成")
    #     
    #     except Exception as e:
    #         logger.error(f"❌ 更新 process_snapshots 失败: {e}")
    #         raise
    
    async def update_subgraphs(
        self,
        db: AsyncSession,
        job_id: str,
        subgraphs_data: List[Dict[str, Any]]
    ):
        """更新 subgraphs 表"""
        logger.info(f"💾 更新 subgraphs: job_id={job_id}")
        
        # Subgraph 表中实际存在的可更新字段
        allowed_fields = {
            'part_name', 'part_code', 'subgraph_file_url', 'weight_kg',
            'material_unit_price', 'material_cost', 'heat_treatment_unit_price',
            'heat_treatment_cost', 'process_description', 'nc_z_time',
            'nc_b_time', 'nc_c_time', 'nc_c_b_time',
            'large_grinding_time', 'small_grinding_time', 'edm_time',
            'engraving_time', 'slow_wire_length', 'slow_wire_side_length',
            'mid_wire_length', 'fast_wire_length', 'separate_item',
            'total_cost', 'wire_process_note', 'nc_z_fee',
            'nc_b_fee', 'nc_c_fee', 'nc_c_b_fee',
            'large_grinding_cost', 'small_grinding_cost', 'slow_wire_cost',
            'slow_wire_side_cost', 'mid_wire_cost', 'fast_wire_cost',
            'edm_cost', 'engraving_cost', 'separate_item_cost',
            'processing_cost_total', 'applied_snapshot_ids', 'rule_reason',
            'override_by_user', 'cost_calculation_method', 'has_sheet_line',
            'sheet_area_mm2', 'sheet_perimeter_mm', 'sheet_line_data',
            'has_single_nc_calc', 'single_prt_file', 'process_changed',
            # 🆕 添加工艺字段
            'wire_process',
            'original_process', 'prt_3d_file', 'recalc_count',
            'last_recalc_at', 'last_recalc_by', 'status', 'meta_data',
            # 🆕 NC视图时间和费用
            'nc_z_view_time', 'nc_b_view_time', 'nc_z_view_fee', 'nc_b_view_fee',
            # 🆕 小磨数量
            'small_grinding_count'
        }
        
        try:
            for subgraph_data in subgraphs_data:
                subgraph_id = subgraph_data.get("subgraph_id")
                
                # 只保留允许更新的字段
                update_data = {k: v for k, v in subgraph_data.items() 
                              if k in allowed_fields}
                
                # 🆕 类型转换：确保数值字段是正确的类型
                update_data = self._convert_subgraph_types(update_data)
                
                # 更新 updated_at
                update_data['updated_at'] = now_shanghai()
                
                stmt = update(Subgraph).where(
                    Subgraph.subgraph_id == subgraph_id,
                    Subgraph.job_id == job_id
                ).values(**update_data)
                
                await db.execute(stmt)
            
            logger.info(f"✅ 更新完成")
        
        except Exception as e:
            logger.error(f"❌ 更新 subgraphs 失败: {e}")
            raise
    
    def _convert_subgraph_types(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        转换 subgraph 数据的类型
        
        Args:
            data: 原始数据
        
        Returns:
            类型转换后的数据
        """
        converted = data.copy()
        
        # 整数字段
        int_fields = ['recalc_count']
        for field in int_fields:
            if field in converted and converted[field] is not None:
                try:
                    converted[field] = int(converted[field])
                except (ValueError, TypeError):
                    logger.warning(f"⚠️  无法转换 {field} 为整数: {converted[field]}")
        
        # 浮点数字段（DECIMAL 类型）
        float_fields = [
            'weight_kg', 'material_unit_price', 'material_cost',
            'heat_treatment_unit_price', 'heat_treatment_cost',
            'nc_z_time', 'nc_b_time', 'nc_c_time', 'nc_c_b_time',
            'large_grinding_time', 'small_grinding_time', 'edm_time',
            'engraving_time', 'slow_wire_length', 'slow_wire_side_length',
            'mid_wire_length', 'fast_wire_length', 'total_cost',
            'nc_z_fee', 'nc_b_fee', 'nc_c_fee', 'nc_c_b_fee',
            'large_grinding_cost', 'small_grinding_cost',
            'slow_wire_cost', 'slow_wire_side_cost', 'mid_wire_cost',
            'fast_wire_cost', 'edm_cost', 'engraving_cost',
            'separate_item_cost', 'processing_cost_total',
            'sheet_area_mm2', 'sheet_perimeter_mm',
            'nc_z_view_time', 'nc_b_view_time', 'nc_z_view_fee', 'nc_b_view_fee'
        ]
        for field in float_fields:
            if field in converted and converted[field] is not None:
                try:
                    converted[field] = float(converted[field])
                except (ValueError, TypeError):
                    logger.warning(f"⚠️  无法转换 {field} 为浮点数: {converted[field]}")
        
        # 布尔字段
        bool_fields = [
            'override_by_user', 'has_sheet_line', 'has_single_nc_calc',
            'process_changed'
        ]
        for field in bool_fields:
            if field in converted and converted[field] is not None:
                if isinstance(converted[field], str):
                    converted[field] = converted[field].lower() in ('true', '1', 'yes')
                else:
                    converted[field] = bool(converted[field])
        
        return converted

    
    # ========== 辅助方法 ==========
    
    def _feature_to_dict(self, feature: Feature) -> Dict[str, Any]:
        """将 Feature 对象转换为字典"""
        return {
            "feature_id": feature.feature_id,
            "subgraph_id": feature.subgraph_id,
            "job_id": str(feature.job_id),
            "version": feature.version,
            "length_mm": float(feature.length_mm) if feature.length_mm else None,
            "width_mm": float(feature.width_mm) if feature.width_mm else None,
            "thickness_mm": float(feature.thickness_mm) if feature.thickness_mm else None,
            "quantity": feature.quantity,
            "material": feature.material,
            "heat_treatment": feature.heat_treatment,
            "calculated_weight_kg": float(feature.calculated_weight_kg) if feature.calculated_weight_kg else None,
            "top_view_wire_length": float(feature.top_view_wire_length) if feature.top_view_wire_length else None,
            "front_view_wire_length": float(feature.front_view_wire_length) if feature.front_view_wire_length else None,
            "side_view_wire_length": float(feature.side_view_wire_length) if feature.side_view_wire_length else None,
            "has_auto_material": feature.has_auto_material,
            "needs_heat_treatment": feature.needs_heat_treatment,
            "boring_length_mm": float(feature.boring_length_mm) if feature.boring_length_mm else None,
            "processing_instructions": feature.processing_instructions,
            "is_complete": feature.is_complete,
            "missing_params": feature.missing_params,
            "abnormal_situation": feature.abnormal_situation,
            "created_by": feature.created_by,
            "created_at": feature.created_at.isoformat() if feature.created_at else None,
            "meta_data": feature.meta_data
        }
    
    def _price_snapshot_to_dict(self, snapshot: JobPriceSnapshot) -> Dict[str, Any]:
        """将 JobPriceSnapshot 对象转换为字典"""
        return {
            "snapshot_id": snapshot.snapshot_id,
            "job_id": str(snapshot.job_id),
            "original_price_id": snapshot.original_price_id,
            "version_id": snapshot.version_id,
            "category": snapshot.category,
            "sub_category": snapshot.sub_category,
            "price": snapshot.price,
            "unit": snapshot.unit,
            "work_hours": snapshot.work_hours,
            "min_num": snapshot.min_num,
            "add_price": snapshot.add_price,
            "weight_num": snapshot.weight_num,
            "note": snapshot.note,
            "instruction": snapshot.instruction,
            "is_modified": snapshot.is_modified,
            "modified_by": snapshot.modified_by,
            "modified_at": snapshot.modified_at.isoformat() if snapshot.modified_at else None,
            "modification_reason": snapshot.modification_reason,
            "snapshot_created_at": snapshot.snapshot_created_at.isoformat() if snapshot.snapshot_created_at else None,
            "meta_data": snapshot.meta_data
        }
    
    def _process_snapshot_to_dict(self, snapshot: JobProcessSnapshot) -> Dict[str, Any]:
        """将 JobProcessSnapshot 对象转换为字典"""
        return {
            "snapshot_id": snapshot.snapshot_id,
            "job_id": str(snapshot.job_id),
            "original_rule_id": snapshot.original_rule_id,
            "version_id": snapshot.version_id,
            "feature_type": snapshot.feature_type,
            "name": snapshot.name,
            "description": snapshot.description,
            "conditions": snapshot.conditions,
            "output_params": snapshot.output_params,
            "priority": snapshot.priority,
            "is_modified": snapshot.is_modified,
            "modified_by": snapshot.modified_by,
            "modified_at": snapshot.modified_at.isoformat() if snapshot.modified_at else None,
            "modification_reason": snapshot.modification_reason,
            "snapshot_created_at": snapshot.snapshot_created_at.isoformat() if snapshot.snapshot_created_at else None,
            "meta_data": snapshot.meta_data
        }
    
    def _subgraph_to_dict(self, subgraph: Subgraph) -> Dict[str, Any]:
        """将 Subgraph 对象转换为字典"""
        return {
            "subgraph_id": subgraph.subgraph_id,
            "job_id": str(subgraph.job_id),
            "part_name": subgraph.part_name,
            "part_code": subgraph.part_code,
            "subgraph_file_url": subgraph.subgraph_file_url,
            "weight_kg": float(subgraph.weight_kg) if subgraph.weight_kg else None,
            "material_unit_price": float(subgraph.material_unit_price) if subgraph.material_unit_price else None,
            "material_cost": float(subgraph.material_cost) if subgraph.material_cost else None,
            "heat_treatment_unit_price": float(subgraph.heat_treatment_unit_price) if subgraph.heat_treatment_unit_price else None,
            "heat_treatment_cost": float(subgraph.heat_treatment_cost) if subgraph.heat_treatment_cost else None,
            "process_description": subgraph.process_description,
            "nc_z_time": float(subgraph.nc_z_time) if subgraph.nc_z_time else None,
            "nc_b_time": float(subgraph.nc_b_time) if subgraph.nc_b_time else None,
            "nc_c_time": float(subgraph.nc_c_time) if subgraph.nc_c_time else None,
            "nc_c_b_time": float(subgraph.nc_c_b_time) if subgraph.nc_c_b_time else None,
            "large_grinding_time": float(subgraph.large_grinding_time) if subgraph.large_grinding_time else None,
            "small_grinding_time": float(subgraph.small_grinding_time) if subgraph.small_grinding_time else None,
            "edm_time": float(subgraph.edm_time) if subgraph.edm_time else None,
            "engraving_time": float(subgraph.engraving_time) if subgraph.engraving_time else None,
            "slow_wire_length": float(subgraph.slow_wire_length) if subgraph.slow_wire_length else None,
            "slow_wire_side_length": float(subgraph.slow_wire_side_length) if subgraph.slow_wire_side_length else None,
            "mid_wire_length": float(subgraph.mid_wire_length) if subgraph.mid_wire_length else None,
            "fast_wire_length": float(subgraph.fast_wire_length) if subgraph.fast_wire_length else None,
            "separate_item": subgraph.separate_item,
            "total_cost": float(subgraph.total_cost) if subgraph.total_cost else None,
            "wire_process": subgraph.wire_process,  # 🆕 工艺代码
            "wire_process_note": subgraph.wire_process_note,
            "nc_z_fee": float(subgraph.nc_z_fee) if subgraph.nc_z_fee else None,
            "nc_b_fee": float(subgraph.nc_b_fee) if subgraph.nc_b_fee else None,
            "nc_c_fee": float(subgraph.nc_c_fee) if subgraph.nc_c_fee else None,
            "nc_c_b_fee": float(subgraph.nc_c_b_fee) if subgraph.nc_c_b_fee else None,
            "large_grinding_cost": float(subgraph.large_grinding_cost) if subgraph.large_grinding_cost else None,
            "small_grinding_cost": float(subgraph.small_grinding_cost) if subgraph.small_grinding_cost else None,
            "slow_wire_cost": float(subgraph.slow_wire_cost) if subgraph.slow_wire_cost else None,
            "slow_wire_side_cost": float(subgraph.slow_wire_side_cost) if subgraph.slow_wire_side_cost else None,
            "mid_wire_cost": float(subgraph.mid_wire_cost) if subgraph.mid_wire_cost else None,
            "fast_wire_cost": float(subgraph.fast_wire_cost) if subgraph.fast_wire_cost else None,
            "edm_cost": float(subgraph.edm_cost) if subgraph.edm_cost else None,
            "engraving_cost": float(subgraph.engraving_cost) if subgraph.engraving_cost else None,
            "separate_item_cost": float(subgraph.separate_item_cost) if subgraph.separate_item_cost else None,
            "processing_cost_total": float(subgraph.processing_cost_total) if subgraph.processing_cost_total else None,
            "nc_z_view_time": float(subgraph.nc_z_view_time) if subgraph.nc_z_view_time else None,
            "nc_b_view_time": float(subgraph.nc_b_view_time) if subgraph.nc_b_view_time else None,
            "nc_z_view_fee": float(subgraph.nc_z_view_fee) if subgraph.nc_z_view_fee else None,
            "nc_b_view_fee": float(subgraph.nc_b_view_fee) if subgraph.nc_b_view_fee else None,
            "small_grinding_count": subgraph.small_grinding_count if subgraph.small_grinding_count else None,
            "applied_snapshot_ids": subgraph.applied_snapshot_ids,
            "rule_reason": subgraph.rule_reason,
            "override_by_user": subgraph.override_by_user,
            "cost_calculation_method": subgraph.cost_calculation_method,
            "has_sheet_line": subgraph.has_sheet_line,
            "sheet_area_mm2": float(subgraph.sheet_area_mm2) if subgraph.sheet_area_mm2 else None,
            "sheet_perimeter_mm": float(subgraph.sheet_perimeter_mm) if subgraph.sheet_perimeter_mm else None,
            "sheet_line_data": subgraph.sheet_line_data,
            "has_single_nc_calc": subgraph.has_single_nc_calc,
            "single_prt_file": subgraph.single_prt_file,
            "process_changed": subgraph.process_changed,
            "original_process": subgraph.original_process,
            "prt_3d_file": subgraph.prt_3d_file,
            "recalc_count": subgraph.recalc_count,
            "last_recalc_at": subgraph.last_recalc_at.isoformat() if subgraph.last_recalc_at else None,
            "last_recalc_by": subgraph.last_recalc_by,
            "status": subgraph.status,
            "created_at": subgraph.created_at.isoformat() if subgraph.created_at else None,
            "updated_at": subgraph.updated_at.isoformat() if subgraph.updated_at else None,
            "meta_data": subgraph.meta_data
        }
    
    def _processing_cost_detail_to_dict(self, detail: ProcessingCostCalculationDetail) -> Dict[str, Any]:
        """
        将 ProcessingCostCalculationDetail 对象转换为字典
        ⚠️ 只包含 weight 字段（根据需求简化）
        """
        return {
            "detail_id": detail.detail_id,
            "job_id": str(detail.job_id),
            "subgraph_id": detail.subgraph_id,
            "weight": float(detail.weight) if detail.weight else None,  # ⚠️ 只查询这一个字段
            "created_at": detail.created_at.isoformat() if detail.created_at else None
        }
    
    # ========== 批量操作方法（性能优化）==========
    
    async def get_all_review_data(
        self,
        db: AsyncSession,
        job_id: str
    ) -> Dict[str, Any]:
        """
        一次性查询所有审核数据（性能优化）
        
        Args:
            db: 数据库会话
            job_id: 任务ID
        
        Returns:
            包含4个表数据的字典
        """
        logger.info(f"📊 批量查询审核数据（4表架构）: job_id={job_id}")
        
        try:
            # 并发查询4个表
            features = await self.get_features(db, job_id)
            price_snapshots = await self.get_price_snapshots(db, job_id)
            subgraphs = await self.get_subgraphs(db, job_id)
            processing_cost_details = await self.get_processing_cost_details(db, job_id)  # 🆕 新增
            
            job_meta_data = await self.get_job_meta_data(db, job_id)
            nc_failed_itemcodes = self._extract_nc_failed_itemcodes(job_meta_data)
            nc_failed_items = self._build_nc_failed_items(nc_failed_itemcodes, subgraphs)

            result = {
                "features": features,
                "job_price_snapshots": price_snapshots,  # 🔑 使用实际表名
                "subgraphs": subgraphs,
                "processing_cost_calculation_details": processing_cost_details  # 🆕 新增
            }
            
            logger.info(f"✅ 批量查询完成: features={len(features)}, "
                       f"job_price_snapshots={len(price_snapshots)}, "
                       f"subgraphs={len(subgraphs)}, "
                       f"processing_cost_calculation_details={len(processing_cost_details)}")  # 🆕 新增
            
            result["job_meta_data"] = job_meta_data
            result["nc_failed_itemcodes"] = nc_failed_itemcodes
            result["nc_failed_items"] = nc_failed_items
            return result
        
        except Exception as e:
            logger.error(f"❌ 批量查询失败: {e}")
            raise
    
    async def get_job_meta_data(
        self,
        db: AsyncSession,
        job_id: str
    ) -> Dict[str, Any]:
        result = await db.execute(
            select(Job.meta_data).where(Job.job_id == job_id)
        )
        meta_data = result.scalar_one_or_none()
        return meta_data if isinstance(meta_data, dict) else {}

    def _extract_nc_failed_itemcodes(self, job_meta_data: Optional[Dict[str, Any]]) -> List[str]:
        if not isinstance(job_meta_data, dict):
            return []

        raw_codes = job_meta_data.get("nc_failed_itemcodes")
        if raw_codes is None:
            raw_codes = job_meta_data.get("fail_itemcode", [])

        if not isinstance(raw_codes, list):
            return []

        normalized_codes: List[str] = []
        seen = set()
        for code in raw_codes:
            text = str(code).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized_codes.append(text)
        return normalized_codes

    def _build_nc_failed_items(
        self,
        nc_failed_itemcodes: List[str],
        subgraphs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if not nc_failed_itemcodes:
            return []

        subgraph_map = {}
        for subgraph in subgraphs:
            part_code = str(subgraph.get("part_code") or "").strip()
            if part_code and part_code not in subgraph_map:
                subgraph_map[part_code] = subgraph

        items = []
        for code in nc_failed_itemcodes:
            matched = subgraph_map.get(code, {})
            items.append({
                "record_id": matched.get("subgraph_id") or code,
                "record_name": matched.get("subgraph_id") or code,
                "subgraph_id": matched.get("subgraph_id"),
                "part_code": matched.get("part_code") or code,
                "part_name": matched.get("part_name"),
                "reason": "NC识别失败",
            })
        return items

    async def update_all_review_data(
        self,
        db: AsyncSession,
        job_id: str,
        data: Dict[str, List[Dict[str, Any]]]
    ):
        """
        批量更新所有审核数据（使用事务）
        
        Args:
            db: 数据库会话
            job_id: 任务ID
            data: 包含3个表数据的字典
        """
        logger.info(f"💾 批量更新审核数据: job_id={job_id}")
        
        try:
            # 按顺序更新（在同一个事务中）
            if "features" in data:
                await self.update_features(db, job_id, data["features"])
            
            # 🔑 支持两种键名（向后兼容）
            if "job_price_snapshots" in data:
                await self.update_price_snapshots(db, job_id, data["job_price_snapshots"])
            elif "price_snapshots" in data:
                await self.update_price_snapshots(db, job_id, data["price_snapshots"])
            
            if "subgraphs" in data:
                await self.update_subgraphs(db, job_id, data["subgraphs"])
            
            logger.info(f"✅ 批量更新完成")
        
        except Exception as e:
            logger.error(f"❌ 批量更新失败: {e}")
            raise
