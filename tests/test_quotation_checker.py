"""T1.4 引号检查核心逻辑单元测试。

覆盖 PHP 原版 QuotationChecker 的全部检测规则族：
缺左/右引号、交叉错乱、空引号、同向嵌套（双套双/单套单）、
跨行闭合（文件末尾/段首位置不合法/隔行错位/下方找不到右引号/多层嵌套）、
英文弯撇号过滤、跨行段首延续（不重复报错）等。
文案与位置断言均取自 PHP 原版（QuotationChecker.php 经 php_harness.php 驱动）的实际输出，
非人工推算。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fixtext_quotation.checker import QuotationChecker, QuotationError, _php_file_lines


def check(text: str):
    """跑检查并返回 [(line, char, msg), ...]。"""
    return [(e.line, e.char, e.msg) for e in QuotationChecker().check_text(text)]


# ———————————————————— 行切分（file() 语义）————————————————————

class TestPhpFileLines:
    def test_trailing_newline_no_empty_tail(self):
        assert _php_file_lines("a\nb\n") == ["a\n", "b\n"]

    def test_no_trailing_newline(self):
        assert _php_file_lines("a\nb") == ["a\n", "b"]

    def test_empty(self):
        assert _php_file_lines("") == []

    def test_crlf_kept(self):
        assert _php_file_lines("a\r\nb\r\n") == ["a\r\n", "b\r\n"]


# ———————————————————— 单行配对 ————————————————————

class TestBasicPairing:
    def test_normal_double_ok(self):
        assert check("“你好”\n") == []

    def test_normal_single_ok(self):
        assert check("‘你好’\n") == []

    def test_nested_ok(self):
        # 双引号内套单引号是规范写法
        assert check("他说“快走‘快点’快走”。\n") == []

    def test_missing_left_double(self):
        assert check("他说”完蛋了。\n") == [
            (1, 2, "<右双引号前> 缺左双引号")
        ]

    def test_missing_left_single(self):
        assert check("他’t\n") == [
            (1, 1, "<右单引号前> 缺左单引号")
        ]

    def test_empty_double_quote(self):
        assert check("空引号“”测试\n") == [
            (1, 4, "<右双引号前> 出现空引号“”现象")
        ]

    def test_empty_single_quote(self):
        assert check("空引号‘’测试\n") == [
            (1, 4, "<右单引号前> 出现空引号‘’现象")
        ]

    def test_crossed_quotes_double_in_single(self):
        # 单引号内出现右双引号：交叉错乱
        assert check("‘abc”\n") == [
            (1, 4, "<右双引号前> 引号嵌套交叉错乱，内部单引号‘未闭合")
        ]

    def test_crossed_quotes_single_in_double(self):
        # 双引号内出现右单引号（非撇号）：交叉错乱
        assert check("“abc’\n") == [
            (1, 4, "<右单引号前> 引号嵌套交叉错乱，内部双引号“未闭合")
        ]

    def test_nested_doubles_in_double(self):
        # 双引号内直接嵌套独立双引号
        assert check("“他说：“不行””\n") == [
            (1, 4, "<左双引号前> 双引号内直接嵌套了独立双引号（应规范使用单引号）")
        ]

    def test_adjacent_doubles_not_nested_err(self):
        # 紧挨着的两个左双引号（““）不触发嵌套报错（原版 prevChar !== '“' 判定）；
        # 单行文件中第一层未闭合 → 文件末尾缺右引号
        assert check("““a”\n") == [
            (1, 4, "<换行时> 缺右双引号（已到文件末尾）")
        ]

    def test_nested_singles_in_single(self):
        # 单引号内直接嵌套独立单引号
        assert check("‘他说：‘不行’’\n") == [
            (1, 4, "<左单引号前> 单引号内直接嵌套了独立单引号（应规范使用双引号）")
        ]

    def test_adjacent_singles_not_nested_err(self):
        assert check("‘‘a’\n") == [
            (1, 4, "<换行时> 缺右单引号（已到文件末尾）")
        ]


# ———————————————————— 撇号过滤 ————————————————————

class TestApostropheFilter:
    def test_apostrophe_between_letters(self):
        assert check("80’s Music 一曲\n") == []

    def test_apostrophe_between_digit_and_letter(self):
        assert check("Guns N’ Roses 乐队\n") == []

    def test_apostrophe_with_punct_neighbors_still_checked(self):
        # 两侧是标点时不是撇号，按右单引号处理 → 缺左单引号
        assert check("他说，’，就走了\n") == [
            (1, 3, "<右单引号前> 缺左单引号")
        ]

    def test_apostrophe_at_line_start(self):
        # 行首的 ’ 前字符为空，不过滤
        assert check("’开头\n") == [
            (1, 0, "<右单引号前> 缺左单引号")
        ]


# ———————————————————— 行尾 / 跨行 ————————————————————

class TestEolAndMultiLine:
    def test_unclosed_then_no_more_lines(self):
        # 第 2 行未闭合，下方仅剩无引号行 → 找不到右引号
        text = "“好”。\n“未闭合\n正文最后一行\n"
        assert check(text) == [
            (2, 4, "<换行时> 缺右双引号，且下方多行内都无法查找到右双引号")
        ]

    def test_unclosed_at_file_end(self):
        # 未闭合行是最后一行（其 \n 即文件末行行尾）
        text = "“好”。\n“一直没闭合\n"
        assert check(text) == [
            (2, 6, "<换行时> 缺右双引号（已到文件末尾）")
        ]

    def test_multiline_ok(self):
        # 规范跨行：段首左引号前置字符合法，下方行有右引号
        text = "“第一段话。\n“第二段话。\n“最后一段话。”\n"
        assert check(text) == []

    def test_multiline_start_pos_invalid(self):
        # 段首左引号前一个字符不合法（如字母）
        text = "x“第一段话。\n“第二段话。”\n"
        assert check(text) == [
            (1, 7, "<换行时> 缺右双引号，段首左双引号的位置有误")
        ]

    def test_multi_level_no_crossline(self):
        # 多层嵌套未闭合时，嵌套报错先触发并跳行；后续右引号变缺左引号
        text = "“外层“内层\n正文\n”\n"
        assert check(text) == [
            (1, 3, "<左双引号前> 双引号内直接嵌套了独立双引号（应规范使用单引号）"),
            (3, 0, "<右双引号前> 缺左双引号"),
        ]

    def test_multi_level_single_no_crossline(self):
        text = "‘外层‘内层\n正文\n’\n"
        assert check(text) == [
            (1, 3, "<左单引号前> 单引号内直接嵌套了独立单引号（应规范使用双引号）"),
            (3, 0, "<右单引号前> 缺左单引号"),
        ]

    def test_no_right_quote_below(self):
        # 下方 100 行内都没有右引号
        text = "“开头\n" + "正文。\n" * 150
        got = check(text)
        assert got == [(1, 3, "<换行时> 缺右双引号，且下方多行内都无法查找到右双引号")]

    def test_blank_lines_skipped_in_search(self):
        # 空行不影响向下探测
        text = "“开头\n\n\n“结尾有”。\n"
        assert check(text) == []

    def test_isolated_left_quote_two_lines_below(self):
        # 下一行无左引号、隔一行却出现左引号 → 不应有的左引号
        text = "“开头\n正文。\n“有引号”。\n"
        assert check(text) == [
            (1, 3, "<换行时> 缺右双引号，两行后却出现不应有的左双引号")
        ]

    def test_left_quote_misaligned_next_line(self):
        # 下一行左引号不在行首（前置字符不在允许集）→ 隔行出现左引号错位
        text = "“开头\nx“错位”。\n"
        assert check(text) == [
            (1, 3, "<换行时> 缺右双引号，隔行出现左双引号错位")
        ]

    def test_multiline_continuation_not_double_counted(self):
        # 跨行段首延续标记不重复压栈、不报嵌套错误（单引号同理）
        text = "“我是第一段话。\n“我是第二段话。\n“我是最后一段话。”\n"
        assert check(text) == []

    def test_unclosed_single_multiline(self):
        text = "‘第一段话。\n‘第二段话。’\n"
        assert check(text) == []


# ———————————————————— 每行至多一处报错 + 跳行续扫 ————————————————————

class TestSkipLineSemantics:
    def test_multiple_bad_lines_all_reported(self):
        text = "缺左”。\n又一处”。\n"
        got = check(text)
        assert got == [
            (1, 2, "<右双引号前> 缺左双引号"),
            (2, 3, "<右双引号前> 缺左双引号"),
        ]

    def test_line_without_quotes_skipped(self):
        # 无引号字符的行完全不参与检查（连行尾状态都不更新）
        text = "“未闭合\n无引号行\n“补上”。”\n"
        assert check(text) == [
            (1, 4, "<换行时> 缺右双引号，两行后却出现不应有的左双引号"),
            (3, 5, "<右双引号前> 缺左双引号"),
        ]


# ———————————————————— 数据结构与便捷入口 ————————————————————

class TestApi:
    def test_check_file(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("他说”。\n", encoding="utf-8")
        errs = QuotationChecker().check_file(p)
        assert len(errs) == 1 and isinstance(errs[0], QuotationError)
        assert errs[0].line == 1 and errs[0].msg == "<右双引号前> 缺左双引号"

    def test_to_dict(self):
        e = QuotationError(line=1, char=2, msg="x")
        assert e.to_dict() == {"line": 1, "char": 2, "msg": "x"}

    def test_check_text_function(self):
        from fixtext_quotation import check_text
        assert check_text("“好”\n") == []
