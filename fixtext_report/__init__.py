"""FixText V1.1 · 替换报告读取（E8 数据层）

把 V1 导出时落盘的「替换统计」报告（``<书名>替换统计.csv`` /
``<书名>替换统计.txt``）读成结构化结果，供界面（E9）直接消费。

**本模块只做数据层**：不 import Qt、不 import ``fixtext_ui``、
不 import ``fixtext_pipeline``，只依赖标准库，因此可以脱离界面独立测试。

对外三样东西::

    from fixtext_report import parse_report, parse_report_dir, Report

    rep = parse_report("炮火弧线替换统计.csv")
    if rep.ok:
        print(rep.title, rep.hits, rep.detail_rows)

    rep = parse_report_dir("/path/to/导出目录")     # 自动找同名报告

读不动的文件**不抛异常**：返回 ``ok=False`` 的报告，``issues`` 里逐条写明
「哪一行、缺什么、怎么处理了」。

口径提醒（重要）
----------------

* 报告**没有**按词库拆分命中数 → :meth:`Report.hits_by_library` 返回空列表，
  不要把它当成「每个词库命中 0 次」。
* 明细行 = 「改前片段 → 改后片段」+ 次数，可直接当「按规则」维度使用
  （同一处改前改后已合并、次数已累加）。
"""

from __future__ import annotations

from .model import (
    DETAIL_COLUMNS,
    FMT_CSV,
    FMT_TEXT,
    KEY_AUTHOR,
    KEY_GENERATED_AT,
    KEY_HITS,
    KEY_LIBRARIES,
    KEY_TITLE,
    LEVEL_INFO,
    LEVEL_WARNING,
    Issue,
    LibraryEntry,
    Report,
    Row,
    Section,
    summarize_libraries,
)
from .parser import ReportParseError, parse_csv_text, parse_report, parse_report_dir, parse_text_text
from .textread import read_text

__all__ = [
    # 入口
    "parse_report",
    "parse_report_dir",
    "parse_csv_text",
    "parse_text_text",
    "read_text",
    "ReportParseError",
    # 数据结构
    "Report",
    "Row",
    "Section",
    "LibraryEntry",
    "Issue",
    # 常量
    "FMT_CSV",
    "FMT_TEXT",
    "DETAIL_COLUMNS",
    "KEY_TITLE", "KEY_AUTHOR", "KEY_GENERATED_AT", "KEY_HITS", "KEY_LIBRARIES",
    "LEVEL_INFO", "LEVEL_WARNING",
    "summarize_libraries",
]
