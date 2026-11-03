"""校正前后对比的差异数据层（V1.1 · E1）
=========================================

给「对比视图」（E2）提供**一份可直接渲染的差异项清单**。本模块不依赖 Qt，
只做数据：读一次运行已有的产物 → 算出差异项 → 交出与替换统计同口径的计数。

为什么是「复用」而不是「另造 diff」
------------------------------------

差异定义在既有链路里已经存在两处权威实现，本层不重算它们的口径：

* **差异从哪来**：``fixtext_bookmap.patcher`` 的 ``generate_patch`` /
  ``PatchAnalyzer``。M1 的替换阶段与导出统计都走这一条，本层同样调用它，
  只是额外保留**行号**（``PatchAnalyzer`` 只返回文本对，不返回位置）。
* **计数口径**：``fixtext_export._count_hits``。它决定「替换统计 N 处」的 N，
  本层逐槽同构地复算一遍，用来证明差异项条数与替换报告不矛盾。
* **前后文从哪来**：``fixtext_run_snapshot.resolve_artifacts`` 已能定位
  ``before_text`` / ``after_text`` / ``ledger``，本层不另建快照。

因此本层只补两件既有代码没有的东西：**位置（章 / 行 / 列）** 和
**可验证的规则归属**。

三个数字，先说清楚关系
----------------------

同一本书的「替换统计」与「差异项清单」不是同一个量，硬凑会造出假数据。
以 301 章的验收样书为例，实测结构如下：

```text
patch 里 304 个 hunk 块
  └─ 逐块按行拆成 542 个「行对」（N 删 N 增 → N 对）
       ├─ 24 个行对的片段贴着 HTML 标签边缘，Option.add_html_stripped_copy
       │   额外产出一份去标签副本 → 542 + 24 = 566 条词条
       └─ 542 个行对 → 542 条差异项（一条行对一条，不去重、不合并）
hits（替换统计 N 处）= 566（按「改前【FixText 替换为】改后」聚合后求和）
```

这条等式在样例书上恰好写成 ``hits = 差异项数 + 去标签副本数``，因为
那本书里没有「一侧为空」的行对。一般情形是
``hits = 计入词条的差异项数 + 去标签副本数``：既有口径会把一侧为空的
纯新增 / 纯删除行对整条丢掉（``php_truthy`` 把空串当假），它们有差异但
不计 hits。本层用 :attr:`DiffReport.hit_eligible` 把这批行对单独记账，
``hit_gap`` 因此恒为 0——差额不是被抹掉，而是被逐项解释清楚了。

已知边界
--------

* **一条差异项 ≠ 一次替换**。同一行里出现两处同样的替换
  （``甲萧衍乙萧衍丙 → 甲萧彦乙萧彦丙``）在既有口径下仍是 1 条词条 / 1 次
  hits。差异项按「行对」计，因此也是 1 条。界面上要展示"这一行改了几处"，
  得看 :attr:`DiffItem.occurrences` 与下面的 ``char_spans``，不能用 hits 推。
* **跨行差异**（patch 里带字面量 ``\\n`` 的对）在替换统计里被过滤掉
  （``Option.get_multi_line_content=False``），本层同样标为 ``kind="multi_line"``
  并计入 :attr:`DiffReport.multi_line_count`，**不计入 hits 对齐量**。
* **规则归属是可验证推断，不是引擎自述**。引擎只吐「执行了 N 次替换」这一个
  数字，不吐命中了哪条规则。本层用「拿规则重放这一行能否得到该行的改后
  文本」来判定归属：能重放出来的才填 ``rule_before`` / ``rule_after``，
  重放不出来的诚实留空并标 ``attribution="unverified"``。
"""

from __future__ import annotations

import json
import re
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

#: 差异项类型：行内替换 / 仅新增 / 仅删除 / 跨行差异
KIND_REPLACE = "replace"
KIND_INSERT = "insert"
KIND_DELETE = "delete"
KIND_MULTI_LINE = "multi_line"

#: 规则归属的可信度
ATTR_VERIFIED = "verified"      # 重放出改后文本，且规则唯一
ATTR_VERIFIED_SET = "verified_set"  # 需多条规则组合才能重放，已记下这组规则
ATTR_UNVERIFIED = "unverified"  # 重放不出来，字段留空，不编造
ATTR_NO_RULES = "no_rules"      # 本次运行没留下派生规则文件

#: 位置精度
LOCATE_EXACT = "exact"          # 行号 + 行内字符区间都有
LOCATE_LINE = "line"            # 只有行号（跨行差异等）
LOCATE_CHAPTER = "chapter"      # 只定位到章

#: 行内字符区间最多给出多少段（避免一次替换在长行里被拆成上百段）
MAX_CHAR_SPANS = 40

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_LITERAL_N = "\\n"
_CHAP_TITLE_RE = re.compile(
    r'<h[1-6][^>]*class="[^"]*chap-title[^"]*"[^>]*>(?P<body>.*?)</h[1-6]>', re.S | re.I
)
_TAG_RE = re.compile(r"<[^>]+>")

#: 规则归属穷举的候选上限。超过这个数就不再穷举组合，
#: 直接判 unverified——宁可空着，也不给一个可能错的组合。
MAX_ATTR_CANDIDATES = 8
#: 规则重放允许的最大遍数（引擎默认两遍，见 ``ReplaceStage`` 的 pass 数）
MAX_REPLAY_PASSES = 2


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class SideRef:
    """一侧（改前 / 改后）里的位置。

    :param chapter_index: 章节在合并文本里的顺序号；定位不到时为 ``-1``
    :param chapter_path:  该章在书内（EPUB）的相对路径
    :param chapter_title: 人可读的章节标题（取章节内 ``chap-title``，取不到用章标签）
    :param line:          合并文本里的 **1 基** 行号；0 表示未知
    :param char_start:    行内 **0 基** 起止字符下标（闭开区间）
    :param char_end:      同上
    """

    chapter_index: int = -1
    chapter_path: str = ""
    chapter_title: str = ""
    line: int = 0
    char_start: int = -1
    char_end: int = -1

    @property
    def located(self) -> bool:
        return self.line > 0

    def to_dict(self) -> dict:
        return {
            "chapter_index": self.chapter_index,
            "chapter_path": self.chapter_path,
            "chapter_title": self.chapter_title,
            "line": self.line,
            "char_start": self.char_start,
            "char_end": self.char_end,
        }


@dataclass
class DiffItem:
    """一条差异项。E2 的左右对比与跳转都靠它。

    一条差异项 = patch 里的一个「行对」（N 删 N 增的块按行拆成 N 对），
    因此左右两侧的行号是确定的、可并列渲染的。
    """

    index: int
    kind: str
    #: 改前 / 改后 的整块文本（跨行差异里用字面量 ``\\n`` 连接，与既有口径一致）
    before_text: str
    after_text: str
    #: 仅覆盖差异字符 + 上下文的短片段，供气泡/高亮用；跨行差异等于整块
    before_snippet: str
    after_snippet: str
    #: 两侧位置
    before: SideRef
    after_ref: SideRef
    #: 行内差异的字符区间清单（相对 ``before.line`` 的行首，0 基闭开区间）
    char_spans: list[tuple[int, int]] = field(default_factory=list)
    #: 这一行里命中了几处（同一替换重复出现时 > 1）
    occurrences: int = 1
    #: 规则归属：能重放验证才填，否则留空
    attribution: str = ATTR_UNVERIFIED
    rule_before: str = ""
    rule_after: str = ""
    #: 组合归属时记下的那组规则（元素为 ``[before, after]``）
    rule_set: list[tuple[str, str]] = field(default_factory=list)
    #: 该行是否因贴 HTML 标签而额外生成了去标签副本（解释 hits 差额）
    has_stripped_copy: bool = False

    def to_dict(self) -> dict:
        """可 JSON 序列化的扁平结构——E2 直接拿它渲染。"""
        return {
            "index": self.index,
            "kind": self.kind,
            "before_text": self.before_text,
            "after_text": self.after_text,
            "before_snippet": self.before_snippet,
            "after_snippet": self.after_snippet,
            "before": self.before.to_dict(),
            "after": self.after_ref.to_dict(),
            "char_spans": [list(sp) for sp in self.char_spans],
            "occurrences": self.occurrences,
            "attribution": self.attribution,
            "rule_before": self.rule_before,
            "rule_after": self.rule_after,
            "rule_set": [list(p) for p in self.rule_set],
            "has_stripped_copy": self.has_stripped_copy,
        }


@dataclass
class DiffReport:
    """一次对比的全部结果 + 与替换统计的核对数据。"""

    items: list[DiffItem] = field(default_factory=list)
    #: 章节表（顺序与合并文本一致），供界面建目录树
    chapters: list[dict] = field(default_factory=list)
    #: 差异项条数（= 行对数）
    item_count: int = 0
    #: 按替换统计口径复算出的 hits；解析不出来时为 ``-1``
    hits: int = 0
    #: 替换统计里被判为跨行而丢弃的对数
    multi_line_count: int = 0
    #: 差异项里「按既有口径会变成词条」的条数（一侧为空的纯增/删不计入）
    hit_eligible: int = 0
    #: 因去标签副本而比词条多出来的份数
    stripped_copies: int = 0
    #: ``hits - (hit_eligible + stripped_copies)``；正常应为 0
    hit_gap: int = 0
    #: 本次是否真的做了 hits 复算（没有 before/after 时为 False）
    hits_verified: bool = False
    before_path: str = ""
    after_path: str = ""
    ledger_path: str = ""
    rules_source: str = ""
    #: 无法验证归属的条数，单独拎出来给验收说明用
    unverified_count: int = 0

    def to_dict(self) -> dict:
        return {
            "items": [item.to_dict() for item in self.items],
            "chapters": self.chapters,
            "summary": {
                "item_count": self.item_count,
                "hits": self.hits,
                "multi_line_count": self.multi_line_count,
                "hit_eligible": self.hit_eligible,
                "stripped_copies": self.stripped_copies,
                "hit_gap": self.hit_gap,
                "hits_verified": self.hits_verified,
                "unverified_count": self.unverified_count,
                "before_path": self.before_path,
                "after_path": self.after_path,
                "ledger_path": self.ledger_path,
                "rules_source": self.rules_source,
            },
            "chapters": self.chapters,
        }

    def items_of_chapter(self, index: int) -> list[DiffItem]:
        """取某一章的差异项（E2 章节目录点击跳转用）。"""
        return [i for i in self.items if i.before.chapter_index == index]


# ---------------------------------------------------------------------------
# patch 解析（带行号）
# ---------------------------------------------------------------------------
@dataclass
class _Pair:
    """一个行对 + 两侧行号。"""

    before_text: str
    after_text: str
    before_line: int
    after_line: int
    kind: str
    span_lines: int = 1


def _php_truthy(value: str) -> bool:
    """PHP 的 falsy 判定（空串与 ``"0"`` 都为假），与既有口径保持一致。"""
    return bool(value) and value != "0"


def _mergeable(before_lines: list[str], after_lines: list[str]) -> bool:
    """是否应当按行拆成多对（复刻 ``PatchAnalyzer.should_merge_as_multi_line``）。"""
    if len(before_lines) != len(after_lines):
        return False
    for bv, av in zip(before_lines, after_lines):
        if bv == av:
            return False
        if (bv == "" and _php_truthy(av)) or (_php_truthy(bv) and av == ""):
            return False
    return True


class PatchLineIndex:
    """把 patch 拆成「行对 + 行号」。

    为什么不能直接用 :class:`PatchAnalyzer`
    ---------------------------------------

    它的输出只有 ``(befores, afters)`` 两串文本，**没有位置**。E2 要在左右
    两栏并列高亮并跳转，必须知道每一对在合并文本的第几行。本类的解析规则
    与它逐条对齐（同样丢前 2 行头、同样按 ``php_ltrim`` 剥 ``-``/``+``、
    同样用字面量 ``\\n`` 拼跨行、同样按 ``should_merge_as_multi_line`` 决定
    拆行还是合并），差别只在多记了行号。

    一致性由 ``tests/test_e1_diff_view.py`` 逐条比对保证：同一份 patch 上，
    本类产出的 (before_text, after_text) 序列必须与 ``PatchAnalyzer`` 完全相同。
    """

    def __init__(self) -> None:
        self.pairs: list[_Pair] = []

    @classmethod
    def from_patch_text(cls, text: str) -> "PatchLineIndex":
        self = cls()
        self._parse(text)
        return self

    def _parse(self, text: str) -> None:
        lines = text.split("\n")
        # 与 PatchAnalyzer 一致：丢弃前 2 行文件头
        lines = lines[2:]

        state: dict | None = None
        bline = 0
        aline = 0

        def flush_block(block: dict) -> None:
            dels = [d for d in block["lines"] if d[0] == "del"]
            ins = [d for d in block["lines"] if d[0] == "ins"]
            if dels and ins:
                db = [d[2] for d in dels]
                da = [d[2] for d in ins]
                if _mergeable(db, da):
                    for i in range(len(dels)):
                        self.pairs.append(_Pair(
                            before_text=dels[i][2], after_text=ins[i][2],
                            before_line=dels[i][1], after_line=ins[i][1],
                            kind=KIND_REPLACE, span_lines=1,
                        ))
                else:
                    self.pairs.append(_Pair(
                        before_text=_LITERAL_N.join(db), after_text=_LITERAL_N.join(da),
                        before_line=dels[0][1], after_line=ins[0][1],
                        kind=KIND_REPLACE, span_lines=len(dels),
                    ))
            elif dels:
                for d in dels:
                    self.pairs.append(_Pair(
                        before_text=d[2], after_text="", before_line=d[1],
                        after_line=0, kind=KIND_DELETE,
                    ))
            elif ins:
                for d in ins:
                    self.pairs.append(_Pair(
                        before_text="", after_text=d[2], before_line=0,
                        after_line=d[1], kind=KIND_INSERT,
                    ))

        for line in lines:
            m = _HUNK_RE.match(line)
            if m:
                if state is not None:
                    flush_block(state)
                state = None
                bline = int(m.group(1))
                aline = int(m.group(3))
                continue
            if line.startswith("\\"):
                # "\ No newline at end of file" 之类的标记行，无内容
                continue
            if line.startswith("-") and not line.startswith("--"):
                if state is None or state["kind"] == "ctx":
                    state = {"kind": "diff", "lines": []}
                state["lines"].append(("del", bline, line[1:]))
                bline += 1
            elif line.startswith("+") and not line.startswith("++"):
                if state is None or state["kind"] == "ctx":
                    state = {"kind": "diff", "lines": []}
                state["lines"].append(("ins", aline, line[1:]))
                aline += 1
            elif line.startswith(" "):
                if state is not None:
                    flush_block(state)
                state = {"kind": "ctx", "lines": []}
                bline += 1
                aline += 1
            else:
                if state is not None:
                    flush_block(state)
                state = None

        if state is not None:
            flush_block(state)

    def texts(self) -> tuple[list[str], list[str]]:
        return ([p.before_text for p in self.pairs],
                [p.after_text for p in self.pairs])


# ---------------------------------------------------------------------------
# 章节定位
# ---------------------------------------------------------------------------
class ChapterMap:
    """合并文本里「第几行属于哪一章」。

    既有 ``epubtext.bundle.split_bundle`` 已经把合并文本按章切开并做三重校验，
    但它不记行号。本类复刻它的切分规则（同一套 ``SPLIT_RE``、同样的严格校验），
    在切的同时记下每章起始行号，供差异项定位。

    :param strict: 与 ``split_bundle`` 同义；缺标记时不抛错，只是定位退化到
        ``LOCATE_LINE`` / ``LOCATE_CHAPTER``。
    """

    def __init__(self, text: str, ledger=None, strict: bool = True) -> None:
        self.chapters: list[dict] = []
        self._starts: list[int] = []
        self._build(text, ledger, strict)

    def _build(self, text: str, ledger, strict: bool) -> None:
        try:
            from epubtext.bundle import (BOOK_RE, HEADER_RE, SPLIT_RE,
                                         parse_attrs)
        except Exception:  # pragma: no cover - 缺依赖时退化
            return

        labels: list[str] = []
        if ledger is not None:
            try:
                labels = [c.label for c in ledger.chapters]
            except Exception:
                labels = []

        starts: list[int] = []
        markers: list[dict] = []
        header_seen = False
        lines = text.split("\n")
        for lineno, line in enumerate(lines, start=1):
            stripped = line.rstrip("\r")
            if HEADER_RE.match(stripped) and not header_seen and not markers:
                header_seen = True
                continue
            if BOOK_RE.match(stripped):
                continue
            m = SPLIT_RE.match(stripped)
            if m:
                attrs = parse_attrs(m.group("body"))
                attrs["index"] = m.group("index")
                attrs["nonce"] = m.group("nonce")
                markers.append(attrs)
                starts.append(lineno + 1)

        self._starts = starts
        for pos, marker in enumerate(markers):
            body = self._chapter_body(text, pos, starts)
            label = marker.get("label", "") or (labels[pos] if pos < len(labels) else "")
            # 章节标题优先用章内的 chap-title（人读得懂），取不到才退回章标签
            title = self._chapter_title(body) or label
            self.chapters.append({
                "index": int(marker.get("index", pos)),
                "path": marker.get("path", ""),
                "label": label,
                "title": title,
                "start_line": starts[pos],
                "end_line": (starts[pos + 1] - 1) if pos + 1 < len(starts) else len(lines),
            })

        if strict and ledger is not None:
            try:
                from epubtext.bundle import BundleFormatError
                expected = ledger.chapters
                if len(markers) != len(expected):
                    raise BundleFormatError(
                        f"切出 {len(markers)} 章，账本记录 {len(expected)} 章，数量不一致")
            except ImportError:  # pragma: no cover
                pass

    def _chapter_body(self, text: str, pos: int, starts: list[int]) -> str:
        begin = starts[pos] - 1
        end = (starts[pos + 1] - 2) if pos + 1 < len(starts) else None
        lines = text.split("\n")[begin:end]
        return "\n".join(lines)

    @staticmethod
    def _chapter_title(body: str) -> str:
        m = _CHAP_TITLE_RE.search(body)
        if not m:
            return ""
        return _TAG_RE.sub("", m.group("body")).strip()

    def chapter_of_line(self, line: int) -> int:
        """行号 → 章节序号（找不到返回 ``-1``）。"""
        if line <= 0 or not self._starts:
            return -1
        idx = 0
        for pos, start in enumerate(self._starts):
            if start <= line:
                idx = pos
            else:
                break
        return idx


# ---------------------------------------------------------------------------
# 规则归属
# ---------------------------------------------------------------------------
class RuleIndex:
    """派生规则的「按首字符倒排」索引 + 可验证重放。

    只读 ``workspace/vocab/derived_rules/<round>/before.json`` / ``after.json``
    这两个**运行时产物**，不碰装载层（``vocab_bridge.compose()`` /
    ``bags.write_round_rules()``）——那是 B3 / C1 的专属入口。

    归属的判定方式是「可验证重放」而不是「字符串包含猜一猜」：拿候选规则
    把这一行的改前文本重放成改后文本，成功才认这条规则。纯 Python 实现，
    只用「首字符倒排 + 逐位置比对」，不引入第三方多模式匹配库——那种库
    只是 Python 降级引擎的内部实现，不该成为 UI 数据层的依赖。
    """

    def __init__(self, before_rules: list[str], after_rules: list[str],
                 passes: int = MAX_REPLAY_PASSES) -> None:
        if len(before_rules) != len(after_rules):
            raise ValueError("派生规则的 before / after 条数不一致")
        self.before_rules = list(before_rules)
        self.after_rules = list(after_rules)
        self.passes = max(1, int(passes))
        self._by_head: dict[str, list[int]] = {}
        for i, word in enumerate(self.before_rules):
            if word:
                self._by_head.setdefault(word[0], []).append(i)

    def __len__(self) -> int:
        return len(self.before_rules)

    # -- 索引 ----------------------------------------------------------- #
    def candidates(self, text: str) -> list[int]:
        """这一行里出现过的所有规则下标（按首字符倒排后逐位置比对）。"""
        found: set[int] = set()
        n = len(text)
        for pos in range(n):
            for i in self._by_head.get(text[pos], ()):
                word = self.before_rules[i]
                if word and text.startswith(word, pos):
                    found.add(i)
        return sorted(found)

    # -- 重放 ----------------------------------------------------------- #
    def _replace_once(self, text: str, rule_ids: list[int]) -> str:
        """单遍、不重叠、按给定顺序 first-wins——贴近 ``strings.NewReplacer``。"""
        out: list[str] = []
        i = 0
        n = len(text)
        order = list(rule_ids)
        while i < n:
            for rid in order:
                word = self.before_rules[rid]
                if word and text.startswith(word, i):
                    out.append(self.after_rules[rid])
                    i += len(word)
                    break
            else:
                out.append(text[i])
                i += 1
        return "".join(out)

    def replay(self, text: str, rule_ids: list[int]) -> str:
        current = text
        for _ in range(self.passes):
            current = self._replace_once(current, rule_ids)
        return current

    def attribute(self, before_line: str, after_line: str) -> dict:
        """给一行找归属规则。

        :return: ``{"attribution":…, "rule_before":…, "rule_after":…, "rule_set":[…],
                   "occurrences":…}``
                 找不到可验证组合时 ``attribution="unverified"``、规则字段留空。
        """
        cands = [i for i in self.candidates(before_line)
                 if self.before_rules[i] in before_line]
        if not cands:
            return {"attribution": ATTR_UNVERIFIED, "rule_before": "", "rule_after": "",
                    "rule_set": [], "occurrences": 1}

        # 1) 单条规则能整行解释
        for i in cands:
            if self.replay(before_line, [i]) == after_line:
                return {
                    "attribution": ATTR_VERIFIED,
                    "rule_before": self.before_rules[i],
                    "rule_after": self.after_rules[i],
                    "rule_set": [(self.before_rules[i], self.after_rules[i])],
                    "occurrences": before_line.count(self.before_rules[i]) or 1,
                }

        if len(cands) > MAX_ATTR_CANDIDATES:
            return {"attribution": ATTR_UNVERIFIED, "rule_before": "", "rule_after": "",
                    "rule_set": [], "occurrences": 1}

        # 2) 多条规则组合能整行解释（组合数有限：<=8 候选，<=255 组）
        import itertools
        for size in range(2, len(cands) + 1):
            for combo in itertools.combinations(cands, size):
                if self.replay(before_line, list(combo)) == after_line:
                    return {
                        "attribution": ATTR_VERIFIED_SET,
                        "rule_before": "",
                        "rule_after": "",
                        "rule_set": [(self.before_rules[i], self.after_rules[i])
                                     for i in combo],
                        "occurrences": 1,
                    }
        return {"attribution": ATTR_UNVERIFIED, "rule_before": "", "rule_after": "",
                "rule_set": [], "occurrences": 1}

    @classmethod
    def from_paths(cls, before_path, after_path) -> "RuleIndex":
        before = json.loads(Path(before_path).read_text(encoding="utf-8"))
        after = json.loads(Path(after_path).read_text(encoding="utf-8"))
        return cls(before, after)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def build_diff(before_text: str, after_text: str, *,
               ledger=None,
               rules: RuleIndex | None = None,
               before_path: str = "",
               after_path: str = "",
               ledger_path: str = "",
               rules_source: str = "",
               patch_text: str | None = None,
               verify_hits: bool = True) -> DiffReport:
    """算出两份正文之间的差异项清单。

    :param before_text: 改前正文（合并 / 排版后的完整文本，含章标记）
    :param after_text:  改后正文
    :param ledger:      ``epubtext.bundle.Ledger``，用于定位章节；可省略
    :param rules:       :class:`RuleIndex`，省略时差异项 ``attribution`` 全为
                        ``no_rules``
    :param patch_text:  已有 patch 文本时直接复用，避免重复生成 patch
    :param verify_hits: 是否复算替换统计口径的 hits（大书可关掉省时间）
    """
    report = DiffReport(
        before_path=str(before_path or ""),
        after_path=str(after_path or ""),
        ledger_path=str(ledger_path or ""),
        rules_source=str(rules_source or ""),
    )

    if patch_text is None:
        patch_text = _generate_patch_text(before_text, after_text)

    index = PatchLineIndex.from_patch_text(patch_text)
    chapmap = ChapterMap(before_text, ledger, strict=False)
    report.chapters = chapmap.chapters

    before_lines = before_text.split("\n")
    after_lines = after_text.split("\n")

    for pos, pair in enumerate(index.pairs):
        item = _build_item(pos, pair, chapmap, before_lines, after_lines, rules)
        report.items.append(item)
        if item.kind == KIND_MULTI_LINE:
            report.multi_line_count += 1

    report.item_count = len(report.items)
    report.unverified_count = sum(
        1 for i in report.items if i.attribution == ATTR_UNVERIFIED)

    if verify_hits:
        stats = _verify_hit_parity(before_text, after_text, report.items)
        report.hits = stats["hits"]
        report.hit_eligible = stats["hit_eligible"]
        report.stripped_copies = stats["stripped_copies"]
        report.hit_gap = report.hits - (report.hit_eligible + report.stripped_copies)
        report.hits_verified = True

    return report


def build_diff_for_run(run_dir, *, rules_dir=None, verify_hits: bool = True) -> DiffReport:
    """从一次运行的产物目录直接算出差异项（复用既有快照定位能力）。

    前后正文与账本一律走 ``fixtext_run_snapshot.resolve_artifacts``，
    不另建一套快照；派生规则只在给定了 ``rules_dir``（或运行工作区里确实
    存在 ``vocab/derived_rules/round_main/``）时才读，读不到就把归属标成
    ``no_rules``，不猜。
    """
    from fixtext_run_snapshot import resolve_artifacts

    work_dir = _resolve_work_dir(run_dir)
    arts = resolve_artifacts(work_dir)
    before_path = arts.get("before_text", "")
    after_path = arts.get("after_text", "")
    if not before_path or not after_path:
        raise FileNotFoundError("运行目录里找不到替换阶段的改前 / 改后正文")

    before_text = Path(before_path).read_text(encoding="utf-8")
    after_text = Path(after_path).read_text(encoding="utf-8")

    ledger = None
    ledger_path = arts.get("ledger", "")
    if ledger_path:
        try:
            from epubtext.bundle import Ledger
            ledger = Ledger.load(ledger_path)
        except Exception:
            ledger = None

    rule_index = None
    source = ""
    if rules_dir is None:
        rules_dir = _default_derived_rules_dir(work_dir)
    if rules_dir is not None:
        rules_dir = Path(rules_dir)
        b = rules_dir / "before.json"
        a = rules_dir / "after.json"
        if b.is_file() and a.is_file():
            rule_index = RuleIndex.from_paths(b, a)
            source = str(rules_dir)

    report = build_diff(
        before_text, after_text,
        ledger=ledger, rules=rule_index,
        before_path=before_path, after_path=after_path,
        ledger_path=ledger_path, rules_source=source,
        verify_hits=verify_hits,
    )
    if rule_index is None:
        for item in report.items:
            item.attribution = ATTR_NO_RULES
        report.unverified_count = 0
    return report


# ---------------------------------------------------------------------------
# 内部实现
# ---------------------------------------------------------------------------
def _resolve_work_dir(run_dir) -> Path:
    """一次运行有两级目录：``runs/<run>/`` 与真正干活用的 ``runs/<run>/work/``。

    既有 ``resolve_artifacts`` 认的是后者（阶段产物都在那下面）。这里先按
    历史页的口径找 ``work/``，找不到再退回传入目录本身——两种调用方都不至于
    拿到空结果。
    """
    run = Path(run_dir)
    work = run / "work"
    return work if work.is_dir() else run


def _default_derived_rules_dir(work_dir) -> Path | None:
    """按既有约定找出派生规则目录：``<包根>/workspace/vocab/derived_rules/round_main``。

    与 ``main_window`` 注入的 ``derived_rules_dir`` 是同一处约定
    （``PKG_ROOT / "workspace" / "vocab"``），这里复用
    ``import_module.default_workspace()`` 而不是自己从 ``__file__`` 往上推，
    免得两处路径规则走散。
    """
    from import_module import default_workspace

    base = Path(default_workspace()) / "vocab" / "derived_rules" / "round_main"
    return base if base.is_dir() else None


def _generate_patch_text(before_text: str, after_text: str) -> str:
    """用既有 ``generate_patch`` 产 patch，再读回文本（不自己造 diff）。"""
    import tempfile

    from fixtext_bookmap.patcher import generate_patch

    with tempfile.TemporaryDirectory() as tmp:
        b = Path(tmp) / "before.txt"
        a = Path(tmp) / "after.txt"
        p = Path(tmp) / "diff.patch"
        b.write_text(before_text, encoding="utf-8")
        a.write_text(after_text, encoding="utf-8")
        generate_patch(str(b), str(a), str(p))
        return p.read_text(encoding="utf-8", errors="surrogateescape")


def _build_item(pos: int, pair: _Pair, chapmap: ChapterMap,
                before_lines: list[str], after_lines: list[str],
                rules: RuleIndex | None) -> DiffItem:
    posix = pair.before_text.find(_LITERAL_N)
    multi = posix >= 0 or pair.after_text.find(_LITERAL_N) >= 0

    if multi:
        kind = KIND_MULTI_LINE
        snippet_b = pair.before_text
        snippet_a = pair.after_text
    else:
        kind = pair.kind
        snippet_b, snippet_a = _extract_snippet(pair.before_text, pair.after_text)

    before_ref = _side_ref(chapmap, pair.before_line, before_lines, pair.before_text)
    after_ref = _side_ref(chapmap, pair.after_line, after_lines, pair.after_text)

    spans: list[tuple[int, int]] = []
    occurrences = 1
    attribution = ATTR_NO_RULES
    rule_before = rule_after = ""
    rule_set: list[tuple[str, str]] = []

    if rules is not None:
        attribution = ATTR_UNVERIFIED
        if not multi and kind == KIND_REPLACE:
            attr = rules.attribute(pair.before_text, pair.after_text)
            attribution = attr["attribution"]
            rule_before = attr["rule_before"]
            rule_after = attr["rule_after"]
            rule_set = attr["rule_set"]
            occurrences = attr["occurrences"]
            if attribution in (ATTR_VERIFIED, ATTR_VERIFIED_SET):
                spans = _locate_spans(pair.before_text, pair.after_text,
                                      rule_set, occurrences)

    return DiffItem(
        index=pos,
        kind=kind,
        before_text=pair.before_text,
        after_text=pair.after_text,
        before_snippet=snippet_b,
        after_snippet=snippet_a,
        before=before_ref,
        after_ref=after_ref,
        char_spans=spans,
        occurrences=occurrences,
        attribution=attribution,
        rule_before=rule_before,
        rule_after=rule_after,
        rule_set=rule_set,
    )


def _side_ref(chapmap: ChapterMap, line: int, lines: list[str],
              block: str) -> SideRef:
    if line <= 0 or line > len(lines):
        return SideRef(chapter_index=chapmap.chapter_of_line(line) if line > 0 else -1)
    chap_idx = chapmap.chapter_of_line(line)
    chap = chapmap.chapters[chap_idx] if 0 <= chap_idx < len(chapmap.chapters) else {}
    text = block.split(_LITERAL_N)[0] if block else ""
    start = lines[line - 1].find(text) if text else -1
    return SideRef(
        chapter_index=chap_idx,
        chapter_path=str(chap.get("path", "")),
        chapter_title=str(chap.get("title", "") or chap.get("label", "")),
        line=line,
        char_start=start,
        char_end=(start + len(text)) if start >= 0 and text else -1,
    )


def _extract_snippet(before: str, after: str) -> tuple[str, str]:
    """差异字符 + 两侧各 3 个字符的上下文（与统计口径 ``context_len`` 同值）。

    只用于界面高亮，不用来判断归属——归属一律走整行重放。
    """
    from fixtext_bookmap.textdiff import extract_str_diff

    got = extract_str_diff(before, after, 3)
    if got is None:
        return before, after
    return got


def _locate_spans(before_line: str, after_line: str,
                  rule_set: list[tuple[str, str]],
                  occurrences: int = 1) -> list[tuple[int, int]]:
    """这条差异在改前行里覆盖的字符区间（供界面精确高亮）。

    取法：逐条规则在改前行里**找出所有出现位置**（不重叠、从左到右），
    而不是只取第一次命中——同一行里同一处替换出现两次时（``occurrences=2``），
    界面必须能把两段都圈出来，否则会误导用户"只改了一处"。

    区域上限 :data:`MAX_CHAR_SPANS` 只用来防长行刷屏，不影响正常量的准确性。
    """
    spans: list[tuple[int, int]] = []
    for rule_b, _rule_a in rule_set:
        if not rule_b:
            continue
        cursor = 0
        while len(spans) < MAX_CHAR_SPANS:
            start = before_line.find(rule_b, cursor)
            if start < 0:
                break
            spans.append((start, start + len(rule_b)))
            cursor = start + len(rule_b)
        if len(spans) >= MAX_CHAR_SPANS:
            break
    return sorted(spans)


def _verify_hit_parity(before_text: str, after_text: str,
                       items: list[DiffItem]) -> dict:
    """按导出层的口径复算 hits，并与差异项对账。

    hits 直接调 ``fixtext_export._count_hits``——**同一个函数**，不是重写一遍
    口径。两处统计若各写一份实现，数字一致也只能算巧合；共用同一处实现，
    「不矛盾」才有意义。

    然后把差异项按 ``gen_diff_words_map`` 的**真实筛选规则**逐条重演一遍，
    数出「哪些差异项会变成词条」以及「其中多少条额外产出了去标签副本」。
    这一步不能省：既有口径会把一侧为空的行对（纯新增 / 纯删除）直接丢掉，
    它们**有差异但不是词条**。不把这类行对单独记账，对账差额会被误当成缺陷。
    """
    from fixtext_export import _count_hits

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        b = work / "before.txt"
        a = work / "after.txt"
        b.write_text(before_text, encoding="utf-8")
        a.write_text(after_text, encoding="utf-8")
        hits, _rows = _count_hits(b, a, work)

    simulated = _simulate_word_map(items)
    return {"hits": hits,
            "hit_eligible": simulated["eligible"],
            "stripped_copies": simulated["stripped"]}


def _simulate_word_map(items: list[DiffItem]) -> dict:
    """逐条重演 ``gen_diff_words_map`` 的筛选，给出两个数。

    :return: ``{"eligible": 会成为词条的差异项数, "stripped": 其中额外产出
              去标签副本的条数}``

    判定顺序与上游一字不差：先跳过跨行（``_count_hits`` 里按字面量 ``\\n``
    过滤），再截差异片段（未跨行时），再去首尾空白，最后用 ``php_truthy``
    判两侧——PHP 的 ``!`` 把空串与 ``"0"`` 都当假，任一侧为假就整条丢掉。
    只有两侧都过硬、``strip_html_tag`` 前后发生了变化，才额外产出一份副本。
    """
    from fixtext_bookmap.option import Option
    from fixtext_bookmap.phpcompat import php_trim, trim_unicode_chars
    from fixtext_bookmap.textdiff import extract_str_diff
    from fixtext_bookmap.wordmap import strip_html_tag

    option = Option()
    eligible = 0
    stripped = 0
    for item in items:
        if item.kind == KIND_MULTI_LINE:
            continue
        before, after = item.before_text, item.after_text
        got = extract_str_diff(before, after, option.context_len)
        if got is None:
            continue
        before, after = got
        before = php_trim(trim_unicode_chars(before, " 　"))
        after = php_trim(trim_unicode_chars(after, " 　"))
        if not _php_truthy(before) or not _php_truthy(after):
            continue
        eligible += 1
        if strip_html_tag(before) != before or strip_html_tag(after) != after:
            stripped += 1
    return {"eligible": eligible, "stripped": stripped}


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------
def compute_diff_metrics(report: DiffReport) -> dict:
    """把报告里的核对数据收成一行，便于日志 / 验收脚本打印。"""
    return {
        "差异项": report.item_count,
        "计入词条的差异项": report.hit_eligible,
        "替换统计 hits": report.hits,
        "跨行差异（不计入 hits）": report.multi_line_count,
        "去标签副本": report.stripped_copies,
        "核对差额": report.hit_gap,
        "归属未验证": report.unverified_count,
    }


def diff_to_json(report: DiffReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=1)
