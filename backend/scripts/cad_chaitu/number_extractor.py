#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
图纸编号提取模块
"""

import re
from typing import Optional, Dict, List, Tuple
from collections import Counter


class ProfessionalDrawingNumberExtractor:
    """专业图纸编号提取器 + 子图文件名提取"""

    def __init__(self):
        # 子图名称识别优先级：
        # 1) 优先匹配"编号"后面的编号
        # 2) 没有编号的话匹配"加工说明"后面的编号
        # 3) 再兜底：子图左上角可能存在编号（如 PS-01）
        self.number_inline_res = [
            re.compile(r'^\s*编号\s*[：:]\s*(\S+)\s*$', re.IGNORECASE),
            re.compile(r'编号\s*[：:]\s*(\S+)', re.IGNORECASE),
            re.compile(r'编号\s*:\([^)]+\)_(\S+)', re.IGNORECASE),
        ]
        self.processing_inline_res = [
            re.compile(
                r'加工说明[^\r\n]*?[_\-\s]*([A-Za-z]{1,4}\d{1,3}(?:[-_][A-Za-z0-9]+)*)',
                re.IGNORECASE,
            ),
            re.compile(
                r'加工说明\s*(?:[：:]\s*)?(?:\([^)]*\)\s*)?([A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*)',
                re.IGNORECASE,
            ),
            re.compile(r'加工说明\s*(?:\([^)]*\)\s*)?[：:]\s*(\S+)', re.IGNORECASE),
        ]
        self.number_label_only_res = re.compile(r'^\s*编号\s*[:：]?\s*$', re.IGNORECASE)
        self.processing_label_only_res = re.compile(r'^\s*加工说明\s*[:：]?\s*$', re.IGNORECASE)
        self.processing_label_anchor_res = re.compile(r'^\s*加工说明.*$', re.IGNORECASE)

        # 受控编号字符集
        self.confirm_code_res = [
            re.compile(
                r'('
                r'U[12](?:-\s*[A-Z0-9]+)?|'
                r'(?:UP|UB|PH|PU|PS|GU|LB|LP|EB|EJ|FB|CV|CJ|CB|PM)(?:-\s*[A-Z0-9]+)?|'
                r'(?:PPS|DIE|BOL|BOI)(?:-\s*[A-Z0-9]+)?|'
                r'B\d{2}(?:-\s*[A-Z0-9]+)?|'
                r'(?:DIE2|PPS2|PS2|PH2|LB2)(?:-\s*[A-Z0-9]+)?|'
                r'(?:UB_P|PH_P|PU_P|PPS_P|PS_P|GU_P|LB_P|DIE_P)(?:-\s*[A-Z0-9]+)?|'
                r'(?:DIE2_P|PPS2_P|PS2_P|PH2_P|LB2_P)(?:-\s*[A-Z0-9]+)?|'
                r'(?:UP_JIAT|PS_JIAT|LOW_JIAT)(?:-\s*[A-Z0-9]+)?|'
                r'(?:UP_ITEM|PSITEM|LOW_ITEM)(?:-\s*[A-Z0-9]+)?|'
                r'(?:STRIP|CAM)(?:-\s*[A-Z0-9]+)?|'
                r'ST[23](?:-\s*[A-Z0-9]+)?|'
                r'TEMP[12](?:-\s*[A-Z0-9]+)?|'
                r'[A-Z]-\d{1,3}(?:-\s*[A-Z0-9]+)?'
                r')(?=\s|$|[^\w-])',
                re.IGNORECASE,
            ),
            re.compile(
                r'(?:[\(_])'
                r'('
                r'U[12](?:-\s*[A-Z0-9]+)?|'
                r'(?:UP|UB|PH|PU|PS|GU|LB|LP|EB|EJ|FB|CV|CJ|CB|PM)(?:-\s*[A-Z0-9]+)?|'
                r'(?:PPS|DIE|BOL|BOI)(?:-\s*[A-Z0-9]+)?|'
                r'B\d{2}(?:-\s*[A-Z0-9]+)?|'
                r'(?:DIE2|PPS2|PS2|PH2|LB2)(?:-\s*[A-Z0-9]+)?|'
                r'(?:UB_P|PH_P|PU_P|PPS_P|PS_P|GU_P|LB_P|DIE_P)(?:-\s*[A-Z0-9]+)?|'
                r'(?:DIE2_P|PPS2_P|PS2_P|PH2_P|LB2_P)(?:-\s*[A-Z0-9]+)?|'
                r'(?:UP_JIAT|PS_JIAT|LOW_JIAT)(?:-\s*[A-Z0-9]+)?|'
                r'(?:UP_ITEM|PSITEM|LOW_ITEM)(?:-\s*[A-Z0-9]+)?|'
                r'(?:STRIP|CAM)(?:-\s*[A-Z0-9]+)?|'
                r'ST[23](?:-\s*[A-Z0-9]+)?|'
                r'TEMP[12](?:-\s*[A-Z0-9]+)?|'
                r'[A-Z]-\d{1,3}(?:-\s*[A-Z0-9]+)?'
                r')(?=\s|$|[^\w-])',
                re.IGNORECASE,
            ),
        ]

        # 高优先级编号模式
        self.primary_patterns = [
            r'PH-[A-Z0-9]+',
            r'DIE-[A-Z0-9]+',
            r'[A-Z]{1,2}[0-9]{1,3}-[A-Z]{1,2}',
            r'[A-Z]{1,2}[0-9]{2,3}',
            r'[A-Z]{2,4}-[0-9]{1,3}',
        ]

        # 排除词汇库
        self.excluded_terms = {
            '图纸', '设计', '审核', '标准', '规格', '材料', '备注', '品名', '编号',
            '数量', '热处理', '修改', '尺寸', '所有', '全周', '已订购',
            'TITLE', 'DRAWING', 'DESIGN', 'SCALE', 'DATE', '制图', '日期',
            '单位', '比例', '共页', '第页', '版本', 'PCS', '深', '攻', '钻',
            '割', '铰', '倒角', '沉头', '背', '穿', '让位', '合销', '导套',
            '螺丝', '基准', '弹簧', '定位', '精铣', '慢丝', '线割', '垂直度',
            '位置度', '加工', '夹板', '入子', '连接块', '外形', '绿色', '虚线',
            '直身', '拼装', '零件', '模板', '精磨'
        }

        # CAD标注符号库
        self.cad_annotations = {
            'M', 'M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7', 'M8', 'M9', 'M10',
            'G', 'G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'G8', 'G9',
            'L', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7', 'L8', 'L9',
            'U', 'U1', 'U2', 'U3', 'U4', 'U5', 'X', 'X1', 'X2', 'X3', 'X4', 'X5', 'X6', 'X7', 'X8', 'X9',
            'K', 'K1', 'K2', 'K3', 'K4', 'K5', 'A', 'A1', 'A2', 'A3', 'A4', 'A5',
            'Q', 'Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9'
        }

    def _text_pos(self, t: Dict, fallback: Tuple[float, float]) -> Tuple[float, float]:
        p = t.get('position')
        if isinstance(p, (tuple, list)) and len(p) >= 2:
            try:
                return float(p[0]), float(p[1])
            except Exception:
                return fallback
        return fallback

    def _extract_inline(self, texts: List[Dict], regexes: List[re.Pattern]) -> Optional[str]:
        for t in texts:
            c = (t.get('content') or '').strip()
            if not c:
                continue
            for rx in regexes:
                m = rx.search(c)
                if m and m.group(1):
                    cand = self._clean_candidate_after_label(m.group(1))
                    if self._validate_drawing_number(cand):
                        return cand
        return None

    def _extract_near_label(self, bounds: Dict, texts: List[Dict], label_only_re: re.Pattern) -> Optional[str]:
        if not texts:
            return None
        min_x, max_x = bounds.get('min_x', 0.0), bounds.get('max_x', 0.0)
        min_y, max_y = bounds.get('min_y', 0.0), bounds.get('max_y', 0.0)
        width = max(max_x - min_x, 1.0)
        height = max(max_y - min_y, 1.0)
        fallback = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)

        label_texts = []
        for t in texts:
            c = (t.get('content') or '').strip()
            if c and label_only_re.match(c):
                label_texts.append(t)
        if not label_texts:
            return None

        candidates = []
        for t in texts:
            c = (t.get('content') or '').strip()
            if not c:
                continue
            cand = self._clean_candidate_after_label(c)
            if not self._validate_drawing_number(cand):
                continue
            x, y = self._text_pos(t, fallback)
            candidates.append((cand, x, y))
        if not candidates:
            return None

        best = None
        best_score = None
        for label_t in label_texts:
            lx, ly = self._text_pos(label_t, fallback)
            for cand, x, y in candidates:
                dx = abs(x - lx)
                dy = abs(y - ly)
                same_line = dy <= height * 0.06
                right_side = x >= lx - width * 0.02
                below = y <= ly + height * 0.02

                score = (dy * 2.0 + dx)
                if same_line and right_side:
                    score *= 0.25
                elif below and right_side:
                    score *= 0.45
                if dx > width * 0.5 or dy > height * 0.5:
                    score *= 3.0

                if best_score is None or score < best_score:
                    best_score = score
                    best = cand
        return best

    def _normalize_confirmed_code(self, code: str) -> str:
        c = (code or "").strip().upper()
        if not c:
            return ""
        c = re.sub(r"\s*-\s*", "-", c)
        c = re.sub(r"\s+", "", c)
        return c

    def _extract_confirmed_codes_from_text(self, text: str) -> List[str]:
        s = (text or "").strip()
        if not s:
            return []
        found: List[str] = []
        for rx in getattr(self, "confirm_code_res", []):
            for m in rx.finditer(s):
                try:
                    g = m.group(1)
                except Exception:
                    g = None
                if not g:
                    continue
                code = self._normalize_confirmed_code(g)
                if code:
                    found.append(code)
        uniq: List[str] = []
        seen = set()
        for c in found:
            if c not in seen:
                uniq.append(c)
                seen.add(c)
        return uniq

    def _extract_near_label_confirmed(self, bounds: Dict, texts: List[Dict], label_re: re.Pattern) -> Optional[str]:
        if not texts:
            return None
        min_x, max_x = bounds.get("min_x", 0.0), bounds.get("max_x", 0.0)
        min_y, max_y = bounds.get("min_y", 0.0), bounds.get("max_y", 0.0)
        width = max(max_x - min_x, 1.0)
        height = max(max_y - min_y, 1.0)
        fallback = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)

        label_texts = []
        for t in texts:
            c = (t.get("content") or "").strip()
            if c and label_re.match(c):
                label_texts.append(t)
        if not label_texts:
            return None

        candidates: List[Tuple[str, float, float]] = []
        for t in texts:
            c = (t.get("content") or "").strip()
            if not c:
                continue
            codes = self._extract_confirmed_codes_from_text(c)
            if not codes:
                continue
            x, y = self._text_pos(t, fallback)
            for code in codes:
                candidates.append((code, x, y))
        if not candidates:
            return None

        best = None
        best_score = None
        for label_t in label_texts:
            lx, ly = self._text_pos(label_t, fallback)
            for code, x, y in candidates:
                dx = abs(x - lx)
                dy = abs(y - ly)
                same_line = dy <= height * 0.06
                right_side = x >= lx - width * 0.02
                below = y <= ly + height * 0.02

                score = (dy * 2.0 + dx)
                if same_line and right_side:
                    score *= 0.25
                elif below and right_side:
                    score *= 0.45
                if dx > width * 0.6 or dy > height * 0.6:
                    score *= 3.0

                if best_score is None or score < best_score:
                    best_score = score
                    best = code
        return best

    def _extract_from_top_left(self, bounds: Dict, texts: List[Dict]) -> Optional[str]:
        if not texts:
            return None
        min_x, max_x = bounds.get('min_x', 0.0), bounds.get('max_x', 0.0)
        min_y, max_y = bounds.get('min_y', 0.0), bounds.get('max_y', 0.0)
        width = max(max_x - min_x, 1.0)
        height = max(max_y - min_y, 1.0)
        fallback = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)

        x_cut = min_x + width * 0.35
        y_cut = max_y - height * 0.35
        corner_x, corner_y = min_x, max_y

        best = None
        best_dist = None
        for t in texts:
            c = (t.get('content') or '').strip()
            if not c:
                continue
            cand = self._clean_candidate_after_label(c)
            if not self._validate_drawing_number(cand):
                continue
            x, y = self._text_pos(t, fallback)
            if x > x_cut or y < y_cut:
                continue
            d = ((x - corner_x) ** 2 + (y - corner_y) ** 2) ** 0.5
            if best_dist is None or d < best_dist:
                best_dist = d
                best = cand
        return best

    def extract_region_filename_by_patterns(self, subdrawing_data: Dict) -> Optional[str]:
        """按"编号">"加工说明">"左上角编号"优先级提取子图文件名"""
        texts = subdrawing_data.get('texts', []) or []
        bounds = subdrawing_data.get('bounds') or {}

        cand = self._extract_inline(texts, self.number_inline_res)
        if cand:
            return self.generate_safe_filename(cand)

        cand = self._extract_near_label(bounds, texts, self.number_label_only_res)
        if cand:
            return self.generate_safe_filename(cand)

        cand = self._extract_inline(texts, self.processing_inline_res)
        if cand:
            return self.generate_safe_filename(cand)

        cand = self._extract_near_label(bounds, texts, self.processing_label_only_res)
        if cand:
            return self.generate_safe_filename(cand)

        cand = self._extract_near_label_confirmed(bounds, texts, self.processing_label_anchor_res)
        if cand:
            return self.generate_safe_filename(cand)

        cand = self._extract_from_top_left(bounds, texts)
        if cand:
            return self.generate_safe_filename(cand)

        return None

    def extract_drawing_number_from_region(self, subdrawing_data: Dict) -> Optional[str]:
        """备用：图纸编号提取逻辑"""
        bounds = subdrawing_data['bounds']
        texts = subdrawing_data['texts']

        filtered_texts = self._preprocess_texts(texts)
        if not filtered_texts:
            return None

        extraction_methods = [
            self._extract_from_explicit_labels,
            self._extract_from_key_positions,
            self._extract_from_pattern_matching,
        ]
        for method in extraction_methods:
            result = method(bounds, filtered_texts)
            if result and self._validate_drawing_number(result):
                return result
        return None

    def _preprocess_texts(self, texts: List) -> List:
        """文本预处理（过滤无效文本）"""
        content_frequency = Counter([text['content'].strip() for text in texts])
        processed = []
        for text in texts:
            content = text['content'].strip()
            layer = (text.get('layer') or '').lower()
            if not content or len(content) > 30:
                continue
            if layer not in {'0', 'dim', 'dimension'}:
                if any(term in content for term in self.excluded_terms):
                    continue
                if content in self.cad_annotations:
                    continue
                if len(content) <= 2 and content_frequency[content] > 5:
                    continue
                if self._is_dimension_or_value(content):
                    continue
            processed.append(text)
        return processed

    def _is_dimension_or_value(self, content: str) -> bool:
        """判断是否为尺寸/数值文本"""
        dimension_patterns = [
            r'^\d+\.?\d*$', r'^\d+\.?\d*[LWTHDRC]$', r'^Φ\d+\.?\d*$',
            r'^R\d+\.?\d*$', r'^\d+\.?\d*°$', r'^\d+\.?\d*mm$',
            r'^M\d+x\d+\.?\d*$', r'^\d+\.?\d*深$', r'^C\d+\.?\d*$'
        ]
        return any(re.match(pattern, content) for pattern in dimension_patterns)

    def _extract_from_explicit_labels(self, bounds: Dict, texts: List) -> Optional[str]:
        """从显式标签提取"""
        cand = self._extract_inline(texts, self.number_inline_res)
        if cand:
            return cand
        cand = self._extract_near_label(bounds, texts, self.number_label_only_res)
        if cand:
            return cand
        cand = self._extract_inline(texts, self.processing_inline_res)
        if cand:
            return cand
        cand = self._extract_near_label(bounds, texts, self.processing_label_only_res)
        if cand:
            return cand
        cand = self._extract_near_label_confirmed(bounds, texts, self.processing_label_anchor_res)
        if cand:
            return cand
        return None

    def _extract_from_key_positions(self, bounds: Dict, texts: List) -> Optional[str]:
        """从关键位置提取"""
        return self._extract_from_top_left(bounds, texts)

    def _extract_from_pattern_matching(self, bounds: Dict, texts: List) -> Optional[str]:
        """从正则模式提取"""
        if not texts:
            return None
        
        for t in texts:
            content = t.get('content', '').strip()
            for pattern in self.primary_patterns:
                match = re.search(pattern, content)
                if match:
                    cand = match.group(0)
                    if self._validate_drawing_number(cand):
                        return cand
        return None

    def _clean_candidate_after_label(self, s: str) -> str:
        """清洗提取到的候选文件名"""
        cleaned = (s or '').strip()
        if not cleaned:
            return cleaned
        
        match = re.match(r'^([A-Z0-9\-_]+)(?:\(|（)', cleaned)
        if match:
            cleaned = match.group(1)
        else:
            cleaned = cleaned.split()[0]
            cleaned = cleaned.strip('，,。.;；:：)]】）\'"').strip('([【（\'"')
        
        cleaned = re.sub(r'^[\s\-_]+|[\s\-_]+$', '', cleaned)
        return cleaned[:64] if len(cleaned) > 64 else cleaned

    def _validate_drawing_number(self, content: str) -> bool:
        """验证编号有效性"""
        if not content or len(content) > 50:
            return False
        try:
            normalized = self._normalize_confirmed_code(content)
            if normalized and normalized in self._extract_confirmed_codes_from_text(normalized):
                return True
        except Exception:
            pass
        invalid_patterns = [
            r'^[:：].*', r'.*[:：]\s*$', r'^\d+\.\d+$', r'^[0-9]{4,}$',
            r'.*说明.*', r'.*加工.*'
        ]
        if any(re.match(p, content) for p in invalid_patterns):
            return False
        valid_patterns = [
            r'^[A-Z]{1,4}[0-9]*$',
            r'^[A-Z]+[0-9]*(-[A-Z0-9]+)+$',
            r'^[A-Z]{2,4}$',
            r'^[A-Z0-9]+\([^)]+\)$',
        ]
        return any(re.match(p, content) for p in valid_patterns)

    def generate_safe_filename(self, name: str) -> str:
        """生成安全文件名"""
        if not name:
            return "未知编号"
        s = name.strip()
        match = re.match(r'^([^(]+)', s)
        if match:
            s = match.group(1).strip()
        if not s:
            s = name.strip()
        s = re.sub(r'[<>:"/\\|?*]', '_', s).replace(' ', '_')
        s = s.rstrip(' .')
        return s if len(s) <= 80 else s[:80]
