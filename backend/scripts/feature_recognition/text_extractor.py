# -*- coding: utf-8 -*-
"""
统一文本提取模块
一次性提取所有文本实体，避免重复遍历
"""

import re
import logging
from typing import Dict, List, Tuple, Optional, Any

logging.basicConfig(level=logging.INFO)


def get_text_content(entity) -> Optional[str]:
    """获取文本实体的内容"""
    try:
        entity_type = entity.dxftype()
        
        if entity_type == 'MTEXT':
            # MTEXT 可能有多种属性
            if hasattr(entity, 'get_text'):
                content = entity.get_text()
            elif hasattr(entity, 'plain_text'):
                content = entity.plain_text()
            elif hasattr(entity, 'text'):
                content = entity.text
            else:
                content = entity.dxf.text
        elif entity_type == 'TEXT':
            content = entity.dxf.text
        elif entity_type in ['ATTRIB', 'ATTDEF']:
            content = entity.dxf.text
        elif entity_type == 'DIMENSION':
            # 检查是否为半径标注
            dim_type = entity.dimtype if hasattr(entity, 'dimtype') else None
            
            if dim_type == 4:  # 半径标注
                measurement = entity.get_measurement() if hasattr(entity, 'get_measurement') else None
                if measurement:
                    # 四舍五入到两位小数，避免浮点精度问题
                    content = f"R{round(measurement, 2)}"  # 添加R前缀
            else:
                # 其他标注类型，保持原逻辑
                if hasattr(entity, 'get_measurement'):
                    content = str(entity.get_measurement())
                else:
                    content = entity.dxf.text if hasattr(entity.dxf, 'text') else None
        else:
            return None
        
        return content if content else None
    except Exception as e:
        logging.debug(f"获取文本内容失败: {e}")
        return None


def get_text_position(entity) -> Optional[Tuple[float, float]]:
    """获取文本实体的位置"""
    try:
        if hasattr(entity.dxf, 'insert'):
            point = entity.dxf.insert
            return (float(point.x), float(point.y))
        elif hasattr(entity.dxf, 'position'):
            point = entity.dxf.position
            return (float(point.x), float(point.y))
    except Exception as e:
        logging.debug(f"获取文本位置失败: {e}")
    return None


# def clean_text_content(content: str) -> str:
#     """清洗文本内容，移除格式化代码"""
#     if not content:
#         return ""
    
#     # 移除 MTEXT 格式化代码
#     content = re.sub(r'\{\\[^}]*\}', '', content)
#     content = re.sub(r'\\[A-Za-z][^;]*;', '', content)
    
#     # 替换特殊符号
#     replacements = {
#         '%%c': 'Φ', '%%C': 'Φ',
#         '%%d': '°', '%%D': '°',
#         '%%p': '±', '%%P': '±',
#         '\\P': '\n', '\\p': '\n'
#     }
#     for old, new in replacements.items():
#         content = content.replace(old, new)
    
#     # 规范化空白字符
#     content = re.sub(r'\s+', ' ', content).strip()
    
#     return content

def clean_text_content(content: str) -> str:
    """清洗文本内容，移除格式化代码"""
    if not content:
        return ""

    # 解码 Unicode 转义序列（如 \U+52a0 -> 加）
    # 这是为了处理从 DWG 转换的 DXF 文件中的中文字符
    if '\\U+' in content or '\\u' in content:
        def decode_unicode_escape(match):
            code = match.group(1)
            try:
                return chr(int(code, 16))
            except:
                return match.group(0)

        # 解码 \U+xxxx 格式（严格 4 位十六进制）
        content = re.sub(r'\\U\+([0-9a-fA-F]{4})', decode_unicode_escape, content)
        # 解码 \uxxxx 格式（严格 4 位十六进制）
        content = re.sub(r'\\u([0-9a-fA-F]{4})', decode_unicode_escape, content)

    # 移除 MTEXT 格式化代码
    content = re.sub(r'\{\\[^}]*\}', '', content)
    content = re.sub(r'\\[A-Za-z][^;]*;', '', content)

    # 替换特殊符号
    replacements = {
        '%%c': 'Φ', '%%C': 'Φ',
        '%%d': '°', '%%D': '°',
        '%%p': '±', '%%P': '±',
        '\\P': '\n', '\\p': '\n'
    }
    for old, new in replacements.items():
        content = content.replace(old, new)

    # 规范化空白字符
    content = re.sub(r'\s+', ' ', content).strip()

    return content

def is_valid_text_content(content: str, entity_type: str = None) -> bool:
    """
    判断文本内容是否有效（过滤无用内容）
    
    过滤规则：
    1. 过滤坐标点格式：(x, y, z)
    2. 过滤纯数字（尺寸标注的测量值）
    3. 过滤空白内容
    4. 过滤单个字母或符号（但保留中文单字和加工代号）
    5. 过滤重复的加工代号标注（如果已经有完整说明）
    6. 特殊规则：保留以 'C' 开头的 MTEXT（多行文字）
    
    Args:
        content: 文本内容
        entity_type: 实体类型 ('TEXT', 'MTEXT', 等)
    """
    if not content or not content.strip():
        return False
    
    content = content.strip()
    
    # 特殊规则：保留以 'C' 开头的 MTEXT（多行文字）
    if entity_type == 'MTEXT' and content.startswith('C'):
        return True
    
    # 过滤坐标点格式：(数字, 数字, 数字)
    if re.match(r'^\([0-9\.\-\+e, ]+\)$', content):
        return False
    
    # 过滤纯数字（包括小数）
    if re.match(r'^[0-9\.\-\+]+$', content):
        return False
    
    # 过滤单个字母或单个符号（但保留中文单字）
    if len(content) == 1 and not re.match(r'[\u4e00-\u9fa5]', content):
        return False
    
    # 过滤只包含空格、逗号、括号等符号的内容
    if re.match(r'^[\s,\(\)\[\]\{\}\.\-\+]+$', content):
        return False
    
    # 过滤单独的加工代号标注（如 "M2", "W1", "M", "L", "C10", "M32" 等）
    # 这些通常是标注位置，而不是实际的加工说明内容
    # 保留带有冒号或详细说明的内容（如 "M2 :1 -M8,Φ9.0钻穿"）
    # 匹配规则：1个大写字母 + 0-2个字母或数字（总长度1-3个字符）
    if re.match(r'^[A-Z][A-Z0-9]{0,2}$', content):
        # 单独的字母或字母+数字组合，可能是重复标注
        return False
    
    return True


def extract_all_texts(msp) -> Dict[str, Any]:
    """
    一次性提取所有文本实体及其属性
    
    Args:
        msp: ezdxf modelspace 对象
    
    Returns:
        {
            'texts': List[str],              # 清洗后的文本内容列表
            'positions': List[Tuple],        # 位置列表 (x, y)
            'types': List[str],              # 实体类型列表
            'layers': List[str],             # 图层列表
            'entities': List[Entity],        # 原始实体对象列表
            'raw_contents': List[str]        # 原始文本内容（未清洗）
        }
    """
    texts = []
    positions = []
    types = []
    layers = []
    entities = []
    raw_contents = []
    
    try:
        # 一次性查询所有文本实体
        for entity in msp.query('TEXT MTEXT ATTRIB ATTDEF DIMENSION'):
            try:
                # 获取原始文本内容
                raw_content = get_text_content(entity)
                if not raw_content:
                    continue
                
                # 获取位置
                position = get_text_position(entity)
                if not position:
                    continue
                
                # 清洗文本内容
                cleaned_content = clean_text_content(raw_content)
                
                # 获取实体类型
                entity_type = entity.dxftype()
                
                # 验证内容是否有效（传递 entity_type 参数）
                if not cleaned_content or not is_valid_text_content(cleaned_content, entity_type):
                    continue
                
                # 收集数据
                texts.append(cleaned_content)
                positions.append(position)
                types.append(entity_type)
                layers.append(getattr(entity.dxf, 'layer', '0'))
                entities.append(entity)
                raw_contents.append(raw_content)
                
            except Exception as e:
                logging.debug(f"处理文本实体失败: {e}")
                continue
        
        logging.info(f"✅ 统一文本提取完成: 共提取 {len(texts)} 条有效文本")
        
        return {
            'texts': texts,
            'positions': positions,
            'types': types,
            'layers': layers,
            'entities': entities,
            'raw_contents': raw_contents
        }
        
    except Exception as e:
        logging.error(f"❌ 统一文本提取失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        
        # 返回空结果而不是抛出异常
        return {
            'texts': [],
            'positions': [],
            'types': [],
            'layers': [],
            'entities': [],
            'raw_contents': []
        }


def extract_all_texts_from_file(dxf_file_path: str) -> Dict[str, Any]:
    """
    从 DXF 文件中提取所有文本（便捷函数）
    
    Args:
        dxf_file_path: DXF 文件路径
    
    Returns:
        与 extract_all_texts() 相同的结果
    """
    import ezdxf
    
    try:
        doc = ezdxf.readfile(dxf_file_path)
        msp = doc.modelspace()
        return extract_all_texts(msp)
    except Exception as e:
        logging.error(f"从文件提取文本失败: {e}")
        return {
            'texts': [],
            'positions': [],
            'types': [],
            'layers': [],
            'entities': [],
            'raw_contents': []
        }


# 测试代码
if __name__ == '__main__':
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) < 2:
        print("用法: python text_extractor.py <dxf_file_path>")
        sys.exit(1)
    
    dxf_path = sys.argv[1]
    result = extract_all_texts_from_file(dxf_path)
    
    print("\n" + "=" * 80)
    print("统一文本提取结果")
    print("=" * 80)
    print(f"提取到 {len(result['texts'])} 条有效文本")
    print("\n前10条文本:")
    for i, text in enumerate(result['texts'][:10], 1):
        pos = result['positions'][i-1]
        text_type = result['types'][i-1]
        print(f"{i:3d}. [{text_type:10s}] {text}")
        print(f"      位置: ({pos[0]:.2f}, {pos[1]:.2f})")
    print("=" * 80)
