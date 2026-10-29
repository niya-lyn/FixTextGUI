"""生僻字注音文本后处理（M5-EX.1）。

在注音袋替换（count=1）之后，按 PHP ZhuyinProcessor 对齐的四档语义整理正文：
去相邻重复注音 → 仅注一次 → 取第一读音。本卡不做「多音字拆分」。
"""

from __future__ import annotations

import re
from typing import Any

#: 与 PHP ZhuyinProcessor 拼音字符集同向的宽松块
_PINYIN_BLOCK = r"\[[^\[\]]+\]"
_RE_ANNOT = re.compile(rf"([\u4e00-\u9fff])({_PINYIN_BLOCK})")
_RE_DUP = re.compile(rf"({_PINYIN_BLOCK})(?:\1)+")
_RE_FIRST = re.compile(r"\[([^\[\]]*?)(?:\s*或\s*[^\[\]]*)+\]")


def clear_repeated_zhuyin(text: str) -> tuple[str, int]:
    """相邻相同 ``[音][音]`` → 保留一个（等价 PHP clearRepeatedZhuyin 取后者形态）。"""
    n = 0

    def _sub(m: re.Match[str]) -> str:
        nonlocal n
        block = m.group(1)
        whole = m.group(0)
        reps = len(whole) // len(block)
        n += max(0, reps - 1)
        return block

    return _RE_DUP.sub(_sub, text), n


def keep_first_only(text: str) -> tuple[str, int]:
    """同一汉字全书只保留首次注音。"""
    seen: set[str] = set()
    dropped = 0

    def _sub(m: re.Match[str]) -> str:
        nonlocal dropped
        ch, block = m.group(1), m.group(2)
        if ch in seen:
            dropped += 1
            return ch
        seen.add(ch)
        return ch + block

    return _RE_ANNOT.sub(_sub, text), dropped


def extract_first_reading(text: str) -> tuple[str, int]:
    """``[音1 或 音2]`` → ``[音1]``。"""
    n = 0

    def _sub(m: re.Match[str]) -> str:
        nonlocal n
        n += 1
        return f"[{m.group(1).strip()}]"

    return _RE_FIRST.sub(_sub, text), n


def apply(text: str, mode: str) -> tuple[str, dict[str, Any]]:
    """mode: ``0`` 仅一次 / ``1`` 所有位置 / ``2`` 仅一次+首音 / ``3`` 所有+首音。"""
    mode = str(mode)
    report: dict[str, Any] = {"mode": mode}
    text, n_dup = clear_repeated_zhuyin(text)
    report["removed_duplicates"] = n_dup
    if mode in ("0", "2"):
        text, n_once = keep_first_only(text)
        report["dropped_repeats"] = n_once
    else:
        report["dropped_repeats"] = 0
    if mode in ("2", "3"):
        text, n_first = extract_first_reading(text)
        report["first_reading_stripped"] = n_first
    else:
        report["first_reading_stripped"] = 0
    return text, report
