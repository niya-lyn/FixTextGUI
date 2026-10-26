"""基于 PHP 真实输出的黄金用例回归测试（验收标准 2 的主体）。

golden.json 中 41 条用例的 expected 均由 FixText PHP 源码
（tools/php_runner.php 批量执行）实际运行产生，测试不依赖 PHP 环境。
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fixtext_layout.engine import LayoutEngine, format_text  # noqa: E402
from fixtext_layout.options import LayoutOptions  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

#: PHP Option 字段名（camelCase）→ LayoutOptions 字段名（snake_case）
_FIELD_MAP = {
    'changeTextFormat': 'change_text_format',
    'addIndentation': 'add_indentation',
    'addHtmlTag': 'add_html_tag',
    'normalizePunctuations': 'normalize_punctuations',
    'quotationType': 'quotation_type',
    'consecutiveQuotationsType': 'consecutive_quotations_type',
    'rmSpacesBetweenChnChars': 'rm_spaces_between_chn_chars',
    'paranoidTextSpacing': 'paranoid_text_spacing',
    'formatHeadings': 'format_headings',
}


def _to_options(php_options: dict) -> LayoutOptions:
    kwargs = {}
    for key, value in php_options.items():
        if key not in _FIELD_MAP:
            raise KeyError('未知 PHP 选项字段: %r' % key)
        kwargs[_FIELD_MAP[key]] = value
    return LayoutOptions(**kwargs)


def _load_golden():
    with open(os.path.join(HERE, 'golden.json'), 'r', encoding='utf-8') as fh:
        return json.load(fh)


GOLDEN = _load_golden()


class GoldenCase(unittest.TestCase):
    """逐条核对 PHP 黄金输出。"""

    def _run(self, case):
        engine = LayoutEngine(_to_options(case['options']))
        self.assertEqual(engine.format(case['input']), case['expected'],
                         '用例 %s 不一致' % case['name'])

    def test_golden_case_count(self):
        """黄金用例规模守卫：低于 40 说明 golden.json 损坏。"""
        self.assertGreaterEqual(len(GOLDEN), 40)

    def test_format_text_helper(self):
        """format_text 便捷入口与 LayoutEngine 等价。"""
        case = GOLDEN[0]
        opts = _to_options(case['options'])
        self.assertEqual(format_text(case['input'], opts), case['expected'])


def _make(case_name):
    def test(self):
        for case in GOLDEN:
            if case['name'] == case_name:
                self._run(case)
                return
        raise AssertionError('golden.json 中找不到用例: %s' % case_name)
    return test


# 为每条黄金用例生成独立测试方法，失败时可直接定位用例名
for _case in GOLDEN:
    setattr(GoldenCase, 'test_' + _case['name'], _make(_case['name']))


if __name__ == '__main__':
    unittest.main()
