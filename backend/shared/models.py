"""
数据库模型
负责人:人员A
"""
from sqlalchemy import Column, String, Integer, DECIMAL, TIMESTAMP, Boolean, Text, ARRAY, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from .database import Base

# 导入时区工具
try:
    from shared.timezone_utils import now_shanghai
except ImportError:
    # 如果导入失败，使用本地定义
    from datetime import datetime
    from zoneinfo import ZoneInfo
    def now_shanghai():
        return datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)

class Job(Base):
    """任务?"""""
    __tablename__ = "jobs"
    
    job_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    
    # DWG文件信息
    dwg_file_id = Column(String(100))
    dwg_file_name = Column(String(255))
    dwg_file_path = Column(String(500))
    dwg_file_size = Column(Integer)
    
    # PRT文件信息
    prt_file_id = Column(String(100))
    prt_file_name = Column(String(255))
    prt_file_path = Column(String(500))
    prt_file_size = Column(Integer)
    
    # 任务状?
    status = Column(String(20), nullable=False, default="pending")
    current_stage = Column(String(50))
    progress = Column(Integer, default=0)
    total_subgraphs = Column(Integer, default=0)
    
    # 成本汇?
    total_cost = Column(DECIMAL(12, 2))
    currency = Column(String(10), default="CNY")
    processes_used = Column(ARRAY(Text))
    
    # 各工艺成?
    material_cost = Column(DECIMAL(12, 2))
    heat_treatment_cost = Column(DECIMAL(12, 2))
    fast_wire_cost = Column(DECIMAL(12, 2))
    mid_wire_cost = Column(DECIMAL(12, 2))
    slow_wire_cost = Column(DECIMAL(12, 2))
    nc_cost = Column(DECIMAL(12, 2))
    grinding_cost = Column(DECIMAL(12, 2))
    edm_cost = Column(DECIMAL(12, 2))
    processing_cost_total = Column(DECIMAL(12, 2))
    
    # 版本锁定(快照模式)
    price_version_locked = Column(String(20))
    process_version_locked = Column(String(20))
    snapshot_created_at = Column(TIMESTAMP)
    
    # 报表
    report_id = Column(String(100))
    
    # 时间字段（Asia/Shanghai 时区）
    created_at = Column(TIMESTAMP, nullable=False, default=now_shanghai)
    updated_at = Column(TIMESTAMP, nullable=False, default=now_shanghai, onupdate=now_shanghai)
    completed_at = Column(TIMESTAMP)
    archived_at = Column(TIMESTAMP)
    
    # 其他
    error_message = Column(Text)
    meta_data = Column("metadata", JSONB)

    subgraphs = relationship("Subgraph", back_populates="job", lazy="select")

class Subgraph(Base):
    """子图?- 存储业务数据和成本数?"""""
    __tablename__ = "subgraphs"
    
    subgraph_id = Column(String(50), primary_key=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.job_id"), nullable=False)
    
    # 基本信息
    part_name = Column(String(100))
    part_code = Column(String(100))
    # material = Column(String(50))  # SQL 设计中有此字段，但实际数据库表中不存在
    subgraph_file_url = Column(String(500))
    
    # 业务数据
    weight_kg = Column(DECIMAL(10, 3))
    
    # 材料和热处理
    material_unit_price = Column(DECIMAL(10, 2))
    material_cost = Column(DECIMAL(12, 2))
    heat_treatment_unit_price = Column(DECIMAL(10, 2))
    heat_treatment_cost = Column(DECIMAL(12, 2))
    
    # 工艺说明
    process_description = Column(String(200))
    
    # 加工时间
    nc_z_time = Column(DECIMAL(10, 2))
    nc_b_time = Column(DECIMAL(10, 2))
    nc_c_time = Column(DECIMAL(10, 2))
    nc_c_b_time = Column(DECIMAL(10, 2))
    large_grinding_time = Column(DECIMAL(10, 2))
    small_grinding_time = Column(DECIMAL(10, 2))
    edm_time = Column(DECIMAL(10, 2))
    engraving_time = Column(DECIMAL(10, 2))
    
    # 线割长度
    slow_wire_length = Column(DECIMAL(12, 3))
    slow_wire_side_length = Column(DECIMAL(12, 3))
    mid_wire_length = Column(DECIMAL(12, 3))
    fast_wire_length = Column(DECIMAL(12, 3))
    
    # 单独?
    separate_item = Column(String(200))
    
    # 费用
    total_cost = Column(DECIMAL(12, 2))
    wire_process = Column(String(255))  # 🆕 工艺代码（如 fast_and_one, slow_and_one）
    wire_process_note = Column(Text)
    nc_z_fee = Column(DECIMAL(12, 2))
    nc_b_fee = Column(DECIMAL(12, 2))
    nc_c_fee = Column(DECIMAL(12, 2))
    nc_c_b_fee = Column(DECIMAL(12, 2))
    large_grinding_cost = Column(DECIMAL(12, 2))
    small_grinding_cost = Column(DECIMAL(12, 2))
    slow_wire_cost = Column(DECIMAL(12, 2))
    slow_wire_side_cost = Column(DECIMAL(12, 2))
    mid_wire_cost = Column(DECIMAL(12, 2))
    fast_wire_cost = Column(DECIMAL(12, 2))
    edm_cost = Column(DECIMAL(12, 2))
    engraving_cost = Column(DECIMAL(12, 2))
    separate_item_cost = Column(DECIMAL(12, 2))
    processing_cost_total = Column(DECIMAL(12, 2))
    small_grinding_count = Column(Integer)
    
    # 工艺决策
    applied_snapshot_ids = Column(ARRAY(Text))
    rule_reason = Column(Text)
    override_by_user = Column(Boolean, default=False)
    cost_calculation_method = Column(String(20))
    
    # 扩展功能
    has_sheet_line = Column(Boolean, default=False)
    sheet_area_mm2 = Column(DECIMAL(12, 3))
    sheet_perimeter_mm = Column(DECIMAL(12, 3))
    sheet_line_data = Column(JSONB)
    has_single_nc_calc = Column(Boolean, default=False)
    single_prt_file = Column(String(500))
    process_changed = Column(Boolean, default=False)
    original_process = Column(String(20))
    prt_3d_file = Column(String(500))
    
    # 重算
    recalc_count = Column(Integer, default=0)
    last_recalc_at = Column(TIMESTAMP)
    last_recalc_by = Column(String(50))
    
    # 状态
    status = Column(String(20), default='pending')
    created_at = Column(TIMESTAMP, nullable=False, default=now_shanghai)
    updated_at = Column(TIMESTAMP, nullable=False, default=now_shanghai, onupdate=now_shanghai)
    meta_data = Column("metadata", JSONB)
    
    # 🆕 NC视图时间和费用
    nc_z_view_time = Column(DECIMAL(10, 2))
    nc_b_view_time = Column(DECIMAL(10, 2))
    nc_z_view_fee = Column(DECIMAL(10, 2))
    nc_b_view_fee = Column(DECIMAL(10, 2))

    job = relationship("Job", back_populates="subgraphs")

class Feature(Base):
    """特征表- 存储从CAD提取的原始特征数据,支持历史版本"""
    __tablename__ = "features"
    
    feature_id = Column(Integer, primary_key=True, autoincrement=True)
    subgraph_id = Column(String(50), ForeignKey("subgraphs.subgraph_id"), nullable=False)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.job_id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    
    # 几何特征(从CAD提取?
    length_mm = Column(DECIMAL(10, 2))
    width_mm = Column(DECIMAL(10, 2))
    thickness_mm = Column(DECIMAL(10, 3))
    quantity = Column(Integer, default=1)
    material = Column(String(50))  # 添加缺失的 material 字段
    heat_treatment = Column(String(100))
    # volume_mm3 = Column(DECIMAL(15, 3))  # 数据库表中不存在，注释掉
    calculated_weight_kg = Column(DECIMAL(10, 3))
    
    # 三个视图的线割长?
    top_view_wire_length = Column(DECIMAL(10, 3))
    front_view_wire_length = Column(DECIMAL(10, 3))
    side_view_wire_length = Column(DECIMAL(10, 3))
    
    # 加工特征
    has_auto_material = Column(Boolean, default=False)
    needs_heat_treatment = Column(Boolean, default=False)
    boring_length_mm = Column(DECIMAL(10, 3))
    
    # 加工说明(JSON格式,包含所有提取到的加工说明)
    processing_instructions = Column(JSONB)
    
    # 识别信息
    is_complete = Column(Boolean, default=False)
    missing_params = Column(ARRAY(String))
    
    # 异常情况
    abnormal_situation = Column(JSONB)
    
    # 元数据
    created_by = Column(String(50))
    created_at = Column(TIMESTAMP, nullable=False, default=now_shanghai)
    meta_data = Column("metadata", JSONB)

    @property
    def volume_mm3(self):
        if isinstance(self.meta_data, dict):
            value = self.meta_data.get("volume_mm3")
            if value is not None:
                return value
        return None

class PriceItem(Base):
    """价格项表(全局模板)"""
    __tablename__ = "price_items"
    
    id = Column(String(50), primary_key=True)
    version_id = Column(String(50))
    category = Column(String(100))
    sub_category = Column(String(200))
    price = Column(String(50))
    unit = Column(String(50))
    work_hours = Column(String(50))
    min_num = Column(String(50))
    add_price = Column(String(50))
    weight_num = Column(String(50))
    note = Column(String(500))
    instruction = Column(String(500))
    is_active = Column(Boolean, default=True)
    created_by = Column(String(100))
    created_at = Column(TIMESTAMP, nullable=False, default=now_shanghai)
    updated_at = Column(TIMESTAMP, nullable=False, default=now_shanghai, onupdate=now_shanghai)

class ProcessRule(Base):
    """工艺规则表(全局模板)"""
    __tablename__ = "process_rules"
    
    id = Column(String(50), primary_key=True)
    version_id = Column(String(20), nullable=False)
    feature_type = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    conditions = Column(String(255), nullable=False)  # ⚠️ 数据库中是 VARCHAR，不是 JSONB
    output_params = Column(String(255), nullable=False)  # ⚠️ 数据库中是 VARCHAR，不是 JSONB
    priority = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, nullable=False, default=now_shanghai)
    # ⚠️ 数据库中没有以下字段：created_by, updated_at, metadata

class JobPriceSnapshot(Base):
    """任务价格快照表"""
    __tablename__ = "job_price_snapshots"
    
    snapshot_id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.job_id"), nullable=False)
    
    # 从price_items复制的字段（VARCHAR类型）
    original_price_id = Column(String(50))
    version_id = Column(String(50))
    category = Column(String(100))
    sub_category = Column(String(200))
    price = Column(String(50))
    unit = Column(String(50))
    work_hours = Column(String(50))
    min_num = Column(String(50))
    add_price = Column(String(50))
    weight_num = Column(String(50))
    note = Column(String(500))
    instruction = Column(String(500))
    
    # 快照特有字段
    is_modified = Column(Boolean, default=False)
    modified_by = Column(String(50))
    modified_at = Column(TIMESTAMP)
    modification_reason = Column(Text)
    
    # 审计字段
    snapshot_created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    meta_data = Column("metadata", JSONB)

class JobProcessSnapshot(Base):
    """任务工艺快照表"""
    __tablename__ = "job_process_snapshots"
    
    snapshot_id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.job_id"), nullable=False)
    
    # 从process_rules复制的字段
    original_rule_id = Column(String(50))
    version_id = Column(String(20), nullable=False)
    feature_type = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    priority = Column(Integer, default=0)
    conditions = Column(String(255), nullable=False)  # 字符串格式，不是JSONB
    output_params = Column(String(255), nullable=False)  # 字符串格式，不是JSONB
    
    # 快照特有字段
    is_modified = Column(Boolean, default=False)
    modified_by = Column(String(50))
    modified_at = Column(TIMESTAMP)
    modification_reason = Column(Text)
    
    # 审计字段
    snapshot_created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    meta_data = Column("metadata", JSONB)

class User(Base):
    """用户?"""""
    __tablename__ = "users"
    
    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(100))
    role = Column(String(20), nullable=False, default="Operator")  # Admin/Operator/Viewer
    department = Column(String(100))
    is_active = Column(Boolean, default=True)
    last_login_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    meta_data = Column("metadata", JSONB)

class UserInteraction(Base):
    """用户交互?"""""
    __tablename__ = "user_interactions"
    
    interaction_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.job_id"), nullable=False)
    card_id = Column(String(100), nullable=False)
    card_type = Column(String(50), nullable=False)  # missing_input/choice/review
    card_data = Column(JSONB, nullable=False)
    user_response = Column(JSONB)
    action = Column(String(50))  # submit/re_recognize/skip
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    responded_at = Column(TIMESTAMP)
    status = Column(String(20), default='pending')  # pending/responded/expired

class OperationLog(Base):
    """操作日志?"""""
    __tablename__ = "operation_logs"
    
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.job_id"))
    subgraph_id = Column(String(50))
    agent = Column(String(50), nullable=False)
    action = Column(String(100), nullable=False)
    input_data = Column(JSONB)
    output_data = Column(JSONB)
    status = Column(String(20), nullable=False)  # success/failed/warning
    duration_ms = Column(Integer)
    error_message = Column(Text)
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)

class AuditLog(Base):
    """审计日志?"""""
    __tablename__ = "audit_logs"
    
    audit_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)  # job/subgraph/price/rule
    resource_id = Column(String(100), nullable=False)
    changes = Column(JSONB)  # {before: {...}, after: {...}}
    ip_address = Column(String(50))
    user_agent = Column(String(255))
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)

class Report(Base):
    """报表?"""""
    __tablename__ = "reports"
    
    report_id = Column(String(100), primary_key=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.job_id"), nullable=False)
    file_type = Column(String(10), nullable=False)  # xlsx/pdf
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)
    download_url = Column(String(1000))
    url_expires_at = Column(TIMESTAMP)
    checksum = Column(String(64))
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)

class ReportSummary(Base):
    """报表汇总表"""
    __tablename__ = "report_summary"
    
    summary_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(String(100), ForeignKey("reports.report_id"), nullable=False)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.job_id"), nullable=False)
    
    # 材料和热处理合计
    total_material_cost = Column(DECIMAL(12, 2))
    total_heat_treatment_cost = Column(DECIMAL(12, 2))
    
    # 加工费合计
    total_nc_z_fee = Column(DECIMAL(12, 2))
    total_nc_b_fee = Column(DECIMAL(12, 2))
    total_nc_c_fee = Column(DECIMAL(12, 2))
    total_nc_c_b_fee = Column(DECIMAL(12, 2))
    total_large_grinding_cost = Column(DECIMAL(12, 2))
    total_small_grinding_cost = Column(DECIMAL(12, 2))
    total_slow_wire_cost = Column(DECIMAL(12, 2))
    total_slow_wire_side_cost = Column(DECIMAL(12, 2))
    total_mid_wire_cost = Column(DECIMAL(12, 2))
    total_fast_wire_cost = Column(DECIMAL(12, 2))
    total_edm_cost = Column(DECIMAL(12, 2))
    total_engraving_cost = Column(DECIMAL(12, 2))
    total_separate_item_cost = Column(DECIMAL(12, 2))
    total_processing_cost = Column(DECIMAL(12, 2))
    
    # 总计
    grand_total = Column(DECIMAL(12, 2))
    management_fee = Column(DECIMAL(12, 2))
    final_total = Column(DECIMAL(12, 2))
    
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)

class Archive(Base):
    """归档?"""""
    __tablename__ = "archives"
    
    archive_id = Column(String(100), primary_key=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.job_id"), nullable=False)
    archive_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)
    checksum = Column(String(64), nullable=False)
    archived_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    expires_at = Column(TIMESTAMP)  # 7年后

class Recalculation(Base):
    """重算记录?"""""
    __tablename__ = "recalculations"
    
    recalc_id = Column(String(100), primary_key=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.job_id"), nullable=False)
    subgraph_id = Column(String(50), nullable=False)
    batch_recalc_id = Column(String(100))
    reason = Column(Text, nullable=False)
    modifications = Column(JSONB)
    old_cost = Column(DECIMAL(12, 2))
    new_cost = Column(DECIMAL(12, 2))
    cost_diff = Column(DECIMAL(12, 2))
    status = Column(String(20), default='pending')  # pending/processing/completed/failed
    created_by = Column(String(50), nullable=False)
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    completed_at = Column(TIMESTAMP)

class BatchRecalculation(Base):
    """批量重算?"""""
    __tablename__ = "batch_recalculations"
    
    batch_recalc_id = Column(String(100), primary_key=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.job_id"), nullable=False)
    subgraph_ids = Column(ARRAY(Text), nullable=False)
    reason = Column(Text, nullable=False)
    total_count = Column(Integer, nullable=False)
    completed_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    old_total_cost = Column(DECIMAL(12, 2))
    new_total_cost = Column(DECIMAL(12, 2))
    cost_diff = Column(DECIMAL(12, 2))
    status = Column(String(20), default='pending')
    created_by = Column(String(50), nullable=False)
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    completed_at = Column(TIMESTAMP)

class NCCalculation(Base):
    """NC计算记录?"""""
    __tablename__ = "nc_calculations"
    
    calc_id = Column(String(100), primary_key=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.job_id"), nullable=False)
    subgraph_id = Column(String(50))
    calc_type = Column(String(20), nullable=False)  # complete/single
    prt_file = Column(String(500), nullable=False)
    drilling_time = Column(DECIMAL(10, 2))
    roughing_time = Column(DECIMAL(10, 2))
    milling_time = Column(DECIMAL(10, 2))
    total_cost = Column(DECIMAL(12, 2))
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)

class ProcessingCostCalculationDetail(Base):
    """加工成本计算详情表 - 存储每个子图的详细计算步骤"""
    __tablename__ = "processing_cost_calculation_details"
    
    detail_id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.job_id"), nullable=False)
    subgraph_id = Column(String(50), ForeignKey("subgraphs.subgraph_id"), nullable=False)
    
    # 工艺类型
    process_type = Column(String(50))  # slow_wire, mid_wire, fast_wire, large_grinding, small_grinding, nc_roughing, nc_milling, drilling
    
    # 计算参数
    adjusted_thickness = Column(DECIMAL(12, 3))
    weight = Column(DECIMAL(12, 3))
    multiplier_coefficient = Column(DECIMAL(12, 3))
    standard_hours = Column(DECIMAL(12, 3))
    actual_hours = Column(DECIMAL(12, 3))
    
    # 成本明细
    basic_processing_cost = Column(DECIMAL(12, 2))
    special_base_cost = Column(DECIMAL(12, 2))
    standard_base_cost = Column(DECIMAL(12, 2))
    selected_base_cost = Column(DECIMAL(12, 2))
    base_cost_selection = Column(String(100))
    
    # 额外成本
    material_additional_cost = Column(DECIMAL(12, 2), default=0)
    material_cost = Column(DECIMAL(12, 2), default=0)
    heat_treatment_cost = Column(DECIMAL(12, 2), default=0)
    heat_additional_cost = Column(DECIMAL(12, 2))
    additional_cost_total = Column(DECIMAL(12, 2), default=0)
    
    # 最终成本
    final_cost = Column(DECIMAL(12, 2))
    
    # 🔑 计算步骤详情 (JSON 格式)
    calculation_steps = Column(JSONB)
    
    # 🆕 按重量计算步骤详情 (JSON 格式)
    weight_price_steps = Column(JSONB)
    
    # 时间戳
    calculated_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)

class LoginLog(Base):
    """登录日志?"""""
    __tablename__ = "login_logs"
    
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    username = Column(String(50), nullable=False)
    login_time = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    ip_address = Column(String(50))
    user_agent = Column(String(255))
    login_status = Column(String(20), nullable=False)  # success/failed
    failure_reason = Column(String(255))
    meta_data = Column("metadata", JSONB)
