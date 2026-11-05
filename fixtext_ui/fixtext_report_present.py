"""V1.1-E9 · 替换报告的界面装配层（界面侧，不依赖 Qt）
=========================================================

E8 已经把报告读成了 :class:`fixtext_report.Report`。本模块只做一件事：
**把那份数据装配成报告页可以直接渲染的视图对象**——标题 / 概况数字 /
按规则明细 / 词库清单 / 提示与说明，以及「这份报告现在能不能看」的状态。

三条口径（与 E8 完全一致，本模块一个数都不重算）
--------------------------------------------

1. **所有数字原样取自报告。** 概况里的每个值都来自 ``Report`` 的字段或它
   自己的汇总属性（``hits`` / ``detail_rows`` / ``detail_total``），本模块只做
   展示形态转换（``None`` → 明确写「报告里没有写」），绝不把「没有这个数」
   写成 0，也不按比例摊派。
2. **按词库拆命中数给不出来，就不给。** ``Report.hits_by_library()`` 返回空
   列表是**诚实缺口**（报告本身没有这层数据），视图里带一条
   :attr:`ReportView.library_hits_note` 说明，词库区只展示报告真给了的
   「规则条数」。
3. **两处口径对不上时两个数都摆出来。** ``hits_consistent is False`` 时视图给
   一条 ``warning`` 级别的提示，正文写 ``N`` 处、明细合计 ``M`` 次，两个数
   都保留，不擅自挑一个。

四种状态（界面据此切内容区 / 空状态）
------------------------------------

``ready``        有命中数也有明细 → 正常呈现
``uncorrected``  读到了报告，但这本书这次导出前没跑过校正（命中 0、无明细）
``empty``        目录里没有报告文件 → 空状态 + 「去导出」引导
``unreadable``   文件在、读不动 → 空状态 + 逐条人话原因

不抛异常：读不动一律落在 ``unreadable`` 状态，``issues`` 里逐条写明。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fixtext_report import Report, parse_report, parse_report_dir
from fixtext_paths import pkg_root, safe_dir_name, history_export_root

# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------

STATE_READY = "ready"
STATE_UNCORRECTED = "uncorrected"
STATE_EMPTY = "empty"
STATE_UNREADABLE = "unreadable"

STATE_TITLES = {
    STATE_READY: "这份报告可以看",
    STATE_UNCORRECTED: "这本书这次没有产生替换",
    STATE_EMPTY: "还没有可看的替换报告",
    STATE_UNREADABLE: "这份报告读不出来",
}

#: 报告形态 → 人话（不写文件格式缩写，用户只需要知道是表格还是文本）
FMT_LABELS = {"csv": "表格", "text": "文本"}

#: 报告字段缺失时的显示（绝不拿 0 顶替）
MISSING = "报告里没有写"


# ---------------------------------------------------------------------------
# 视图对象
# ---------------------------------------------------------------------------

@dataclass
class Kpi:
    """概况里的一个数字格（原型 .kv / .stat 的一格）。"""

    key: str
    label: str
    value: str
    note: str = ""


@dataclass
class RuleRow:
    """按规则明细的一行：一次「改前 → 改后」在全书出现的次数。"""

    index: int           # 1 起，报告里的顺序号（按次数降序后的位次）
    before: str
    after: str
    count: int
    #: 占明细次数合计的百分比（只有合计 > 0 时才算，且由代码算，不是估）
    share: float = 0.0

    @property
    def share_text(self) -> str:
        return f"{self.share:.1f}%" if self.share > 0 else "—"


@dataclass
class LibraryRow:
    """报告「涉及词库」的一条：词库名 + 报告真给了的那些数字。"""

    name: str
    detail: str = ""
    applied_rules: int | None = None
    unique_rules: int | None = None
    extracted_entries: int | None = None

    @property
    def numbers_text(self) -> str:
        """把报告括号里的数字拼成一句人话；缺哪个就不提哪个。"""
        bits: list[str] = []
        if self.applied_rules is not None:
            bits.append(f"本次应用规则 {self.applied_rules} 条")
        if self.unique_rules is not None:
            bits.append(f"去重后 {self.unique_rules} 条")
        if self.extracted_entries is not None:
            bits.append(f"提取 {self.extracted_entries} 条")
        return " · ".join(bits) if bits else "报告没给这个数"


@dataclass
class IssueRow:
    """读取过程中的一条提示（人话，可直接上界面）。"""

    level: str
    text: str
    line_no: int | None = None

    @property
    def is_warning(self) -> bool:
        return self.level == "warning"


@dataclass
class ReportView:
    """报告页要渲染的全部内容（一次装配，页面只读）。"""

    state: str = STATE_EMPTY
    source_name: str = ""
    fmt_label: str = ""
    title: str = ""
    author: str = ""
    generated_at: str = ""

    #: 报告自报的命中数（``None`` = 报告里没写这个字段）
    hits: int | None = None
    detail_rows: int = 0
    detail_total: int = 0
    #: 报告「涉及词库」里真列出来的词库数（「无」不算一个词库）
    library_count: int = 0
    #: 各词库「本次应用规则」合计；报告一个都没给时为 ``None``
    applied_total: int | None = None

    kpis: list[Kpi] = field(default_factory=list)
    rows: list[RuleRow] = field(default_factory=list)
    libraries: list[LibraryRow] = field(default_factory=list)
    issues: list[IssueRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: 次数最多的一批（页面顶部「改前 → 改后」直接摆这几条）
    top_rows: list[RuleRow] = field(default_factory=list)
    #: 次数分布：[(次数, 有几条)]，按次数降序
    distribution: list[tuple[int, int]] = field(default_factory=list)

    #: ``None`` = 报告没写命中数 / ``True`` 一致 / ``False`` 对不上
    hits_consistent: bool | None = None
    consistency_note: str = ""
    #: 「按词库拆命中数」这条缺口的人话说明（报告不支持，不是 0）
    library_hits_note: str = ""
    #: 空状态用的标题 / 说明
    empty_title: str = ""
    empty_desc: str = ""
    #: 这本书上一次校正的运行目录（供「打开前后对比」联动；没有就空）
    run_dir: str = ""

    @property
    def ok_to_show(self) -> bool:
        return self.state in (STATE_READY, STATE_UNCORRECTED)

    def search(self, keyword: str) -> list[RuleRow]:
        """在改前 / 改后两侧找包含某段文字的明细（界面筛选用）。"""
        text = (keyword or "").strip()
        if not text:
            return list(self.rows)
        return [r for r in self.rows if text in r.before or text in r.after]

    def summary_line(self) -> str:
        """一句人话概览（页头状态 / 验收对账用）。"""
        if self.state == STATE_READY:
            n = self.detail_rows
            return f"这份报告记了 {n} 条改法、合计 {self.detail_total} 次替换。"
        if self.state == STATE_UNCORRECTED:
            return self.notes[-1] if self.notes else "这本书这次导出前没有跑过校正。"
        if self.state == STATE_UNREADABLE:
            return self.empty_title or STATE_TITLES[STATE_UNREADABLE]
        return self.empty_title or STATE_TITLES[STATE_EMPTY]

    def to_dict(self) -> dict[str, Any]:
        """扁平字典（证据 / 自检 / 日志用，**不用于界面**）。"""
        return {
            "state": self.state,
            "source_name": self.source_name,
            "fmt_label": self.fmt_label,
            "title": self.title,
            "author": self.author,
            "generated_at": self.generated_at,
            "hits": self.hits,
            "detail_rows": self.detail_rows,
            "detail_total": self.detail_total,
            "library_count": self.library_count,
            "applied_total": self.applied_total,
            "hits_consistent": self.hits_consistent,
            "kpis": [k.__dict__ for k in self.kpis],
            "rows": [r.__dict__ for r in self.rows],
            "libraries": [dict(name=e.name, detail=e.detail,
                               applied_rules=e.applied_rules,
                               unique_rules=e.unique_rules,
                               extracted_entries=e.extracted_entries,
                               numbers_text=e.numbers_text)
                          for e in self.libraries],
            "issues": [dict(level=i.level, text=i.text, line_no=i.line_no)
                       for i in self.issues],
            "notes": list(self.notes),
            "distribution": [list(d) for d in self.distribution],
            "run_dir": self.run_dir,
        }


# ---------------------------------------------------------------------------


def _count_libraries(report: Report) -> int:
    """报告真列出来的词库数——「无（这本书还没有跑过校正…）」不算一个词库。"""
    n = 0
    for e in report.libraries:
        name = (e.name or "").strip()
        if name and name != "无":
            n += 1
    return n


def _applied_total(report: Report) -> int | None:
    """各词库「本次应用规则」合计；一个词库都没给这个数时返回 ``None``。

    注意这不是把「没有」当 0：只有当报告里至少有一个词库写了应用规则条数，
    这个合计才成立；否则它就是「报告没给」，返回 ``None``。
    """
    values = [e.applied_rules for e in report.libraries if e.applied_rules is not None]
    return sum(values) if values else None


def _fmt_count(v: int | None) -> str:
    """数字 → 显示串；``None`` 显示「报告里没有写」，不显示 0。"""
    return MISSING if v is None else str(v)


def view_of(report: Report, *, source_name: str = "", run_dir: str = "") -> ReportView:
    """把一份 :class:`Report` 装配成报告页视图（唯一装配入口）。"""
    view = ReportView(
        source_name=source_name or Path(report.source).name,
        fmt_label=FMT_LABELS.get(report.fmt, "未知"),
        title=report.title or "",
        author=report.author or "",
        generated_at=report.generated_at or "",
        hits=report.hits,
        detail_rows=report.detail_rows,
        detail_total=report.detail_total,
        library_count=_count_libraries(report),
        applied_total=_applied_total(report),
        notes=list(report.notes),
        hits_consistent=report.hits_consistent,
        run_dir=run_dir,
    )

    # ---- 提示 -----------------------------------------------------------
    # 先转成可上界面的行，状态判断要用到其中的 warning 级别
    view.issues = [
        IssueRow(level=i.level, text=i.message, line_no=i.line_no)
        for i in report.issues
    ]

    # ---- 状态 ------------------------------------------------------------
    if not report.ok:
        view.state = STATE_UNREADABLE
        view.empty_title = "这份报告读不出来"
        first = next((i for i in view.issues if i.is_warning), None)
        view.empty_desc = (
            f"{first.text}可以重新导出一次，报告会自动重新生成。"
            if first else "报告文件在，但内容读不出来。可以重新导出一次。")
    elif report.corrected:
        view.state = STATE_READY
    else:
        view.state = STATE_UNCORRECTED
        view.empty_title = "这本书这次没有产生替换"
        view.empty_desc = (
            "报告里的命中数是 0，也没有任何明细——说明这次导出前没有跑过校正，"
            "或者校正没有改动任何地方。先跑一次校正，再导出就会有一份有内容的报告。")

    # ---- 概况数字（全部原样取自报告） ------------------------------------
    view.kpis = [
        Kpi("hits", "替换命中", _fmt_count(view.hits),
            "" if view.hits is not None else "报告里没有这个字段"),
        Kpi("rows", "明细条数", str(view.detail_rows)),
        Kpi("libraries", "涉及词库", f"{view.library_count} 套" if view.library_count
            else "报告没列词库"),
        Kpi("applied", "应用规则合计",
            f"{view.applied_total} 条" if view.applied_total is not None
            else "报告没给这个数"),
    ]

    # ---- 两处口径对账 ----------------------------------------------------
    if view.hits_consistent is False:
        view.consistency_note = (
            f"报告正文写的命中数是 {view.hits} 处，明细表里各条次数加起来是 "
            f"{view.detail_total} 次，两处对不上。两个数都按报告原样保留，"
            "可以重新导出一次再看。")
    elif view.hits_consistent is True:
        view.consistency_note = (
            f"报告正文的命中数（{view.hits} 处）与明细各条次数合计"
            f"（{view.detail_total} 次）一致。")
    else:
        view.consistency_note = "报告里没有写命中数，只按明细呈现。"

    # ---- 按规则明细 -----------------------------------------------------
    total = view.detail_total or 0
    ordered = sorted(report.rows, key=lambda r: -r.count)
    view.rows = [
        RuleRow(
            index=i + 1,
            before=r.before,
            after=r.after,
            count=r.count,
            share=(r.count / total * 100.0) if total > 0 else 0.0,
        )
        for i, r in enumerate(ordered)
    ]
    view.top_rows = view.rows[:5]
    view.distribution = list(report.count_distribution().items())

    # ---- 词库 ------------------------------------------------------------
    view.libraries = [
        LibraryRow(name=e.name, detail=e.detail,
                   applied_rules=e.applied_rules,
                   unique_rules=e.unique_rules,
                   extracted_entries=e.extracted_entries)
        for e in report.libraries
    ]
    # 诚实缺口：报告没有「每个词库各命中多少次」这一层数据
    view.library_hits_note = (
        "报告只写了命中数合计和涉及哪几个词库，没有写每个词库各命中多少次；"
        "所以这里只给出各词库的规则条数，不按比例摊派命中数。"
        if report.hits_by_library() == [] else "")

    # ---- 提示（已在上方转换，供状态判断使用） -------------------------------
    return view


def load_report_file(path: str | Path, *, run_dir: str = "") -> ReportView:
    """读一个报告文件 → 视图（读不动落在 ``unreadable``，不抛异常）。"""
    p = Path(path)
    report = parse_report(p)
    return view_of(report, source_name=p.name, run_dir=run_dir)


def load_report_dir(directory: str | Path, *, run_dir: str = "") -> ReportView:
    """读一个导出目录里那份「替换统计」→ 视图。"""
    d = Path(directory)
    report = parse_report_dir(d)
    return view_of(report, source_name=Path(report.source).name if report.source else "",
                   run_dir=run_dir)


def empty_view(reason: str = "", *, title: str = "", desc: str = "",
               run_dir: str = "") -> ReportView:
    """没有报告可看时的视图（页面据此走空状态）。"""
    view = ReportView(state=STATE_EMPTY, run_dir=run_dir)
    view.empty_title = title or STATE_TITLES[STATE_EMPTY]
    view.empty_desc = desc or reason or (
        "替换报告在导出时自动生成，和导出结果放在同一个地方。"
        "先去导出一次，这里就会出现这本书这次改了什么。")
    view.kpis = [
        Kpi("hits", "替换命中", "—", "还没有报告"),
        Kpi("rows", "明细条数", "—", "还没有报告"),
        Kpi("libraries", "涉及词库", "—", "还没有报告"),
        Kpi("applied", "应用规则合计", "—", "还没有报告"),
    ]
    return view


# ---------------------------------------------------------------------------
# 找这份书最近的一份报告（入口联动用）
# ---------------------------------------------------------------------------

def default_export_root() -> Path:
    """导出根（包根下的 ``导出/``，与导出页默认目录同一处）。"""
    return pkg_root() / "导出"


def report_files_for(title: str, *, roots: list[Path] | None = None) -> list[Path]:
    """按书名找「替换统计」报告，**最新的在前**。

    只认 ``<书名>替换统计.csv`` / ``.txt`` 两种命名（与导出侧同一口径）；
    搜索范围是导出根（平铺导出）与它的「历史记录」子目录（历史页重新导出）。
    找不到就是找不到——返回空列表，不猜。
    """
    safe = safe_dir_name(title) if title else ""
    if not safe:
        return []
    search: list[Path] = []
    for root in (roots if roots is not None else [default_export_root(),
                                                 history_export_root()]):
        root = Path(root)
        if not root.is_dir():
            continue
        for name in (f"{safe}替换统计.csv", f"{safe}替换统计.txt"):
            direct = root / name
            if direct.is_file():
                search.append(direct)
        try:
            search.extend(sorted(root.glob(f"*/{safe}替换统计.*")))
        except OSError:
            pass
    # 同一份报告两种形态都在时，表格优先（字段更全），再按修改时间新→旧
    uniq: dict[str, Path] = {}
    for p in search:
        if p.is_file():
            uniq[str(p.resolve())] = p
    files = sorted(uniq.values(),
                   key=lambda p: (p.suffix.lower() != ".csv", -_mtime(p)))
    return files


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def latest_report_view(title: str, *, run_dir: str = "",
                       roots: list[Path] | None = None) -> ReportView:
    """按书名取最近一份报告 → 视图；一份都没有时给空状态视图（附原因）。"""
    files = report_files_for(title, roots=roots)
    if not files:
        return empty_view(
            title="这本书还没有导出过",
            desc=("替换报告在导出时自动生成。先导出一次，这里就会出现这次改了什么；"
                  "报告和导出结果放在同一个地方。"),
            run_dir=run_dir)
    return load_report_file(files[0], run_dir=run_dir)


if __name__ == "__main__":      # 手工看一眼真实样本装出来的视图
    import json

    here = Path(__file__).resolve().parent.parent
    sample = here / "tests" / "fixtures" / "report" / "炮火弧线替换统计.csv"
    v = load_report_file(sample)
    print(json.dumps({k: val for k, val in v.to_dict().items()
                      if k in ("state", "title", "hits", "detail_rows",
                               "detail_total", "library_count", "applied_total")},
                     ensure_ascii=False, indent=2))
