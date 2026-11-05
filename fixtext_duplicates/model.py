"""重复段落命中的数据结构（V1.1-E6 交付物②）。

设计目标是**让 E7（清单与处置）拿来就能用**，而不是只给一对下标：

* 每个段落都给「在书里的位置」三套口径：全局段落序号、章节序号 / 章节标题、
  行号区间、字符偏移区间。E7 的跳转按行号定位（与检查页、对比视图同一套
  定位口径），因此行号是必需的；字符偏移供高亮选中使用。
* 每条命中都给「重复类型 + 相似度分值 + 是否跨章 + 是否相邻（连续段落）」，
  E7 的分组、排序、筛选都从这些字段直接取，不需要自己再算。
* 全部结构可序列化（``to_dict`` / ``from_dict`` / ``to_json``），字段类型只
  用 ``int`` / ``float`` / ``str`` / ``bool`` / ``list`` / ``dict``，
  落盘后原样读回即可重建，不依赖任何运行期对象。

本模块**不导入 Qt、不导入界面层、不导入 pipeline**：只用标准库。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

#: 重复类型
KIND_EXACT = "exact"
KIND_SIMILAR = "similar"
KIND_NAMES = {KIND_EXACT: "完全重复", KIND_SIMILAR: "相似重复"}

#: 清单默认排序方式（E7 可直接暴露成三个选项）
ORDER_BY_COUNT = "count"          # 出现次数多 → 少
ORDER_BY_POSITION = "position"    # 书里靠前的先出
ORDER_BY_SIMILARITY = "similarity"  # 相似度高的先出
ORDER_NAMES = {
    ORDER_BY_COUNT: "按出现次数",
    ORDER_BY_POSITION: "按书中位置",
    ORDER_BY_SIMILARITY: "按相似度",
}

#: 清单里每条成员默认展示多少字
EXCERPT_CHARS = 120


@dataclass
class ParagraphRef:
    """一个段落以及它在书里的全部位置信息。

    字段口径（写进 E7 之前不要改，改了清单的跳转就会错位）：

    * ``index``       全局段落序号，0 起，按书中的先后顺序。
    * ``chapter_index`` 章序号，0 起；``-1`` 表示这份文本没有章节信息（纯文本导入）。
    * ``chapter_no``  给用户看的章序号，1 起；无章节信息时同样为 ``-1``。
    * ``line_start`` / ``line_end`` 段落在书正文里的行号区间（1 起，闭区间）。
      跳转按行号定位，与检查页 / 对比视图同一套口径。
    * ``char_start`` / ``char_end`` 段落在书正文里的字符偏移区间（左闭右开）。
      这里指向**原文区间**（EPUB 合并文本里含标签本身），供高亮选中使用；
      比对用的干净文本在 ``text``。
    """

    index: int
    text: str
    line_start: int
    line_end: int
    char_start: int
    char_end: int
    chapter_index: int = -1
    chapter_no: int = -1
    chapter_title: str = ""
    chapter_label: str = ""
    source: str = "paragraph"

    #: 段落字数（不计空白），用于 E7 里按长度筛选 / 展示
    @property
    def chars(self) -> int:
        from .similarity import core_length

        return core_length(self.text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": int(self.index),
            "text": self.text,
            "line_start": int(self.line_start),
            "line_end": int(self.line_end),
            "char_start": int(self.char_start),
            "char_end": int(self.char_end),
            "chapter_index": int(self.chapter_index),
            "chapter_no": int(self.chapter_no),
            "chapter_title": self.chapter_title,
            "chapter_label": self.chapter_label,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParagraphRef":
        return cls(
            index=int(data["index"]),
            text=str(data.get("text", "")),
            line_start=int(data["line_start"]),
            line_end=int(data["line_end"]),
            char_start=int(data.get("char_start", 0)),
            char_end=int(data.get("char_end", 0)),
            chapter_index=int(data.get("chapter_index", -1)),
            chapter_no=int(data.get("chapter_no", -1)),
            chapter_title=str(data.get("chapter_title", "")),
            chapter_label=str(data.get("chapter_label", "")),
            source=str(data.get("source", "paragraph")),
        )

    def excerpt(self, limit: int = EXCERPT_CHARS) -> str:
        """清单里展示用的短文本（超长截断并补省略号）。"""
        t = self.text
        if limit > 0 and len(t) > limit:
            return t[:limit] + "…"
        return t

    def location_text(self) -> str:
        """一行位置描述，例如「第 12 章 · 考城隍 · 第 321 行」。"""
        parts: list[str] = []
        if self.chapter_no > 0:
            parts.append(f"第 {self.chapter_no} 章")
        if self.chapter_title:
            parts.append(self.chapter_title)
        parts.append(f"第 {self.line_start} 行")
        return " · ".join(parts)


@dataclass
class DuplicatePair:
    """一对重复段落。

    以「对」为单位是因为它**天然可判真假**：清单上任何一条「这两段重复」
    都能被人工逐条核对；分组是派生视图，由这些对连起来。
    """

    left: int                  # 段落序号（较小者）
    right: int                 # 段落序号（较大者）
    similarity: float
    kind: str
    cross_chapter: bool
    adjacent: bool = False
    raw_equal: bool = False    # 逐字相同（不只是规范化后相同）
    line_gap: int = 0

    @property
    def key(self) -> tuple[int, int]:
        return (self.left, self.right)

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": int(self.left),
            "right": int(self.right),
            "similarity": round(float(self.similarity), 6),
            "kind": self.kind,
            "cross_chapter": bool(self.cross_chapter),
            "adjacent": bool(self.adjacent),
            "raw_equal": bool(self.raw_equal),
            "line_gap": int(self.line_gap),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DuplicatePair":
        return cls(
            left=int(data["left"]),
            right=int(data["right"]),
            similarity=float(data["similarity"]),
            kind=str(data["kind"]),
            cross_chapter=bool(data.get("cross_chapter", False)),
            adjacent=bool(data.get("adjacent", False)),
            raw_equal=bool(data.get("raw_equal", False)),
            line_gap=int(data.get("line_gap", 0)),
        )


@dataclass
class DuplicateGroup:
    """一组重复（由重复对连通而成，同类只成一组便于清单展示）。

    ``adjacent_runs`` 是「连续段落块」的个数：成员行号差 ≤ ``adjacent_window``
    视为相邻（原版 find-dupl-text 的「连续段落」判定，差 ≤3 视为相邻）。
    它给的是「这一组里有几段连续搬运」的信号，不是精确的块划分。
    """

    group_id: str
    kind: str
    members: list[ParagraphRef]
    pair_indices: list[int]
    max_similarity: float
    min_similarity: float
    adjacent_runs: int = 0

    @property
    def occurrences(self) -> int:
        return len(self.members)

    @property
    def first_position(self) -> int:
        return self.members[0].index if self.members else -1

    @property
    def cross_chapter(self) -> bool:
        chapters = {m.chapter_index for m in self.members}
        return len(chapters) > 1

    @property
    def chapter_span(self) -> tuple[int, int]:
        nos = [m.chapter_no for m in self.members if m.chapter_no > 0]
        return (min(nos), max(nos)) if nos else (-1, -1)

    @property
    def kind_name(self) -> str:
        return KIND_NAMES.get(self.kind, self.kind)

    def to_dict(self, *, limit: int = EXCERPT_CHARS) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "kind": self.kind,
            "kind_name": self.kind_name,
            "occurrences": int(self.occurrences),
            "max_similarity": round(float(self.max_similarity), 6),
            "min_similarity": round(float(self.min_similarity), 6),
            "cross_chapter": bool(self.cross_chapter),
            "chapter_span": list(self.chapter_span),
            "adjacent_runs": int(self.adjacent_runs),
            "pair_count": len(self.pair_indices),
            # 组的成员由「对」连通而来，E7 要按组回查那几对（相似度分档展示）
            "pair_indices": [int(i) for i in self.pair_indices],
            "first_position": int(self.first_position),
            "members": [
                {
                    "paragraph_index": int(m.index),
                    "chapter_no": int(m.chapter_no),
                    "chapter_title": m.chapter_title,
                    "line_start": int(m.line_start),
                    "line_end": int(m.line_end),
                    "char_start": int(m.char_start),
                    "char_end": int(m.char_end),
                    "chars": m.chars,
                    "text": m.excerpt(limit),
                }
                for m in self.members
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DuplicateGroup":
        members: list[ParagraphRef] = []
        for m in data.get("members") or []:
            members.append(ParagraphRef(
                index=int(m["paragraph_index"]),
                text=str(m.get("text", "")),
                line_start=int(m["line_start"]),
                line_end=int(m["line_end"]),
                char_start=int(m.get("char_start", 0)),
                char_end=int(m.get("char_end", 0)),
                chapter_no=int(m.get("chapter_no", -1)),
                chapter_title=str(m.get("chapter_title", "")),
            ))
        return cls(
            group_id=str(data["group_id"]),
            kind=str(data["kind"]),
            members=members,
            pair_indices=[int(i) for i in data.get("pair_indices") or []],
            max_similarity=float(data.get("max_similarity", 0.0)),
            min_similarity=float(data.get("min_similarity", 0.0)),
            adjacent_runs=int(data.get("adjacent_runs", 0)),
        )


@dataclass
class DuplicateReport:
    """一次检测的全部结果（E7 的唯一输入）。

    ``pairs`` 是判定单位，也是**阈值单调性的口径**；``groups`` 是由 ``pairs``
    连通出来的清单视图。两者一起给，是因为清单要分组、验收要对数。
    """

    threshold: float
    min_chars: int
    paragraph_count: int
    chapter_count: int
    pairs: list[DuplicatePair] = field(default_factory=list)
    groups: list[DuplicateGroup] = field(default_factory=list)
    elapsed_ms: int = 0
    options: dict[str, Any] = field(default_factory=dict)
    #: 本次检测用的段落表（E7 要显示全文与跳转，报告自带这份表就不用另找书稿）。
    #: ``groups[*].members[*].text`` 是截断后的摘要，全文一律从这里取。
    paragraphs: list[ParagraphRef] = field(default_factory=list)

    # ---- 查询 ------------------------------------------------------

    def paragraph(self, index: int) -> ParagraphRef | None:
        """按段落序号取完整段落（越界返回 ``None``）。"""
        if 0 <= index < len(self.paragraphs):
            return self.paragraphs[index]
        return None

    def texts_of(self, pair: DuplicatePair) -> tuple[str, str]:
        """一对命中的两侧全文（清单展开、对比视图直接用）。"""
        left = self.paragraph(pair.left)
        right = self.paragraph(pair.right)
        return (left.text if left else "", right.text if right else "")

    # ---- 计数 ------------------------------------------------------

    def _pairs_of(self, kind: str) -> list[DuplicatePair]:
        return [p for p in self.pairs if p.kind == kind]

    @property
    def exact_pairs(self) -> list[DuplicatePair]:
        return self._pairs_of(KIND_EXACT)

    @property
    def similar_pairs(self) -> list[DuplicatePair]:
        return self._pairs_of(KIND_SIMILAR)

    @property
    def exact_groups(self) -> list[DuplicateGroup]:
        return [g for g in self.groups if g.kind == KIND_EXACT]

    @property
    def similar_groups(self) -> list[DuplicateGroup]:
        return [g for g in self.groups if g.kind == KIND_SIMILAR]

    @property
    def cross_chapter_pairs(self) -> int:
        return sum(1 for p in self.pairs if p.cross_chapter)

    @property
    def involved_paragraphs(self) -> int:
        out: set[int] = set()
        for p in self.pairs:
            out.add(p.left)
            out.add(p.right)
        return len(out)

    # ---- 清单视图 --------------------------------------------------

    def sorted_groups(self, order: str = ORDER_BY_COUNT) -> list[DuplicateGroup]:
        """按 E7 的三种排序方式返回分组（返回新列表，不动原顺序）。"""
        groups = list(self.groups)
        if order == ORDER_BY_POSITION:
            return sorted(groups, key=lambda g: (g.first_position, -g.occurrences))
        if order == ORDER_BY_SIMILARITY:
            return sorted(groups, key=lambda g: (-g.max_similarity, g.first_position))
        if order == ORDER_BY_COUNT:
            return sorted(groups, key=lambda g: (-g.occurrences, g.first_position))
        raise ValueError(f"未知排序方式：{order}，可选 {sorted(ORDER_NAMES)}")

    def pairs_of_group(self, group: DuplicateGroup) -> list[DuplicatePair]:
        return [self.pairs[i] for i in group.pair_indices
                if 0 <= i < len(self.pairs)]

    def summary(self) -> str:
        """一句人话小结（可直接进清单页顶部或评论）。"""
        if not self.pairs:
            return (f"共 {self.paragraph_count} 段，没有发现重复段落"
                    f"（相似度阈值 {self.threshold:.2f}，最短 {self.min_chars} 字）。")
        return (
            f"共 {self.paragraph_count} 段，检出 {len(self.groups)} 组重复，"
            f"涉及 {self.involved_paragraphs} 段："
            f"完全重复 {len(self.exact_groups)} 组、"
            f"相似重复 {len(self.similar_groups)} 组；"
            f"其中跨章 {self.cross_chapter_pairs} 对"
            f"（相似度阈值 {self.threshold:.2f}，最短 {self.min_chars} 字）。"
        )

    # ---- 序列化 ----------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "paragraphs": int(self.paragraph_count),
            "chapters": int(self.chapter_count),
            "pairs": len(self.pairs),
            "exact_pairs": len(self.exact_pairs),
            "similar_pairs": len(self.similar_pairs),
            "groups": len(self.groups),
            "exact_groups": len(self.exact_groups),
            "similar_groups": len(self.similar_groups),
            "cross_chapter_pairs": int(self.cross_chapter_pairs),
            "involved_paragraphs": int(self.involved_paragraphs),
            "elapsed_ms": int(self.elapsed_ms),
        }

    def to_dict(self, *, limit: int = EXCERPT_CHARS,
                include_paragraphs: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "threshold": round(float(self.threshold), 6),
            "min_chars": int(self.min_chars),
            "paragraph_count": int(self.paragraph_count),
            "chapter_count": int(self.chapter_count),
            "elapsed_ms": int(self.elapsed_ms),
            "options": dict(self.options),
            "stats": self.stats(),
            "pairs": [p.to_dict() for p in self.pairs],
            "groups": [g.to_dict(limit=limit) for g in self.groups],
        }
        if include_paragraphs:
            # 带全文才能让 E7 离线复现清单（截断摘要不足以做对比视图）
            data["paragraphs"] = [p.to_dict() for p in self.paragraphs]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DuplicateReport":
        raw_paragraphs = data.get("paragraphs")
        paragraphs = [ParagraphRef.from_dict(p) for p in raw_paragraphs or []]
        return cls(
            threshold=float(data["threshold"]),
            min_chars=int(data["min_chars"]),
            paragraph_count=int(data.get("paragraph_count", len(paragraphs))),
            chapter_count=int(data.get("chapter_count", 0)),
            pairs=[DuplicatePair.from_dict(p) for p in data.get("pairs") or []],
            groups=[DuplicateGroup.from_dict(g) for g in data.get("groups") or []],
            elapsed_ms=int(data.get("elapsed_ms", 0)),
            options=dict(data.get("options") or {}),
            paragraphs=paragraphs,
        )

    def to_json(self, *, indent: int | None = None, limit: int = EXCERPT_CHARS,
                include_paragraphs: bool = True) -> str:
        return json.dumps(
            self.to_dict(limit=limit, include_paragraphs=include_paragraphs),
            ensure_ascii=False, indent=indent, sort_keys=False)

    @classmethod
    def from_json(cls, payload: str) -> "DuplicateReport":
        return cls.from_dict(json.loads(payload))

    def payload(self) -> dict[str, Any]:
        """给清单页直接消费的紧凑视图（分组 + 成员位置 + 段落全文索引）。

        ``groups`` 里的成员是「位置 + 截断摘要」，段落全文按
        ``paragraph_index`` 在 ``paragraphs`` 里查——清单展开一条时就不用
        再回书稿取文本。
        """
        index_of: dict[int, dict[str, Any]] = {}
        for p in self.paragraphs:
            index_of[p.index] = {
                "chapter_no": p.chapter_no,
                "chapter_title": p.chapter_title,
                "line_start": p.line_start,
                "line_end": p.line_end,
                "chars": p.chars,
                "text": p.text,
            }
        return {
            "threshold": round(float(self.threshold), 6),
            "min_chars": int(self.min_chars),
            "paragraph_count": int(self.paragraph_count),
            "chapter_count": int(self.chapter_count),
            "stats": self.stats(),
            "groups": [g.to_dict() for g in self.sorted_groups(ORDER_BY_COUNT)],
            "paragraphs": index_of,
        }


def pairs_from_reports(reports: Iterable[DuplicateReport]) -> list[DuplicatePair]:
    """把多次检测（例如同一本书用不同阈值跑）的命中并起来（按对去重取最高分）。"""
    merged: dict[tuple[int, int], DuplicatePair] = {}
    for rep in reports:
        for p in rep.pairs:
            old = merged.get(p.key)
            if old is None or p.similarity > old.similarity:
                merged[p.key] = p
    return sorted(merged.values(), key=lambda p: (p.left, p.right))


def group_by_chapters(members: Sequence[ParagraphRef]) -> dict[int, list[ParagraphRef]]:
    """按章分桶（E7 想按章折叠展示时用）。"""
    buckets: dict[int, list[ParagraphRef]] = {}
    for m in members:
        buckets.setdefault(m.chapter_index, []).append(m)
    return buckets
