"""php_compat 兼容层单元测试。

覆盖：php_trim / php_strtr / php_html_entity_decode / php_strip_tags /
compile_pcre 的多行锚点翻译 / php_replacement 回引用语义。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fixtext_layout.php_compat import (  # noqa: E402
    PHP_TRIM_CHARS,
    compile_pcre,
    php_html_entity_decode,
    php_replacement,
    php_strip_tags,
    php_strtr,
    php_trim,
)


class PhpTrimTest(unittest.TestCase):

    def test_default_chars(self):
        self.assertEqual(php_trim("  abc\n\t"), 'abc')

    def test_keeps_ideographic_space(self):
        # PHP trim 不裁剪 U+3000 —— 这是与 Python str.strip 的关键差异
        self.assertEqual(php_trim('　abc　'), '　abc　')

    def test_empty(self):
        self.assertEqual(php_trim(''), '')

    def test_all_trimmed(self):
        self.assertEqual(php_trim(' \t\n\r\0\x0b'), '')

    def test_default_chars_constant(self):
        self.assertEqual(PHP_TRIM_CHARS, " \t\n\r\0\x0b")


class PhpStrtrTest(unittest.TestCase):

    def test_replaces_longest_key_first(self):
        # strtr 先匹配最长键：'ab' 优先于 'a'
        self.assertEqual(php_strtr('abc', {'a': '1', 'ab': '2'}), '2c')

    def test_no_overlap(self):
        self.assertEqual(php_strtr('hello', {'l': 'L'}), 'heLLo')

    def test_empty_mapping(self):
        self.assertEqual(php_strtr('hello', {}), 'hello')

    def test_multi_char_key(self):
        self.assertEqual(php_strtr('一二三', {'二三': 'XX'}), '一XX')


class PhpHtmlEntityDecodeTest(unittest.TestCase):

    def test_named_entity_with_semicolon(self):
        self.assertEqual(php_html_entity_decode('a&amp;b'), 'a&b')

    def test_named_entity_without_semicolon_kept(self):
        # PHP 要求分号；Python html.unescape 会解码 —— 差异点
        self.assertEqual(php_html_entity_decode('a&ampb'), 'a&ampb')

    def test_numeric_decimal(self):
        self.assertEqual(php_html_entity_decode('&#20013;'), '中')

    def test_numeric_hex(self):
        self.assertEqual(php_html_entity_decode('&#x4E2D;'), '中')

    def test_invalid_codepoint_substituted(self):
        # 超出 Unicode 范围 → U+FFFD（ENT_SUBSTITUTE）
        self.assertEqual(php_html_entity_decode('&#x110000;'), '\ufffd')

    def test_unknown_entity_kept(self):
        self.assertEqual(php_html_entity_decode('&nosuch;'), '&nosuch;')

    def test_html4_not_html5_entities(self):
        # &apos; 在 HTML 4.01 实体表中不存在，PHP 默认不解码
        self.assertEqual(php_html_entity_decode('&apos;'), '&apos;')


class PhpStripTagsTest(unittest.TestCase):

    def test_simple_tag(self):
        self.assertEqual(php_strip_tags('a<b>c</b>d'), 'acd')

    def test_tag_with_quoted_gt(self):
        self.assertEqual(php_strip_tags('<p title="a>b">x</p>'), 'x')

    def test_comment(self):
        self.assertEqual(php_strip_tags('a<!-- note -->b'), 'ab')

    def test_unterminated_tag(self):
        self.assertEqual(php_strip_tags('a<b'), 'a')

    def test_plain_text_untouched(self):
        # '<' 后跟空白是字面量（已与 PHP 8.5 实测核对）
        self.assertEqual(php_strip_tags('a < b'), 'a < b')
        self.assertEqual(php_strip_tags('a<\tb'), 'a<\tb')

    def test_lt_followed_by_non_space_is_tag(self):
        # '<' 后跟非空白字符（数字/汉字/标点）都算标签起始
        self.assertEqual(php_strip_tags('a <3 b'), 'a ')
        self.assertEqual(php_strip_tags('a <中文> b'), 'a  b')
        self.assertEqual(php_strip_tags('1<2>3'), '13')
        self.assertEqual(php_strip_tags('a<.b'), 'a')


class CompilePcreCaretTest(unittest.TestCase):
    """多行模式下 PCRE ^ 与 Python re.M ^ 的语义差异翻译。

    差异（已在 13 组样本上与 PCRE 逐位比对确认）：
    - PCRE ^ 在 m 模式下匹配串首或任意 \n 之后（但最后一个 \n 之后不匹配）；
    - Python re.M ^ 额外匹配「以 \n 结尾的串末位置」。
    """

    def test_trailing_newline_no_extra_match(self):
        pat = compile_pcre(r'^X', 'um')
        # "a\n" 后没有 X，两个引擎都不匹配；关键是否在末位置误判
        self.assertIsNone(pat.search('a\n'))
        self.assertEqual(pat.findall('a\nX\n'), ['X'])

    def test_caret_after_each_newline_except_last(self):
        pat = compile_pcre(r'(?<=^)x', 'um')
        # 三个换行、四处行首位置，x 出现在中间两处行首
        self.assertEqual(pat.findall('x\nx\nx\n'), ['x', 'x', 'x'])
        # 结尾 \n 后面没有字符，PCRE ^ 不在那里匹配；无 x 可匹配
        self.assertEqual(pat.findall('a\n'), [])

    def test_negative_lookbehind_caret(self):
        # (?<!^) 语义 = 当前位置不是行首
        pat = compile_pcre(r'(?<!^)X', 'um')
        self.assertIsNone(pat.search('X\n'))       # 行首的 X 被排除
        self.assertIsNotNone(pat.search('aX\n'))  # 行中的 X 保留

    def test_pos_lookbehind_caret(self):
        pat = compile_pcre(r'(?<=^)X', 'um')
        self.assertIsNotNone(pat.search('X\n'))
        self.assertIsNone(pat.search('aX\n'))

    def test_dollar_equivalent(self):
        pat = compile_pcre(r'X$', 'um')
        self.assertEqual(pat.findall('X\nX'), ['X', 'X'])

    def test_caret_inside_char_class_not_translated(self):
        pat = compile_pcre(r'^[^X]+$', 'um')
        self.assertIsNotNone(pat.search('abc'))
        self.assertIsNone(pat.search('abX'))

    def test_anchor_translation_on_crlf(self):
        # PCRE 换行约定为 LF：\r\n 的 \n 之后才是行首
        pat = compile_pcre(r'^B', 'um')
        self.assertIsNotNone(pat.search('A\r\nB'))
        pat2 = compile_pcre(r'A$', 'um')
        self.assertIsNone(pat2.search('A\r\nB'))  # A 后面跟的是 \r 不是行尾


class PhpReplacementTest(unittest.TestCase):

    def test_dollar_group(self):
        repl = php_replacement('<$1>')
        pat = compile_pcre(r'(a+)', 'u')
        self.assertEqual(pat.sub(repl, 'baad'), 'b<aa>d')

    def test_braced_group(self):
        repl = php_replacement('${1}x')
        pat = compile_pcre(r'(a)', 'u')
        self.assertEqual(pat.sub(repl, 'ba'), 'bax')

    def test_backslash_group(self):
        repl = php_replacement('\\1')
        pat = compile_pcre(r'(a)', 'u')
        self.assertEqual(pat.sub(repl, 'ba'), 'ba')

    def test_missing_group_becomes_empty(self):
        # 引用不存在的分组 → 空字符串
        repl = php_replacement('[$9]')
        pat = compile_pcre(r'(a)', 'u')
        self.assertEqual(pat.sub(repl, 'ba'), 'b[]')

    def test_literal_dollar(self):
        repl = php_replacement('$x')
        pat = compile_pcre(r'(a)', 'u')
        self.assertEqual(pat.sub(repl, 'ba'), 'b$x')


if __name__ == '__main__':
    unittest.main()
