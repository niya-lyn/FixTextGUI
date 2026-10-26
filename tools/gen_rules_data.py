#!/usr/bin/env python3
"""把 tools/export_rules.php 导出的 rules.json 转成 Python 规则数据模块。

用法: python3 tools/gen_rules_data.py [rules.json] [输出文件]

运行前需要先在 FixText 源码上执行:
    php tools/export_rules.php rules.json
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_PARENT = os.path.dirname(HERE)

HEADER = '''"""排版规则数据（自动生成，请勿手工修改）。

本文件由 ``tools/gen_rules_data.py`` 从 ``tools/export_rules.php`` 导出的
``rules.json`` 生成，规则内容与 FixText 的 PHP 源码完全一致，是 PHP 与
Python 两套实现共用的唯一事实源。

重新生成:
    php tools/export_rules.php rules.json
    python3 tools/gen_rules_data.py rules.json fixtext_layout/rules_data.py
"""

from __future__ import annotations

from typing import Dict, List, Tuple

'''


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(PKG_PARENT, 'rules.json')
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(PKG_PARENT, 'fixtext_layout', 'rules_data.py')
    with open(src, encoding='utf-8') as fh:
        data = json.load(fh)

    pmap: Dict[str, str] = data['punctuation_map']
    patterns = data['punctuation_patterns']

    lines: List[str] = [HEADER]
    lines.append('# --- 全角/半角与标点形态映射（PHP strtr 实际生效的 113 条） ---\n')
    lines.append('PUNCTUATION_MAP: Dict[str, str] = {\n')
    for k, v in pmap.items():
        lines.append('    %r: %r,\n' % (k, v))
    lines.append('}\n\n')

    lines.append('# --- 标点规范正则规则（PHP punctuationPatterns，共 %d 条） ---\n' % len(patterns))
    lines.append('# 每项为 (search, replace)；replace 为 PHP 的 $n 风格回引用写法。\n')
    lines.append('PUNCTUATION_PATTERNS: List[Tuple[str, str]] = [\n')
    for p in patterns:
        if p.get('replace') is None:
            raise SystemExit('规则中存在回调式 replace，需要单独处理: %r' % (p,))
        lines.append('    (%r, %r),\n' % (p['search'], p['replace']))
    lines.append(']\n\n')

    lines.append('# --- FileProcessor 常量 ---\n')
    lines.append('SPACE_PATTERN: str = %r\n' % data['space_pattern'])
    lines.append('HTML_CHAPTER_MARK: str = %r\n' % data['html_chapter_mark'])

    with open(dst, 'w', encoding='utf-8') as fh:
        fh.write(''.join(lines))
    print('generated %s (%d map entries, %d patterns)' % (dst, len(pmap), len(patterns)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
