# -*- coding: utf-8 -*-
"""
尺寸提取模块
从 DXF 文件中提取长宽厚尺寸信息。
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO)

SEPARATORS = r'[*xX×脳]+'
ROUND_DIAMETER_MARKERS = r'(?:%%C|[ΦφØ⌀])'


def extract_dimensions_from_text(doc) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    从 DXF 文件的文字中提取尺寸信息（L, W, T）。

    支持示例：
        - 123.5L×45.6W×7.8T
        - 32.00Tx110.0Lx87.0W
        - 123.5 L 45.6 W 7.8 T
        - L123.5×W45.6×T7.8
        - 123.5×45.6×7.8
    """
    try:
        fixed_order_patterns = [
            rf'(\d+\.?\d*)\s*L\s*{SEPARATORS}\s*(\d+\.?\d*)\s*W\s*{SEPARATORS}\s*(\d+\.?\d*)\s*T',
            r'(\d+\.?\d*)\s*L\s+(\d+\.?\d*)\s*W\s+(\d+\.?\d*)\s*T',
            rf'L\s*(\d+\.?\d*)\s*{SEPARATORS}\s*W\s*(\d+\.?\d*)\s*{SEPARATORS}\s*T\s*(\d+\.?\d*)',
            rf'(\d+\.?\d*)\s*{SEPARATORS}\s*(\d+\.?\d*)\s*{SEPARATORS}\s*(\d+\.?\d*)',
        ]

        for text_content in _collect_text_contents(doc):
            result = _extract_flexible_order_dimensions(text_content)
            if result:
                length, width, thickness = result
                if _is_valid_dimension_triplet(length, width, thickness):
                    logging.info(
                        f"成功从文字提取尺寸（任意顺序）: L={length}, W={width}, T={thickness}"
                    )
                    return length, width, thickness

            for pattern in fixed_order_patterns:
                match = re.search(pattern, text_content, re.IGNORECASE)
                if not match:
                    continue

                length = float(match.group(1))
                width = float(match.group(2))
                thickness = float(match.group(3))
                if _is_valid_dimension_triplet(length, width, thickness):
                    logging.info(
                        f"成功从文字提取尺寸（固定顺序）: L={length}, W={width}, T={thickness}"
                    )
                    return length, width, thickness

        logging.warning("未找到符合格式的尺寸文字信息，将返回 (0, 0, 0)")
        return None, None, None
    except Exception as exc:
        logging.error(f"从文字提取尺寸失败: {exc}")
        return None, None, None


def _extract_flexible_order_dimensions(text: str) -> Optional[Tuple[float, float, float]]:
    """从文本中提取任意顺序的 L/W/T 尺寸。"""
    try:
        matches = re.findall(r'(\d+\.?\d*)\s*([LWT])', text, re.IGNORECASE)
        if not matches:
            return None

        dimensions: Dict[str, float] = {}
        for value, label in matches:
            label_upper = label.upper()
            if label_upper not in dimensions:
                dimensions[label_upper] = float(value)

        if {'L', 'W', 'T'}.issubset(dimensions.keys()):
            return dimensions['L'], dimensions['W'], dimensions['T']
        return None
    except Exception as exc:
        logging.debug(f"任意顺序尺寸提取失败: {exc}")
        return None


def _collect_text_contents(doc) -> List[str]:
    """Collect text-like contents from the DXF modelspace."""
    texts: List[str] = []

    try:
        msp = doc.modelspace()
    except Exception:
        return texts

    for entity in msp:
        entity_type = entity.dxftype()
        if entity_type not in ['TEXT', 'MTEXT', 'ATTRIB', 'ATTDEF']:
            continue

        try:
            if entity_type == 'MTEXT':
                text_content = entity.text if hasattr(entity, 'text') else entity.dxf.text
            else:
                text_content = entity.dxf.text
        except Exception:
            continue

        if text_content:
            texts.append(_normalize_text(text_content))

    return texts


def _normalize_text(text: str) -> str:
    """Normalize DXF text so CAD escape sequences and line breaks are easier to match."""
    return (
        text.replace(" ", "")
        .replace("\\P", "")
        .replace("\\X", "")
        .replace("{", "")
        .replace("}", "")
    )


def _extract_round_dimensions_from_text(doc) -> Tuple[Optional[float], Optional[float]]:
    """Extract round stock diameter and thickness from text patterns."""
    round_patterns = [
        re.compile(
            rf'{ROUND_DIAMETER_MARKERS}\s*(\d+\.?\d*)\s*{SEPARATORS}\s*(\d+\.?\d*)\s*(?:T|t|THK|thk)(?=[^A-Za-z]|$)',
            re.IGNORECASE,
        ),
        re.compile(
            rf'(\d+\.?\d*)\s*(?:T|t|THK|thk)(?=[^A-Za-z]|$)\s*{SEPARATORS}\s*{ROUND_DIAMETER_MARKERS}\s*(\d+\.?\d*)',
            re.IGNORECASE,
        ),
    ]
    no_t_pattern = re.compile(
        rf'{ROUND_DIAMETER_MARKERS}\s*(\d+\.?\d*)\s*{SEPARATORS}\s*(\d+\.?\d*)(?=\s*(?:\d+\s*(?:PCS|PC)|[A-Za-z0-9#-]+|$))',
        re.IGNORECASE,
    )

    for text_content in _collect_text_contents(doc):
        for pattern in round_patterns:
            match = pattern.search(text_content)
            if not match:
                continue

            if pattern is round_patterns[0]:
                diameter = float(match.group(1))
                thickness = float(match.group(2))
            else:
                thickness = float(match.group(1))
                diameter = float(match.group(2))

            if _is_valid_dimension_triplet(diameter, diameter, thickness):
                logging.info(f"成功从文字提取圆料尺寸: D={diameter}, T={thickness}")
                return diameter, thickness

        fallback_match = no_t_pattern.search(text_content)
        if not fallback_match:
            continue

        diameter = float(fallback_match.group(1))
        thickness = float(fallback_match.group(2))
        if _is_valid_dimension_triplet(diameter, diameter, thickness):
            logging.info(f"éŽ´æ„¬å§›æµ åº¢æžƒç€›æ¥å½é™æ §æ¸¾é‚æ¬æ˜‚ç€µ?(no T) D={diameter}, T={thickness}")
            return diameter, thickness

    return None, None


def _is_valid_dimension_triplet(length: float, width: float, thickness: float) -> bool:
    return 0 < length < 10000 and 0 < width < 10000 and 0 < thickness < 10000


def extract_dimensions(doc) -> Tuple[float, float, float]:
    """提取尺寸的统一接口。"""
    length, width, thickness = extract_dimensions_from_text(doc)
    if length is None or width is None or thickness is None:
        logging.warning("文字提取失败，返回 (0, 0, 0)")
        return 0.0, 0.0, 0.0
    return length, width, thickness


def extract_dimensions_with_shape(doc) -> Tuple[float, float, float, Optional[Dict[str, Any]]]:
    """Extract dimensions and optional material shape metadata."""
    length, width, thickness = extract_dimensions_from_text(doc)
    if length is not None and width is not None and thickness is not None:
        return length, width, thickness, {
            'material_shape': 'rect',
            'recognition_source': 'lwt_text',
        }

    diameter, round_thickness = _extract_round_dimensions_from_text(doc)
    if diameter is not None and round_thickness is not None:
        return diameter, diameter, round_thickness, {
            'material_shape': 'round',
            'diameter_mm': diameter,
            'recognition_source': 'phi_thickness_text',
        }

    logging.warning("文字提取失败，返回 (0, 0, 0)")
    return 0.0, 0.0, 0.0, None


if __name__ == "__main__":
    print("尺寸提取模块测试")
