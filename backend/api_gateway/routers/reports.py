"""
报表导出API路由 - xlsxwriter 版本
性能比 openpyxl 快 20-30%
标题行：worksheet.set_row(0, 30)
表头行：worksheet.set_row(1, 40)
数据行：在数据循环里加 worksheet.set_row(row, 你想要的高度)
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import xlsxwriter
from io import BytesIO
from datetime import datetime
import logging
from uuid import UUID
import asyncio
from pathlib import Path
from urllib.parse import quote
import json
import re

from shared.database import get_db
from shared.models import Job, Subgraph, Feature
from shared.validators.completeness_validator import CompletenessValidator
from api_gateway.utils.minio_client import upload_file_to_minio, get_file_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

# 报表生成状态缓存
report_status = {}

# 常量定义
ASYNC_THRESHOLD = 500
REPORT_BUCKET = "reports"
REPORT_EXPIRY_DAYS = 7
EXPORT_EXCLUDE_KEYWORDS = ["订购", "附图订购", "二次加工", "钣金"]

# 表头定义
HEADERS = [
    '序号', '编号', '零件名称', '材质', '备料于', '数量', '长/mm', '宽/mm', '厚/mm', '重量/kg',
    '热处理', '工艺', '材料单价', '材料费（元）', '开粗后体积', '开粗后重量', '热处理单价', '热处理费（元）',
    '单件加工费合计（元）', '热处理+加工费（元）', '加工费（按重量计算）', '单件费用合计（元）', '费用合计（元） 材料费+热处理+加工费',
    'NC开粗时间(单件/h)', 'NC精铣时间(单件/h)', 'NC钻孔时间(单件/h)', 'NC加工面数量',
    'A面(单件/h)', 'B面(单件/h)', 'C面(单件/h)', 'D面(单件/h)', 'E面(单件/h)', 'F面(单件/h)',
    'NC加工费（单件/元）',
    '小磨床 YM(h)', '小磨床（元）', '大水磨 M(h)', '大水磨（元）',
    '慢丝 W/E(mm)', '侧割长度(mm)', '中丝 W/Z(mm)', '快丝 W/C(mm)', '线割时间', '线割工艺说明',
    '慢丝（元）', '侧割（元）', '中丝（元）', '快丝（元）',
    '放电 EDM(h)', '放电（元）', '雕刻 DK(h)', '雕刻（元）',
    '异常情况'
]

SUM_COLUMNS = [
    5,   # 数量
    13,  # 材料费（元）
    16, 17,                          # 开粗后重量/热处理费
    18, 19, 20, 21, 22,              # 加工费/单独计费/费用合计
    23, 24, 25,                      # NC开粗/精铣/钻孔时间
    27, 28, 29, 30, 31, 32,          # A-F面工时
    33,                              # NC加工费（单件/元）
    34, 35, 36, 37,                  # 磨床
    38, 39, 40, 41, 42,              # 线割长度/时间
    44, 45, 46, 47,                  # 线割费用
    48, 49, 50, 51                   # 放电/雕刻工时费用
]


@router.get("/{job_id}/export")
async def export_pricing_report(
    job_id: str,
    format: str = "xlsx",
    async_mode: bool = None,
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = None
):
    """导出价格报表 - xlsxwriter 版本"""
    try:
        logger.info(f"[xlsxwriter] 开始导出报表: job_id={job_id}")
        
        job_uuid = _validate_job_id(job_id)
        job_data = await _fetch_report_data(db, job_uuid)
        
        if async_mode is None:
            async_mode = len(job_data['subgraphs']) >= ASYNC_THRESHOLD
        
        if format.lower() != "xlsx":
            raise HTTPException(status_code=400, detail="目前仅支持xlsx格式")
        
        if async_mode:
            return _start_async_export(job_id, job_data, background_tasks)
        
        return await _sync_export(job_id, job_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出报表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导出报表失败: {str(e)}")


def _validate_job_id(job_id: str) -> UUID:
    """验证job_id"""
    try:
        return UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的任务ID格式")


async def _fetch_report_data(db: AsyncSession, job_uuid: UUID) -> dict:
    """优化的数据查询"""
    logger.info(f"[数据查询] 开始: job_id={job_uuid}")
    
    # 使用预加载
    result = await db.execute(
        select(Job)
        .options(selectinload(Job.subgraphs))
        .where(Job.job_id == job_uuid)
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    if not job.subgraphs:
        raise HTTPException(status_code=404, detail="没有找到子图数据")
    
    # 批量查询Feature
    subgraph_ids = [sg.subgraph_id for sg in job.subgraphs]
    result = await db.execute(
        select(Feature)
        .where(Feature.job_id == job_uuid)
        .where(Feature.subgraph_id.in_(subgraph_ids))
        .order_by(Feature.subgraph_id, Feature.version.desc())
    )
    features = result.scalars().all()
    
    # 构建特征字典
    features_dict = {}
    for feature in features:
        if feature.subgraph_id not in features_dict:
            features_dict[feature.subgraph_id] = feature

    filtered_subgraphs = await _filter_export_subgraphs(list(job.subgraphs), features_dict)
    if not filtered_subgraphs:
        raise HTTPException(status_code=404, detail="过滤后没有可导出的子图数据")
    
    logger.info(
        f"[数据查询] 完成: 原始 {len(job.subgraphs)} 个子图, "
        f"过滤后 {len(filtered_subgraphs)} 个子图"
    )
    
    return {
        'job': job,
        'subgraphs': filtered_subgraphs,
        'features_dict': features_dict
    }


async def _filter_export_subgraphs(subgraphs: list[Subgraph], features_dict: dict) -> list[Subgraph]:
    """导出前过滤不需要进入报表的零件。"""
    tasks = [
        _should_exclude_from_report(subgraph, features_dict.get(subgraph.subgraph_id))
        for subgraph in subgraphs
    ]
    exclude_flags = await asyncio.gather(*tasks)
    return [
        subgraph
        for subgraph, should_exclude in zip(subgraphs, exclude_flags)
        if not should_exclude
    ]


async def _should_exclude_from_report(subgraph: Subgraph, feature: Feature | None) -> bool:
    """两层判断：
    1. 先按零件名称模糊匹配；
    2. 再按 processing_instructions 内容模糊匹配。
    """
    part_name = str(subgraph.part_name or "").strip()
    if _contains_export_exclude_keyword(part_name):
        return True

    processing_text = _flatten_processing_instructions(
        getattr(feature, "processing_instructions", None)
    )
    return _contains_export_exclude_keyword(processing_text)


def _contains_export_exclude_keyword(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return any(keyword in normalized for keyword in EXPORT_EXCLUDE_KEYWORDS)


def _flatten_processing_instructions(value) -> str:
    """把 processing_instructions 递归压平成字符串，便于模糊匹配。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_processing_instructions(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_processing_instructions(item) for item in value)
    return str(value)


def _start_async_export(job_id: str, job_data: dict, background_tasks: BackgroundTasks):
    """启动异步导出"""
    report_status[job_id] = {
        "status": "processing",
        "progress": 0,
        "total": len(job_data['subgraphs']),
        "started_at": datetime.now().isoformat(),
        "file_url": None,
        "error": None
    }
    
    background_tasks.add_task(_generate_report_async, job_id, job_data)
    
    return JSONResponse({
        "mode": "async",
        "status": "processing",
        "message": "报表正在后台生成中",
        "job_id": job_id,
        "total_subgraphs": len(job_data['subgraphs']),
        "status_url": f"/api/v1/reports/{job_id}/status"
    })


async def _sync_export(job_id: str, job_data: dict):
    """同步导出"""
    file_stream = await asyncio.to_thread(generate_excel_report, job_data)
    
    filename = f"{job_data['job'].dwg_file_name or job_id}_报价单_{datetime.now().strftime('%Y%m%d')}.xlsx"
    ascii_filename = f"report_{datetime.now().strftime('%Y%m%d')}.xlsx"
    encoded_filename = quote(filename)
    
    logger.info(f"报表生成成功: {filename}")
    
    return StreamingResponse(
        file_stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}',
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )


async def _generate_report_async(job_id: str, job_data: dict):
    """异步生成报表"""
    try:
        logger.info(f"开始异步生成报表: job_id={job_id}")
        
        file_stream = await asyncio.to_thread(generate_excel_report, job_data)
        
        filename = f"{job_data['job'].dwg_file_name or job_id}_报价单_{datetime.now().strftime('%Y%m%d')}.xlsx"
        file_path = f"reports/{job_id}/{filename}"
        
        try:
            file_stream.seek(0)
            upload_file_to_minio(
                bucket_name=REPORT_BUCKET,
                object_name=file_path,
                file_data=file_stream,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            file_url = get_file_url(
                bucket_name=REPORT_BUCKET,
                object_name=file_path,
                expires=REPORT_EXPIRY_DAYS * 24 * 3600
            )
            
            report_status[job_id].update({
                "status": "completed",
                "progress": len(job_data['subgraphs']),
                "completed_at": datetime.now().isoformat(),
                "file_url": file_url,
                "filename": filename
            })
            
        except Exception as e:
            logger.error(f"上传报表失败: {e}")
            local_path = Path(f"temp_reports/{filename}")
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_stream.seek(0)
            with open(local_path, 'wb') as f:
                f.write(file_stream.read())
            
            report_status[job_id].update({
                "status": "completed",
                "progress": len(job_data['subgraphs']),
                "completed_at": datetime.now().isoformat(),
                "file_url": f"/temp_reports/{filename}",
                "filename": filename
            })
        
    except Exception as e:
        logger.error(f"异步生成报表失败: {e}", exc_info=True)
        report_status[job_id].update({
            "status": "failed",
            "completed_at": datetime.now().isoformat(),
            "error": str(e)
        })


def generate_excel_report(job_data: dict) -> BytesIO:
    """使用 xlsxwriter 生成Excel报表（比 openpyxl 快 20-30%）"""
    logger.info(f"[xlsxwriter] 开始生成")
    
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet('报价单')
    
    # 定义样式（xlsxwriter 的样式是预定义的，性能更好）
    title_format = workbook.add_format({
        'font_name': '宋体',
        'font_size': 14,
        'bold': True,
        'align': 'center',
        'valign': 'vcenter'
    })
    
    header_format = workbook.add_format({
        'font_name': '宋体',
        'font_size': 11,
        'bold': True,
        'align': 'center',
        'valign': 'vcenter',
        'bg_color': '#E0E0E0',
        'border': 1,
        'text_wrap': True
    })

    wrap_format = workbook.add_format({
    'font_name': '宋体',
    'font_size': 10,
    'align': 'left',
    'valign': 'vcenter',
    'border': 1,
    'text_wrap': False  # 改成False
    })
    
    data_format = workbook.add_format({
        'font_name': '宋体',
        'font_size': 10,
        'align': 'center',
        'valign': 'vcenter',
        'border': 1
    })
    
    data_left_format = workbook.add_format({
        'font_name': '宋体',
        'font_size': 10,
        'align': 'left',
        'valign': 'vcenter',
        'border': 1
    })
    
    number_format = workbook.add_format({
        'font_name': '宋体',
        'font_size': 10,
        'align': 'center',
        'valign': 'vcenter',
        'border': 1,
        'num_format': '0.00'
    })

    highlight_wrap_format = workbook.add_format({
        'font_name': 'Microsoft YaHei',
        'font_size': 10,
        'align': 'left',
        'valign': 'vcenter',
        'border': 1,
        'bg_color': '#FFC7CE',
        'font_color': '#9C0006',
        'text_wrap': False
    })

    highlight_data_format = workbook.add_format({
        'font_name': 'Microsoft YaHei',
        'font_size': 10,
        'align': 'center',
        'valign': 'vcenter',
        'border': 1,
        'bg_color': '#FFC7CE',
        'font_color': '#9C0006'
    })

    highlight_data_left_format = workbook.add_format({
        'font_name': 'Microsoft YaHei',
        'font_size': 10,
        'align': 'left',
        'valign': 'vcenter',
        'border': 1,
        'bg_color': '#FFC7CE',
        'font_color': '#9C0006'
    })

    highlight_number_format = workbook.add_format({
        'font_name': 'Microsoft YaHei',
        'font_size': 10,
        'align': 'center',
        'valign': 'vcenter',
        'border': 1,
        'bg_color': '#FFC7CE',
        'font_color': '#9C0006',
        'num_format': '0.00'
    })

    nc_fail_wrap_format = workbook.add_format({
        'font_name': 'Microsoft YaHei',
        'font_size': 10,
        'align': 'left',
        'valign': 'vcenter',
        'border': 1,
        'bg_color': '#FFC7CE',
        'font_color': '#9C0006',
        'text_wrap': False
    })

    nc_fail_data_format = workbook.add_format({
        'font_name': 'Microsoft YaHei',
        'font_size': 10,
        'align': 'center',
        'valign': 'vcenter',
        'border': 1,
        'bg_color': '#FFC7CE',
        'font_color': '#9C0006'
    })

    nc_fail_data_left_format = workbook.add_format({
        'font_name': 'Microsoft YaHei',
        'font_size': 10,
        'align': 'left',
        'valign': 'vcenter',
        'border': 1,
        'bg_color': '#FFC7CE',
        'font_color': '#9C0006'
    })

    nc_fail_number_format = workbook.add_format({
        'font_name': 'Microsoft YaHei',
        'font_size': 10,
        'align': 'center',
        'valign': 'vcenter',
        'border': 1,
        'bg_color': '#FFC7CE',
        'font_color': '#9C0006',
        'num_format': '0.00'
    })
    
    total_format = workbook.add_format({
        'font_name': '宋体',
        'font_size': 11,
        'bold': True,
        'align': 'center',
        'valign': 'vcenter',
        'bg_color': '#FFF2CC',
        'border': 1,
        'num_format': '0.00'
    })
    
    # 设置列宽
    column_widths = [
        5, 8, 10, 8, 6, 7.5, 6, 6, 7, 7, 12, 20, 8, 10, 10, 8, 8, 9, 9, 10, 10, 15,
        12, 12, 8, 12, 10, 12, 12, 12, 12, 12, 12,
        9, 9, 9, 9,
        10, 10, 10, 10, 9, 12,
        9, 9, 9, 9,
        9, 9, 9, 9,
        10, 18, 12
    ]
    
    for col_idx, width in enumerate(column_widths):
        worksheet.set_column(col_idx, col_idx, width)
    
    # 设置行高
    worksheet.set_row(0, 30)
    worksheet.set_row(1, 40)
    # 冻结行列
    worksheet.freeze_panes(2, 12)
    
    # 标题行
    job = job_data['job']
    title_text = f"{_extract_report_mold_code(job.dwg_file_name, job.job_id)}-{datetime.now().strftime('%Y.%m.%d')}模具核算清单"
    worksheet.merge_range('A1:O1', title_text, title_format)
    
    # 表头行
    for col_idx, header in enumerate(HEADERS):
        worksheet.write(1, col_idx, header, header_format)
    
    # 数据行
    subgraphs = _order_subgraphs_for_export(job_data['subgraphs'], job_data['features_dict'])
    features_dict = job_data['features_dict']
    missing_fields_map = _build_missing_fields_map(subgraphs, features_dict)
    nc_failed_part_codes = _build_nc_failed_part_code_set(job)
    
    for idx, subgraph in enumerate(subgraphs, start=1):
        row = idx + 1  # 从第3行开始（0-based: row 2）
        worksheet.set_row(row, 23)
        feature = features_dict.get(subgraph.subgraph_id)
        normalized_part_code = _normalize_code(subgraph.part_code)
        is_nc_failed_row = normalized_part_code in nc_failed_part_codes
        has_wire_time = getattr(subgraph, "wire_time", None) not in (None, 0, 0.0)
        has_wire_process_note = bool((getattr(subgraph, "wire_process_note", None) or "").strip())
        is_wire_process_without_time_row = has_wire_process_note and not has_wire_time
        is_warning_row = (
            subgraph.subgraph_id in missing_fields_map
            and not _has_material_preparation(feature)
        )

        if is_nc_failed_row or is_wire_process_without_time_row:
            current_wrap_format = nc_fail_wrap_format
            current_data_format = nc_fail_data_format
            current_data_left_format = nc_fail_data_left_format
            current_number_format = nc_fail_number_format
        elif is_warning_row:
            current_wrap_format = highlight_wrap_format
            current_data_format = highlight_data_format
            current_data_left_format = highlight_data_left_format
            current_number_format = highlight_number_format
        else:
            current_wrap_format = wrap_format
            current_data_format = data_format
            current_data_left_format = data_left_format
            current_number_format = number_format

        row_data = _build_row_data(idx, subgraph, feature, is_nc_failed_row=is_nc_failed_row)
        
        abnormal_col_idx = HEADERS.index('异常情况')
        for col_idx, value in enumerate(row_data):
            if col_idx == abnormal_col_idx:
                worksheet.write(row, col_idx, value, current_wrap_format)
            elif col_idx in (1, 2):
                worksheet.write(row, col_idx, value, current_data_left_format)
            elif col_idx > 7 and isinstance(value, (int, float)):
                worksheet.write(row, col_idx, value, current_number_format)
            else:
                worksheet.write(row, col_idx, value, current_data_format)
    
    # 合计行
    total_row = len(subgraphs) + 2
    worksheet.write(total_row, 0, '合计', total_format)
    
    for col_idx in range(len(HEADERS)):
        if col_idx == 0:
            continue
        
        if col_idx in SUM_COLUMNS:
            col_letter = xlsxwriter.utility.xl_col_to_name(col_idx)
            formula = f'=SUM({col_letter}3:{col_letter}{total_row})'
            worksheet.write_formula(total_row, col_idx, formula, total_format)
        else: 
            worksheet.write(total_row, col_idx, '', total_format)
    
    workbook.close()
    output.seek(0)
    
    logger.info(f"[xlsxwriter] 完成")
    return output


def _extract_report_mold_code(dwg_file_name: str | None, job_id) -> str:
    """从图纸文件名中提取报表标题使用的模号。"""
    if not dwg_file_name:
        return str(job_id)

    stem = Path(dwg_file_name).stem.strip()
    if not stem:
        return str(job_id)

    stem = re.sub(r'-\d{8}$', '', stem)
    if stem.startswith('MM'):
        stem = stem[1:]

    match = re.match(r'^(M\d+(?:-[A-Za-z0-9]+)*)', stem, re.IGNORECASE)
    if match:
        return match.group(1).upper()

    return stem.upper()

def _extract_abnormal_desc(abnormal_situation, include_nc_failed: bool = False):
    descriptions = []

    try:
        data = abnormal_situation if isinstance(abnormal_situation, dict) else json.loads(abnormal_situation)
        for key in ['dimension_anomalies', 'wire_cut_anomalies']:
            anomalies = data.get(key, [])
            if isinstance(anomalies, list):
                descriptions.extend(
                    item.get('description', '')
                    for item in anomalies
                    if isinstance(item, dict) and item.get('description')
                )
    except:
        descriptions = []

    if include_nc_failed:
        descriptions.append('NC识别失败')

    return '；'.join(descriptions)

def _build_row_data(idx: int, subgraph: Subgraph, feature: Feature, is_nc_failed_row: bool = False) -> list:
    """构建行数据"""
    def safe_float(value, default=0):
        return float(value) if value is not None else default
    
    def safe_int(value, default=0):
        return int(value) if value is not None else default

    quantity = max(safe_int(feature.quantity if feature else None, 1), 1)

    def per_piece(value, default=0):
        if value is None:
            return default
        return float(value) / quantity

    wire_time_value = per_piece(subgraph.wire_time)
    wire_process_note = (subgraph.wire_process_note or '').strip()
    if wire_time_value not in (None, 0, 0.0, '') and not wire_process_note:
        wire_process_note = '快丝割一刀'

    nc_processing_fee_per_piece = (
        per_piece(subgraph.nc_z_fee)
        + per_piece(subgraph.nc_b_fee)
        + per_piece(subgraph.nc_c_fee)
        + per_piece(subgraph.nc_c_b_fee)
        + per_piece(subgraph.nc_z_view_fee)
        + per_piece(subgraph.nc_b_view_fee)
    )

    heat_plus_processing_total = safe_float(subgraph.processing_cost_total) + safe_float(subgraph.heat_treatment_cost)
    roughing_volume_value = (
        safe_float(feature.volume_mm3 if feature else None, '')
        if feature and feature.heat_treatment
        else ''
    )
    nc_face_count = sum(
        1 for value in [
            subgraph.nc_z_time,
            subgraph.nc_b_time,
            subgraph.nc_c_time,
            subgraph.nc_c_b_time,
            subgraph.nc_z_view_time,
            subgraph.nc_b_view_time,
        ]
        if value not in (None, 0, 0.0)
    )
    
    return [
        idx,
        subgraph.part_code or '',
        subgraph.part_name or '',
        feature.material if feature else '',
        _extract_material_preparation(feature),
        quantity,
        safe_float(feature.length_mm if feature else None, ''),
        safe_float(feature.width_mm if feature else None, ''),
        safe_float(feature.thickness_mm if feature else None, ''),
        per_piece(subgraph.weight_kg),
        feature.heat_treatment if feature else '',
        subgraph.process_description or '',  # 工艺描述字段
        safe_float(subgraph.material_unit_price),
        per_piece(subgraph.material_cost),
        roughing_volume_value,
        safe_float(subgraph.nc_roughing_weight),
        safe_float(subgraph.heat_treatment_unit_price),
        per_piece(subgraph.heat_treatment_cost),
        per_piece(subgraph.processing_cost_total),
        heat_plus_processing_total,
        safe_float(subgraph.separate_item_cost),
        per_piece(subgraph.total_cost),
        safe_float(subgraph.total_cost),
        safe_float(subgraph.nc_roughing_time),
        safe_float(subgraph.nc_milling_time),
        safe_float(subgraph.drilling_time),
        nc_face_count,
        per_piece(subgraph.nc_z_time),  # A面时间
        per_piece(subgraph.nc_b_time),  # B面时间
        per_piece(subgraph.nc_c_time),  # C面时间
        per_piece(subgraph.nc_c_b_time),  # D面时间
        per_piece(subgraph.nc_z_view_time),  # E面时间
        per_piece(subgraph.nc_b_view_time),  # F面时间
        nc_processing_fee_per_piece,
        per_piece(subgraph.small_grinding_time),
        per_piece(subgraph.small_grinding_cost),
        per_piece(subgraph.large_grinding_time),
        per_piece(subgraph.large_grinding_cost),
        safe_float(subgraph.slow_wire_length),
        safe_float(subgraph.slow_wire_side_length),
        safe_float(subgraph.mid_wire_length),
        safe_float(subgraph.fast_wire_length),
        wire_time_value,
        wire_process_note,
        per_piece(subgraph.slow_wire_cost),
        per_piece(subgraph.slow_wire_side_cost),
        per_piece(subgraph.mid_wire_cost),
        per_piece(subgraph.fast_wire_cost),
        safe_float(subgraph.edm_time),
        safe_float(subgraph.edm_cost),
        safe_float(subgraph.engraving_time),
        safe_float(subgraph.engraving_cost),
        _extract_abnormal_desc(
            feature.abnormal_situation if feature else None,
            include_nc_failed=is_nc_failed_row
        )
    ]


def _build_missing_fields_map(subgraphs, features_dict):
    features_payload = []
    for subgraph in subgraphs:
        feature = features_dict.get(subgraph.subgraph_id)
        if not feature:
            continue
        features_payload.append(_build_completeness_feature_payload(subgraph, feature))

    completeness_result = CompletenessValidator.check_data_completeness({
        "features": features_payload
    })

    return {
        item.get("record_name"): item
        for item in completeness_result.get("missing_fields", [])
        if item.get("record_name")
    }


def _order_subgraphs_for_export(subgraphs, features_dict):
    indexed_subgraphs = sorted(
        enumerate(subgraphs),
        key=lambda item: _subgraph_export_sort_key(item[0], item[1])
    )
    part_code_to_subgraph_ids = {}
    part_lookup = {}
    original_index_map = {}

    for original_index, subgraph in indexed_subgraphs:
        original_index_map[subgraph.subgraph_id] = original_index
        for key in _subgraph_lookup_keys(subgraph):
            part_lookup.setdefault(key, subgraph.subgraph_id)

        normalized_code = _normalize_code(subgraph.part_code)
        if normalized_code:
            part_code_to_subgraph_ids.setdefault(normalized_code, []).append(subgraph.subgraph_id)

    children_by_parent_id = {}
    child_subgraph_ids = set()
    subgraph_by_id = {subgraph.subgraph_id: subgraph for _, subgraph in indexed_subgraphs}

    for _, subgraph in indexed_subgraphs:
        feature = features_dict.get(subgraph.subgraph_id)
        parent_code = _normalize_code(_extract_material_preparation(feature))
        if not parent_code:
            continue

        parent_ids = part_code_to_subgraph_ids.get(parent_code)
        if not parent_ids:
            continue

        parent_id = min(parent_ids, key=lambda item: original_index_map.get(item, float("inf")))
        if parent_id == subgraph.subgraph_id:
            continue

        children = children_by_parent_id.setdefault(parent_id, [])
        if subgraph.subgraph_id not in children:
            children.append(subgraph.subgraph_id)
        child_subgraph_ids.add(subgraph.subgraph_id)

    for _, subgraph in indexed_subgraphs:
        if subgraph.subgraph_id in child_subgraph_ids:
            continue

        feature = features_dict.get(subgraph.subgraph_id)
        common_targets = _extract_common_output_targets(
            getattr(feature, "processing_instructions", None)
        )
        if not common_targets:
            continue

        for target_code in common_targets:
            target_id = part_lookup.get(_normalize_code(target_code))
            if not target_id or target_id == subgraph.subgraph_id:
                continue

            target_subgraph = subgraph_by_id.get(target_id)
            if not target_subgraph:
                continue

            child_id, parent_id = _select_common_output_child_parent(
                subgraph,
                features_dict.get(subgraph.subgraph_id),
                target_subgraph,
                features_dict.get(target_id),
            )
            if not child_id or not parent_id:
                continue
            if child_id in child_subgraph_ids:
                continue

            children = children_by_parent_id.setdefault(parent_id, [])
            if child_id not in children:
                children.append(child_id)
            child_subgraph_ids.add(child_id)

    for parent_id, child_ids in children_by_parent_id.items():
        child_ids.sort(key=lambda item: original_index_map.get(item, float("inf")))

    ordered_subgraphs = []
    emitted_ids = set()

    def emit_with_children(subgraph_id):
        if subgraph_id in emitted_ids:
            return
        subgraph = subgraph_by_id.get(subgraph_id)
        if not subgraph:
            return

        emitted_ids.add(subgraph_id)
        ordered_subgraphs.append(subgraph)

        for child_id in children_by_parent_id.get(subgraph_id, []):
            emit_with_children(child_id)

    for _, subgraph in indexed_subgraphs:
        if subgraph.subgraph_id in child_subgraph_ids:
            continue
        emit_with_children(subgraph.subgraph_id)

    for _, subgraph in indexed_subgraphs:
        emit_with_children(subgraph.subgraph_id)

    return ordered_subgraphs


def _subgraph_lookup_keys(subgraph: Subgraph) -> set[str]:
    keys = set()
    for value in [
        getattr(subgraph, "subgraph_id", None),
        getattr(subgraph, "part_code", None),
        getattr(subgraph, "part_name", None),
    ]:
        normalized = _normalize_code(value)
        if normalized:
            keys.add(normalized)

    part_name = str(getattr(subgraph, "part_name", None) or "")
    if "." in part_name:
        normalized_stem = _normalize_code(part_name.rsplit(".", 1)[0])
        if normalized_stem:
            keys.add(normalized_stem)
    return keys


def _extract_common_output_targets(processing_instructions) -> list[str]:
    text = _flatten_processing_instructions(processing_instructions)
    if not text:
        return []

    targets = []
    for match in re.finditer(r"与\s*([A-Za-z0-9][A-Za-z0-9_－-]*)\s*共出", text, re.IGNORECASE):
        target = match.group(1).strip().upper().replace("－", "-")
        if target:
            targets.append(target)
    return targets


def _feature_area(feature: Feature | None) -> float:
    if not feature:
        return 0.0
    try:
        length = float(feature.length_mm or 0)
        width = float(feature.width_mm or 0)
    except (TypeError, ValueError):
        return 0.0
    if length <= 0 or width <= 0:
        return 0.0
    return length * width


def _select_common_output_child_parent(
    subgraph_a: Subgraph,
    feature_a: Feature | None,
    subgraph_b: Subgraph,
    feature_b: Feature | None,
) -> tuple[str | None, str | None]:
    area_a = _feature_area(feature_a)
    area_b = _feature_area(feature_b)
    if area_a <= 0 or area_b <= 0:
        return None, None
    if abs(area_a - area_b) < 0.001:
        return None, None
    if area_a < area_b:
        return subgraph_a.subgraph_id, subgraph_b.subgraph_id
    return subgraph_b.subgraph_id, subgraph_a.subgraph_id


def _subgraph_export_sort_key(original_index, subgraph):
    sort_order = getattr(subgraph, "sort_order", None)
    if sort_order is not None:
        sort_text = str(sort_order).strip()
        if sort_text:
            try:
                return (0, int(sort_text), subgraph.subgraph_id or "")
            except (TypeError, ValueError):
                return (1, sort_text, subgraph.subgraph_id or "")

    return (2, original_index, subgraph.subgraph_id or "")


def _extract_material_preparation(feature: Feature) -> str:
    if not feature:
        return ''
    value = getattr(feature, "has_material_preparation", None)
    if value is None:
        return ''
    return str(value).strip()


def _has_material_preparation(feature: Feature) -> bool:
    return bool(_extract_material_preparation(feature))


def _build_nc_failed_part_code_set(job: Job):
    meta_data = job.meta_data if isinstance(job.meta_data, dict) else {}
    raw_codes = meta_data.get("nc_failed_itemcodes")
    if raw_codes is None:
        raw_codes = meta_data.get("fail_itemcode", [])

    if not isinstance(raw_codes, list):
        return set()

    return {
        normalized
        for normalized in (_normalize_code(code) for code in raw_codes)
        if normalized
    }


def _build_completeness_feature_payload(subgraph: Subgraph, feature: Feature) -> dict:
    return {
        "feature_id": feature.feature_id,
        "subgraph_id": feature.subgraph_id,
        "part_code": subgraph.part_code,
        "part_name": subgraph.part_name,
        "length_mm": _to_number_or_none(feature.length_mm),
        "width_mm": _to_number_or_none(feature.width_mm),
        "thickness_mm": _to_number_or_none(feature.thickness_mm),
        "quantity": _to_number_or_none(feature.quantity),
        "material": feature.material,
    }


def _to_number_or_none(value):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _normalize_code(value):
    if value is None:
        return ""
    return str(value).strip().upper()


@router.get("/{job_id}/status")
async def get_report_status(job_id: str):
    """获取异步报表生成状态"""
    if job_id not in report_status:
        raise HTTPException(status_code=404, detail="未找到报表生成任务")
    
    return {
        "job_id": job_id,
        **report_status[job_id]
    }
