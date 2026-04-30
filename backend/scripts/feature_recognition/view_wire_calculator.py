# -*- coding: utf-8 -*-
"""
视图线割计算协调器
协调视图识别、线割实线计算和线割过滤等模块，完成整体业务逻辑
"""
import logging
import math
import re
from typing import Optional, Dict, List
from .view_identifier import ViewIdentifier
from .red_line_calculator import RedLineCalculator
from .wire_cut_filter import WireCutFilter
from .text_extractor import clean_text_content
from .spatial_wire_cut_analyzer import SpatialWireCutAnalyzer

logging.basicConfig(level=logging.INFO)


class ViewWireCalculator:
    """视图线割计算协调器 - 协调各模块完成整体业务逻辑"""
    
    def __init__(self, tolerance: float = 10.0, proximity_threshold: float = 50.0, text_search_expand_margin: float = 18.0):
        """
        Args:
            tolerance: 尺寸匹配容差（单位：mm）
            proximity_threshold: 线割编号邻近阈值（单位：mm）
            text_search_expand_margin: 文本搜索边界扩展量（单位：mm），用于查找可能在视图边界外的工艺编号
        """
        self.view_identifier = ViewIdentifier(tolerance=tolerance)
        self.red_line_calculator = RedLineCalculator()
        self.wire_cut_filter = WireCutFilter(
            proximity_threshold=proximity_threshold,
            text_search_expand_margin=text_search_expand_margin
        )
        self.spatial_analyzer = SpatialWireCutAnalyzer(connection_tolerance=0.5)

    def _calculate_matched_count(self, lines: List[Dict]) -> int:
        """Count connected groups as one matched item."""
        connectivity_groups = set()
        individual_count = 0

        for line in lines or []:
            if 'connectivity_group_id' in line:
                connectivity_groups.add(line['connectivity_group_id'])
            else:
                individual_count += 1

        return len(connectivity_groups) + individual_count

    def _get_polyline_bounds(self, entity) -> Optional[Dict[str, float]]:
        try:
            points = list(entity.get_points('xy'))
            if not points:
                return None
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            return {
                'min_x': min(xs),
                'max_x': max(xs),
                'min_y': min(ys),
                'max_y': max(ys),
            }
        except Exception:
            return None

    def _bounds_overlap(self, first: Dict, second: Dict, tolerance: float = 1.0) -> bool:
        return not (
            first['max_x'] < second['min_x'] - tolerance or
            first['min_x'] > second['max_x'] + tolerance or
            first['max_y'] < second['min_y'] - tolerance or
            first['min_y'] > second['max_y'] + tolerance
        )

    def _find_partial_front_view_bounds(
        self,
        msp,
        length: float,
        thickness: float,
        views: Optional[Dict[str, Dict]],
    ) -> List[Dict[str, float]]:
        """
        Find partial front-view material-line boxes.

        Some drawings include local front/section views with width ~= L but height
        smaller than T. They are valid places for front-view wire marks, but the
        standard LxT view recognizer skips them.
        """
        candidates = []
        size_tolerance = max(5.0, self.view_identifier.tolerance * 2)
        min_height = 2.0

        existing_bounds = [
            view_data.get('bounds')
            for view_data in (views or {}).values()
            if isinstance(view_data, dict) and view_data.get('bounds')
        ]

        try:
            for entity in msp.query('LWPOLYLINE'):
                color = getattr(entity.dxf, 'color', 256)
                linetype = getattr(entity.dxf, 'linetype', 'ByLayer')
                if color != 252:
                    continue
                if linetype.lower() not in ['dashed', 'acad_iso02w100', 'acad_iso10w100']:
                    continue

                bounds = self._get_polyline_bounds(entity)
                if not bounds:
                    continue

                width = bounds['max_x'] - bounds['min_x']
                height = bounds['max_y'] - bounds['min_y']
                if abs(width - length) > size_tolerance:
                    continue
                if height < min_height or height >= thickness - 1.0:
                    continue
                if any(self._bounds_overlap(bounds, existing) for existing in existing_bounds):
                    continue

                candidates.append(bounds)
        except Exception as exc:
            logging.debug(f"查找局部正视图板料线失败: {exc}")

        candidates.sort(key=lambda item: (item['min_x'], -item['min_y']))
        if candidates:
            logging.info(
                "🔍 找到 %s 个局部 front_view 候选框: %s",
                len(candidates),
                [
                    (
                        round(b['min_x'], 2),
                        round(b['min_y'], 2),
                        round(b['max_x'], 2),
                        round(b['max_y'], 2),
                    )
                    for b in candidates
                ],
            )

        return candidates

    def _apply_partial_front_view_wire_fallback(
        self,
        msp,
        length: float,
        thickness: float,
        views: Optional[Dict[str, Dict]],
        wire_cut_info: Dict[str, int],
        processing_instructions: Optional[Dict[str, str]],
        result: Dict,
        code_details_by_view: Dict,
        code_wire_lengths: Dict,
        all_red_lines_for_length: List[Dict],
        code_red_lines: Dict[str, List[Dict]],
    ) -> bool:
        """Match still-unmatched wire codes in partial front-view boxes."""
        unmatched_codes = []
        for code in wire_cut_info.keys():
            matched_count = sum(
                detail.get('matched_count', 0)
                for detail in code_details_by_view.get(code, [])
            )
            if matched_count == 0:
                unmatched_codes.append(code)

        if not unmatched_codes:
            return False

        partial_front_bounds = self._find_partial_front_view_bounds(
            msp, length, thickness, views
        )
        if not partial_front_bounds:
            return False

        applied = False
        used_fallback_line_ids = set()

        for bounds in partial_front_bounds:
            for code in list(unmatched_codes):
                if code not in unmatched_codes:
                    continue

                single_code_info = {code: wire_cut_info[code]}
                wire_length, red_line_count, _, _, code_matched_lines = (
                    self.red_line_calculator.calculate_red_lines_in_bounds(
                        msp,
                        bounds,
                        self.wire_cut_filter,
                        single_code_info,
                        processing_instructions,
                        return_count=True,
                    )
                )

                lines = code_matched_lines.get(code, [])
                if not lines:
                    continue

                line_ids = {id(line['entity']) for line in lines}
                if line_ids & used_fallback_line_ids:
                    continue
                used_fallback_line_ids.update(line_ids)

                view_total_length = sum(line['length'] for line in lines)
                single_length = view_total_length / len(lines) if lines else 0.0
                matched_count = self._calculate_matched_count(lines)

                result['front_view_wire_length'] += view_total_length
                if code not in code_details_by_view:
                    code_details_by_view[code] = []
                code_details_by_view[code].append({
                    'view': 'front_view',
                    'matched_count': matched_count,
                    'single_length': round(single_length, 2),
                    'total_length': round(view_total_length, 2),
                    'matched_line_ids': [id(line['entity']) for line in lines],
                    'partial_front_view_fallback': True,
                })

                for line in lines:
                    code_wire_lengths[code] += line['length']
                    all_red_lines_for_length.append(line)
                    if code in code_red_lines:
                        code_red_lines[code].append(line)

                unmatched_codes.remove(code)
                applied = True
                logging.info(
                    "✅ 局部 front_view 兜底匹配: 编号 '%s' 匹配 %s 个, 总长 %.2fmm, "
                    "bounds=(%.2f,%.2f)-(%.2f,%.2f), 候选红线=%s",
                    code,
                    matched_count,
                    view_total_length,
                    bounds['min_x'],
                    bounds['min_y'],
                    bounds['max_x'],
                    bounds['max_y'],
                    red_line_count,
                )

        return applied

    def calculate_wire_lengths_by_views(
        self, 
        doc, 
        length: float, 
        width: float, 
        thickness: float,
        processing_instructions: Optional[Dict[str, str]] = None,
        all_texts: Optional[list] = None
    ) -> Dict[str, any]:
        """
        识别三个视图并计算各视图中的线割实线长度
        
        Args:
            doc: ezdxf Document 对象
            length: 长度 L（单位：mm）
            width: 宽度 W（单位：mm）
            thickness: 厚度 T（单位：mm）
            processing_instructions: 加工说明字典 {code: instruction}
            all_texts: 图纸中所有文字列表（用于检测是否有"割"字，以及提取额外的线割工艺文字）
        
        Returns:
            Dict: {
                'top_view_wire_length': float,      # 俯视图线割长度
                'front_view_wire_length': float,    # 正视图线割长度
                'side_view_wire_length': float,     # 侧视图线割长度
                'wire_cut_anomalies': list,         # 线割异常情况列表
                'wire_cut_details': list            # 每个工艺编号的详细信息
            }
        """
        try:
            msp = doc.modelspace()
            
            logging.info("")
            logging.info("=" * 80)
            logging.info("🔍 【阶段5】视图识别开始")
            logging.info("=" * 80)
            
            # 1. 识别三个视图的边框（委托给 ViewIdentifier）
            views, view_anomalies_from_identifier = self.view_identifier.identify_views(msp, length, width, thickness)
            
            logging.info("")
            logging.info("=" * 80)
            logging.info("✂️ 【阶段6】工艺编号匹配开始")
            logging.info("=" * 80)
            
            # 2. 提取包含"割"字的加工说明编号及数量（数量表示编号在图纸中出现的次数）
            wire_cut_info = self.wire_cut_filter.extract_wire_cut_codes_with_count(processing_instructions)
            wire_cut_codes = list(wire_cut_info.keys())
            
            # 3. 提取额外的线割工艺文字（不在加工说明中，但包含"割"字）
            additional_wire_cut_texts = self.wire_cut_filter.extract_additional_wire_cut_texts(
                all_texts, processing_instructions
            )
            
            # 检查所有文字中是否有"割"字
            has_wire_cut_in_all_texts = False
            if all_texts:
                has_wire_cut_in_all_texts = any('割' in text for text in all_texts)
            
            if wire_cut_codes:
                total_count = sum(wire_cut_info.values())
                logging.info(f"识别到 {len(wire_cut_codes)} 个线割加工编号，共 {total_count} 个实例: {wire_cut_info}")
            else:
                if has_wire_cut_in_all_texts:
                    logging.warning("图纸中有'割'字，但未在加工说明中找到对应编号")
                else:
                    logging.warning("图纸中所有文字都没有'割'字")
            
            # 3. 计算每个视图中的线割实线长度
            result = {
                'top_view_wire_length': 0.0,
                'front_view_wire_length': 0.0,
                'side_view_wire_length': 0.0,
                'wire_cut_anomalies': []
            }
            
            view_mapping = {
                'top_view': 'top_view_wire_length',
                'front_view': 'front_view_wire_length',
                'side_view': 'side_view_wire_length'
            }
            
            # 用于检测异常的标志
            has_red_lines = False
            # 统计所有视图中每个编号成功配对的次数（只统计有线割实线配对的）
            code_matched_occurrence_count = {code: 0 for code in wire_cut_codes}
            # 收集所有视图中的配对失败异常
            all_count_mismatches = []
            # 收集每个工艺编号在所有视图中的线割实线长度
            code_wire_lengths = {code: 0.0 for code in wire_cut_codes}
            # 收集每个工艺编号的详细信息（按视图分组）
            code_details_by_view = {}
            # 收集所有视图中未匹配的线割实线
            all_unmatched_red_lines = []
            # 收集额外线割工艺文字的详细信息
            additional_code_details_by_view = {}
            # 收集所有视图中用于计算长度的线割实线（用于检测封闭空间）
            all_red_lines_for_length = []
            # 收集每个工艺编号对应的线割实线（用于检测该工艺是否形成封闭区域）
            code_red_lines = {code: [] for code in wire_cut_codes}
            # 收集额外工艺对应的线割实线
            additional_code_red_lines = {}
            
            for view_name, field_name in view_mapping.items():
                if view_name in views and views[view_name]:
                    bounds = views[view_name]['bounds']
                    # 委托给 RedLineCalculator 计算线割实线
                    wire_length, red_line_count, code_occurrences, count_mismatches, code_matched_lines = self.red_line_calculator.calculate_red_lines_in_bounds(
                        msp, bounds, self.wire_cut_filter, wire_cut_info, processing_instructions, return_count=True
                    )
                    result[field_name] = wire_length
                    
                    if red_line_count > 0:
                        has_red_lines = True
                    
                    # 只统计成功配对的编号出现次数（有线割实线配对的才算）
                    for code, lines in code_matched_lines.items():
                        if lines:  # 只有成功配对的才计数
                            code_matched_occurrence_count[code] += 1
                    
                    # 累加每个编号在各视图中的线割实线长度
                    for code, lines in code_matched_lines.items():
                        for line in lines:
                            code_wire_lengths[code] += line['length']
                            # 收集用于计算长度的线割实线
                            all_red_lines_for_length.append(line)
                            # 收集每个工艺编号对应的线割实线
                            if code in code_red_lines:
                                code_red_lines[code].append(line)
                    
                    # 收集每个编号在此视图中的详细信息
                    for code, lines in code_matched_lines.items():
                        if lines:  # 只记录有匹配的编号
                            if code not in code_details_by_view:
                                code_details_by_view[code] = []
                            
                            # 计算此视图中该编号的总长度和平均长度
                            view_total_length = sum(line['length'] for line in lines)
                            single_length = view_total_length / len(lines) if lines else 0.0
                            
                            # 计算匹配数量：考虑连通组，同一个连通组的多个实体算作1个
                            # 统计连通组数量 + 独立实体数量
                            connectivity_groups = set()
                            individual_count = 0
                            
                            for line in lines:
                                if 'connectivity_group_id' in line:
                                    connectivity_groups.add(line['connectivity_group_id'])
                                else:
                                    individual_count += 1
                            
                            matched_count = len(connectivity_groups) + individual_count
                            
                            if connectivity_groups:
                                logging.debug(
                                    f"   编号 '{code}' 在 {view_name} 中: "
                                    f"{len(lines)} 个实体, {len(connectivity_groups)} 个连通组, "
                                    f"{individual_count} 个独立实体, 总计 {matched_count} 个"
                                )
                            
                            code_details_by_view[code].append({
                                'view': view_name,
                                'matched_count': matched_count,
                                'single_length': round(single_length, 2),
                                'total_length': round(view_total_length, 2),
                                'matched_line_ids': [id(line['entity']) for line in lines]  # 保存匹配的线割实线实体ID
                            })
                    
                    # 收集配对失败的异常
                    if count_mismatches:
                        for mismatch in count_mismatches:
                            mismatch['view'] = view_name
                            all_count_mismatches.append(mismatch)
                    
                    # 收集此视图中未匹配的线割实线（无论是否有额外工艺文字）
                    # 获取此视图中所有线割实线
                    all_red_lines_in_view = self.red_line_calculator._get_all_red_lines_in_bounds(msp, bounds)
                    
                    # 找出未匹配的线割实线
                    matched_line_entities = set()
                    for lines in code_matched_lines.values():
                        for line in lines:
                            matched_line_entities.add(id(line['entity']))
                    
                    unmatched_lines = [
                        line for line in all_red_lines_in_view 
                        if id(line['entity']) not in matched_line_entities
                    ]
                    
                    # 添加调试日志
                    if all_red_lines_in_view:
                        logging.debug(
                            f"   {view_name}: 总线割实线={len(all_red_lines_in_view)}, "
                            f"已匹配={len(matched_line_entities)}, "
                            f"未匹配={len(unmatched_lines)}"
                        )
                    
                    if unmatched_lines:
                        all_unmatched_red_lines.append({
                            'view': view_name,
                            'bounds': bounds,
                            'lines': unmatched_lines
                        })
                    
                    logging.info(f"✅ {view_name} 线割长度: {wire_length:.2f}mm (线割实线数: {red_line_count})")
                else:
                    logging.warning(f"⚠️ 未识别到 {view_name}")

            partial_front_applied = self._apply_partial_front_view_wire_fallback(
                msp=msp,
                length=length,
                thickness=thickness,
                views=views,
                wire_cut_info=wire_cut_info,
                processing_instructions=processing_instructions,
                result=result,
                code_details_by_view=code_details_by_view,
                code_wire_lengths=code_wire_lengths,
                all_red_lines_for_length=all_red_lines_for_length,
                code_red_lines=code_red_lines,
            )
            if partial_front_applied:
                has_red_lines = True

            # 4. 检测异常情况
            if wire_cut_codes and not has_red_lines:
                # 异常情况1：有线割文字说明（加工说明中有"割"），但没有线割实线
                anomaly = {
                    'type': 'missing_red_lines',
                    'description': '存在线割工艺文字说明，但未找到线割实线',
                    'wire_cut_codes': wire_cut_codes
                }
                result['wire_cut_anomalies'].append(anomaly)
                logging.warning(f"⚠️ 线割异常: {anomaly['description']}, 编号: {wire_cut_codes}")
            
            elif not has_wire_cut_in_all_texts and has_red_lines:
                # 异常情况2：图纸中所有文字都没有"割"字，但有线割实线
                anomaly = {
                    'type': 'missing_wire_cut_text',
                    'description': '存在线割实线，但图纸中所有文字都没有"割"字'
                }
                result['wire_cut_anomalies'].append(anomaly)
                logging.warning(f"⚠️ 线割异常: {anomaly['description']}")
            
            # 5. 处理配对数量不匹配的异常（跨视图汇总后判断）
            # 统计每个编号在所有视图中总共匹配到的线割实线数量
            code_total_matched_count = {}
            for code in wire_cut_info.keys():
                total_matched = 0
                if code in code_details_by_view:
                    for view_detail in code_details_by_view[code]:
                        total_matched += view_detail['matched_count']
                code_total_matched_count[code] = total_matched
                code_total_matched_count[code] = total_matched
            
            # 只有在所有视图汇总后仍然不匹配的，才记录为异常
            for code, expected_count in wire_cut_info.items():
                total_matched = code_total_matched_count.get(code, 0)
                
                if total_matched != expected_count:
                    if total_matched == 0:
                        # 完全未配对（所有视图都没找到）
                        anomaly = {
                            'type': 'wire_cut_matching_failed',
                            'description': f"工艺编号 {code} 在所有视图中都未能配对到线割实线",
                            'code': code,
                            'expected_count': expected_count,
                            'actual_count': 0
                        }
                        result['wire_cut_anomalies'].append(anomaly)
                        logging.warning(
                            f"⚠️ 线割异常: 工艺编号 '{code}' "
                            f"在所有视图中都未能配对到线割实线（期望 {expected_count} 个）"
                        )
                    else:
                        # 部分配对（数量不足）
                        anomaly = {
                            'type': 'wire_cut_count_mismatch',
                            'description': f"工艺编号 {code} 的线割实线数量不匹配",
                            'code': code,
                            'expected_count': expected_count,
                            'actual_count': total_matched
                        }
                        result['wire_cut_anomalies'].append(anomaly)
                        logging.warning(
                            f"⚠️ 线割异常: 工艺编号 '{code}' "
                            f"期望 {expected_count} 个线割实线，实际在所有视图中找到 {total_matched} 个"
                        )
            
            # 6. 处理额外的线割工艺文字（将未匹配的线割实线归类到这些文字下）
            if additional_wire_cut_texts and all_unmatched_red_lines:
                logging.info("")
                logging.info("=" * 80)
                logging.info("🔧 【额外工艺匹配】开始处理额外的线割工艺文字")
                logging.info(f"   额外工艺数量: {len(additional_wire_cut_texts)}")
                logging.info(f"   未匹配线割实线数量: {len(all_unmatched_red_lines)}")
                logging.info("=" * 80)
                
                for additional_code in additional_wire_cut_texts:
                    # 判断是否为"侧割"工艺
                    is_side_cut = '侧割' in additional_code
                    
                    if is_side_cut:
                        logging.info(f"🔍 检测到特殊工艺 '{additional_code}'，将在正视图或侧视图中查找")
                        
                        # "侧割"：在正视图和侧视图中找最近的视图
                        target_views = ['front_view', 'side_view']
                        
                        # 在整个图纸中查找该文字的位置（不限制在视图边界内）
                        text_positions_global = []
                        try:
                            for entity in msp.query('TEXT MTEXT'):
                                try:
                                    # 获取文本内容
                                    if entity.dxftype() == 'MTEXT':
                                        content = entity.text if hasattr(entity, 'text') else entity.dxf.text
                                    else:
                                        content = entity.dxf.text
                                    
                                    if not content:
                                        continue
                                    
                                    # 使用 clean_text_content 清洗文本（移除格式化代码、解码 Unicode）
                                    content = clean_text_content(content)
                                    
                                    # 检查是否是目标文本
                                    if content != additional_code:
                                        continue
                                    
                                    # 获取文本位置
                                    if hasattr(entity.dxf, 'insert'):
                                        pos = entity.dxf.insert
                                        text_positions_global.append((pos.x, pos.y))
                                    elif hasattr(entity.dxf, 'position'):
                                        pos = entity.dxf.position
                                        text_positions_global.append((pos.x, pos.y))
                                
                                except Exception as e:
                                    logging.debug(f"处理文本实体失败: {e}")
                                    continue
                        except Exception as e:
                            logging.error(f"查找文本位置失败: {e}")
                        
                        if not text_positions_global:
                            logging.warning(f"⚠️ 未在图纸中找到额外工艺文字 '{additional_code}'")
                            continue
                        
                        logging.info(f"📍 在图纸中找到 '{additional_code}' 文字，位置: {text_positions_global}")
                        
                        # 计算文字到各目标视图的距离
                        view_distances = {}
                        
                        for view_data in all_unmatched_red_lines:
                            view_name = view_data['view']
                            
                            # 只考虑正视图和侧视图
                            if view_name not in target_views:
                                continue
                            
                            if not view_data['lines']:
                                continue
                            
                            bounds = view_data['bounds']
                            
                            # 计算视图中心点
                            view_center_x = (bounds['min_x'] + bounds['max_x']) / 2
                            view_center_y = (bounds['min_y'] + bounds['max_y']) / 2
                            
                            # 计算文字到视图中心的最短距离
                            min_distance = float('inf')
                            for text_x, text_y in text_positions_global:
                                distance = math.sqrt((text_x - view_center_x)**2 + (text_y - view_center_y)**2)
                                min_distance = min(min_distance, distance)
                            
                            view_distances[view_name] = {
                                'distance': min_distance,
                                'bounds': bounds,
                                'lines': view_data['lines']
                            }
                        
                        if not view_distances:
                            logging.warning(f"⚠️ 没有可用的目标视图用于匹配 '{additional_code}'")
                            continue
                        
                        # 选择距离最近的视图
                        closest_view = min(view_distances.items(), key=lambda x: x[1]['distance'])
                        view_name = closest_view[0]
                        view_info = closest_view[1]
                        
                        logging.info(
                            f"📍 '{additional_code}' 距离 {view_name} 最近 (距离: {view_info['distance']:.2f}mm)，"
                            f"将该视图中所有未匹配的线割实线归类到此工艺"
                        )
                        
                        # 将该视图中所有未匹配的线割实线归类到此工艺
                        matched_lines_for_code = view_info['lines']
                        
                        if matched_lines_for_code:
                            # 从未匹配列表中移除已配对的线割实线
                            view_data = next((v for v in all_unmatched_red_lines if v['view'] == view_name), None)
                            if view_data:
                                view_data['lines'] = []  # 清空该视图的未匹配列表
                            
                            # 计算总长度和平均长度
                            view_total_length = sum(line['length'] for line in matched_lines_for_code)
                            single_length = view_total_length / len(matched_lines_for_code)
                            
                            # 累加到视图的线割长度中
                            field_name = view_mapping.get(view_name)
                            if field_name:
                                result[field_name] += view_total_length
                            
                            # 记录详细信息
                            if additional_code not in additional_code_details_by_view:
                                additional_code_details_by_view[additional_code] = []
                            
                            # 计算匹配数量：考虑连通组，同一个连通组的多个实体算作1个
                            connectivity_groups = set()
                            individual_count = 0
                            
                            for line in matched_lines_for_code:
                                if 'connectivity_group_id' in line:
                                    connectivity_groups.add(line['connectivity_group_id'])
                                else:
                                    individual_count += 1
                            
                            matched_count = len(connectivity_groups) + individual_count
                            
                            additional_code_details_by_view[additional_code].append({
                                'view': view_name,
                                'matched_count': matched_count,
                                'single_length': round(single_length, 2),
                                'total_length': round(view_total_length, 2),
                                'matched_line_ids': [id(line['entity']) for line in matched_lines_for_code]  # 保存匹配的线割实线实体ID
                            })
                            
                            # 收集额外工艺对应的线割实线
                            if additional_code not in additional_code_red_lines:
                                additional_code_red_lines[additional_code] = []
                            additional_code_red_lines[additional_code].extend(matched_lines_for_code)
                            
                            logging.info(
                                f"✅ 额外工艺文字 '{additional_code}' 在 {view_name} 中匹配到 "
                                f"{len(matched_lines_for_code)} 条线割实线，总长度 {view_total_length:.2f}mm"
                            )
                    
                    else:
                        # 其他额外工艺：使用空间分析器进行智能识别
                        logging.info(f"🔍 处理额外工艺 '{additional_code}'，尝试使用空间分析器")
                        
                        # 查找俯视图的未匹配线割实线
                        top_view_data = next((v for v in all_unmatched_red_lines if v['view'] == 'top_view'), None)
                        
                        if not top_view_data or not top_view_data['lines']:
                            logging.warning(f"⚠️ 俯视图中没有未匹配的线割实线，跳过额外工艺 '{additional_code}'")
                            continue
                        
                        # 获取俯视图边界
                        top_view_bounds = views.get('top_view', {}).get('bounds')
                        if not top_view_bounds:
                            logging.warning(f"⚠️ 无法获取俯视图边界，跳过额外工艺 '{additional_code}'")
                            continue
                        
                        # 尝试使用空间分析器识别
                        spatial_detail = self.spatial_analyzer.analyze_additional_wire_cut(
                            instruction=additional_code,
                            unmatched_red_lines=top_view_data['lines'],
                            view_bounds=top_view_bounds,
                            view_name='top_view',
                            length=length,
                            width=width,
                            thickness=thickness
                        )
                        
                        if spatial_detail:
                            # 空间分析器识别成功
                            logging.info(
                                f"✅ 空间分析器识别成功: '{additional_code}' "
                                f"匹配到 {spatial_detail['matched_count']} 条线，"
                                f"总长度 {spatial_detail['total_length']:.2f}mm"
                            )
                            
                            # 从未匹配列表中移除已匹配的线段
                            matched_line_ids = set(spatial_detail['matched_line_ids'])
                            top_view_data['lines'] = [
                                line for line in top_view_data['lines']
                                if id(line['entity']) not in matched_line_ids
                            ]
                            
                            # 累加到俯视图的线割长度中
                            result['top_view_wire_length'] += spatial_detail['total_length']
                            
                            # 记录详细信息
                            if additional_code not in additional_code_details_by_view:
                                additional_code_details_by_view[additional_code] = []
                            
                            additional_code_details_by_view[additional_code].append({
                                'view': 'top_view',
                                'matched_count': spatial_detail['matched_count'],
                                'single_length': spatial_detail['single_length'],
                                'total_length': spatial_detail['total_length'],
                                'matched_line_ids': spatial_detail['matched_line_ids'],
                                'area_details': spatial_detail.get('area_details', []),
                                'geometry_features': spatial_detail.get('geometry_features', {})
                            })
                            
                            # 收集额外工艺对应的线割实线（需要从matched_line_ids重建）
                            if additional_code not in additional_code_red_lines:
                                additional_code_red_lines[additional_code] = []
                            # 注意：这里无法直接获取line对象，因为spatial_detail只返回了ID
                            # 如果需要，可以在spatial_analyzer中返回完整的line对象
                            
                        else:
                            # 空间分析器无法识别，使用原有逻辑（将所有未匹配线割实线归类）
                            logging.info(f"⚠️ 空间分析器无法识别 '{additional_code}'，使用原有逻辑")
                            
                            matched_lines_for_code = top_view_data['lines']
                            
                            # 清空俯视图的未匹配列表
                            top_view_data['lines'] = []
                            
                            # 计算总长度和平均长度
                            view_total_length = sum(line['length'] for line in matched_lines_for_code)
                            single_length = view_total_length / len(matched_lines_for_code) if matched_lines_for_code else 0
                            
                            # 累加到俯视图的线割长度中
                            result['top_view_wire_length'] += view_total_length
                            
                            # 记录详细信息
                            if additional_code not in additional_code_details_by_view:
                                additional_code_details_by_view[additional_code] = []
                            
                            # 计算匹配数量：考虑连通组，同一个连通组的多个实体算作1个
                            connectivity_groups = set()
                            individual_count = 0
                            
                            for line in matched_lines_for_code:
                                if 'connectivity_group_id' in line:
                                    connectivity_groups.add(line['connectivity_group_id'])
                                else:
                                    individual_count += 1
                            
                            matched_count = len(connectivity_groups) + individual_count
                            
                            additional_code_details_by_view[additional_code].append({
                                'view': 'top_view',
                                'matched_count': matched_count,
                                'single_length': round(single_length, 2),
                                'total_length': round(view_total_length, 2),
                                'matched_line_ids': [id(line['entity']) for line in matched_lines_for_code]
                            })
                            
                            # 收集额外工艺对应的线割实线
                            if additional_code not in additional_code_red_lines:
                                additional_code_red_lines[additional_code] = []
                            additional_code_red_lines[additional_code].extend(matched_lines_for_code)
                            
                            logging.info(
                                f"✅ 额外工艺文字 '{additional_code}' 在 top_view 中匹配到 "
                                f"{len(matched_lines_for_code)} 条线割实线，总长度 {view_total_length:.2f}mm"
                            )
            
            # 6.5. 检查是否还有剩余的未匹配线割实线（在额外工艺匹配后）
            # 只检查俯视图中的未匹配线割实线
            logging.debug(f"检查未匹配线割实线: all_unmatched_red_lines 包含 {len(all_unmatched_red_lines)} 个视图")
            
            remaining_unmatched_lines = []
            for view_data in all_unmatched_red_lines:
                # 只收集俯视图中的未匹配线割实线
                if view_data['view'] == 'top_view' and view_data['lines']:
                    logging.debug(f"   {view_data['view']}: {len(view_data['lines'])} 条未匹配线割实线")
                    remaining_unmatched_lines.extend([
                        {
                            'view': view_data['view'],
                            'length': line['length']
                        }
                        for line in view_data['lines']
                    ])
            
            if remaining_unmatched_lines:
                logging.info(f"🔍 检测到俯视图中有 {len(remaining_unmatched_lines)} 条未匹配的线割实线")
                
                # 计算总长度
                total_unmatched_length = sum(line['length'] for line in remaining_unmatched_lines)
                
                # 构建异常描述（只有俯视图）
                anomaly = {
                    'type': 'unmatched_red_lines',
                    'description': f"俯视图中存在未匹配的线割实线: {len(remaining_unmatched_lines)}条({total_unmatched_length:.2f}mm)",
                    'total_count': len(remaining_unmatched_lines),
                    'total_length': round(total_unmatched_length, 2),
                    'view': 'top_view'
                }
                result['wire_cut_anomalies'].append(anomaly)
                logging.warning(f"⚠️ 线割异常: {anomaly['description']}")
            
            # 7. 构建每个工艺编号的详细信息数组
            wire_cut_details = []
            
            # 定义用于匹配"直xx,斜xx"模式的正则表达式
            cone_pattern = r'直.+,斜.+'
            
            # 首先添加加工说明中的工艺编号
            for code in wire_cut_codes:
                expected_count = wire_cut_info.get(code, 0)
                instruction = processing_instructions.get(code, '')
                
                # 判断是否包含"直xx,斜xx"模式
                has_cone = 't' if re.search(cone_pattern, instruction) else 'f'
                
                # 检测该工艺对应的线割实线形成的封闭区域数量
                # 传入 expected_count 参数，限制封闭空间个数不超过工艺期望数量
                code_lines = code_red_lines.get(code, [])
                closed_area_count = 0
                if code_lines:
                    logging.debug(f"🔍 工艺 '{code}' 传入 {len(code_lines)} 条线割实线进行封闭区域检测")
                    closed_area_count = self.red_line_calculator.detect_closed_areas(
                        code_lines, 
                        expected_count=expected_count
                    )
                
                # 获取该编号在所有视图中的详细信息
                view_details = code_details_by_view.get(code, [])
                
                if view_details:
                    # 如果有匹配的线割实线，为每个视图创建一条记录
                    for detail in view_details:
                        wire_cut_details.append({
                            'code': code,
                            'instruction': instruction,
                            'expected_count': expected_count,
                            'matched_count': detail['matched_count'],
                            'single_length': detail['single_length'],
                            'total_length': detail['total_length'],
                            'view': detail['view'],
                            'slider_angle': 0,  # 滑块角度，默认为0
                            'is_additional': False,  # 标记为非额外工艺
                            'cone': has_cone,  # 是否包含直斜模式
                            'area_num': closed_area_count,  # 封闭区域的数量
                            'matched_line_ids': detail.get('matched_line_ids', [])  # 匹配的线割实线ID列表
                        })
                else:
                    # 如果没有匹配的线割实线，创建一条空记录
                    wire_cut_details.append({
                        'code': code,
                        'instruction': instruction,
                        'expected_count': expected_count,
                        'matched_count': 0,
                        'single_length': 0.0,
                        'total_length': 0.0,
                        'view': None,
                        'slider_angle': 0,  # 滑块角度，默认为0
                        'is_additional': False,  # 标记为非额外工艺
                        'cone': has_cone,  # 是否包含直斜模式
                        'area_num': 0,  # 没有线割实线，封闭区域数量为0
                        'matched_line_ids': []  # 空列表
                    })
            
            # 然后添加额外的线割工艺文字
            for additional_code in additional_wire_cut_texts:
                # 判断额外工艺文字是否包含"直xx,斜xx"模式
                has_cone = 't' if re.search(cone_pattern, additional_code) else 'f'
                
                # 检测该额外工艺对应的线割实线形成的封闭区域数量
                # 额外工艺的期望数量固定为 1
                additional_lines = additional_code_red_lines.get(additional_code, [])
                closed_area_count = 0
                if additional_lines:
                    closed_area_count = self.red_line_calculator.detect_closed_areas(
                        additional_lines,
                        expected_count=1  # 额外工艺期望数量固定为 1
                    )
                
                view_details = additional_code_details_by_view.get(additional_code, [])
                
                if view_details:
                    # 如果有匹配的线割实线，为每个视图创建一条记录
                    for detail in view_details:
                        wire_cut_details.append({
                            'code': additional_code,
                            'instruction': additional_code,  # 使用文字本身作为说明
                            'expected_count': 1,  # 额外工艺期望数量固定为 1
                            'matched_count': detail['matched_count'],
                            'single_length': detail['single_length'],
                            'total_length': detail['total_length'],
                            'view': detail['view'],
                            'slider_angle': 0,  # 滑块角度，默认为0
                            'is_additional': True,  # 标记为额外工艺
                            'cone': has_cone,  # 是否包含直斜模式
                            'area_num': closed_area_count,  # 封闭区域的数量
                            'matched_line_ids': detail.get('matched_line_ids', [])  # 匹配的线割实线ID列表
                        })
                else:
                    # 如果没有匹配的线割实线，不创建记录（避免冗余）
                    pass
            
            result['wire_cut_details'] = wire_cut_details
            
            # 添加视图信息到返回结果（供牙孔检测等其他模块使用）
            result['views'] = views
            
            # 添加未匹配的线割实线信息（供滑块工艺计算使用）
            # 注意：这里传递的是引用，如果后续有代码修改 all_unmatched_red_lines，会影响到滑块计算
            result['unmatched_red_lines'] = all_unmatched_red_lines
            
            # 添加调试日志
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                logging.debug(f"返回 unmatched_red_lines，包含 {len(all_unmatched_red_lines)} 个视图")
                for view_data in all_unmatched_red_lines:
                    logging.debug(f"  视图 '{view_data['view']}': {len(view_data.get('lines', []))} 条未匹配线割实线")
            
            # 添加视图识别过程中的异常信息
            if view_anomalies_from_identifier:
                result['wire_cut_anomalies'].extend(view_anomalies_from_identifier)
            
            # 打印每个工艺编号的详细信息
            if wire_cut_details:
                logging.info("📏 各工艺编号的线割详情:")
                for detail in wire_cut_details:
                    if detail['is_additional']:
                        logging.info(
                            f"   额外工艺 '{detail['code']}' ({detail['view'] or '未匹配'}): "
                            f"匹配{detail['matched_count']}个, "
                            f"单个{detail['single_length']:.2f}mm, 总计{detail['total_length']:.2f}mm"
                        )
                    else:
                        logging.info(
                            f"   编号 '{detail['code']}' ({detail['view'] or '未匹配'}): "
                            f"期望{detail['expected_count']}个, 匹配{detail['matched_count']}个, "
                            f"单个{detail['single_length']:.2f}mm, 总计{detail['total_length']:.2f}mm"
                        )
            
            return result
            
        except Exception as e:
            logging.error(f"计算视图线割长度失败: {str(e)}")
            return {
                'top_view_wire_length': 0.0,
                'front_view_wire_length': 0.0,
                'side_view_wire_length': 0.0,
                'wire_cut_anomalies': []
            }
