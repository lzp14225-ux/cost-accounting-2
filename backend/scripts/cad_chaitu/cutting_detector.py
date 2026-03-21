#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
切割轮廓检测模块
"""

import re
import math
from typing import Dict, List, Tuple
from collections import defaultdict


class RelaxedCuttingDetector:
    """放宽的切割轮廓检测器"""

    def __init__(self):
        self.cutting_colors = set(range(1, 256))
        self.BYLAYER_COLOR = 256  # ByLayer
        self.geometric_entities = {'LINE', 'CIRCLE', 'ARC', 'LWPOLYLINE', 'POLYLINE', 'SPLINE', 'ELLIPSE'}
        self.exclude_layer_patterns = [
            r'^text$', r'^dimension$', r'^dim$', r'^annotation$',
            r'^center$', r'^construction$', r'^hidden$', r'^dashed$'
        ]

    def detect_cutting_contours_in_region(self, bounds: Dict, entities: List, layer_colors: Dict) -> Dict:
        """检测区域内切割轮廓"""
        region_entities = self._get_entities_in_bounds(entities, bounds)
        red = []
        for e in region_entities:
            if self._should_exclude_entity(e):
                continue
            color = e.get('entity_color', self.BYLAYER_COLOR)
            if color == self.BYLAYER_COLOR:
                color = layer_colors.get(e.get('layer', ''), self.BYLAYER_COLOR)
            e['final_color'] = color

            if self._is_geometric_entity_relaxed(e):
                red.append(e)

        analysis = self._generate_cutting_analysis(red)
        ref_idx = self._identify_reference_points(red)
        analysis['reference_points'] = ref_idx
        analysis['reference_count'] = len(ref_idx)

        return analysis

    def _get_entities_in_bounds(self, entities: List[Dict], bounds: Dict) -> List[Dict]:
        """获取区域内实体"""
        res = []
        min_x, max_x = bounds['min_x'], bounds['max_x']
        min_y, max_y = bounds['min_y'], bounds['max_y']
        for info in entities:
            center = info.get('center')
            if center is None:
                continue
            cx, cy = center
            if (min_x <= cx <= max_x) and (min_y <= cy <= max_y):
                res.append(info)
        return res

    def _should_exclude_entity(self, entity_info: Dict) -> bool:
        """排除不需要的实体"""
        layer = (entity_info.get('layer') or '').lower()
        for pat in self.exclude_layer_patterns:
            if re.match(pat, layer, re.IGNORECASE):
                return True
        return False

    def _is_geometric_entity_relaxed(self, entity_info: Dict) -> bool:
        """放宽的几何实体判断"""
        if entity_info.get('type', '') not in self.geometric_entities:
            return False

        color = entity_info.get('final_color', self.BYLAYER_COLOR)
        if color not in self.cutting_colors and color != self.BYLAYER_COLOR:
            return False

        lt = (entity_info.get('linetype', 'ByLayer') or '').lower()
        excluded_linetypes = {'hidden', 'dashed', 'center'}
        return lt not in excluded_linetypes

    def _get_contour_types(self, contours: List[Dict]) -> Dict[str, int]:
        """轮廓类型统计"""
        d = defaultdict(int)
        for c in contours:
            d[c.get('type', 'UNKNOWN')] += 1
        return dict(d)

    def _generate_cutting_analysis(self, contours: List[Dict]) -> Dict:
        """生成切割分析结果"""
        analysis = {
            'summary': '未检测到切割轮廓',
            'contour_count': 0,
            'total_cutting_length': 0.0,
            'avg_length': 0.0,
            'min_length': 0.0,
            'max_length': 0.0,
            'type_distribution': {}
        }
        if not contours:
            return analysis
        peris = [c.get('perimeter', 0.0) for c in contours if c.get('perimeter', 0.0) > 0.0]
        total_len = sum(peris)
        analysis['contour_count'] = len(contours)
        analysis['total_cutting_length'] = total_len
        analysis['type_distribution'] = self._get_contour_types(contours)
        if peris:
            analysis['avg_length'] = total_len / len(peris)
            analysis['min_length'] = min(peris)
            analysis['max_length'] = max(peris)
            analysis['summary'] = f"检测到{analysis['contour_count']}个切割轮廓，总长度{total_len:.2f}mm"
        else:
            analysis['summary'] = f"检测到{analysis['contour_count']}个切割轮廓，但未获取到有效长度数据"
        return analysis

    def _identify_reference_points(self, red_entities: List[Dict]) -> List[int]:
        """识别基准点"""
        circles = [i for i, e in enumerate(red_entities) if e.get('type') == 'CIRCLE']
        if len(circles) < 3:
            return []
        for i in range(len(circles)):
            for j in range(i + 1, len(circles)):
                for k in range(j + 1, len(circles)):
                    idxs = [circles[i], circles[j], circles[k]]
                    ents = [red_entities[t] for t in idxs]
                    peris = [e.get('perimeter', 0.0) for e in ents]
                    if not peris or any(p <= 0 for p in peris):
                        continue
                    if not all(abs(peris[0] - p) < 0.5 for p in peris[1:]):
                        continue
                    centers = [e.get('center', (0.0, 0.0)) for e in ents]
                    if self._is_equal_right_triangle(centers):
                        return idxs
        return []

    def _is_equal_right_triangle(self, centers: List[Tuple[float, float]]) -> bool:
        """判断是否为等腰直角三角形（基准点验证）"""
        if len(centers) != 3:
            return False
        d = []
        for a in range(3):
            for b in range(a + 1, 3):
                x1, y1 = centers[a]
                x2, y2 = centers[b]
                d.append(math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2))
        d.sort()
        if len(d) != 3:
            return False
        tol = 0.5
        equal_sides = abs(d[0] - d[1]) < tol
        hyp = d[2]
        return equal_sides and abs(hyp - d[0] * 1.414) < tol
