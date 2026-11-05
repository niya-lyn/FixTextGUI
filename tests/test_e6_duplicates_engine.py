"""V1.1-E6 交付物①：重复段落检测算法（``fixtext_duplicates``）的单元测试。

覆盖验收硬指标点名的六类：

1. **完全重复**——一字不差的两段必须被检出，类型是 ``exact``，分值 1.0；
2. **高相似**——只改个别字的两段必须被检出，类型是 ``similar``，分值可复算；
3. **低相似不误报**——换了主题的两段不能进命中（各自主题的段落也不许互相误报）；
4. **阈值单调性**——阈值调高时命中集合**单调不增**（且在样本上严格递减）；
5. **跨章重复**——同一句话落在两章里必须被标成 ``cross_chapter``，且行号/章号可定位；
6. **大文本性能冒烟**——用样本目录里的真实书跑一次，记录耗时（断言宽松上限）。

另外补三类结构断言：候选剪枝不改变结果（``exhaustive`` 对拍）、最小字数过滤、
以及「同一段文字出现三次」不会把第 2、3 处误标成相似重复。
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import pytest

from fixtext_duplicates import (DEFAULT_MIN_CHARS, DetectOptions,
                                DuplicateReport, KIND_EXACT, KIND_SIMILAR,
                                detect, detect_file, detect_text,
                                extract_paragraphs, similarity_of)
from fixtext_duplicates.engine import _similar_candidates
from fixtext_duplicates.similarity import (core_length, dice, normalize,
                                           shared_bigram_floor)

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = Path(__file__).resolve().parent / "samples"

#: 三条基准句：A 与 B 只差几个字，C 是完全不同的主题
A = "他推开门，院子里静得出奇，只有一只老猫趴在墙头上，眼睛在月光下泛着黄光。他站住脚，忽然听见身后有人叫他的名字。"
B = "他推开门，院子里静得出奇，只有一只老猫趴在墙头上，眼睛在月光下泛着黄光。他站住脚，忽然听见身后有人在喊他的名字。"
C = "天色将明，江面上起了雾，船家摇着橹，水声一下一下地响，远处的山影慢慢浮出水面。"
D = "掌柜的翻了翻账本，叹了口气，说这半年生意清淡，伙计们都瘦了一圈，年关怕是难过。"


def _bundle(chapters, *, nonce="a1b2c3d4e5f60718", title="样本"):
    """造一份最小可逆合并文本（章节标记与 ``epubtext.bundle`` 同语法）。"""
    from urllib.parse import quote

    lines = [
        f"<!-- EPUBTEXT-BUNDLE format=epubtext-bundle/1 "
        f"nonce={nonce} books=1 chapters={len(chapters)} -->",
        f"<!-- EPUBTEXT-BOOK:{nonce}:0 title={quote(title)} "
        f"source={quote('sample.epub')} chapters={len(chapters)} -->",
    ]
    for idx, (label, body) in enumerate(chapters):
        lines.append(
            f"<!-- EPUBTEXT-SPLIT:{nonce}:{idx} path={quote(f'c{idx}.xhtml')} "
            f"label={quote(label)} chars={len(body)} sha=0123456789abcdef -->")
        lines.append(f"<html><body><p>{body}</p></body></html>")
    return "\n".join(lines) + "\n"


def _detect(text, **kw):
    opt = DetectOptions(**kw)
    return detect_text(text, opt)


# ---------------------------------------------------------------------------
# 1. 完全重复
# ---------------------------------------------------------------------------

def test_exact_duplicate_detected_with_full_score():
    text = f"{A}\n\n{C}\n\n{A}\n"
    rep = _detect(text)
    assert isinstance(rep, DuplicateReport)
    assert [(p.left, p.right, p.kind) for p in rep.pairs] == [(0, 2, KIND_EXACT)]
    assert rep.pairs[0].similarity == 1.0
    assert rep.pairs[0].raw_equal is True
    assert len(rep.exact_groups) == 1 and len(rep.similar_groups) == 0


def test_exact_duplicate_threshold_does_not_matter():
    """完全重复恒为 1.0，阈值顶到 1.0 也必须还在。"""
    text = f"{A}\n\n{A}\n"
    for thr in (0.5, 0.85, 0.99, 1.0):
        rep = _detect(text, threshold=thr)
        assert len(rep.pairs) == 1, thr
        assert rep.pairs[0].similarity == 1.0


def test_exact_duplicate_only_whitespace_diff_still_exact():
    """排版差异（换行 / 缩进 / 全角空格）不算内容不同：规范化后相同即 exact。"""
    text = f"{A}\n\n{A[:20]}　　{A[20:]}\n"
    rep = _detect(text)
    assert len(rep.pairs) == 1 and rep.pairs[0].kind == KIND_EXACT
    # 但逐字不同，raw_equal 要如实标 False（清单上要能区分「连排版都一样」）
    assert rep.pairs[0].raw_equal is False


def test_three_occurrences_pairwise_all_exact():
    """同一段出现三次：三个对全是 exact，不许把第 2、3 处降级成 similar。"""
    text = f"{A}\n\n{D}\n\n{A}\n\n{A}\n"
    rep = _detect(text)
    assert [(p.left, p.right, p.kind) for p in rep.pairs] == \
           [(0, 2, KIND_EXACT), (0, 3, KIND_EXACT), (2, 3, KIND_EXACT)]
    assert len(rep.groups) == 1 and rep.groups[0].occurrences == 3


# ---------------------------------------------------------------------------
# 2. 高相似
# ---------------------------------------------------------------------------

def test_high_similarity_detected_as_similar_kind():
    """只改一处措辞：分值落在 [0.85, 1) 之间，类型是 similar。"""
    expected = similarity_of(A, B)
    assert 0.85 <= expected < 1.0, expected
    rep = _detect(f"{A}\n\n{C}\n\n{B}\n")
    assert len(rep.pairs) == 1
    pair = rep.pairs[0]
    assert pair.kind == KIND_SIMILAR
    assert pair.similarity == pytest.approx(expected, abs=1e-9)
    assert pair.raw_equal is False
    # 分值可独立复算：报告里的数必须等于 similarity_of 的结果
    left, right = rep.texts_of(pair)
    assert similarity_of(left, right) == pytest.approx(pair.similarity, abs=1e-9)


def test_similar_duplicate_spanning_one_paragraph_boundary():
    """一大段被拆成两段后重复：整体相似度会掉下来，不应误判成命中。

    这条是**反向断言**：段落切分口径决定了「拆开的不算一段」，避免把
    「相邻两段拼起来才等于另一段」当成同一段重复（那是 E7 的合并处置场景，
    不是检测层的重复命中）。
    """
    half = A[: len(A) // 2]
    rep = _detect(f"{A}\n\n{half}\n\n{A[len(A) // 2:]}\n")
    assert rep.pairs == []


# ---------------------------------------------------------------------------
# 3. 低相似不误报
# ---------------------------------------------------------------------------

def test_low_similarity_not_reported():
    """两个完全不同主题的段落：分值远低于阈值，不能进命中。"""
    assert similarity_of(A, C) < 0.2
    rep = _detect(f"{A}\n\n{C}\n\n{D}\n")
    assert rep.pairs == [] and rep.groups == []
    assert "没有发现重复段落" in rep.summary()


def test_shared_topic_words_alone_do_not_trigger():
    """共享几个常用词（同一场景、同一批人名）不足以命中——判据是整段共享度。"""
    E = "他推开门，屋里坐着三个人，桌上摆着一壶茶，窗外的雨还没停，风把门帘吹得直响。"
    F = "他推开门，屋里没有人，桌上的茶早就凉了，窗外的雨停了，门帘静静地垂着不动。"
    assert similarity_of(A, E) < 0.85 and similarity_of(E, F) < 0.85
    rep = _detect(f"{A}\n\n{E}\n\n{F}\n")
    assert rep.pairs == []


def test_short_paragraphs_filtered_by_min_chars():
    """两三个字的短句在任何书里都重复几十次，必须被最短字数挡掉。"""
    rep = _detect("「嗯」\n\n「嗯」\n\n「好」\n\n「好」\n")
    assert rep.pairs == []
    rep2 = _detect("「嗯」\n\n「嗯」\n", min_chars=1, threshold=0.5)
    assert len(rep2.pairs) == 1              # 放开最短字数就能检出，证明是过滤而非漏洞
    assert DEFAULT_MIN_CHARS == 20


# ---------------------------------------------------------------------------
# 4. 阈值单调性
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("corpus_name", ["synthetic", "real_book"])
def test_threshold_monotonicity(corpus_name):
    """阈值调高 → 命中集合单调不增（这里是「包含关系」，不只是数量）。"""
    if corpus_name == "synthetic":
        # 造 4 档相似度：完全相同 / 改一字 / 改半句 / 换主题
        near = B
        mid = A[: len(A) // 2] + "后半句完全换了，讲的是另一个人在路上遇见的事。"
        paras = [A, D, near, mid, C]
        text = "\n\n".join(paras)
        reps = {thr: _detect(text, threshold=thr)
                for thr in (0.5, 0.7, 0.85, 0.95, 0.99)}
    else:
        text = _real_book_text()
        reps = {thr: _detect(text, threshold=thr)
                for thr in (0.5, 0.7, 0.85, 0.95, 0.99)}

    thresholds = sorted(reps)
    counts = [len(reps[t].pairs) for t in thresholds]
    for prev, cur in zip(thresholds, thresholds[1:]):
        keys_prev = {p.key for p in reps[prev].pairs}
        keys_cur = {p.key for p in reps[cur].pairs}
        assert keys_cur <= keys_prev, f"阈值 {cur} 反而多出命中：{keys_cur - keys_prev}"
    assert counts == sorted(counts, reverse=True), counts

    # synthetic 语料上必须真的严格递减，否则这条测试证明不了过滤在起作用
    if corpus_name == "synthetic":
        assert len(set(counts)) > 1, counts
        assert reps[0.99].pairs == [] and len(reps[0.7].pairs) >= 1


def test_threshold_boundary_is_inclusive():
    """命中判据是 ``score >= threshold``（闭区间），不是严格大于。"""
    text = f"{A}\n\n{C}\n\n{B}\n"
    score = similarity_of(A, B)
    assert len(_detect(text, threshold=score).pairs) == 1
    assert len(_detect(text, threshold=score + 1e-9).pairs) == 0


def test_threshold_out_of_range_clamped():
    rep = _detect(f"{A}\n\n{B}\n", threshold=1.5)
    assert rep.threshold == 1.0
    rep_neg = _detect(f"{A}\n\n{C}\n", threshold=-0.5)
    assert rep_neg.threshold == 0.0


# ---------------------------------------------------------------------------
# 5. 跨章重复
# ---------------------------------------------------------------------------

def test_cross_chapter_exact_and_similar_both_detected():
    """同一句落在两章：exact 与 similar 都要带 cross_chapter=True 与章节定位。"""
    text = _bundle([("第一章", A), ("第二章", C), ("第三章", A), ("第四章", B)])
    rep = _detect(text, threshold=0.8)
    pairs = {(p.left, p.right): p for p in rep.pairs}
    assert (0, 2) in pairs and pairs[(0, 2)].kind == KIND_EXACT
    assert pairs[(0, 2)].cross_chapter is True
    assert (0, 3) in pairs and pairs[(0, 3)].kind == KIND_SIMILAR
    assert pairs[(0, 3)].cross_chapter is True
    # 章号 / 行号 / 字符偏移都要能定位到原文区间
    p0, p3 = rep.paragraph(0), rep.paragraph(3)
    assert (p0.chapter_no, p3.chapter_no) == (1, 4)
    assert p0.chapter_title == "第一章" and p3.chapter_title == "第四章"
    assert p0.line_start < p3.line_start and p0.char_start < p3.char_start
    assert text[p0.char_start:p0.char_end].find("他推开门") >= 0
    assert rep.chapter_count == 4


def test_cross_chapter_only_filter():
    """E7 的「只看跨章」开关：同章内的重复要被过滤掉，跨章的留着。"""
    # 同章内重复：一章里放三段，其中第 1、3 段相同
    same = "\n".join([
        "<!-- EPUBTEXT-BUNDLE format=epubtext-bundle/1 nonce=a1b2c3d4e5f60718 books=1 chapters=1 -->",
        "<!-- EPUBTEXT-BOOK:a1b2c3d4e5f60718:0 title=x source=y chapters=1 -->",
        "<!-- EPUBTEXT-SPLIT:a1b2c3d4e5f60718:0 path=c0.xhtml "
        "label=%E5%90%8C%E7%AB%A0 chars=999 sha=0123456789abcdef -->",
        f"<html><body><p>{A}</p><p>{C}</p><p>{A}</p></body></html>",
    ]) + "\n"
    ex = extract_paragraphs(same)
    assert ex.chapter_count == 1 and len(ex.paragraphs) == 3
    rep_all = detect(ex.paragraphs, DetectOptions(threshold=0.85))
    assert len(rep_all.pairs) == 1 and rep_all.pairs[0].cross_chapter is False
    rep_cross = detect(ex.paragraphs,
                       DetectOptions(threshold=0.85, cross_chapter_only=True))
    assert rep_cross.pairs == []


def test_adjacent_flag_uses_line_window():
    """连续段落（搬运整块）要能被标出来：行差 ≤ adjacent_window 才算相邻。"""
    lines = [A, C, A]
    text = "\n".join(lines) + "\n"
    rep = _detect(text, adjacent_window=3)
    assert rep.pairs and rep.pairs[0].adjacent is True     # 行差 2
    rep_tight = _detect(text, adjacent_window=1)
    assert rep_tight.pairs and rep_tight.pairs[0].adjacent is False


# ---------------------------------------------------------------------------
# 候选剪枝不改变结果（对拍）
# ---------------------------------------------------------------------------

def test_pruned_candidates_match_exhaustive_on_small_corpus():
    """前缀剪枝只是性能手段：小语料上与穷举**逐对**一致。"""
    paras = [A, B, C, D, A[:30] + "结尾不同。", B[:40] + "又一处改动。"]
    pruned = detect(extract_paragraphs("\n\n".join(paras)).paragraphs,
                    DetectOptions(threshold=0.6))
    full = detect(extract_paragraphs("\n\n".join(paras)).paragraphs,
                  DetectOptions(threshold=0.6, exhaustive=True))
    assert {p.key for p in pruned.pairs} == {p.key for p in full.pairs}
    assert [(p.key, p.kind) for p in pruned.pairs] == \
           [(p.key, p.kind) for p in full.pairs]


def test_candidate_generation_scale_is_subquadratic():
    """在**内容不重复**的语料上，候选数必须远小于平方级（粗筛真在起作用）。

    注意：如果语料本身全是近重复段（每个都跟每个像），候选必然接近平方级——
    那不是粗筛失效，而是真的都该精算。所以这里用互不相似的段做基准。
    """
    # 200 段互不相同的随机汉字串（确定性种子，避免每次跑结果漂移）
    import random
    han = [chr(0x4E00 + i) for i in range(20000)]
    rng = random.Random(7)
    cores = ["".join(rng.choice(han) for _ in range(150)) for _ in range(200)]
    cand = _similar_candidates(cores, DetectOptions(), list(range(200)))
    full = 200 * 199 // 2
    assert len(cand) < full // 10, (len(cand), full)


def test_candidate_filter_never_drops_a_real_hit():
    """安全性回归：任何真命中都必须留在候选集里（粗筛只做必要条件）。"""
    paras = [A, B, C, D, A[:30] + "结尾不同。", B[:40] + "又一处改动。",
             A[: len(A) // 2] + "后半句换了。"]
    cores = [normalize(p) for p in paras]
    for thr in (0.3, 0.5, 0.6, 0.85, 0.95, 1.0):
        cand = _similar_candidates(cores, DetectOptions(threshold=thr),
                                   list(range(len(paras))))
        for i in range(len(paras)):
            for j in range(i + 1, len(paras)):
                if similarity_of(paras[i], paras[j]) >= thr:
                    assert (i, j) in cand, (thr, i, j)


def test_detect_exact_and_similar_can_be_disabled_independently():
    text = f"{A}\n\n{B}\n\n{A}\n"
    exact_only = _detect(text, detect_similar=False, threshold=0.8)
    assert exact_only.pairs and all(p.kind == KIND_EXACT for p in exact_only.pairs)
    similar_only = _detect(text, detect_exact=False, threshold=0.8)
    assert similar_only.pairs and all(p.kind == KIND_SIMILAR
                                      for p in similar_only.pairs)


# ---------------------------------------------------------------------------
# 相似度定义本身
# ---------------------------------------------------------------------------

def test_dice_is_symmetric_bounded_and_identity():
    a, b = normalize(A), normalize(B)
    ba, bb = _bigrams(a), _bigrams(b)
    assert dice(ba, ba) == 1.0
    assert dice(ba, bb) == pytest.approx(dice(bb, ba))
    assert 0.0 <= dice(ba, bb) <= 1.0


def test_shared_bigram_floor_is_safe_lower_bound():
    """剪枝下界必须是「安全下界」：达标的对共享数一定 ≥ 下界。

    参数口径是 **bigram 个数**（字数 − 1）；早期误传字数进来，下界被抬高 1，
    真命中（共享 52）被判需要 53 而漏掉——这条就是那次修复的回归。
    """
    a, b = normalize(A), normalize(B)
    ba, bb = _bigrams(a), _bigrams(b)
    score = dice(ba, bb)
    floor = shared_bigram_floor(score, sum(ba.values()), sum(bb.values()))
    shared = sum((ba & bb).values())
    assert shared >= floor, (shared, floor)
    # 边界：阈值 0 时下界 0（不剪任何东西），阈值 1 时下界 = 短段 bigram 数
    assert shared_bigram_floor(0.0, 58, 59) == 0
    assert shared_bigram_floor(1.0, 58, 59) == 58


def _bigrams(t):
    from collections import Counter
    return Counter(t[i:i + 2] for i in range(len(t) - 1))


# ---------------------------------------------------------------------------
# 6. 大文本性能冒烟（真实书）
# ---------------------------------------------------------------------------

_REAL_TEXT: str | None = None


def _real_book_text() -> str:
    """样本目录里那本真实 EPUB → 可逆合并正文（一次合并，后续用例复用）。"""
    global _REAL_TEXT
    if _REAL_TEXT is None:
        from fixtext_ui.fixtext_export import ensure_vendor
        ensure_vendor(ROOT / "pipeline")
        from epubtext import merge_epub

        epub = SAMPLES / "book_public_domain.epub"
        assert epub.exists(), epub
        tmp = Path(_tmpdir())
        merged = merge_epub(epub, tmp / "merged.txt")
        _REAL_TEXT = merged.text_path.read_text(encoding="utf-8")
    return _REAL_TEXT


_TMP: str | None = None


def _tmpdir() -> str:
    global _TMP
    if _TMP is None:
        import tempfile
        _TMP = tempfile.mkdtemp(prefix="e6_real_")
    return _TMP


def test_real_book_performance_smoke():
    """真实书跑一次：记录耗时并把关键数字写进报告（断言宽松上限，只防退化）。"""
    text = _real_book_text()
    extracted = extract_paragraphs(text)
    assert extracted.kind == "epub"
    assert extracted.chapter_count == 301, extracted.chapter_count
    assert len(extracted.paragraphs) > 1000, len(extracted.paragraphs)

    started = time.perf_counter()
    rep = detect(extracted.paragraphs, DetectOptions(threshold=0.85))
    wall = time.perf_counter() - started
    # 1 核沙箱上这条实测 ~0.2s；上限放到 10s 只为防平方级退化
    assert wall < 10.0, f"真实书检测耗时 {wall:.2f}s，疑似退化"
    assert rep.paragraph_count == len(extracted.paragraphs)
    assert rep.chapter_count == 301
    assert rep.elapsed_ms <= int(wall * 1000) + 5

    # 真实书上的检出必须是可人工核对的那几对（不是「0 命中」的空跑）
    assert len(rep.pairs) == 4, [(p.left, p.right, p.kind) for p in rep.pairs]
    assert len(rep.exact_pairs) == 4 and rep.similar_pairs == []
    assert rep.cross_chapter_pairs == 4
    for p in rep.pairs:
        left, right = rep.texts_of(p)
        assert core_length(left) >= 20
        assert similarity_of(left, right) == 1.0
    print(f"[E6 性能冒烟] {rep.paragraph_count} 段 / {rep.chapter_count} 章，"
          f"阈值 0.85，耗时 {wall * 1000:.0f}ms，"
          f"命中 {len(rep.pairs)} 对（全部跨章完全重复）")


def test_real_book_threshold_sweep_is_monotone():
    """真实书上做一次阈值扫描，命中数单调不增（0.5 → 1.0）。"""
    text = _real_book_text()
    paras = extract_paragraphs(text).paragraphs
    counts = []
    for thr in (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0):
        counts.append(len(detect(paras, DetectOptions(threshold=thr)).pairs))
    assert counts == sorted(counts, reverse=True), counts
    print(f"[E6 阈值扫描] 0.5→1.0 命中数 {counts}")


def test_detect_file_reads_without_modifying(tmp_path):
    """``detect_file`` 只读：跑完源文件内容与 mtime 都不许变。"""
    src = tmp_path / "book.txt"
    src.write_text(f"{A}\n\n{C}\n\n{A}\n", encoding="utf-8")
    before = (src.read_bytes(), src.stat().st_mtime_ns)
    rep = detect_file(str(src))
    assert len(rep.pairs) == 1
    assert (src.read_bytes(), src.stat().st_mtime_ns) == before
