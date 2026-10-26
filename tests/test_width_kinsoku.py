"""width.py（宽度库）与 kinsoku.py（标点禁排/挤压）的单元测试。

这两个模块是 Python 侧的标注扩展：FixText PHP 源码中不存在对应实现，
不被 LayoutEngine.format() 默认调用；此处验证其自身行为正确。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fixtext_layout.kinsoku import (  # noqa: E402
    can_break_after,
    can_break_before,
    effective_width,
    wrap_text,
)
from fixtext_layout.width import (  # noqa: E402
    WidthConfig,
    char_width,
    text_width,
)


class WidthTest(unittest.TestCase):

    def test_cjk_fullwidth(self):
        self.assertEqual(char_width('中'), 2)
        self.assertEqual(char_width('Ａ'), 2)
        self.assertEqual(char_width('！'), 2)
        self.assertEqual(char_width('　'), 2)

    def test_ascii_narrow(self):
        self.assertEqual(char_width('a'), 1)
        self.assertEqual(char_width('!'), 1)
        self.assertEqual(char_width(' '), 1)

    def test_combining_mark_zero(self):
        self.assertEqual(char_width('\u0301'), 0)

    def test_mixed_text(self):
        self.assertEqual(text_width('中文abc'), 7)
        self.assertEqual(text_width(''), 0)

    def test_ambiguous_default_narrow(self):
        # U+201D（”）East Asian Width = A，默认按窄处理
        self.assertEqual(char_width('”'), 1)

    def test_ambiguous_config_wide(self):
        cfg = WidthConfig(ambiguous_wide=True)
        self.assertEqual(char_width('”', cfg), 2)
        self.assertEqual(cfg.width('””'), 4)

    def test_config_combining_zero(self):
        cfg = WidthConfig(combining_zero=False)
        self.assertEqual(char_width('\u0301', cfg), 1)

    def test_aliases(self):
        from fixtext_layout.width import display_width, visual_length
        self.assertEqual(visual_length('中文'), 4)
        self.assertEqual(display_width('中文'), 4)


class KinsokuPredicateTest(unittest.TestCase):

    def test_line_start_forbidden(self):
        for ch in '，。、；：？！）」』':
            self.assertFalse(can_break_before(ch), repr(ch))

    def test_line_start_allowed(self):
        for ch in 'abc中（「':
            self.assertTrue(can_break_before(ch), repr(ch))

    def test_line_end_forbidden(self):
        for ch in '（【「『“':
            self.assertFalse(can_break_after(ch), repr(ch))

    def test_line_end_allowed(self):
        for ch in 'abc中。':
            self.assertTrue(can_break_after(ch), repr(ch))


class KinsokuWidthTest(unittest.TestCase):

    def test_no_compression(self):
        self.assertEqual(effective_width('你好。，', compression=False), 8)

    def test_compression_trailing_run(self):
        # 行尾连续全角可挤压标点：最左 1 个保持全宽 2，其余折半
        self.assertEqual(effective_width('你好。，', compression=True), 7)
        self.assertEqual(effective_width('你好。，。', compression=True), 8)

    def test_compression_unaffected_when_no_target(self):
        self.assertEqual(effective_width('你好abc', compression=True), 7)


class WrapTextTest(unittest.TestCase):

    def test_basic_wrap(self):
        self.assertEqual(wrap_text('一二三四五六七八九十。', 10),
                         '一二三四五\n六七八九\n十。')

    def test_punctuation_not_at_line_start(self):
        wrapped = wrap_text('一二三四五六七八九十，十百千万', 10)
        for line in wrapped.split('\n'):
            self.assertTrue(line, '不应产生空行')
            self.assertTrue(can_break_before(line[0]),
                           '行首出现禁排标点: %r' % line[0])
            self.assertTrue(can_break_after(line[-1]),
                            '行尾出现禁排标点: %r' % line[-1])

    def test_keep_paragraphs(self):
        self.assertEqual(wrap_text('甲\n\n乙', 10, keep_paragraphs=True),
                         '甲\n\n乙')

    def test_narrow_width_single_char_lines(self):
        # 宽度 2 恰好放 1 个全角字
        self.assertEqual(wrap_text('一二三', 2), '一\n二\n三')

    def test_width_not_exceeded(self):
        wrapped = wrap_text('一二三四五六七八九，十一二三四五六七八九', 10)
        for line in wrapped.split('\n'):
            self.assertLessEqual(effective_width(line, compression=True), 10,
                                 '行宽超限: %r' % line)


if __name__ == '__main__':
    unittest.main()
