"""PHP 语义兼容层测试。

断言来源：``fixtures/strip_tags_php.json``（由真实 PHP 8.5.8 生成），
以及同批 probe 中的 ``trimUnicodeChars`` / ``changeEncodingAndNewLineType`` /
``getFilename`` / ``getWordsPrintStr`` 权威结果。
"""

from __future__ import annotations

import pytest

from fixtext_bookmap.phpcompat import (
    PHP_DEFAULT_TRIM_CHARS,
    change_encoding_and_new_line_type,
    mb_strlen,
    php_ltrim,
    php_preg_replace_multiline_start,
    php_rtrim,
    php_strip_tags,
    php_trim,
    php_truthy,
    trim_unicode_chars,
)


class TestPhpStripTags:
    """PHP strip_tags 状态机：以真实 PHP 输出为唯一标准。"""

    def test_all_php_vectors(self, strip_tags_vectors):
        """每一条 PHP 权威向量都必须逐字匹配。"""
        assert len(strip_tags_vectors) >= 40, "权威向量数量不足，夹具可能损坏"

        mismatches = []
        for vec in strip_tags_vectors:
            got = php_strip_tags(vec["input"])
            if got != vec["expected"]:
                mismatches.append(
                    f"input={vec['input']!r} php={vec['expected']!r} py={got!r}"
                )
        assert not mismatches, "与 PHP 不一致:\n" + "\n".join(mismatches)

    def test_plain_text_passthrough(self):
        assert php_strip_tags("普通文本内容") == "普通文本内容"

    def test_nested_tags_removed(self):
        assert php_strip_tags("<a<b<c>>>d") == "d"

    def test_trailing_lone_angle_bracket_dropped(self):
        # 末尾孤立 '<' 被丢弃（PHP 实测行为）
        assert php_strip_tags("尾<") == "尾"

    def test_angle_bracket_before_space_is_literal(self):
        # '<' 后跟空白 -> 字面输出，而非标签起始
        assert php_strip_tags("a < b") == "a < b"


class TestPhpTrimFamily:
    """trim 系列按「字符集合」而非子串剥离。"""

    def test_default_charset(self):
        assert PHP_DEFAULT_TRIM_CHARS == " \t\n\r\x00\x0b"

    @pytest.mark.parametrize(
        "raw,left,right,trimmed",
        [
            ("  abc  ", "abc  ", "  abc", "abc"),
            ("\t\nabc\r\n", "abc\r\n", "\t\nabc", "abc"),
            ("\x00abc\x0b", "abc\x0b", "\x00abc", "abc"),
        ],
    )
    def test_ltrim_rtrim_directions(self, raw, left, right, trimmed):
        # 经 PHP 8.5 实测：ltrim 只剥左侧、rtrim 只剥右侧、trim 两侧都剥
        assert php_ltrim(raw) == left
        assert php_rtrim(raw) == right
        assert php_trim(raw) == trimmed

    def test_charset_semantics_not_substring(self):
        # "-" 是字符集合，"---abc" 会被全部剥掉
        assert php_ltrim("---abc", "-") == "abc"

    def test_fullwidth_space_not_trimmed_by_php_trim(self):
        # PHP 原生 trim 默认不剥全角空格（因此上游另有 trimUnicodeChars）
        assert php_trim("　内容　") == "　内容　"

    def test_trim_unicode_removes_fullwidth_space(self):
        assert trim_unicode_chars("　内容　", " 　") == "内容"

    def test_trim_unicode_directions(self):
        assert trim_unicode_chars("  abc  ", " ", "left") == "abc  "
        assert trim_unicode_chars("  abc  ", " ", "right") == "  abc"
        assert trim_unicode_chars("  abc  ", " ", "both") == "abc"

    def test_trim_unicode_invalid_direction_returns_input(self):
        assert trim_unicode_chars("  abc  ", " ", "bogus") == "  abc  "


class TestPhpTruthy:
    """PHP 的假值集合与 Python 不同，尤其是字符串 "0"。"""

    @pytest.mark.parametrize("value", ["", "0", None, False, 0, 0.0, [], {}, ()])
    def test_falsy(self, value):
        assert php_truthy(value) is False

    @pytest.mark.parametrize("value", ["0.0", " ", "a", 1, -1, [0], {"k": 0}])
    def test_truthy(self, value):
        assert php_truthy(value) is True

    def test_string_zero_is_falsy_but_zero_string_other_is_truthy(self):
        # 这是上游 genDiffWordsMap 丢弃 "0" 词条的原因
        assert php_truthy("0") is False
        assert php_truthy("00") is True


class TestPhpPregReplaceMultilineStart:
    """``/^/m`` 的边界行为（经 PHP 8.5 实测）。"""

    def test_prefix_each_line(self):
        assert php_preg_replace_multiline_start("行一\n行二") == "    行一\n    行二"

    def test_empty_string_gets_prefix(self):
        # PHP 实测：空串也匹配串首
        assert php_preg_replace_multiline_start("") == "    "

    def test_no_prefix_after_trailing_newline(self):
        # PHP 实测：末尾换行之后不插入
        assert php_preg_replace_multiline_start("行一\n") == "    行一\n"

    def test_blank_lines_between_content(self):
        assert php_preg_replace_multiline_start("a\n\nb") == "    a\n    \n    b"

    def test_two_trailing_newlines(self):
        assert php_preg_replace_multiline_start("a\n\n") == "    a\n    \n"

    def test_custom_replacement(self):
        assert php_preg_replace_multiline_start("x\ny", "-") == "-x\n-y"


class TestChangeEncodingAndNewLineType:
    """换行统一与不可见字符清理。"""

    def test_crlf_normalized(self):
        assert change_encoding_and_new_line_type("行一\r\n行二") == "行一\n行二"

    def test_cr_normalized(self):
        assert change_encoding_and_new_line_type("行一\r行二") == "行一\n行二"

    def test_bom_removed(self):
        assert change_encoding_and_new_line_type("\ufeff内容") == "内容"

    def test_zero_width_removed(self):
        assert change_encoding_and_new_line_type("零宽\u200b字符") == "零宽字符"

    def test_plain_content_untouched(self):
        assert change_encoding_and_new_line_type("内容\n") == "内容\n"


class TestMbHelpers:
    def test_mb_strlen_counts_code_points(self):
        # 按码点计数，而非字节
        assert mb_strlen("中文abc") == 5
        assert mb_strlen("") == 0
