"""V1.1-D1 · 分隔符与引号规则的判定。

从 Excel / 在线表格复制出来的文本，分隔符取决于源表格的保存格式：

* Excel 复制单行多列 → **制表符**（`\\t`）；
* Excel 另存 CSV → **逗号**；
* WPS / 部分在线表格 → 逗号或制表符；
* 中文输入法手打的「表格」→ 偶尔是**全角逗号**或**分号**。

判定原则：**用「每列都一致的列数」投票，而不是猜哪一种更像**。
理由是——错误的判定会让整张表的列数参差不齐（这就是用户在预览里
一眼看到的「错位」）；正确的判定会让绝大多数行的列数相同。
所以「列数一致性」是最稳的证据，且完全可复算、不含随机。

引号规则单独处理：标准 CSV 里 `"a,b"` 是一个字段，不是两个。
但原版导出（见 `escape.py`）**从不输出引号包裹**——它把逗号换成中文标记，
所以 CSV 里不存在需要引号保护的字段。两种规则都要支持：
先按标准 CSV 引号规则切，若整表列数不齐再退回「不认引号、只切分隔符」，
因为用户手写的 txt 里引号常是正文的一部分。
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from io import StringIO

#: 候选分隔符，按「出现成本」排序：先试最可能是结构性分隔的。
#: 单列纯文本（一行一个词条）不在此列——那是「无分隔符」的特例，单独处理。
CANDIDATE_DELIMITERS: tuple[str, ...] = ("\t", ",", ";", "|", "，", "、")

#: 判定这些分隔符时是否认标准 CSV 引号规则。
#: 制表符 / 全角标点不可能出现在标准 CSV 的引号语义里，但对用户手写文本
#: 认引号会让 `"他说，你好"` 被当成一个字段——所以这两类默认不认引号。
QUOTE_AWARE_DELIMITERS: frozenset[str] = frozenset({",", ";", "|"})

#: 至少要有这么多行，投票才有意义（1 行无法区分「1 列」和「分隔符没生效」）
MIN_ROWS_FOR_VOTE = 2


@dataclass
class DelimiterGuess:
    """分隔符判定结论与依据。"""

    delimiter: str | None               # None = 判定为「单列 / 无分隔符」
    confidence: str                     # tab-vote | single-column | uniform | fallback
    rows: int                           # 参与投票的数据行数
    column_count: int                   # 该分隔符下的众数列数
    consistency: float                  # 众数列数占参与行的比例
    quote_aware: bool = False
    evidence: list[str] = field(default_factory=list)

    @property
    def is_single_column(self) -> bool:
        return self.delimiter is None


def _split_line(line: str, delimiter: str, quote_aware: bool) -> list[str]:
    if not quote_aware:
        return line.split(delimiter)
    reader = csv.reader(StringIO(line), delimiter=delimiter, quotechar='"',
                        doublequote=True, skipinitialspace=False)
    try:
        return next(reader)
    except (StopIteration, csv.Error):
        return line.split(delimiter)


def _vote(lines: list[str], delimiter: str, quote_aware: bool) -> tuple[int, float, int]:
    """返回 (众数列数, 一致比例, 众数出现行数)。"""
    counts: list[int] = []
    for line in lines:
        counts.append(len(_split_line(line, delimiter, quote_aware)))
    if not counts:
        return 0, 0.0, 0
    tally: dict[int, int] = {}
    for n in counts:
        tally[n] = tally.get(n, 0) + 1
    mode_cols = max(tally, key=lambda k: (tally[k], k))
    return mode_cols, tally[mode_cols] / len(counts), tally[mode_cols]


def _sample_lines(text: str, limit: int = 50) -> list[str]:
    """取前若干**非空**行参与投票（空行不携带分隔符信息）。"""
    out: list[str] = []
    for line in text.splitlines():
        if line.strip():
            out.append(line)
            if len(out) >= limit:
                break
    return out


_QUOTED_CHUNK = re.compile(r'"[^"]*"')


def has_unclosed_quote(line: str) -> bool:
    """这一行是否有落单的引号（跨行字段被换行打断的典型征兆）。"""
    return line.count('"') % 2 == 1


def guess_delimiter(text: str) -> DelimiterGuess:
    """判定分隔符。结论附带证据，供预览页直接展示。"""
    lines = _sample_lines(text)
    if not lines:
        return DelimiterGuess(
            delimiter=None, confidence="single-column", rows=0, column_count=0,
            consistency=0.0, evidence=["没有可解析的内容，按单列处理"],
        )

    evidence: list[str] = []

    # 单行文本：只有一个非空行时，无法靠列数一致性区分。
    # 这时按「分隔符是否真的出现」判断，并把置信度标成 fallback（上层会提示）。
    if len(lines) < MIN_ROWS_FOR_VOTE:
        line = lines[0]
        for delim in CANDIDATE_DELIMITERS:
            if delim in line:
                cols = len(_split_line(line, delim, delim in QUOTE_AWARE_DELIMITERS))
                evidence.append(
                    f"只有一行内容，按出现的分隔符判定为"
                    f"{_delimiter_name(delim)}（{cols} 列）"
                )
                return DelimiterGuess(
                    delimiter=delim, confidence="fallback", rows=1,
                    column_count=cols, consistency=1.0,
                    quote_aware=delim in QUOTE_AWARE_DELIMITERS,
                    evidence=evidence,
                )
        return DelimiterGuess(
            delimiter=None, confidence="single-column", rows=1, column_count=1,
            consistency=1.0, evidence=["只有一行内容，且没有出现任何常见分隔符，按单列处理"],
        )

    # 制表符优先：从 Excel 复制来的文本几乎必然带制表符，
    # 而正文里出现制表符的概率远低于逗号——先判它可避免被正文逗号带偏。
    tab_cols, tab_cons, tab_hits = _vote(lines, "\t", quote_aware=False)
    if tab_cols >= 2 and tab_cons >= 0.9:
        evidence.append(
            f"每行都用制表符分开，{tab_hits}/{len(lines)} 行的列数一致（{tab_cols} 列）"
        )
        return DelimiterGuess(
            delimiter="\t", confidence="tab-vote", rows=len(lines),
            column_count=tab_cols, consistency=tab_cons, evidence=evidence,
        )

    # 其余候选按「一致比例」再按「列数」排序
    best: tuple[float, int, str, bool] | None = None
    for delim in CANDIDATE_DELIMITERS:
        if delim == "\t":
            continue
        qa = delim in QUOTE_AWARE_DELIMITERS
        cols, cons, _hits = _vote(lines, delim, qa)
        if cols < 2:
            continue
        key = (cons, cols, delim, qa)
        if best is None or (key[0], key[1]) > (best[0], best[1]):
            best = key

    if best is None:
        evidence.append(
            f"{len(lines)} 行内容里没有任何常见分隔符，按单列处理（一行一个词条）"
        )
        return DelimiterGuess(
            delimiter=None, confidence="single-column", rows=len(lines), column_count=1,
            consistency=1.0, evidence=evidence,
        )

    cons, cols, delim, qa = best
    if cons >= 0.9:
        evidence.append(
            f"按{_delimiter_name(delim)}切分时，{int(cons * len(lines))}/{len(lines)} "
            f"行的列数一致（{cols} 列）"
        )
        confidence = "uniform"
    else:
        evidence.append(
            f"按{_delimiter_name(delim)}切分时列数最整齐，但只有 {cons:.0%} 的行一致"
            f"（{cols} 列）；表格里可能有跨行内容，需要你确认列映射"
        )
        confidence = "fallback"
    return DelimiterGuess(
        delimiter=delim, confidence=confidence, rows=len(lines),
        column_count=cols, consistency=cons, quote_aware=qa, evidence=evidence,
    )


_DELIMITER_NAMES = {
    "\t": "制表符",
    ",": "逗号",
    ";": "分号",
    "|": "竖线",
    "，": "全角逗号",
    "、": "顿号",
}


def _delimiter_name(delim: str) -> str:
    """分隔符的人话名字（写进证据串，供预览页展示）。"""
    return _DELIMITER_NAMES.get(delim, delim)


def delimiter_name(delim: str | None) -> str:
    """对外的分隔符人话名。"""
    if delim is None:
        return "无分隔符（单列）"
    return _delimiter_name(delim)
