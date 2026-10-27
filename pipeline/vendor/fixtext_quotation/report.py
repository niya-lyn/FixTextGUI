"""报告生成：把 QuotationError 列表渲染为人类可读报告 / JSON。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from .checker import QuotationError

FETCH_CONTEXT_LINES = 2  # 对齐原版 FETCH_CONTEX_LINES


def render_report(file_path: str, text: str, errors: List[QuotationError]) -> str:
    """按原版报告风格渲染单文件检查报告。

    结构对齐原版 dumpErr 输出的信息要素：报错信息 / 文件名 / 当前进度（行号）/ 原文上下文。
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    total = len(lines) or 1

    out = []
    out.append(f"文件名：《{Path(file_path).name}》")
    out.append(f"总行数：{total}")
    out.append(f"引号错误段落：共 {len(errors)} 处")
    out.append("")
    if not errors:
        out.append("（未检出引号错误）")
        return "\n".join(out)

    for idx, err in enumerate(errors, 1):
        prev_n = FETCH_CONTEXT_LINES
        prev_nk = max(err.line - 1 - prev_n, 0)
        ctx_lines = lines[prev_nk : err.line - 1 + prev_n + 1]
        # 标记报错行
        err_rel = err.line - 1 - prev_nk
        marked = []
        for j, ln in enumerate(ctx_lines):
            prefix = "【报错段落】" if j == err_rel else "               "
            marked.append(prefix + ln)
        out.append(f"======= ↓↓↓ 第 {idx} 处 =======")
        out.append(f"报错信息：！！{err.msg}！！")
        out.append(f"所在行：第 {err.line} 行（行内字符下标 {err.char}）")
        out.append("原文内容如下：")
        out.extend(marked)
        out.append(f"======= ↑↑↑ 第 {idx} 处结束 =======")
        out.append("")
    return "\n".join(out)


def render_json(file_path: str, errors: Iterable[QuotationError]) -> str:
    """机器可读 JSON（与等价性比对所用的 events 结构一致）。"""
    return json.dumps(
        {
            "file": Path(file_path).name,
            "errCount": len(list(errors)),
            "events": [e.to_dict() for e in errors],
        },
        ensure_ascii=False,
    )
