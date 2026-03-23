# -*- coding: utf-8 -*-
"""
CAD 服务统一接口
整合拆图服务和特征识别服务的接口定义
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 导入处理函数
try:
    from cad_chaitu import chaitu_process
    CHAITU_AVAILABLE = True
    logger.info("✅ 拆图服务模块加载成功")
except Exception as e:
    CHAITU_AVAILABLE = False
    logger.error(f"❌ 拆图服务模块加载失败: {e}")

try:
    from feature_recognition import batch_feature_recognition_process
    FEATURE_AVAILABLE = True
    logger.info("✅ 特征识别服务模块加载成功")
except Exception as e:
    FEATURE_AVAILABLE = False
    logger.error(f"❌ 特征识别服务模块加载失败: {e}")

# 创建 FastAPI 应用
app = FastAPI(
    title="CAD 服务统一接口",
    description="整合拆图服务和特征识别服务",
    version="2.0.0"
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 数据模型定义 ====================

class ChaiTuRequest(BaseModel):
    """拆图请求模型"""
    dwg_url: Optional[str] = None
    prt_url: Optional[str] = None  # PRT 文件路径（可选，有则导出 .x_t 上传 MinIO）
    job_id: str

class ChaiTuResponse(BaseModel):
    """拆图响应模型"""
    status: str  # "ok" | "error"
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

class FeatureRecognitionRequest(BaseModel):
    """特征识别请求模型"""
    job_id: str
    subgraph_id: Optional[str] = None

class FeatureRecognitionResponse(BaseModel):
    """特征识别响应模型"""
    success: bool
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

class UploadFeatureDbRequest(BaseModel):
    """上传滑块特征库请求模型"""
    csv_folder: str  # 拆分文件夹路径，含 特征面识别报告_增强版.csv
    minio_path: Optional[str] = None  # MinIO 目标路径，默认 slider/feature_database.json

# ==================== 拆图服务接口 ====================

@app.post("/api/chaitu", response_model=ChaiTuResponse, tags=["拆图服务"])
async def chaitu_api(request: ChaiTuRequest):
    """
    拆图接口
    
    传入 job_id，自动从数据库查询 dwg_file_path，从 MinIO 获取文件，
    识别所有子图并拆分成单独的 DXF 文件
    
    Args:
        request.dwg_url: DWG 文件的 URL 或本地路径（可选）
        request.job_id: 任务ID
    
    Returns:
        拆图结果
    """
    if not CHAITU_AVAILABLE:
        raise HTTPException(status_code=503, detail="拆图服务不可用")
    
    try:
        result = await chaitu_process(request.dwg_url, request.job_id, prt_url=request.prt_url)
        
        # 根据返回的 status 判断是否成功
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("message", "拆图失败"))
        
        return ChaiTuResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"拆图服务异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/chaitu/health", tags=["拆图服务"])
async def chaitu_health():
    """拆图服务健康检查"""
    return {
        "service": "拆图服务",
        "status": "healthy" if CHAITU_AVAILABLE else "unavailable",
        "available": CHAITU_AVAILABLE
    }

# ==================== 特征识别服务接口 ====================

@app.post("/api/feature-recognition/batch", response_model=FeatureRecognitionResponse, tags=["特征识别服务"])
async def feature_recognition_batch_api(request: FeatureRecognitionRequest):
    """
    批量特征识别接口
    
    从数据库查询子图信息，从 MinIO 读取 DXF 文件并批量识别特征
    
    Args:
        request.job_id: 任务ID
        request.subgraph_id: 子图ID（可选，如果不提供则处理所有子图）
    
    Returns:
        批量识别结果
    """
    if not FEATURE_AVAILABLE:
        raise HTTPException(status_code=503, detail="特征识别服务不可用")
    
    try:
        result = batch_feature_recognition_process(request.job_id, request.subgraph_id)
        
        # 根据结果返回适当的状态码
        if not result['success']:
            if '未找到子图' in result.get('message', ''):
                raise HTTPException(status_code=404, detail=result['message'])
            else:
                raise HTTPException(status_code=500, detail=result['message'])
        
        return FeatureRecognitionResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"特征识别服务异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/feature-recognition/health", tags=["特征识别服务"])
async def feature_recognition_health():
    """特征识别服务健康检查"""
    return {
        "service": "特征识别服务",
        "status": "healthy" if FEATURE_AVAILABLE else "unavailable",
        "available": FEATURE_AVAILABLE
    }

@app.post("/api/feature-recognition/upload-feature-db", tags=["特征识别服务"])
async def upload_feature_db_api(request: UploadFeatureDbRequest):
    """
    上传滑块特征库到 MinIO

    前置条件：已在 NX 环境中跑过 recognize_by_features_enhanced.py，
    生成了 特征面识别报告_增强版.csv。

    本接口完成后两步：
      1. 读取 CSV → 生成 feature_database.json
      2. 上传 feature_database.json 到 MinIO

    Args:
        csv_folder:  包含 特征面识别报告_增强版.csv 的拆分文件夹路径
        minio_path:  MinIO 目标路径（可选，默认 slider/feature_database.json）
    """
    import glob, csv as _csv, json as _json, tempfile

    folder = os.path.abspath(request.csv_folder)
    if not os.path.isdir(folder):
        raise HTTPException(status_code=400, detail=f"文件夹不存在: {folder}")

    # 找最新的 CSV
    pattern = os.path.join(folder, "特征面识别报告_增强版*.csv")
    csv_files = sorted(glob.glob(pattern), key=os.path.getmtime)
    if not csv_files:
        raise HTTPException(status_code=404, detail=f"未找到识别报告 CSV: {folder}")
    csv_path = csv_files[-1]
    logger.info(f"读取 CSV: {csv_path}")

    # CSV → dict
    database = {}
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = _csv.DictReader(f)
        for row in reader:
            part_name = row.get('零件名', '').strip()
            if not part_name:
                continue
            if any('\u4e00' <= c <= '\u9fff' for c in part_name):
                continue
            red_count_str = row.get('红色面数量', '0').strip()
            # 只读取红色面总面积（兼容 mm2 / mm²）
            area_str = row.get('红色面总面积(mm2)', row.get('红色面总面积(mm²)', '0')).strip()
            red_count = int(red_count_str) if red_count_str.isdigit() else 0
            if red_count == 0:
                continue
            try:
                total_area = float(area_str)
            except ValueError:
                total_area = 0.0
            slider_result = row.get('识别结果', '').strip()
            code = '滑块' if slider_result not in ('', '未识别') else 'none'
            database[part_name] = {
                "wire_cut_details": [{
                    "code": code, "cone": "f", "view": "front_view",
                    "area_num": red_count,
                    "instruction": f"{red_count} -红色面",
                    "slider_angle": 0,
                    "total_length": round(total_area, 3),
                    "is_additional": False,
                    "matched_count": red_count,
                    "single_length": round(total_area / red_count, 3) if red_count else 0.0,
                    "expected_count": red_count,
                    "matched_line_ids": [],
                    "overlapping_length": 0.0,
                }]
            }

    if not database:
        raise HTTPException(status_code=400, detail="CSV 中没有有效的红色面数据")

    # 写临时 JSON
    tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w', encoding='utf-8')
    _json.dump(database, tmp, ensure_ascii=False, indent=2)
    tmp.close()

    # 上传 MinIO
    from minio_client import minio_client as _mc
    from feature_recognition.slider_red_face_lookup import invalidate_cache
    minio_path = request.minio_path or os.getenv('SLIDER_FEATURE_DB_MINIO_PATH', 'slider/feature_database.json')
    ok = _mc.upload_file(tmp.name, minio_path)
    os.unlink(tmp.name)

    if not ok:
        raise HTTPException(status_code=500, detail="上传 MinIO 失败")

    # 清除内存缓存，下次查表时重新拉取
    invalidate_cache(minio_path)

    logger.info(f"✅ 特征库上传成功: {minio_path}，共 {len(database)} 条")
    return {
        "success": True,
        "message": f"上传成功，共 {len(database)} 条记录",
        "minio_path": minio_path,
        "csv_source": csv_path,
    }

# ==================== 通用接口 ====================

@app.get("/", tags=["通用"])
async def root():
    """根路径 - 服务信息"""
    return {
        "service": "CAD 服务统一接口",
        "version": "2.0.0",
        "services": {
            "chaitu": {
                "available": CHAITU_AVAILABLE,
                "endpoints": [
                    "POST /api/chaitu - 拆图服务",
                    "GET /api/chaitu/health - 拆图服务健康检查"
                ]
            },
            "feature_recognition": {
                "available": FEATURE_AVAILABLE,
                "endpoints": [
                    "POST /api/feature-recognition/batch - 批量特征识别",
                    "GET /api/feature-recognition/health - 特征识别服务健康检查"
                ]
            }
        },
        "docs": "/docs",
        "redoc": "/redoc"
    }

@app.get("/health", tags=["通用"])
async def health():
    """统一健康检查"""
    return {
        "status": "healthy",
        "service": "CAD 服务统一接口",
        "services": {
            "chaitu": "available" if CHAITU_AVAILABLE else "unavailable",
            "feature_recognition": "available" if FEATURE_AVAILABLE else "unavailable"
        }
    }

# ==================== 启动配置 ====================

if __name__ == "__main__":
    # 从环境变量读取配置
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("API_RELOAD", "false").lower() == "true"
    workers = int(os.getenv("API_WORKERS", "1"))
    
    print("=" * 80)
    print("CAD 服务统一接口")
    print("=" * 80)
    print(f"服务地址: http://{host}:{port}")
    print(f"自动重载: {reload}")
    print(f"工作进程: {workers}")
    print("-" * 80)
    print("服务状态:")
    print(f"  拆图服务: {'✅ 可用' if CHAITU_AVAILABLE else '❌ 不可用'}")
    print(f"  特征识别服务: {'✅ 可用' if FEATURE_AVAILABLE else '❌ 不可用'}")
    print("-" * 80)
    print("可用接口:")
    print()
    print("  【拆图服务】")
    print(f"    POST http://{host}:{port}/api/chaitu")
    print(f"    GET  http://{host}:{port}/api/chaitu/health")
    print()
    print("  【特征识别服务】")
    print(f"    POST http://{host}:{port}/api/feature-recognition/batch")
    print(f"    GET  http://{host}:{port}/api/feature-recognition/health")
    print()
    print("  【通用接口】")
    print(f"    GET  http://{host}:{port}/")
    print(f"    GET  http://{host}:{port}/health")
    print(f"    GET  http://{host}:{port}/docs (Swagger 文档)")
    print(f"    GET  http://{host}:{port}/redoc (ReDoc 文档)")
    print("=" * 80)
    
    uvicorn.run(
        "unified_api:app",
        host=host,
        port=port,
        reload=reload,
        workers=1 if reload else workers  # reload 模式下只能用单进程
    )
