#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CAD 拆图主处理流程
"""

import os
import tempfile
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict
import asyncio
from concurrent.futures import ThreadPoolExecutor
from loguru import logger
from dotenv import load_dotenv

# 禁用 ezdxf 的日志输出
logging.getLogger('ezdxf').setLevel(logging.WARNING)

# 加载项目根目录的 .env 文件
_project_root = Path(__file__).parent.parent.parent
_env_path = _project_root / '.env'
if _env_path.exists():
    load_dotenv(_env_path)
    logger.info(f"✅ 加载配置文件: {_env_path}")
else:
    logger.error(f"❌ 配置文件不存在: {_env_path}")
    raise FileNotFoundError(f"配置文件不存在: {_env_path}")

# 直接从环境变量读取配置（不使用默认值）
ODA_FILE_CONVERTER_PATH = os.getenv('ODA_FILE_CONVERTER_PATH')
DB_HOST = os.getenv('DB_HOST')
DB_PORT = int(os.getenv('DB_PORT')) if os.getenv('DB_PORT') else None
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')

# 验证必需的配置项
_required_configs = {
    'ODA_FILE_CONVERTER_PATH': ODA_FILE_CONVERTER_PATH,
    'DB_HOST': DB_HOST,
    'DB_PORT': DB_PORT,
    'DB_NAME': DB_NAME,
    'DB_USER': DB_USER,
    'DB_PASSWORD': DB_PASSWORD,
}

_missing_configs = [k for k, v in _required_configs.items() if v is None]
if _missing_configs:
    logger.error(f"❌ 缺少必需的配置项: {', '.join(_missing_configs)}")
    raise ValueError(f"缺少必需的配置项: {', '.join(_missing_configs)}")

logger.info(f"✅ 配置加载完成: ODA={ODA_FILE_CONVERTER_PATH}, DB={DB_HOST}:{DB_PORT}/{DB_NAME}")

# 支持相对导入和绝对导入
try:
    # 尝试相对导入（作为包使用时）
    from .converter import DWGConverter
    from .cad_system import CADAnalysisSystem
    from .database import DatabaseManager
    from .storage import FileStorageManager
    from .utils import extract_model_code_from_source
except ImportError:
    # 绝对导入（直接运行时）
    from converter import DWGConverter
    from cad_system import CADAnalysisSystem
    from database import DatabaseManager
    from storage import FileStorageManager
    from utils import extract_model_code_from_source


# 全局实例
db_manager = None
storage_manager = None
_minio_client = None


def init_managers(minio_client=None):
    """初始化管理器"""
    global db_manager, storage_manager, _minio_client
    
    # 保存 minio_client 引用
    _minio_client = minio_client
    
    # 初始化数据库管理器
    if db_manager is None:
        db_manager = DatabaseManager(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
    
    # 初始化存储管理器
    if storage_manager is None:
        storage_manager = FileStorageManager(minio_client=minio_client)
    
    logger.info("✅ 管理器初始化完成")


async def chaitu_process(dwg_url: Optional[str], job_id: str, minio_client=None) -> Dict:
    """
    拆图处理函数
    
    Args:
        dwg_url: DWG 文件的 URL 或本地路径（可选，如果不提供则从数据库查询）
        job_id: 任务ID（用于关联数据库和查询 dwg_file_path）
        minio_client: MinIO 客户端实例（可选）
    
    Returns:
        Dict: {
            "status": "ok" | "error",
            "message": str,
            "data": {...} (可选)
        }
    """
    global _minio_client
    
    # 如果传入了 minio_client，使用传入的
    if minio_client is not None:
        _minio_client = minio_client
    
    # 如果还没有 minio_client，尝试从上层导入
    if _minio_client is None:
        try:
            import sys
            # 添加 scripts 目录到路径
            scripts_dir = Path(__file__).parent.parent
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            from minio_client import minio_client as imported_client
            _minio_client = imported_client
            logger.info("✅ 成功导入 MinIO 客户端")
        except ImportError as e:
            logger.warning(f"⚠️ 无法导入 MinIO 客户端: {e}")
            _minio_client = None
        except Exception as e:
            logger.warning(f"⚠️ 导入 MinIO 客户端时出错: {e}")
            _minio_client = None
    
    # 初始化管理器
    if db_manager is None or storage_manager is None:
        init_managers(_minio_client)
    
    temp_dir = None
    try:
        # 确定 DWG 文件来源
        dwg_source = dwg_url
        use_minio = False
        
        # 如果没有提供 dwg_url，则从数据库查询
        if not dwg_source:
            logger.info(f"未提供 dwg_url，从数据库查询 job_id={job_id} 的 dwg_file_path")
            dwg_file_path = db_manager.get_dwg_file_path(job_id)
            
            if not dwg_file_path:
                return {"status": "error", "message": f"未找到 job_id={job_id} 对应的 dwg_file_path"}
            
            dwg_source = dwg_file_path
            use_minio = True
            logger.info(f"从数据库查询到 dwg_file_path: {dwg_source}")
        
        # 从路径或 URL 提取源文件名（不含扩展名）
        if dwg_source.startswith(('http://', 'https://')):
            url_filename = dwg_source.split('/')[-1]
        else:
            url_filename = Path(dwg_source).name
        
        source_filename = os.path.splitext(url_filename)[0]
        
        # 提取模型代码（用于日志）
        model_code = extract_model_code_from_source(dwg_source) or source_filename
        
        logger.info(f"收到拆图请求: dwg_source={dwg_source}, job_id={job_id}, use_minio={use_minio}")
        logger.info(f"源文件名: {source_filename}, 模型代码: {model_code}")

        # 1. 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix="chaidan_cad_")
        temp_dwg = os.path.join(temp_dir, "input.dwg")
        temp_dxf = os.path.join(temp_dir, "input.dxf")

        # 2. 获取 DWG 文件
        if not await storage_manager.get_file(dwg_source, temp_dwg, use_minio=use_minio):
            return {"status": "error", "message": "获取 DWG 文件失败"}

        # 3. 转换 DWG -> DXF
        converter = DWGConverter(ODA_FILE_CONVERTER_PATH)
        
        if not converter.convert_dwg_to_dxf(temp_dwg, temp_dxf):
            return {"status": "error", "message": "DWG -> DXF 转换失败"}

        logger.info(f"✅ DXF 转换成功: {temp_dxf}")

        # 4. 准备流式处理
        result_files = []
        timestamp = datetime.now()
        year = timestamp.strftime("%Y")
        month = timestamp.strftime("%m")
        
        # MinIO 路径格式: dxf/2026/01/{job_id}/{subgraph_id}.dxf
        minio_base_path = f"dxf/{year}/{month}/{job_id}"
        
        logger.info(f"MinIO 基础路径: {minio_base_path}")
        logger.info("开始流式分析和处理 DXF 文件...")

        # 5. 新流程：先识别所有子图，再批量处理和上传
        analysis_system = CADAnalysisSystem()
        analysis_time = 0
        export_time = 0
        upload_time = 0
        db_time = 0
        
        total_start = datetime.now()
        
        # 步骤1: 识别所有子图
        logger.info("步骤1: 开始识别所有子图...")
        analysis_start = datetime.now()
        
        try:
            # 一次性识别所有子图
            all_regions = []
            for region_id, region, index, total in analysis_system.analyzer.analyze_cad_file_streaming(temp_dxf):
                if index == 1:
                    logger.info(f"✅ 识别到 {total} 个子图")
                all_regions.append((region_id, region))
            
            analysis_time = (datetime.now() - analysis_start).total_seconds()
            logger.info(f"✅ 子图识别完成，共 {len(all_regions)} 个子图 (耗时: {analysis_time:.2f}s)")
            
            if not all_regions:
                return {"status": "error", "message": "未识别到任何子图"}
            
            # 步骤2: 在各个子图范围内识别编号和品名
            logger.info("步骤2: 识别各子图的编号、品名和编号...")
            region_info_list = []
            failed_recognition_count = 0
            
            # 用于跟踪已使用的 sub_code，处理重复
            used_sub_codes = {}  # {base_code: count}
            
            for index, (region_id, region) in enumerate(all_regions, 1):
                try:
                    sub_code, part_name, part_code = analysis_system.analyzer.resolve_region_info(region_id, region)
                    
                    # 确保 part_name 有值
                    if not part_name:
                        part_name = "未识别"
                    
                    # 确保 part_code 有值
                    if not part_code:
                        part_code = region_id
                    
                    # 使用 part_code 作为 sub_code 的基础
                    # 如果 sub_code 为空或是 region_id，使用 part_code
                    if not sub_code or sub_code == region_id:
                        base_code = part_code
                    else:
                        base_code = sub_code
                    
                    # 处理重复的 sub_code，添加后缀 A, B, C...
                    if base_code in used_sub_codes:
                        # 已经使用过，添加后缀
                        count = used_sub_codes[base_code]
                        suffix = chr(ord('A') + count)  # A, B, C, ...
                        final_sub_code = f"{base_code}{suffix}"
                        used_sub_codes[base_code] += 1
                        logger.info(f"   检测到重复编号 {base_code}，添加后缀: {final_sub_code}")
                    else:
                        # 第一次使用
                        final_sub_code = base_code
                        used_sub_codes[base_code] = 1
                    
                    region_info_list.append({
                        'region_id': region_id,
                        'region': region,
                        'sub_code': final_sub_code,
                        'part_name': part_name,
                        'part_code': part_code,
                        'index': index
                    })
                    
                except Exception as e:
                    failed_recognition_count += 1
                    logger.error(f"[{index}/{len(all_regions)}] ❌ 识别编号、品名和编号失败: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    continue
            
            logger.info(f"✅ 编号、品名和编号识别完成，成功识别 {len(region_info_list)} 个子图，失败 {failed_recognition_count} 个")
            
            if not region_info_list:
                return {"status": "error", "message": "所有子图的编号和品名识别失败"}
            
            # 步骤3: 智能选择导出策略
            logger.info("步骤3: 开始导出所有子图...")
            export_start = datetime.now()
            
            # 准备批量导出列表
            batch_export_list = []
            for info in region_info_list:
                sub_code = info['sub_code']
                region = info['region']
                temp_output_dxf = os.path.join(temp_dir, f"output_{sub_code}.dxf")
                
                batch_export_list.append({
                    'sub_code': sub_code,
                    'region': region,
                    'output_path': temp_output_dxf
                })
            
            # 使用并发方案导出（每个子图独立读取文件）
            max_workers = int(os.getenv('EXPORT_WORKERS', '5'))
            logger.info(f"使用并发方案导出 {len(batch_export_list)} 个子图 (并发数: {max_workers})")
            export_results = analysis_system.batch_export_regions_concurrent(
                batch_export_list,
                pad=0.0,
                horizontal_spacing=50.0,
                align_to_origin=True,
                max_workers=max_workers
            )
            
            # 处理导出结果
            export_files = []
            failed_export_count = 0
            for i, result in enumerate(export_results):
                info = region_info_list[i]
                sub_code = result['sub_code']
                index = info['index']
                part_name = info['part_name']
                part_code = info.get('part_code')  # 获取 part_code
                
                if result['success']:
                    export_files.append({
                        'sub_code': sub_code,
                        'part_name': part_name,
                        'part_code': part_code,
                        'local_path': result['output_path'],
                        'minio_path': f"{minio_base_path}/{sub_code}.dxf",
                        'index': index
                    })
                else:
                    failed_export_count += 1
                    logger.warning(f"⚠️ 导出失败 [{failed_export_count}]: {sub_code} - {result.get('error', '未知错误')}")
            
            export_time = (datetime.now() - export_start).total_seconds()
            logger.info(f"✅ 子图导出完成，成功导出 {len(export_files)} 个文件，失败 {failed_export_count} 个 (耗时: {export_time:.2f}s)")
            
            if not export_files:
                return {"status": "error", "message": "所有子图导出失败"}
            
            # 步骤4: 并发上传所有子图到MinIO
            logger.info("步骤4: 开始并发上传所有子图到MinIO...")
            upload_start = datetime.now()
            
            # 准备上传文件列表
            upload_list = [
                (f['sub_code'], f['local_path'], f['minio_path'])
                for f in export_files
            ]
            
            # 使用MinIO客户端的批量上传功能
            upload_results = _minio_client.batch_upload_files(upload_list)
            
            upload_time = (datetime.now() - upload_start).total_seconds()
            
            # 步骤5: 保存成功上传的文件到数据库
            logger.info("步骤5: 保存数据到数据库...")
            db_start = datetime.now()
            db_success_count = 0
            failed_upload_count = 0
            failed_db_count = 0
            
            for file_info in export_files:
                sub_code = file_info['sub_code']
                
                # 检查上传是否成功
                if sub_code not in upload_results or not upload_results[sub_code].get('success'):
                    failed_upload_count += 1
                    upload_error = upload_results.get(sub_code, {}).get('error', '未知错误')
                    logger.warning(f"⚠️ 上传失败 [{failed_upload_count}]: {sub_code} - {upload_error}")
                    continue
                
                try:
                    db_manager.save_subgraph(
                        sub_code,
                        file_info['minio_path'],
                        source_filename,
                        job_id,
                        file_info['part_name'],
                        file_info.get('part_code')
                    )
                    
                    result_files.append({
                        "path": file_info['minio_path'],
                        "filename": f"{sub_code}.dxf",
                        "sub_code": sub_code,
                        "source_file": source_filename,
                        "part_name": file_info['part_name'],
                        "part_code": file_info.get('part_code')
                    })
                    
                    db_success_count += 1
                    
                except Exception as e:
                    failed_db_count += 1
                    logger.error(f"❌ 保存数据库失败 [{failed_db_count}]: {sub_code} - {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    continue
            
            db_time = (datetime.now() - db_start).total_seconds()
            logger.info(
                f"✅ 数据库保存完成，成功保存 {db_success_count} 条记录，"
                f"上传失败 {failed_upload_count} 个，数据库失败 {failed_db_count} 个 (耗时: {db_time:.2f}s)"
            )
        
        except Exception as e:
            logger.error(f"处理异常: {e}")
            return {"status": "error", "message": f"处理失败: {e}"}
        
        if not result_files:
            return {"status": "error", "message": "所有子图处理失败"}

        total_time = (datetime.now() - total_start).total_seconds()
        avg_time = total_time / len(result_files) if result_files else 0
        
        logger.info(f"✅ 拆图完成！成功处理 {len(result_files)} 个子图")
        logger.info("=" * 80)
        logger.info("📊 处理流程统计:")
        logger.info(f"   步骤1 - 识别图框: {len(all_regions)} 个")
        logger.info(f"   步骤2 - 识别编号品名: {len(region_info_list)} 个 (失败 {failed_recognition_count} 个)")
        logger.info(f"   步骤3 - 导出子图: {len(export_files)} 个 (失败 {failed_export_count} 个)")
        logger.info(f"   步骤4 - 上传MinIO: {len(export_files) - failed_upload_count} 个 (失败 {failed_upload_count} 个)")
        logger.info(f"   步骤5 - 保存数据库: {db_success_count} 个 (失败 {failed_db_count} 个)")
        logger.info(f"   最终结果: {len(result_files)} 个子图成功")
        logger.info("=" * 80)
        logger.info(
            f"📊 性能统计: "
            f"识别={analysis_time:.2f}s, "
            f"导出={export_time:.2f}s, "
            f"上传={upload_time:.2f}s, "
            f"数据库={db_time:.2f}s, "
            f"总耗时={total_time:.2f}s, "
            f"平均={avg_time:.2f}s/个"
        )
        logger.info(f"📁 MinIO 路径: {minio_base_path}")

        # 提取文件名列表
        filenames = [item["filename"] for item in result_files]

        return {
            "status": "ok",
            "data": {
                "total_count": len(result_files),
                "result_files": filenames
            }
        }

    except Exception as e:
        logger.error(f"拆图异常: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
    
    finally:
        # 清理分析系统缓存
        try:
            if 'analysis_system' in locals():
                analysis_system.clear_cache()
                logger.debug("✅ 缓存清理完成")
        except Exception as e:
            logger.warning(f"清理缓存失败: {e}")
        
        # 清理临时目录
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.warning(f"清理临时目录失败: {e}")
