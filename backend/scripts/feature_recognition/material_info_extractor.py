# -*- coding: utf-8 -*-
"""
材质信息提取模块
从 DXF 文件中提取数量、材质、热处理和重量信息
"""

import re
import ezdxf
from typing import Dict, Optional, Tuple, List
import logging


# 材质字典 - 支持的材质类型（不区分大小写）
MATERIAL_KEYWORDS = [
    # 特殊材质（长关键词优先，避免部分匹配）
    '45#调质',
    '激光热处理/深冷热处理',
    '激光热处理',
    '深冷热处理',
    'SKD11进口',
    '德国进口POM材质',
    '7CrSiMnMov',
    # 基础材质
    '45#',
    'P20',
    'CR12MOV',
    'CR12',
    'CR8',
    'SKD11',
    'SKH-51',
    'SKH-9',
    'DC53',
    'D2',
    'TOOLOX44',
    'TOOLOX33',
    'TOOL0X44',
    'TOOL0X33',
    'T00L0X44',
    'T00L0X33',
    'A3',
    # 特殊材料
    '钨钢',
    '铝',
    '尼龙',
    '赛钢',
    '铁氟龙',
    '合金铜',
    '优力胶',
    '黄铜',
    'PEEK',
    '8566',
    '铍铜',
    '电木'
]

# 材质标准化映射 - 将不同写法统一为标准格式
MATERIAL_NORMALIZATION = {
    'TOOL0X44': 'T00L0X44',
    'TOOLOX44': 'T00L0X44',
    'TOOL0X33': 'T00L0X33',
    'TOOLOX33': 'T00L0X33',
}


def normalize_material(material: str) -> str:
    """
    标准化材质名称
    
    将不同写法的材质统一为标准格式
    例如：TOOL0X44, TOOLOX44 -> T00L0X44
    
    Args:
        material: 原始材质名称
    
    Returns:
        标准化后的材质名称
    """
    if not material:
        return material
    
    # 转换为大写进行匹配
    material_upper = material.upper()
    
    # 检查是否需要标准化
    if material_upper in MATERIAL_NORMALIZATION:
        normalized = MATERIAL_NORMALIZATION[material_upper]
        logging.debug(f"材质标准化: {material} -> {normalized}")
        return normalized
    
    return material


def get_text_content(entity) -> Optional[str]:
    """获取文本实体的内容"""
    try:
        entity_type = entity.dxftype()
        
        if entity_type == 'MTEXT':
            content = entity.text if hasattr(entity, 'text') else entity.dxf.text
        elif entity_type == 'TEXT':
            content = entity.dxf.text
        elif entity_type in ['ATTRIB', 'ATTDEF']:
            content = entity.dxf.text
        else:
            return None
        
        return content if content else None
    except Exception as e:
        logging.debug(f"获取文本内容失败: {e}")
        return None


def extract_heat_treatment_from_text(text: str) -> Optional[Dict]:
    """
    从文本中提取热处理信息（基于优先级匹配 + 标签格式）
    
    优先级顺序：
    0. 标签格式：热处理：xxx（最高优先级）
    1. HRC 硬度 - 如 HRC58-62, HRC58
    2. 调质
    3. 激光热处理
    4. 深冷热处理
    
    Args:
        text: 文本内容
    
    Returns:
        {
            'heat_treatment': str,      # 完整的热处理信息（如 'HRC58-62'）
            'heat_treatment_type': str, # 热处理类型（'HRC', '调质', '激光', '深冷'）
            'heat_treated': bool        # 是否有热处理
        }
        或 None（如果没有找到热处理信息）
    """
    if not text:
        return None
    
    try:
        # 策略0: 标签格式匹配（优先级最高）
        labeled_heat_treatment = extract_labeled_value(text, ['热处理'])
        if labeled_heat_treatment:
            # 进一步识别热处理类型
            ht_upper = labeled_heat_treatment.upper()
            
            # 检查是否是 HRC
            if 'HRC' in ht_upper:
                hrc_pattern = r'(HRC\s*\d+(?:\s*[-~]\s*\d+)?)'
                hrc_match = re.search(hrc_pattern, labeled_heat_treatment, re.IGNORECASE)
                if hrc_match:
                    hrc_code = re.sub(r'\s+', '', hrc_match.group(1)).upper()
                    logging.debug(f"从标签格式提取到 HRC 热处理: {hrc_code}")
                    return {
                        'heat_treatment': hrc_code,
                        'heat_treatment_type': 'HRC',
                        'heat_treated': True
                    }
            
            # 检查其他类型
            if '调质' in labeled_heat_treatment:
                logging.debug(f"从标签格式提取到调质热处理")
                return {
                    'heat_treatment': '调质',
                    'heat_treatment_type': '调质',
                    'heat_treated': True
                }
            elif '激光' in labeled_heat_treatment:
                logging.debug(f"从标签格式提取到激光热处理")
                return {
                    'heat_treatment': '激光热处理',
                    'heat_treatment_type': '激光',
                    'heat_treated': True
                }
            elif '深冷' in labeled_heat_treatment:
                logging.debug(f"从标签格式提取到深冷热处理")
                return {
                    'heat_treatment': '深冷热处理',
                    'heat_treatment_type': '深冷',
                    'heat_treated': True
                }
            else:
                # 其他热处理类型，直接返回
                logging.debug(f"从标签格式提取到热处理: {labeled_heat_treatment}")
                return {
                    'heat_treatment': labeled_heat_treatment,
                    'heat_treatment_type': '其他',
                    'heat_treated': True
                }
        
        # 策略1: HRC 硬度识别（优先级最高）
        # 匹配: HRC58, HRC 58, HRC58-62, HRC 58 ~ 62, HRC58~62
        hrc_pattern = r'(HRC\s*\d+(?:\s*[-~]\s*\d+)?)'
        hrc_match = re.search(hrc_pattern, text, re.IGNORECASE)
        
        if hrc_match:
            # 提取完整的 HRC 代码并去除空格
            hrc_code = re.sub(r'\s+', '', hrc_match.group(1))
            # 统一转换为大写（HRC 部分）
            hrc_code = hrc_code.upper()
            logging.debug(f"从文本中提取到 HRC 热处理: {hrc_code}")
            return {
                'heat_treatment': hrc_code,
                'heat_treatment_type': 'HRC',
                'heat_treated': True
            }
        
        # 策略2: 调质识别
        if '调质' in text:
            logging.debug(f"从文本中提取到调质热处理")
            return {
                'heat_treatment': '调质',
                'heat_treatment_type': '调质',
                'heat_treated': True
            }
        
        # 策略3: 激光热处理识别
        if '激光' in text:
            logging.debug(f"从文本中提取到激光热处理")
            return {
                'heat_treatment': '激光热处理',
                'heat_treatment_type': '激光',
                'heat_treated': True
            }
        
        # 策略4: 深冷热处理识别
        if '深冷' in text:
            logging.debug(f"从文本中提取到深冷热处理")
            return {
                'heat_treatment': '深冷热处理',
                'heat_treatment_type': '深冷',
                'heat_treated': True
            }
        
        return None
        
    except Exception as e:
        logging.debug(f"提取热处理失败: {e}")
        return None


def extract_labeled_value(text: str, labels: List[str]) -> Optional[str]:
    """
    从标签格式的文本中提取值
    
    格式：标签：值 或 标签: 值
    
    Args:
        text: 文本内容
        labels: 标签列表（如 ['品名', '材料', '材质']）
    
    Returns:
        提取的值或 None
    
    示例：
        - "品名：储运块" -> "储运块"
        - "材料：塑料" -> "塑料"
        - "热处理：" -> None（空值）
    """
    if not text:
        return None
    
    try:
        for label in labels:
            # 匹配 "标签：值" 或 "标签: 值"（支持中英文冒号）
            pattern = rf'{re.escape(label)}\s*[:：]\s*(.+)'
            match = re.search(pattern, text)
            
            if match:
                value = match.group(1).strip()
                # 如果值为空或只有横线，返回 None
                if value and value not in ['--', '-', '—']:
                    logging.debug(f"从标签格式提取: {label} = {value}")
                    return value
        
        return None
        
    except Exception as e:
        logging.debug(f"提取标签值失败: {e}")
        return None


def extract_material_from_text(text: str) -> Optional[str]:
    """
    从文本中提取材质信息（基于材质字典 + 标签格式）
    
    规则：
    1. 优先匹配标签格式：材料：xxx 或 材质：xxx
    2. 如果没有标签格式，使用材质字典匹配
    3. 不区分大小写
    4. 返回标准化后的材质名称
    
    Args:
        text: 文本内容
    
    Returns:
        材质字符串或 None
    """
    if not text:
        return None
    
    try:
        # 策略1: 标签格式匹配（优先级最高）
        labeled_material = extract_labeled_value(text, ['材料', '材质'])
        if labeled_material:
            logging.debug(f"从标签格式提取到材质: {labeled_material}")
            # 标准化材质名称
            return normalize_material(labeled_material)
        
        # 策略2: 材质字典匹配
        # 转换为大写进行匹配（不区分大小写）
        text_upper = text.upper()
        
        # 按长度降序排序，优先匹配更长的关键词（避免部分匹配）
        sorted_keywords = sorted(MATERIAL_KEYWORDS, key=len, reverse=True)
        
        for keyword in sorted_keywords:
            keyword_upper = keyword.upper()
            
            # 查找关键词位置
            pos = text_upper.find(keyword_upper)
            if pos != -1:
                # 返回原始文本中的材质（保持原有大小写）
                matched_text = text[pos:pos + len(keyword)]
                logging.debug(f"从材质字典提取到材质: {matched_text} (匹配关键词: {keyword})")
                # 标准化材质名称
                return normalize_material(matched_text)
        
        return None
        
    except Exception as e:
        logging.debug(f"提取材质失败: {e}")
        return None


def extract_material_from_text_safe(text: str) -> Optional[str]:
    """
    从文本中安全提取材质信息（排除工艺编号干扰）
    
    改进点：
    1. 优先匹配标签格式
    2. 排除工艺编号格式（如 "D2 :1 -..."）
    3. 使用材质字典匹配
    
    Args:
        text: 文本内容
    
    Returns:
        材质字符串或 None
    """
    if not text:
        return None
    
    try:
        # 策略1: 标签格式匹配（优先级最高）
        labeled_material = extract_labeled_value(text, ['材料', '材质'])
        if labeled_material:
            logging.debug(f"从标签格式提取到材质: {labeled_material}")
            return normalize_material(labeled_material)
        
        # 策略2: 排除工艺编号后的字典匹配
        # 检查是否为工艺编号格式：字母+数字 :数字 -...
        # 例如：D2 :1 -V型导板槽...
        process_code_pattern = r'^[A-Z]\d*\s*:\s*\d+\s*-'
        if re.match(process_code_pattern, text.strip()):
            logging.debug(f"跳过工艺编号格式文本: {text[:50]}")
            return None
        
        # 策略3: 材质字典匹配（排除工艺编号后）
        text_upper = text.upper()
        sorted_keywords = sorted(MATERIAL_KEYWORDS, key=len, reverse=True)
        
        for keyword in sorted_keywords:
            keyword_upper = keyword.upper()
            pos = text_upper.find(keyword_upper)
            
            if pos != -1:
                # 额外验证：确保不是工艺编号的一部分
                # 检查匹配位置前后的字符
                before_char = text_upper[pos-1] if pos > 0 else ' '
                after_char = text_upper[pos+len(keyword)] if pos+len(keyword) < len(text_upper) else ' '
                
                # 如果前面是字母，后面是空格+冒号，很可能是工艺编号
                # 例如：D2 :1 中的 D2
                if before_char.isalpha() and after_char in [' ', ':']:
                    # 检查是否符合工艺编号模式
                    snippet = text[max(0, pos-5):min(len(text), pos+len(keyword)+10)]
                    if re.search(r'[A-Z]\d*\s*:\s*\d+', snippet):
                        logging.debug(f"跳过疑似工艺编号: {snippet}")
                        continue
                
                matched_text = text[pos:pos + len(keyword)]
                logging.debug(f"从材质字典提取到材质: {matched_text}")
                return normalize_material(matched_text)
        
        return None
        
    except Exception as e:
        logging.debug(f"提取材质失败: {e}")
        return None


def parse_quantity_from_text(text: str) -> Optional[int]:
    """
    从文本中提取数量（简化规则 + 标签格式）
    
    规则：
    1. 优先匹配标签格式：数量：xxx
    2. 识别PCS，PCS前面的数字就是数量
    
    支持格式:
        - "数量：4PCS"
        - "数量: 4PCS"
        - "2PCS"
        - "2 PCS"
        - "3pcs"
        - "1 Pcs"
    
    Args:
        text: 文本内容
    
    Returns:
        数量（整数）或 None
    """
    if not text:
        return None
    
    try:
        # 策略1: 标签格式匹配（优先级最高）
        labeled_quantity = extract_labeled_value(text, ['数量'])
        if labeled_quantity:
            # 从标签值中提取数字
            pattern = r'(\d+)\s*PCS'
            match = re.search(pattern, labeled_quantity, re.IGNORECASE)
            if match:
                quantity = int(match.group(1))
                logging.debug(f"从标签格式提取到数量: {quantity}")
                return quantity
            # 如果没有 PCS，尝试直接提取数字
            pattern = r'(\d+)'
            match = re.search(pattern, labeled_quantity)
            if match:
                quantity = int(match.group(1))
                logging.debug(f"从标签格式提取到数量（无PCS）: {quantity}")
                return quantity
        
        # 策略2: 匹配 "数字 + PCS"（可选空格，大小写不敏感）
        pattern = r'(\d+)\s*PCS'
        match = re.search(pattern, text, re.IGNORECASE)
        
        if match:
            quantity = int(match.group(1))
            logging.debug(f"从文本中提取到数量: {quantity}")
            return quantity
        
        return None
        
    except Exception as e:
        logging.debug(f"提取数量失败: {e}")
        return None


def parse_dimension_line(text: str) -> Optional[Dict]:
    """
    解析包含尺寸、数量、材质、热处理的行
    
    格式示例:
    - 97.0L×50.0W×169.0H 2PCS 45# --
    - 309.5L*87.0W*47.0T 1PCS Cr12MoV HRC58-62
    - 100L×50W×30T 3PCS SKD11 --
    
    Returns:
        {
            'length': 97.0,
            'width': 50.0,
            'thickness': 169.0,
            'quantity': 2,
            'material': '45#',
            'heat_treatment': None  # 或 'HRC58-62'
        }
    """
    if not text:
        return None
    
    # 清理文本
    text = text.strip()
    
    # 模式1: 完整格式 - 尺寸 + 数量 + 材质 + 热处理（热处理可选）
    # 97.0L×50.0W×169.0H 2PCS 45# --
    # 309.5L*87.0W*47.0T 1PCS Cr12MoV HRC58-62
    # 1989.0L*950.0W*27.50T 1PCS 45#
    pattern = r'(\d+\.?\d*)\s*[Ll]\s*[*×xX]\s*(\d+\.?\d*)\s*[Ww]\s*[*×xX]\s*(\d+\.?\d*)\s*[HhTt]\s+(\d+)\s*PCS\s+([A-Za-z0-9#]+)(?:\s+(.*))?'
    
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        length = float(match.group(1))
        width = float(match.group(2))
        thickness = float(match.group(3))
        quantity = int(match.group(4))
        material = match.group(5).strip()
        heat_treatment_str = match.group(6).strip() if match.group(6) else None
        
        # 解析热处理
        heat_treatment = None
        if heat_treatment_str:
            # 清理空格和横线
            cleaned = heat_treatment_str.replace(' ', '').replace('-', '')
            # 如果清理后还有内容，说明是有效的热处理值
            if cleaned:
                heat_treatment = heat_treatment_str.strip()
            else:
                heat_treatment = None
        
        return {
            'length': length,
            'width': width,
            'thickness': thickness,
            'quantity': quantity,
            'material': material,
            'heat_treatment': heat_treatment
        }
    
    return None


def parse_weight_line(text: str) -> Optional[float]:
    """
    解析重量信息
    
    格式示例:
    - GW:19.38KG
    - GW: 19.38 KG
    - GW:19.38kg
    
    Returns:
        重量（千克），如 19.38
    """
    if not text:
        return None
    
    # 模式: GW: 和 KG 之间的数字
    pattern = r'GW\s*[:：]\s*(\d+\.?\d*)\s*KG'
    
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        weight = float(match.group(1))
        return weight
    
    return None


def extract_material_info_from_text(content: str) -> Dict:
    """
    从文本内容中提取材质信息
    
    Args:
        content: 文本内容，可能包含多行
    
    Returns:
        {
            'quantity': int,
            'material': str,
            'heat_treatment': str,
            'weight_kg': float
        }
    """
    result = {
        'quantity': None,
        'material': None,
        'heat_treatment': None,
        'weight_kg': None
    }
    
    if not content:
        return result
    
    # 处理换行符
    lines = content.replace('\\P', '\n').replace('\\p', '\n').split('\n')
    
    for line in lines:
        # 尝试解析尺寸行（包含数量、材质、热处理）
        dimension_info = parse_dimension_line(line)
        if dimension_info:
            result['quantity'] = dimension_info.get('quantity')
            result['material'] = dimension_info.get('material')
            result['heat_treatment'] = dimension_info.get('heat_treatment')
        
        # 尝试解析重量行
        weight = parse_weight_line(line)
        if weight is not None:
            result['weight_kg'] = weight
    
    return result


def check_auto_material_from_texts(texts: List[str]) -> bool:
    """
    检查文本列表中是否包含"自找料"（优化版，避免重复读取文件）
    
    Args:
        texts: 文本内容列表
    
    Returns:
        bool: 如果找到"自找料"返回 True，否则返回 False
    """
    try:
        # 遍历所有文本
        for content in texts:
            if not content:
                continue
            
            # 检查是否包含"自找料"
            if '自找料' in content:
                logging.info(f"✅ 找到'自找料'文本: {content}")
                return True
        
        logging.info("未找到'自找料'文本")
        return False
        
    except Exception as e:
        logging.error(f"检查'自找料'失败: {e}")
        return False


def check_auto_material(dxf_file_path: str) -> bool:
    """
    检查 DXF 文件中是否包含"自找料"文本（兼容旧接口）
    
    注意：此函数会读取整个文件，建议使用 check_auto_material_from_texts
    
    Args:
        dxf_file_path: DXF 文件路径
    
    Returns:
        bool: 如果找到"自找料"返回 True，否则返回 False
    """
    try:
        logging.info(f"开始检查是否包含'自找料': {dxf_file_path}")
        doc = ezdxf.readfile(dxf_file_path)
        msp = doc.modelspace()
        
        # 收集所有文本
        texts = []
        for entity in msp.query('TEXT MTEXT ATTRIB ATTDEF'):
            content = get_text_content(entity)
            if content:
                texts.append(content)
        
        # 使用新函数检查
        return check_auto_material_from_texts(texts)
        
    except Exception as e:
        logging.error(f"检查'自找料'失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return False


def parse_material_info_from_texts(texts: List[str]) -> Dict:
    """
    从预提取的文本列表中解析材质信息（优化版，三层级策略）
    
    策略优先级：
    1. 标准格式精确匹配（xxxL*xxxW*xxxT xxxPCS 材料）- 最可靠
    2. 排除工艺编号后的字典匹配 - 避免误匹配
    3. 标签格式匹配（材料：xxx）- 兜底
    
    Args:
        texts: 文本内容列表
    
    Returns:
        {
            'quantity': int,           # 数量（从任意包含"数字PCS"的文本中提取）
            'material': str,           # 材质，如 '45#', 'Cr12MoV'
            'heat_treatment': str,     # 热处理，如 'HRC58-62'，无则为 None
            'weight_kg': float         # 重量（千克）
        }
    """
    # 初始化结果
    result = {
        'quantity': None,
        'material': None,
        'heat_treatment': None,
        'weight_kg': None
    }
    
    try:
        # ========== 第一轮：优先处理标准格式（最可靠） ==========
        for content in texts:
            if not content:
                continue
            
            # 尝试从标准格式中提取（xxxL*xxxW*xxxT xxxPCS 材料 热处理）
            dimension_info = parse_dimension_line(content)
            if dimension_info:
                if result['quantity'] is None:
                    result['quantity'] = dimension_info.get('quantity')
                    logging.info(f"✅ [标准格式] 找到数量: {result['quantity']} PCS")
                
                if result['material'] is None:
                    result['material'] = dimension_info.get('material')
                    logging.info(f"✅ [标准格式] 找到材质: {result['material']}")
                
                if result['heat_treatment'] is None:
                    result['heat_treatment'] = dimension_info.get('heat_treatment')
                    if result['heat_treatment']:
                        logging.info(f"✅ [标准格式] 找到热处理: {result['heat_treatment']}")
        
        # ========== 第二轮：处理其他信息 ==========
        for content in texts:
            if not content:
                continue
            
            # 提取数量（如果第一轮没找到）
            if result['quantity'] is None:
                quantity = parse_quantity_from_text(content)
                if quantity is not None:
                    result['quantity'] = quantity
                    logging.info(f"✅ [简化规则] 找到数量: {quantity} PCS")
            
            # 提取材质（如果第一轮没找到）
            if result['material'] is None:
                # 使用改进的材质提取函数（排除工艺编号）
                material = extract_material_from_text_safe(content)
                if material is not None:
                    result['material'] = material
                    logging.info(f"✅ [字典匹配] 找到材质: {material}")
            
            # 提取热处理（如果第一轮没找到）
            if result['heat_treatment'] is None:
                heat_treatment_info = extract_heat_treatment_from_text(content)
                if heat_treatment_info is not None:
                    result['heat_treatment'] = heat_treatment_info['heat_treatment']
                    logging.info(f"✅ [字典匹配] 找到热处理: {result['heat_treatment']} (类型: {heat_treatment_info['heat_treatment_type']})")
            
            # 提取重量
            if result['weight_kg'] is None:
                weight = parse_weight_line(content)
                if weight is not None:
                    result['weight_kg'] = weight
                    logging.debug(f"找到重量: {weight} KG")
        
        # 默认值处理
        if result['quantity'] is None:
            result['quantity'] = 1
            logging.info(f"⚠️ 未找到数量信息，使用默认值: 1")
        
        logging.info(
            f"材质信息解析完成: 扫描 {len(texts)} 条文本, "
            f"数量={result['quantity']}, 材质={result['material']}, "
            f"热处理={result['heat_treatment']}, 重量={result['weight_kg']}KG"
        )
        
        return result
        
    except Exception as e:
        logging.error(f"解析材质信息失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {
            'quantity': 1,  # 出错时也使用默认值1
            'material': None,
            'heat_treatment': None,
            'weight_kg': None
        }


def extract_material_info(dxf_file_path: str) -> Dict:
    """
    从 DXF 文件中提取材质信息（兼容旧接口）
    
    注意：此函数会读取整个文件，建议使用 parse_material_info_from_texts
    
    Args:
        dxf_file_path: DXF 文件路径
    
    Returns:
        {
            'quantity': int,           # 数量
            'material': str,           # 材质，如 '45#', 'Cr12MoV'
            'heat_treatment': str,     # 热处理，如 'HRC58-62'，无则为 None
            'weight_kg': float         # 重量（千克）
        }
    """
    try:
        logging.info(f"开始提取材质信息: {dxf_file_path}")
        doc = ezdxf.readfile(dxf_file_path)
        msp = doc.modelspace()
        
        # 收集所有文本
        texts = []
        for entity in msp.query('TEXT MTEXT ATTRIB ATTDEF'):
            content = get_text_content(entity)
            if content:
                texts.append(content)
        
        # 使用新函数解析
        return parse_material_info_from_texts(texts)
        
    except Exception as e:
        logging.error(f"提取材质信息失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {
            'quantity': None,
            'material': None,
            'heat_treatment': None,
            'weight_kg': None
        }


def format_material_info(info: Dict) -> str:
    """
    格式化材质信息为可读字符串
    
    Args:
        info: 材质信息字典
    
    Returns:
        格式化的字符串
    """
    lines = []
    
    if info.get('quantity') is not None:
        lines.append(f"数量: {info['quantity']} PCS")
    else:
        lines.append("数量: 未识别")
    
    if info.get('material'):
        lines.append(f"材质: {info['material']}")
    else:
        lines.append("材质: 未识别")
    
    if info.get('heat_treatment'):
        lines.append(f"热处理: {info['heat_treatment']}")
    else:
        lines.append("热处理: 无")
    
    if info.get('weight_kg') is not None:
        lines.append(f"重量: {info['weight_kg']} KG")
    else:
        lines.append("重量: 未识别")
    
    return '\n'.join(lines)


# 测试代码
if __name__ == '__main__':
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # 测试材质提取函数
    print("\n" + "=" * 80)
    print("测试材质提取函数")
    print("=" * 80)
    
    material_test_cases = [
        "45#调质",
        "CR12",
        "cr12",  # 小写
        "Cr12MoV",
        "SKD11",
        "skh-51",  # 小写
        "SKH-9",
        "P20",
        "p20",  # 小写
        "激光热处理/深冷热处理",
        "材质: 45# 其他信息",
        "使用 CR12MOV 材料",
    ]
    
    for text in material_test_cases:
        material = extract_material_from_text(text)
        print(f"文本: '{text}' -> 材质: {material}")
    
    # 测试解析函数
    print("\n" + "=" * 80)
    print("测试完整解析函数")
    print("=" * 80)
    
    test_cases = [
        "97.0L×50.0W×169.0H 2PCS 45# --",
        "309.5L*87.0W*47.0T 1PCS Cr12MoV HRC58-62",
        "100L×50W×30T 3PCS SKD11 --",
        "GW:19.38KG",
        "GW: 19.38 KG",
    ]
    
    for text in test_cases:
        print(f"\n测试文本: {text}")
        
        # 测试材质提取
        material = extract_material_from_text(text)
        if material:
            print(f"  材质: {material}")
        
        # 测试尺寸解析
        dim_info = parse_dimension_line(text)
        if dim_info:
            print(f"  尺寸信息: {dim_info}")
        
        # 测试重量解析
        weight = parse_weight_line(text)
        if weight:
            print(f"  重量: {weight} KG")
    
    # 测试文件提取
    if len(sys.argv) > 1:
        dxf_path = sys.argv[1]
        print("\n" + "=" * 80)
        print(f"测试文件提取: {dxf_path}")
        print("=" * 80)
        
        info = extract_material_info(dxf_path)
        print("\n提取结果:")
        print(format_material_info(info))
        print("=" * 80)
