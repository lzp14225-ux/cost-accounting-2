# -*- coding: utf-8 -*-
"""DWG to DXF conversion service.

This service preserves the conversion logic used by
`sheet_line/dwg_to_dxf_converter.py`, but exposes it as a reusable module for
the current backend flow.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


logger = logging.getLogger("scripts.dwg_to_dxf_service")


ODA_CONVERTER_PATH = os.getenv("ODA_CONVERTER_PATH", r"D:\my_project\ODAFileConverter.exe")


def convert_with_oda(dwg_path: str, dxf_path: Optional[str] = None) -> bool:
    """Convert DWG to DXF with ODA File Converter."""
    try:
        if not os.path.exists(ODA_CONVERTER_PATH):
            logger.warning("ODA File Converter not found: %s", ODA_CONVERTER_PATH)
            return False

        if dxf_path is None:
            dxf_path = str(Path(dwg_path).with_suffix(".dxf"))

        temp_dir = tempfile.mkdtemp(prefix="dwg_to_dxf_")
        temp_input_dir = os.path.join(temp_dir, "input")
        temp_output_dir = os.path.join(temp_dir, "output")
        os.makedirs(temp_input_dir, exist_ok=True)
        os.makedirs(temp_output_dir, exist_ok=True)

        dwg_filename = os.path.basename(dwg_path)
        temp_dwg_path = os.path.join(temp_input_dir, dwg_filename)
        shutil.copy2(dwg_path, temp_dwg_path)

        cmd = [
            ODA_CONVERTER_PATH,
            temp_input_dir,
            temp_output_dir,
            "ACAD2018",
            "DXF",
            "0",
            "1",
            "*.dwg",
        ]

        logger.info("Starting DWG to DXF conversion with ODA: %s -> %s", dwg_path, dxf_path)
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=temp_dir)

        if result.returncode != 0:
            logger.warning(
                "ODA conversion failed: returncode=%s, stderr=%s",
                result.returncode,
                result.stderr.strip(),
            )
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False

        temp_dxf_path = os.path.join(
            temp_output_dir,
            dwg_filename.replace(".dwg", ".dxf").replace(".DWG", ".dxf"),
        )
        if not os.path.exists(temp_dxf_path):
            logger.warning("ODA conversion did not produce DXF: %s", temp_dxf_path)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False

        Path(dxf_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(temp_dxf_path, dxf_path)
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info("ODA conversion succeeded: %s", dxf_path)
        return True
    except Exception as exc:
        logger.warning("ODA conversion raised exception: %s", exc)
        return False


def convert_dwg_to_dxf_with_ezdxf(dwg_path: str, dxf_path: Optional[str] = None) -> bool:
    """Fallback conversion logic aligned with the original script."""
    try:
        import ezdxf

        if dxf_path is None:
            dxf_path = str(Path(dwg_path).with_suffix(".dxf"))

        logger.info("Starting DWG to DXF conversion with ezdxf: %s -> %s", dwg_path, dxf_path)
        doc = ezdxf.readfile(dwg_path)
        doc.saveas(dxf_path)
        logger.info("ezdxf conversion succeeded: %s", dxf_path)
        return True
    except Exception as exc:
        logger.warning("ezdxf conversion failed: %s", exc)
        return False


def convert_dwg_to_dxf(dwg_path: str, dxf_path: Optional[str] = None) -> Optional[str]:
    """Convert a DWG file to DXF and return the local DXF path on success."""
    if dxf_path is None:
        dxf_path = str(Path(dwg_path).with_suffix(".dxf"))

    if convert_with_oda(dwg_path, dxf_path):
        return dxf_path
    if convert_dwg_to_dxf_with_ezdxf(dwg_path, dxf_path):
        return dxf_path
    return None
