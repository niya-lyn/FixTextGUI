"""重复段落检测引擎（V1.1-E6 交付物①的算法主体）。

两条独立通道，各自不会漏掉自己那一类：

* **完全重复**（``KIND_EXACT``）：按规范化文本的哈希分桶，同桶内两两成对。
  一次线性扫描，**不存在候选剪枝**，所以「完全重复一定被检出」是可保证的。
* **相似重复**（``KIND_SIMILAR``）：确定性粗筛 + 精确 Dice 精算。
  粗筛只用对 Dice 成立的**必要条件**（长度窗口 + 去重交集下界），
  **不引入任何近似**，因此不会漏报；分值永远是精确 Dice，不是估计。
  阈值只参与「粗筛的必要条件」与「最终 ``score >= threshold`` 过滤」，
  两者都随阈值升高而收紧，命中集合的单调性因此成立。

**处理顺序**：

1. 过滤掉字数 < ``min_chars`` 的段（两三个字的「嗯」在任何书里都重复几十次）。
2. 完全重复：``normalize(text)`` → 分桶 → 桶内两两成对。
3. 相似重复：
   a. 长度窗口：长段/短段 ≤ ``(2-t)/t``（否则 Dice 数学上不可能达标）；
   b. 去重交集下界：去重 bigram 交集 ≥ ``ceil(t·短段bigram数/2)``；
   c. 剩下的候选对算精确 Dice，``>= threshold`` 才收。
   已经在完全重复通道出现过的对不再进相似通道（一条对只给一个类型）。
4. 分组：按类型分别用并查集把「对」连通成组；组内保留 ``max_similarity`` /
   ``min_similarity``，清单里可据此判断「这一组是不是真的整组都像」。

**为什么不用「低频前缀倒排」**：那是近似粗筛，共享前缀只是**可能**相似，
不共享前缀却依然相似的情形（一段在大段尾部被改动、前缀恰好不共享）会被
漏掉——实测在 6 段小语料上漏了 5 对真命中。本卡的取舍是**一条都不漏**，
代价是把粗筛降级成「必要条件过滤」，工作量换正确性。
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Sequence

from .model import (DuplicateGroup, DuplicatePair, DuplicateReport,
                    KIND_EXACT, KIND_SIMILAR, ParagraphRef)
from .similarity import (DEFAULT_MIN_CHARS, bigrams, core_length, dice,
                         max_length_ratio, normalize)

#: 「连续段落」判定：行号差 ≤ 这个值视为相邻（沿用原版 find-dupl-text 的 ≤3）
DEFAULT_ADJACENT_WINDOW = 3


@dataclass
class DetectOptions:
    """检测参数（E7 的筛选面板直接映射这些字段）。"""

    threshold: float = 0.85
    min_chars: int = DEFAULT_MIN_CHARS
    detect_exact: bool = True
    detect_similar: bool = True
    adjacent_window: int = DEFAULT_ADJACENT_WINDOW
    #: 关掉候选剪枝，穷举所有对（只用于小语料与验收对拍，大书上会退化成平方级）
    exhaustive: bool = False
    #: 只保留跨章命中（E7 的「只看跨章」开关）
    cross_chapter_only: bool = False

    def clamp(self) -> "DetectOptions":
        thr = float(self.threshold)
        if thr < 0.0:
            thr = 0.0
        if thr > 1.0:
            thr = 1.0
        return DetectOptions(
            threshold=thr,
            min_chars=max(1, int(self.min_chars)),
            detect_exact=bool(self.detect_exact),
            detect_similar=bool(self.detect_similar),
            adjacent_window=max(0, int(self.adjacent_window)),
            exhaustive=bool(self.exhaustive),
            cross_chapter_only=bool(self.cross_chapter_only),
        )

    def to_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "min_chars": self.min_chars,
            "detect_exact": self.detect_exact,
            "detect_similar": self.detect_similar,
            "adjacent_window": self.adjacent_window,
            "exhaustive": self.exhaustive,
            "cross_chapter_only": self.cross_chapter_only,
        }


# ---------------------------------------------------------------------------
# 对 → 组
# ---------------------------------------------------------------------------

class _UnionFind:
    """并查集（只用来把「对」连成组，判定依据始终是那对对本身）。"""

    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _build_groups(paragraphs: Sequence[ParagraphRef],
                  pairs: Sequence[DuplicatePair],
                  kinds: Sequence[str],
                  adjacent_window: int) -> list[DuplicateGroup]:
    """按类型把对连成组。``group_id`` 形如 ``E-3`` / ``S-7``（稳定、可复现）。"""
    groups: list[DuplicateGroup] = []
    prefix_of = {KIND_EXACT: "E", KIND_SIMILAR: "S"}

    for kind in kinds:
        kind_pairs = [(i, p) for i, p in enumerate(pairs) if p.kind == kind]
        if not kind_pairs:
            continue
        uf = _UnionFind(len(paragraphs))
        used: set[int] = set()
        for _, p in kind_pairs:
            uf.union(p.left, p.right)
            used.add(p.left)
            used.add(p.right)

        buckets: dict[int, list[int]] = defaultdict(list)
        for idx in used:
            buckets[uf.find(idx)].append(idx)

        ordered = sorted(buckets.values(), key=lambda members: min(members))
        for seq, members in enumerate(ordered):
            members = sorted(members)
            related = [p for _, p in kind_pairs
                       if uf.find(p.left) == uf.find(members[0])]
            pair_ids = [i for i, p in kind_pairs
                        if uf.find(p.left) == uf.find(members[0])]
            sims = [p.similarity for p in related]
            groups.append(DuplicateGroup(
                group_id=f"{prefix_of.get(kind, kind[:1].upper())}-{seq + 1}",
                kind=kind,
                members=[paragraphs[i] for i in members],
                pair_indices=pair_ids,
                max_similarity=max(sims) if sims else 0.0,
                min_similarity=min(sims) if sims else 0.0,
                # 连续的段落块数：相邻（行差 ≤ 窗口）的对才算一段「搬运」
                adjacent_runs=sum(1 for p in related if p.adjacent) or (1 if related else 0),
            ))
    groups.sort(key=lambda g: (g.kind != KIND_EXACT, g.first_position))
    return groups


# ---------------------------------------------------------------------------
# 相似候选
# ---------------------------------------------------------------------------

def _similar_candidates(cores: Sequence[str],
                        options: DetectOptions,
                        active: Sequence[int] | None = None) -> set[tuple[int, int]]:
    """生成值得精算的候选对（**无漏报**的粗筛，分值仍由精确 Dice 决定）。

    粗筛只用两条对 Dice 成立的**必要条件**，都不依赖任何近似：

    * **长度窗口**：由 ``2·I/(a+b) ≥ t`` 且 ``I ≤ min(a,b)`` 得
      ``b ≤ a·(2-t)/t``。超出这个长度比的两段**不可能**达标，跳过它们
      不会漏任何真命中（``_LEN_RATIO``）。
    * **去重交集下界**：达标时多重集交集 ``I ≥ t·(a+b)/2 ≥ t·min(a,b)/2``；
      而多重集交集永远 ≤ 去重交集，所以「去重交集 < 该下界」的对同样不可能
      达标。这是一条安全下界（判据只会少剪、不会多剪）。

    早期版本用「每段取 6 个最低频 bigram 作前缀」的倒排剪枝——那是**近似**
    粗筛，实测在「一段在大段尾部被改动」的语料上会漏掉 5 对真命中
    （阈值 0.6 时穷举出 6 对、前缀法只出 1 对）。本卡宁可慢一点也不要漏报，
    因此换成这条无漏报路径；``exhaustive=True`` 仍可完全跳过粗筛做对拍。

    ``active`` 传入已过 ``min_chars`` 的段号；缺省时按「规范化长度 ≥ 2」取。
    """
    if active is None:
        active = [i for i, c in enumerate(cores) if len(c) >= 2]
    else:
        active = list(active)
    if not active:
        return set()

    out: set[tuple[int, int]] = set()
    thr = float(options.threshold)
    if options.exhaustive or thr <= 0.0:
        # 阈值 ≤ 0 时任何长度可比的段都算达标，粗筛形同全对
        for pos, i in enumerate(active):
            for j in active[pos + 1:]:
                out.add((i, j) if i < j else (j, i))
        return out

    ratio = max_length_ratio(thr)
    #: 每段的去重 bigram 集合（多重集交集 ≤ 去重交集，用它做安全下界）
    distinct: dict[int, frozenset[str]] = {}
    tokens: dict[int, int] = {}
    for i in active:
        core = cores[i]
        distinct[i] = frozenset(core[k:k + 2] for k in range(len(core) - 1))
        tokens[i] = len(core) - 1
    if ratio <= 0.0:                       # pragma: no cover - ratio 恒 > 0
        return out

    by_len = sorted(active, key=lambda i: (tokens[i], i))
    lengths = [tokens[i] for i in by_len]
    n = len(by_len)
    for pos in range(n):
        short = by_len[pos]
        upper = lengths[pos] * ratio
        j_pos = pos + 1
        # 安全下界：达标时多重集交集 ≥ t·min(a,b)，而去重交集 ≥ 多重集交集
        floor = max(1, int(-(-thr * lengths[pos] // 1)))
        s_short = distinct[short]
        while j_pos < n and lengths[j_pos] <= upper:
            long = by_len[j_pos]
            j_pos += 1
            if len(s_short & distinct[long]) < floor:
                continue
            out.add((short, long) if short < long else (long, short))
    return out



# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def detect(paragraphs: Sequence[ParagraphRef],
           options: DetectOptions | None = None) -> DuplicateReport:
    """对一组段落做重复检测，返回可序列化的 :class:`DuplicateReport`。"""
    started = time.time()
    opt = (options or DetectOptions()).clamp()

    cores = [normalize(p.text) for p in paragraphs]
    lengths = [len(c) for c in cores]
    eligible = [i for i, n in enumerate(lengths) if n >= opt.min_chars]

    pairs: list[DuplicatePair] = []
    seen_pairs: set[tuple[int, int]] = set()

    def emit(left: int, right: int, sim: float, kind: str,
             raw_equal: bool) -> None:
        a, b = (left, right) if left < right else (right, left)
        key = (a, b)
        if key in seen_pairs:
            return
        seen_pairs.add(key)
        la, lb = paragraphs[a], paragraphs[b]
        cross = la.chapter_index != lb.chapter_index
        gap = abs(la.line_start - lb.line_start)
        pairs.append(DuplicatePair(
            left=a, right=b, similarity=sim, kind=kind,
            cross_chapter=cross,
            adjacent=gap <= opt.adjacent_window,
            raw_equal=raw_equal,
            line_gap=gap,
        ))

    # ---- 完全重复：哈希分桶，无候选剪枝 -----------------------------------
    if opt.detect_exact and eligible:
        buckets: dict[str, list[int]] = defaultdict(list)
        for i in eligible:
            buckets[cores[i]].append(i)
        for members in buckets.values():
            if len(members) < 2:
                continue
            # 桶内**两两成对**：只连「首段 → 其余」会漏掉「其余之间」那几对，
            # 清单上就会把同一段文字的第 2、3 处误标成「相似重复」（实测踩过）。
            for pos, left in enumerate(members):
                left_raw = paragraphs[left].text
                for right in members[pos + 1:]:
                    emit(left, right, 1.0, KIND_EXACT,
                         raw_equal=paragraphs[right].text == left_raw)

    # ---- 相似重复：候选 + 精确 Dice ---------------------------------------
    if opt.detect_similar and eligible:
        exact_keys = {(p.left, p.right) for p in pairs if p.kind == KIND_EXACT}
        # 已进完全重复通道的段仍可与其他段构成相似对，但同一对不再重复计
        tokens: dict[int, Counter[str]] = {}
        for i in eligible:
            tokens[i] = bigrams(paragraphs[i].text)

        def precise(i: int, j: int) -> float:
            if i not in tokens:
                tokens[i] = bigrams(paragraphs[i].text)
            if j not in tokens:
                tokens[j] = bigrams(paragraphs[j].text)
            return dice(tokens[i], tokens[j])

        candidates = _similar_candidates(cores, opt, eligible)
        for i, j in sorted(candidates):
            if (i, j) in exact_keys:
                continue
            sim = precise(i, j)
            if sim >= opt.threshold:
                emit(i, j, sim, KIND_SIMILAR, raw_equal=False)

    # ---- 只留跨章 --------------------------------------------------------
    if opt.cross_chapter_only:
        pairs = [p for p in pairs if p.cross_chapter]

    pairs.sort(key=lambda p: (p.left, p.right))
    kinds = tuple(k for k, on in ((KIND_EXACT, opt.detect_exact),
                                  (KIND_SIMILAR, opt.detect_similar)) if on)
    groups = _build_groups(paragraphs, pairs, kinds, opt.adjacent_window)

    return DuplicateReport(
        threshold=opt.threshold,
        min_chars=opt.min_chars,
        paragraph_count=len(paragraphs),
        chapter_count=len({p.chapter_index for p in paragraphs
                           if p.chapter_index >= 0}),
        pairs=pairs,
        groups=groups,
        elapsed_ms=int((time.time() - started) * 1000),
        options=opt.to_dict(),
        paragraphs=list(paragraphs),
    )


def detect_text(text: str,
                options: DetectOptions | None = None,
                *,
                include_headings: bool = False) -> DuplicateReport:
    """一步到位：正文文本 → 切段 → 检测（E7 与验收脚本的共同入口）。"""
    from .extract import extract_paragraphs

    extracted = extract_paragraphs(text, include_headings=include_headings)
    report = detect(extracted.paragraphs, options)
    report.options = {**report.options,
                      "kind": extracted.kind,
                      "chapters_parsed": extracted.chapter_count}
    return report


def detect_file(path: str,
                options: DetectOptions | None = None,
                *,
                include_headings: bool = False) -> DuplicateReport:
    """一步到位：``book.txt`` → 切段 → 检测（只读）。"""
    from pathlib import Path

    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return detect_text(text, options, include_headings=include_headings)


__all__ = [
    "DetectOptions", "DEFAULT_ADJACENT_WINDOW",
    "detect", "detect_text", "detect_file",
]
