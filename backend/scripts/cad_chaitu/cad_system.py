#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CAD分析系统主类
"""

import re
import ezdxf
import logging
from typing import Dict, List, Tuple
from loguru import logger
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 禁用 ezdxf 的日志输出
logging.getLogger('ezdxf').setLevel(logging.WARNING)

# 支持相对导入和绝对导入
try:
    from .block_analyzer import OptimizedCADBlockAnalyzer
    from .number_extractor import ProfessionalDrawingNumberExtractor
except ImportError:
    from block_analyzer import OptimizedCADBlockAnalyzer
    from number_extractor import ProfessionalDrawingNumberExtractor


class CADAnalysisSystem:
    """CAD分析系统主类"""

    def __init__(self):
        self.analyzer = OptimizedCADBlockAnalyzer()
        self.number_extractor = ProfessionalDrawingNumberExtractor()

    def _calculate_overlap_area(self, bounds1: Dict, bounds2: Dict) -> float:
        """计算两个边界框的重叠面积"""
        try:
            overlap_min_x = max(bounds1['min_x'], bounds2['min_x'])
            overlap_max_x = min(bounds1['max_x'], bounds2['max_x'])
            overlap_min_y = max(bounds1['min_y'], bounds2['min_y'])
            overlap_max_y = min(bounds1['max_y'], bounds2['max_y'])
            
            if overlap_min_x >= overlap_max_x or overlap_min_y >= overlap_max_y:
                return 0.0
            
            overlap_area = (overlap_max_x - overlap_min_x) * (overlap_max_y - overlap_min_y)
            return overlap_area
        except Exception:
            return 0.0

    def _translate_entity(self, entity, dx: float, dy: float):
        """平移单个CAD实体"""
        try:
            try:
                from ezdxf.math import Matrix44
                m = Matrix44.translate(dx, dy, 0)
                entity.transform(m)
                return
            except Exception:
                pass
            
            entity_type = entity.dxftype()
            
            if entity_type == 'LINE':
                start = entity.dxf.start
                end = entity.dxf.end
                entity.dxf.start = (start.x + dx, start.y + dy, start.z if hasattr(start, 'z') else 0)
                entity.dxf.end = (end.x + dx, end.y + dy, end.z if hasattr(end, 'z') else 0)
            
            elif entity_type in ['CIRCLE', 'ARC']:
                center = entity.dxf.center
                entity.dxf.center = (center.x + dx, center.y + dy, center.z if hasattr(center, 'z') else 0)
            
            elif entity_type == 'ELLIPSE':
                center = entity.dxf.center
                entity.dxf.center = (center.x + dx, center.y + dy, center.z if hasattr(center, 'z') else 0)
            
            elif entity_type in ['TEXT', 'ATTRIB', 'ATTDEF']:
                if hasattr(entity.dxf, 'insert'):
                    insert = entity.dxf.insert
                    entity.dxf.insert = (insert.x + dx, insert.y + dy, insert.z if hasattr(insert, 'z') else 0)
                elif hasattr(entity.dxf, 'position'):
                    pos = entity.dxf.position
                    entity.dxf.position = (pos.x + dx, pos.y + dy, pos.z if hasattr(pos, 'z') else 0)
            
            elif entity_type == 'MTEXT':
                insert = entity.dxf.insert
                entity.dxf.insert = (insert.x + dx, insert.y + dy, insert.z if hasattr(insert, 'z') else 0)
            
            elif entity_type in ['LWPOLYLINE', 'POLYLINE']:
                points = list(entity.get_points())
                new_points = []
                for pt in points:
                    if len(pt) >= 2:
                        new_pt = (pt[0] + dx, pt[1] + dy) + pt[2:]
                        new_points.append(new_pt)
                if new_points:
                    entity.set_points(new_points)
            
            elif entity_type == 'SPLINE':
                if hasattr(entity, 'control_points') and entity.control_points:
                    new_control_points = []
                    for pt in entity.control_points:
                        try:
                            if hasattr(pt, 'x'):
                                new_control_points.append((pt.x + dx, pt.y + dy, getattr(pt, 'z', 0)))
                            else:
                                new_control_points.append((pt[0] + dx, pt[1] + dy, pt[2] if len(pt) > 2 else 0))
                        except Exception:
                            new_control_points.append(pt)
                    entity.control_points = new_control_points
                
                if hasattr(entity, 'fit_points') and entity.fit_points:
                    new_fit_points = []
                    for pt in entity.fit_points:
                        new_fit_points.append((pt.x + dx, pt.y + dy, getattr(pt, 'z', 0)))
                    entity.fit_points = new_fit_points
            
            elif entity_type == 'INSERT':
                insert = entity.dxf.insert
                entity.dxf.insert = (insert.x + dx, insert.y + dy, insert.z if hasattr(insert, 'z') else 0)
            
            elif entity_type == 'DIMENSION':
                dimension_attrs = [
                    'defpoint', 'defpoint2', 'defpoint3', 'defpoint4',
                    'text_midpoint', 'dimline_point', 'insert'
                ]
                for attr in dimension_attrs:
                    if hasattr(entity.dxf, attr):
                        pt = getattr(entity.dxf, attr)
                        if pt is not None:
                            try:
                                setattr(entity.dxf, attr, (pt.x + dx, pt.y + dy, pt.z if hasattr(pt, 'z') else 0))
                            except Exception:
                                pass
            
            elif entity_type in ['LEADER', 'MLEADER']:
                if hasattr(entity, 'vertices'):
                    new_vertices = []
                    for pt in entity.vertices:
                        new_vertices.append((pt[0] + dx, pt[1] + dy, pt[2] if len(pt) > 2 else 0))
                    entity.vertices = new_vertices
            
            elif entity_type == 'SOLID':
                for i in range(4):
                    attr = f'vtx{i}'
                    if hasattr(entity.dxf, attr):
                        pt = getattr(entity.dxf, attr)
                        if pt:
                            setattr(entity.dxf, attr, (pt.x + dx, pt.y + dy, pt.z if hasattr(pt, 'z') else 0))
            
        except Exception as e:
            logger.debug(f"平移实体失败 ({entity.dxftype() if hasattr(entity, 'dxftype') else 'unknown'}): {e}")

    
    def batch_export_regions_concurrent(self, export_list: List[Dict], pad: float = 0.0, 
                                       horizontal_spacing: float = 50.0, align_to_origin: bool = True,
                                       max_workers: int = 5) -> List[Dict]:
        """
        批量导出子图（顺序处理，共享源文档对象以提升性能）
        
        Args:
            export_list: 导出列表
            pad: 边界扩展值
            horizontal_spacing: 水平间距
            align_to_origin: 是否对齐到原点
            max_workers: 最大并发数（已废弃，保留参数以兼容旧代码）
        
        Returns:
            导出结果列表
        """
        if not self.analyzer.sub_drawings or not self.analyzer.source_path:
            return [{'sub_code': item['sub_code'], 'success': False, 'error': '未提取到子图或未加载源文件'} 
                    for item in export_list]
        
        if not export_list:
            return []
        
        logger.info(f"🚀 开始导出 {len(export_list)} 个子图（顺序处理，共享文档对象）")
        
        # 只读取一次文件到 doc 对象
        logger.info(f"📖 读取源文件...")
        try:
            read_start = datetime.now()
            source_path = str(self.analyzer.source_path)
            source_doc = ezdxf.readfile(source_path)
            source_msp = source_doc.modelspace()
            read_time = (datetime.now() - read_start).total_seconds()
            logger.info(f"✅ 文件读取完成 (耗时: {read_time:.2f}s)")
        except Exception as e:
            error_msg = f"读取文件失败: {e}"
            logger.error(f"❌ {error_msg}")
            return [{'sub_code': item['sub_code'], 'success': False, 'error': error_msg} 
                    for item in export_list]
        
        results = []
        success_count = 0
        failed_count = 0
        start_time = datetime.now()
        
        # 顺序处理所有子图
        for i, item in enumerate(export_list, 1):
            try:
                result = self._export_single_region_from_doc(
                    sub_code=item['sub_code'],
                    region=item['region'],
                    output_path=item['output_path'],
                    source_doc=source_doc,
                    source_msp=source_msp,
                    pad=pad,
                    align_to_origin=align_to_origin
                )
                results.append(result)
                
                if result['success']:
                    success_count += 1
                    # 每10个打印一次进度
                    if success_count % 10 == 0:
                        elapsed = (datetime.now() - start_time).total_seconds()
                        avg_time = elapsed / success_count
                        remaining = (len(export_list) - success_count) * avg_time
                        logger.info(
                            f"📊 导出进度: {success_count}/{len(export_list)} "
                            f"(平均: {avg_time:.1f}s/个, 预计剩余: {remaining:.0f}s)"
                        )
                else:
                    failed_count += 1
                    logger.warning(f"⚠️ 导出失败: {item['sub_code']} - {result.get('error', '未知错误')}")
                    
            except Exception as e:
                failed_count += 1
                results.append({
                    'sub_code': item['sub_code'],
                    'success': False,
                    'error': str(e)
                })
                logger.error(f"❌ 导出异常: {item['sub_code']} - {e}")
        
        total_time = (datetime.now() - start_time).total_seconds()
        avg_time = total_time / len(export_list) if export_list else 0
        logger.info(
            f"✅ 导出完成: {success_count}/{len(export_list)} 成功, "
            f"总耗时: {total_time:.1f}s, 平均: {avg_time:.1f}s/个"
        )
        
        return results
    


    
    def _copy_text_styles(self, source_doc, target_doc):
        """复制文字样式"""
        try:
            for text_style in source_doc.styles:
                style_name = text_style.dxf.name
                if style_name not in target_doc.styles:
                    new_text_style = target_doc.styles.new(style_name)
                else:
                    new_text_style = target_doc.styles.get(style_name)
                
                # 复制所有文字样式属性
                attrs_to_copy = ['font', 'bigfont', 'height', 'width', 'oblique', 'flags', 'generation_flags']
                for attr in attrs_to_copy:
                    try:
                        if hasattr(text_style.dxf, attr):
                            setattr(new_text_style.dxf, attr, getattr(text_style.dxf, attr))
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"复制文字样式失败: {e}")

    def _copy_dimension_styles(self, source_doc, target_doc):
        """复制标注样式（完整属性）"""
        try:
            for dim_style in source_doc.dimstyles:
                style_name = dim_style.dxf.name
                if style_name not in target_doc.dimstyles:
                    target_doc.dimstyles.new(style_name)
                new_dim = target_doc.dimstyles.get(style_name)
                
                # 复制所有标注样式属性（关键：包含小数位数和零抑制）
                dim_attrs_to_copy = [
                    # 文字相关
                    'dimtxsty', 'dimtxt', 'dimtad', 'dimgap', 'dimjust', 'dimtih', 'dimtoh',
                    # 数值格式（关键属性）
                    'dimdec', 'dimzin', 'dimlunit', 'dimdsep', 'dimrnd', 'dimtfac',
                    # 线条和箭头
                    'dimscale', 'dimasz', 'dimblk', 'dimblk1', 'dimblk2', 'dimdle', 'dimdli',
                    'dimexe', 'dimexo', 'dimclrd', 'dimclre', 'dimclrt',
                    # 单位和测量
                    'dimlfac', 'dimpost', 'dimapost', 'dimalt', 'dimaltd', 'dimaltf',
                    # 公差
                    'dimtol', 'dimlim', 'dimtp', 'dimtm', 'dimtolj',
                    # 其他
                    'dimse1', 'dimse2', 'dimfrac', 'dimlwd', 'dimlwe'
                ]
                
                for attr in dim_attrs_to_copy:
                    try:
                        if hasattr(dim_style.dxf, attr):
                            setattr(new_dim.dxf, attr, getattr(dim_style.dxf, attr))
                    except Exception:
                        pass
                
                # 特别处理测量值（保留原始设置）
                try:
                    if hasattr(dim_style, 'dxfattribs'):
                        for key, value in dim_style.dxfattribs().items():
                            if key not in ['handle', 'owner']:
                                try:
                                    setattr(new_dim.dxf, key, value)
                                except Exception:
                                    pass
                except Exception:
                    pass
                
                # 显式保证小数点分隔符和小数位数与原图一致
                try:
                    if hasattr(dim_style.dxf, 'dimdsep'):
                        new_dim.dxf.dimdsep = dim_style.dxf.dimdsep
                    else:
                        new_dim.dxf.dimdsep = '.'
                except Exception:
                    new_dim.dxf.dimdsep = '.'
                    
                try:
                    if hasattr(dim_style.dxf, 'dimdec'):
                        new_dim.dxf.dimdec = dim_style.dxf.dimdec
                except Exception:
                    pass
                    
        except Exception as e:
            logger.debug(f"复制标注样式失败: {e}")

    def _copy_block_definitions(self, source_doc, target_doc):
        """复制块定义"""
        try:
            for src_block in source_doc.blocks:
                block_name = src_block.dxf.name
                # 跳过模型空间和图纸空间
                if block_name in ('*Model_Space', '*Paper_Space', '*Paper_Space0'):
                    continue
                # 如果新文档中没有这个块，则创建
                if block_name not in target_doc.blocks:
                    try:
                        new_block = target_doc.blocks.new(name=block_name)
                        # 复制块的属性
                        try:
                            new_block.dxf.description = src_block.dxf.description
                        except Exception:
                            pass
                        try:
                            new_block.dxf.base_point = src_block.dxf.base_point
                        except Exception:
                            pass
                    except Exception as e:
                        logger.debug(f"创建块 {block_name} 时出错: {e}")
        except Exception as e:
            logger.debug(f"复制块定义失败: {e}")

    def _copy_styles_to_new_doc(self, source_doc, target_doc):
        """
        复制样式定义到新文档（仅复制必要的样式，避免与 Importer 冲突）
        
        注意：不复制图层和线型，让 Importer 自动处理
        """
        try:
            # 1. 复制文字样式（标注依赖文字样式）
            self._copy_text_styles(source_doc, target_doc)
            
            # 2. 复制标注样式（完整复制所有属性）
            self._copy_dimension_styles(source_doc, target_doc)
            
            # 3. 复制块定义（只创建空块，让 Importer 填充内容）
            self._copy_block_definitions(source_doc, target_doc)
            
            # 注意：不复制图层和线型，让 Importer 自动处理
            # 这样可以避免句柄冲突和引用问题
            
        except Exception as e:
            logger.warning(f"复制样式定义失败: {e}")

    def _fix_dimension_styles(self, target_msp, target_doc):
        """修正标注样式，确保一致性"""
        try:
            # 强制所有DIMENSION实体使用指定的dimstyle和dimtxsty
            force_dimstyle_name = None
            # 自动选择原图中第一个非Standard的dimstyle作为默认
            for ds in target_doc.dimstyles:
                if ds.dxf.name != 'Standard':
                    force_dimstyle_name = ds.dxf.name
                    break
            if not force_dimstyle_name:
                force_dimstyle_name = 'Standard'

            # 获取该dimstyle对应的dimtxsty
            force_dimtxsty = None
            try:
                force_dimtxsty = target_doc.dimstyles.get(force_dimstyle_name).dxf.dimtxsty
            except Exception:
                force_dimtxsty = 'Standard'

            for dim in target_msp.query('DIMENSION'):
                try:
                    dim.dxf.dimstyle = force_dimstyle_name
                    # 强制dimtxsty（标注用文字样式）
                    if hasattr(dim.dxf, 'dimtxsty'):
                        dim.dxf.dimtxsty = force_dimtxsty
                    # 兼容部分CAD只认dimstyle里的dimtxsty
                    ds = target_doc.dimstyles.get(force_dimstyle_name)
                    if ds and hasattr(ds.dxf, 'dimtxsty'):
                        ds.dxf.dimtxsty = force_dimtxsty
                except Exception as e:
                    logger.debug(f"修正DIMENSION样式失败: {e}")
        except Exception as e:
            logger.debug(f"修正标注样式失败: {e}")

    def _export_single_region_from_doc(self, sub_code: str, region: Dict, output_path: str,
                                       source_doc, source_msp, pad: float, align_to_origin: bool) -> Dict:
        """
        导出单个子图（从已解析的文档对象）- 使用高效复制方式（参考 dxf_split_s1230.py）
        
        优化点：
        1. 简化边界判断逻辑（使用简单的 intersect 函数）
        2. 使用 Importer 批量导入实体
        3. 简化对齐逻辑
        
        Args:
            sub_code: 子图编号
            region: 子图区域信息
            output_path: 输出路径
            source_doc: 源文档对象
            source_msp: 源模型空间
            pad: 边界扩展值
            align_to_origin: 是否对齐到原点
        
        Returns:
            导出结果字典
        """
        try:
            from ezdxf.addons import Importer
            step_start = datetime.now()
            
            # 精确的边界判断函数：两步判断策略
            def is_entity_in_region(ent_bounds: Dict, target_bounds: Dict) -> bool:
                """
                判断实体是否应该被包含在目标区域中
                
                策略：
                1. 对于 INSERT 实体：
                   - 第一步：检查插入点是否在目标区域内
                   - 第二步：如果插入点在内，计算块内图形的几何中心，再次判断
                2. 对于其他实体：
                   - 检查中心点是否在目标区域内
                   - 或者实体完全在目标区域内
                
                Args:
                    ent_bounds: 实体边界
                    target_bounds: 目标区域边界
                """
                # 特殊处理：INSERT 实体（块引用）
                if ent_bounds.get('_is_insert', False):
                    # 第一步：检查插入点是否在目标区域内
                    insert_x = (ent_bounds['min_x'] + ent_bounds['max_x']) / 2
                    insert_y = (ent_bounds['min_y'] + ent_bounds['max_y']) / 2
                    
                    insert_in_region = (
                        target_bounds['min_x'] <= insert_x <= target_bounds['max_x'] and
                        target_bounds['min_y'] <= insert_y <= target_bounds['max_y']
                    )
                    
                    # 如果插入点不在区域内，直接排除
                    if not insert_in_region:
                        return False
                    
                    # 第二步：插入点在区域内，计算块内图形的实际几何中心
                    try:
                        insert_entity = ent_bounds.get('_insert_entity')
                        blocks_doc = ent_bounds.get('_blocks_doc')
                        
                        if insert_entity and blocks_doc:
                            block_name = insert_entity.dxf.name
                            block_def = blocks_doc.get(block_name)
                            
                            if block_def:
                                # 计算块的实际边界
                                from scripts.cad_chaitu.block_analyzer import OptimizedCADBlockAnalyzer
                                analyzer = OptimizedCADBlockAnalyzer()
                                block_bounds = analyzer._calculate_block_bounds(block_def, insert_entity)
                                
                                if block_bounds:
                                    # 使用块的几何中心判断
                                    block_center_x = (block_bounds['min_x'] + block_bounds['max_x']) / 2
                                    block_center_y = (block_bounds['min_y'] + block_bounds['max_y']) / 2
                                    
                                    return (
                                        target_bounds['min_x'] <= block_center_x <= target_bounds['max_x'] and
                                        target_bounds['min_y'] <= block_center_y <= target_bounds['max_y']
                                    )
                    except Exception:
                        pass
                    
                    # 兜底：如果无法计算块边界，使用插入点判断
                    return insert_in_region
                
                # 普通实体：计算中心点
                ent_center_x = (ent_bounds['min_x'] + ent_bounds['max_x']) / 2
                ent_center_y = (ent_bounds['min_y'] + ent_bounds['max_y']) / 2
                
                # 策略1：中心点必须在目标区域内部（使用 <= 允许边界上的实体）
                if (target_bounds['min_x'] <= ent_center_x <= target_bounds['max_x'] and
                    target_bounds['min_y'] <= ent_center_y <= target_bounds['max_y']):
                    return True
                
                # 策略2：实体完全在目标区域内
                if (ent_bounds['min_x'] >= target_bounds['min_x'] and
                    ent_bounds['max_x'] <= target_bounds['max_x'] and
                    ent_bounds['min_y'] >= target_bounds['min_y'] and
                    ent_bounds['max_y'] <= target_bounds['max_y']):
                    return True
                
                return False
            
            # 计算目标边界（加上 pad）
            bounds = region['bounds']
            target_bound = {
                'min_x': bounds['min_x'] - pad,
                'max_x': bounds['max_x'] + pad,
                'min_y': bounds['min_y'] - pad,
                'max_y': bounds['max_y'] + pad
            }
            
            # 步骤1: 筛选需要复制的实体（使用严格的中心点判断）
            select_start = datetime.now()
            selected_entities = []
            skipped_entities = 0
            
            for ent in source_msp:
                try:
                    # 获取实体边界
                    ent_bounds = self.analyzer._compute_entity_bounds(ent, source_doc.blocks)
                    
                    if not ent_bounds:
                        continue
                    
                    # 严格判断：只有中心点在目标区域内的实体才包含
                    if is_entity_in_region(ent_bounds, target_bound):
                        selected_entities.append(ent)
                    else:
                        skipped_entities += 1
                        
                except Exception:
                    continue
            
            select_time = (datetime.now() - select_start).total_seconds()
            logger.debug(
                f"[{sub_code}] 筛选实体: {select_time:.2f}s "
                f"(选中: {len(selected_entities)}, 跳过: {skipped_entities})"
            )
            
            if len(selected_entities) == 0:
                logger.warning(f"[{sub_code}] 未找到匹配的实体")
                return {
                    'sub_code': sub_code,
                    'success': False,
                    'error': '未找到匹配的实体'
                }
            
            # 步骤2: 创建新文档并复制样式（参考 dxf_split_s1230.py）
            copy_start = datetime.now()
            new_doc = ezdxf.new(dxfversion=source_doc.dxfversion)
            try:
                new_doc.units = source_doc.units
            except:
                pass
            
            # 复制样式（只复制文字样式、标注样式、空块定义，不复制图层和线型）
            self._copy_styles_to_new_doc(source_doc, new_doc)
            
            # 步骤3: 使用 Importer 批量导入实体
            target_msp = new_doc.modelspace()
            importer = Importer(source_doc, new_doc)
            importer.import_entities(selected_entities, target_msp)
            importer.finalize()
            
            copy_time = (datetime.now() - copy_start).total_seconds()
            logger.debug(f"[{sub_code}] 复制实体: {copy_time:.2f}s")
            
            # 步骤4: 修正标注样式
            self._fix_dimension_styles(target_msp, new_doc)
            
            # 步骤5: 对齐到原点（简化逻辑）
            if align_to_origin:
                align_start = datetime.now()
                offset_x = -bounds['min_x']
                offset_y = -bounds['min_y']
                
                # 直接平移所有实体
                for ent in target_msp:
                    try:
                        self._translate_entity(ent, offset_x, offset_y)
                    except:
                        continue
                
                align_time = (datetime.now() - align_start).total_seconds()
                logger.debug(f"[{sub_code}] 对齐原点: {align_time:.2f}s")
            
            # 步骤6: 保存文件
            save_start = datetime.now()
            new_doc.saveas(output_path)
            save_time = (datetime.now() - save_start).total_seconds()
            
            total_time = (datetime.now() - step_start).total_seconds()
            logger.debug(
                f"[{sub_code}] ✅ 导出成功: {total_time:.2f}s "
                f"(筛选:{select_time:.1f}s, 复制:{copy_time:.1f}s, 保存:{save_time:.1f}s)"
            )
            
            return {
                'sub_code': sub_code,
                'success': True,
                'output_path': output_path
            }
            
        except Exception as e:
            logger.error(f"[{sub_code}] ❌ 导出失败: {e}")
            import traceback
            logger.debug(f"[{sub_code}] 错误详情: {traceback.format_exc()}")
            return {
                'sub_code': sub_code,
                'success': False,
                'error': str(e)
            }
    

    def clear_cache(self):
        """清理缓存的 DXF 文档和分析器缓存，释放内存"""
        # 清理分析器缓存
        if self.analyzer:
            self.analyzer.clear_cache()
        
        # 清理数字提取器缓存（如果有的话）
        if self.number_extractor:
            # number_extractor 目前没有缓存，但保留接口以备将来使用
            pass
