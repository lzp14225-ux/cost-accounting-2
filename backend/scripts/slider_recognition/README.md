# 红色面分析工具

自动识别NX PRT文件中的红色面，测量面积和周长，并生成详细报告。

## 功能

1. ✅ 自动识别所有红色面（颜色索引：186）
2. ✅ 获取红色面所属的零件编号
3. ✅ 自动测量每个红色面的面积（mm²）和周长（mm）
4. ✅ 生成Excel可打开的CSV报告
5. ✅ 自动计算总面积和总周长

## 使用方法

### 在NX Python环境中运行

```powershell
python 红色面分析工具.py [PRT文件路径]
```

如果不指定文件路径，默认使用：`C:\Projects\slider_recognition\M250286-P3.prt`

### 示例

```powershell
# 使用默认文件
python 红色面分析工具.py

# 指定文件
python 红色面分析工具.py "D:\models\my_part.prt"
```

## 输出

脚本会生成一个CSV报告文件：`红色面分析报告.csv`

报告包含：
- 零件编号
- 面编号
- Face Tag（用于在NX中定位）
- 颜色索引
- 面积（mm²）
- 周长（mm）
- 汇总统计

## 技术实现

### 核心API

```python
# 测量面积和周长
measure_mgr = work_part.MeasureManager
result = measure_mgr.NewFaceProperties(
    area_unit,      # 面积单位（SquareMilliMeter）
    length_unit,    # 长度单位（MilliMeter）
    accuracy,       # 精度（0.01）
    [face]          # 面对象列表
)

area = result.Area          # 获取面积
perimeter = result.Perimeter  # 获取周长
```

### 识别红色面

```python
# 红色颜色索引
red_colors = {186}

# 检查面的颜色
if face.Color in red_colors:
    # 这是红色面
    pass
```

## 文件说明

- `红色面分析工具.py` - 主程序（唯一需要的文件）
- `prt_split.py` - PRT文件拆分工具（可选，用于其他用途）
- `sliderrecognition.macro` - NX宏文件（参考）
- `README.md` - 本说明文档

## 测试结果

测试文件：`M250286-P3.prt`
- 零件编号：DIE-06
- 红色面数量：45个
- 总面积：39218.467 mm²
- 总周长：5147.892 mm

## 系统要求

- NX 2312（或其他版本）
- Python环境（NX自带）
- NXOpen库

## 注意事项

1. 必须在NX Python环境中运行（命令提示符显示 `(NX)`）
2. 脚本会自动打开PRT文件，无需手动在NX中打开
3. 生成的CSV文件可以用Excel打开查看
4. 测量精度设置为0.01mm

## 作者：黄福兵

Created: 2026-03-12
