# -*- coding: utf-8 -*-
"""Plate-line supplementation using the full banliaoxian.py plate-line workflow."""

from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path
from typing import Any, Dict, Optional


logger = logging.getLogger("scripts.feature_recognition.plate_line_generator")


class PlateLineGenerator:
    """Run banliaoxian.py's full material-line recognition/generation logic in-place."""

    _projector_class = None

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
        # Kept for the backend interface. The full banliaoxian flow draws on PROJ_MATERIAL.
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
        result = {
            "status": "skipped",
            "input_views": input_views,
            "generated_views": [],
            "skipped_views": [],
            "already_existing_views": [],
            "added_count": 0,
            "message": "",
        }

        logger.info(
            "板料线补线开始(banliaoxian完整逻辑): input_views=%s, dimensions=%s, tolerance=%s, color=%s",
            input_views,
            dimensions,
            self.tolerance,
            self.color,
        )

        lwt = self._normalize_dimensions(dimensions)
        if not lwt:
            result["status"] = "failed"
            result["message"] = "缺少完整的 L/W/T，无法执行 banliaoxian 补板料线逻辑"
            logger.info("板料线补线失败: %s", result["message"])
            return result

        try:
            projector = self._build_banliaoxian_projector(doc, lwt)
        except Exception as exc:
            result["status"] = "failed"
            result["message"] = f"加载 banliaoxian 补板料线逻辑失败: {exc}"
            logger.warning(result["message"])
            return result

        try:
            before_count = self._entity_count(doc)

            logger.info("banliaoxian步骤1: 查找所有闭合区域")
            regions = projector.find_view_contours_with_filtering()
            logger.info("banliaoxian步骤1完成: regions=%s", len(regions or []))
            if not regions:
                result["status"] = "failed"
                result["message"] = "banliaoxian未找到任何有效闭合区域"
                logger.info("板料线补线失败: %s", result["message"])
                return result

            logger.info("banliaoxian步骤2: 按L/W/T识别主视图、侧视图和正视图")
            identified = projector.identify_views_with_alignment(regions)
            if not identified or not projector.views or "main_view" not in projector.views:
                result["status"] = "failed"
                result["message"] = "banliaoxian未能识别主视图，无法补板料线"
                logger.info("板料线补线失败: %s", result["message"])
                return result

            validation_error = self._validate_banliaoxian_views(projector.views, lwt)
            if validation_error:
                result["status"] = "failed"
                result["message"] = validation_error
                logger.info("板料线补线失败: %s", result["message"])
                return result

            logger.info("banliaoxian步骤3: 基于视图闭合区域边界生成板料线")
            projector.generate_material_lines_from_bbox()

            after_count = self._entity_count(doc)
            added_count = max(0, after_count - before_count)
            result["added_count"] = added_count
            result["generated_views"] = self._generated_backend_view_names(projector.views)
            result["status"] = "success" if added_count > 0 else "skipped"
            result["message"] = (
                f"已按banliaoxian完整逻辑对 {len(result['generated_views'])} 个视图补画板料线"
                if added_count > 0
                else "banliaoxian完整逻辑未新增板料线"
            )
            result["query_views"] = self._summarize_banliaoxian_views(projector.views)

            for view_name in result["generated_views"]:
                logger.info("板料线已补画(banliaoxian): view=%s", view_name)
            logger.info("板料线补线汇总: %s", result)
            return result

        except Exception as exc:
            logger.exception("banliaoxian完整补板料线逻辑执行失败")
            result["status"] = "failed"
            result["message"] = f"banliaoxian完整补板料线逻辑执行失败: {exc}"
            return result

    def _build_banliaoxian_projector(self, doc, lwt: Dict[str, float]):
        projector_class = self._load_banliaoxian_projector_class()
        projector = projector_class.__new__(projector_class)
        projector.doc = doc
        projector.msp = doc.modelspace()
        projector.lwt_info = lwt
        projector.log_file_dir = None
        projector.need_centering = False
        projector.config = {
            "min_area": 1.0,
            "min_area_ratio": 0.6,
            "max_area_ratio": 1.1,
            "angle_tolerance": 5,
            "alignment_tolerance": 0.3,
            "material_layer_color": self.color,
            "material_linetype": self.linetype,
            "new_layer_prefix": "PROJ_",
            "radius_threshold": 2.0,
            "tolerance": 0.01,
            "material_line_tolerance": 0.6,
            "classify_area_tolerance": 5.0,
            "overlap_area_tolerance": 1e-2,
        }
        projector.views = {}
        projector.material_lines = []
        projector.projected_lines = []
        projector.is_valid_material_line = False
        projector.ordinate_0_0 = {}
        projector._ensure_resources()
        return projector

    @classmethod
    def _load_banliaoxian_projector_class(cls):
        if cls._projector_class is not None:
            return cls._projector_class

        current = Path(__file__).resolve()
        query_path = None
        for parent in current.parents:
            candidate = parent / "banliaoxian.py"
            if candidate.exists():
                query_path = candidate
                break
        if query_path is None:
            raise FileNotFoundError("未找到 banliaoxian.py")

        spec = importlib.util.spec_from_file_location("backend_banliaoxian", query_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载 banliaoxian.py: {query_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        if importlib.util.find_spec("pandas") is None and "pandas" not in sys.modules:
            # banliaoxian imports pandas only for CSV reading. The backend passes L/W/T directly.
            sys.modules["pandas"] = types.ModuleType("pandas")
        spec.loader.exec_module(module)
        projector_class = getattr(module, "MaterialLineProjector", None)
        if projector_class is None:
            raise AttributeError("banliaoxian.py 中未找到 MaterialLineProjector")

        cls._projector_class = projector_class
        logger.info("已加载banliaoxian完整补板料线逻辑: %s", query_path)
        return projector_class

    def _normalize_dimensions(self, dimensions: Optional[Dict[str, float]]) -> Optional[Dict[str, float]]:
        if not dimensions:
            return None
        try:
            lwt = {
                "L": float(dimensions.get("L") or 0),
                "W": float(dimensions.get("W") or 0),
                "T": float(dimensions.get("T") or 0),
            }
        except (TypeError, ValueError):
            return None
        if not all(lwt.values()):
            return None
        return lwt

    def _validate_banliaoxian_views(self, views: Dict[str, Any], lwt: Dict[str, float]) -> str:
        tolerance = 0.6
        checks = {
            "main_view": ("L/W", lwt["L"], lwt["W"]),
            "side_view": ("T/W", lwt["T"], lwt["W"]),
            "front_view": ("L/T", lwt["L"], lwt["T"]),
        }
        for view_name, (label, expected_w, expected_h) in checks.items():
            view_list = views.get(view_name) or []
            if not view_list:
                # banliaoxian will create missing side/front during generate_material_lines_from_bbox.
                if view_name == "main_view":
                    return "banliaoxian未能识别主视图，无法补板料线"
                continue
            bbox = view_list[0].bbox
            width = float(bbox[2] - bbox[0])
            height = float(bbox[3] - bbox[1])
            if view_name == "main_view":
                if abs(width - expected_w) > tolerance or abs(height - expected_h) > tolerance:
                    return (
                        f"banliaoxian识别到的主视图尺寸不匹配: {width:.3f}x{height:.3f}, "
                        f"期望{label}={expected_w}/{expected_h}"
                    )
            elif view_name == "side_view":
                if abs(width - expected_w) > tolerance:
                    return (
                        f"banliaoxian识别到的侧视图宽度不匹配: {width:.3f}, "
                        f"期望T={expected_w}"
                    )
            elif view_name == "front_view":
                if abs(height - expected_h) > tolerance:
                    return (
                        f"banliaoxian识别到的正视图高度不匹配: {height:.3f}, "
                        f"期望T={expected_h}"
                    )
        return ""

    def _entity_count(self, doc) -> int:
        try:
            return sum(1 for _ in doc.modelspace())
        except Exception:
            return 0

    def _generated_backend_view_names(self, query_views: Dict[str, Any]):
        mapping = {
            "main_view": "top_view",
            "front_view": "front_view",
            "side_view": "side_view",
        }
        return [
            backend_name
            for query_name, backend_name in mapping.items()
            if query_views.get(query_name)
        ]

    def _summarize_banliaoxian_views(self, query_views: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
        summary = {}
        for name, view_list in (query_views or {}).items():
            if not view_list:
                continue
            bbox = view_list[0].bbox
            summary[name] = {
                "min_x": float(bbox[0]),
                "min_y": float(bbox[1]),
                "max_x": float(bbox[2]),
                "max_y": float(bbox[3]),
                "width": float(bbox[2] - bbox[0]),
                "height": float(bbox[3] - bbox[1]),
            }
        return summary
