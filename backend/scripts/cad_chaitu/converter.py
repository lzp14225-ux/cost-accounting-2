#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DWG/DXF 格式转换模块
"""

import os
import subprocess
import tempfile
import shutil
from loguru import logger


class DWGConverter:
    """DWG <-> DXF 转换器（基于 ODA File Converter）"""
    
    def __init__(self, oda_converter_path: str = None):
        self.oda_converter_path = oda_converter_path

    def _convert(self, input_file, output_file, output_format, output_version='ACAD2004'):
        """使用 ODAFileConverter.exe 转换文件格式"""
        if not os.path.exists(input_file):
            logger.debug(f"错误：找不到输入文件 {input_file}")
            return None

        if not os.path.exists(self.oda_converter_path):
            logger.error(f"错误：找不到 ODA 转换器: {self.oda_converter_path}")
            return None

        temp_output_dir = tempfile.mkdtemp(prefix="oda_output_")
        input_dir = os.path.dirname(input_file)

        command = [
            self.oda_converter_path,
            input_dir,
            temp_output_dir,
            output_version,
            output_format,
            '0',
            '1',
        ]

        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=300, shell=False)
            base_name = os.path.splitext(os.path.basename(input_file))[0]
            generated_file = os.path.join(temp_output_dir, f"{base_name}.{output_format.lower()}")
            if os.path.exists(generated_file):
                shutil.move(generated_file, output_file)
                return output_file
            else:
                return None
        except subprocess.TimeoutExpired:
            logger.error(f"转换超时（300秒）")
            return None
        except subprocess.CalledProcessError as e:
            logger.error(f"转换失败，返回码: {e.returncode}")
            logger.error(f"标准输出: {e.stdout}")
            logger.error(f"标准错误: {e.stderr}")
            return None
        except Exception as e:
            logger.error(f"转换失败: {type(e).__name__}: {e}")
            return None
        finally:
            try:
                shutil.rmtree(temp_output_dir)
            except Exception:
                pass

    def convert_dwg_to_dxf(self, input_dwg_file, output_dxf_file):
        """DWG -> DXF"""
        return self._convert(input_dwg_file, output_dxf_file, 'DXF')

    def convert_dxf_to_dwg(self, input_dxf_file, output_dwg_file, output_version='ACAD2004'):
        """DXF -> DWG"""
        return self._convert(input_dxf_file, output_dwg_file, 'DWG', output_version)

if __name__ == "__main__":
    converter = DWGConverter(oda_converter_path=r"D:\ODAFileConverter 26.7.0\ODAFileConverter.exe")
    converter.convert_dwg_to_dxf(r"D:\AI\Pycharm\chengben2\mold_main\backend\scripts\cad_chaitu\input.dwg", r"output.dxf")