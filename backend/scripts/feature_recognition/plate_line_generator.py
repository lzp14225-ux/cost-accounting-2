# -*- coding: utf-8 -*-
"""Plate-line supplementation adapter.

This module keeps the current backend interface, but the supplementation rules
are aligned with the implementation from `sheet_line/dxf_auto_sheetline.py`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger("scripts.feature_recognition.plate_line_generator")


Bounds = Dict[str, float]

VIEW_TYPE_MAP = {
    "top_view": "主视图",
    "front_view": "俯视图",
    "side_view": "侧视图",
}


class PlateLineGenerator:
    """Supplement plate lines by reusing the old sheet_line logic."""

    def __init__(
        self,
        tolerance: float = 5.0,
        color: int = 252,
        linetype: str = "DASHED",
        layer_name: str = "MATERIAL_LINE_AUTO",
    ) -> None:
        self.tolerance = tolerance
        self.color = color
        self.linetype = linetype
        self.layer_name = layer_name

    def ensure_plate_lines(
        self,
        doc,
        views: Optional[Dict[str, Dict[str, Any]]],
        dimensions: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        input_views = sorted(
            view_name
            for view_name, view_data in (views or {}).items()
            if isinstance(view_data, dict) and view_data.get("bounds")
        )
        logger.info(
            "板料线补线开始: input_views=%s, dimensions=%s, tolerance=%s, layer=%s",
            input_views,
            dimensions,
            self.tolerance,
            self.layer_name,
        )

        result = {
            "status": "skipped",
            "input_views": input_views,
            "generated_views": [],
            "skipped_views": [],
            "already_existing_views": [],
            "added_count": 0,
            "message": "",
        }

        if not input_views:
            result["message"] = "未识别到可补线的视图边界，跳过补线"
            logger.info("板料线补线跳过: %s", result["message"])
            return result

        if not dimensions or not all(dimensions.get(key) for key in ("L", "W", "T")):
            result["status"] = "failed"
            result["message"] = "缺少完整的 L/W/T，无法按旧补线逻辑执行"
            logger.info("板料线补线失败: %s", result["message"])
            return result

        msp = doc.modelspace()
        matching_regions = []

        for view_name in input_views:
            bounds = views[view_name].get("bounds")
            if not self._is_valid_bounds(bounds):
                result["skipped_views"].append(view_name)
                logger.info(
                    "板料线补线跳过视图: view=%s, reason=invalid_bounds, bounds=%s",
                    view_name,
                    bounds,
                )
                continue

            bbox = self._bounds_to_bbox(bounds)
            if self.check_existing_material_lines_in_bbox(msp, bbox):
                result["already_existing_views"].append(view_name)
                logger.info("板料线已存在: view=%s, bounds=%s", view_name, bounds)
                continue

            matching_regions.append(
                {
                    "bbox": bbox,
                    "view_type": VIEW_TYPE_MAP.get(view_name, view_name),
                }
            )

        if matching_regions:
            part_info = {
                "matching_regions": matching_regions,
                "confidence": 1.0,
                "count": 1,
                "positions": [self._calculate_position(matching_regions)],
            }
            lines_added = self.add_material_lines_for_part(
                msp,
                dimensions,
                part_info["positions"][0],
                self.layer_name,
                part_info,
            )
            result["generated_views"] = [
                view_name
                for view_name in input_views
                if view_name not in result["already_existing_views"]
                and view_name not in result["skipped_views"]
            ]
            result["added_count"] = int(lines_added)
            for view_name in result["generated_views"]:
                logger.info("板料线已补画: view=%s", view_name)

        if result["added_count"] > 0 and not result["skipped_views"]:
            result["status"] = "success"
        elif result["added_count"] > 0:
            result["status"] = "partial"
        elif result["already_existing_views"]:
            result["status"] = "skipped"
        else:
            result["status"] = "failed"

        result["message"] = self._build_message(result)
        logger.info("板料线补线汇总: %s", result)
        return result

    def calculate_dynamic_tolerance(self, dimension: float, relative_error: float = 0.05) -> float:
        min_tolerance = 2.0
        max_tolerance = 20.0
        tolerance = dimension * relative_error
        return max(min_tolerance, min(tolerance, max_tolerance))

    def check_existing_material_lines_in_bbox(
        self,
        msp,
        bbox: Tuple[float, float, float, float],
        tolerance: float = 10.0,
    ) -> bool:
        """Logic aligned with sheet_line/dxf_auto_sheetline.py."""
        x_min, y_min, x_max, y_max = bbox
        search_bbox = (x_min - tolerance, y_min - tolerance, x_max + tolerance, y_max + tolerance)

        for entity in msp.query("LINE LWPOLYLINE POLYLINE"):
            layer = getattr(entity.dxf, "layer", "") or ""
            if "MATERIAL_LINE" not in layer.upper():
                continue

            entity_bbox = self._entity_bbox(entity)
            if not entity_bbox:
                continue

            if (
                entity_bbox[2] > search_bbox[0]
                and entity_bbox[0] < search_bbox[2]
                and entity_bbox[3] > search_bbox[1]
                and entity_bbox[1] < search_bbox[3]
            ):
                return True
        return False

    def draw_material_box_with_cad_standard(
        self,
        msp,
        bbox: Tuple[float, float, float, float],
        layer_name: str,
        color: int = 252,
        linetype: str = "DASHED",
    ) -> int:
        """Logic aligned with sheet_line/dxf_auto_sheetline.py."""
        try:
            x1, y1, x2, y2 = bbox
            doc = msp.doc

            if linetype not in doc.linetypes:
                try:
                    doc.linetypes.new(
                        linetype,
                        dxfattribs={
                            "description": "Dashed line",
                            "pattern": [6.0, -3.0],
                        },
                    )
                except Exception as exc:
                    logger.warning("创建线型失败，使用 CONTINUOUS: %s", exc)
                    linetype = "CONTINUOUS"

            if layer_name not in doc.layers:
                doc.layers.new(
                    layer_name,
                    dxfattribs={
                        "color": color,
                        "linetype": linetype,
                    },
                )

            polyline = msp.add_lwpolyline(
                [(x1, y1), (x2, y1), (x2, y2), (x1, y2)],
                close=True,
                dxfattribs={
                    "layer": layer_name,
                    "color": color,
                    "linetype": linetype,
                },
            )
            return 1 if polyline else 0
        except Exception as exc:
            logger.warning("绘制板料线失败: bbox=%s, error=%s", bbox, exc)
            return 0

    def add_material_lines_for_part(
        self,
        msp,
        lwt: Dict[str, float],
        position: Tuple[float, float],
        layer_name: str,
        part_info: Dict[str, Any],
    ) -> int:
        """Reuse the matching-regions supplementation branch from sheet_line."""
        try:
            matching_regions = part_info.get("matching_regions", [])
            logger.info(
                "板料线旧逻辑补线: position=%s, matching_regions=%s, lwt=%s",
                position,
                len(matching_regions),
                lwt,
            )
            if not matching_regions:
                return 0

            lines_added = 0
            view_types_added = set()

            for index, region in enumerate(matching_regions):
                bbox = region.get("bbox")
                view_type = region.get("view_type", f"VIEW_{index + 1}")
                view_type_base = view_type.replace("(LINE)", "").replace("旋转", "")

                if view_type_base in view_types_added:
                    continue
                if not bbox:
                    continue
                if self.check_existing_material_lines_in_bbox(msp, bbox):
                    view_types_added.add(view_type_base)
                    continue

                lines_added += self.draw_material_box_with_cad_standard(
                    msp,
                    bbox,
                    f"{layer_name}_{view_type_base.upper()}",
                    color=self.color,
                    linetype=self.linetype,
                )
                view_types_added.add(view_type_base)

            return lines_added
        except Exception as exc:
            logger.warning("旧补线逻辑执行失败: %s", exc)
            return 0

    def _entity_bbox(self, entity) -> Optional[Tuple[float, float, float, float]]:
        try:
            if entity.dxftype() == "LINE":
                return (
                    min(float(entity.dxf.start[0]), float(entity.dxf.end[0])),
                    min(float(entity.dxf.start[1]), float(entity.dxf.end[1])),
                    max(float(entity.dxf.start[0]), float(entity.dxf.end[0])),
                    max(float(entity.dxf.start[1]), float(entity.dxf.end[1])),
                )

            if entity.dxftype() in {"LWPOLYLINE", "POLYLINE"}:
                try:
                    points = list(entity.get_points(format="xy"))
                except TypeError:
                    points = [(point[0], point[1]) for point in entity.get_points()]
                if not points:
                    return None
                xs = [float(point[0]) for point in points]
                ys = [float(point[1]) for point in points]
                return (min(xs), min(ys), max(xs), max(ys))
        except Exception:
            return None
        return None

    def _is_valid_bounds(self, bounds: Optional[Bounds]) -> bool:
        if not isinstance(bounds, dict):
            return False
        required_keys = {"min_x", "max_x", "min_y", "max_y"}
        if not required_keys.issubset(bounds):
            return False
        return bounds["max_x"] > bounds["min_x"] and bounds["max_y"] > bounds["min_y"]

    def _bounds_to_bbox(self, bounds: Bounds) -> Tuple[float, float, float, float]:
        return (
            float(bounds["min_x"]),
            float(bounds["min_y"]),
            float(bounds["max_x"]),
            float(bounds["max_y"]),
        )

    def _calculate_position(self, matching_regions: List[Dict[str, Any]]) -> Tuple[float, float]:
        first_bbox = matching_regions[0]["bbox"]
        return ((first_bbox[0] + first_bbox[2]) / 2, (first_bbox[1] + first_bbox[3]) / 2)

    def _build_message(self, result: Dict[str, Any]) -> str:
        if result["generated_views"]:
            return (
                f"已按旧板料线逻辑对 {len(result['generated_views'])} 个视图补画板料线，"
                "未为缺失视图创建新框"
            )
        if result["already_existing_views"]:
            return "目标视图范围内已存在板料线，无需补线"
        if result["skipped_views"]:
            return "部分视图边界无效，未执行补线"
        return "未生成板料线"
