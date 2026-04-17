"""
报表导出API路由 - xlsxwriter 版本
性能比 openpyxl 快 20-30%
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

# 表头定义
HEADERS = [
    '序号', '零件名称', '编号', '数量', '长/mm', '宽/mm', '厚/mm', '重量/kg',
    '材质', '材料单价', '材料费（元）', '热处理', '热处理单价', '热处理费（元）',
    '工艺', '单件费用总计（元）', '费用总计（元）', 'NC主视图(h)', 'NC背面(h)', 'NC侧面正面(h)', 'NC侧背(h)',
    'NC正面(h)', 'NC正面的背面(h)', 'NC主视图（元）', 'NC背面（元）', 'NC侧面正面（元）', 'NC侧背（元）',
    'NC正面（元）', 'NC正面的背面（元）', '大水磨 M(h)', '小磨床 YM(个)', '大磨床（元）', '小磨床（元）',
    '慢丝 W/E(mm)', '侧割长度(mm)', '中丝 W/Z(mm)', '快丝 W/C(mm)', '线割工艺说明',
    '放电 EDM(h)', '雕刻 DK(h)', '线割时间', '慢丝（元）', '侧割（元）', '中丝（元）', '快丝（元）',
    '放电（元）', '雕刻（元）', '开粗实际时间', '精铣实际时间', '钻床实际时间',
    '单独计费（元）', '单件加工费合计（元）', '加工费合计（元）', '体积/mm³', '异常情况'  # 最后两项
]

# 需要合计的列索引（基于0的索引）
HEADERS = [*HEADERS, '其它（备料于）']

SUM_COLUMNS = [
    3,   # 数量
    10,  # 材料费（元）
    13,  # 热处理费（元）
    15, 16, 17, 18, 19, 20, 21, 22,  # 单件费用总计 + 费用总计 + NC工时列
    23, 24, 25, 26, 27, 28,          # NC费用列
    29, 30, 31, 32,                  # 水磨时间/数量/费用
    38, 39, 40,                      # 放电/雕刻/线割时间
    41, 42, 43, 44, 45, 46,          # 线割/放电/雕刻费用
    47, 48, 49,                      # 开粗/精铣/钻床实际时间
    50, 51, 52                       # 单独计费/单件加工费合计/加工费合计
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
    
    logger.info(f"[数据查询] 完成: {len(job.subgraphs)} 个子图")
    
    return {
        'job': job,
        'subgraphs': list(job.subgraphs),
        'features_dict': features_dict
    }


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
    column_widths = [6, 12, 10, 10, 8, 8, 8, 6, 10, 12, 10, 12, 10, 12, 8, 12,
                     12, 10, 10, 12, 12, 12, 18, 12, 12, 12, 12, 10, 14, 20,
                     12, 12, 10, 10, 12, 12, 10, 12, 10, 10, 10, 10, 12, 14,
                     14, 12, 12, 20, 20, 8, 20]
    
    for col_idx, width in enumerate(column_widths):
        worksheet.set_column(col_idx, col_idx, width)
    
    # 设置行高
    worksheet.set_row(0, 30)
    worksheet.set_row(1, 40)
    
    # 标题行
    job = job_data['job']
    title_text = f"M{job.dwg_file_name or job.job_id} P4 {datetime.now().strftime('%Y.%m.%d')}模具核算清单"
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
        feature = features_dict.get(subgraph.subgraph_id)
        normalized_part_code = _normalize_code(subgraph.part_code)
        is_nc_failed_row = normalized_part_code in nc_failed_part_codes
        is_warning_row = (
            subgraph.subgraph_id in missing_fields_map
            and not _has_material_preparation(feature)
        )

        if is_nc_failed_row:
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
        
        for col_idx, value in enumerate(row_data):
            if col_idx == len(row_data) - 1:  # 异常情况列
                worksheet.write(row, col_idx, value, current_wrap_format)
            elif col_idx == 1:
                worksheet.write(row, col_idx, value, current_data_left_format)
            elif col_idx > 7 and isinstance(value, (int, float)):
                worksheet.write(row, col_idx, value, current_number_format)
            else:
                worksheet.write(row, col_idx, value, current_data_format)
        # 加在这里↓
        worksheet.write(row, len(row_data), _extract_material_preparation(feature), current_wrap_format)
    
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
    
    return [
        idx,
        subgraph.part_name or '',
        subgraph.part_code or '',
        quantity,
        safe_float(feature.length_mm if feature else None, ''),
        safe_float(feature.width_mm if feature else None, ''),
        safe_float(feature.thickness_mm if feature else None, ''),
        per_piece(subgraph.weight_kg),
        feature.material if feature else '',
        safe_float(subgraph.material_unit_price),
        per_piece(subgraph.material_cost),
        feature.heat_treatment if feature else '',
        safe_float(subgraph.heat_treatment_unit_price),
        per_piece(subgraph.heat_treatment_cost),
        subgraph.process_description or '',  # 工艺描述字段
        per_piece(subgraph.total_cost),
        safe_float(subgraph.total_cost),
        per_piece(subgraph.nc_z_time),  # NC主视图时间
        per_piece(subgraph.nc_b_time),  # NC背面时间
        per_piece(subgraph.nc_c_time),  # NC侧面正面时间
        per_piece(subgraph.nc_c_b_time),  # NC侧背时间
        per_piece(subgraph.nc_z_view_time),  # NC正面时间
        per_piece(subgraph.nc_b_view_time),  # NC正面的背面时间
        per_piece(subgraph.nc_z_fee),  # NC主视图费用
        per_piece(subgraph.nc_b_fee),  # NC背面费用
        per_piece(subgraph.nc_c_fee),  # NC侧面正面费用
        per_piece(subgraph.nc_c_b_fee),  # NC侧背费用
        per_piece(subgraph.nc_z_view_fee),  # NC正面费用
        per_piece(subgraph.nc_b_view_fee),  # NC正面的背面费用
        per_piece(subgraph.large_grinding_time),
        safe_int(subgraph.small_grinding_count),
        per_piece(subgraph.large_grinding_cost),
        per_piece(subgraph.small_grinding_cost),
        safe_float(subgraph.slow_wire_length),
        safe_float(subgraph.slow_wire_side_length),
        safe_float(subgraph.mid_wire_length),
        safe_float(subgraph.fast_wire_length),
        subgraph.wire_process_note or '',
        safe_float(subgraph.edm_time),
        safe_float(subgraph.engraving_time),
        per_piece(subgraph.wire_time),
        per_piece(subgraph.slow_wire_cost),
        per_piece(subgraph.slow_wire_side_cost),
        per_piece(subgraph.mid_wire_cost),
        per_piece(subgraph.fast_wire_cost),
        safe_float(subgraph.edm_cost),
        safe_float(subgraph.engraving_cost),
        safe_float(subgraph.nc_roughing_time),
        safe_float(subgraph.nc_milling_time),
        safe_float(subgraph.drilling_time),
        safe_float(subgraph.separate_item_cost),
        per_piece(subgraph.processing_cost_total),
        safe_float(subgraph.processing_cost_total),
        safe_float(feature.volume_mm3 if feature else None),      # 新增
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
    indexed_subgraphs = list(enumerate(subgraphs))
    part_code_to_subgraph_ids = {}
    original_index_map = {}

    for original_index, subgraph in indexed_subgraphs:
        original_index_map[subgraph.subgraph_id] = original_index
        normalized_code = _normalize_code(subgraph.part_code)
        if not normalized_code:
            continue
        part_code_to_subgraph_ids.setdefault(normalized_code, []).append(subgraph.subgraph_id)

    children_by_parent_id = {}
    child_subgraph_ids = set()

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
        children.append(subgraph.subgraph_id)
        child_subgraph_ids.add(subgraph.subgraph_id)

    for parent_id, child_ids in children_by_parent_id.items():
        child_ids.sort(key=lambda item: original_index_map.get(item, float("inf")))

    subgraph_by_id = {subgraph.subgraph_id: subgraph for _, subgraph in indexed_subgraphs}
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
