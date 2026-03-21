# -*- coding: utf-8 -*-
"""
牙孔工艺识别模块
识别加工说明中的牙孔信息（Mxx8*Pxx 或 Mxx攻）
"""

import re
import logging
from typing import List, Dict, Any, Optional


def detect_tooth_hole(all_texts: List[str], 
                     processing_instructions: Dict[str, List[str]],
                     has_auto_material: bool,
                     heat_treatment: Optional[str],
                     msp=None,
                     views: Optional[Dict[str, Dict]] = None) -> Optional[Dict[str, Any]]:
    """
    识别牙孔工艺信息
    
    条件：
    1. 必须是自找料（has_auto_material = True）
    2. 必须有热处理（heat_treatment 不为空）
    
    识别模式：
    - 'Mxx8*Pxx' 格式（如 M8*P1.25）
    - 'Mxx8XPxx' 格式（如 M8XP1.25）
    - 'Mxx攻' 格式（如 M8攻）
    
    识别规则：
    - size: 从 Mxx 中提取（如 M8, M10）
    - is_through: 根据是否包含 '攻穿' 判断（有='t', 无='f'）
    - set_screw: 根据是否包含 '止付螺丝' 判断（有='t', 无='f'）
    - number: 优先从文本中提取（如 "M :1 -" 提取1），如果没有则从图框ID提取（如 "frame_M4" 提取4），都没有则默认2
    - view: 根据阶段5识别的三个视图判断牙孔所在视图
    
    Args:
        all_texts: 所有文本列表
        processing_instructions: 加工说明字典（图框文字）
        has_auto_material: 是否是自找料
        heat_treatment: 热处理信息
        msp: modelspace（用于查找文本位置）
        views: 阶段5识别的三个视图信息 {'top_view': {'bounds': {...}}, 'front_view': {...}, 'side_view': {...}}
    
    Returns:
        Dict: 牙孔数据，格式为：
        {
            "tooth_hole_details": [
                {
                    "code": "M",           # 工艺编号
                    "size": "M8",          # 牙孔规格
                    "view": "top_view",    # 视图（从阶段5识别）
                    "number": 4,           # 数量（从编号提取）
                    "set_screw": "t",      # 是否止付螺丝（从文本识别）
                    "is_through": "f"      # 是否通孔（从文本识别）
                }
            ]
        }
        如果不满足条件或未识别到牙孔，返回 None
    """
    try:
        # 判断是否满足识别条件
        if not has_auto_material:
            logging.info("ℹ️ 非自找料，跳过牙孔识别")
            return None
        
        if not heat_treatment or not heat_treatment.strip():
            logging.info("ℹ️ 无热处理，跳过牙孔识别")
            return None
        
        logging.info("")
        logging.info("=" * 80)
        logging.info("🔧 【牙孔工艺识别】")
        logging.info("=" * 80)
        logging.info(f"✅ 满足识别条件: 自找料={has_auto_material}, 热处理={heat_treatment}")
        
        # 打印视图信息
        if views:
            logging.info(f"✅ 已获取阶段5的视图信息: {list(views.keys())}")
        else:
            logging.warning("⚠️ 未获取到阶段5的视图信息，将使用默认视图")
        
        # 定义识别模式
        # 模式1: Mxx8*Pxx 或 Mxx8XPxx 格式（如 M8*P1.25, M8XP1.25, M10*P1.5）
        # 支持的分隔符: *, ×, x, X（可选空格）
        pattern1 = re.compile(r'(M\d+(?:\.\d+)?)\s*[*×xX]\s*P\d+(?:\.\d+)?', re.IGNORECASE)
        
        # 模式2: Mxx攻 格式（如 M8攻, M10攻）
        pattern2 = re.compile(r'(M\d+(?:\.\d+)?)攻', re.IGNORECASE)
        
        tooth_hole_details = []
        found_codes = {}  # 用于去重，key=frame_id, value=set of sizes
        
        # 遍历加工说明（图框文字）
        for frame_id, texts in processing_instructions.items():
            if frame_id not in found_codes:
                found_codes[frame_id] = set()
            
            # 预处理：合并以逗号开头的行
            merged_texts = _merge_continuation_lines(texts)
            
            for text in merged_texts:
                if not text:
                    continue
                
                # 尝试匹配模式1: Mxx8*Pxx
                matches1 = pattern1.finditer(text)
                for match in matches1:
                    size = match.group(1).upper()  # 提取 M8, M10 等
                    
                    # 提取数量：优先从文本中提取，如果没有则从图框ID提取
                    number_from_text = _extract_number_from_text(text)
                    code, number_from_frame = _extract_code_and_number(frame_id)
                    number = number_from_text if number_from_text is not None else number_from_frame
                    
                    # 去重（同一个图框内的同一规格只记录一次）
                    if size in found_codes[frame_id]:
                        continue
                    found_codes[frame_id].add(size)
                    
                    # 判断是否通孔：检查是否包含 '攻穿'
                    is_through = 't' if '攻穿' in text else 'f'
                    
                    # 判断是否止付螺丝：检查是否包含 '止付螺丝'
                    set_screw = 't' if '止付螺丝' in text else 'f'
                    
                    # 判断视图：根据文本位置和阶段5的视图信息
                    view = _determine_view_for_text(text, msp, views)
                    
                    tooth_hole_details.append({
                        "code": code,
                        "size": size,
                        "view": view,
                        "number": number,
                        "set_screw": set_screw,
                        "is_through": is_through
                    })
                    
                    logging.info(
                        f"✅ 识别到牙孔（模式1-Mxx*Pxx/MxxXPxx）: {text} -> "
                        f"编号={code}, 规格={size}, 数量={number}, "
                        f"视图={view}, 通孔={is_through}, 止付螺丝={set_screw}"
                    )
                
                # 尝试匹配模式2: Mxx攻
                matches2 = pattern2.finditer(text)
                for match in matches2:
                    size = match.group(1).upper()  # 提取 M8, M10 等
                    
                    # 提取数量：优先从文本中提取，如果没有则从图框ID提取
                    number_from_text = _extract_number_from_text(text)
                    code, number_from_frame = _extract_code_and_number(frame_id)
                    number = number_from_text if number_from_text is not None else number_from_frame
                    
                    # 去重（同一个图框内的同一规格只记录一次）
                    if size in found_codes[frame_id]:
                        continue
                    found_codes[frame_id].add(size)
                    
                    # 判断是否通孔：检查是否包含 '攻穿'
                    is_through = 't' if '攻穿' in text else 'f'
                    
                    # 判断是否止付螺丝：检查是否包含 '止付螺丝'
                    set_screw = 't' if '止付螺丝' in text else 'f'
                    
                    # 判断视图：根据文本位置和阶段5的视图信息
                    view = _determine_view_for_text(text, msp, views)
                    
                    tooth_hole_details.append({
                        "code": code,
                        "size": size,
                        "view": view,
                        "number": number,
                        "set_screw": set_screw,
                        "is_through": is_through
                    })
                    
                    logging.info(
                        f"✅ 识别到牙孔（模式2）: {text} -> "
                        f"编号={code}, 规格={size}, 数量={number}, "
                        f"视图={view}, 通孔={is_through}, 止付螺丝={set_screw}"
                    )
        
        # 返回结果
        if tooth_hole_details:
            result = {"tooth_hole_details": tooth_hole_details}
            logging.info(f"✅ 牙孔识别完成: 共识别到 {len(tooth_hole_details)} 个牙孔")
            logging.info("=" * 80)
            logging.info("")
            return result
        else:
            logging.info("ℹ️ 未识别到牙孔信息")
            logging.info("=" * 80)
            logging.info("")
            return None
        
    except Exception as e:
        logging.error(f"❌ 牙孔识别失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return None


def _merge_continuation_lines(texts: List[str]) -> List[str]:
    """
    合并以逗号开头的续行
    
    规则：
    - 如果一行以逗号开头，则与上一行合并
    - 合并后的文本用于后续识别
    
    Args:
        texts: 原始文本列表
    
    Returns:
        List[str]: 合并后的文本列表
    
    Examples:
        输入:
        [
            "M :1 -M10XP1.5背攻穿",
            ",背沉头Φ14.5留底深10.0mm(螺丝)"
        ]
        
        输出:
        [
            "M :1 -M10XP1.5背攻穿,背沉头Φ14.5留底深10.0mm(螺丝)"
        ]
    """
    if not texts:
        return []
    
    merged = []
    current_line = None
    
    for text in texts:
        if not text:
            continue
        
        # 检查是否以逗号开头（去除前导空格）
        stripped_text = text.lstrip()
        if stripped_text.startswith(','):
            # 续行：与上一行合并
            if current_line is not None:
                current_line += stripped_text  # 保留逗号
                logging.debug(f"合并续行: {current_line}")
            else:
                # 第一行就是逗号开头，单独保留
                current_line = stripped_text
        else:
            # 新的一行：保存上一行（如果有），开始新行
            if current_line is not None:
                merged.append(current_line)
            current_line = text
    
    # 保存最后一行
    if current_line is not None:
        merged.append(current_line)
    
    return merged


def _extract_number_from_text(text: str) -> Optional[int]:
    """
    从文本中提取数量
    
    识别模式：
    - "M :1 -M10XP1.5" → 提取 :1 后的数字 → 1
    - "M :4 -M8*P1.25" → 提取 :4 后的数字 → 4
    - "N :10 -M12攻" → 提取 :10 后的数字 → 10
    
    Args:
        text: 文本内容
    
    Returns:
        int: 提取的数量，如果没有匹配则返回 None
    """
    # 模式: "字母 :数字 -" 格式（如 "M :1 -", "N :4 -"）
    match = re.search(r'[A-Za-z]\s*:\s*(\d+)\s*-', text)
    if match:
        number = int(match.group(1))
        logging.debug(f"从文本中提取数量: {text} -> {number}")
        return number
    
    return None


def _extract_code_and_number(frame_id: str) -> tuple:
    """
    从图框ID中提取工艺编号和数量
    
    Args:
        frame_id: 图框ID（如 "frame_M", "frame_M4", "frame_N10"）
    
    Returns:
        tuple: (code, number)
            - code: 工艺编号（如 "M", "N", "L"）
            - number: 数量（从编号后的数字提取，如果没有则返回2）
    
    Examples:
        "frame_M" -> ("M", 2)
        "frame_M4" -> ("M", 4)
        "frame_N10" -> ("N", 10)
        "frame_L2" -> ("L", 2)
    """
    if not frame_id:
        return ("M", 2)
    
    # 移除 "frame_" 前缀（如果有）
    if frame_id.startswith("frame_"):
        frame_id = frame_id[6:]  # 移除 "frame_"
    
    # 提取字母和数字
    # 例如: "M4" -> code="M", number=4
    #      "N10" -> code="N", number=10
    #      "M" -> code="M", number=2 (默认)
    match = re.match(r'([A-Za-z])(\d*)', frame_id)
    if match:
        code = match.group(1).upper()
        number_str = match.group(2)
        
        if number_str:
            number = int(number_str)
        else:
            number = 2  # 默认值
        
        return (code, number)
    else:
        # 如果没有匹配到，返回默认值
        return ("M", 2)


def _determine_view_for_text(text: str, msp, views: Optional[Dict[str, Dict]]) -> str:
    """
    根据文本位置和阶段5的视图信息判断文本所在的视图
    
    Args:
        text: 文本内容
        msp: modelspace（用于查找文本位置）
        views: 阶段5识别的三个视图信息 {'top_view': {'bounds': {...}}, ...}
    
    Returns:
        str: 视图名称（'top_view', 'front_view', 'side_view'），如果无法判断则返回 'top_view'
    """
    # 如果没有提供 msp 或 views，返回默认值
    if not msp or not views:
        return "top_view"
    
    try:
        # 查找包含该文本的 TEXT 或 MTEXT 实体
        text_position = None
        
        # 查找 TEXT 实体
        for entity in msp.query('TEXT'):
            if hasattr(entity.dxf, 'text') and entity.dxf.text == text:
                if hasattr(entity.dxf, 'insert'):
                    text_position = (entity.dxf.insert.x, entity.dxf.insert.y)
                    break
        
        # 如果没找到，查找 MTEXT 实体
        if not text_position:
            for entity in msp.query('MTEXT'):
                if hasattr(entity, 'text') and entity.text == text:
                    if hasattr(entity.dxf, 'insert'):
                        text_position = (entity.dxf.insert.x, entity.dxf.insert.y)
                        break
        
        # 如果找到了文本位置，判断它在哪个视图中
        if text_position:
            x, y = text_position
            
            # 检查每个视图
            for view_name, view_data in views.items():
                if 'bounds' in view_data:
                    bounds = view_data['bounds']
                    
                    # 判断点是否在边界内
                    if (bounds['min_x'] <= x <= bounds['max_x'] and 
                        bounds['min_y'] <= y <= bounds['max_y']):
                        logging.debug(f"文本 '{text}' 位于 {view_name}")
                        return view_name
            
            logging.debug(f"文本 '{text}' 不在任何视图内，使用默认视图")
        else:
            logging.debug(f"未找到文本 '{text}' 的位置，使用默认视图")
        
    except Exception as e:
        logging.warning(f"判断文本视图时出错: {e}")
    
    # 默认返回俯视图
    return "top_view"


def _extract_number_from_code(code: str) -> int:
    """
    从工艺编号中提取数字
    
    Args:
        code: 工艺编号（如 "M", "N", "M4", "N2"）
    
    Returns:
        int: 提取的数字，如果没有数字则返回 2（默认值）
    
    Examples:
        "M" -> 2 (默认值)
        "M4" -> 4
        "N2" -> 2
        "L10" -> 10
    """
    # 提取编号中的数字
    match = re.search(r'\d+', code)
    if match:
        return int(match.group(0))
    else:
        # 如果没有数字，返回默认值 2
        return 2


# 测试代码
if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    print("\n" + "=" * 80)
    print("测试牙孔识别")
    print("=" * 80)
    
    # 测试用例1: 满足条件，有牙孔
    test_processing_instructions_1 = {
        "frame_M": ["M8*P1.25", "其他说明"],
        "frame_N": ["M10攻", "备注"]
    }
    
    result1 = detect_tooth_hole(
        all_texts=[],
        processing_instructions=test_processing_instructions_1,
        has_auto_material=True,
        heat_treatment="HRC58-62"
    )
    print(f"\n测试1结果: {result1}")
    
    # 测试用例2: 不满足条件（非自找料）
    result2 = detect_tooth_hole(
        all_texts=[],
        processing_instructions=test_processing_instructions_1,
        has_auto_material=False,
        heat_treatment="HRC58-62"
    )
    print(f"\n测试2结果: {result2}")
    
    # 测试用例3: 不满足条件（无热处理）
    result3 = detect_tooth_hole(
        all_texts=[],
        processing_instructions=test_processing_instructions_1,
        has_auto_material=True,
        heat_treatment=None
    )
    print(f"\n测试3结果: {result3}")
    
    # 测试用例4: 满足条件，但无牙孔
    test_processing_instructions_4 = {
        "frame_M": ["其他说明", "无牙孔"]
    }
    
    result4 = detect_tooth_hole(
        all_texts=[],
        processing_instructions=test_processing_instructions_4,
        has_auto_material=True,
        heat_treatment="HRC58-62"
    )
    print(f"\n测试4结果: {result4}")
    
    print("\n" + "=" * 80)
