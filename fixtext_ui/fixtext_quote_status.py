# -*- coding: utf-8 -*-
"""一键校正摘要 · 引号三分支文案（M4-EX.6-R3 / 原型 §7）。

关 →「检出引号问题 N 处」
开且 M>0 →「已自动修复 N 处，剩余 M 处待人工确认」+ 去检查页
开且 M=0 →「已自动修复 N 处」无按钮
"""

from __future__ import annotations

from typing import Any, Mapping


def quote_status_from_summary(
    summary: Mapping[str, Any] | None,
) -> tuple[str, bool, str]:
    """返回 ``(主文案, 是否显示「去检查页」, 提示短句)``。"""
    s = summary or {}
    auto = bool(s.get("auto_fix_quotes"))
    remaining = int(s.get("quote_errors") or 0)
    before = s.get("quote_errors_before")
    if before is None:
        before = remaining
    before = int(before or 0)
    fixed = s.get("quote_fixed")
    if fixed is None:
        fixed = max(0, before - remaining) if auto else 0
    fixed = int(fixed or 0)

    if not auto:
        text = f"检出引号问题 {before} 处"
        tip = "引号配对问题已检出，请在「检查问题」逐处人工确认。"
        return text, before > 0, tip

    if remaining > 0:
        text = f"已自动修复 {fixed} 处，剩余 {remaining} 处待人工确认"
        tip = "已自动修复可确定的引号配对问题，剩余项请在「检查问题」逐处确认。"
        return text, True, tip

    text = f"已自动修复 {fixed or before} 处"
    tip = "已自动修复可确定的引号配对问题。"
    return text, False, tip
