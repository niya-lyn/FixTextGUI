"""V1.1-E1 · 对比视图差异数据层的单元测试。

覆盖任务要求的五类场景（有差异 / 无差异 / 单处替换 / 多处替换 / 空文本），
外加三类本层特有风险：

* **口径一致性**：差异项条数与替换统计 hits 必须能对上账，且 hits 取自
  ``fixtext_export._count_hits`` 这**同一个函数**；
* **位置正确**：行号解析必须与 ``PatchAnalyzer`` 逐条一致，且行号真的指向
  那一段文本（否则 E2 跳转会跳到别处去）；
* **归属诚实**：能重放验证的才填规则，验证不了必须留空，不许猜。

最后一组用例（``test_does_not_touch_loading_layer``）是硬约束的自检：
本卡不得触碰 ``vocab_bridge.compose()`` / ``bags.write_round_rules()``。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "fixtext_ui", ROOT / "pipeline" / "vendor", ROOT / "vendor"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import fixtext_diff_view as DV  # noqa: E402


# ---------------------------------------------------------------------------
# 语料
# ---------------------------------------------------------------------------
#: 最小可运行的合并文本：头部 + 两章标记，结构与真实产物一致
MINI_TEXT = """\
<!-- EPUBTEXT-BUNDLE format=epubtext-bundle/1 nonce=deadbeefdeadbeef books=1 chapters=2 -->
<!-- EPUBTEXT-BOOK:deadbeefdeadbeef:0 title=%E7%A4%BA%E4%BE%8B source=sample.epub chapters=2 -->
<!-- EPUBTEXT-SPLIT:deadbeefdeadbeef:0 path=OEBPS/chapter001.xhtml label=第一章 chars=40 sha=0 -->
<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <h2 class="chap-title">第一章</h2>
    <p>甲萧衍乙萧衍丙</p>
  </body>
</html>
<!-- EPUBTEXT-SPLIT:deadbeefdeadbeef:1 path=OEBPS/chapter002.xhtml label=第二章 chars=40 sha=1 -->
<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <h2 class="chap-title">第二章</h2>
    <p>此处无错字</p>
  </body>
</html>
"""


def _txt(text: str) -> str:
    return text


def _replace_once(text: str, old: str, new: str) -> str:
    assert old in text, f"语料里没有 {old!r}"
    return text.replace(old, new, 1)


def _rules(pairs: list[tuple[str, str]]) -> DV.RuleIndex:
    return DV.RuleIndex([p[0] for p in pairs], [p[1] for p in pairs])


# ---------------------------------------------------------------------------
# 一、无差异
# ---------------------------------------------------------------------------
def test_no_diff_when_texts_identical():
    """两份完全相同的正文：零差异项、零 hits，且不误报。"""
    report = DV.build_diff(MINI_TEXT, MINI_TEXT)

    assert report.item_count == 0
    assert report.items == []
    assert report.hits == 0
    assert report.hit_gap == 0
    assert report.multi_line_count == 0
    assert report.stripped_copies == 0
    assert report.hits_verified is True


def test_no_diff_chapters_still_listed():
    """即使没有差异，章节表也要在——E2 的章节目录不依赖有没有差异。"""
    report = DV.build_diff(MINI_TEXT, MINI_TEXT)

    assert len(report.chapters) == 2
    assert [c["title"] for c in report.chapters] == ["第一章", "第二章"]
    assert report.chapters[0]["start_line"] >= 1


# ---------------------------------------------------------------------------
# 二、空文本
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("before,after", [
    ("", ""),                      # 两侧都空
    ("", "有一个字"),               # 从空到有
    ("有一个字", ""),               # 从有到空
    ("   \n\n  ", "   \n\n  "),    # 只有空白
])
def test_empty_text_does_not_crash(before, after):
    """空文本不该炸；两侧都空时不许凭空造差异项。"""
    report = DV.build_diff(before, after)

    if before == after:
        assert report.item_count == 0, "两侧相同不该有差异项"
    else:
        # 一侧为空是**合法差异**（整段新增 / 整段删除），但既有词条口径
        # 用 php_truthy 判假把它整条丢掉 → 计 0 条词条、不进 hits
        assert report.item_count == 1
        assert report.items[0].kind in (DV.KIND_INSERT, DV.KIND_DELETE)
    assert report.hit_eligible == 0, "一侧为空的行对不计入词条"
    assert report.hits == 0
    assert report.hit_gap == 0


def test_empty_both_sides_has_no_chapters():
    report = DV.build_diff("", "")
    assert report.chapters == []


# ---------------------------------------------------------------------------
# 三、单处替换
# ---------------------------------------------------------------------------
def test_single_replacement_produces_one_item():
    after = _replace_once(MINI_TEXT, "甲萧衍乙", "甲萧彦乙")
    report = DV.build_diff(MINI_TEXT, after)

    assert report.item_count == 1
    item = report.items[0]

    assert item.kind == DV.KIND_REPLACE
    assert "萧衍" in item.before_text
    assert "萧彦" in item.after_text
    # 片段只带差异字符与上下文，不是整行
    assert item.before_snippet != item.before_text
    assert "衍" in item.before_snippet and "彦" in item.after_snippet


def test_single_replacement_locates_chapter_line_and_column():
    """位置三件事都要对：第几章、第几行、行内第几列。"""
    # 用带章标记、且该词只出现一次的语料：归属可验证，才有精确字符区间
    before = MINI_TEXT.replace("甲萧衍乙萧衍丙", "甲萧衍乙丙")
    after = _replace_once(before, "甲萧衍乙", "甲萧彦乙")
    report = DV.build_diff(before, after, rules=_rules([("萧衍", "萧彦")]))
    item = report.items[0]

    # chapter_index 是 chapters 列表下标，第一章即 0
    chapter = report.chapters[item.before.chapter_index]
    assert chapter["title"] == "第一章"
    assert item.before.chapter_index == 0

    # 行号必须真的指向含萧衍的那一行（1 基）
    lines = before.split("\n")
    assert "萧衍" in lines[item.before.line - 1]

    # 行内列位置必须精确落在「萧衍」这两个字上
    line = lines[item.before.line - 1]
    start, end = item.char_spans[0]
    assert line[start:end] == "萧衍"


def test_single_replacement_marks_chapter_of_item():
    """``items_of_chapter`` 要能按章取差异项，E2 点目录才能跳。"""
    after = _replace_once(MINI_TEXT, "甲萧衍乙", "甲萧彦乙")
    report = DV.build_diff(MINI_TEXT, after)

    assert len(report.items_of_chapter(0)) == 1
    assert report.items_of_chapter(1) == []


# ---------------------------------------------------------------------------
# 四、多处替换
# ---------------------------------------------------------------------------
def test_multiple_replacements_across_chapters():
    after = (_replace_once(MINI_TEXT, "甲萧衍乙", "甲萧彦乙")
             .replace("此处无错字", "此处无错字，另改之"))
    report = DV.build_diff(MINI_TEXT, after)

    # 第一处是改字；第二处是行内追加 → 两条差异项
    assert report.item_count == 2

    chapters = {i.before.chapter_index for i in report.items}
    assert len(chapters) == 2, "跨章差异应落在不同的章节索引上"


def test_repeated_same_replacement_in_one_line():
    """同一行里同一处替换出现两次：既有口径下是 1 条词条 / 1 次 hits。

    差异项按「行对」计，因此也是 1 条——但 ``occurrences`` 要如实记成 2，
    否则界面上会告诉用户"只改了一处"。这是本层与 hits 口径的已知边界。
    """
    rules = _rules([("萧衍", "萧彦")])
    before = MINI_TEXT
    after = _replace_once(MINI_TEXT, "甲萧衍乙萧衍丙", "甲萧彦乙萧彦丙")

    report = DV.build_diff(before, after, rules=rules)

    assert report.item_count == 1, "整行算一条差异项（行对口径）"
    item = report.items[0]
    assert item.occurrences == 2, "同一行两处同一替换，occurrences 必须记 2"
    # 两个字符区间都点出来
    assert len(item.char_spans) == 2
    # 词条口径：1 条词条 + 1 份去标签副本 = 2 次 hits
    assert report.hits == 2
    assert report.hit_gap == 0


def test_two_different_replacements_in_one_line_is_one_item():
    """同一行的两处**不同**替换也合成一条差异项（行对口径）。"""
    before = MINI_TEXT
    after = _replace_once(before, "甲萧衍乙", "甲萧彦乙").replace("丙</p>", "丁</p>", 1)
    report = DV.build_diff(before, after)

    assert report.item_count == 1
    assert report.hits == 2, "1 条词条 + 1 份去标签副本"
    assert report.hit_gap == 0


# ---------------------------------------------------------------------------
# 五、与替换统计对账
# ---------------------------------------------------------------------------
def test_hits_use_the_export_layer_function():
    """hits 必须是 ``fixtext_export._count_hits`` 算出来的同一个数。

    两处统计各写一份实现，数字相等也只能算巧合；共用一处实现才叫不矛盾。
    """
    import fixtext_export

    after = _replace_once(MINI_TEXT, "甲萧衍乙", "甲萧彦乙")
    report = DV.build_diff(MINI_TEXT, after)

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "before.txt").write_text(MINI_TEXT, encoding="utf-8")
        (work / "after.txt").write_text(after, encoding="utf-8")
        expected, _rows = fixtext_export._count_hits(
            work / "before.txt", work / "after.txt", work)

    assert report.hits == expected


def test_hit_gap_zero_on_minimal_case():
    """最小场景上：hits = 差异项 + 去标签副本，差额必须为 0。"""
    after = _replace_once(MINI_TEXT, "甲萧衍乙", "甲萧彦乙")
    report = DV.build_diff(MINI_TEXT, after)

    assert report.hit_gap == 0
    assert report.hit_gap == report.hits - (report.item_count + report.stripped_copies)


def test_stripped_copy_counted_when_snippet_touches_html_tag():
    """贴着 ``<``/``>`` 的片段会额外产出一份去标签副本，要单独记账。

    这不是缺陷：``Option.add_html_stripped_copy=True`` 就是这么设计的，
    本层把它显式数出来，才解释得清 hits 为什么比差异项多。
    """
    before = MINI_TEXT.replace("<p>甲萧衍乙萧衍丙</p>", "<p>甲萧衍</p>")
    after = before.replace("<p>甲萧衍</p>", "<p>甲萧彦</p>")
    report = DV.build_diff(before, after)

    # 片段里带尖括号 → 去标签后内容变了 → 多一份副本
    assert report.item_count == 1
    assert report.hits >= 1
    assert report.stripped_copies >= 1
    assert report.hit_gap == 0, "记账之后差额仍然必须是 0"


# ---------------------------------------------------------------------------
# 六、行号解析与 PatchAnalyzer 一致
# ---------------------------------------------------------------------------
def test_line_index_matches_patch_analyzer_texts():
    """本层的行对必须与既有 ``PatchAnalyzer`` 逐条同文同序。

    本层只多记了行号；文本对若与既有实现有任何偏差，差异项就会与替换
    报告对不上账。这条用例是该不变量的守门人。
    """
    from fixtext_bookmap.patcher import PatchAnalyzer, generate_patch

    before = MINI_TEXT
    after = (_replace_once(before, "甲萧衍乙", "甲萧彦乙")
             .replace("此处无错字", "此处无错别字"))
    patch_text = DV._generate_patch_text(before, after)

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "d.patch"
        p.write_text(patch_text, encoding="utf-8")
        exp_before, exp_after = PatchAnalyzer().get_diff_from_patch_file(str(p))

    idx = DV.PatchLineIndex.from_patch_text(patch_text)
    got_before, got_after = idx.texts()

    assert got_before == exp_before
    assert got_after == exp_after


def test_line_numbers_point_at_real_text():
    """每一条差异项的行号都必须真的指向它自己那段文本。"""
    before = MINI_TEXT
    after = (_replace_once(before, "甲萧衍乙", "甲萧彦乙")
             .replace("此处无错字", "此处无错别字"))
    report = DV.build_diff(before, after)

    blines = before.split("\n")
    alines = after.split("\n")
    for item in report.items:
        assert blines[item.before.line - 1] == item.before_text
        assert alines[item.after_ref.line - 1] == item.after_text


# ---------------------------------------------------------------------------
# 七、规则归属：能验证才填，验证不了留空
# ---------------------------------------------------------------------------
def test_attribution_verified_when_rule_replays():
    """单条规则能重放出改后文本 → 填规则，且标记 verified。"""
    # 用「只出现一次」的词做语料：重放才可能整行对上，
    # 否则规则会把行内两处同类词都改掉，重放自然验不过（那才是诚实的 unverified）
    rules = _rules([("萧衍", "萧彦")])
    before = "他乡遇故知，萧衍登场。"
    after = "他乡遇故知，萧彦登场。"
    report = DV.build_diff(before, after, rules=rules)

    item = report.items[0]
    assert item.attribution == DV.ATTR_VERIFIED
    assert item.rule_before == "萧衍"
    assert item.rule_after == "萧彦"
    assert (item.rule_before, item.rule_after) in item.rule_set


def test_attribution_verified_set_when_rule_combination_replays():
    """一行里两处不同替换 → 需要两条规则组合才能重放。"""
    rules = _rules([("萧衍", "萧彦"), ("丙", "丁")])
    before = "他乡遇故知，萧衍登场，丙次登场。"
    after = "他乡遇故知，萧彦登场，丁次登场。"
    report = DV.build_diff(before, after, rules=rules)

    item = report.items[0]
    assert item.attribution == DV.ATTR_VERIFIED_SET
    assert len(item.rule_set) == 2
    # 单条字段留空：既然是组合，就不能谎称某一单条规则解释了它
    assert item.rule_before == ""
    assert item.rule_after == ""


def test_attribution_unverified_leaves_fields_empty():
    """没有规则能重放出来时必须留空，不许编造。"""
    rules = _rules([("张三", "李四")])   # 与本次差异无关的规则
    after = _replace_once(MINI_TEXT, "甲萧衍乙", "甲萧彦乙")
    report = DV.build_diff(MINI_TEXT, after, rules=rules)

    item = report.items[0]
    assert item.attribution == DV.ATTR_UNVERIFIED
    assert item.rule_before == ""
    assert item.rule_after == ""
    assert item.rule_set == []
    assert item.char_spans == [], "归属未验证时不给字符区间（给了就是猜的）"
    assert report.unverified_count == 1


def test_no_rules_marks_no_rules_instead_of_unverified():
    """压根没给规则时，标记应与「给了但验证失败」区分开。"""
    after = _replace_once(MINI_TEXT, "甲萧衍乙", "甲萧彦乙")
    report = DV.build_diff(MINI_TEXT, after)   # rules=None

    assert report.items[0].attribution == DV.ATTR_NO_RULES


def test_rule_index_rejects_mismatched_rule_lists():
    with pytest.raises(ValueError):
        DV.RuleIndex(["甲", "乙"], ["丙"])


def test_rule_index_replay_is_leftmost_first_wins():
    """重放语义要贴近 ``strings.NewReplacer``：从左到右、first-wins、不重叠。"""
    rules = _rules([("ab", "X"), ("abc", "Y")])
    # 左侧先到先得，"abc" 里的 "ab" 会先被吃掉
    assert rules.replay("abc", [0, 1]) == "Xc"


# ---------------------------------------------------------------------------
# 八、跨行差异
# ---------------------------------------------------------------------------
def test_multi_line_diff_excluded_from_hits():
    """跨行差异在既有口径下被过滤，本层同样不计入 hits 对齐量。"""
    before = MINI_TEXT
    after = before.replace(
        "<p>此处无错字</p>",
        "<p>此处无错字</p>\n    <p>新加一行</p>", 1)
    report = DV.build_diff(before, after)

    multi = [i for i in report.items if i.kind == DV.KIND_MULTI_LINE]
    assert multi or report.items, "新增行必须产生差异项"
    assert report.hit_gap == 0, "无论跨行与否，差额都必须是 0"


# ---------------------------------------------------------------------------
# 九、序列化
# ---------------------------------------------------------------------------
def test_to_dict_is_json_serialisable_and_flat():
    """E2 直接吃这个 dict，必须能过 JSON、字段名稳定。"""
    after = _replace_once(MINI_TEXT, "甲萧衍乙", "甲萧彦乙")
    rules = _rules([("萧衍", "萧彦")])
    report = DV.build_diff(MINI_TEXT, after, rules=rules)

    payload = report.to_dict()
    text = json.dumps(payload, ensure_ascii=False)
    back = json.loads(text)

    item = back["items"][0]
    for key in ("index", "kind", "before_text", "after_text", "before", "after",
                "char_spans", "occurrences", "attribution", "rule_before",
                "rule_after", "has_stripped_copy"):
        assert key in item, f"差异项缺字段：{key}"

    for key in ("chapter_index", "chapter_path", "chapter_title", "line",
                "char_start", "char_end"):
        assert key in item["before"]

    summary = back["summary"]
    for key in ("item_count", "hits", "hit_gap", "hits_verified", "stripped_copies"):
        assert key in summary


def test_diff_to_json_helper():
    after = _replace_once(MINI_TEXT, "甲萧衍乙", "甲萧彦乙")
    report = DV.build_diff(MINI_TEXT, after)
    assert json.loads(DV.diff_to_json(report))["summary"]["item_count"] == 1


def test_compute_diff_metrics_reports_all_five_numbers():
    after = _replace_once(MINI_TEXT, "甲萧衍乙", "甲萧彦乙")
    metrics = DV.compute_diff_metrics(DV.build_diff(MINI_TEXT, after))
    assert set(metrics) == {"差异项", "计入词条的差异项", "替换统计 hits",
                            "跨行差异（不计入 hits）", "去标签副本",
                            "核对差额", "归属未验证"}


# ---------------------------------------------------------------------------
# 十、硬约束自检：不碰装载层
# ---------------------------------------------------------------------------
def test_does_not_touch_loading_layer():
    """本卡硬约束：不得触碰 ``vocab_bridge.compose()`` / ``bags.write_round_rules()``。

    装载层的唯一入口由 B3 / C1 串行扩展；E 组另造一条过滤 / 装载路径就是违规。
    这条用例扫本模块源码，确保里面连这两个名字都没出现过。
    """
    src = (ROOT / "fixtext_ui" / "fixtext_diff_view.py").read_text(encoding="utf-8")

    # 注释与文档里可以提到这两个名字（用来声明"不碰它"），但不得调用
    for banned in ("vocab_bridge.compose(", "write_round_rules(", "vocab_bridge"):
        calls = [
            line for line in src.split("\n")
            if banned in line and not line.strip().startswith("#")
            and "``" not in line and '"' not in line
        ]
        assert not calls, f"差异层出现了装载层调用：{calls}"


def test_does_not_reimplement_engine():
    """归因靠重放验证，不靠自己造引擎：源码里不应出现 Go 引擎 / 进程调用。"""
    src = (ROOT / "fixtext_ui" / "fixtext_diff_view.py").read_text(encoding="utf-8")
    for banned in ("subprocess", "GoEngineClient", "pyahocorasick", "ahocorasick"):
        assert banned not in src, f"差异层不该出现 {banned}"


# ---------------------------------------------------------------------------
# 十一、真实运行产物上的一致性（fixture 缺失时跳过，不造假数据）
# ---------------------------------------------------------------------------
def _real_run_dir() -> Path | None:
    """找一次真实运行目录（替换阶段产物齐全）。"""
    for cand in (ROOT / "runs" / "t33_real" / "work",):
        if (cand / "03_replace" / "replace_report.json").is_file():
            return cand
    return None


@pytest.mark.skipif(_real_run_dir() is None, reason="没有可用的真实运行产物")
def test_real_run_numbers_are_consistent():
    """真实 301 章书上：差异项 / hits / 去标签副本三者必须对得上账。

    这是验收判据「差异结果与替换报告的数字一致」的机器化版本：
    差额必须为 0，且 hits 必须等于导出层同一函数算出来的值。
    """
    import fixtext_export

    work = _real_run_dir()
    report = DV.build_diff_for_run(work.parent, verify_hits=True)

    before_path = Path(report.before_path)
    after_path = Path(report.after_path)
    expected_hits, _rows = fixtext_export._count_hits(before_path, after_path, work)

    assert report.hits == expected_hits, "差异层 hits 必须与导出层同函数同值"
    assert report.hit_gap == 0, (
        f"对账差额应为 0，实际 {report.hit_gap}"
        f"（差异项 {report.item_count} + 副本 {report.stripped_copies}"
        f" vs hits {report.hits}）")
    assert report.item_count > 0
    assert len(report.chapters) > 0


@pytest.mark.skipif(_real_run_dir() is None, reason="没有可用的真实运行产物")
def test_real_run_line_numbers_all_correct():
    """真实书上逐条校验行号——542 条全对才算位置可用。"""
    work = _real_run_dir()
    report = DV.build_diff_for_run(work.parent, verify_hits=False)
    blines = Path(report.before_path).read_text(encoding="utf-8").split("\n")
    alines = Path(report.after_path).read_text(encoding="utf-8").split("\n")

    bad = [i.index for i in report.items
           if blines[i.before.line - 1] != i.before_text
           or alines[i.after_ref.line - 1] != i.after_text]

    assert bad == [], f"行号错位的差异项：{bad[:10]}"


@pytest.mark.skipif(_real_run_dir() is None, reason="没有可用的真实运行产物")
def test_real_run_attribution_is_honest():
    """真实书上归属要么 verified / verified_set，要么 unverified——没有半猜的。"""
    work = _real_run_dir()
    report = DV.build_diff_for_run(work.parent, verify_hits=False)

    allowed = {DV.ATTR_VERIFIED, DV.ATTR_VERIFIED_SET, DV.ATTR_UNVERIFIED, DV.ATTR_NO_RULES}
    assert {i.attribution for i in report.items} <= allowed

    for item in report.items:
        if item.attribution == DV.ATTR_VERIFIED:
            assert item.rule_before and item.rule_after
        elif item.attribution == DV.ATTR_VERIFIED_SET:
            assert len(item.rule_set) >= 2
        else:
            assert item.rule_before == "" and item.rule_after == ""
