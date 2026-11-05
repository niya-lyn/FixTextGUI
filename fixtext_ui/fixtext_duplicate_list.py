"""V1.1-E7 · 重复段落清单的装配层（界面侧，不依赖 Qt）
========================================================

本模块只做一件事：把 E6 已经交付的检测结果
(:meth:`fixtext_duplicates.model.DuplicateReport.payload`) 装配成清单页
可以直接渲染的行——**分组编号、四套定位口径、排序、筛选、处置状态**。

数据口径一律沿用 E6，不在本模块重算
------------------------------------
``payload()`` 已经给出「分组（含稳定编号 ``E-x`` / ``S-x``）+ 成员位置 +
段落全文索引」三样东西，正是清单页需要的全部输入。因此这里：

* 分组 **不重算**——组号直接取 ``DuplicateGroup.group_id``，与检测报告逐字
  相同，同一本书同一份正文永远同一套编号；
* 相似度 **不重算**——"完全重复 / 相似重复"取报告里的 ``kind`` 与分档分数；
* 段落全文 **不回书稿重取**——按 ``paragraph_index`` 在 ``payload`` 的
  ``paragraphs`` 里查（成员自带的 ``text`` 是截断摘要，只作兜底）。

四套定位口径（清单上同时给出，跳转时按行区间落地）
--------------------------------------------------
1. **段序号** ``paragraph_index``——0 起全局序号，比对与统计都用它；
   给人看的"第 N 段"是它 + 1。
2. **章节** ``chapter_no`` + ``chapter_title``——1 起；纯文本导入时为 -1。
3. **行区间** ``line_start`` – ``line_end``——1 起、闭区间，与检查页 /
   对比视图同一套口径；跳转正文按这个区间选中。
4. **字符偏移** ``char_start`` – ``char_end``——左闭右开，指向含标签的原文
   区间，供行内高亮使用。

处置状态以**纯字典**进来（``{组号: 状态}``），本模块不认识存储层——
装配与持久化分开，界面与测试都只拿这一份视图。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from fixtext_duplicates.model import (
    KIND_EXACT,
    KIND_NAMES,
    KIND_SIMILAR,
    ORDER_BY_COUNT,
    ORDER_BY_POSITION,
    ORDER_BY_SIMILARITY,
    ORDER_NAMES,
)

# ---------------------------------------------------------------------------
# 筛选口径（清单页顶部「只看」用；名字与 E6 的类型名同一套人话）
# ---------------------------------------------------------------------------

FILTER_ALL = "all"
FILTER_EXACT = KIND_EXACT
FILTER_SIMILAR = KIND_SIMILAR

FILTER_NAMES = {
    FILTER_ALL: "全部",
    FILTER_EXACT: KIND_NAMES[KIND_EXACT],
    FILTER_SIMILAR: KIND_NAMES[KIND_SIMILAR],
}

#: 「只看未处置」的口径名（与「全部」并列，界面一个下拉切换）
SHOW_NAMES = {"all": "全部", "open": "只看未处置"}


# ---------------------------------------------------------------------------
# 一个成员段落：四套位置口径
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParagraphSlot:
    """一个成员段落在书里的位置（四套口径各一个字段组）。

    ``text`` 是段落**全文**（从 ``payload["paragraphs"]`` 取），清单展开与
    对比预览都读它；取不到时才退回成员自带的截断摘要。
    """

    index: int
    chapter_no: int
    chapter_title: str
    line_start: int
    line_end: int
    char_start: int
    char_end: int
    chars: int
    text: str

    # -- 装配 -------------------------------------------------------------

    @classmethod
    def from_member(cls, member: dict[str, Any],
                    paragraphs: dict[Any, dict[str, Any]] | None = None) -> "ParagraphSlot":
        """从 ``payload()["groups"][i]["members"][j]`` 装配一个位置。

        ``paragraphs`` 是 ``payload()["paragraphs"]``（段落全文索引）。它的键
        在内存里是整数、经 JSON 往返后是字符串——两种都认，免得离线复现的
        清单取不到全文。
        """
        idx = int(member.get("paragraph_index"))
        full: dict[str, Any] = {}
        for key in (idx, str(idx)):
            got = (paragraphs or {}).get(key)
            if isinstance(got, dict):
                full = got
                break
        text = full.get("text")
        if not isinstance(text, str) or not text:
            text = str(member.get("text") or "")
        return cls(
            index=idx,
            chapter_no=int(member.get("chapter_no") or -1),
            chapter_title=str(member.get("chapter_title") or ""),
            line_start=int(member.get("line_start") or 0),
            line_end=int(member.get("line_end") or 0),
            char_start=int(member.get("char_start") or 0),
            char_end=int(member.get("char_end") or 0),
            chars=int(member.get("chars") or 0),
            text=text,
        )

    # -- 四套口径（人话） ---------------------------------------------------

    def index_text(self) -> str:
        """段序号口径：给人看的是 1 起的序号，括号里补原始序号便于核对。"""
        return f"第 {self.index + 1} 段（序号 {self.index}）"

    def chapter_text(self) -> str:
        """章节口径；没有章节信息时如实说「未分章」。"""
        if self.chapter_no > 0:
            title = self.chapter_title.strip()
            return f"第 {self.chapter_no} 章 · {title}" if title else f"第 {self.chapter_no} 章"
        if self.chapter_title.strip():
            return self.chapter_title.strip()
        return "未分章"

    def line_text(self) -> str:
        """行区间口径（1 起、闭区间）。"""
        if self.line_end and self.line_end != self.line_start:
            return f"第 {self.line_start}–{self.line_end} 行"
        return f"第 {self.line_start} 行"

    def char_text(self) -> str:
        """字符偏移口径（左闭右开）。"""
        return f"字 {self.char_start}–{self.char_end}"

    def texts(self) -> dict[str, str]:
        """四套口径一次给全（定位卡逐行显示、测试逐条核对）。"""
        return {
            "index": self.index_text(),
            "chapter": self.chapter_text(),
            "line": self.line_text(),
            "char": self.char_text(),
        }

    def location_text(self) -> str:
        """一行合并描述，例如「第 3 章 · 考城隍 · 第 210–212 行」。"""
        head = self.chapter_text()
        return head if head == "未分章" else f"{head} · {self.line_text()}"

    # -- 跳转载荷 -----------------------------------------------------------

    def target(self) -> dict[str, Any]:
        """跳转正文的载荷：行区间用于选中，字符偏移用于行内高亮。

        四个口径都带上（验收要能逐条对上），界面按行区间落地。
        """
        return {
            "paragraph_index": self.index,
            "chapter_no": self.chapter_no,
            "chapter_title": self.chapter_title,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "chars": self.chars,
        }


# ---------------------------------------------------------------------------
# 一条清单：一组重复段落
# ---------------------------------------------------------------------------

@dataclass
class DuplicateItem:
    """清单上的一行 —— 一个 ``DuplicateGroup`` 的视图。

    ``group_id`` 是稳定编号（``E-1`` 完全重复 / ``S-1`` 相似重复），与检测
    报告逐字一致；组内第几处、共几处另外给出，供「上一处 / 下一处」用。
    """

    group_id: str
    kind: str
    occurrences: int
    max_similarity: float
    min_similarity: float
    cross_chapter: bool
    first_position: int
    pair_count: int
    slots: list[ParagraphSlot] = field(default_factory=list)

    # -- 展示 -------------------------------------------------------------

    @property
    def kind_name(self) -> str:
        return KIND_NAMES.get(self.kind, self.kind)

    def position_text(self) -> str:
        """这一组在书里第一次出现在哪（清单主列）。"""
        if not self.slots:
            return "—"
        return self.slots[0].location_text()

    def chapter_span_text(self) -> str:
        nos = [s.chapter_no for s in self.slots if s.chapter_no > 0]
        if not nos:
            return "未分章"
        lo, hi = min(nos), max(nos)
        return f"跨 {hi - lo + 1} 章" if hi != lo else f"第 {lo} 章"

    def summary_text(self) -> str:
        """一行概览：「6 段 · 完全重复 · 跨 2 章」。"""
        bits = [f"{self.occurrences} 段", self.kind_name]
        if self.occurrences > 1:
            bits.append(self.chapter_span_text())
        return " · ".join(bits)

    def similarity_text(self) -> str:
        if self.kind == KIND_EXACT:
            return "完全一致"
        if self.max_similarity and self.min_similarity and \
                abs(self.max_similarity - self.min_similarity) > 0.005:
            return f"{self.max_similarity:.0%}–{self.min_similarity:.0%}"
        return f"{self.max_similarity:.0%}"

    def member_lines(self) -> list[str]:
        """组内每个成员一行（展开区显示，带上四套口径里的前三套）。"""
        out: list[str] = []
        for i, slot in enumerate(self.slots, 1):
            out.append(
                f"{i}. {slot.location_text()}　{slot.index_text()}　"
                f"{slot.char_text()}")
        return out

    def target(self, which: int = 0) -> dict[str, Any] | None:
        """第 ``which`` 个成员的跳转载荷（越界返回 ``None``）。"""
        if 0 <= which < len(self.slots):
            return self.slots[which].target()
        return None

    def text_of(self, which: int = 0) -> str:
        if 0 <= which < len(self.slots):
            return self.slots[which].text
        return ""


# ---------------------------------------------------------------------------
# 整份清单
# ---------------------------------------------------------------------------

@dataclass
class DuplicateList:
    """装配好的清单（行 + 概况），界面只读这一份。"""

    items: list[DuplicateItem] = field(default_factory=list)
    threshold: float = 0.0
    min_chars: int = 0
    paragraph_count: int = 0
    chapter_count: int = 0
    stats: dict[str, Any] = field(default_factory=dict)
    order: str = ORDER_BY_COUNT
    kind_filter: str = FILTER_ALL
    show: str = "all"
    #: 处置状态（组号 → marked/ignored），只作展示与筛选，不在本模块写盘
    marks: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.items)

    def empty(self) -> bool:
        return not self.items

    def item_at(self, row: int) -> DuplicateItem | None:
        if 0 <= row < len(self.items):
            return self.items[row]
        return None

    def row_of(self, group_id: str) -> int:
        for i, it in enumerate(self.items):
            if it.group_id == group_id:
                return i
        return -1

    def state_of(self, group_id: str) -> str:
        return str(self.marks.get(group_id) or "")

    def handled_count(self) -> int:
        """已处置（标记或忽略）的组数。"""
        return sum(1 for it in self.items if self.state_of(it.group_id))

    def counts(self) -> dict[str, int]:
        """分组 / 段的计数（概况条用；口径与 E6 的 stats 对齐）。"""
        exact = [it for it in self.items if it.kind == KIND_EXACT]
        similar = [it for it in self.items if it.kind == KIND_SIMILAR]
        page_ids: set[int] = set()
        for it in self.items:
            page_ids.update(s.index for s in it.slots)
        return {
            "groups": len(self.items),
            "exact_groups": len(exact),
            "similar_groups": len(similar),
            "paragraphs": len(page_ids),
            "handled": self.handled_count(),
        }

    def overview_text(self) -> str:
        """一句概况（清单页顶部；空清单与有命中各一套说法）。"""
        if not self.items:
            total = self.paragraph_count
            return (f"共 {total} 段，在这个范围里没有发现重复段落"
                    f"（相似度阈值 {self.threshold:.2f}，最短 {self.min_chars} 字）。")
        c = self.counts()
        text = (f"共 {self.paragraph_count} 段，检出 {c['groups']} 组重复、"
                f"涉及 {c['paragraphs']} 段；完全重复 {c['exact_groups']} 组、"
                f"相似重复 {c['similar_groups']} 组")
        if c["handled"]:
            text += f"；已处置 {c['handled']} 组"
        return text + f"（相似度阈值 {self.threshold:.2f}，最短 {self.min_chars} 字）。"


# ---------------------------------------------------------------------------
# 装配入口
# ---------------------------------------------------------------------------

def _sort_key(order: str):
    if order == ORDER_BY_POSITION:
        return lambda g: (int(g.get("first_position") or 0), -int(g.get("occurrences") or 0))
    if order == ORDER_BY_SIMILARITY:
        return lambda g: (-float(g.get("max_similarity") or 0.0),
                          int(g.get("first_position") or 0))
    if order == ORDER_BY_COUNT:
        return lambda g: (-int(g.get("occurrences") or 0),
                          int(g.get("first_position") or 0))
    raise ValueError(f"未知排序方式：{order}，可选 {sorted(ORDER_NAMES)}")


def item_from_group(group: dict[str, Any],
                    paragraphs: dict[Any, dict[str, Any]] | None = None) -> DuplicateItem:
    """把 ``payload()["groups"][i]`` 装配成一条清单行（不重算任何数值）。"""
    slots = [ParagraphSlot.from_member(m, paragraphs)
             for m in (group.get("members") or [])]
    slots.sort(key=lambda s: s.index)
    return DuplicateItem(
        group_id=str(group.get("group_id") or ""),
        kind=str(group.get("kind") or ""),
        occurrences=int(group.get("occurrences") or len(slots)),
        max_similarity=float(group.get("max_similarity") or 0.0),
        min_similarity=float(group.get("min_similarity") or 0.0),
        cross_chapter=bool(group.get("cross_chapter")),
        first_position=int(group.get("first_position") or 0),
        pair_count=int(group.get("pair_count") or 0),
        slots=slots,
    )


def build_list(payload: dict[str, Any], *,
               order: str = ORDER_BY_COUNT,
               kind: str = FILTER_ALL,
               show: str = "all",
               marks: dict[str, str] | None = None) -> DuplicateList:
    """``payload()`` → 清单视图（排序 / 筛选 / 处置状态都在这一处收敛）。

    * ``order``：三种排序，键与 :meth:`DuplicateReport.sorted_groups` 逐字对齐；
    * ``kind``：只看完全重复 / 只看相似重复 / 全部；
    * ``show``：``"all"`` 全部，``"open"`` 只看还没处置的组；
    * ``marks``：组号 → 处置状态（空 = 这本书还没处置过任何一组）。
    """
    if not isinstance(payload, dict):
        raise TypeError("清单装配要的是一份检测结果视图")
    paragraphs = payload.get("paragraphs")
    if not isinstance(paragraphs, dict):
        paragraphs = {}
    groups = [dict(g) for g in (payload.get("groups") or []) if isinstance(g, dict)]
    groups.sort(key=_sort_key(order))

    states = {str(k): str(v) for k, v in (marks or {}).items() if str(k)}
    items: list[DuplicateItem] = []
    for g in groups:
        if kind in (FILTER_EXACT, FILTER_SIMILAR) and str(g.get("kind")) != kind:
            continue
        if show == "open" and states.get(str(g.get("group_id") or "")):
            continue
        items.append(item_from_group(g, paragraphs))

    return DuplicateList(
        items=items,
        threshold=float(payload.get("threshold") or 0.0),
        min_chars=int(payload.get("min_chars") or 0),
        paragraph_count=int(payload.get("paragraph_count") or 0),
        chapter_count=int(payload.get("chapter_count") or 0),
        stats=dict(payload.get("stats") or {}),
        order=order,
        kind_filter=kind,
        show=show,
        marks=states,
    )


def slots_of_items(items: Iterable[DuplicateItem]) -> list[ParagraphSlot]:
    """把若干组的成员摊平（跨组去重前先按段序号排好）——给"按段看"的视图用。"""
    seen: dict[int, ParagraphSlot] = {}
    for it in items:
        for slot in it.slots:
            seen.setdefault(slot.index, slot)
    return [seen[k] for k in sorted(seen)]


__all__ = [
    "FILTER_ALL", "FILTER_EXACT", "FILTER_SIMILAR", "FILTER_NAMES", "SHOW_NAMES",
    "ParagraphSlot", "DuplicateItem", "DuplicateList",
    "build_list", "item_from_group", "slots_of_items",
]
