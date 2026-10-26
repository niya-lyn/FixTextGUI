# -*- coding: utf-8 -*-
"""
T1.6 · FixText NoteParser 的 Python 等价管线（对比验证用 + 引擎接入辅助）

复刻范围：FixText/src/app/Service/Note/NoteParser.php 的完整公开行为
  normalizeContent / extractMatches / processBrandSpecificMatches / cleanMatches / parseFileContent

品牌闭包本身在 note_brand_processors.py（本包核心交付物）；本文件只负责把它们放进管线，
保证与 PHP 侧 end-to-end 可对照。noteMatchPatterns 优先从 T0.2 迁移产物 JSON 加载，
无 JSON 时使用内嵌等价翻译（含 \d→[0-9] 的 PCRE 语义对齐，见下方说明）。

PCRE → Pythonre 对齐说明（noteMatchPatterns 9 条）：
  1. PHP 侧统一拼为 "/{$pattern}/ums"：u=UTF-8、m=MULTILINE、s=DOTALL
     ⇒ Python 统一 flags=re.M | re.S（对无锚点模式 M 是 no-op，与 PHP 一致地"无效果"）。
  2. PHP /u 且未开 PCRE_UCP：\d 只匹配 ASCII 数字；Python \d 匹配全部 Unicode 十进制数字。
     为逐字节等价，翻译时把 `\d` 显式替换为 `[0-9]`。
  3. `\/`（JSON 中来自 PHP 双引号串的 `\/`，PCRE 转义斜杠）= 字面斜杠，Python re 同义，保留。
  4. PHP str_replace 在单引号串中 '\n' 是"反斜杠+n"字面量 ⇒ normalize_content 中按字面量处理。
  5. Python 正则无回溯上限（PHP PCRE 有 pcre.backtrack_limit），对大文本上"必然不命中"的模式
     用**必现字面量**短路（REQUIRED_LITERALS）：模式缺少该字面量时数学上不可能命中，跳过不影响
     结果；PHP 侧不受此影响（harness 用真实 NoteParser）。这是纯性能短路，语义等价。
"""

import re
from note_brand_processors import NOTE_BRAND_PROCESSORS

__all__ = [
    "NoteParseError",
    "normalize_content",
    "NOTE_MATCH_PATTERNS",
    "REQUIRED_LITERALS",
    "extract_matches",
    "clean_matches",
    "parse_file_content",
    "strip_trailing_missing",
]


class NoteParseError(Exception):
    """等价 PHP App\Exception\AppException("未找到匹配的批注内容")"""

    def __init__(self):
        super().__init__("未找到匹配的批注内容")


# ── noteMatchPatterns：PCRE 原文与 Python 翻译对照 ──────────────────────────────
# pcre = T0.2 导出（build/exported/.._config_general.php.__return__.json）里的原文；
# py    = 按"模块头说明 2"翻译后的 Python 正则（唯一差异：\d → [0-9]）。
_RAW_PATTERNS = {
    "boox":       (r"^\d{4}-\d{2}-\d{2}.*?\n(.*?)(?:\n【批注】(.*?))?\n----------",
                   r"^[0-9]{4}-[0-9]{2}-[0-9]{2}.*?\n(.*?)(?:\n【批注】(.*?))?\n----------"),
    "ireader":    (r"^\d{4}-\d{2}-\d{2}.*?\n原文：(.*?)\n想法：(.*?)\n\n",
                   r"^[0-9]{4}-[0-9]{2}-[0-9]{2}.*?\n原文：(.*?)\n想法：(.*?)\n\n"),
    "legado":     (r'"bookText": "(.*?)",\n.*?"content": "(.*?)",\n',
                   r'"bookText": "(.*?)",\n.*?"content": "(.*?)",\n'),
    "duokan":     (r" \d{4}-\d{2}-\d{2}\n(.*?)(?:\n注: (.*?))?(?=\n\n| \d{4}-\d{2}-\d{2}\n|\n+<EOF>)",
                   r" [0-9]{4}-[0-9]{2}-[0-9]{2}\n(.*?)(?:\n注: (.*?))?(?=\n\n| [0-9]{4}-[0-9]{2}-[0-9]{2}\n|\n+<EOF>)"),
    "moonreader": (r"▪ (.*?)(?=▪ |\n+<EOF>)",
                   r"▪ (.*?)(?=▪ |\n+<EOF>)"),
    "calibre":    (r"^(.*?)(?:\n\d{4}\/\d{1,2}\/\d{1,2}.*?\n(.*?))?\n───",
                   r"^(.*?)(?:\n[0-9]{4}\/[0-9]{1,2}\/[0-9]{1,2}.*?\n(.*?))?\n───"),
    "weread":     (r"◆ .*?(?=◆ |-- 来自微信读书)",
                   r"◆ .*?(?=◆ |-- 来自微信读书)"),
    "foliate":    (r'"text": "(.*?)",\n.*?"note": "(.*?)",\n',
                   r'"text": "(.*?)",\n.*?"note": "(.*?)",\n'),
    "reeden":     (r"笔记内容: (.*?)\n备注: (.*?)\n创建时间: ",
                   r"笔记内容: (.*?)\n备注: (.*?)\n创建时间: "),
}

NOTE_MATCH_PATTERNS = {brand: re.compile(py, re.M | re.S) for brand, (_pcre, py) in _RAW_PATTERNS.items()}

# 必现字面量短路（模块头说明 5）：模式缺少该子串时不可能命中。键为字面量**必须**出现的子串。
REQUIRED_LITERALS = {
    "boox": ["\n----------"],
    "ireader": ["原文：", "想法："],
    "legado": ['"bookText": "'],
    "duokan": [],  # 前缀为 " +日期，非单一字面量；线性扫描无回溯爆炸，无需短路
    "moonreader": ["▪ "],
    "calibre": ["\n───"],
    "weread": ["◆ "],
    "foliate": ['"text": "'],
    "reeden": ["笔记内容: "],
}


def normalize_content(content):
    # PHP NoteParser::normalizeContent
    #   $content = str_replace(["\r\n", "\r"], "\n", $content);
    #   $content = str_replace(['\n　　', '\n  '], '\n', $content);   ← 单引号！字面量 反斜杠+n
    #   return $content . "\n<EOF>";
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    # PHP 单引号 '\n' 是两个字符（反斜杠+n），故这里用 "\\n" 字面量，逐字对齐
    content = content.replace("\\n　　", "\\n").replace("\\n  ", "\\n")
    return content + "\n<EOF>"


def extract_matches(content, with_brand=False):
    """等价 PHP NoteParser::extractMatches + processBrandSpecificMatches：
    依序尝试各品牌模式，首个命中者胜出并执行品牌闭包。返回 (brand, matches) 或 (None, [])。"""
    normalized = normalize_content(content)
    for brand, regex in NOTE_MATCH_PATTERNS.items():
        if any(lit not in normalized for lit in REQUIRED_LITERALS[brand]):
            continue  # 必现字面量缺失 ⇒ 必然不命中（性能短路，语义等价）
        found = []
        for m in regex.finditer(normalized):
            row = [m.group(0)]
            for i in range(1, regex.groups + 1):
                row.append(m.group(i))  # 未参与的捕获组 = None（等价 PHP 缺键）
            found.append(row)
        if found:
            processor = NOTE_BRAND_PROCESSORS.get(brand)
            if processor is not None:
                processor(found)
            return (brand, found) if with_brand else found
    return (None, []) if with_brand else []


def clean_matches(matches):
    # PHP NoteParser::cleanMatches
    #   $match[1] = trim($match[1], "\n");
    #   $match[1] = preg_replace('/^[ 　]*$\n/um', '', $match[1]);
    #   if (isset($match[2]) && $match[2]) { 同上两步 }
    _blank_line = re.compile(r"^[ 　]*$\n", re.M)
    for match in matches:
        match[1] = match[1].strip("\n")
        match[1] = _blank_line.sub("", match[1])
        v2 = match[2] if len(match) > 2 else None
        if v2:  # isset($match[2]) && $match[2]：缺失或空串都不处理
            match[2] = v2.strip("\n")
            match[2] = _blank_line.sub("", match[2])
    return matches


def parse_file_content(content):
    """等价 PHP NoteParser::parseFileContent：返回清理后的 matches；无命中抛 NoteParseError。"""
    matches = extract_matches(content)
    if not matches:
        raise NoteParseError()
    return clean_matches(matches)


def strip_trailing_missing(row):
    """把 Python 行尾的 None（PHP 缺键）剥掉，序列化后与 PHP json_encode 数组结构一致。"""
    out = list(row)
    while out and out[-1] is None:
        out.pop()
    return out


def py_pipeline_report(content):
    """T1.6 对比 harness 用：一次跑出三阶段结构，与 PHP 侧 harness 的 JSON 同构。
    stage1_raw = 正则提取后（未跑闭包）；stage2 = 闭包处理后；stage3 = cleanMatches 后。"""
    normalized = normalize_content(content)
    brand = None
    raw = []
    for b, regex in NOTE_MATCH_PATTERNS.items():
        if any(lit not in normalized for lit in REQUIRED_LITERALS[b]):
            continue
        rows = []
        for m in regex.finditer(normalized):
            row = [m.group(0)]
            for i in range(1, regex.groups + 1):
                row.append(m.group(i))
            rows.append(row)
        if rows:
            brand, raw = b, rows
            break
    if not raw:
        return {"ok": False, "__exception__": "未找到匹配的批注内容"}

    stage2 = [list(r) for r in raw]
    processor = NOTE_BRAND_PROCESSORS.get(brand)
    if processor is not None:
        processor(stage2)
    stage3 = clean_matches([list(r) for r in stage2])

    return {
        "ok": True,
        "brand": brand,
        "stage1_raw": [strip_trailing_missing(r) for r in raw],
        "stage2_after_processor": [strip_trailing_missing(r) for r in stage2],
        "stage3_final": [strip_trailing_missing(r) for r in stage3],
    }
