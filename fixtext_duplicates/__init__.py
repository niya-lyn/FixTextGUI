"""FixText V1.1 · 重复段落检测（E6 数据层）

**这个模块只做数据层，不含任何界面代码**：不 import Qt、不 import
``fixtext_ui``、不 import ``fixtext_pipeline``。E7（清单与处置）拿
:class:`~fixtext_duplicates.model.DuplicateReport` / ``.payload()`` 即可渲染，
本卡不提供界面。

对外三样东西：

* :func:`~fixtext_duplicates.engine.detect` —— 段落序列 → 检测报告
* :func:`~fixtext_duplicates.engine.detect_text` —— 正文文本 → 检测报告
* :func:`~fixtext_duplicates.engine.detect_file` —— ``book.txt`` → 检测报告

以及段落切分 :func:`~fixtext_duplicates.extract.extract_paragraphs` /
``extract_from_file``，和数据结构 :class:`DuplicateReport` /
:class:`DuplicateGroup` / :class:`DuplicatePair` / :class:`ParagraphRef`。
"""

from __future__ import annotations

from .engine import (DEFAULT_ADJACENT_WINDOW, DetectOptions, detect,
                     detect_file, detect_text)
from .extract import (ChapterSpan, ExtractResult, extract_from_file,
                      extract_paragraphs, has_bundle_header)
from .model import (EXCERPT_CHARS, KIND_EXACT, KIND_NAMES, KIND_SIMILAR,
                    ORDER_BY_COUNT, ORDER_BY_POSITION, ORDER_BY_SIMILARITY,
                    ORDER_NAMES, DuplicateGroup, DuplicatePair,
                    DuplicateReport, ParagraphRef, group_by_chapters,
                    pairs_from_reports)
from .similarity import (DEFAULT_MIN_CHARS, containment_of, core_length,
                         max_length_ratio, normalize, shared_bigram_floor,
                         similarity_of)

__all__ = [
    # 算法
    "DetectOptions", "detect", "detect_text", "detect_file",
    "DEFAULT_MIN_CHARS", "DEFAULT_ADJACENT_WINDOW",
    # 切段
    "extract_paragraphs", "extract_from_file", "has_bundle_header",
    "ExtractResult", "ChapterSpan",
    # 数据结构
    "DuplicateReport", "DuplicateGroup", "DuplicatePair", "ParagraphRef",
    "KIND_EXACT", "KIND_SIMILAR", "KIND_NAMES",
    "ORDER_BY_COUNT", "ORDER_BY_POSITION", "ORDER_BY_SIMILARITY", "ORDER_NAMES",
    "EXCERPT_CHARS", "group_by_chapters", "pairs_from_reports",
    # 相似度
    "similarity_of", "containment_of", "core_length", "normalize",
    "shared_bigram_floor", "max_length_ratio",
    "shared_bigram_floor", "max_length_ratio",
]
