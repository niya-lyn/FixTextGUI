"""V1.1-E6 交付物②：命中位置数据结构（``fixtext_duplicates.model``）的单元测试。

这一层的验收口径是「E7 拿来就能用」，所以断言都落在**清单页真正会读的字段**上：

* 位置三口径（段落序号 / 章节 / 行号 / 字符偏移）都齐全且自洽；
* 每条命中都带重复类型、相似度、是否跨章、是否相邻；
* 序列化后原样读回，字段一个不少（E7 会把报告存进运行目录）；
* 三种排序、按对取全文、按章折叠都能直接用。

不做任何 Qt / 界面依赖（``fixtext_duplicates`` 本身也不许依赖界面层）。
"""

from __future__ import annotations

import json

import pytest

from fixtext_duplicates.model import (EXCERPT_CHARS, KIND_EXACT, KIND_NAMES,
                                      KIND_SIMILAR, ORDER_BY_COUNT,
                                      ORDER_BY_POSITION, ORDER_BY_SIMILARITY,
                                      ORDER_NAMES, DuplicateGroup,
                                      DuplicatePair, DuplicateReport,
                                      ParagraphRef, group_by_chapters,
                                      pairs_from_reports)


def _ref(index: int, text: str, *, chapter: int = -1, line: int = 1,
         title: str = "") -> ParagraphRef:
    return ParagraphRef(
        index=index, text=text,
        line_start=line, line_end=line,
        char_start=index * 10, char_end=index * 10 + len(text),
        chapter_index=chapter,
        chapter_no=chapter + 1 if chapter >= 0 else -1,
        chapter_title=title,
        chapter_label=title,
    )


# ---------------------------------------------------------------------------
# 段落位置
# ---------------------------------------------------------------------------

def test_paragraph_ref_carries_three_location_views():
    """位置要给三套口径：段落序号 / 章节 / 行号 + 字符偏移。"""
    text = "他推开门，院子里静得出奇。"
    p = _ref(7, text, chapter=2, line=321, title="考城隍")
    assert p.index == 7
    assert p.chapter_index == 2 and p.chapter_no == 3
    assert (p.line_start, p.line_end) == (321, 321)
    assert (p.char_start, p.char_end) == (70, 70 + len(text))
    assert p.chars == len(text)


def test_paragraph_ref_location_text_is_human_readable():
    """清单上那一行「第 N 章 · 标题 · 第 M 行」由数据层给，页面不用自己拼。"""
    p = _ref(3, "正文", chapter=4, line=120, title="耳中人")
    assert p.location_text() == "第 5 章 · 耳中人 · 第 120 行"
    # 纯文本（无章节信息）时不能出现「第 -1 章」
    plain = _ref(0, "正文", line=8)
    assert plain.location_text() == "第 8 行"


def test_paragraph_ref_excerpt_truncates_with_ellipsis():
    long_text = "字" * (EXCERPT_CHARS + 20)
    p = _ref(0, long_text)
    shown = p.excerpt()
    assert len(shown) == EXCERPT_CHARS + 1 and shown.endswith("…")
    assert p.excerpt(0) == long_text           # 0 = 不截断


def test_paragraph_ref_dict_roundtrip():
    p = _ref(5, "一段正文", chapter=1, line=40, title="某章")
    again = ParagraphRef.from_dict(p.to_dict())
    assert again == p


# ---------------------------------------------------------------------------
# 对与组
# ---------------------------------------------------------------------------

def test_pairs_roundtrip_keeps_type_and_score():
    pair = DuplicatePair(left=2, right=9, similarity=0.9231, kind=KIND_SIMILAR,
                         cross_chapter=True, adjacent=False, raw_equal=False,
                         line_gap=40)
    again = DuplicatePair.from_dict(pair.to_dict())
    assert again == pair
    assert again.key == (2, 9)


def test_group_exposes_occurrences_and_chapter_span():
    members = [_ref(4, "甲", chapter=1, line=10, title="一"),
               _ref(30, "甲", chapter=6, line=88, title="六")]
    g = DuplicateGroup(group_id="E-1", kind=KIND_EXACT, members=members,
                       pair_indices=[0], max_similarity=1.0,
                       min_similarity=1.0, adjacent_runs=1)
    assert g.occurrences == 2
    assert g.first_position == 4
    assert g.cross_chapter is True
    assert g.chapter_span == (2, 7)
    assert g.kind_name == KIND_NAMES[KIND_EXACT]


def test_group_roundtrip_keeps_member_positions():
    members = [_ref(4, "甲", chapter=1, line=10, title="一"),
               _ref(30, "乙", chapter=6, line=88, title="六")]
    g = DuplicateGroup(group_id="S-2", kind=KIND_SIMILAR, members=members,
                       pair_indices=[3, 4], max_similarity=0.9,
                       min_similarity=0.8, adjacent_runs=2)
    again = DuplicateGroup.from_dict(g.to_dict())
    assert again.group_id == "S-2" and again.pair_indices == [3, 4]
    assert [(m.index, m.line_start, m.chapter_no) for m in again.members] == \
           [(4, 10, 2), (30, 88, 7)]


# ---------------------------------------------------------------------------
# 报告（E7 的唯一输入）
# ---------------------------------------------------------------------------

def _sample_report() -> DuplicateReport:
    paras = [
        _ref(0, "头一段，随便写点什么填充长度。", chapter=0, line=10, title="第一章"),
        _ref(1, "这段在第三章又出现了一次，一模一样。", chapter=0, line=12, title="第一章"),
        _ref(2, "第三章的别的内容，讲另一件事。", chapter=2, line=90, title="第三章"),
        _ref(3, "这段在第三章又出现了一次，一模一样。", chapter=2, line=95, title="第三章"),
    ]
    pairs = [DuplicatePair(left=1, right=3, similarity=1.0, kind=KIND_EXACT,
                           cross_chapter=True, adjacent=False, raw_equal=True,
                           line_gap=83)]
    groups = [DuplicateGroup(group_id="E-1", kind=KIND_EXACT,
                             members=[paras[1], paras[3]], pair_indices=[0],
                             max_similarity=1.0, min_similarity=1.0,
                             adjacent_runs=1)]
    return DuplicateReport(threshold=0.85, min_chars=20, paragraph_count=4,
                           chapter_count=2, pairs=pairs, groups=groups,
                           elapsed_ms=12, options={"kind": "epub"},
                           paragraphs=paras)


def test_report_counts_and_summary_are_consistent():
    rep = _sample_report()
    assert len(rep.exact_pairs) == 1 and len(rep.similar_pairs) == 0
    assert rep.cross_chapter_pairs == 1
    assert rep.involved_paragraphs == 2
    assert rep.stats()["groups"] == 1
    text = rep.summary()
    assert "共 4 段" in text and "1 组" in text and "跨章 1 对" in text
    # 无命中时也必须给人话，而不是空字符串
    empty = DuplicateReport(threshold=0.85, min_chars=20, paragraph_count=10,
                            chapter_count=1)
    assert "没有发现重复段落" in empty.summary()


def test_report_texts_of_pair_returns_full_text():
    """清单展开一条时要拿全文，报告自带段落表就不用回书稿。"""
    rep = _sample_report()
    left_text, right_text = rep.texts_of(rep.pairs[0])
    assert left_text == right_text == "这段在第三章又出现了一次，一模一样。"
    assert rep.paragraph(99) is None


def test_report_json_roundtrip_including_paragraphs():
    rep = _sample_report()
    again = DuplicateReport.from_json(rep.to_json())
    assert again.paragraph_count == rep.paragraph_count
    assert again.chapter_count == rep.chapter_count
    assert [p.key for p in again.pairs] == [p.key for p in rep.pairs]
    assert again.pairs[0].cross_chapter is True
    assert [p.text for p in again.paragraphs] == [p.text for p in rep.paragraphs]
    assert again.options == rep.options
    # 不带段落表的序列化（只存清单）也能读回
    lean = DuplicateReport.from_json(rep.to_json(include_paragraphs=False))
    assert lean.paragraphs == [] and lean.paragraph_count == 4


def test_report_payload_is_flat_and_consumable():
    """``payload()`` 是页面直读的形态：分组 + 段落全文索引，全 JSON 原生类型。"""
    rep = _sample_report()
    data = rep.payload()
    json.dumps(data)                                  # 必须能直接落盘
    assert data["stats"]["pairs"] == 1
    g = data["groups"][0]
    assert g["occurrences"] == 2 and g["kind_name"] == "完全重复"
    assert [m["paragraph_index"] for m in g["members"]] == [1, 3]
    assert data["paragraphs"][1]["text"] == "这段在第三章又出现了一次，一模一样。"


# ---------------------------------------------------------------------------
# 排序与派生视图
# ---------------------------------------------------------------------------

def test_sorted_groups_by_three_orders():
    rep = _sample_report()
    g2 = DuplicateGroup(group_id="S-1", kind=KIND_SIMILAR,
                       members=[rep.paragraphs[0], rep.paragraphs[2]],
                       pair_indices=[], max_similarity=0.91,
                       min_similarity=0.91, adjacent_runs=1)
    rep.groups.append(g2)
    by_count = rep.sorted_groups(ORDER_BY_COUNT)
    assert [g.occurrences for g in by_count] == [2, 2]      # 同数按位置
    assert [g.first_position for g in by_count] == [0, 1]
    by_pos = rep.sorted_groups(ORDER_BY_POSITION)
    assert [g.first_position for g in by_pos] == [0, 1]
    by_sim = rep.sorted_groups(ORDER_BY_SIMILARITY)
    assert by_sim[0].max_similarity == 1.0
    with pytest.raises(ValueError):
        rep.sorted_groups("unknown")
    assert set(ORDER_NAMES) == {ORDER_BY_COUNT, ORDER_BY_POSITION,
                                ORDER_BY_SIMILARITY}


def test_pairs_of_group_resolves_indices():
    rep = _sample_report()
    assert [p.key for p in rep.pairs_of_group(rep.groups[0])] == [(1, 3)]
    bad = DuplicateGroup(group_id="E-9", kind=KIND_EXACT, members=[],
                         pair_indices=[42], max_similarity=1.0,
                         min_similarity=1.0)
    assert rep.pairs_of_group(bad) == []              # 越界下标不炸


def test_pairs_from_reports_keeps_highest_score():
    a = _sample_report()
    b = _sample_report()
    b.pairs[0].similarity = 0.7
    merged = pairs_from_reports([a, b])
    assert len(merged) == 1 and merged[0].similarity == 1.0


def test_group_by_chapters_buckets_members():
    rep = _sample_report()
    buckets = group_by_chapters(rep.groups[0].members)
    assert sorted(buckets) == [0, 2]
    assert [m.index for m in buckets[2]] == [3]
