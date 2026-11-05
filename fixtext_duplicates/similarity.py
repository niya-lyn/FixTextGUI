"""段落文本规范化与相似度计算（V1.1-E6 交付物①的计算内核）。

**相似度定义（本卡口径，E7 与验收都按这一条）**

1. 规范化：去 HTML 标签 → 去全部空白字符 → 保留标点与正文。
   中文书稿里空白没有语义（换行、缩进、全角空格都只是排版），去掉它们
   才能让「同一段落在两处排版不同」被判成重复，而不是被判成 0.9。
2. 完全重复：规范化后**逐字相同**即 ``KIND_EXACT``，分值恒为 ``1.0``。
   另外单独记录 ``raw_equal``（原始文本也逐字相同），供清单区分「连标点都
   一样」和「只差排版」。
3. 相似重复：以**字符二元组（bigram）多重集**的 Dice 系数

   .. code-block:: text

       sim(A, B) = 2 · |A ∩ B| / (|A| + |B|)

   ``A`` / ``B`` 是两段规范化文本的 bigram 多重集（重复的 bigram 重复计数）。
   取 Dice 而不是 ``difflib`` 的 ratio，原因是：Dice 只看「共享了多少字面
   相邻对」，与两段的**长度差异**在同一条公式里，且对顺序错位不敏感
   （同一句话被插进一个词，其余 bigram 仍然共享）；复杂度是 O(长度)，
   大书上不会退化成平方级。Dice 满足 ``sim(A,A)=1``、对称、与长度无关地
   落在 ``[0,1]``——阈值语义因此是干净的「共享度百分比」。

**阈值语义**：``threshold=0.85`` 表示「两段共享至少 85% 的相邻字对」。
取值越高要求越像；``1.0`` 时只剩完全重复（以及极短的、bigram 集合
恰好全同的段落）。命中集合随阈值升高**单调不增**（见 ``detect`` 实现：
候选生成与阈值无关，最终只做 ``score >= threshold`` 过滤）。

**为什么不用编辑距离 / LCS**：两者都是 O(长度²)，一本 20MB 的书上逐对
比对无法在可接受时间内跑完；Dice 的线性复杂度是本卡性能冒烟能过的前提。

本模块只依赖标准库。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Iterator

#: 段落最短字数（不计空白）。低于这个长度的段不参与比对——两三个字的
#: 「嗯」「好」在任何书里都重复几十次，报出来只是噪声。默认 20 字与原版
#: find-dupl-text 的「截取片段 ≥20 字」同口径。
DEFAULT_MIN_CHARS = 20

#: 标签剥离：只去形如 ``<p>`` / ``<h2 class="...">`` 的尖括号标签。
#: 不用 HTML 解析器是因为合并文本里的章节是「片段 + 边界标记」，整篇不是
#: 合法 XML；正则足以覆盖段落内部的标签（``<br/>``、``<i>``）。
_TAG_RE = re.compile(r"<[^>]{0,200}>")
#: 全部空白（含全角空格 U+3000、不换行空格 U+00A0）
_WS_RE = re.compile(r"[\s\u3000\xa0]+")


def strip_tags(text: str) -> str:
    """去掉段落内的标签与实体残留。"""
    if not text:
        return ""
    out = _TAG_RE.sub("", text)
    # 常见实体还原（合并文本里只出现少量，如 &nbsp; / &amp;）
    if "&" in out:
        out = (out.replace("&nbsp;", " ").replace("&lt;", "<")
                   .replace("&gt;", ">").replace("&quot;", '"')
                   .replace("&apos;", "'").replace("&amp;", "&"))
    return out


def normalize(text: str) -> str:
    """比对用的规范形态：去标签 → 去全部空白。"""
    return _WS_RE.sub("", strip_tags(text or ""))


def core_length(text: str) -> int:
    """字数口径：去标签、去空白后的字符数（与产品里「字数」一致）。"""
    return len(normalize(text))


def bigrams(text: str) -> Counter[str]:
    """规范化文本的字符二元组多重集。"""
    core = normalize(text)
    if len(core) < 2:
        return Counter(core)
    return Counter(core[i:i + 2] for i in range(len(core) - 1))


def dice(a: Counter[str], b: Counter[str]) -> float:
    """两个 bigram 多重集的 Dice 系数。"""
    if not a and not b:
        return 1.0
    total = sum(a.values()) + sum(b.values())
    if total <= 0:
        return 1.0
    shared = sum((a & b).values())
    return 2.0 * shared / total


def similarity_of(text_a: str, text_b: str) -> float:
    """两段文本的相似度（规范化后 Dice）。"""
    na, nb = normalize(text_a), normalize(text_b)
    if na == nb:
        return 1.0
    if len(na) < 2 or len(nb) < 2:
        return 0.0
    return dice(bigrams(na), bigrams(nb))


def containment_of(text_a: str, text_b: str) -> float:
    """短的一段有多大比例被长的一段覆盖（``重合 / 短段 bigram 数``）。

    这不是命中判据，只是**辅助信息**：清单里能提示「这一段其实是另一段的
    一部分」，处置时用户可以合并而不是各留一份。1.0 表示短段被长段完全覆盖。
    """
    na, nb = normalize(text_a), normalize(text_b)
    ca, cb = bigrams(na), bigrams(nb)
    short = ca if sum(ca.values()) <= sum(cb.values()) else cb
    if not short:
        return 0.0
    return sum((ca & cb).values()) / sum(short.values())


def max_length_ratio(threshold: float) -> float:
    """Dice 达标的**长度比上限** ``长段/短段 ≤ (2-t)/t``。

    由 ``2·I/(a+b) ≥ t`` 且 ``I ≤ min(a,b)`` 得 ``b ≤ a·(2-t)/t``。
    超出这个长度比的两段**不可能**达标，是安全剪枝条件（无漏报）。
    ``t=0.5`` 时上限 3.0，``t=0.85`` 时 1.353，``t→1`` 时趋近 1。
    """
    t = min(1.0, max(1e-9, float(threshold)))
    if t >= 1.0:
        return 1.0
    return (2.0 - t) / t


def shared_bigram_floor(threshold: float, bigrams_a: int, bigrams_b: int) -> int:
    """Dice 达到 ``threshold`` 所必需的**最少共享 bigram 数**（安全下界）。

    参数是两侧的 **bigram 个数**（= 规范化字数 − 1），不是字数——
    早期版本传字数进来，下界被抬高 1，实测会把真命中剪掉（52 共享被判
    需要 53），这条断言就是那次修复的回归。

    推导：``2·I/(a+b) ≥ t`` 且 ``a+b ≥ 2·min(a,b)`` ⇒ ``I ≥ t·min(a,b)``。
    多重集交集 ``I`` 永远 ≤ 去重交集，所以「去重交集 < 该下界」的对不可能
    达标——这条判据只会少剪、不会多剪。
    """
    if threshold <= 0:
        return 0
    smaller = max(1, min(int(bigrams_a), int(bigrams_b)))
    # ceil：宁可多留候选也不漏
    return max(1, int(-(-float(threshold) * smaller // 1)))


def sketch_tokens(text: str, size: int = 16) -> list[int]:
    """bottom-k 草图：取哈希值最小的 ``size`` 个 bigram（用于候选分块）。

    只用于「决定谁跟谁值得精算」，不参与分值计算——分值永远是 ``dice()``
    的精确值。草图与阈值无关，因此候选集也跟阈值无关，命中集合的单调性
    由精确分值的过滤单独保证。
    """
    core = normalize(text)
    if len(core) < 2:
        return []
    seen: set[int] = set()
    for i in range(len(core) - 1):
        seen.add(hash((core[i], core[i + 1])) & 0xFFFFFFFFFFFF)
        if len(seen) > size * 4:                 # 早剪：只需最小的一小撮
            seen = set(sorted(seen)[:size])
    return sorted(seen)[:size]


def iter_bigram_pairs(texts: Iterable[str]) -> Iterator[tuple[int, int, float]]:
    """朴素两两精算（只给测试与极小语料用；大书上会退化成平方级）。"""
    items = list(texts)
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            yield i, j, similarity_of(items[i], items[j])
