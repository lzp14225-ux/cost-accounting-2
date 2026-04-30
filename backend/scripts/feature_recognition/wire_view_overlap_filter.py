# -*- coding: utf-8 -*-
"""
跨视图线割重合过滤模块
用于过滤侧视图中与主视图（top_view）重合的无效红色线割实线。
"""
import logging
import math
from typing import Dict, List, Tuple

from .red_line_calculator import RedLineCalculator

logger = logging.getLogger("scripts.feature_recognition.wire_view_overlap_filter")


class WireViewOverlapFilter:
    """跨视图线割重合过滤器"""

    def __init__(self, overlap_tolerance: float = 0.5, full_overlap_ratio: float = 0.95):
        self.overlap_tolerance = overlap_tolerance
        self.full_overlap_ratio = full_overlap_ratio
        self.red_line_calculator = RedLineCalculator()

    def filter_side_view_overlaps_with_top_view(
        self,
        doc,
        wire_cut_details: List[Dict],
        views: Dict[str, Dict],
    ) -> Tuple[List[Dict], Dict[str, float]]:
        """
        过滤侧视图中与主视图重合的无效红色线割实线。

        Returns:
            Tuple[List[Dict], Dict[str, float]]: 更新后的工艺详情和视图长度调整
        """
        try:
            top_view = views.get('top_view') if views else None
            side_view = views.get('side_view') if views else None

            if not top_view or not side_view:
                logger.info("⏭️ 跳过跨视图线割重合过滤: top_view 或 side_view 不存在")
                return wire_cut_details, {}

            msp = doc.modelspace()
            top_bounds = top_view.get('bounds')
            side_bounds = side_view.get('bounds')
            if not top_bounds or not side_bounds:
                logger.info("⏭️ 跳过跨视图线割重合过滤: 视图边界不完整")
                return wire_cut_details, {}

            logger.info("")
            logger.info("=" * 80)
            logger.info("🔍 【阶段7.4】跨视图线割重合检测")
            logger.info("=" * 80)

            top_red_lines = self.red_line_calculator._get_all_red_lines_in_bounds(msp, top_bounds)
            side_red_lines = self.red_line_calculator._get_all_red_lines_in_bounds(msp, side_bounds)

            top_lines_by_id = {id(line['entity']): line for line in top_red_lines}
            side_lines_by_id = {id(line['entity']): line for line in side_red_lines}

            top_matched_ids = set()
            for detail in wire_cut_details:
                if detail.get('view') == 'top_view':
                    top_matched_ids.update(detail.get('matched_line_ids', []))

            top_matched_lines = [
                top_lines_by_id[line_id]
                for line_id in top_matched_ids
                if line_id in top_lines_by_id
            ]

            if not top_matched_lines:
                logger.info("⏭️ 跳过跨视图线割重合过滤: 主视图没有已匹配线割实线")
                return wire_cut_details, {}

            logger.info("主视图已匹配线割实线: %s 条", len(top_matched_lines))

            updated_details = []
            view_length_adjustments = {'side_view_wire_length': 0.0}
            filtered_detail_count = 0

            for detail in wire_cut_details:
                if detail.get('view') != 'side_view':
                    updated_details.append(detail)
                    continue

                matched_line_ids = detail.get('matched_line_ids', [])
                if not matched_line_ids:
                    updated_details.append(detail)
                    continue

                side_lines = [
                    side_lines_by_id[line_id]
                    for line_id in matched_line_ids
                    if line_id in side_lines_by_id
                ]
                if not side_lines:
                    updated_details.append(detail)
                    continue

                duplicate_line_ids = []
                overlapping_length = 0.0
                for side_line in side_lines:
                    if self._is_duplicate_against_top_view(side_line, top_matched_lines):
                        duplicate_line_ids.append(id(side_line['entity']))
                        overlapping_length += side_line['length']

                if overlapping_length <= 0:
                    updated_details.append(detail)
                    continue

                filtered_detail_count += 1
                remaining_line_ids = [
                    line_id for line_id in matched_line_ids
                    if line_id not in set(duplicate_line_ids)
                ]
                remaining_lines = [
                    side_lines_by_id[line_id]
                    for line_id in remaining_line_ids
                    if line_id in side_lines_by_id
                ]
                new_total_length = sum(line['length'] for line in remaining_lines)

                updated_detail = detail.copy()
                updated_detail['matched_line_ids'] = remaining_line_ids
                updated_detail['view_overlap_removed_length'] = round(overlapping_length, 2)
                updated_detail['view_overlap_removed_line_ids'] = duplicate_line_ids

                if new_total_length <= self.overlap_tolerance:
                    updated_detail['matched_count'] = 0
                    updated_detail['single_length'] = 0.0
                    updated_detail['total_length'] = 0.0
                else:
                    old_matched_count = max(1, int(detail.get('matched_count', 1)))
                    remaining_entity_count = max(1, len(remaining_line_ids))
                    new_matched_count = min(old_matched_count, remaining_entity_count)
                    updated_detail['matched_count'] = new_matched_count
                    updated_detail['total_length'] = round(new_total_length, 2)
                    updated_detail['single_length'] = round(new_total_length / new_matched_count, 2)

                view_length_adjustments['side_view_wire_length'] -= overlapping_length
                updated_details.append(updated_detail)

                logger.info(
                    "✅ 工艺 '%s' 在 side_view 中过滤与 top_view 重合的无效红线 %.2fmm, 原长度 %.2fmm → 新长度 %.2fmm",
                    detail.get('code'),
                    overlapping_length,
                    detail.get('total_length', 0.0),
                    updated_detail['total_length'],
                )

            if filtered_detail_count == 0:
                logger.info("✅ 未发现侧视图与主视图重合的无效线割实线")
                return wire_cut_details, {}

            logger.info(
                "📊 跨视图线割重合过滤完成: 过滤工艺 %s 个, side_view 调整 %.2fmm",
                filtered_detail_count,
                view_length_adjustments['side_view_wire_length'],
            )
            return updated_details, view_length_adjustments

        except Exception as e:
            logger.error(f"跨视图线割重合过滤失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return wire_cut_details, {}

    def _is_duplicate_against_top_view(self, side_line: Dict, top_lines: List[Dict]) -> bool:
        side_length = float(side_line.get('length') or 0.0)
        if side_length <= 0:
            return False

        for top_line in top_lines:
            top_length = float(top_line.get('length') or 0.0)
            if top_length <= 0:
                continue

            if side_line.get('type') == 'CIRCLE' and top_line.get('type') == 'CIRCLE':
                if self._is_circle_duplicate(side_line, top_line):
                    return True
                continue

            overlap_length = self._calculate_line_overlap(side_line, top_line)
            if overlap_length <= 0:
                continue

            overlap_ratio = overlap_length / side_length if side_length > 0 else 0.0
            if overlap_ratio >= self.full_overlap_ratio:
                return True

        return False

    def _is_circle_duplicate(self, side_line: Dict, top_line: Dict) -> bool:
        side_center = side_line.get('center')
        top_center = top_line.get('center')
        if not side_center or not top_center:
            return False

        center_distance = math.sqrt(
            (side_center[0] - top_center[0]) ** 2 +
            (side_center[1] - top_center[1]) ** 2
        )
        length_diff = abs((side_line.get('length') or 0.0) - (top_line.get('length') or 0.0))
        return center_distance <= self.overlap_tolerance and length_diff <= self.overlap_tolerance

    def _calculate_line_overlap(self, seg1: Dict, seg2: Dict) -> float:
        start1 = seg1.get('start')
        end1 = seg1.get('end')
        start2 = seg2.get('start')
        end2 = seg2.get('end')
        if not start1 or not end1 or not start2 or not end2:
            return 0.0

        if not self._are_collinear_segments(start1, end1, start2, end2):
            return 0.0

        dx = end1[0] - start1[0]
        dy = end1[1] - start1[1]

        if abs(dx) >= abs(dy):
            seg1_min = min(start1[0], end1[0])
            seg1_max = max(start1[0], end1[0])
            seg2_min = min(start2[0], end2[0])
            seg2_max = max(start2[0], end2[0])
        else:
            seg1_min = min(start1[1], end1[1])
            seg1_max = max(start1[1], end1[1])
            seg2_min = min(start2[1], end2[1])
            seg2_max = max(start2[1], end2[1])

        overlap_min = max(seg1_min, seg2_min)
        overlap_max = min(seg1_max, seg2_max)
        if overlap_max <= overlap_min:
            return 0.0
        return overlap_max - overlap_min

    def _are_collinear_segments(self, start1, end1, start2, end2) -> bool:
        return (
            self._point_to_line_distance(start2, start1, end1) <= self.overlap_tolerance and
            self._point_to_line_distance(end2, start1, end1) <= self.overlap_tolerance and
            self._point_to_line_distance(start1, start2, end2) <= self.overlap_tolerance and
            self._point_to_line_distance(end1, start2, end2) <= self.overlap_tolerance
        )

    def _point_to_line_distance(self, point, line_start, line_end) -> float:
        px, py = point
        x1, y1 = line_start
        x2, y2 = line_end

        line_length_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
        if line_length_sq <= 0:
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)

        cross = abs((y2 - y1) * px - (x2 - x1) * py + x2 * y1 - y2 * x1)
        return cross / math.sqrt(line_length_sq)
