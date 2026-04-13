from decimal import Decimal
import json
from typing import Any, Dict, Optional

PI = Decimal("3.141592653589793")


def parse_metadata(metadata: Any) -> Dict[str, Any]:
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def get_shape_info(part: Dict[str, Any]) -> Dict[str, Any]:
    metadata = parse_metadata(part.get("metadata"))
    shape = metadata.get("shape")
    return shape if isinstance(shape, dict) else {}


def get_material_shape(part: Dict[str, Any]) -> str:
    shape_info = get_shape_info(part)
    shape = shape_info.get("material_shape")
    return shape if shape in {"rect", "round"} else "rect"


def get_round_diameter_mm(part: Dict[str, Any]) -> Optional[Decimal]:
    shape_info = get_shape_info(part)
    diameter = shape_info.get("diameter_mm")
    if diameter in (None, ""):
        return None
    return Decimal(str(diameter))


def get_shape_price_category(part: Dict[str, Any], rect_category: str, round_category: str) -> str:
    return round_category if get_material_shape(part) == "round" else rect_category


def get_stock_volume_mm3(part: Dict[str, Any]) -> Decimal:
    thickness_mm = Decimal(str(part.get("thickness_mm")))
    material_shape = get_material_shape(part)

    if material_shape == "round":
        diameter_mm = get_round_diameter_mm(part)
        if diameter_mm is None:
            diameter_mm = Decimal(str(part.get("length_mm")))
        radius_mm = diameter_mm / Decimal("2")
        return PI * radius_mm * radius_mm * thickness_mm

    length_mm = Decimal(str(part.get("length_mm")))
    width_mm = Decimal(str(part.get("width_mm")))
    return length_mm * width_mm * thickness_mm
