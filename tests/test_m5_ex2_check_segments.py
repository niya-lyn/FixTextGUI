"""M5-EX.2 / BUG-5：检查页三段上下文。"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for _p in (PKG, PKG / "fixtext_ui"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_segments_from_lines_list():
    from fixtext_check import attach_segments, segments_from_lines

    lines = ["前一段文字", "问题段“缺右", "后一段文字"]
    before, problem, after, has_b, has_a = segments_from_lines(lines, 2)
    assert before == "前一段文字"
    assert problem.startswith("问题段")
    assert after == "后一段文字"
    assert has_b and has_a

    item = dict(line=2, pre="", hl="“", post="")
    attach_segments(item, lines)
    assert item["seg_before"] == "前一段文字"
    assert item["has_before"] is True
    assert item["has_after"] is True


def test_segments_edges():
    from fixtext_check import segments_from_lines

    lines = ["仅一行"]
    b, p, a, has_b, has_a = segments_from_lines(lines, 1)
    assert b == "" and p == "仅一行" and a == ""
    assert has_b is False and has_a is False


def test_attach_segments_dict_neighbors():
    from fixtext_check import attach_segments

    lines = {1: "A", 2: "B缺右", 3: "C"}
    item = dict(line=2)
    attach_segments(item, lines)
    assert item["seg_before"] == "A"
    assert item["seg_problem"] == "B缺右"
    assert item["seg_after"] == "C"


def test_editor_roundtrip_split_write():
    """模拟编辑器三段空行分隔 → 回写对应行号。"""
    from fixtext_check import attach_segments

    lines = ["前段", "中段“", "后段"]
    item = dict(line=2, pre="中段", hl="“", post="")
    attach_segments(item, lines)
    prefix = f"L{item['line']}   "
    body = f"{item['seg_before']}\n\n{item['seg_problem']}\n\n{item['seg_after']}"
    text = prefix + body
    raw = text.split("   ", 1)[-1]
    parts = raw.split("\n\n", 2)
    assert parts == ["前段", "中段“", "后段"]

    # 用户改了问题段
    parts[1] = "中段“补全”"
    updates = {2: parts[1], 1: parts[0], 3: parts[2]}
    out = list(lines)
    for ln, val in updates.items():
        out[ln - 1] = val
    assert out == ["前段", "中段“补全”", "后段"]
