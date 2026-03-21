# CAD 拆图模块

## 模块结构

原来的 `cad_chaitu.py` 文件（2242行）已拆分为以下模块：

### 核心模块

1. **converter.py** - DWG/DXF 格式转换
   - `DWGConverter`: 基于 ODA File Converter 的格式转换器
   - 支持 DWG ↔ DXF 双向转换

2. **number_extractor.py** - 图纸编号识别
   - `ProfessionalDrawingNumberExtractor`: 智能提取子图编号
   - 支持多种编号格式（编号、加工说明、左上角编号等）
   - 内置受控编号字符集和验证规则

3. **text_processor.py** - 文本智能过滤
   - `IntelligentTextProcessor`: 过滤尺寸标注等噪音文本
   - 保留有意义的文本（品名、编号、材料等）

4. **cutting_detector.py** - 切割轮廓检测
   - `RelaxedCuttingDetector`: 识别红色切割线
   - 支持基准点识别（等腰直角三角形）

5. **block_analyzer.py** - CAD 块分析
   - `OptimizedCADBlockAnalyzer`: 识别图框、提取子图区域
   - 自动分配文本到子图
   - 分析切割轮廓

6. **cad_system.py** - CAD 分析系统
   - `CADAnalysisSystem`: 主系统类
   - 子图导出、实体平移、匹配算法

### 辅助模块

7. **database.py** - 数据库操作
   - `DatabaseManager`: 数据库连接池管理
   - 查询 DWG 文件路径
   - 保存子图信息

8. **storage.py** - 文件存储
   - `FileStorageManager`: 支持 MinIO/本地/HTTP
   - 文件上传下载

9. **utils.py** - 工具函数
   - `extract_model_code_from_source`: 提取模型代码

10. **config.py** - 配置管理
    - `Config`: 统一配置类
    - 从 .env 文件加载配置

11. **main.py** - 主处理流程
    - `chaitu_process`: 拆图主函数
    - 完整的拆图流程编排

### 入口文件

- **__init__.py** - 模块入口（推荐使用）
- **cad_chaitu.py** - 原始文件（保留用于向后兼容）

## 使用方法

### 推荐方式：通过模块导入

```python
from scripts.cad_chaitu import chaitu_process

# 调用拆图函数
result = await chaitu_process(
    dwg_url="path/to/file.dwg",  # 可选
    job_id="uuid-string",
    minio_client=minio_client  # 可选
)
```

### 方式 2：独立使用某个模块

```python
from scripts.cad_chaitu import (
    DWGConverter,
    CADAnalysisSystem,
    DatabaseManager,
    FileStorageManager
)

# 1. 转换 DWG -> DXF
converter = DWGConverter(oda_path)
converter.convert_dwg_to_dxf(input_dwg, output_dxf)

# 2. 分析 CAD 文件
system = CADAnalysisSystem()
sub_drawings = system.analyzer.analyze_cad_file(dxf_path)

# 3. 导出子图
system.export_matching_regions(
    target_names=["A01", "B02"],
    output_path="output.dxf"
)
```

### 方式 3：向后兼容（使用原文件）

```python
# 原来的代码仍然可以正常工作
from scripts.cad_chaitu.cad_chaitu import chaitu_process
```

## 功能说明

### 1. DWG/DXF 转换
- 使用 ODA File Converter 进行格式转换
- 支持超时控制（300秒）
- 自动清理临时文件

### 2. 图纸编号识别
识别优先级：
1. "编号" 标签后的编号
2. "加工说明" 标签后的编号
3. 子图左上角的编号

支持的编号格式：
- 标准格式：`A01`, `B02`, `PS-01`
- 复杂格式：`PH-10`, `DIE-20`, `M250247-P6`
- 带括号：`A07(CH-SHESS-70-PG.40-W4.80)`

### 3. 文本过滤
自动过滤：
- 尺寸标注（如 `100.5`, `Φ20`, `R5`）
- CAD 符号（如 `M1`, `G2`, `L3`）
- 高频重复文本
- 排除词汇（如 "图纸", "设计", "审核"）

### 4. 切割轮廓检测
- 识别红色切割线（颜色 1-255）
- 计算切割长度
- 识别基准点（等腰直角三角形）

### 5. 子图导出
- 自动识别图框
- 提取子图区域
- 支持多子图导出
- 自动对齐到原点
- 水平排列多个子图

## 配置说明

在 `.env` 文件中配置：

```env
# ODA 转换器路径
ODA_FILE_CONVERTER_PATH=D:\ODAFileConverter\ODAFileConverter.exe

# 服务器配置
SERVER_HOST=0.0.0.0
SERVER_PORT=6009
SERVER_RELOAD=false
SERVER_WORKERS=1

# 数据库配置
DB_HOST=192.168.0.123
DB_PORT=5432
DB_NAME=mold_cost_db
DB_USER=root
DB_PASSWORD=your_password
```

## 依赖项

```
ezdxf>=1.0.0
loguru>=0.7.0
python-dotenv>=1.0.0
psycopg2-binary>=2.9.0
httpx>=0.24.0
```

## 注意事项

1. **ODA File Converter**: 需要安装 ODA File Converter 并配置正确路径
2. **数据库**: 需要 PostgreSQL 数据库，包含 `jobs` 和 `subgraphs` 表
3. **MinIO**: 可选，用于对象存储
4. **临时文件**: 自动清理，但建议定期检查临时目录

## 迁移指南

从原 `cad_chaitu.py` 迁移到新模块：

1. **无需修改调用代码**：`chaitu_process` 函数接口保持不变
2. **可选升级**：使用 `cad_chaitu_new.py` 作为入口
3. **独立使用**：可以单独导入需要的模块

## 测试

```python
# 测试转换器
from scripts.cad_chaitu import DWGConverter
converter = DWGConverter()
result = converter.convert_dwg_to_dxf("test.dwg", "test.dxf")

# 测试编号提取
from scripts.cad_chaitu import ProfessionalDrawingNumberExtractor
extractor = ProfessionalDrawingNumberExtractor()
filename = extractor.generate_safe_filename("A01(测试)")
```

## 维护建议

1. **日志**: 使用 loguru 记录详细日志
2. **错误处理**: 每个模块都有完善的异常处理
3. **性能**: 使用数据库连接池，避免频繁连接
4. **扩展**: 可以轻松添加新的编号识别规则或文本过滤规则
