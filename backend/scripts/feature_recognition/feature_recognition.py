# -*- coding: utf-8 -*-
"""
特征识别API - 主模块
接收 job_id 和可选的 subgraph_id，从数据库查询文件路径，从MinIO读取并批量识别
"""
# Flask 相关导入已移至 unified_api.py
# from flask import Flask, request, jsonify
import psycopg2
from datetime import datetime
import logging
import os
import tempfile
import shutil
import json
import time
import ezdxf
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional
import sys
from urllib.parse import urlparse

# 加载环境变量
load_dotenv()

# 导入 minio_client（从上级目录）
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from minio_client import minio_client
from dwg_to_dxf_service import convert_dwg_to_dxf

# 导入拆分的模块
from .dimension_extractor import extract_dimensions_with_shape
from .wire_length_calculator import calculate_red_line_length
from .processing_instruction_extractor import (
    extract_processing_instructions, 
    parse_processing_instructions_from_texts
)
from .material_info_extractor import (
    extract_material_info, 
    check_auto_material,
    parse_material_info_from_texts,
    check_auto_material_from_texts
)
from .view_wire_calculator import ViewWireCalculator
from .frame_text_extractor import extract_frame_texts, parse_frame_texts_from_extracted
from .text_extractor import extract_all_texts
from .boring_calculator import calculate_boring_num
from .material_preparation_extractor import extract_material_preparation
from .water_mill_calculator import get_water_mill_data, should_calculate_water_mill
from .hanging_table_detector import detect_hanging_table
from .chamfer_detector import detect_chamfers
from .oil_tank_detector import detect_oil_tank
from .bevel_detector import detect_bevel
from .grinding_detector import detect_grinding_faces
from .tooth_hole_detector import detect_tooth_hole
from .slider_calculator import SliderCalculator
from .slider_red_face_updater import update_slider_red_face_data
from .plate_line_generator import PlateLineGenerator

# Flask app 实例已移至 unified_api.py
# app = Flask(__name__)

# 配置日志
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', 'feature_recognition.log')

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper()),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("scripts.feature_recognition")
# Keep standalone basicConfig above, but route subsequent module log calls to
# the scripts.* logger so MCP writes them into backend/logs/scripts.log.
logging = logger

# 数据库配置 (PostgreSQL)
DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'port': int(os.getenv('DB_PORT')),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME')
}

# API服务配置
API_HOST = os.getenv('API_HOST', '0.0.0.0')
API_PORT = int(os.getenv('API_PORT', 8080))
API_DEBUG = os.getenv('API_DEBUG', 'False').lower() == 'true'
PLATE_LINE_OUTPUT_DIR = Path(__file__).resolve().parents[2] / 'output'
PLATE_LINE_OUTPUT_RETENTION_DAYS = int(os.getenv('PLATE_LINE_OUTPUT_RETENTION_DAYS', '7'))
PLATE_LINE_OUTPUT_CLEANUP_INTERVAL_DAYS = int(os.getenv('PLATE_LINE_OUTPUT_CLEANUP_INTERVAL_DAYS', '1'))
PLATE_LINE_OUTPUT_CLEANUP_STATE_FILE = PLATE_LINE_OUTPUT_DIR / '.plate_line_output_cleanup_state.json'

PLATE_LINE_TRIGGER_TYPES = {
    'plate_line_not_found',
    'plate_line_insufficient',
    'plate_line_partial',
    'plate_line_assignment_failed'
}


def _extract_plate_line_trigger_reason(anomalies: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    for anomaly in anomalies or []:
        anomaly_type = anomaly.get('type')
        if anomaly_type in PLATE_LINE_TRIGGER_TYPES:
            return anomaly_type
    return None


def _extract_view_names_with_bounds(views: Optional[Dict[str, Dict[str, Any]]]) -> List[str]:
    return sorted(
        view_name
        for view_name, view_data in (views or {}).items()
        if isinstance(view_data, dict) and view_data.get('bounds')
    )


def _infer_source_extension(file_url: str) -> str:
    parsed_path = urlparse(file_url or "").path
    suffix = Path(parsed_path).suffix.lower()
    if suffix in {'.dwg', '.dxf'}:
        return suffix
    return '.dxf'


def _prepare_local_dxf_path(local_source_path: str) -> Optional[str]:
    source_path = Path(local_source_path)
    suffix = source_path.suffix.lower()

    if suffix == '.dxf':
        return str(source_path)

    if suffix != '.dwg':
        logging.warning("不支持的图纸格式，跳过处理: %s", local_source_path)
        return None

    converted_path = str(source_path.with_suffix('.dxf'))
    logging.info("检测到 DWG 输入，开始转换 DXF: %s -> %s", local_source_path, converted_path)
    result_path = convert_dwg_to_dxf(str(source_path), converted_path)
    if not result_path:
        logging.warning("DWG 转 DXF 失败: %s", local_source_path)
        return None
    logging.info("DWG 转 DXF 完成: %s", result_path)
    return result_path


def _save_plate_line_output(doc, source_dxf_file_path: str, job_id: Optional[str] = None) -> Optional[str]:
    try:
        output_dir = PLATE_LINE_OUTPUT_DIR / (job_id or 'unknown_job') / 'subgraphs'
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{Path(source_dxf_file_path).stem}_plate_line.dxf"
        doc.saveas(str(output_path))
        logging.info("板料线补线文件已保存: %s", output_path)
        return str(output_path)
    except Exception as exc:
        logging.warning("板料线补线文件保存失败: %s", exc)
        return None


def _maybe_cleanup_plate_line_output_files() -> None:
    if PLATE_LINE_OUTPUT_RETENTION_DAYS <= 0 or PLATE_LINE_OUTPUT_CLEANUP_INTERVAL_DAYS <= 0:
        logging.info(
            "跳过板料线输出清理: retention_days=%s, cleanup_interval_days=%s",
            PLATE_LINE_OUTPUT_RETENTION_DAYS,
            PLATE_LINE_OUTPUT_CLEANUP_INTERVAL_DAYS,
        )
        return

    now_ts = time.time()
    interval_seconds = PLATE_LINE_OUTPUT_CLEANUP_INTERVAL_DAYS * 24 * 60 * 60

    try:
        last_cleanup_ts = _load_plate_line_output_cleanup_state()
        if last_cleanup_ts and now_ts - last_cleanup_ts < interval_seconds:
            return

        cutoff_ts = now_ts - (PLATE_LINE_OUTPUT_RETENTION_DAYS * 24 * 60 * 60)
        deleted_files = _cleanup_plate_line_output_files(PLATE_LINE_OUTPUT_DIR, cutoff_ts)
        _write_plate_line_output_cleanup_state(now_ts)
        logging.info(
            "板料线输出清理完成: deleted_files=%s, retention_days=%s, cleanup_interval_days=%s",
            deleted_files,
            PLATE_LINE_OUTPUT_RETENTION_DAYS,
            PLATE_LINE_OUTPUT_CLEANUP_INTERVAL_DAYS,
        )
    except Exception as exc:
        logging.warning("板料线输出清理失败: %s", exc)


def _load_plate_line_output_cleanup_state() -> float:
    if not PLATE_LINE_OUTPUT_CLEANUP_STATE_FILE.exists():
        return 0.0

    try:
        state = json.loads(PLATE_LINE_OUTPUT_CLEANUP_STATE_FILE.read_text(encoding='utf-8'))
        return float(state.get('last_cleanup_ts', 0.0))
    except Exception as exc:
        logging.warning("读取板料线输出清理状态失败: %s", exc)
        return 0.0


def _write_plate_line_output_cleanup_state(timestamp: float) -> None:
    PLATE_LINE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        'last_cleanup_ts': timestamp,
        'last_cleanup_at': datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'retention_days': PLATE_LINE_OUTPUT_RETENTION_DAYS,
        'cleanup_interval_days': PLATE_LINE_OUTPUT_CLEANUP_INTERVAL_DAYS,
    }
    PLATE_LINE_OUTPUT_CLEANUP_STATE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def _cleanup_plate_line_output_files(root_dir: Path, cutoff_ts: float) -> int:
    if not root_dir.exists():
        return 0

    deleted_files = 0
    for file_path in root_dir.rglob('*_plate_line.dxf'):
        try:
            if file_path.stat().st_mtime < cutoff_ts:
                file_path.unlink()
                deleted_files += 1
        except FileNotFoundError:
            continue
        except Exception as exc:
            logging.warning("删除过期板料线输出文件失败: %s, error=%s", file_path, exc)

    directories = [path for path in root_dir.rglob('*') if path.is_dir()]
    directories.sort(key=lambda path: len(path.parts), reverse=True)
    for directory in directories:
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
        except OSError:
            continue

    return deleted_files


def _build_view_anomalies(views: Optional[Dict[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    missing_views = []
    if not views or not views.get('top_view'):
        missing_views.append('俯视图')
    if not views or not views.get('front_view'):
        missing_views.append('正视图')
    if not views or not views.get('side_view'):
        missing_views.append('侧视图')

    if not missing_views:
        return []

    return [{
        'type': 'view_recognition_failed',
        'description': f"视图识别异常: {', '.join(missing_views)}未识别到",
        'missing_views': missing_views,
    }]


def get_db_connection():
    """获取数据库连接 (PostgreSQL)"""
    try:
        connection = psycopg2.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            database=DB_CONFIG['database'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password']
        )
        return connection
    except Exception as e:
        logging.error(f"数据库连接失败: {str(e)}")
        raise


def get_subgraphs_from_db(job_id: str, subgraph_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    从数据库查询子图信息
    
    Args:
        job_id: 任务ID
        subgraph_id: 子图ID（可选）
    
    Returns:
        子图信息列表
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if subgraph_id:
            # 查询特定子图
            cursor.execute(
                """
                SELECT subgraph_id, part_code, subgraph_file_url, xt_file_url, part_name
                FROM subgraphs
                WHERE job_id = %s AND subgraph_id = %s
                """,
                (job_id, subgraph_id)
            )
        else:
            # 查询所有子图
            cursor.execute(
                """
                SELECT subgraph_id, part_code, subgraph_file_url, xt_file_url, part_name
                FROM subgraphs
                WHERE job_id = %s
                ORDER BY part_code
                """,
                (job_id,)
            )
        
        rows = cursor.fetchall()
        
        subgraphs = []
        for row in rows:
            subgraphs.append({
                'subgraph_id': row[0],
                'part_code': row[1],
                'subgraph_file_url': row[2],
                'xt_file_url': row[3],
                'part_name': row[4] or '',
            })
        
        logging.info(f"从数据库查询到 {len(subgraphs)} 个子图")
        return subgraphs
        
    except Exception as e:
        logging.error(f"查询子图失败: {e}")
        return []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def analyze_dxf_features(dxf_file_path: str, job_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    分析DXF文件特征（优化版：只读取一次文件）
    
    Args:
        dxf_file_path: DXF 文件路径
    
    Returns:
        Dict: 包含特征的字典，失败返回 None
        {
            'length_mm': float,
            'width_mm': float,
            'thickness_mm': float,
            'top_view_wire_length': float,
            'processing_instructions': dict,
            'quantity': int,              # 新增：数量
            'material': str,              # 新增：材质
            'heat_treatment': str,        # 新增：热处理
            'weight_kg': float            # 新增：重量
        }
    """
    try:
        logging.info("=" * 80)
        logging.info("🚀 【阶段1】开始读取DXF文件")
        logging.info(f"   文件路径: {dxf_file_path}")
        logging.info("=" * 80)
        
        doc = ezdxf.readfile(dxf_file_path)  # 只读取一次
        msp = doc.modelspace()
        
        logging.info("")
        logging.info("=" * 80)
        logging.info("📝 【阶段2】文本识别开始")
        logging.info("=" * 80)
        
        all_text_data = extract_all_texts(msp)
        all_texts = all_text_data['texts']
        logging.info(f"✅ 文本识别完成: 共提取 {len(all_texts)} 条有效文本")
        
        logging.info("")
        logging.info("=" * 80)
        logging.info("📐 【阶段3】尺寸提取开始")
        logging.info("=" * 80)
        
        # 提取长宽厚尺寸，并补充材料形状识别结果
        length_mm, width_mm, thickness_mm, shape_info = extract_dimensions_with_shape(doc)
        logging.info(f"✅ 尺寸提取完成: L={length_mm}, W={width_mm}, T={thickness_mm}")
        
        # 检测尺寸缺失异常
        dimension_anomalies = []
        missing_dimensions = []
        if not length_mm:
            missing_dimensions.append('长度')
        if not width_mm:
            missing_dimensions.append('宽度')
        if not thickness_mm:
            missing_dimensions.append('厚度')
        
        if missing_dimensions:
            dimension_anomaly = {
                'type': 'dimension_missing',
                'description': f"零件尺寸缺失: {', '.join(missing_dimensions)}",
                'missing_dimensions': missing_dimensions
            }
            dimension_anomalies.append(dimension_anomaly)
            logging.warning(f"⚠️ 尺寸异常: {dimension_anomaly['description']}")
        
        logging.info("")
        logging.info("=" * 80)
        logging.info("🔧 【阶段4】加工说明解析开始")
        logging.info("=" * 80)
        
        # 提取加工说明（使用预提取的文本）
        # 返回两个值：字典格式的加工说明 和 完整文本列表（用于倒角识别排除）
        processing_instructions_old, instruction_full_texts = parse_processing_instructions_from_texts(all_texts)
        
        # 提取图框中的所有文字（使用预提取的文本）
        frame_texts = parse_frame_texts_from_extracted(all_text_data, doc)
        
        # 提取材质信息（使用预提取的文本）
        material_info = parse_material_info_from_texts(all_texts)
        
        # 检查是否包含"自找料"（使用预提取的文本）
        has_auto_material = check_auto_material_from_texts(all_texts)
        
        # 识别备料信息（提前到这里，用于线割板料重合检测）
        has_material_preparation = extract_material_preparation(all_texts)
        
        # 将图框文字转换为适合保存的格式（只保存文字内容）
        processing_instructions = {}
        all_texts_for_anomaly = []  # 收集所有文字用于异常检测
        
        for frame_id, texts in frame_texts.items():
            # 只保存文字内容，不保存 type, layer, position
            text_contents = [text['content'] for text in texts]
            processing_instructions[frame_id] = text_contents
            all_texts_for_anomaly.extend(text_contents)  # 收集所有文字
        
        logging.info(f"提取到 {len(frame_texts)} 个图框，共 {len(all_texts_for_anomaly)} 条文本")
        
        # 新增：根据长宽厚识别三个视图并分别计算线割长度
        view_wire_lengths = {
            'top_view_wire_length': 0.0,
            'front_view_wire_length': 0.0,
            'side_view_wire_length': 0.0
        }
        wire_cut_anomalies = []
        wire_cut_details = []  # 新增：每个工艺编号的详细信息
        views = None  # 新增：保存阶段5识别的三个视图信息
        view_anomalies = []  # 新增：视图识别异常
        plate_line_generation = None  # 新增：板料线自动补线结果
        
        # 尝试视图识别和线割计算（即使长宽厚缺失，也可能通过板料线识别视图）
        try:
            view_calculator = ViewWireCalculator(tolerance=5.0)
            
            # 如果长宽厚缺失，传入0值，让板料线识别尝试识别视图
            l = length_mm if length_mm else 0
            w = width_mm if width_mm else 0
            t = thickness_mm if thickness_mm else 0
            
            if not (length_mm and width_mm and thickness_mm):
                logging.warning("⚠️ 长宽厚信息不完整，将尝试通过板料线识别视图")
            
            # 使用旧的加工说明格式进行线割计算，并传递所有文字用于异常检测和额外工艺识别
            view_result = view_calculator.calculate_wire_lengths_by_views(
                doc, l, w, t, processing_instructions_old, all_texts  # 使用 all_texts 而不是 all_texts_for_anomaly
            )
            
            view_wire_lengths['top_view_wire_length'] = view_result['top_view_wire_length']
            view_wire_lengths['front_view_wire_length'] = view_result['front_view_wire_length']
            view_wire_lengths['side_view_wire_length'] = view_result['side_view_wire_length']
            view_wire_lengths['unmatched_red_lines'] = view_result.get('unmatched_red_lines', [])  # 新增：获取未匹配的线割实线
            wire_cut_anomalies = view_result.get('wire_cut_anomalies', [])
            wire_cut_details = view_result.get('wire_cut_details', [])
            views = view_result.get('views')  # 新增：获取视图信息

            plate_line_trigger_reason = _extract_plate_line_trigger_reason(wire_cut_anomalies)
            if plate_line_trigger_reason:
                logging.info(
                    "板料线补线触发: reason=%s, dimensions=(L=%s, W=%s, T=%s), input_views=%s",
                    plate_line_trigger_reason,
                    length_mm,
                    width_mm,
                    thickness_mm,
                    _extract_view_names_with_bounds(views),
                )
                if length_mm and width_mm and thickness_mm:
                    plate_line_generator = PlateLineGenerator(tolerance=5.0)
                    plate_line_generation = plate_line_generator.ensure_plate_lines(
                        doc,
                        views,
                        {'L': length_mm, 'W': width_mm, 'T': thickness_mm}
                    )
                    plate_line_generation['triggered'] = True
                    plate_line_generation['reason'] = plate_line_trigger_reason
                    logging.info("板料线补线结果: %s", plate_line_generation)

                    if plate_line_generation.get('added_count', 0) > 0:
                        saved_dxf_path = _save_plate_line_output(doc, dxf_file_path, job_id=job_id)
                        if saved_dxf_path:
                            plate_line_generation['saved_dxf_path'] = saved_dxf_path
                        logging.info("板料线补线完成，准备重算视图和线割长度: %s", plate_line_generation)
                        view_result = view_calculator.calculate_wire_lengths_by_views(
                            doc, l, w, t, processing_instructions_old, all_texts
                        )
                        view_wire_lengths['top_view_wire_length'] = view_result['top_view_wire_length']
                        view_wire_lengths['front_view_wire_length'] = view_result['front_view_wire_length']
                        view_wire_lengths['side_view_wire_length'] = view_result['side_view_wire_length']
                        view_wire_lengths['unmatched_red_lines'] = view_result.get('unmatched_red_lines', [])
                        wire_cut_anomalies = view_result.get('wire_cut_anomalies', [])
                        wire_cut_details = view_result.get('wire_cut_details', [])
                        views = view_result.get('views')
                    else:
                        logging.info(
                            "板料线补线未触发重算: status=%s, generated_views=%s, already_existing_views=%s, skipped_views=%s",
                            plate_line_generation.get('status'),
                            plate_line_generation.get('generated_views', []),
                            plate_line_generation.get('already_existing_views', []),
                            plate_line_generation.get('skipped_views', []),
                        )
                else:
                    plate_line_generation = {
                        'triggered': True,
                        'reason': plate_line_trigger_reason,
                        'status': 'skipped',
                        'input_views': _extract_view_names_with_bounds(views),
                        'generated_views': [],
                        'skipped_views': [],
                        'already_existing_views': [],
                        'added_count': 0,
                        'message': '零件尺寸不完整，跳过补线'
                    }
                    logging.info("板料线补线跳过: %s", plate_line_generation)

            view_anomalies = _build_view_anomalies(views)
            
            logging.info("")
            logging.info("=" * 80)
            logging.info("📊 【阶段7】线割长度计算完成")
            logging.info("=" * 80)
            logging.info(
                f"✅ 视图线割长度: 俯视图={view_wire_lengths['top_view_wire_length']:.2f}mm, "
                f"正视图={view_wire_lengths['front_view_wire_length']:.2f}mm, "
                f"侧视图={view_wire_lengths['side_view_wire_length']:.2f}mm"
            )
            
            if wire_cut_anomalies:
                logging.warning(f"⚠️ 检测到 {len(wire_cut_anomalies)} 个线割异常")
                for anomaly in wire_cut_anomalies:
                    logging.warning(f"   - {anomaly['description']}")

            try:
                slider_calculator = SliderCalculator()
                
                # 从阶段6的结果中获取未匹配的线割实线（避免重复计算）
                unmatched_red_lines = view_wire_lengths.get('unmatched_red_lines', [])
                
                # 添加调试日志
                logging.info(f"从阶段6获取到 {len(unmatched_red_lines)} 个视图的未匹配线割实线数据")
                for view_data in unmatched_red_lines:
                    logging.info(f"  视图 '{view_data['view']}': {len(view_data.get('lines', []))} 条未匹配线割实线")
                
                wire_cut_details, slider_anomaly, _ = slider_calculator.calculate_slider_process(
                    msp=msp,
                    views=views,
                    wire_cut_details=wire_cut_details,
                    unmatched_red_lines=unmatched_red_lines,  # 直接传递阶段6的匹配结果
                    length=l,  # 传递零件长度
                    width=w,   # 传递零件宽度
                    thickness=t  # 传递零件厚度
                )
                
                # 如果检测到滑块，添加到视图异常列表
                if slider_anomaly:
                    view_anomalies.append(slider_anomaly)
                    logging.info(f"⚠️ 滑块异常: {slider_anomaly['description']}")
                    
                    # 移除"未匹配线割实线"异常，因为滑块工艺会使用这些未匹配的线割实线
                    wire_cut_anomalies = [
                        anomaly for anomaly in wire_cut_anomalies 
                        if anomaly.get('type') != 'unmatched_red_lines'
                    ]
                    logging.info("✅ 已移除'未匹配线割实线'异常（滑块工艺使用这些线割实线）")
                    
            except Exception as e:
                logging.warning(f"⚠️ 滑块工艺计算失败: {e}")
                import traceback
                logging.debug(traceback.format_exc())
            
            # 线割实线与板料线重合过滤（在滑块计算之后）
            try:
                from .wire_plate_overlap_filter import WirePlateOverlapFilter
                
                overlap_filter = WirePlateOverlapFilter(overlap_tolerance=0.5)
                
                # 过滤重合部分，更新工艺详情和视图长度
                # 传递自找料和备料信息，用于判断是否需要进行重合检测
                wire_cut_details, view_length_adjustments = overlap_filter.filter_overlapping_wire_cuts(
                    doc, wire_cut_details, views, has_auto_material, has_material_preparation
                )
                
                # 应用视图长度调整
                for view_field, adjustment in view_length_adjustments.items():
                    if adjustment != 0:
                        view_wire_lengths[view_field] += adjustment
                        logging.info(
                            f"✅ {view_field} 调整后长度: {view_wire_lengths[view_field]:.2f}mm "
                            f"(调整量: {adjustment:.2f}mm)"
                        )
                
            except Exception as e:
                logging.warning(f"⚠️ 线割实线与板料线重合过滤失败: {e}")
                import traceback
                logging.debug(traceback.format_exc())
            
        except Exception as e:
            logging.warning(f"⚠️ 视图线割长度计算失败，使用备用方案: {e}")
            import traceback
            logging.debug(traceback.format_exc())
            # 备用方案：使用旧模块计算整体长度
            fallback_length = calculate_red_line_length(doc)
            view_wire_lengths['top_view_wire_length'] = fallback_length
            logging.info(f"📌 备用方案计算结果: {fallback_length:.2f}mm")
        
        # 计算孔的个数
        boring_num = calculate_boring_num(wire_cut_details)
        logging.info(f"✅ 孔数量计算完成: {boring_num} 个")
        
        # 匹配 "x丝割xxxx" 文字
        import re
        wire_process_note = None
        wire_pattern = re.compile(r'[^\s]*丝割[^\s]*')
        for text in all_texts:
            match = wire_pattern.search(text)
            if match:
                wire_process_note = match.group(0)
                logging.info(f"✅ 匹配到线割工艺说明: {wire_process_note}")
                break
        
        # 根据 wire_process_note 映射 wire_process
        wire_process = None
        if wire_process_note:
            wire_process_mapping = {
                '慢丝割一刀': 'slow_cut',
                '慢丝割一修一': 'slow_and_one',
                '慢丝割一修二': 'slow_and_two',
                '慢丝割一修三': 'slow_and_three',
                '中丝割一修一': 'middle_and_one',
                '快丝割一刀': 'fast_cut'
            }
            wire_process = wire_process_mapping.get(wire_process_note)
            if wire_process:
                logging.info(f"✅ 映射线割工艺类型: {wire_process_note} -> {wire_process}")
            else:
                logging.warning(f"⚠️ 未找到匹配的线割工艺类型: {wire_process_note}")
        
        # 构建 abnormal_situation（包含所有异常信息）
        abnormal_situation = {}
        
        # 添加尺寸缺失异常
        if dimension_anomalies:
            abnormal_situation['dimension_anomalies'] = dimension_anomalies
        
        # 添加视图识别异常
        if view_anomalies:
            abnormal_situation['view_anomalies'] = view_anomalies
        
        # 添加线割异常
        if wire_cut_anomalies:
            abnormal_situation['wire_cut_anomalies'] = wire_cut_anomalies
        
        logging.info("")
        logging.info("=" * 80)
        logging.info("💾 【阶段8】通用特征识别（所有零件）")
        logging.info("=" * 80)
        
        # 对所有零件进行倒角、斜面、油槽识别
        # 识别倒角（使用完整文本列表排除加工说明）
        chamfer_counts = detect_chamfers(all_texts, instruction_full_texts)
        
        # 识别油槽
        oil_tank = detect_oil_tank(all_texts, doc)
        logging.info(f"✅ 油槽识别完成: {'有油槽' if oil_tank == 1 else '无油槽'}")
        
        # 识别斜面长度（返回列表）
        bevel = detect_bevel(all_texts, doc, views)
        if bevel:
            logging.info(f"✅ 斜面识别完成: 共 {len(bevel)} 个斜面，长度: {bevel}mm")
        else:
            logging.info(f"✅ 斜面识别完成: 无斜面")
        
        # 识别研磨面数（传入尺寸信息用于视图识别）
        grinding_faces = detect_grinding_faces(doc, length_mm, width_mm, thickness_mm)
        
        # 备用方案：处理尺寸缺失的情况
        if grinding_faces == 0 and not all([length_mm, width_mm, thickness_mm]):
            logging.info("🔄 尝试研磨面识别备用方案（尺寸缺失）")
            fallback_result = fallback_grinding_detection(processing_instructions, doc)
            if fallback_result > 0:
                grinding_faces = fallback_result
                logging.info(f"✅ 备用方案成功: {grinding_faces}面研磨")
            else:
                logging.warning("⚠️ 备用方案也无法识别研磨面")
        
        logging.info(f"✅ 研磨识别完成: {grinding_faces}面研磨")
        
        logging.info("")
        logging.info("=" * 80)
        logging.info("💾 【阶段9】水磨数据判断")
        logging.info("=" * 80)
        
        # 备料信息已在阶段4后提取，这里直接使用
        if has_material_preparation:
            logging.info(f"✅ 识别到备料信息: 备料于{has_material_preparation}")
        else:
            logging.info("ℹ️ 未识别到备料信息")
        
        # 判断是否需要水磨数据（线头和挂台）
        need_water_mill = should_calculate_water_mill(has_material_preparation, has_auto_material)
        
        # 初始化水磨数据相关变量
        hanging_table = 0
        thread_ends = 0  # 默认为0（普通零件）
        
        if need_water_mill:
            # 需要水磨数据，进行线头和挂台识别
            logging.info("")
            logging.info("=" * 80)
            logging.info("🔧 【阶段10】水磨专属特征识别（备料件/自找料）")
            logging.info("=" * 80)
            
            # 线头固定为1（备料件/自找料）
            thread_ends = 1
            logging.info(f"✅ 线头件数: {thread_ends}")
            
            # 识别挂台（返回个数：0, 1, 2...）
            hanging_table = detect_hanging_table(all_texts, doc, length_mm, width_mm, thickness_mm)
            logging.info(f"✅ 挂台识别完成: {hanging_table}个")
        else:
            logging.info("ℹ️ 非备料件/自找料，线头=0，挂台=0")
        
        # 生成水磨数据（所有零件都生成）
        water_mill_data = get_water_mill_data(
            hanging_table=hanging_table,
            c1_c2_chamfer=chamfer_counts['c1_c2_chamfer'],
            c3_c5_chamfer=chamfer_counts['c3_c5_chamfer'],
            r1_r2_chamfer=chamfer_counts['r1_r2_chamfer'],
            r3_r5_chamfer=chamfer_counts['r3_r5_chamfer'],
            oil_tank=oil_tank,
            thread_ends=thread_ends,
            bevel=bevel,
            grinding=grinding_faces  # 新增：传入实际识别的研磨面数
        )
        logging.info("✅ 水磨数据生成完成")
        
        logging.info("")
        logging.info("=" * 80)
        logging.info("🔧 【阶段10】牙孔工艺识别")
        logging.info("=" * 80)
        
        # 识别牙孔（只有自找料且有热处理才识别）
        tooth_hole = detect_tooth_hole(
            all_texts=all_texts,
            processing_instructions=processing_instructions,  # 修复：使用 processing_instructions 而不是 processing_instructions_old
            has_auto_material=has_auto_material,
            heat_treatment=material_info.get('heat_treatment'),
            msp=msp,  # 新增：传入 modelspace
            views=views  # 新增：传入阶段5识别的视图信息
        )
        if tooth_hole:
            logging.info(f"✅ 牙孔识别完成: 共 {len(tooth_hole.get('tooth_hole_details', []))} 个牙孔")
        else:
            logging.info("ℹ️ 无牙孔或不满足识别条件")
        
        # 确保所有值都是 Python 原生类型（避免 numpy 类型导致数据库错误）
        result = {
            'length_mm': float(round(length_mm, 2)) if length_mm else 0.0,
            'width_mm': float(round(width_mm, 2)) if width_mm else 0.0,
            'thickness_mm': float(round(thickness_mm, 2)) if thickness_mm else 0.0,
            'top_view_wire_length': float(round(view_wire_lengths['top_view_wire_length'], 2)),
            'front_view_wire_length': float(round(view_wire_lengths['front_view_wire_length'], 2)),
            'side_view_wire_length': float(round(view_wire_lengths['side_view_wire_length'], 2)),
            'processing_instructions': processing_instructions,
            'quantity': material_info.get('quantity'),
            'material': material_info.get('material'),
            'heat_treatment': material_info.get('heat_treatment'),
            'weight_kg': float(round(material_info.get('weight_kg'), 3)) if material_info.get('weight_kg') else None,
            'has_auto_material': has_auto_material,
            'abnormal_situation': abnormal_situation if abnormal_situation else None,
            'shape': shape_info,
            'wire_cut_details': wire_cut_details,  # 新增：每个工艺编号的详细信息
            'boring_num': boring_num,  # 新增：孔的个数
            'wire_process_note': wire_process_note,  # 新增：线割工艺说明
            'wire_process': wire_process,  # 新增：线割工艺类型
            'has_material_preparation': has_material_preparation,  # 新增：水磨数据（备料信息）
            'water_mill': water_mill_data,  # 新增：水磨数据详情
            'tooth_hole': tooth_hole  # 新增：牙孔数据
        }
        
        logging.info("")
        logging.info("=" * 80)
        logging.info("✅ 【特征提取完成】")
        logging.info("=" * 80)
        logging.info(
            f"   尺寸: L={result['length_mm']}mm, W={result['width_mm']}mm, T={result['thickness_mm']}mm"
        )
        logging.info(
            f"   材料: 数量={result['quantity']}, 材质={result['material']}, 热处理={result['heat_treatment']}, 重量={result['weight_kg']}KG"
        )
        logging.info(
            f"   加工: 自找料={has_auto_material}, 图框文字={sum(len(texts) for texts in processing_instructions.values())}条, 孔数量={boring_num}个"
        )
        logging.info(
            f"   水磨: {'需要' if need_water_mill else '不需要'}, 数据={'已生成' if water_mill_data else '无'}"
        )
        logging.info("=" * 80)
        logging.info("")
        
        return result
        
    except Exception as e:
        logging.error(f"分析DXF文件失败: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
        return None


def save_features_to_db(subgraph_id: str, job_id: str, features: Dict[str, Any]) -> bool:
    """保存特征到数据库（包括加工说明和材质信息）"""
    conn = None
    cursor = None
    try:
        logging.info("")
        logging.info("=" * 80)
        logging.info("💾 【阶段11】保存到数据库")
        logging.info("=" * 80)
        
        conn = get_db_connection()
        cursor = conn.cursor()

        # 保留已存在的 NC 结果，避免后续特征识别回写时覆盖 nc_time_cost / volume_mm3
        cursor.execute(
            """
            SELECT nc_time_cost, volume_mm3
            FROM features
            WHERE subgraph_id = %s AND version = %s
            """,
            (subgraph_id, 1)
        )
        existing_feature_row = cursor.fetchone()
        existing_nc_time_cost = existing_feature_row[0] if existing_feature_row else None
        existing_volume_mm3 = existing_feature_row[1] if existing_feature_row else None
        if existing_nc_time_cost is not None or existing_volume_mm3 is not None:
            logging.info(
                "检测到已有 NC 字段，保存特征时将保留: "
                f"subgraph_id={subgraph_id}, "
                f"has_nc_time_cost={existing_nc_time_cost is not None}, "
                f"has_volume_mm3={existing_volume_mm3 is not None}"
            )
        
        # PostgreSQL 的 jsonb 类型可以直接接受 Python 字典
        # psycopg2 会自动处理 JSON 序列化
        # processing_instructions 现在包含图框中的所有文字
        processing_instructions = features.get('processing_instructions', {})
        
        # 只保存 wire_cut_details 到 metadata
        metadata = {}
        
        # 添加每个工艺编号的详细信息到 metadata
        wire_cut_details = features.get('wire_cut_details', [])

        # ── 滑块红色面查表补充 ──────────────────────────────────────────
        # Do not use template feature-face lookup for slider recognition.
        # Keep slider details from slider_calculator, then update red-face
        # area/length fields later via NX accumulation.
        # ────────────────────────────────────────────────────────────────

        if wire_cut_details:
            metadata['wire_cut_details'] = wire_cut_details
            logging.info(f"保存 {len(wire_cut_details)} 个工艺编号的详细信息到 metadata")
            for detail in wire_cut_details:
                logging.info(
                    f"  - 编号 '{detail['code']}': 期望{detail['expected_count']}个, "
                    f"匹配{detail['matched_count']}个, 总长{detail['total_length']:.2f}mm"
                )
        
        # 使用 (subgraph_id, version) 作为唯一约束
        # version 默认为 1，表示最新版本
        shape_info = features.get('shape')
        if shape_info:
            metadata['shape'] = shape_info
            logging.info(f"保存材料形状信息到 metadata: {shape_info}")

        sql = """
            INSERT INTO features 
            (subgraph_id, job_id, version, length_mm, width_mm, thickness_mm, 
             top_view_wire_length, front_view_wire_length, side_view_wire_length,
             processing_instructions, metadata, abnormal_situation,
             quantity, material, heat_treatment, calculated_weight_kg, needs_heat_treatment, has_auto_material, 
             boring_num, has_material_preparation, water_mill, tooth_hole, nc_time_cost, volume_mm3, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (subgraph_id, version) 
            DO UPDATE SET 
                length_mm = EXCLUDED.length_mm,
                width_mm = EXCLUDED.width_mm,
                thickness_mm = EXCLUDED.thickness_mm,
                top_view_wire_length = EXCLUDED.top_view_wire_length,
                front_view_wire_length = EXCLUDED.front_view_wire_length,
                side_view_wire_length = EXCLUDED.side_view_wire_length,
                processing_instructions = EXCLUDED.processing_instructions,
                metadata = EXCLUDED.metadata,
                abnormal_situation = EXCLUDED.abnormal_situation,
                quantity = EXCLUDED.quantity,
                material = EXCLUDED.material,
                heat_treatment = EXCLUDED.heat_treatment,
                calculated_weight_kg = EXCLUDED.calculated_weight_kg,
                needs_heat_treatment = EXCLUDED.needs_heat_treatment,
                has_auto_material = EXCLUDED.has_auto_material,
                boring_num = EXCLUDED.boring_num,
                has_material_preparation = EXCLUDED.has_material_preparation,
                water_mill = EXCLUDED.water_mill,
                tooth_hole = EXCLUDED.tooth_hole,
                nc_time_cost = COALESCE(features.nc_time_cost, EXCLUDED.nc_time_cost),
                volume_mm3 = COALESCE(features.volume_mm3, EXCLUDED.volume_mm3),
                created_at = EXCLUDED.created_at
            RETURNING feature_id
        """
        
        # 导入 psycopg2.extras 用于 JSON 支持
        from psycopg2.extras import Json
        
        # 根据 heat_treatment 是否有值来确定 needs_heat_treatment
        heat_treatment = features.get('heat_treatment')
        needs_heat_treatment = bool(heat_treatment and heat_treatment.strip())
        
        # 获取 abnormal_situation
        abnormal_situation = features.get('abnormal_situation')
        
        # 获取 water_mill 数据
        water_mill = features.get('water_mill')
        
        # 获取 tooth_hole 数据
        tooth_hole = features.get('tooth_hole')
        
        values = (
            subgraph_id,
            job_id,
            1,  # version 默认为 1（最新版本）
            features['length_mm'],
            features['width_mm'],
            features['thickness_mm'],
            features['top_view_wire_length'],
            features.get('front_view_wire_length', 0.0),
            features.get('side_view_wire_length', 0.0),
            Json(processing_instructions),  # 图框中的所有文字
            Json(metadata) if metadata else None,  # 包含 wire_cut_details（每个工艺的详细信息，包括 area_num）
            Json(abnormal_situation) if abnormal_situation else None,  # 异常情况（包含线割异常）
            features.get('quantity'),  # 新增：数量
            features.get('material'),  # 新增：材质
            heat_treatment,  # 新增：热处理
            features.get('weight_kg'),  # 新增：重量
            needs_heat_treatment,  # 新增：是否需要热处理
            features.get('has_auto_material', False),  # 新增：是否有自找料
            features.get('boring_num', 0),  # 新增：孔的个数
            features.get('has_material_preparation'),  # 新增：水磨数据（备料信息）
            Json(water_mill) if water_mill else None,  # 新增：水磨数据详情
            Json(tooth_hole) if tooth_hole else None,  # 新增：牙孔数据
            Json(existing_nc_time_cost) if existing_nc_time_cost is not None else None,  # 保留已有 NC 明细
            existing_volume_mm3,  # 保留已有 NC 体积
            datetime.now()
        )
        
        cursor.execute(sql, values)
        feature_id = cursor.fetchone()[0]
        
        # 统计图框文字数量
        total_texts = sum(len(texts) for texts in processing_instructions.values()) if isinstance(processing_instructions, dict) else 0
        
        # 统计线割工艺编号数量
        wire_cut_count = len(features.get('wire_cut_details', []))
        
        # 统计线割异常
        anomaly_count = 0
        if abnormal_situation and 'wire_cut_anomalies' in abnormal_situation:
            anomaly_count = len(abnormal_situation['wire_cut_anomalies'])
        
        # 统计牙孔数量
        tooth_hole_count = 0
        if tooth_hole and 'tooth_hole_details' in tooth_hole:
            tooth_hole_count = len(tooth_hole['tooth_hole_details'])
        
        logging.info("✅ 特征数据已保存到 features 表")
        logging.info(
            f"   feature_id={feature_id}, 图框数量={len(processing_instructions)}, 文字数量={total_texts}, "
            f"线割工艺编号={wire_cut_count}个, 线割异常={anomaly_count}个, 孔数量={features.get('boring_num', 0)}个, "
            f"线割工艺说明={features.get('wire_process_note', '无')}, 线割工艺类型={features.get('wire_process', '无')}, "
            f"备料信息={'备料于' + features.get('has_material_preparation') if features.get('has_material_preparation') else '非备料件'}, "
            f"水磨数据={'已保存' if features.get('water_mill') else '无'}, "
            f"牙孔数量={tooth_hole_count}个"
        )
        
        # 打印图框详情（用于调试）
        if processing_instructions:
            logging.info(f"   图框列表: {list(processing_instructions.keys())}")
        
        # 插入到 processing_cost_calculation_details 表
        insert_processing_cost_detail_sql = """
            INSERT INTO processing_cost_calculation_details 
            (job_id, subgraph_id, calculated_at, created_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """
        
        detail_values = (
            job_id,
            subgraph_id,
            datetime.now(),
            datetime.now()
        )
        
        cursor.execute(insert_processing_cost_detail_sql, detail_values)
        
        logging.info(f"✅ 加工成本计算明细已初始化到 processing_cost_calculation_details 表")
        
        # 更新 subgraphs 表的 wire_process_note 和 wire_process 字段
        wire_process_note = features.get('wire_process_note')
        wire_process = features.get('wire_process')
        
        if wire_process_note or wire_process:
            # 构建动态 SQL
            update_fields = []
            update_values = []
            
            if wire_process_note:
                update_fields.append("wire_process_note = %s")
                update_values.append(wire_process_note)
            
            if wire_process:
                update_fields.append("wire_process = %s")
                update_values.append(wire_process)
            
            update_values.append(subgraph_id)
            
            update_subgraph_sql = f"""
                UPDATE subgraphs
                SET {', '.join(update_fields)}
                WHERE subgraph_id = %s
            """
            cursor.execute(update_subgraph_sql, tuple(update_values))
            
            log_msg = []
            if wire_process_note:
                log_msg.append(f"wire_process_note={wire_process_note}")
            if wire_process:
                log_msg.append(f"wire_process={wire_process}")
            logging.info(f"✅ 已更新 subgraphs 表: {', '.join(log_msg)}")
        
        conn.commit()
        
        logging.info("")
        logging.info("=" * 80)
        logging.info("✅ 【特征识别流程完成】")
        logging.info("=" * 80)
        logging.info("")
        
        return True
        
    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"❌ 保存特征失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def batch_feature_recognition_process(job_id: str, subgraph_id: Optional[str] = None) -> Dict[str, Any]:
    """
    批量特征识别处理函数（使用并行下载优化）
    
    Args:
        job_id: 任务ID
        subgraph_id: 子图ID（可选，如果不提供则处理所有子图）
    
    Returns:
        Dict: {
            "success": bool,
            "message": str,
            "data": {
                "total": int,
                "success_count": int,
                "failed_count": int,
                "results": List[Dict]
            }
        }
    """
    temp_dir = None
    
    try:
        logging.info(f"开始批量特征识别 - job_id: {job_id}, subgraph_id: {subgraph_id or '全部'}")
        _maybe_cleanup_plate_line_output_files()
        
        # 1. 从数据库查询子图信息
        subgraphs = get_subgraphs_from_db(job_id, subgraph_id)
        
        if not subgraphs:
            return {
                'success': False,
                'message': f'未找到子图: job_id={job_id}, subgraph_id={subgraph_id}'
            }
        
        # 2. 创建临时目录
        temp_dir = tempfile.mkdtemp()
        
        # 3. 准备并行下载任务列表
        download_tasks = []
        subgraph_map = {}  # 用于快速查找子图信息
        
        for subgraph in subgraphs:
            sg_id = subgraph['subgraph_id']
            file_url = subgraph['subgraph_file_url']
            file_ext = _infer_source_extension(file_url)
            temp_dxf = os.path.join(temp_dir, f"{sg_id}{file_ext}")
            
            download_tasks.append((sg_id, file_url, temp_dxf))
            subgraph_map[sg_id] = {
                'part_code': subgraph['part_code'],
                'part_name': subgraph.get('part_name', ''),
                'temp_path': temp_dxf,
                'file_ext': file_ext,
            }
        
        # 4. 并行下载所有文件
        logging.info(f"准备并行下载 {len(download_tasks)} 个文件...")
        max_workers = int(os.getenv('MINIO_DOWNLOAD_WORKERS', '5'))
        download_results = minio_client.batch_get_files(download_tasks, max_workers=max_workers)
        
        # 5. 处理下载成功的文件
        results = []
        success_count = 0
        failed_count = 0
        
        for sg_id, download_result in download_results.items():
            part_code = subgraph_map[sg_id]['part_code']
            
            if not download_result['success']:
                # 下载失败
                logging.error(f"下载文件失败: {sg_id}")
                results.append({
                    'subgraph_id': sg_id,
                    'part_code': part_code,
                    'success': False,
                    'message': f"下载失败: {download_result.get('error', '未知错误')}"
                })
                failed_count += 1
                continue
            
            try:
                # 分析特征
                temp_source_path = download_result['save_path']
                temp_dxf = _prepare_local_dxf_path(temp_source_path)
                if not temp_dxf:
                    logging.error(f"图纸预处理失败: {sg_id}, source={temp_source_path}")
                    results.append({
                        'subgraph_id': sg_id,
                        'part_code': part_code,
                        'success': False,
                        'message': '图纸预处理失败（DWG 转 DXF 失败或格式不支持）'
                    })
                    failed_count += 1
                    continue

                features = analyze_dxf_features(temp_dxf, job_id=job_id)
                
                if features is None:
                    logging.error(f"特征识别失败: {sg_id}")
                    results.append({
                        'subgraph_id': sg_id,
                        'part_code': part_code,
                        'success': False,
                        'message': '特征识别失败'
                    })
                    failed_count += 1
                    continue
                
                # 保存到数据库
                save_success = save_features_to_db(sg_id, job_id, {
                    **features,
                    'part_code': subgraph_map[sg_id]['part_code'],
                    'part_name': subgraph_map[sg_id]['part_name'],
                })
                
                if save_success:
                    results.append({
                        'subgraph_id': sg_id,
                        'part_code': part_code,
                        'success': True,
                        'features': features
                    })
                    success_count += 1
                    logging.info(f"✅ {sg_id} 处理成功")
                    # ── 滑块红色面写入 ──────────────────────────────────
                    # 如果识别到滑块工艺，尝试从对应的 .x_t 文件提取红色面数据
                    _wire_cut_details = features.get('wire_cut_details', [])
                    # Accept both explicit slider code and instruction text containing "滑"
                    # so we can run NX red-face accumulation after server-side slider detection.
                    _has_slider = any(
                        (d.get('code') == '滑块') or ('滑' in (d.get('instruction') or ''))
                        for d in _wire_cut_details
                    )
                    if _has_slider:
                        _subgraph_info = next(
                            (s for s in subgraphs if s['subgraph_id'] == sg_id), {}
                        )
                        # 直接从数据库字段取 .x_t 路径（由拆图流程上传 MinIO 后写入）
                        _xt_url = _subgraph_info.get('xt_file_url') or ''
                        if _xt_url:
                            logging.info(f"检测到滑块工艺，尝试提取红色面: {_xt_url}")
                            try:
                                update_slider_red_face_data(
                                    subgraph_id=sg_id,
                                    job_id=job_id,
                                    xt_file_url=_xt_url,
                                    db_config=DB_CONFIG,
                                    minio_client=minio_client
                                )
                            except Exception as _e:
                                logging.warning(f"滑块红色面写入失败（不影响主流程）: {_e}")
                        else:
                            logging.info(f"subgraph {sg_id} 无 xt_file_url，跳过红色面提取")
                    # ────────────────────────────────────────────────────
                else:
                    results.append({
                        'subgraph_id': sg_id,
                        'part_code': part_code,
                        'success': False,
                        'message': '保存到数据库失败'
                    })
                    failed_count += 1
                
            except Exception as e:
                logging.error(f"处理子图 {sg_id} 时出错: {e}")
                results.append({
                    'subgraph_id': sg_id,
                    'part_code': part_code,
                    'success': False,
                    'message': str(e)
                })
                failed_count += 1
        
        # 返回结果
        logging.info(f"批量处理完成: 成功 {success_count}, 失败 {failed_count}")
        
        return {
            'success': True,
            'data': {
                'success_count': success_count,
                'failed_count': failed_count,
                'results': results
            }
        }
        
    except Exception as e:
        logging.error(f"批量特征识别异常: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }
    
    finally:
        # 清理临时文件
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass



# ==================== 研磨面识别备用方案 ====================

def fallback_grinding_detection(processing_instructions, doc):
    """
    尺寸缺失时的研磨面识别备用方案
    
    Args:
        processing_instructions: 加工说明字典
        doc: DXF文档对象
    
    Returns:
        int: 推断的研磨面数
    """
    try:
        # 收集所有文本
        all_texts = []
        for frame_texts in processing_instructions.values():
            all_texts.extend(frame_texts)
        
        logging.info(f"🔍 备用方案分析: 共收集到 {len(all_texts)} 条加工说明文本")
        
        # 方法1：直接文本匹配
        text_result = extract_grinding_from_text_patterns(all_texts)
        if text_result > 0:
            logging.info(f"✅ 方法1成功: 直接文本匹配识别到 {text_result} 面研磨")
            return text_result
        
        # 方法2：标准描述推断
        standard_result = infer_grinding_from_standard_descriptions(all_texts)
        if standard_result > 0:
            logging.info(f"✅ 方法2成功: 标准描述推断为 {standard_result} 面研磨")
            return standard_result
        
        # 方法3：符号计数（简化版）
        try:
            msp = doc.modelspace()
            symbol_count = count_grinding_symbols_simple(msp)
            logging.info(f"🔍 检测到 {symbol_count} 个可能的研磨符号")
            
            if symbol_count >= 2:
                estimated_result = estimate_by_symbol_count(symbol_count, all_texts)
                if estimated_result > 0:
                    logging.info(f"✅ 方法3成功: 符号计数推断为 {estimated_result} 面研磨")
                    return estimated_result
        except Exception as e:
            logging.debug(f"符号计数失败: {e}")
        
        logging.info("ℹ️ 所有备用方案都无法确定研磨面数")
        return 0
        
    except Exception as e:
        logging.error(f"备用研磨识别失败: {e}")
        import traceback
        logging.debug(traceback.format_exc())
        return 0


def extract_grinding_from_text_patterns(texts):
    """从文本中直接提取研磨面数"""
    import re
    
    patterns = [
        r'(\d+)\s*面\s*研磨',
        r'研磨\s*(\d+)\s*面',
        r'磨\s*(\d+)\s*面',
        r'(\d+)\s*面.*磨',
    ]
    
    for text in texts:
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                faces = int(match.group(1))
                logging.info(f"🎯 文本匹配: '{text}' → {faces}面研磨")
                return faces
    
    return 0


def infer_grinding_from_standard_descriptions(texts):
    """基于标准描述推断研磨面数"""
    import re
    
    # 标准研磨描述模式 (描述, 推断面数)
    standard_patterns = [
        (r'D\s*:\s*\d+\s*-\s*研磨基准边[，,]\s*深度准[，,]\s*侧壁准', 4),
        (r'研磨基准边.*深度准.*侧壁准', 4),
        (r'全周.*研磨', 6),
        (r'两面.*研磨', 2),
        (r'四面.*研磨', 4),
        (r'六面.*研磨', 6),
        (r'研磨.*基准.*边', 4),  # 简化的基准边描述
    ]
    
    for text in texts:
        for pattern, faces in standard_patterns:
            if re.search(pattern, text):
                logging.info(f"🎯 标准描述匹配: '{text}' → {faces}面研磨")
                return faces
    
    return 0


def count_grinding_symbols_simple(msp):
    """简化的研磨符号计数"""
    try:
        grinding_count = 0
        
        # 方法1：统计特定块名
        target_blocks = ['XYMFH-A', 'XYMFH', 'XYMFH-A0', '研磨标记', '磨削标记']
        for entity in msp.query('INSERT'):
            try:
                if entity.dxf.name in target_blocks:
                    grinding_count += 1
                    logging.debug(f"发现研磨块: {entity.dxf.name}")
            except:
                continue
        
        # 方法2：统计可能的研磨多段线（简化检测）
        polylines = list(msp.query('POLYLINE')) + list(msp.query('LWPOLYLINE'))
        for polyline in polylines:
            try:
                points = list(polyline.get_points('xy'))
                # 研磨符号通常有6-20个点（3个三角形）
                if 6 <= len(points) <= 20:
                    # 简单检查是否可能是锯齿状
                    if is_likely_grinding_symbol(points):
                        grinding_count += 1
                        logging.debug(f"发现可能的研磨多段线: {len(points)}个点")
            except:
                continue
        
        return grinding_count
        
    except Exception as e:
        logging.debug(f"符号计数异常: {e}")
        return 0


def is_likely_grinding_symbol(points):
    """简单判断点序列是否可能是研磨符号"""
    try:
        if len(points) < 6:
            return False
        
        # 计算Y坐标的变化次数（锯齿状应该有多次上下变化）
        y_changes = 0
        for i in range(1, len(points)):
            if i < len(points) - 1:
                y1, y2, y3 = points[i-1][1], points[i][1], points[i+1][1]
                # 检查是否有峰值或谷值
                if (y2 > y1 and y2 > y3) or (y2 < y1 and y2 < y3):
                    y_changes += 1
        
        # 研磨符号应该有至少3个峰值/谷值
        return y_changes >= 3
        
    except:
        return False


def estimate_by_symbol_count(symbol_count, texts):
    """基于符号数量和文本推断"""
    
    # 检查文本中的关键词
    text_content = ' '.join(texts)
    has_standard = '研磨基准边' in text_content
    has_full_perimeter = '全周' in text_content
    has_depth_side = '深度准' in text_content and '侧壁准' in text_content
    
    logging.info(f"🔍 文本特征: 基准边={has_standard}, 全周={has_full_perimeter}, 深度侧壁={has_depth_side}")
    
    # 基于文本特征和符号数量的推断规则
    if has_standard or has_depth_side:
        # 有标准研磨描述，通常是4面研磨
        if 2 <= symbol_count <= 6:
            return 4
        elif symbol_count > 6:
            return 6
    
    if has_full_perimeter and symbol_count >= 4:
        return 6
    
    # 纯符号计数的保守推断
    if symbol_count == 2:
        return 2
    elif symbol_count in [3, 4]:
        return 4
    elif symbol_count >= 5:
        return 6
    
    return 0
