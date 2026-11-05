"""FixText V1.1-E8 · 替换报告的数据结构（供界面与后续卡片消费）

E8 的产出是**纯数据层**：把 V1 导出时落盘的「替换统计」报告读成结构化结果，
后续卡片（E9 界面呈现）直接拿这里的对象渲染，不再自己解析文本。

设计要点
--------

1. **只描述报告里真实存在的东西。** 报告本身给的是：书名 / 作者 / 生成时间 /
   命中数 / 涉及词库清单 + 一张「改前 → 改后 → 替换次数」的明细表。
   它**没有**按词库拆分命中数，所以本模块的 ``hits_by_library`` 一律返回
   空列表 + 一条说明，绝不按比例摊派或猜一个数出来。
2. **明细行就是「按规则汇总」**（同一处改前改后合并成一条、次数已累加），
   所以 ``rows`` 可直接当规则维度来用，另附排序 / 取前 N / 次数分布。
3. **两处口径互相对账。** 报告在「命中数」和「明细次数合计」两处写了同一个量，
   本模块把它算出来比对，不一致就出一条人话提示（两个数都保留，不擅自取一个）。
4. 全部结构可序列化（``to_dict``），字段只用 ``int`` / ``str`` / ``bool`` /
   ``list`` / ``dict``，落盘后能原样重建。
5. 本模块**不导入 Qt、不导入界面层、不导入 pipeline**：只依赖标准库。

为什么不做「按词库归因」
------------------------

实测（《炮火弧线》788 章真实报告，2477 条明细）：明细行是**带上下文的差异
片段**（如「，长长的叹了口 → ，长长地叹了口」），不是词库里的原始词条。拿出厂
词库做「改前改后全等匹配」命中 0 条；用子串回溯能覆盖 97.5%，但属于推断，
而且本书专有词库是在替换**之后**才提取的（05 阶段），那次运行里根本没参与替换。
把推断结果当成「这个词库命中 N 次」会给出一个看起来精确、实际不成立的数字，
所以这里只做报告本身能支撑的汇总。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

#: 报告形态
FMT_CSV = "csv"
FMT_TEXT = "text"

#: 明细表的三列表头（CSV 形态）
DETAIL_COLUMNS = ("改前", "改后", "替换次数")

#: 报告里的字段名（CSV 的键值区第一列 / TXT 的「字段：值」左侧）
KEY_TITLE = "书名"
KEY_AUTHOR = "作者"
KEY_GENERATED_AT = "生成时间"
KEY_HITS = "命中数"
KEY_LIBRARIES = "涉及词库"

#: 提示级别
LEVEL_WARNING = "warning"
LEVEL_INFO = "info"


@dataclass
class Issue:
    """一条读取过程中的提示（人话，可逐条给界面看）。

    ``line_no`` 为 ``None`` 表示与具体行无关（比如整份报告的字段缺失）。
    """

    level: str
    code: str
    message: str
    line_no: int | None = None
    #: 技术细节（进日志 / 证据，界面不展示）
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "line_no": self.line_no,
            "detail": self.detail,
        }


@dataclass
class LibraryEntry:
    """报告「涉及词库」里的一条。

    报告把每个词库写成一句人话，例如::

        通用校对词库（本次应用规则 151192 条，去重后 149969 条）
        本书专有词库（提取 3037 条）

    这里把词库名与括号里的数字拆出来。括号里没有数字（例如
    「无（这本书还没有跑过校正，没有替换记录）」）时三个数字字段都是 ``None``，
    表示报告没给这个数——不是 0。
    """

    name: str
    detail: str = ""
    #: 「本次应用规则 N 条」
    applied_rules: int | None = None
    #: 「去重后 N 条」
    unique_rules: int | None = None
    #: 「提取 N 条」
    extracted_entries: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "detail": self.detail,
            "applied_rules": self.applied_rules,
            "unique_rules": self.unique_rules,
            "extracted_entries": self.extracted_entries,
        }


@dataclass
class Row:
    """明细表的一行：一次「改前 → 改后」在全书出现的次数。"""

    before: str
    after: str
    count: int
    #: 该行在报告文件里的物理行号（1 起；CSV 记录的是该行结束的行号）
    line_no: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "before": self.before,
            "after": self.after,
            "count": self.count,
            "line_no": self.line_no,
        }


@dataclass
class Section:
    """TXT 报告里的一段明细（一个「// 【替换次数报告】X」小节）。

    单本书一般只有一段；分段存在是因为上游按「每本被比对的书」各出一段。
    """

    label: str = ""
    #: 该小节自报的总替换次数（报告里「总替换次数：【N】」），没写就是 None
    stated_total: int | None = None
    #: 该小节自报的明细条数（序号里的「/N」），没写就是 None
    stated_entries: int | None = None
    #: 该小节生效的次数下限（「重复次数大于 N」），没写就是 None
    threshold: int | None = None
    #: 该小节**实际读到**的明细条数与次数合计（解析器填，不是报告写的）
    rows_found: int = 0
    total_found: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "stated_total": self.stated_total,
            "stated_entries": self.stated_entries,
            "threshold": self.threshold,
            "rows_found": self.rows_found,
            "total_found": self.total_found,
        }


@dataclass
class Report:
    """一份替换报告读出来的全部内容。

    ``ok`` 只表示「读到了东西」（有字段或有明细）；读取失败也不抛异常，
    而是 ``ok=False`` + ``issues`` 里一条人话说明，界面照样能展示。
    """

    ok: bool = False
    #: csv / text
    fmt: str = ""
    source: str = ""
    #: 文件是多少行（读完后填）
    total_lines: int = 0

    title: str = ""
    author: str = ""
    generated_at: str = ""
    #: 报告自报的命中数（``None`` = 报告里没写这个字段）
    hits: int | None = None
    #: 「涉及词库」原文（整段，便于逐字核对）
    libraries_text: str = ""
    libraries: list[LibraryEntry] = field(default_factory=list)

    rows: list[Row] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)

    #: 报告里没能识别的键值对（原样留着，不丢信息）
    extra_fields: dict[str, str] = field(default_factory=dict)

    issues: list[Issue] = field(default_factory=list)
    #: 与具体行无关的说明（不是问题，只是口径说明）
    notes: list[str] = field(default_factory=list)
    #: 文本是怎么读出来的（人话，界面可展示）
    read_note: str = ""

    # ---------------------------------------------------------------- 汇总
    @property
    def detail_rows(self) -> int:
        """明细条数（报告里有几行「改前 → 改后」。"""
        return len(self.rows)

    @property
    def detail_total(self) -> int:
        """明细里所有次数之和。"""
        return sum(r.count for r in self.rows)

    @property
    def hits_consistent(self) -> bool | None:
        """「命中数」与「明细次数合计」是否一致；报告缺字段时为 ``None``。"""
        if self.hits is None:
            return None
        return self.hits == self.detail_total

    @property
    def corrected(self) -> bool:
        """这本书这次导出前是否跑过校正（有明细或命中数非 0 即视为跑过）。"""
        return bool(self.rows) or bool(self.hits)

    def hits_by_library(self) -> list[dict[str, Any]]:
        """按词库拆命中数——**报告不支持，因此返回空列表**。

        报告只给「命中数合计 + 涉及词库清单」，没有每个词库各命中多少次。
        要这层数据得让导出侧加字段；在此之前，界面应展示 :attr:`libraries`
        （各词库的规则条数）与 :attr:`rows`（按规则的命中次数），
        不要把合计摊派成「每个词库多少」。
        """
        return []

    def library_rule_totals(self) -> tuple[int, int]:
        """(应用规则合计, 去重后合计)，只累加报告真给了数的词库。"""
        applied = sum(e.applied_rules or 0 for e in self.libraries)
        unique = sum(e.unique_rules or 0 for e in self.libraries)
        return applied, unique

    def top(self, limit: int = 10) -> list[Row]:
        """次数最多的前 ``limit`` 条（按次数降序，同次数保持报告原序）。"""
        if limit <= 0:
            return []
        ordered = sorted(self.rows, key=lambda r: -r.count)
        return ordered[:limit]

    def count_distribution(self) -> dict[int, int]:
        """次数 → 有多少条明细。例如 ``{10: 1, 9: 2}``。"""
        dist: dict[int, int] = {}
        for r in self.rows:
            dist[r.count] = dist.get(r.count, 0) + 1
        return dict(sorted(dist.items(), key=lambda kv: -kv[0]))

    def search(self, keyword: str) -> list[Row]:
        """在改前 / 改后两侧找包含某段文字的明细（界面筛选用）。"""
        if not keyword:
            return list(self.rows)
        return [r for r in self.rows if keyword in r.before or keyword in r.after]

    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == LEVEL_WARNING]

    def infos(self) -> list[Issue]:
        return [i for i in self.issues if i.level == LEVEL_INFO]

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "fmt": self.fmt,
            "source": self.source,
            "total_lines": self.total_lines,
            "title": self.title,
            "author": self.author,
            "generated_at": self.generated_at,
            "hits": self.hits,
            "hits_detail_total": self.detail_total,
            "hits_consistent": self.hits_consistent,
            "detail_rows": self.detail_rows,
            "libraries_text": self.libraries_text,
            "libraries": [e.to_dict() for e in self.libraries],
            "hits_by_library": self.hits_by_library(),
            "rows": [r.to_dict() for r in self.rows],
            "sections": [s.to_dict() for s in self.sections],
            "extra_fields": dict(self.extra_fields),
            "issues": [i.to_dict() for i in self.issues],
            "notes": list(self.notes),
            "read_note": self.read_note,
        }

    #: 兼容「属性当字典取」的调用方（界面侧写 ``report["hits"]`` 也能用）
    def __getitem__(self, key: str) -> Any:
        try:
            return self.to_dict()[key]
        except KeyError:
            raise KeyError(key) from None

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


def make_report(*, fmt: str, source: str, total_lines: int) -> Report:
    """建一份空报告并填好形态与来源（解析器内部用）。"""
    return Report(fmt=fmt, source=source, total_lines=total_lines)


def summarize_libraries(text: str) -> tuple[list[LibraryEntry], str]:
    """把「涉及词库」原文拆成条目。

    报告用全角分号「；」分隔多个词库；括号里可能带「本次应用规则 N 条」
    「去重后 N 条」「提取 N 条」。返回 (条目列表, 原文)。
    没有词库字段时返回 ([], "")。
    """
    raw = (text or "").strip()
    if not raw:
        return [], ""
    entries: list[LibraryEntry] = []
    for part in raw.replace("；", ";").split(";"):
        piece = part.strip()
        if not piece:
            continue
        entries.append(_library_entry(piece))
    return entries, raw


import re as _re

_N_APPLIED = _re.compile(r"本次应用规则\s*(\d+)\s*条")
_N_UNIQUE = _re.compile(r"去重后\s*(\d+)\s*条")
_N_EXTRACT = _re.compile(r"提取\s*(\d+)\s*条")
_NAME_CUT = _re.compile(r"[（(]")


def _library_entry(piece: str) -> LibraryEntry:
    name = _NAME_CUT.split(piece, 1)[0].strip() or piece
    applied = _N_APPLIED.search(piece)
    unique = _N_UNIQUE.search(piece)
    extract = _N_EXTRACT.search(piece)
    return LibraryEntry(
        name=name,
        detail=piece,
        applied_rules=int(applied.group(1)) if applied else None,
        unique_rules=int(unique.group(1)) if unique else None,
        extracted_entries=int(extract.group(1)) if extract else None,
    )
