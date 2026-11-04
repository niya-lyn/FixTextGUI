"""V1.1-D1 · 原版非标准转义的还原与生成。

原版把 CSV 里会破坏列结构的四个字符，换成了以【】包裹的中文标记
（`FixText/src/app/Service/Csv.php:20-26`，逐字抄录如下，顺序即原版数组顺序）：

    ","  => "【英文逗号】"
    "'"  => "【英文单引号】"
    "\"" => "【英文双引号】"
    "\n" => "【换行符】"

原版的还原动作是**一次** `str_replace(array_values, array_keys, $line)`
（`Csv.php:96-100`）。本模块把这套规则做成可复算的 Python 实现，并明确
「一次性还原」的技术含义——这是本卡验收判据的核心，不是修辞：

1. **必须单趟扫描**。四个标记互不相同，且替换目标（`,` `'` `"` `\n`）里
   不含任何标记，所以单趟等价于顺序替换；但**一旦以后表里新增了
   「替换文本中包含另一个标记」的条目，顺序替换就会级联放大**。
   本实现用一条正则分支（长的优先）单趟替换，从机制上不可能级联——
   单测里用一张「人为构造的级联表」验证顺序替换会错、单趟不会。
2. **必须先切列、再还原**。还原会把 `【英文逗号】` 变回 `,`，而 `,` 正是
   隔开两列的分隔符。若先还原再切列，一个值里的逗号就会被当成列边界，
   原本 2 列被切成 3 列，值被截断。原版正是「先 explode 再替换」。
   单测里保留一个对比实现，证明反着做会出错。
3. **还原是有损的（必须告知用户）**。如果用户的词条里本来就有字面量
   `【英文逗号】`，还原后无法区分它原本是五个汉字还是一枚逗号。
   原版同样无法区分。本模块不假装能分辨，只把次数报出来让人可复核。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

#: 原版 `Csv::$csvEscapedChars` 的等价表：``(原字符, 占位标记)``，顺序与原版一致。
CSV_ESCAPED_CHARS: tuple[tuple[str, str], ...] = (
    (",", "【英文逗号】"),
    ("'", "【英文单引号】"),
    ('"', "【英文双引号】"),
    ("\n", "【换行符】"),
)

#: 标记 → 原字符
MARKER_TO_CHAR: dict[str, str] = {m: c for c, m in CSV_ESCAPED_CHARS}

#: 原字符 → 标记
CHAR_TO_MARKER: dict[str, str] = {c: m for c, m in CSV_ESCAPED_CHARS}


def _build_pattern(markers: Iterable[str]) -> re.Pattern[str]:
    """把一组标记编成单趟正则：**长的先试**，避免短标记吃掉长标记的前缀。"""
    ordered = sorted(set(markers), key=len, reverse=True)
    return re.compile("|".join(re.escape(m) for m in ordered))


_RESTORE_PATTERN = _build_pattern(MARKER_TO_CHAR)
_ESCAPE_PATTERN = _build_pattern(CHAR_TO_MARKER)


def contains_escaped_markers(text: str) -> bool:
    """这段文本里是否出现了原版占位标记（用于提示「这条是原版格式」）。"""
    if not text:
        return False
    return bool(_RESTORE_PATTERN.search(text))


@dataclass
class RestoreReport:
    """一次还原的可复核账目。"""

    text: str
    replaced: int                       # 命中并替换的标记个数
    counts: dict[str, int]              # 每个标记各还原了几个

    @property
    def touched(self) -> bool:
        return self.replaced > 0


def restore_escaped_once(
    text: str,
    *,
    table: Sequence[tuple[str, str]] | None = None,
) -> RestoreReport:
    """**单趟**把【英文逗号】等标记还原成原字符。

    只对**已经切好的单个字段**调用——这是本模块对调用方的硬约束，
    原因见模块头第 2 条：还原出的逗号会冒充列分隔符。

    :param table: 仅测试用（验证「级联表」下顺序替换会出错）；生产调用留空。
    """
    if not text:
        return RestoreReport(text="", replaced=0, counts={})

    if table is None:
        mapping, pattern = MARKER_TO_CHAR, _RESTORE_PATTERN
    else:
        mapping = {m: c for c, m in table}
        pattern = _build_pattern(mapping)

    counts: dict[str, int] = {}

    def _sub(match: re.Match[str]) -> str:
        marker = match.group(0)
        counts[marker] = counts.get(marker, 0) + 1
        return mapping[marker]

    restored = pattern.sub(_sub, text)
    return RestoreReport(
        text=restored, replaced=sum(counts.values()), counts=counts,
    )


def escape_escaped(
    text: str,
    *,
    table: Sequence[tuple[str, str]] | None = None,
) -> str:
    """反向：把原字符换成标记（D7 导出用；本卡只用于往返自证）。

    与原版一致——标记里不含原字符，所以单趟不会自我递归。
    """
    if not text:
        return ""
    if table is None:
        char_to_marker, pattern = CHAR_TO_MARKER, _ESCAPE_PATTERN
    else:
        char_to_marker = {c: m for c, m in table}
        pattern = _build_pattern(char_to_marker)
    return pattern.sub(lambda m: char_to_marker[m.group(0)], text)


def restore_field_without_split(text: str) -> RestoreReport:
    """**故意做错的对照组**：不切列就直接还原。

    仅供单测证明「先切列再还原」是必要的；生产代码不得调用（见模块头第 2 条）。
    """
    return restore_escaped_once(text)


#: 单测用的「会级联的表」：某个标记还原出来的文本**本身又是另一个标记**。
#: 顺序替换会先把它还原成 `【逗号】`、再被下一条规则啃成 `B`；单趟替换不会。
#: 注意：**真实的原版表不会级联**（`【英文逗号】` 等四个标记还原成 `, ' " \n`，
#: 都不构成任何标记），这条只用于证明本实现不会被未来的表改动带坏，
#: 不代表原版有 bug。
CASCADING_TABLE: tuple[tuple[str, str], ...] = (
    ("【逗号】", "【A】"),      # 先插入的标记，还原后得到「【逗号】」
    ("B", "【逗号】"),          # 这条会把上一步的结果再啃一遍
)


def sequential_restore_for_test(text: str, table: Sequence[tuple[str, str]]) -> str:
    """**顺序替换的对照组**（完全照原版 `str_replace(array_values, array_keys)` 的写法）。

    只用于单测对比：在会级联的表上它会产出错的结果，单趟实现不会。
    """
    mapping = {m: c for c, m in table}
    out = text
    for marker in mapping:                       # 逐个标记依次替换
        out = out.replace(marker, mapping[marker])
    return out


def sequential_escape_for_test(text: str, table: Sequence[tuple[str, str]]) -> str:
    """顺序替换版的反向（导出方向）对照组，同样只用于单测。"""
    out = text
    for char, marker in table:
        out = out.replace(char, marker)
    return out
