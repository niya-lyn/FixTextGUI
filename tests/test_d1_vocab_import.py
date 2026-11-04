"""V1.1-D1 · 导入来源解析与格式归一 的单测。

这组用例**一一对应 9.3 的三条验收判据**，不是泛泛的覆盖：

A. 「原版非标准转义能被**一次性还原**」——这条判据在技术上要同时成立三件事，
   每件都有会失败的对照组，而不是只跑一遍看它"看起来对"：

   A1 **单趟扫描**。四个真实标记互不相同、还原结果也不构成任何标记，所以
      顺序替换与单趟等价；但只要表里出现「还原文本本身又是另一个标记」，
      顺序替换就会级联放大。`CASCADING_TABLE` 就是这张会级联的表——
      对照组（`sequential_restore_for_test`）必须错，本实现必须对。
   A2 **必须先切列、再还原**。还原出来的 `,` 就是列边界；先还原会把
      一个值里的逗号当成列分隔，2 列裂成 5 列。
   A3 **有损性要如实记账**。词条里本来就有字面量 `【英文逗号】` 时无法区分，
      本实现报还原次数、不假装无损。

B. 「列映射错配时可纠正」——用「两列反了」这个最常见的错配，
   证明 `swap()` 改一次即可，且**不重解析**（同一份 `ParsedSheet` 对象）。

C. 「解析失败给人话原因」——禁用词表机械扫描**所有源码里的用户可见字面量**
   （失败文案在正常测试里跑不到，只有扫源码才能保证它一开始就是人话），
   外加逐个失败场景断言「说得清哪里、为什么、怎么办」，且不含异常类名。

真实样本全部来自原版程序的真实导出（`php` 调 `Csv::mapToCsvFile`），
不是手工仿写的格式：`orig_tempMap_all_markers.csv`（四种占位符齐全）、
`orig_normalmap_markers.csv`（出厂词库里真实含占位符的词条）、
`orig_oldstyle_map.csv`（1103 行真实旧式词库）。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
MOD = PKG / "fixtext_vocab_import"
for _p in (PKG, PKG / "fixtext_ui"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fixtext_vocab_import import (  # noqa: E402
    ColumnMapping,
    ParseError,
    contains_escaped_markers,
    escape_escaped,
    guess_delimiter,
    human_error,
    parse_file,
    parse_text,
    restore_escaped_once,
)
from fixtext_vocab_import import messages as msg  # noqa: E402
from fixtext_vocab_import.dialect import QUOTE_AWARE_DELIMITERS, delimiter_name  # noqa: E402
from fixtext_vocab_import.escape import (  # noqa: E402
    CASCADING_TABLE,
    CSV_ESCAPED_CHARS,
    sequential_restore_for_test,
)
from fixtext_vocab_import.mapping import (  # noqa: E402
    DEFAULT_TYPE,
    ROLE_IGNORE,
    ROLE_TYPE,
    ROLE_VALUE,
    ROLE_WORD,
)

SAMPLES = HERE / "samples" / "vocab_import"

#: 原版 `Csv.php` 里的四项，逐字对照（少一项就等于漏还原一种符号）
ORIG_MARKERS = ("【英文逗号】", "【英文单引号】", "【英文双引号】", "【换行符】")
ORIG_CHARS = (",", "'", '"', "\n")


# ===========================================================================
# A. 一次性还原
# ===========================================================================

def test_escape_table_matches_original_php_table_verbatim():
    """转义表必须与原版 `Csv.php` 的静态数组**逐字**一致。

    这是本卡所有还原断言的源头：表错了，后面全错，而且是"看起来对"的错。
    """
    assert dict(CSV_ESCAPED_CHARS) == {
        ",": "【英文逗号】",
        "'": "【英文单引号】",
        '"': "【英文双引号】",
        "\n": "【换行符】",
    }
    assert tuple(c for c, _m in CSV_ESCAPED_CHARS) == ORIG_CHARS
    assert tuple(m for _c, m in CSV_ESCAPED_CHARS) == ORIG_MARKERS


def test_A1_single_pass_vs_sequential_on_cascading_table():
    """A1 · 会级联的表上：顺序替换必错，单趟必对。

    对照组不是摆设——它真的产出不一样的结果，这条用例才算证明了事情。
    """
    text = "x【A】y"
    once = restore_escaped_once(text, table=CASCADING_TABLE).text
    seq = sequential_restore_for_test(text, CASCADING_TABLE)

    assert once == "x【逗号】y"          # 单趟：只还原一层，不再回头啃
    assert seq == "xBy"                  # 顺序：把上一步的结果又啃了一遍
    assert once != seq, "对照组必须与本实现不同，否则这条用例证明不了任何事"


def test_A1_real_table_single_pass_eq_sequential_and_correct():
    """A1 · 真实表上单趟与顺序等价（这正是原版能工作的原因，可复算）。"""
    text = ('混合【英文逗号】他说【英文双引号】停【英文双引号】'
            '【换行符】再【英文单引号】走【英文单引号】【英文逗号】')
    once = restore_escaped_once(text).text
    seq = sequential_restore_for_test(text, CSV_ESCAPED_CHARS)

    assert once == seq == '混合,他说"停"\n再\'走\','
    for marker in ORIG_MARKERS:
        assert marker in text, "四个标记都要出现，不能只验其中一两个"


def test_A1_restore_counts_are_per_marker_and_summed():
    """还原次数要能逐标记复核——否则「还原了几处」只是个说不清的数字。"""
    report = restore_escaped_once("a,b【英文逗号】c【换行符】d")
    assert report.replaced == 2
    assert report.counts == {"【英文逗号】": 1, "【换行符】": 1}
    assert report.touched is True
    assert restore_escaped_once("没有标记的普通词条").replaced == 0


def test_A2_split_first_then_restore_real_sample():
    """A2 · 原版真实导出的那一行：先还原再切列会裂成 5 列，先切列再还原是 2 列。

    这行来自 `orig_tempMap_all_markers.csv` 第 8 行（`php` 真实导出）：
        只有逗号在中间【英文逗号】a【英文逗号】b【英文逗号】,只有逗号在中间
    值里有 3 个逗号：先还原 → 5 列；先切列 → 正好 2 列。
    """
    line = "只有逗号在中间【英文逗号】a【英文逗号】b【英文逗号】,只有逗号在中间"

    wrong_order = restore_escaped_once(line).text.split(",")          # 先还原 → 错
    right_order = [restore_escaped_once(f).text for f in line.split(",")]

    assert len(wrong_order) == 5, "对照组应当裂成 5 列（证明先还原确实是错的）"
    assert len(right_order) == 2, "先切列再还原应当得到 2 列"
    assert right_order == ["只有逗号在中间,a,b,", "只有逗号在中间"]


def test_A2_end_to_end_all_four_markers_from_real_export():
    """A2 · 原版真实导出的四种占位符，端到端走完整管线后全部复原。"""
    sheet = parse_file(SAMPLES / "orig_tempMap_all_markers.csv")

    assert sheet.delimiter == ","
    assert sheet.column_count == 2, "先切列再还原：整表列数必须是 2，不能被值里的逗号切坏"
    assert sheet.row_count == 7

    result = sheet.mapped()
    assert not result.bad(), [r.problem for r in result.bad()]
    got = [(r.word, r.value) for r in result.good()]

    assert ("逗号测试,尾巴", "逗号测试，尾巴") in got
    assert ("他说'你好'就走了", "他说「你好」就走了") in got
    assert ('他说"你好"就走了', "他说「你好」就走了") in got
    assert ("换行测试\n第二行", "换行测试第二行") in got
    assert ("混合,他说\"停\"\n再'走',", "混合：他说「停」再走") in got
    assert ("只有逗号在中间,a,b,", "只有逗号在中间") in got

    # 还原次数必须与数据行里标记的实际个数一致（可回原文复核）；
    # 首行是原版自带的说明文字，含 4 个标记，不算在内。
    data_lines = (SAMPLES / "orig_tempMap_all_markers.csv").read_text(
        encoding="utf-8").split("\n")[1:]
    expected = sum(line.count(m) for line in data_lines for m in ORIG_MARKERS)
    assert result.restored_marks == expected == 16


def test_A3_lossy_and_honest_on_real_factory_entries():
    """A3 · 出厂词库里真实存在的「值本身带逗号/换行」的词条，还原后保真。

    `啾了一嘴,`（值里真逗号）、`匆念\\n`（值里真换行）都来自
    `orig_normalmap_markers.csv`——原版 `normalMap` 真实导出的行。
    还原必须把它们还原成**原字符**，且尾部换行不能被 `strip()` 吃掉：
    那枚换行是替换时要连行尾一起吃掉的内容，吃掉就等于改坏词条。
    """
    sheet = parse_file(SAMPLES / "orig_normalmap_markers.csv")
    got = {r.word: r.value for r in sheet.mapped().good()}

    assert got["啾了一嘴"] == "啾了一嘴,", "值里的逗号必须还原成真逗号"
    assert got["匆念\n"] == "勿念\n", "键与值里的换行都要在，且不能被 strip 掉"
    assert all(v.endswith("\n") for k, v in got.items() if k.endswith("\n"))


def test_A3_lossy_case_is_reported_not_hidden():
    """A3 · 词条里本来就有字面量标记时，还原是有损的——必须报次数，不能假装无损。

    原版同样无法区分「五个汉字」与「一枚逗号」。本卡只保证：
    ① 会去还原（与原版一致）；② 把改动次数报出来让人可复核；
    ③ 实现说明里如实写明这是有损的。
    """
    sheet = parse_text("口令【英文逗号】,口令\n普通,常见")
    result = sheet.mapped()
    assert result.restored_marks == 1
    assert result.good()[0].word == "口令,", "字面量标记会被还原——这是有损的那一面"
    assert restore_escaped_once("口令【英文逗号】").replaced == 1


def test_A_round_trip_escape_then_restore():
    """escape → restore 往返：含四个原字符的词条也要逐字回到原文。"""
    for word in ("萧衍", "九牛二虎之力", "他说「你好」就走了", "匆念"):
        assert restore_escaped_once(escape_escaped(word)).text == word
    for word in ("a,b", "他说'停'", 'a"b"', "两行\n内容"):
        assert restore_escaped_once(escape_escaped(word)).text == word


def test_contains_escaped_markers():
    assert contains_escaped_markers("啾了一嘴【英文逗号】")
    assert contains_escaped_markers("匆念【换行符】")
    assert not contains_escaped_markers("萧衍")
    assert not contains_escaped_markers("")


def test_orig_banner_line_is_not_imported_as_a_word():
    """原版导出文件的第一行是它自己的说明文字，不能当成词条。

    这行自己含一个真逗号，会让首行切成 3 列、把整表列数一致性从 100% 拉到 88%
    ——真实踩到过（未处理时映射出 1 条不合格）。
    """
    sheet = parse_file(SAMPLES / "orig_tempMap_all_markers.csv")
    assert not sheet.mapped().bad(), "说明文字被当词条时这里会出现不合格行"
    assert sheet.row_count == 7, "7 条真词条，说明文字不计入"
    assert sheet.data_rows[0][0] == 2, "说明文字置空但行号保持，第一条真词条仍在第 2 行"
    assert "说明文字" in sheet.messages.text()


# ===========================================================================
# B. 列映射错配可纠正
# ===========================================================================

def test_B_reversed_columns_are_corrected_without_reparsing():
    """B · 两列反了（最常见的错配）：换一次映射即可，且**同一份解析结果**可用。

    这里不假设表头识别会认错——恰恰相反，`正确写法,错词,分类` 这种表头
    提示词能认对（另一条用例单独验这个）。所以本用例**显式把映射设成反的**
    （模拟用户手动指错，或表头无提示词时默认按位置指派），先证明反了真的错，
    再用 `swap` 纠正，并验证纠正**没有重新解析**（行号与原始单元格都还在）。
    """
    text = "正确写法,错词,分类\n萧彦,萧衍,角色名\n九牛二虎之力,九牛二虎,其他"
    sheet = parse_text(text)
    assert sheet.mapping.roles == [ROLE_VALUE, ROLE_WORD, ROLE_TYPE], "表头提示词把两列认对了"

    # 显式设成反的映射（用户手滑 / 无表头时按位置默认）
    sheet.set_mapping(ColumnMapping(roles=[ROLE_WORD, ROLE_VALUE, ROLE_TYPE]))
    wrong = sheet.mapped()
    assert [(r.word, r.value) for r in wrong.good()] == [
        ("萧彦", "萧衍"), ("九牛二虎之力", "九牛二虎"),
    ], "反着读时必须真的读出反的词条（否则下面的纠错验证是空的）"

    raw_before = [list(f) for _ln, f in sheet.data_rows]
    sheet.set_mapping(sheet.mapping.swap(0, 1))
    after = sheet.mapped()
    assert [(r.word, r.value) for r in after.good()] == [
        ("萧衍", "萧彦"), ("九牛二虎", "九牛二虎之力"),
    ]
    assert [ln for ln, _f in sheet.data_rows] == [2, 3], "纠错没有重解析：行号还是那两行"
    assert [list(f) for _ln, f in sheet.data_rows] == raw_before, "原始单元格没被纠正动作改动"


def test_B_assigning_a_role_releases_the_other_column():
    """B · 把某列改指给一个已被别列占用的用途，必须自动解占（不会两列同角色）。"""
    mapping = ColumnMapping(roles=[ROLE_VALUE, ROLE_WORD, ROLE_TYPE])
    moved = mapping.with_role(0, ROLE_WORD)
    assert moved.roles == [ROLE_WORD, ROLE_IGNORE, ROLE_TYPE]
    assert moved.word_column == 0 and moved.value_column is None


def test_B_unknown_role_and_bad_column_are_rejected():
    """B · 越界与未知用途必须当场失败，不能静默接受。"""
    mapping = ColumnMapping(roles=[ROLE_WORD, ROLE_VALUE])
    with pytest.raises(ValueError):
        mapping.with_role(5, ROLE_WORD)
    with pytest.raises(ValueError):
        mapping.with_role(0, "not-a-role")
    with pytest.raises(ValueError):
        mapping.swap(0, 9)


def test_B_missing_key_columns_are_named_in_human_words():
    """B · 关键列没指到时，要说清缺哪一列（人话，不带角色代号）。"""
    mapping = ColumnMapping(roles=[ROLE_IGNORE, ROLE_IGNORE])
    problems = mapping.problems()
    assert "「错词」" in problems[0]
    assert "「正确写法」" in problems[1]
    assert not mapping.is_ready()

    joined = " ".join(problems).lower()
    for term in msg.FORBIDDEN_TERMS:
        assert term not in joined


def test_B_mapping_must_match_column_count():
    """B · 指派数量与列数不一致时必须拒绝，否则会静默错位。"""
    sheet = parse_text("错词,正确写法\n甲,乙")
    with pytest.raises(ValueError):
        sheet.set_mapping(ColumnMapping(roles=[ROLE_WORD]))


def test_B_describe_is_human_readable():
    """B · 逐列说明给的是人话用途名，不是 word/value 代号。"""
    mapping = ColumnMapping(roles=[ROLE_WORD, ROLE_VALUE, ROLE_TYPE])
    assert mapping.describe() == ["第 1 列：错词", "第 2 列：正确写法", "第 3 列：分类"]


def test_B_free_rearrangement_any_order():
    """B · 任意列序都能改对：把「分类」放到第 1 列的怪表也能救回来。"""
    text = "分类,错词,正确写法\n角色名,萧衍,萧彦\n其他,九牛二虎,九牛二虎之力"
    sheet = parse_text(text)
    assert sheet.mapping.roles == [ROLE_TYPE, ROLE_WORD, ROLE_VALUE]
    assert [(r.word, r.value, r.typ) for r in sheet.mapped().good()] == [
        ("萧衍", "萧彦", "角色名"), ("九牛二虎", "九牛二虎之力", "其他"),
    ]


# ===========================================================================
# C. 解析失败给人话
# ===========================================================================

def _user_facing_string_constants(path: Path) -> list[tuple[int, str]]:
    """抽出一个模块里**所有**中文字符串字面量（f-string 模板算在内，docstring 排除）。"""
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


def test_C_no_technical_terms_leak_into_user_facing_strings():
    """C · 机械扫描：源码里所有面向用户的中文字面量都不许出现技术词。

    扫**源码字面量**而不是"跑一遍看输出"，因为失败路径的文案在正常测试里
    根本跑不到——只有扫源码才能保证它一开始就是人话。
    """
    hits: list[str] = []
    for path in sorted(MOD.glob("*.py")):
        for line_no, text in _user_facing_string_constants(path):
            low = text.lower()
            for term in msg.FORBIDDEN_TERMS:
                # 词边界：避免 "int" 命中 "point" 之类假阳性
                if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", low):
                    hits.append(f"{path.name}:{line_no}: {term!r} 出现在 {text[:70]!r}")
    assert not hits, "面向用户的文案里出现了技术词：\n" + "\n".join(hits)


def test_C_forbidden_list_itself_covers_the_judgement():
    """C · 禁用表本身要覆盖判据点名的几类词（不是一张随便写的表）。"""
    for must in ("utf-8", "gbk", "gb18030", "bom", "encoding", "codec",
                 "delimiter", "csv", "exception", "traceback", "error"):
        assert must in msg.FORBIDDEN_TERMS


def test_C_failure_messages_say_where_why_and_what_to_do():
    """C · 每种失败都要说清「哪里 / 为什么 / 怎么办」三件事。"""
    cases = {
        "空内容": msg.empty_input(),
        "成不了列": msg.no_columns(),
        "读不出来": msg.unreadable_text("换了几种常见写法都没读通"),
        "文件不在": msg.file_missing("词表.txt"),
        "类型不对": msg.not_a_table_file(".pdf"),
        "体积超限": msg.file_too_big(80.0, 64.0),
        "列没对应好": msg.mapping_problem("还没有指定哪一列是「错词」"),
    }
    for name, problem in cases.items():
        assert isinstance(problem, ParseError)
        assert problem.headline, f"{name} 缺结论句"
        assert problem.details, f"{name} 缺原因"
        assert problem.advice, f"{name} 缺下一步"
        assert problem.advice.rstrip().endswith(("。", "！")), f"{name} 的建议句没写完"


def test_C_error_str_is_human_and_has_no_class_name():
    """C · 异常转成字符串也是人话——不能带类名、不能带英文术语。"""
    rendered = str(msg.empty_input())
    assert "ParseProblem" not in rendered
    assert "Exception" not in rendered
    for term in msg.FORBIDDEN_TERMS:
        assert term not in rendered.lower()


@pytest.mark.parametrize(
    "exc, expect_keyword",
    [
        (PermissionError("denied"), "占用"),
        (FileNotFoundError("gone"), "找不到"),
        (IsADirectoryError("dir"), "文件夹"),
        (UnicodeError("bad"), "读不出来"),
        (MemoryError(), "太大"),
        (OSError("io"), "读不进去"),
    ],
)
def test_C_human_error_translates_common_failures(exc, expect_keyword):
    """C · 常见异常都要翻成人话，且不吐英文类名。"""
    text = human_error(exc)
    assert expect_keyword in text
    assert type(exc).__name__ not in text, "界面文案不许出现异常类名"


def test_C_human_error_fallback_does_not_leak_class_name():
    """C · 兜底分支同样不许吐类名——这是最容易顺手写成 f"{name}" 的一处。"""
    class WeirdError(RuntimeError):
        pass

    text = human_error(WeirdError("boom"))
    assert "WeirdError" not in text
    assert "RuntimeError" not in text
    assert text.endswith(("。", "！"))


def test_C_log_line_keeps_technical_detail_out_of_the_ui():
    """C · 技术细节走日志专用函数，界面文案与日志各走各的。"""
    bad = UnicodeDecodeError("utf-8", b"x", 0, 1, "bad")
    assert "UnicodeDecodeError" in msg.log_unexpected(bad)
    assert "UnicodeDecodeError" not in human_error(bad)


def test_C_row_level_reasons_are_human_and_located():
    """C · 行级原因要带行号，且不含英文。"""
    line = msg.row_problem(12, msg.ROW_WORD_EMPTY)
    assert line.startswith("第 12 行：")
    assert "「错词」" in line
    for term in msg.FORBIDDEN_TERMS:
        assert term not in line.lower()


def test_C_real_failures_raise_parse_problem_not_tracebacks():
    """C · 真实失败场景抛的是 ParseError（人话），不是裸异常。"""
    with pytest.raises(ParseError) as ei:
        parse_file(SAMPLES / "enc_empty.csv")
    assert "没有读到任何内容" in str(ei.value)

    with pytest.raises(ParseError) as ei2:
        parse_file(SAMPLES / "enc_blank_only.csv")
    assert "没有读到任何内容" in str(ei2.value)

    with pytest.raises(ParseError) as ei3:
        parse_file(SAMPLES / "不存在.csv")
    assert "找不到这个文件" in str(ei3.value)

    with pytest.raises(ParseError) as ei4:
        parse_file(SAMPLES)          # 传目录
    assert "文件夹" in str(ei4.value)


def test_C_empty_parse_text_is_human():
    with pytest.raises(ParseError) as ei:
        parse_text("   \n\n\t  \n")
    assert "没有读到任何内容" in str(ei.value)


# ===========================================================================
# 分隔符判定（粘贴通道的核心）
# ===========================================================================

@pytest.mark.parametrize(
    "text, expect_delim, expect_cols, expect_conf",
    [
        ("错词\t正确写法\t分类\n甲\t乙\t丙\n丁\t戊\t己", "\t", 3, "tab-vote"),
        ("错词,正确写法\n甲,乙\n丙,丁", ",", 2, "uniform"),
        ("错词;正确写法\n甲;乙\n丙;丁", ";", 2, "uniform"),
        ("错词|正确写法\n甲|乙\n丙|丁", "|", 2, "uniform"),
        ("错词，正确写法\n甲，乙\n丙，丁", "，", 2, "uniform"),
        ("错词、正确写法\n甲、乙\n丙、丁", "、", 2, "uniform"),
        ("萧衍\n萧彦\n九牛二虎", None, 1, "single-column"),
    ],
)
def test_delimiter_matrix(text, expect_delim, expect_cols, expect_conf):
    """分隔符判定矩阵：每种来源形态都要判对，且结论附可复算的依据。"""
    guess = guess_delimiter(text)
    assert guess.delimiter == expect_delim
    assert guess.column_count == expect_cols
    assert guess.confidence == expect_conf
    assert guess.evidence, "判定必须留下可展示的依据"


def test_tab_wins_over_commas_in_body_text():
    """制表符优先：Excel 复制来的表，正文里的逗号不能把它带偏。"""
    guess = guess_delimiter("错词\t正确写法\n他说，你好\t他说你好\n甲,乙\t丙，丁")
    assert guess.delimiter == "\t"
    assert guess.column_count == 2


def test_quote_aware_only_for_standard_delimiters():
    """引号语义只对 , ; | 生效——制表符/全角标点下引号是正文。"""
    assert QUOTE_AWARE_DELIMITERS == frozenset({",", ";", "|"})
    # `"他说,你好"` 在逗号表里是一个字段
    sheet = parse_text('错词,正确写法\n"他说,你好",他说你好')
    assert sheet.data_rows[0][1] == ["他说,你好", "他说你好"]
    # 全角逗号表不认引号：引号就是正文的一部分
    sheet2 = parse_text('错词，正确写法\n"他说，停"，他说停')
    assert sheet2.delimiter == "，"
    assert sheet2.data_rows[0][1] == ['"他说', '停"', "他说停"]


def test_short_input_is_flagged_as_fallback():
    """单行内容无法靠列数一致性投票——要标 fallback，让上层提示用户确认。"""
    guess = guess_delimiter("萧衍,萧彦")
    assert guess.delimiter == ","
    assert guess.confidence == "fallback"
    assert "只有一行" in guess.evidence[0]


def test_inconsistent_columns_downgrade_to_fallback():
    """列数不齐时要降级成 fallback，而不是硬判 uniform。"""
    guess = guess_delimiter("甲,乙\n丙,丁,戊\n己,庚\n辛,壬,癸\n子,丑")
    assert guess.delimiter == ","
    assert guess.confidence == "fallback", "3/5 行一致，不该判成 uniform"
    assert "确认列映射" in " ".join(guess.evidence)


def test_delimiter_names_are_human():
    assert delimiter_name("\t") == "制表符"
    assert delimiter_name(",") == "逗号"
    assert delimiter_name("，") == "全角逗号"
    assert delimiter_name("、") == "顿号"
    assert delimiter_name(None) == "无分隔符（单列）"
    for term in msg.FORBIDDEN_TERMS:
        assert term not in delimiter_name(",").lower()


# ===========================================================================
# 表头判定与位置约定
# ===========================================================================

def test_header_detected_when_words_look_like_headers():
    sheet = parse_text("错词,正确写法,分类\n萧衍,萧彦,角色名\n九牛二虎,九牛二虎之力,其他")
    assert sheet.header_skipped is True
    assert sheet.headers == ["错词", "正确写法", "分类"]
    assert sheet.mapping.roles == [ROLE_WORD, ROLE_VALUE, ROLE_TYPE]
    assert "已经跳过" in sheet.messages.text()


def test_header_absent_keeps_first_row_as_data():
    sheet = parse_text("萧衍,萧彦,角色名\n九牛二虎,九牛二虎之力,其他\n丙,丁,其他")
    assert sheet.header_skipped is False
    assert sheet.row_count == 3
    assert sheet.data_rows[0][1] == ["萧衍", "萧彦", "角色名"]
    assert "第一行看起来就是词条" in sheet.messages.text()


def test_single_row_is_never_treated_as_header():
    """只有一行时不能当表头跳过——否则用户粘了一条词条会得到 0 行。"""
    sheet = parse_text("萧衍,萧彦")
    assert sheet.header_skipped is False
    assert sheet.row_count == 1


def test_positional_mapping_without_headers():
    assert parse_text("萧衍\n萧彦\n九牛二虎").mapping.roles == [ROLE_WORD]
    assert parse_text("萧衍,萧彦\n九牛二虎,九牛二虎之力").mapping.roles == [ROLE_WORD, ROLE_VALUE]
    assert parse_text("萧衍,萧彦,角色名\n九牛二虎,九牛二虎之力,其他").mapping.roles == [
        ROLE_WORD, ROLE_VALUE, ROLE_TYPE,
    ]


def test_header_hint_for_extra_columns_goes_to_ignore():
    """备注 / 序号这类列要落到「不使用」，不能硬塞进某个用途。"""
    sheet = parse_text("序号,错词,正确写法,备注\n1,萧衍,萧彦,角色表\n2,九牛二虎,九牛二虎之力,成语")
    assert sheet.mapping.roles == [ROLE_IGNORE, ROLE_WORD, ROLE_VALUE, ROLE_IGNORE]


# ===========================================================================
# 编码识别矩阵（文件通道）
# ===========================================================================

@pytest.mark.parametrize(
    "name, expect_label, expect_rows, expect_cols",
    [
        ("enc_utf8_lf.csv", "UTF-8", 4, 3),
        ("enc_utf8_bom.csv", "UTF-8", 4, 3),
        ("enc_utf8_crlf.csv", "UTF-8", 4, 3),
        ("enc_gbk_crlf.csv", "GBK", 4, 3),
        ("enc_gbk_lf.csv", "GBK", 4, 3),
        ("enc_gb18030_ext.csv", "GB18030", 5, 3),
        ("enc_big5.csv", "Big5", 6, 3),
    ],
)
def test_encoding_matrix(name, expect_label, expect_rows, expect_cols):
    """编码识别矩阵：UTF-8（含 BOM、CRLF）/ GBK（LF 与 CRLF）/ GB18030 / Big5 逐档验。

    特别注意 GBK 系：GB18030 是 GBK 的超集，只靠"能不能解码"会把
    GBK 误判成 GB18030、也会把 Big5 误判成国标——这里每档都必须判对。
    """
    sheet = parse_file(SAMPLES / name)
    assert sheet.encoding_label == expect_label
    assert sheet.row_count == expect_rows
    assert sheet.column_count == expect_cols
    words = [r.word for r in sheet.mapped().good()]
    assert words and words[0], "解出来的第一条词条不能是空的"
    assert "\ufffd" not in "".join(words), "不该出现读不出的替换符"


def test_bom_is_stripped_not_left_as_invisible_char():
    """BOM 必须被吃掉——留在首格里会让第一条词条永远匹配不上。"""
    sheet = parse_file(SAMPLES / "enc_utf8_bom.csv")
    first = sheet.data_rows[0][1][0]
    assert not first.startswith("\ufeff")
    assert first == "他说【英文单引号】你好【英文单引号】就走了"


def test_crlf_and_lf_give_identical_results():
    """行尾是 CRLF 还是 LF，解析结果必须一样（不让用户为行尾付代价）。"""
    a = parse_file(SAMPLES / "enc_utf8_lf.csv")
    b = parse_file(SAMPLES / "enc_utf8_crlf.csv")
    assert a.row_count == b.row_count
    assert [f for _ln, f in a.data_rows] == [f for _ln, f in b.data_rows]


def test_gbk_crlf_and_lf_also_identical():
    a = parse_file(SAMPLES / "enc_gbk_lf.csv")
    b = parse_file(SAMPLES / "enc_gbk_crlf.csv")
    assert a.encoding_label == b.encoding_label == "GBK"
    assert [f for _ln, f in a.data_rows] == [f for _ln, f in b.data_rows]


def test_blank_lines_are_skipped_but_line_numbers_preserved():
    """空行要跳过，但**行号不能跟着缩**——否则定位会指错行。"""
    sheet = parse_text("错词,正确写法\n甲,乙\n\n\n丙,丁\n \n戊,己")
    assert [ln for ln, _f in sheet.data_rows] == [2, 5, 7]
    assert [f[0] for _ln, f in sheet.data_rows] == ["甲", "丙", "戊"]


def test_gb18030_extension_char_survives_round_trip():
    """GB18030 扩展区生僻字（4 字节）必须能读出来，不能被替换成问号。

    这一行在样本里只有一格（`生僻字：𧟇`），它是一张 3 列表里的**残行**——
    按映射规则它会被判成「正确写法这一格是空的」而不进可导入清单，
    所以断言放在**单元格层**：解码后的文本必须逐字保留那个扩展区字符。
    """
    sheet = parse_file(SAMPLES / "enc_gb18030_ext.csv")
    cells = [c for _ln, f in sheet.data_rows for c in f]
    text = "".join(cells)
    assert "\ufffd" not in text, "出现了替换字符，说明扩展区字符被解坏了"
    target = next(c for c in cells if c.startswith("生僻字"))
    assert target == "生僻字：\ue7c7", f"扩展区字符被改写：{target!r}"


def test_big5_is_not_mistaken_for_gbk():
    """Big5 繁体必须判成 Big5，不能被 GB18030 把字节"成功解码"成乱码。"""
    sheet = parse_file(SAMPLES / "enc_big5.csv")
    assert sheet.encoding_label == "Big5"
    values = [r.value for r in sheet.mapped().good()]
    assert "他說「你好」就走了" in values


# ===========================================================================
# 两条通道的形态差异
# ===========================================================================

def test_paste_excel_tabs_sample():
    """Excel 复制形态（制表符 + 表头）走粘贴通道必须正确。"""
    sheet = parse_text((SAMPLES / "paste_excel_tabs.txt").read_text(encoding="utf-8"))
    assert sheet.delimiter == "\t"
    assert sheet.column_count == 3
    assert sheet.header_skipped is True
    assert sheet.mapping.roles == [ROLE_WORD, ROLE_VALUE, ROLE_TYPE]
    assert [(r.word, r.value, r.typ) for r in sheet.mapped().good()] == [
        ("萧衍", "萧彦", "角色名"),
        ("九牛二虎", "九牛二虎之力", "其他"),
        ("他说'走'", "他说「走」", "错词校正"),      # 粘贴内容里的占位符也被还原
    ]


def test_single_column_sample_is_readable_with_advice():
    """一列内容要能读，并且明确告诉用户「正确写法要自己补」。"""
    sheet = parse_file(SAMPLES / "single_column.txt")
    assert sheet.delimiter is None
    assert sheet.column_count == 1
    assert [f[0] for _ln, f in sheet.data_rows] == ["萧衍", "萧彦", "九牛二虎"]
    assert "只有一列" in sheet.messages.text()
    assert not sheet.mapping.is_ready()
    assert "「正确写法」" in sheet.mapping.problems()[0]


def test_both_channels_share_one_pipeline():
    """同一段内容走两条通道，结构结果必须一致（不给用户两套行为）。"""
    import tempfile

    text = "错词,正确写法,分类\n萧衍,萧彦,角色名\n九牛二虎,九牛二虎之力,其他"
    pasted = parse_text(text)
    fd, name = tempfile.mkstemp(suffix=".csv")
    Path(name).write_text(text, encoding="utf-8")
    from_file = parse_file(Path(name))

    assert pasted.delimiter == from_file.delimiter
    assert pasted.column_count == from_file.column_count
    assert pasted.mapping.roles == from_file.mapping.roles
    assert [f for _ln, f in pasted.data_rows] == [f for _ln, f in from_file.data_rows]


# ===========================================================================
# 行级校验与默认值（对齐 D5 写入层的字段口径）
# ===========================================================================

def test_blank_cells_are_reported_per_row_with_line_numbers():
    """缺格要逐行报、带行号、人话；不能整批失败。"""
    sheet = parse_text("错词,正确写法\n萧衍,\n,萧彦\n九牛二虎,九牛二虎之力")
    result = sheet.mapped()
    assert [(r.line_no, r.problem) for r in result.bad()] == [
        (2, msg.ROW_VALUE_EMPTY),   # 第 2 行「萧衍,」：有错词、缺正确写法
        (3, msg.ROW_WORD_EMPTY),    # 第 3 行「,萧彦」：缺错词
    ]
    assert len(result.good()) == 1


def test_default_type_matches_write_layer():
    """缺「分类」时用与写入层一致的默认值，别让 D5 再猜一次。"""
    assert DEFAULT_TYPE == "错词校正"
    sheet = parse_text("萧衍,萧彦\n九牛二虎,九牛二虎之力")
    assert all(r.typ == "错词校正" for r in sheet.mapped().good())


def test_explicit_type_is_kept():
    sheet = parse_text("萧衍,萧彦,角色名\n九牛二虎,九牛二虎之力,其他")
    assert [r.typ for r in sheet.mapped().good()] == ["角色名", "其他"]


def test_trailing_newline_in_value_is_preserved():
    """值的尾部换行是内容，不能被 trim 掉（出厂词库真实有此形态）。"""
    sheet = parse_text("匆念【换行符】,勿念【换行符】\n匆怪【换行符】,勿怪【换行符】")
    assert [r.value for r in sheet.mapped().good()] == ["勿念\n", "勿怪\n"]


def test_surrounding_spaces_trimmed_but_content_kept():
    sheet = parse_text("  萧衍  ,  萧彦  \n九牛二虎 , 九牛二虎之力")
    assert [(r.word, r.value) for r in sheet.mapped().good()] == [
        ("萧衍", "萧彦"), ("九牛二虎", "九牛二虎之力"),
    ]


def test_is_ready_and_problems_track_mapping_changes():
    sheet = parse_text("错词,正确写法\n萧衍,萧彦")
    assert sheet.is_ready()

    sheet.set_mapping(ColumnMapping(roles=[ROLE_WORD, ROLE_IGNORE]))
    assert not sheet.is_ready()
    assert any("「正确写法」" in p for p in sheet.problems())


def test_mapping_changes_do_not_touch_raw_text():
    """改映射只动数据，不动原文——`raw_text` 改映射前后必须逐字不变。"""
    sheet = parse_text("错词,正确写法,分类\n萧衍,萧彦,角色名")
    before = sheet.raw_text
    sheet.set_mapping(sheet.mapping.swap(1, 2))
    assert sheet.raw_text == before


# ===========================================================================
# 样本集自身的完整性（防止样本被误删/误改后测试变成空转）
# ===========================================================================

def test_sample_set_is_complete():
    """样本集必须齐活：真实原版导出 + 编码矩阵 + 两条通道形态。"""
    required = [
        "orig_tempMap_all_markers.csv",     # 原版真实导出，四种占位符齐全
        "orig_normalmap_markers.csv",       # 原版真实导出，出厂词条含占位符
        "orig_oldstyle_map.csv",            # 原版真实导出，1103 行
        "enc_utf8_lf.csv", "enc_utf8_bom.csv", "enc_utf8_crlf.csv",
        "enc_gbk_lf.csv", "enc_gbk_crlf.csv", "enc_gb18030_ext.csv",
        "enc_big5.csv", "enc_empty.csv", "enc_blank_only.csv",
        "paste_excel_tabs.txt", "single_column.txt", "handwritten_commas.txt",
    ]
    missing = [n for n in required if not (SAMPLES / n).exists()]
    assert not missing, f"样本集缺文件：{missing}"

    raw = (SAMPLES / "orig_tempMap_all_markers.csv").read_text(encoding="utf-8")
    for marker in ORIG_MARKERS:
        assert marker in raw, f"真实样本里缺 {marker}，验收判据就验不到了"


def test_oldstyle_sample_scales_up():
    """1103 行真实旧式词库要能整体解析（不是只跑得动玩具样本）。"""
    sheet = parse_file(SAMPLES / "orig_oldstyle_map.csv")
    assert sheet.row_count == 1102            # 首行是原版说明文字，已跳过
    assert sheet.column_count == 2
    result = sheet.mapped()
    assert not result.bad()
    assert len(result.good()) == 1102
