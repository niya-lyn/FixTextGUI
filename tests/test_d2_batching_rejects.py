"""V1.1-D2 · 超限分批 + 不合格行清单 的单测。

用例组织对齐 9.4 的两条验收判据，不是泛泛覆盖：

**判据一 · 不合格行不阻塞合法行入库。**
「不阻塞」必须在**结构上**可证，而不是「跑一遍看起来没问题」：
`ImportPrep.plan` 里只装合法行，所以要证明的是三件事——
① 混合表里每条合法行都进了批（不因旁边的烂行被牵连）；
② 不合格行一条都没进批（否则它们的处理失败会拖住整批）；
③ 两边不重不漏（条数守恒），且合法行条数与输入里合法的行数相等。
另外还有一个**反向对照**：把合法行人为删掉，断言结果确实变空——
证明上面的断言不是恒真的空转。

**判据二 · 清单每条能定位到原始行号。**
最硬的验法是「回原文按行号取那一行」，逐条比对：
`原文.split("\n")[行号 - 1]` 必须**逐字**等于清单里的「该行原文」；
且行号口径与 D1 一致——原版导出的说明文字在第 1 行（置空不删行），
所以第一条词条的行号是 2，不是 1。用真实原版导出样本
（`orig_oldstyle_map.csv`，1103 行）做这一组，对 1102 行逐条核对。

分批侧对应的是「每批的原始行号区间」：进度卡在哪批 = 卡在哪一段原文。

两条判据都有一个**跨模块**用例：从真实文本解析、切分、再回原文核对，
而不是只喂手工构造的对象。
"""

from __future__ import annotations

import ast
import re
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
MOD = PKG / "fixtext_vocab_import"
import sys                                           # noqa: E402
for _p in (PKG, PKG / "fixtext_ui"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fixtext_vocab_import import (                     # noqa: E402
    DEFAULT_BATCH_SIZE,
    DEFAULT_BATCH_THRESHOLD,
    BatchPolicy,
    ImportPrep,
    parse_file,
    parse_text,
    plan_batches,
    prepare_from_rejects,
    prepare_import,
    run_batches,
)
from fixtext_vocab_import import messages as msg        # noqa: E402
from fixtext_vocab_import.batching import (             # noqa: E402
    BatchFailure,
    BatchPlan,
    ProgressReport,
)
from fixtext_vocab_import.mapping import MappedRow, ColumnMapping, apply_mapping  # noqa: E402
from fixtext_vocab_import.rejects import (              # noqa: E402
    EXPORT_COLUMNS,
    REJECT_REASONS,
    RejectList,
    RejectedRow,
    judge_row,
    partition_rows,
    partition_sheet,
    reason_of,
)

SAMPLES = HERE / "samples" / "vocab_import"
OLD_STYLE = SAMPLES / "orig_oldstyle_map.csv"

#: 原版导出写在第一行的说明文字（与 D1 的 parse 判定同一特征）
BANNER = ("【英文逗号】【英文单引号】【英文双引号】【换行符】"
          "，这几种符号都被转成了以【】包裹的特殊标记，如果要在程序中用到，需要自行还原")

#: 一张既有合法行、又有各类不合格行的混合表（每行编号都能在注释里数清楚）
MIXED_TEXT = "\n".join([
    BANNER,                                             # 第 1 行：说明文字（置空不删）
    "错词,正确写法,分类",                                # 第 2 行：表头
    "萧衍,萧彦,角色名",                                  # 第 3 行：合法
    ",萧彦,角色名",                                      # 第 4 行：错词空
    "萧衍,,角色名",                                      # 第 5 行：正确写法空
    "萧衍,萧彦,角色名",                                  # 第 6 行：合法
    "九牛二虎",                                          # 第 7 行：少了几格
    ",,备注",                                             # 第 8 行：两格都空（分类有字，不算空行）
    "   ,萧彦,角色名",                                   # 第 9 行：错词只有普通空格
    "\u3000,萧彦,角色名",                                # 第 10 行：错词是整格全角空格
    "萧彦,萧衍,角色名",                                  # 第 11 行：合法
    "",                                                  # 第 12 行：空行（跳过，不占词条）
    "何晏,何宴,角色名",                                  # 第 13 行：合法
])

#: 上面这张表里**应当合格**的行号（判据一的正向对照组）
MIXED_GOOD_LINES = [3, 6, 11, 13]
#: 上面这张表里**应当进清单**的行号与原因（判据二的正向对照组）
MIXED_BAD = {
    4: "WORD_EMPTY",
    5: "VALUE_EMPTY",
    7: "SHORT_ROW",
    8: "BOTH_EMPTY",
    9: "WORD_EMPTY",       # 只有普通空格 → 仍然是空
    10: "WORD_EMPTY",      # 整格全角空格 → 仍然是空（本卡补的判定）
}


def _raw_lines(text: str) -> list[str]:
    return text.split("\n")


# ===========================================================================
# 判据一 · 不合格行不阻塞合法行入库
# ===========================================================================

def test_mixed_table_keeps_every_legal_row_in_the_plan():
    """混合表里每条合法行都进了批——不因旁边的烂行被牵连。"""
    prep = prepare_import(parse_text(MIXED_TEXT))
    planned = [row.line_no for batch in prep.plan for row in batch.rows]
    assert planned == MIXED_GOOD_LINES, "合法行必须一条不少地进批，且保持原文顺序"
    assert prep.blocking is False, "有合法行、列也指好了，就不该判成整表阻塞"


def test_mixed_table_keeps_every_illegal_row_out_of_the_plan():
    """不合格行一条都没进批——否则它的失败会把整批拖住。"""
    prep = prepare_import(parse_text(MIXED_TEXT))
    planned = {row.line_no for batch in prep.plan for row in batch.rows}
    assert not (planned & set(MIXED_BAD)), (
        f"不合格行不该进批，却在批里：{sorted(planned & set(MIXED_BAD))}"
    )
    got = {r.line_no: r.code for r in prep.rejects.rejects}
    assert got == MIXED_BAD, "清单必须收全每一类不合格行，且原因分类正确"


def test_counts_are_conserved_no_row_is_lost_or_double_counted():
    """两边不重不漏：合法行 + 不合格行 = 全部非空行。"""
    prep = prepare_import(parse_text(MIXED_TEXT))
    assert prep.rejects.conserved()
    assert prep.total_rows == len(MIXED_GOOD_LINES) + len(MIXED_BAD)
    # 空行（第 12 行）由 D1 跳过，不作为词条出现，也不影响别人的行号
    assert prep.rejects.skipped_blank >= 1


def test_negative_control_deleting_legal_rows_empties_the_plan():
    """反向对照：把合法行删掉，批里就只剩空格——证明上一条不是恒真空转。"""
    only_bad = "\n".join([
        "错词,正确写法,分类",
        ",萧彦,角色名",
        "萧衍,,角色名",
    ])
    prep = prepare_import(parse_text(only_bad))
    assert prep.plan.total_rows == 0
    assert prep.plan.batch_count == 0
    assert len(prep.rejects.rejects) == 2


def test_real_old_style_file_is_fully_legal_and_fully_planned():
    """真实 1102 行旧式词库：一行不合格都没有，也一行都没被漏掉。

    这份文件首行是原版说明文字、没有表头，所以首条词条是第 2 行。
    """
    prep = prepare_import(parse_file(OLD_STYLE))
    assert len(prep.rejects.rejects) == 0
    assert prep.plan.total_rows == 1102
    assert [r.line_no for b in prep.plan for r in b.rows] == list(range(2, 1104))


def test_blocking_only_when_the_columns_are_not_assigned():
    """「整表阻塞」只发生在列没指好时——那是配置问题，不是用户的行有错。"""
    sheet = parse_text("萧衍,萧彦,角色名\n九牛二虎,九牛二虎之力,其他")
    sheet.set_mapping(ColumnMapping.all_ignored(sheet.column_count))
    prep = ImportPrep(rejects=partition_sheet(sheet),
                      plan=plan_batches(partition_sheet(sheet).good))
    assert prep.blocking is True
    assert prep.good == []
    # 阻塞时每一行都进清单，原因统一是「还没指定列」
    assert {r.code for r in prep.rejects.rejects} == {"NO_WORD_COLUMN"}
    assert len(prep.rejects.rejects) == 2


def test_blocking_explains_both_missing_columns_without_repeating_per_row():
    """阻塞的说明只讲两条（缺两列），不把每一行都念一遍。"""
    sheet = parse_text("萧衍,萧彦\n九牛二虎,九牛二虎之力\n何晏,何宴")
    sheet.set_mapping(ColumnMapping.all_ignored(sheet.column_count))
    lst = partition_sheet(sheet)
    items = lst.blocking_items()
    assert len(items) == 1 and "错词" in items[0]
    assert lst.is_blocking()

    sheet2 = parse_text("萧衍\t萧彦")
    sheet2.set_mapping(ColumnMapping(roles=["word", "ignore"]))   # 只缺「正确写法」
    lst2 = partition_sheet(sheet2)
    assert {r.code for r in lst2.rejects} == {"NO_VALUE_COLUMN"}
    assert "正确写法" in lst2.blocking_items()[0]


# ===========================================================================
# 判据二 · 清单每条能定位到原始行号
# ===========================================================================

def test_every_reject_points_at_the_real_original_line():
    """最硬的验法：回原文按行号取那一行，逐字比对。"""
    prep = prepare_import(parse_text(MIXED_TEXT))
    lines = _raw_lines(MIXED_TEXT)
    for r in prep.rejects.rejects:
        actual = lines[r.line_no - 1]
        assert r.raw_line == actual, (
            f"第 {r.line_no} 行取回的是 {actual!r}，清单里记的是 {r.raw_line!r}"
        )


def test_line_number_keeps_d1_banner_convention_banner_is_line_1():
    """行号口径与 D1 一致：说明文字是第 1 行（置空不删），首条词条是第 2 行。"""
    sheet = parse_text(MIXED_TEXT)
    assert sheet.banner_removed is True
    # 说明文字占第 1 行、表头占第 2 行，首条词条就是第 3 行——一行都没前移
    assert sheet.data_rows[0][0] == 3, "首条词条的行号必须是 3（说明 1 / 表头 2），不能前移"
    assert sheet.headers == ["错词", "正确写法", "分类"]
    prep = prepare_import(sheet)
    assert prep.rejects.banner_note is True
    assert "行号没有前移" in prep.rejects.header_note()


def test_real_file_1102_rows_line_numbers_match_the_file_verbatim():
    """真实文件逐条核对：1102 条行号与原文逐字对齐（不是抽查）。"""
    sheet = parse_file(OLD_STYLE)
    raw = OLD_STYLE.read_text(encoding="utf-8-sig").split("\n")
    rows = sheet.mapped().rows
    assert len(rows) == 1102
    mismatches = [
        (r.line_no, raw[r.line_no - 1])
        for r in rows
        if raw[r.line_no - 1].strip() and raw[r.line_no - 1].rstrip("\r") != raw[r.line_no - 1]
    ]
    # 该文件是 LF 落盘的（D1 样本已统一），所以逐条都必须**完全**相等
    assert not mismatches, f"行号与原文不一致：{mismatches[:3]}"
    # 关键锚点：第 1 行是说明文字，第 2 行才是首条词条「伕,夫」
    assert raw[0].startswith("【英文逗号】")
    assert raw[1].strip() == "伕,夫"
    assert rows[0].line_no == 2 and rows[0].word == "伕" and rows[0].value == "夫"


def test_crlf_file_keeps_line_numbers_after_newline_normalization():
    """换行统一成 LF 之后，行号照样对得上（CRLF 不会多算一行）。"""
    text = "错词,正确写法\r\n萧衍,萧彦\r\n,萧彦\r\n何晏,何宴\r\n"
    sheet = parse_text(text)
    prep = prepare_import(sheet)
    assert [r.line_no for r in prep.rejects.rejects] == [3]
    lines = sheet.raw_text.split("\n")
    assert prep.rejects.rejects[0].raw_line == lines[2] == ",萧彦"
    assert [r.line_no for b in prep.plan for r in b.rows] == [2, 4]


def test_raw_line_is_kept_verbatim_including_markers_and_spaces():
    """清单里的原文是**未还原、未切列**的那一行，用户能直接拿去比对。"""
    text = "\n".join([
        "错词,正确写法",
        "他说【英文单引号】走【英文单引号】,他说「走」",
        ",只有正确写法【英文逗号】带标记",
    ])
    prep = prepare_import(parse_text(text))
    bad = prep.rejects.rejects[0]
    assert bad.line_no == 3
    assert bad.raw_line == ",只有正确写法【英文逗号】带标记"
    assert "【英文逗号】" in bad.raw_line, "原文要保留占位标记，还原只发生在词条值上"


def test_reject_text_names_the_line_in_human_words():
    """一条人话：「第 4 行：『错词』这一格是空的」。"""
    prep = prepare_import(parse_text(MIXED_TEXT))
    first = prep.rejects.rejects[0]
    assert first.text() == "第 4 行：「错词」这一格是空的"
    assert first.where() == "第 4 行"


# ===========================================================================
# 原因分类
# ===========================================================================

def test_reason_table_covers_every_judged_case_and_is_ordered():
    """原因表要收全判定里会出现的所有 code，且每条都有人话的说明与办法。"""
    codes = [r.code for r in REJECT_REASONS]
    assert len(codes) == len(set(codes)), "原因 code 不能重复"
    for expect in ("NO_WORD_COLUMN", "NO_VALUE_COLUMN", "WORD_EMPTY",
                   "VALUE_EMPTY", "BOTH_EMPTY", "SHORT_ROW"):
        assert expect in codes, f"原因表缺 {expect}"
    for reason in REJECT_REASONS:
        assert reason.label and reason.detail and reason.advice
        assert reason.detail.endswith("。") and reason.advice.endswith("。")
    assert reason_of("WORD_EMPTY").label == "「错词」这一格是空的"


def test_grouped_counts_are_per_reason_in_fixed_order():
    prep = prepare_import(parse_text(MIXED_TEXT))
    grouped = prep.rejects.grouped()
    assert [r.code for r, _rows in grouped] == [
        "WORD_EMPTY", "VALUE_EMPTY", "BOTH_EMPTY", "SHORT_ROW",
    ]
    assert [len(rows) for _r, rows in grouped] == [3, 1, 1, 1]
    for _reason, rows in grouped:
        assert [r.line_no for r in rows] == sorted(r.line_no for r in rows)
    assert prep.rejects.counts() == {
        "「错词」这一格是空的": 3,
        "「正确写法」这一格是空的": 1,
        "「错词」和「正确写法」都是空的": 1,
        "这一行少了几格": 1,
    }


def test_same_word_and_value_is_not_treated_as_invalid():
    """「改前改后一模一样」是能存的词条，不是不合格行——真数据里就有 103 条。"""
    sheet = parse_file(OLD_STYLE)
    same = [r for r in sheet.mapped().rows if r.word == r.value]
    assert len(same) == 103, "样本自带的对照数字（改前改后相同），不能被打成不合格"
    prep = prepare_import(sheet)
    assert len(prep.rejects.rejects) == 0
    assert all(r.line_no in {x.line_no for x in prep.plan.rows} for r in same)


def test_full_width_space_only_cell_is_rejected():
    """整格全角空格看着是空的，D1 的普通去空白判不出来，本卡这一刀要落在。"""
    row = MappedRow(line_no=5, word="\u3000", value="萧彦")
    verdict = judge_row(row, ["\u3000", "萧彦"], ColumnMapping(roles=["word", "value"]), 2)
    assert verdict == ("WORD_EMPTY", "只有空白字符")


def test_short_row_is_told_how_many_cells_it_has():
    """「少了几格」要说出切出几格、表头几列，用户才知道漏在哪。"""
    row = MappedRow(line_no=7, word="九牛二虎", value="")
    verdict = judge_row(row, ["九牛二虎"], ColumnMapping(roles=["word", "value", "type"]), 3)
    assert verdict == ("SHORT_ROW", "只切出 1 格，表头有 3 列")


def test_blank_value_with_only_spaces_is_marked_as_such():
    row = MappedRow(line_no=6, word="萧衍", value="   ")
    verdict = judge_row(row, ["萧衍", "   "], ColumnMapping(roles=["word", "value"]), 2)
    assert verdict == ("VALUE_EMPTY", "只有空白字符")


def test_partition_rows_works_without_a_sheet():
    """轻量入口：手边只有映射结果时也能切分（少「少了几格」这条判定）。"""
    rows = [
        MappedRow(line_no=2, word="萧衍", value="萧彦"),
        MappedRow(line_no=3, word="", value="萧彦"),
        MappedRow(line_no=4, word="何晏", value="  "),
    ]
    lst = partition_rows(rows, raw_lines={2: "萧衍,萧彦", 3: ",萧彦", 4: "何晏,  "})
    assert [r.line_no for r in lst.good] == [2]
    assert [(r.line_no, r.code) for r in lst.rejects] == [(3, "WORD_EMPTY"), (4, "VALUE_EMPTY")]
    assert lst.rejects[0].raw_line == ",萧彦"


# ===========================================================================
# 导出
# ===========================================================================

def test_export_table_has_one_row_per_reject_with_all_columns():
    prep = prepare_import(parse_text(MIXED_TEXT))
    table = prep.rejects.table_lines()
    assert table[0] == list(EXPORT_COLUMNS)
    assert len(table) == 1 + len(prep.rejects)
    assert [row[0] for row in table[1:]] == [str(r.line_no) for r in prep.rejects]
    assert table[1][1] == "「错词」这一格是空的"
    assert table[1][2] == prep.rejects.rejects[0].reason.advice
    for row in table[1:]:
        assert len(row) == len(EXPORT_COLUMNS), "每条七列都要给全，不能缺列"


def test_export_bytes_are_stable_and_openable(tmp_path):
    """导出的是带签名的表格文件：字节稳定、能被重新读出来、行号不丢。"""
    prep = prepare_import(parse_text(MIXED_TEXT))
    path = prep.rejects.write_export(tmp_path / "清单")
    assert path.endswith(".csv")
    raw = Path(path).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "带签名才不会被表格软件当成乱码"
    assert raw == prep.rejects.to_file_bytes(), "写盘内容与内存里的一致"

    text = Path(path).read_text(encoding="utf-8-sig")
    lines = [ln for ln in text.split("\n") if ln]
    assert lines[0].split(",")[0] == "原文行号"
    # 行号那一列逐条对得上
    assert [ln.split(",")[0] for ln in lines[1:]] == [str(r.line_no) for r in prep.rejects]


def test_export_preserves_marker_text_and_compresses_newlines_into_one_row(tmp_path):
    """原文里带换行的单元格不能把清单撑成两行——压成 \\n 写在同格里。"""
    text = "错词,正确写法\n萧衍,萧彦\n,正确写法【换行符】带换行\n何晏,何宴\n"
    prep = prepare_import(parse_text(text))
    rows = prep.rejects.table_lines()
    assert len(rows) == 2, "一行不合格 = 清单里一行，不能因为原文含换行变成两行"
    assert "【换行符】" in rows[1][6]
    assert rows[1][0] == "3"


def test_export_name_is_a_plain_file_name_without_path():
    prep = prepare_import(parse_text(MIXED_TEXT))
    name = prep.rejects.export_name("20261104_1415")
    assert name.startswith("导入不合格清单")
    assert "/" not in name and "\\" not in name
    assert name.endswith(".csv")
    assert "20261104_1415" in name


def test_export_is_offered_only_when_there_is_something_to_export():
    """没有不合格行就不生成空清单糊弄用户。"""
    prep = prepare_import(parse_file(OLD_STYLE))
    assert prep.rejects.export_ready() is False
    assert prep.rejects.summary_text().startswith("全部 1102 行都合格")


def test_summary_text_matches_the_numbers_it_reports():
    prep = prepare_import(parse_text(MIXED_TEXT))
    text = prep.rejects.summary_text()
    assert f"{prep.total_rows} 行里" in text
    assert f"{len(prep.good)} 行合格会照常导入" in text
    assert f"{len(prep.rejects)} 行不合格" in text
    for label, n in prep.rejects.counts().items():
        assert f"{label} {n} 条" in text


# ===========================================================================
# 分批：阈值与边界
# ===========================================================================

def _rows(n: int) -> list[MappedRow]:
    """n 条待处理行，行号从 2 起（模拟首行是表头 / 说明文字的真实情况）。"""
    return [MappedRow(line_no=i + 2, word=f"词{i}", value=f"值{i}") for i in range(n)]


@pytest.mark.parametrize("n, expect_batches", [
    (0, 0),
    (1, 1),
    (DEFAULT_BATCH_THRESHOLD - 1, 1),
    (DEFAULT_BATCH_THRESHOLD, 1),          # 等于阈值仍一次走完
    (DEFAULT_BATCH_THRESHOLD + 1, 2),      # 超过才切
    (DEFAULT_BATCH_SIZE, 1),               # 1000 条（=批大小）仍然一次走完
    (DEFAULT_BATCH_SIZE + 1, 2),
    (DEFAULT_BATCH_SIZE * 3, 3),
])
def test_threshold_decides_whether_to_batch_not_whether_it_can_be_done(n, expect_batches):
    plan = plan_batches(_rows(n))
    assert plan.batch_count == expect_batches
    assert plan.total_rows == n
    assert plan.covers_all_rows()


def test_over_limit_is_reported_from_the_threshold_exactly():
    plan = plan_batches(_rows(DEFAULT_BATCH_THRESHOLD))
    assert plan.over_limit is False
    assert plan.describe() == f"共 {DEFAULT_BATCH_THRESHOLD} 条，一次处理完。"
    plan2 = plan_batches(_rows(DEFAULT_BATCH_THRESHOLD + 1))
    assert plan2.over_limit is True
    assert "分成 2 批处理" in plan2.describe()


def test_batches_are_contiguous_and_cover_every_row_in_order():
    """分批边界：连续切、不重不漏、顺序不变（切点只落在两条之间）。"""
    rows = _rows(7000)
    plan = plan_batches(rows)
    flat = [r for b in plan.batches for r in b.rows]
    assert len(flat) == 7000
    assert [r.line_no for r in flat] == [i + 2 for i in range(7000)], "顺序被改了"
    assert [b.count for b in plan.batches] == [1000] * 7
    # 相邻批的首尾行号紧挨着，没有空洞也没有重叠
    for prev, nxt in zip(plan.batches, plan.batches[1:]):
        assert nxt.first_line == prev.last_line + 1


def test_batch_line_span_is_reported_and_readable():
    plan = plan_batches(_rows(5000))
    plan5 = plan_batches(_rows(5000))
    assert [(b.first_line, b.last_line) for b in plan5.batches] == [
        (2, 1001), (1002, 2001), (2002, 3001), (3002, 4001), (4002, 5001),
    ]
    assert plan5.batches[0].title() == "第 1 / 5 批 · 第 2–1001 行 · 1000 条"
    single = plan_batches(_rows(1)).batches[0]
    assert single.span_text() == "第 2 行"


def test_policy_rejects_nonsense_values():
    with pytest.raises(ValueError):
        BatchPolicy(threshold=0)
    with pytest.raises(ValueError):
        BatchPolicy(batch_size=0)


def test_policy_describe_avoids_internal_jargon():
    text = BatchPolicy(threshold=1000, batch_size=2000).describe()
    assert "阈值" not in text and "参数" not in text
    assert "1000" in text and "2000" in text and "进度" in text


def test_custom_policy_is_honoured():
    plan = plan_batches(_rows(600), BatchPolicy(threshold=100, batch_size=250))
    assert plan.batch_count == 3
    assert [b.count for b in plan.batches] == [250, 250, 100]


def test_plan_refuses_to_lie_about_coverage():
    """自检：故意造一个漏行的计划，必须被抓出来（证明 covers_all_rows 有效）。"""
    rows = _rows(3000)
    plan = plan_batches(rows)
    assert plan.covers_all_rows() is True
    # 人为丢掉最后一批：必须被抓出来（证明这个自检不是恒真）
    broken = BatchPlan(rows=plan.rows, batches=plan.batches[:-1], policy=plan.policy)
    assert broken.covers_all_rows() is False


# ===========================================================================
# 分批：进度反馈
# ===========================================================================

def test_progress_reports_reach_100_and_name_the_batch_span():
    rows = _rows(5000)
    plan = plan_batches(rows)
    seen: list[ProgressReport] = []

    counter = {"t": 0.0}
    def clock() -> float:
        counter["t"] += 0.01
        return counter["t"]

    run_batches(plan, lambda batch: batch.count, on_progress=seen.append, clock=clock)
    assert len(seen) == 5
    assert [r.done for r in seen] == [1000, 2000, 3000, 4000, 5000]
    assert seen[-1].total == 5000
    assert seen[-1].percent == 100.0 and seen[-1].finished
    assert seen[-1].text().endswith("全部处理完了。")
    assert seen[0].text().startswith("第 1 / 5 批 · 第 2–1001 行 · 已完成 1000 / 5000 条（20%）")


def test_eta_comes_from_the_measured_rate_not_from_a_guess():
    """剩余时间必须由**本次实测**速率外推；没有实测就给不出，不编。"""
    rows = _rows(3000)
    plan = plan_batches(rows, BatchPolicy(threshold=100, batch_size=1000))

    ticks = iter([0.0, 1.0, 2.0, 3.0, 4.0])
    reports: list[ProgressReport] = []
    run_batches(plan, lambda b: None, on_progress=reports.append,
                clock=lambda: next(ticks))
    first = reports[0]
    assert first.done == 1000 and first.elapsed == 1.0
    assert first.rate() == 1000.0
    assert abs(first.eta_seconds() - 2.0) < 1e-9, "剩 2000 条、1000 条/秒 → 2 秒"
    assert "大约还要 2 秒" in first.text()


def test_eta_is_absent_when_nothing_has_been_measured_yet():
    """一条都还没处理完（elapsed 为 0）时不给估计——那种数字只能靠猜。"""
    report = ProgressReport(done=0, total=10, batch_index=1, batch_count=1,
                            first_line=2, last_line=2, elapsed=0.0)
    assert report.rate() is None
    assert report.eta_seconds() is None
    assert "正在处理剩下的" in report.text()


def test_eta_switches_to_minutes_for_long_remainders():
    report = ProgressReport(done=100, total=100000, batch_index=1, batch_count=10,
                            first_line=2, last_line=101, elapsed=60.0)
    assert report.eta_seconds() == pytest.approx(99900 / (100 / 60), rel=1e-9)
    assert "分钟" in report.text()


# ===========================================================================
# 分批：失败不丢已完成部分
# ===========================================================================

def test_failing_batch_keeps_the_batches_already_done_and_names_the_span():
    rows = _rows(5000)
    plan = plan_batches(rows)

    calls = {"n": 0}
    def handler(batch):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk full")
        return batch.count

    result = run_batches(plan, handler)
    assert result.ok is False
    assert result.completed_batches == 1
    assert result.rows_done == 1000, "前一批的成果必须留着，不能整批丢"
    assert result.failure.batch_index == 2
    assert (result.failure.first_line, result.failure.last_line) == (1002, 2001)
    assert "第 1002–2001 行" in result.failure.text()
    assert "RuntimeError" not in result.failure.text(), "界面上不许出现异常类名"
    assert "RuntimeError" in result.failure.log_line(), "技术细节只进日志"
    assert "已处理 1000 条（1 批）" in result.summary()


def test_failure_is_humanized_for_common_causes():
    plan = plan_batches(_rows(10), BatchPolicy(threshold=2, batch_size=5))
    result = run_batches(plan, lambda b: (_ for _ in ()).throw(PermissionError("busy")))
    assert result.failure.reason.endswith("。")
    assert "占用" in result.failure.reason
    assert result.rows_done == 0


def test_stop_on_failure_false_continues_other_batches():
    plan = plan_batches(_rows(5000))
    calls = {"n": 0}
    def handler(batch):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return batch.count

    result = run_batches(plan, handler, stop_on_failure=False)
    assert result.failure is not None
    assert result.failure.batch_index == 2
    # 5 批里第 2 批失败，其余 4 批照常走完；失败那批的条数不计入
    assert result.rows_done == 1000 * 4


def test_successful_run_reports_ok_and_total():
    result = run_batches(plan_batches(_rows(100)), lambda b: b.count)
    assert result.ok is True
    assert result.rows_done == 100
    assert result.summary() == "共 100 条分 1 批处理完了。"


def test_keyboard_interrupt_is_not_swallowed_as_a_batch_failure():
    """Ctrl-C 之类不能当成「某批处理失败」继续往下走——它得往上冒。"""
    plan = plan_batches(_rows(10), BatchPolicy(threshold=1, batch_size=5))
    with pytest.raises(KeyboardInterrupt):
        run_batches(plan, lambda b: (_ for _ in ()).throw(KeyboardInterrupt()))


# ===========================================================================
# 跨模块：从真实文本到两份产出，再回原文核对
# ===========================================================================

def test_end_to_end_on_a_large_mixed_table_every_reject_traces_back():
    """3000+ 行的混合表：清单里每条都能回原文取到那一行，批里只有合法行。"""
    lines = ["错词,正确写法,分类"]
    expect_bad: dict[int, str] = {}
    expect_good: list[int] = []
    expect_blank_skipped = 0
    for i in range(1, 3001):
        if i % 97 == 0:
            lines.append(",,")                     # 两格都空（整行被 D1 当空行跳过）
            expect_blank_skipped += 1
        elif i % 89 == 0:
            lines.append(f"词{i},")                # 正确写法空
            expect_bad[len(lines)] = "VALUE_EMPTY"
        elif i % 73 == 0:
            lines.append("孤零零的一格")            # 少了几格
            expect_bad[len(lines)] = "SHORT_ROW"
        else:
            lines.append(f"词{i},值{i},其他")
            expect_good.append(len(lines))
    text = "\n".join(lines)

    t0 = time.perf_counter()
    prep = prepare_import(parse_text(text))
    elapsed = time.perf_counter() - t0

    assert elapsed < 3.0, f"3000 行总耗时 {elapsed:.2f}s，超过一次导入该有的等待"
    assert len(expect_good) + len(expect_bad) + expect_blank_skipped == 3000
    assert prep.rejects.skipped_blank == expect_blank_skipped
    assert prep.rejects.conserved()
    assert [r.line_no for b in prep.plan for r in b.rows] == expect_good
    assert {r.line_no: r.code for r in prep.rejects.rejects} == expect_bad
    assert prep.plan.batch_count >= 2 and prep.needs_progress is True

    raw = text.split("\n")
    for r in prep.rejects.rejects:
        assert r.raw_line == raw[r.line_no - 1], f"第 {r.line_no} 行回原文对不上"
    # 两处都要成立才算判据过：批里只有合法行、清单能回原文
    assert prep.plan.total_rows == len(expect_good)


def test_batching_a_real_1102_row_file_crosses_the_threshold_with_progress():
    """真实文件 1102 条：超过 1000 条阈值 → 切成 2 批、需要给进度。

    这份文件同时是「真实规模」的对照组：1102 条本身来自原版真实导出，
    不是造出来的数字，所以这条阈值判据是拿真数据验的。
    """
    prep = prepare_import(parse_file(OLD_STYLE))
    assert prep.plan.total_rows == 1102
    assert prep.plan.batch_count == 2
    assert [b.count for b in prep.plan.batches] == [1000, 102]
    assert prep.plan.over_limit is True and prep.needs_progress is True
    assert prep.plan.describe() == "共 1102 条，按每批 1000 条分成 2 批处理。"
    assert (prep.plan.batches[0].first_line, prep.plan.batches[0].last_line) == (2, 1001)


def test_a_thousand_rows_exactly_stays_one_batch():
    """1000 条整（=阈值=批大小）一次走完、不给进度——边界不能差一条。"""
    prep = prepare_from_rejects(partition_rows(_rows(1000)))
    assert prep.plan.batch_count == 1
    assert prep.plan.over_limit is False and prep.needs_progress is False
    assert prep.plan.describe() == "共 1000 条，一次处理完。"


# ===========================================================================
# 人话：新增文案同样不许出现技术词（与 D1 同一张禁用表）
# ===========================================================================

def _user_facing_string_constants(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            if re.search(r"[\u4e00-\u9fff]", node.value):
                out.append((node.lineno, node.value))
    return out


def test_no_technical_terms_in_the_two_new_modules():
    """D2 的两个模块同样过 D1 那张禁用表（扫源码字面量，失败文案也跑不到）。"""
    hits: list[str] = []
    for name in ("batching.py", "rejects.py"):
        path = MOD / name
        for line_no, text in _user_facing_string_constants(path):
            low = text.lower()
            for term in msg.FORBIDDEN_TERMS:
                if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", low):
                    hits.append(f"{name}:{line_no}: {term!r} 出现在 {text[:70]!r}")
    assert not hits, "面向用户的文案里出现了技术词：\n" + "\n".join(hits)


def test_all_user_facing_text_of_a_real_partition_is_jargon_free():
    """把真实混合表的产出文案逐条过一遍（不只是扫源码）。"""
    prep = prepare_import(parse_text(MIXED_TEXT))
    texts = [prep.rejects.summary_text(), prep.rejects.header_note(),
             prep.plan.describe()]
    texts += [r.text() for r in prep.rejects.rejects]
    texts += [r.detail + r.advice for r in REJECT_REASONS]
    for text in texts:
        low = text.lower()
        for term in msg.FORBIDDEN_TERMS:
            assert not re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", low), \
                f"文案里出现技术词 {term!r}：{text}"
    # 文案里要出现「行」这个字——判据「能定位到原始行号」在话术上也要落地
    assert all("第 " in r.text() and " 行" in r.text() for r in prep.rejects.rejects)


# ===========================================================================
# 边界与稳定性
# ===========================================================================

def test_empty_list_is_a_normal_state_not_a_crash():
    lst = RejectList()
    assert lst.summary_text() == "全部 0 行都合格，没有不合格的行。"
    assert lst.counts() == {}
    assert lst.table_lines() == [list(EXPORT_COLUMNS)]
    assert lst.conserved()
    assert lst.export_ready() is False


def test_reject_codes_are_stable_strings_not_localized_labels():
    """清单要能被程序读：分类用固定的 code，标签才是中文。"""
    for reason in REJECT_REASONS:
        assert re.fullmatch(r"[A-Z_]+", reason.code), f"code 不稳：{reason.code}"
        assert re.search(r"[\u4e00-\u9fff]", reason.label)


def test_two_partitions_of_the_same_sheet_agree():
    """同一份表切两次结果一致（导出 / 界面 / 批处理拿到的是同一份事实）。"""
    sheet = parse_text(MIXED_TEXT)
    a = prepare_import(sheet)
    b = prepare_import(sheet)
    assert [(r.line_no, r.code) for r in a.rejects.rejects] == \
           [(r.line_no, r.code) for r in b.rejects.rejects]
    assert [r.line_no for r in a.plan.rows] == [r.line_no for r in b.plan.rows]


# ===========================================================================
# 包顶导出完整：D2 的公开类型必须能一步拿到（不能只从子模块 import）
# ===========================================================================

def test_every_d2_public_name_is_reachable_from_the_package_top():
    """D2 的公开名字都得从包顶导出。

    这不是洁癖：界面层只 `from fixtext_vocab_import import ...` 一处，
    拿不到就得知道内部文件名 `batching` / `rejects`，等于把实现细节
    漏给了调用方。本卡交付时 `ProgressReport`（进度回调的类型）
    正好漏在外面，被这条用例的等价检查抓住，补上后才过。
    """
    import fixtext_vocab_import as pkg
    required = [
        # 分批
        "BatchPolicy", "Batch", "BatchPlan", "ProgressReport",
        "BatchFailure", "BatchRunResult", "ImportPrep",
        "plan_batches", "run_batches", "prepare_import", "prepare_from_rejects",
        "DEFAULT_BATCH_THRESHOLD", "DEFAULT_BATCH_SIZE",
        # 不合格清单
        "RejectList", "RejectReason", "RejectedRow",
        "partition_sheet", "partition_rows",
    ]
    missing = [n for n in required if not hasattr(pkg, n)]
    assert not missing, f"包顶缺导出：{missing}"
    assert set(required) <= set(pkg.__all__), "缺名字在 __all__ 里，通配导入拿不到"
