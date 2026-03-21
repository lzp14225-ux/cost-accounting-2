"""
ProcessRulesRepository - 工艺规则仓储
负责人：人员B2

职责：
1. 查询 price_items 表（线切割工艺）
2. 根据描述模糊匹配工艺规则
3. 获取工艺代码和说明
4. 直接使用数据库中的工艺代码格式（不做映射转换）

数据库工艺代码格式：
- fast_cut: 快丝割一刀
- slow_cut: 慢丝割一刀
- middle_and_one: 中丝割一修一
- slow_and_one: 慢丝割一修一
- slow_and_two: 慢丝割一修二
- slow_and_three: 慢丝割一修三
"""
import json
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy import select, and_, or_, distinct
from sqlalchemy.ext.asyncio import AsyncSession
from shared.models import PriceItem

logger = logging.getLogger(__name__)


class ProcessRulesRepository:
    """工艺规则仓储"""
    
    async def find_wire_process_by_description(
        self,
        db: AsyncSession,
        description: str,
        version_id: str = "v1.0"
    ) -> Optional[Dict[str, Any]]:
        """
        根据描述模糊匹配线切割工艺规则（从 price_items 表查询）
        
        Args:
            db: 数据库会话
            description: 工艺描述（如"慢丝割一修三"）
            version_id: 版本ID（默认 v1.0，暂未使用）
        
        Returns:
            匹配的工艺规则字典，如果没找到返回 None
            {
                "id": "P004",
                "name": "慢丝割一修三",
                "description": "慢丝割一修三",
                "process_code": "slow_and_three",
                "conditions": "slow_and_three",
                "output_params": {},
                "priority": 1
            }
        """
        logger.info(f"🔍 查询工艺规则（price_items）: description='{description}'")
        
        try:
            # 从 price_items 表查询线切割工艺
            stmt = select(PriceItem).where(
                and_(
                    PriceItem.category == "wire",  # 只查询线切割工艺
                    PriceItem.is_active == True,
                    # 模糊匹配 note 字段
                    PriceItem.note.ilike(f"%{description}%")
                )
            ).limit(1)  # 只取第一条
            
            result = await db.execute(stmt)
            item = result.scalars().first()
            
            if item:
                # 🔑 直接使用数据库中的工艺代码
                process_code = item.sub_category
                note = item.note or description
                
                logger.info(f"✅ 找到工艺规则: id={item.id}, note={note}, process_code={process_code}")
                
                return {
                    "id": item.id,
                    "name": note,
                    "description": note,
                    "process_code": process_code,  # 🔑 sub_category 就是工艺代码
                    "conditions": process_code,
                    "output_params": {},
                    "priority": 1
                }
            else:
                logger.warning(f"⚠️  未找到匹配的工艺规则: '{description}'")
                return None
        
        except Exception as e:
            logger.error(f"❌ 查询工艺规则失败: {e}", exc_info=True)
            return None
    
    async def get_all_wire_processes(
        self,
        db: AsyncSession,
        version_id: str = "v1.0"
    ) -> List[Dict[str, Any]]:
        """
        获取所有线切割工艺规则（从 price_items 表查询）
        
        Args:
            db: 数据库会话
            version_id: 版本ID（暂未使用）
        
        Returns:
            工艺规则列表
        """
        logger.info(f"📋 获取所有线切割工艺规则（price_items）")
        
        try:
            # 查询所有线切割工艺，按 sub_category 去重
            stmt = select(
                PriceItem.id,
                PriceItem.sub_category,
                PriceItem.note
            ).where(
                and_(
                    PriceItem.category == "wire",
                    PriceItem.is_active == True
                )
            ).distinct(PriceItem.sub_category)
            
            result = await db.execute(stmt)
            items = result.all()
            
            logger.info(f"✅ 找到 {len(items)} 条工艺规则")
            
            result_list = []
            for item in items:
                item_id, sub_category, note = item
                note = note or sub_category
                
                result_list.append({
                    "id": item_id,
                    "name": note,
                    "description": note,
                    "process_code": sub_category,
                    "conditions": sub_category,
                    "output_params": {},
                    "priority": 1
                })
            
            return result_list
        
        except Exception as e:
            logger.error(f"❌ 获取工艺规则失败: {e}", exc_info=True)
            return []
