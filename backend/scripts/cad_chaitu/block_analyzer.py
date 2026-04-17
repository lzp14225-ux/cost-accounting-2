#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CAD块分析模块
"""

import re
import math
import ezdxf
from typing import Optional, Dict, List, Tuple
from pathlib import Path
from loguru import logger

# 支持相对导入和绝对导入
try:
    from .text_processor import IntelligentTextProcessor
    from .cutting_detector import RelaxedCuttingDetector
    from .number_extractor import ProfessionalDrawingNumberExtractor
except ImportError:
    from text_processor import IntelligentTextProcessor
    from cutting_detector import RelaxedCuttingDetector
    from number_extractor import ProfessionalDrawingNumberExtractor


class OptimizedCADBlockAnalyzer:
    """优化的CAD块分析器"""

    def __init__(self):
        self.all_texts = []
        self.all_entities = []
        self.frame_blocks = []
        self.sub_drawings = {}
        self.layer_colors = {}
        self.text_processor = IntelligentTextProcessor()
        self.cutting_detector = RelaxedCuttingDetector()
        self.number_extractor = ProfessionalDrawingNumberExtractor()
        self.doc = None
        self.msp = None
        self.classify_map = None
        self.source_path: Optional[str] = None

    def analyze_cad_file(self, file_path: str) -> Dict:
        """分析CAD文件，提取子图（批量模式，保留向后兼容）"""
        try:
            doc = ezdxf.readfile(file_path)
            msp = doc.modelspace()
            self.doc = doc
            self.msp = msp
            self.source_path = file_path

            self._extract_layer_colors(doc)
            self._extract_all_texts(msp)
            self._extract_all_entities(msp)
            self._identify_frame_blocks(msp)
            self._create_subdrawing_regions()
            self._assign_texts_to_regions()
            self._analyze_cutting_contours_for_regions()
            
            # 预先识别所有子图的品名并缓存（避免并行处理时重复识别）
            self._preload_part_names()

            logger.info(f"识别出 {len(self.sub_drawings)} 个子图")
            return self.sub_drawings
        except Exception as e:
            logger.error(f"分析失败: {str(e)}")
            return {}
    
    def analyze_cad_file_streaming(self, file_path: str):
        """
        流式分析CAD文件，逐个识别并 yield 子图
        
        Yields:
            tuple: (region_id, region_dict, index, total)
        """
        try:
            doc = ezdxf.readfile(file_path)
            msp = doc.modelspace()
            self.doc = doc
            self.msp = msp
            self.source_path = file_path

            # 1. 提取基础数据（必须一次性完成）
            logger.info("提取图层颜色...")
            self._extract_layer_colors(doc)
            
            # 1. 一次性识别所有子图
            self._extract_all_texts(msp)
            self._extract_all_entities(msp)
            self._identify_frame_blocks(msp)
            self._create_subdrawing_regions()
            self._assign_texts_to_regions()
            
            # 跳过耗时的切割轮廓分析（不影响导出功能）
            # self._analyze_cutting_contours_for_regions()
            
            total = len(self.sub_drawings)
            logger.info(f"✅ 识别出 {total} 个子图")
            
            # 2. 逐个 yield 子图（流式处理）
            for index, (region_id, region) in enumerate(self.sub_drawings.items(), start=1):
                # 直接 yield，不预先识别品名（在后续步骤中统一识别）
                yield region_id, region, index, total
                
        except Exception as e:
            logger.error(f"流式分析失败: {str(e)}")
            return

    def _safe_spline_points(self, entity):
        """安全获取SPLINE点"""
        pts = []
        try:
            if hasattr(entity, 'control_points') and entity.control_points:
                for p in entity.control_points:
                    try:
                        pts.append((float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0))
                    except Exception:
                        pts.append((float(p.x), float(p.y), float(getattr(p, 'z', 0.0))))
            if not pts and hasattr(entity, 'fit_points') and entity.fit_points:
                for p in entity.fit_points:
                    pts.append((float(p.x), float(p.y), float(getattr(p, 'z', 0.0))))
        except Exception:
            pass
        return pts

    def _point_in_bounds(self, pt, bounds: Dict) -> bool:
        """判断点是否在区域内"""
        if pt is None:
            return False
        x, y = pt
        return (bounds['min_x'] <= x <= bounds['max_x']) and (bounds['min_y'] <= y <= bounds['max_y'])

    def _compute_entity_bounds(self, e, blocks_doc) -> Optional[Dict]:
        """
        计算实体边界框（优化版本 - 简化计算以提升性能）
        
        性能优化：
        1. 移除 bbox() 调用（慢19倍）
        2. 简化 DIMENSION 等实体的处理
        3. 简化 INSERT 块的边界计算
        """
        try:
            entity_type = e.dxftype()

            if entity_type == 'LINE':
                start, end = e.dxf.start, e.dxf.end
                return {
                    'min_x': min(start.x, end.x),
                    'max_x': max(start.x, end.x),
                    'min_y': min(start.y, end.y),
                    'max_y': max(start.y, end.y)
                }

            elif entity_type in ('CIRCLE', 'ARC'):
                center = e.dxf.center
                radius = float(e.dxf.radius)
                return {
                    'min_x': center.x - radius,
                    'max_x': center.x + radius,
                    'min_y': center.y - radius,
                    'max_y': center.y + radius
                }

            elif entity_type in ('LWPOLYLINE', 'POLYLINE'):
                try:
                    pts = e.get_points(format='xy')
                    if pts:
                        xs, ys = zip(*pts)
                        return {
                            'min_x': min(xs),
                            'max_x': max(xs),
                            'min_y': min(ys),
                            'max_y': max(ys)
                        }
                except Exception:
                    return None

            elif entity_type == 'ELLIPSE':
                center = e.dxf.center
                major_axis = e.dxf.major_axis
                ratio = float(getattr(e.dxf, 'ratio', 0.5) or 0.5)
                # 简化：直接使用主轴长度
                return {
                    'min_x': center.x - major_axis.x,
                    'max_x': center.x + major_axis.x,
                    'min_y': center.y - (major_axis.y * ratio),
                    'max_y': center.y + (major_axis.y * ratio)
                }

            elif entity_type == 'SPLINE':
                # 使用控制点或拟合点计算边界
                pts = self._safe_spline_points(e)
                if pts:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    return {
                        'min_x': min(xs),
                        'max_x': max(xs),
                        'min_y': min(ys),
                        'max_y': max(ys)
                    }
                return None

            elif entity_type in ('TEXT', 'ATTRIB', 'ATTDEF'):
                pos = getattr(e.dxf, 'insert', None) or getattr(e.dxf, 'pos', None)
                if not pos:
                    return None
                height = float(getattr(e.dxf, 'height', 2.5) or 2.5)
                width = height * 5
                return {
                    'min_x': pos.x,
                    'max_x': pos.x + width,
                    'min_y': pos.y,
                    'max_y': pos.y + height
                }
            
            elif entity_type == 'MTEXT':
                pos = getattr(e.dxf, 'insert', None)
                if not pos:
                    return None
                height = float(getattr(e.dxf, 'char_height', 2.5) or 2.5)
                width = float(getattr(e.dxf, 'width', height * 10) or height * 10)
                return {
                    'min_x': pos.x,
                    'max_x': pos.x + width,
                    'min_y': pos.y,
                    'max_y': pos.y + height * 3  # 估算多行文字高度
                }
            
            elif entity_type == 'DIMENSION':
                # 简化：使用标注的定义点来估算边界
                try:
                    defpoint = e.dxf.defpoint
                    text_pos = getattr(e.dxf, 'text_midpoint', None) or getattr(e.dxf, 'text_location', None) or defpoint
                    
                    # 使用两个点来估算边界
                    min_x = min(defpoint.x, text_pos.x) - 50
                    max_x = max(defpoint.x, text_pos.x) + 50
                    min_y = min(defpoint.y, text_pos.y) - 50
                    max_y = max(defpoint.y, text_pos.y) + 50
                    
                    return {
                        'min_x': min_x,
                        'max_x': max_x,
                        'min_y': min_y,
                        'max_y': max_y
                    }
                except Exception:
                    return None
            
            elif entity_type in ('HATCH', 'SOLID', 'LEADER', 'MLEADER'):
                # 简化：使用中心点估算（这些实体在拆图时不是关键）
                c = self._calculate_entity_center(e)
                if c:
                    cx, cy = c
                    pad = 100.0
                    return {
                        'min_x': cx - pad,
                        'max_x': cx + pad,
                        'min_y': cy - pad,
                        'max_y': cy + pad
                    }
                return None

            elif entity_type == 'INSERT':
                # 优化策略：
                # 1. 先返回插入点作为初步边界（用于快速筛选）
                # 2. 在 cad_system.py 中，如果插入点在区域内，再计算详细边界
                ins = getattr(e.dxf, 'insert', None)
                if ins:
                    # 返回插入点信息，同时标记这是一个 INSERT 实体
                    # 使用极小的边界，确保中心点就是插入点
                    epsilon = 0.01
                    return {
                        'min_x': ins.x - epsilon,
                        'max_x': ins.x + epsilon,
                        'min_y': ins.y - epsilon,
                        'max_y': ins.y + epsilon,
                        '_is_insert': True,  # 标记为 INSERT 实体
                        '_insert_entity': e,  # 保存实体引用（用于后续详细计算）
                        '_blocks_doc': blocks_doc  # 保存 blocks 引用
                    }

        except Exception:
            return None

    def resolve_region_name(self, region_id: str, region: Dict) -> str:
        """生成子图文件名"""
        fname = self.number_extractor.extract_region_filename_by_patterns(region)
        if not fname:
            drawing_number = self.number_extractor.extract_drawing_number_from_region(region)
            if drawing_number:
                fname = self.number_extractor.generate_safe_filename(drawing_number)
        if not fname:
            texts = region.get('texts', [])
            text_contents = [t.get('content', '') for t in texts[:20]]
            logger.warning(f"[识别失败] {region_id}, 文本: {text_contents}")
            # 使用 region_id 作为默认文件名（格式：subdrawing_001）
            fname = region_id
        return fname
    
    def resolve_region_info(self, region_id: str, region: Dict) -> tuple[str, Optional[str], Optional[str]]:
        """
        同时识别子图编号、品名和编号（避免重复识别）
        
        Returns:
            tuple: (sub_code, part_name, part_code)
            - sub_code: 优先使用识别出的编号，如果没有则使用 region_id
            - part_name: 零件名称
            - part_code: 零件编号（从图纸中识别）
        """
        # 识别品名（会使用缓存机制）
        part_name = self.extract_part_name(region)
        
        # 识别编号（会使用缓存机制）
        part_code = self.extract_part_code(region)
        
        # 尝试从文件名模式中提取编号
        fname = self.number_extractor.extract_region_filename_by_patterns(region)
        
        # 确定 sub_code 的优先级：
        # 1. 优先使用 part_code（零件编号）
        # 2. 其次使用 fname（文件名模式识别）
        # 3. 最后使用 region_id（兜底）
        if part_code:
            sub_code = part_code
        elif fname and fname != region_id:
            sub_code = fname
        else:
            sub_code = region_id
        
        # 如果 part_code 为空，使用 sub_code 作为默认值
        if not part_code:
            part_code = sub_code
        
        return sub_code, part_name, part_code

    def _log_region_texts_for_debug(self, region: Dict, reason: str) -> None:
        """记录子图中的文本详情，便于定位识别失败原因。"""
        texts = region.get('texts', []) or []
        region_id = region.get('_region_id', 'unknown')

        text_details = []
        for idx, text in enumerate(texts, start=1):
            text_details.append({
                'idx': idx,
                'content': (text.get('content') or '').strip(),
                'position': text.get('position'),
                'layer': text.get('layer', ''),
                'entity_type': text.get('entity_type', ''),
            })

        logger.warning(
            f"⚠️ 子图文本诊断 [{reason}] region={region_id}, "
            f"text_count={len(texts)}, texts={text_details}"
        )

    def _log_region_bounds_summary(self) -> None:
        """记录各子图边界，便于判断 region 是否划分异常。"""
        summaries = []
        for rid, region in self.sub_drawings.items():
            bounds = region.get('bounds') or {}
            summaries.append({
                'region': rid,
                'min_x': round(bounds.get('min_x', 0.0), 2),
                'max_x': round(bounds.get('max_x', 0.0), 2),
                'min_y': round(bounds.get('min_y', 0.0), 2),
                'max_y': round(bounds.get('max_y', 0.0), 2),
                'width': round(bounds.get('width', 0.0), 2),
                'height': round(bounds.get('height', 0.0), 2),
            })

        logger.info(f"子图边界诊断: {summaries}")

    def _log_key_text_assignments(self) -> None:
        """记录关键标题栏/编号文本最终被分配到哪个子图。"""
        keyword_patterns = [
            re.compile(r'品名|名称|编号|图号|加工说明', re.IGNORECASE),
            re.compile(r'\b(?:DIE|PU|PS|LB|UB|BL|SB|BUP|BUN|M)\b[-]?\d+', re.IGNORECASE),
            re.compile(r'(?:DIE|PU|PS|LB|UB|BL|SB)[A-Z0-9\\-]*', re.IGNORECASE),
        ]

        assignments = []
        for rid, region in self.sub_drawings.items():
            for text in region.get('texts', []) or []:
                content = (text.get('content') or '').strip()
                if not content:
                    continue
                if any(pattern.search(content) for pattern in keyword_patterns):
                    assignments.append({
                        'region': rid,
                        'content': content,
                        'position': text.get('position'),
                        'layer': text.get('layer', ''),
                        'entity_type': text.get('entity_type', ''),
                    })

        logger.info(f"关键文本归属诊断: match_count={len(assignments)}, assignments={assignments}")

    def _log_region_assignment_summary(self) -> None:
        """记录每个子图的来源图框、文本数、实体数、关键编号命中数。"""
        code_patterns = [
            re.compile(r'(?:DIE|PU|PS|LB|UB|BL|SB)[A-Z0-9\-]*', re.IGNORECASE),
            re.compile(r'\b[A-Z]{1,5}-\d+\b', re.IGNORECASE),
            re.compile(r'\b[A-Z]+\d+(?:-\d+)?\b', re.IGNORECASE),
        ]

        summaries = []
        for rid, region in self.sub_drawings.items():
            bounds = region.get('bounds') or {}
            frame_block = region.get('frame_block') or {}

            entity_count = 0
            for entity in self.all_entities:
                center = entity.get('center')
                if self._point_in_bounds(center, bounds):
                    entity_count += 1

            key_code_hits = []
            for text in region.get('texts', []) or []:
                content = (text.get('content') or '').strip()
                if not content:
                    continue
                if any(pattern.search(content) for pattern in code_patterns):
                    key_code_hits.append(content)

            summaries.append({
                'region': rid,
                'frame_block': frame_block.get('block_name'),
                'insert_point': frame_block.get('insert_point'),
                'text_count': len(region.get('texts', []) or []),
                'entity_count': entity_count,
                'key_code_hit_count': len(key_code_hits),
                'key_code_hits': key_code_hits[:12],
            })

        logger.info(f"子图归属摘要诊断: {summaries}")

    def extract_part_name(self, region: Dict) -> Optional[str]:
        """提取品名（零件名称）"""
        # 如果已经缓存了品名，直接返回
        if '_cached_part_name' in region:
            return region['_cached_part_name']
        
        texts = region.get('texts', []) or []
        process_note_keywords = [
            '外形割单', '倒角', '全周倒角', '热处理', '线割', '攻牙', '沉头',
            '割单', '加工说明', '备料', '淬火', '磨床', '铣床', '钻孔',
        ]

        def is_process_note_text(content: str) -> bool:
            return any(keyword in content for keyword in process_note_keywords)
        
        # 多种品名标签模式
        label_patterns = [
            re.compile(r'^\s*品\s*名\s*[:：]?\s*(.*)$', re.IGNORECASE),
            re.compile(r'^\s*零件名称\s*[:：]?\s*(.*)$', re.IGNORECASE),
            re.compile(r'^\s*名\s*称\s*[:：]?\s*(.*)$', re.IGNORECASE),
            re.compile(r'^\s*部件名称\s*[:：]?\s*(.*)$', re.IGNORECASE),
            re.compile(r'^\s*零件\s*[:：]?\s*(.*)$', re.IGNORECASE),
        ]
        
        # 1. 优先从加工说明提取，避免被“外形割单/倒角”等工艺说明误命中
        processing_pattern = re.compile(r'加工说明\s*[:：]\s*[（(]([^)）]+)[)）]', re.IGNORECASE)
        processing_with_code_pattern = re.compile(r'加工说明\s*[:：]\s*_?\s*[（(]([^)）]+)[)）]\s*_?\s*([A-Z0-9\-]+)', re.IGNORECASE)
        processing_fallback_pattern = re.compile(r'加工说明\s*[:：]\s*_?\s*([\u4e00-\u9fa5]+)\s*_?\s*([A-Z0-9\-]+)', re.IGNORECASE)

        for t in texts:
            c = (t.get('content') or '').strip()
            if not c:
                continue
            
            m_with_code = processing_with_code_pattern.search(c)
            if m_with_code:
                part_name = m_with_code.group(1).strip()
                part_code = m_with_code.group(2).strip()
                if part_name and len(part_name) > 1:
                    region['_cached_part_name'] = part_name
                    region['_cached_part_code'] = part_code
                    logger.info(f"✅ 从加工说明中提取品名和编号（带括号）: 品名='{part_name}', 编号='{part_code}'")
                    return part_name
            
            m_fallback = processing_fallback_pattern.search(c)
            if m_fallback:
                part_name = m_fallback.group(1).strip()
                part_code = m_fallback.group(2).strip()
                if part_name and len(part_name) > 1:
                    region['_cached_part_name'] = part_name
                    region['_cached_part_code'] = part_code
                    logger.info(f"✅ 从加工说明中提取品名和编号（兜底机制）: 品名='{part_name}', 编号='{part_code}'")
                    return part_name
            
            m = processing_pattern.search(c)
            if m:
                part_name = m.group(1).strip()
                if part_name and len(part_name) > 1:
                    region['_cached_part_name'] = part_name
                    logger.info(f"✅ 从加工说明中提取品名（仅品名）: 品名='{part_name}'")
                    return part_name

        # 2. 再尝试匹配标签模式（品名:xxx 或 品名 xxx）
        for i, t in enumerate(texts):
            c = (t.get('content') or '').strip()
            if not c:
                continue
            
            for label_re in label_patterns:
                m = label_re.match(c)
                if m:
                    # 如果标签后面直接有内容（品名:下模座）
                    inline_val = (m.group(1) or '').strip()
                    if inline_val and len(inline_val) > 1:
                        if is_process_note_text(inline_val):
                            logger.info(f"⚠️ 跳过疑似工艺说明的品名内联值: '{inline_val}'")
                            continue
                        region['_cached_part_name'] = inline_val
                        return inline_val
                    
                    # 如果标签后面没有内容，查找下一个文本
                    for j in range(i + 1, min(i + 6, len(texts))):
                        nxt = (texts[j].get('content') or '').strip()
                        if nxt and len(nxt) > 1:
                            # 排除其他标签
                            is_label = any(lp.match(nxt) for lp in label_patterns)
                            if not is_label:
                                if is_process_note_text(nxt):
                                    logger.info(f"⚠️ 跳过疑似工艺说明的品名候选: '{nxt}'")
                                    continue
                                region['_cached_part_name'] = nxt
                                return nxt
        
        # 3. 如果没有找到标签，尝试查找标题框区域的大字体文本
        # 通常品名会在图纸右下角的标题栏中，字体较大
        title_candidates = []
        for t in texts:
            c = (t.get('content') or '').strip()
            if not c or len(c) < 2:
                continue
            
            # 排除明显的非品名文本
            if any(keyword in c for keyword in ['材料', '数量', '比例', '图号', '日期', '设计', '审核', '制图']):
                continue
            if is_process_note_text(c):
                continue
            
            # 排除纯数字、尺寸标注等
            if re.match(r'^[\d\.\-\+\s]+$', c):
                continue
            if re.match(r'^\d+\.?\d*[LWTHDRC]$', c):
                continue
            if re.match(r'^[Φ∅]?\d+\.?\d*$', c):
                continue
            if re.match(r'^R\d+\.?\d*$', c):
                continue
            
            # 如果文本包含中文且长度适中（2-20个字符），可能是品名
            if re.search(r'[\u4e00-\u9fa5]', c) and 2 <= len(c) <= 20:
                title_candidates.append(c)
        
        # 4. 如果找到候选品名，返回第一个（通常是最显眼的）
        if title_candidates:
            part_name = title_candidates[0]
            # 缓存结果
            region['_cached_part_name'] = part_name
            return part_name
        
        logger.warning(f"⚠️ 未能识别品名，文本数量: {len(texts)}")
        self._log_region_texts_for_debug(region, "part_name_unrecognized")
        # 缓存 None 结果，避免重复识别
        region['_cached_part_name'] = None
        return None

    def extract_part_code(self, region: Dict) -> Optional[str]:
        """提取编号（零件编号）"""
        # 如果已经缓存了编号，直接返回
        if '_cached_part_code' in region:
            return region['_cached_part_code']
        
        texts = region.get('texts', []) or []
        
        # 1. 尝试从"加工说明:_(品名)编号"格式中提取（带括号，支持下划线在括号前或括号后）
        processing_with_code_pattern = re.compile(r'加工说明\s*[:：]\s*_?\s*[（(]([^)）]+)[)）]\s*_?\s*([A-Z0-9\-]+)', re.IGNORECASE)
        
        for t in texts:
            c = (t.get('content') or '').strip()
            if not c:
                continue
            
            m = processing_with_code_pattern.search(c)
            if m:
                part_code = m.group(2).strip()
                if part_code:
                    # 缓存结果
                    region['_cached_part_code'] = part_code
                    logger.info(f"✅ 从加工说明中提取编号（带括号）: '{part_code}'")
                    return part_code
        
        # 2. 尝试兜底机制：从"加工说明:_中文品名_字母数字编号"格式中提取
        # 支持下划线在品名和编号之间
        processing_fallback_pattern = re.compile(r'加工说明\s*[:：]\s*_?\s*([\u4e00-\u9fa5]+)\s*_?\s*([A-Z0-9\-]+)', re.IGNORECASE)
        
        for t in texts:
            c = (t.get('content') or '').strip()
            if not c:
                continue
            
            m = processing_fallback_pattern.search(c)
            if m:
                part_code = m.group(2).strip()
                if part_code:
                    # 缓存结果
                    region['_cached_part_code'] = part_code
                    logger.info(f"✅ 从加工说明中提取编号（兜底机制）: '{part_code}'")
                    return part_code
        
        # 3. 尝试匹配"编号"标签模式
        code_label_patterns = [
            re.compile(r'^\s*编\s*号\s*[:：]?\s*(.*)$', re.IGNORECASE),
            re.compile(r'^\s*零件编号\s*[:：]?\s*(.*)$', re.IGNORECASE),
            re.compile(r'^\s*图\s*号\s*[:：]?\s*(.*)$', re.IGNORECASE),
            re.compile(r'^\s*料\s*号\s*[:：]?\s*(.*)$', re.IGNORECASE),
        ]
        
        for i, t in enumerate(texts):
            c = (t.get('content') or '').strip()
            if not c:
                continue
            
            for label_re in code_label_patterns:
                m = label_re.match(c)
                if m:
                    # 如果标签后面直接有内容（编号:DIE-47）
                    inline_val = (m.group(1) or '').strip()
                    if inline_val and len(inline_val) > 1:
                        # 缓存结果
                        region['_cached_part_code'] = inline_val
                        return inline_val
                    
                    # 如果标签后面没有内容，查找下一个文本
                    for j in range(i + 1, min(i + 6, len(texts))):
                        nxt = (texts[j].get('content') or '').strip()
                        if nxt and len(nxt) > 1:
                            # 排除其他标签
                            is_label = any(lp.match(nxt) for lp in code_label_patterns)
                            if not is_label:
                                # 缓存结果
                                region['_cached_part_code'] = nxt
                                return nxt
        
        logger.debug(f"未能识别编号，文本数量: {len(texts)}")
        self._log_region_texts_for_debug(region, "part_code_unrecognized")
        # 缓存 None 结果，避免重复识别
        region['_cached_part_code'] = None
        return None

    def _extract_layer_colors(self, doc):
        """提取图层颜色"""
        try:
            for layer in doc.layers:
                self.layer_colors[layer.dxf.name] = getattr(layer.dxf, 'color', 7)
        except Exception as e:
            logger.error(f"图层颜色提取失败: {e}")

    def _extract_all_entities(self, msp):
        """提取几何实体"""
        geometric_types = ['LINE', 'CIRCLE', 'ARC', 'LWPOLYLINE', 'POLYLINE', 'ELLIPSE', 'SPLINE',
                           'DIMENSION', 'HATCH', 'SOLID', 'LEADER', 'MLEADER']
        for entity_type in geometric_types:
            try:
                for entity in msp.query(entity_type):
                    info = self._process_geometric_entity(entity)
                    if info:
                        self.all_entities.append(info)
            except Exception:
                continue

    def _process_geometric_entity(self, entity) -> Optional[Dict]:
        """处理几何实体信息"""
        try:
            t = entity.dxftype()
            layer = getattr(entity.dxf, 'layer', '0')
            color = getattr(entity.dxf, 'color', 256)
            handle = getattr(entity.dxf, 'handle', 'N/A')
            linetype = getattr(entity.dxf, 'linetype', 'ByLayer')
            center = self._calculate_entity_center(entity)
            if center is None:
                return None
            perimeter = self._calculate_entity_perimeter(entity)
            return {
                'type': t, 'layer': layer, 'entity_color': color, 'handle': handle,
                'linetype': linetype, 'center': center, 'perimeter': perimeter
            }
        except Exception:
            return None

    def _calculate_entity_center(self, entity):
        """计算实体中心"""
        try:
            t = entity.dxftype()
            if t in ['CIRCLE', 'ARC']:
                c = entity.dxf.center
                return (round(c.x, 2), round(c.y, 2))
            elif t == 'LINE':
                s, e = entity.dxf.start, entity.dxf.end
                return (round((s.x + e.x) / 2, 2), round((s.y + e.y) / 2, 2))
            elif t in ['LWPOLYLINE', 'POLYLINE']:
                pts = entity.get_points(format='xy')
                if pts:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    return (round(sum(xs) / len(xs), 2), round(sum(ys) / len(ys), 2))
            elif t == 'ELLIPSE':
                c = entity.dxf.center
                return (round(c.x, 2), round(c.y, 2))
            elif t == 'SPLINE':
                pts = self._safe_spline_points(entity)
                if len(pts) >= 2:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    return (round(sum(xs) / len(xs), 2), round(sum(ys) / len(ys), 2))
            elif t in ['TEXT', 'ATTRIB', 'ATTDEF']:
                if hasattr(entity.dxf, 'insert'):
                    p = entity.dxf.insert
                    return (round(p.x, 2), round(p.y, 2))
                elif hasattr(entity.dxf, 'position'):
                    p = entity.dxf.position
                    return (round(p.x, 2), round(p.y, 2))
            elif t == 'MTEXT':
                p = entity.dxf.insert
                return (round(p.x, 2), round(p.y, 2))
            elif t in ['DIMENSION', 'LEADER', 'MLEADER']:
                bb = getattr(entity, "bbox", None)
                if callable(bb):
                    box = bb()
                    if box and getattr(box, "has_data", False):
                        min_v, max_v = box.extmin, box.extmax
                        return (round((min_v.x + max_v.x) / 2, 2), round((min_v.y + max_v.y) / 2, 2))
                pts = []
                for attr in ['defpoint', 'defpoint2', 'defpoint3', 'dimline_point', 'text_midpoint', 'insert']:
                    p = getattr(entity.dxf, attr, None)
                    if p:
                        pts.append((p.x, p.y))
                if pts:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    return (round(sum(xs) / len(xs), 2), round(sum(ys) / len(ys), 2))
            bb = getattr(entity, "bbox", None)
            if callable(bb):
                box = bb()
                if box and getattr(box, "has_data", False):
                    min_v, max_v = box.extmin, box.extmax
                    return (round((min_v.x + max_v.x) / 2, 2), round((min_v.y + max_v.y) / 2, 2))
        except Exception:
            pass
        return None

    def _calculate_entity_perimeter(self, entity):
        """计算实体周长"""
        try:
            t = entity.dxftype()
            if t == 'CIRCLE':
                r = entity.dxf.radius
                return round(2 * math.pi * r, 2)
            elif t == 'ARC':
                r = entity.dxf.radius
                sa = math.radians(entity.dxf.start_angle)
                ea = math.radians(entity.dxf.end_angle)
                if ea < sa:
                    ea += 2 * math.pi
                return round(r * (ea - sa), 2)
            elif t == 'LINE':
                s, e = entity.dxf.start, entity.dxf.end
                return round(math.sqrt((e.x - s.x) ** 2 + (e.y - s.y) ** 2), 2)
            elif t in ['LWPOLYLINE', 'POLYLINE']:
                return round(self._calculate_polyline_length(entity), 2)
            bb = getattr(entity, "bbox", None)
            if callable(bb):
                box = bb()
                if box and getattr(box, "has_data", False):
                    min_v, max_v = box.extmin, box.extmax
                    w = max_v.x - min_v.x
                    h = max_v.y - min_v.y
                    return round(2 * (w + h), 2)
        except Exception:
            pass
        return 0.0

    def _calculate_polyline_length(self, polyline):
        """计算多段线长度"""
        try:
            pts = polyline.get_points(format='xy')
            if len(pts) < 2:
                return 0.0
            total = 0.0
            for i in range(len(pts) - 1):
                x1, y1 = pts[i]
                x2, y2 = pts[i + 1]
                total += math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            # 如果是闭合多段线，加上最后一段
            if getattr(polyline.dxf, 'closed', False) and len(pts) > 2:
                x1, y1 = pts[-1]
                x2, y2 = pts[0]
                total += math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            return total
        except Exception:
            return 0.0

    def _extract_all_texts(self, msp):
        """提取文本实体"""
        for t in ['TEXT', 'MTEXT', 'ATTRIB', 'ATTDEF', 'DIMENSION']:
            try:
                for e in msp.query(t):
                    info = self._process_text_entity(e)
                    if info:
                        self.all_texts.append(info)
            except Exception:
                continue

    def _process_text_entity(self, entity) -> Optional[Dict]:
        """处理文本实体信息"""
        try:
            content = self._extract_text_content(entity)
            if not content:
                return None
            position = self._get_text_position(entity)
            if not position:
                return None
            return {
                'content': self._clean_text_content(content),
                'position': position,
                'entity_type': entity.dxftype(),
                'layer': getattr(entity.dxf, 'layer', '').strip()
            }
        except Exception:
            return None

    def _extract_text_content(self, entity) -> Optional[str]:
        """提取文本内容"""
        t = entity.dxftype()
        try:
            if t == 'TEXT':
                return entity.dxf.text
            elif t == 'MTEXT':
                if hasattr(entity, 'get_text'):
                    return entity.get_text()
                elif hasattr(entity, 'plain_text'):
                    return entity.plain_text()
                return getattr(entity.dxf, 'text', None)
            elif t in ['ATTRIB', 'ATTDEF']:
                return entity.dxf.text
            elif t == 'DIMENSION':
                if hasattr(entity, 'get_measurement'):
                    return str(entity.get_measurement())
                return getattr(entity.dxf, 'text', None)
        except Exception:
            pass
        return None

    def _get_text_position(self, entity) -> Optional[Tuple[float, float]]:
        """获取文本位置"""
        try:
            if hasattr(entity.dxf, 'insert'):
                p = entity.dxf.insert
                return (float(p.x), float(p.y))
            elif hasattr(entity.dxf, 'position'):
                p = entity.dxf.position
                return (float(p.x), float(p.y))
        except Exception:
            pass
        return None

    def _clean_text_content(self, content: str) -> str:
        """清洗文本内容"""
        if not content:
            return ""
        content = re.sub(r'\{\\[^}]*\}', '', content)
        content = re.sub(r'\\[A-Za-z][^;]*;', '', content)
        repl = {'%%c': 'Φ', '%%C': 'Φ', '%%d': '°', '%%D': '°', '%%p': '±', '%%P': '±'}
        for k, v in repl.items():
            content = content.replace(k, v)
        return re.sub(r'\s+', ' ', content).strip()

    def _identify_frame_blocks(self, msp):
        """识别框架块（图框）"""
        for insert in msp.query('INSERT'):
            try:
                name = insert.dxf.name
                ins_pt = insert.dxf.insert
                block_def = insert.doc.blocks.get(name)
                if not block_def:
                    continue
                bounds = self._calculate_block_bounds(block_def, insert)
                if not bounds or not self._is_valid_frame_block(bounds):
                    continue
                self.frame_blocks.append({
                    'block_name': name,
                    'insert_point': (ins_pt.x, ins_pt.y),
                    'bounds': bounds,
                    'insert_entity': insert
                })
            except Exception:
                continue
        self._filter_frame_blocks_by_name_frequency()

    def _filter_frame_blocks_by_name_frequency(self):
        """改为只去重重叠的图框，不按名称过滤"""
        if len(self.frame_blocks) <= 1:
            return
        
        # 按面积从大到小排序
        self.frame_blocks.sort(key=lambda x: (x['bounds']['width'] * x['bounds']['height']), 
                            reverse=True)
        
        unique = [self.frame_blocks[0]]
        
        # 只去除空间重叠的图框，保留所有不同类型
        for candidate in self.frame_blocks[1:]:
            c_bounds = candidate['bounds']
            overlap = False
            
            for existing in unique:
                e_bounds = existing['bounds']
                if (c_bounds['max_x'] > e_bounds['min_x'] and
                    c_bounds['min_x'] < e_bounds['max_x'] and
                    c_bounds['max_y'] > e_bounds['min_y'] and
                    c_bounds['min_y'] < e_bounds['max_y']):
                    
                    # 计算重叠区域的边界
                    overlap_x_min = max(c_bounds['min_x'], e_bounds['min_x'])
                    overlap_x_max = min(c_bounds['max_x'], e_bounds['max_x'])
                    overlap_y_min = max(c_bounds['min_y'], e_bounds['min_y'])
                    overlap_y_max = min(c_bounds['max_y'], e_bounds['max_y'])
                    
                    # 计算重叠面积
                    overlap_area = (overlap_x_max - overlap_x_min) * (overlap_y_max - overlap_y_min)
                    
                    # 计算候选图框的面积
                    candidate_area = c_bounds['width'] * c_bounds['height']
                    
                    # 计算重叠比例（重叠面积占候选图框面积的比例）
                    overlap_ratio = overlap_area / candidate_area if candidate_area > 0 else 0
                    
                    # 只有重叠比例超过阈值才认为是真正的重叠
                    OVERLAP_THRESHOLD = 0.2  # 阈值：50%，可根据需要调整
                    if overlap_ratio > OVERLAP_THRESHOLD:
                        overlap = True
                        break
            
            if not overlap:
                unique.append(candidate)
        
        orig = len(self.frame_blocks)
        self.frame_blocks = unique
        logger.debug(f"去重后：原有 {orig} 个图框，保留 {len(self.frame_blocks)} 个不重叠的图框")

    def _calculate_block_bounds(self, block_def, insert) -> Optional[Dict]:
        """计算块边界"""
        try:
            min_x = min_y = float('inf')
            max_x = max_y = float('-inf')
            has_entities = False
            for e in block_def:
                eb = self._get_entity_bounds(e)
                if eb:
                    has_entities = True
                    min_x = min(min_x, eb['min_x'])
                    max_x = max(max_x, eb['max_x'])
                    min_y = min(min_y, eb['min_y'])
                    max_y = max(max_y, eb['max_y'])
            if not has_entities:
                return None
            ip = insert.dxf.insert
            sx = getattr(insert.dxf, 'xscale', 1.0)
            sy = getattr(insert.dxf, 'yscale', 1.0)
            return {
                'min_x': ip.x + min_x * sx,
                'max_x': ip.x + max_x * sx,
                'min_y': ip.y + min_y * sy,
                'max_y': ip.y + max_y * sy,
                'width': (max_x - min_x) * abs(sx),
                'height': (max_y - min_y) * abs(sy)
            }
        except Exception:
            return None

    def _get_entity_bounds(self, entity) -> Optional[Dict]:
        """获取实体边界"""
        try:
            t = entity.dxftype()
            if t == 'LINE':
                s, e = entity.dxf.start, entity.dxf.end
                return {'min_x': min(s.x, e.x), 'max_x': max(s.x, e.x),
                        'min_y': min(s.y, e.y), 'max_y': max(s.y, e.y)}
            elif t in ['CIRCLE', 'ARC']:
                c = entity.dxf.center
                r = entity.dxf.radius
                return {'min_x': c.x - r, 'max_x': c.x + r, 'min_y': c.y - r, 'max_y': c.y + r}
            elif t in ['LWPOLYLINE', 'POLYLINE']:
                pts = entity.get_points(format='xy')
                if pts:
                    xs, ys = zip(*pts)
                    return {'min_x': min(xs), 'max_x': max(xs), 'min_y': min(ys), 'max_y': max(ys)}
            elif t == 'SPLINE':
                # 使用控制点或拟合点计算边界
                pts = self._safe_spline_points(entity)
                if pts:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    return {'min_x': min(xs), 'max_x': max(xs), 'min_y': min(ys), 'max_y': max(ys)}
        except Exception:
            pass
        return None

    def _is_valid_frame_block(self, bounds: Dict) -> bool:
        """判断是否为有效框架块"""
        min_size = 120
        return bounds['width'] > min_size or bounds['height'] > min_size

    def _create_subdrawing_regions(self):
        """创建子图区域"""
        self.frame_blocks.sort(key=self._get_spatial_sort_key)
        for i, fb in enumerate(self.frame_blocks):
            rid = f"subdrawing_{i + 1:03d}"
            self.sub_drawings[rid] = {
                '_region_id': rid,
                'frame_block': fb,
                'bounds': fb['bounds'],
                'texts': [],
                'cutting_analysis': {}
            }
        self._log_region_bounds_summary()

    def _get_spatial_sort_key(self, frame_block):
        """空间排序键"""
        b = frame_block['bounds']
        tol = 100
        return (-round(b['min_y'] / tol), round(b['min_x'] / tol))

    def _assign_texts_to_regions(self):
        """分配文本到子图区域"""
        for text in self.all_texts:
            x, y = text['position']
            assigned = False
            for rid, r in self.sub_drawings.items():
                b = r['bounds']
                if b['min_x'] <= x <= b['max_x'] and b['min_y'] <= y <= b['max_y']:
                    r['texts'].append(text)
                    assigned = True
                    break
            if not assigned:
                cr = self._find_closest_region((x, y))
                if cr:
                    self.sub_drawings[cr]['texts'].append(text)
        for rid, r in self.sub_drawings.items():
            r['texts'] = self.text_processor.process_text_list(r['texts'])
        self._log_key_text_assignments()
        self._log_region_assignment_summary()
    
    def _preload_part_names(self):
        """预先识别所有子图的品名并缓存（避免并行处理时重复识别）"""
        logger.info("预加载所有子图的品名...")
        for region_id, region in self.sub_drawings.items():
            # 调用 extract_part_name 会自动缓存结果
            part_name = self.extract_part_name(region)
            if part_name:
                logger.debug(f"{region_id}: {part_name}")
        logger.info(f"✅ 完成品名预加载，共 {len(self.sub_drawings)} 个子图")

    def _analyze_cutting_contours_for_regions(self):
        """分析各区域切割轮廓"""
        for rid, r in self.sub_drawings.items():
            b = r['bounds']
            cutting = self.cutting_detector.detect_cutting_contours_in_region(b, self.all_entities, self.layer_colors)
            r['cutting_analysis'] = cutting

    def _find_closest_region(self, pos: Tuple[float, float]) -> Optional[str]:
        """找到最近的子图区域"""
        x, y = pos
        md = float('inf')
        cid = None
        for rid, r in self.sub_drawings.items():
            b = r['bounds']
            cx = (b['min_x'] + b['max_x']) / 2
            cy = (b['min_y'] + b['max_y']) / 2
            d = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            if d < md:
                md = d
                cid = rid
        return cid
    
    def clear_cache(self):
        """清理所有缓存数据，释放内存"""
        self.all_texts.clear()
        self.all_entities.clear()
        self.frame_blocks.clear()
        self.sub_drawings.clear()
        self.layer_colors.clear()
        self.doc = None
        self.msp = None
        self.classify_map = None
        self.source_path = None
