#!/usr/bin/env python3
"""PHP ↔ Python 排版差分测试。

把同一批文本分别送进 FixText 的 PHP 源码和本项目的 Python 实现，逐条比对输出。

用法:
    python3 tools/diff_check.py            # 运行全部用例
    python3 tools/diff_check.py --verbose  # 打印差异上下文
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from fixtext_layout.engine import LayoutEngine  # noqa: E402
from fixtext_layout.options import LayoutOptions  # noqa: E402

PHP_RUNNER = os.path.join(HERE, 'php_runner.php')

# PHP Option 属性名 -> Python LayoutOptions 字段名
OPTION_MAP = {
    'changeTextFormat': 'change_text_format',
    'addIndentation': 'add_indentation',
    'addHtmlTag': 'add_html_tag',
    'normalizePunctuations': 'normalize_punctuations',
    'consecutiveQuotationsType': 'consecutive_quotations_type',
    'quotationType': 'quotation_type',
    'rmSpacesBetweenChnChars': 'rm_spaces_between_chn_chars',
    'paranoidTextSpacing': 'paranoid_text_spacing',
    'formatHeadings': 'format_headings',
    'newLineType': 'new_line_type',
}


def build_cases() -> List[Tuple[str, Dict[str, Any], str]]:
    """构造覆盖各条排版规则的差分用例。"""
    cases: List[Tuple[str, Dict[str, Any], str]] = []

    def add(name: str, options: Dict[str, Any], text: str) -> None:
        cases.append((name, options, text))

    fmt = {'changeTextFormat': True}

    # --- 行首行尾空白 / 空行 ---
    add('行首行尾空格', fmt, '  正文第一行  \n\t第二行\t\n')
    add('全角空格缩进', fmt, '　　全角缩进\n')
    add('空行清理', fmt, 'A\n\n\n\nB\n')
    add('仅空白的行', fmt, 'A\n   \n\t\nB\n')
    add('行尾空白行', fmt, 'A\n     \nB\n')
    add('NBSP与私用区', fmt, 'A BC\n')
    add('不换行空格', fmt, 'A B\n')
    add('软连字符', fmt, 'A­B\n')
    add('首尾空白', fmt, '\n\n  内容  \n\n')
    add('单行无换行', fmt, '只有一行')
    add('空内容', fmt, '')
    add('只有换行', fmt, '\n\n\n')
    add('CRLF输入', fmt, 'A\r\nB\r\n')

    # --- 章节标题识别 ---
    for title in ['第一章 起点', '第1章 起点', '第十二回 某', '楔子', '引子', '前言', '序章', '序1',
                  '尾声', '终章', '番外篇', '后记', '番外', '特别篇', '后日谈', '小剧场', '间章',
                  '内容简介', '第一章：开端', '第一章：', '大结局', '最终卷', '第壹卷', '第廿回',
                  '（一）楔子', '正文总结一二三四五六七八', '感言一二三四五六']:
        add('章节标题:%s' % title, fmt, '正文\n%s\n正文2\n' % title)

    add('章节标题带空格', fmt, '前\n第一章  起点\n后\n')
    add('章节标题句点', fmt, '前\n第一章.\n后\n')
    add('标题出现在行尾', fmt, '前面第一章\n后面\n')

    # --- ◎ 标记 ---
    add('◎标记', fmt, '正文\n◎特殊章节\n正文2\n')
    add('◎标记多个', fmt, '◎一\n◎二\n◎三\n')
    add('◎标记缩进', fmt, '　　◎缩进的标记\n')
    add('◎与章节同时', fmt, '◎第一章 起点\n')

    # --- 标题分级 ---
    add('标题分级', {'formatHeadings': True}, '第一章 起点\n正文\n第二章 继续\n正文2\n')
    add('标题分级三层', {'formatHeadings': True}, '◎一\n◎二\n◎三\n')

    # --- 标点规范 ---
    punct = {'normalizePunctuations': True}
    add('标点-省略号', punct, '他说。。。然后走了...她说：……好吧\n')
    add('标点-英文标点', punct, 'Hello, world! Really?\n中文,中文。中文\n')
    add('标点-全角数字', punct, '０１２３４５６７８９ＡＢＣａｂｃ\n')
    add('标点-全角符号', punct, '＃＠＆￥％＝／＼｜＋－＊＜＞［］｛｝\n')
    add('标点-间隔号', punct, '3.14和3．14还有1..2\n')
    add('标点-冒号', punct, '注释：1\n问题：2\n答案：3\n1:2\n123:4\n1.5:2\n')
    add('标点-括号', punct, '他说(你好)然后(世界)\n')
    add('标点-引号', punct, '"你好" \'世界\' "混合’\n')
    add('标点-破折号', punct, 'a--b --- c —— d\n')
    add('标点-波浪', punct, 'a~b c～d\n')
    add('标点-百分号', punct, '50%~60% 70%～80%\n')
    add('标点-空格', punct, '中文 ， 标点 ， 中文\n')
    add('标点-重复', punct, 'a！！b？？c？！d，，e、、f～～g\n')
    add('标点-HTML实体', punct, 'a&nbsp;b&amp;c&lt;d&#65;e\n')
    add('标点-HTML实体无分号', punct, 'a&nbspb&ampc\n')

    # --- 引号形式 ---
    add('引号-直角转弯', {'quotationType': 1}, '「你好」『世界』\n')
    add('引号-弯转直角', {'quotationType': 2}, '“你好”‘世界’\n')

    # --- 连续引号 ---
    add('连续引号1', {'normalizePunctuations': True, 'consecutiveQuotationsType': 1},
        '他说：“第一行\n第二行”结束\n')
    add('连续引号2', {'normalizePunctuations': True, 'consecutiveQuotationsType': 2},
        '他说：“第一行\n第二行”结束\n')

    # --- 中英文加空格 ---
    pangu = {'paranoidTextSpacing': True}
    add('pangu-中英', pangu, '中文English混排\n')
    add('pangu-数字', pangu, '第1章开始\n')
    add('pangu-引号', pangu, '中文"quoted"中文\n')
    add('pangu-括号', pangu, '中文(abc)中文\n')
    add('pangu-井号', pangu, '中文#tag中文\n')
    add('pangu-运算符', pangu, '中文a+b中文\n')

    # --- 移除中文间空格 ---
    rm = {'rmSpacesBetweenChnChars': True}
    add('去中文空格', rm, '中 文 混 排\n')
    add('去中文空格-英文', rm, '中文 abc 123 中文\n')
    add('去中文空格-章节', rm, '第一章 起点\n正文\n')

    # --- HTML 标签 ---
    add('html标签1', {'changeTextFormat': True, 'addHtmlTag': 1},
        '第一章\n正文\n\n※※※\n')
    add('html标签2', {'changeTextFormat': True, 'addHtmlTag': 2},
        '<p>第一段</p>\n<p>第二段</p>\n')

    # --- 组合 ---
    add('组合-排版+标点', {'changeTextFormat': True, 'normalizePunctuations': True},
        '  第一章 起点 \n\n他说："你好,世界"。\n\n')
    add('组合-全开', {
        'changeTextFormat': True, 'normalizePunctuations': True,
        'quotationType': 1, 'paranoidTextSpacing': True,
        'rmSpacesBetweenChnChars': True,
    }, '  第一章 起点 \n\n他说："你好,世界"。第1章。\n\n')
    return cases


def run_php(cases: List[Tuple[str, Dict[str, Any], str]]) -> List[Dict[str, Any]]:
    payload = [{'options': o, 'input': t} for _, o, t in cases]
    proc = subprocess.run(
        ['php', PHP_RUNNER],
        input=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=os.path.dirname(os.path.dirname(HERE)),
    )
    if proc.returncode != 0:
        raise RuntimeError('php runner failed: %s' % proc.stderr.decode('utf-8', 'replace'))
    return json.loads(proc.stdout.decode('utf-8'))


def run_python(options: Dict[str, Any], text: str) -> str:
    opt = LayoutOptions()
    for php_key, py_key in OPTION_MAP.items():
        if php_key in options:
            setattr(opt, py_key, options[php_key])
    return LayoutEngine(opt).format(text)


def describe_diff(a: str, b: str) -> str:
    limit = min(len(a), len(b))
    idx = limit
    for i in range(limit):
        if a[i] != b[i]:
            idx = i
            break
    start = max(0, idx - 40)
    return ('首个差异位于第 %d 个字符（PHP 长度 %d / Python 长度 %d）\n'
            '  PHP    : %r\n  Python : %r'
            % (idx, len(a), len(b), a[start:idx + 40], b[start:idx + 40]))


def main() -> int:
    verbose = '--verbose' in sys.argv
    cases = build_cases()
    results = run_php(cases)

    failed = 0
    for (name, options, text), res in zip(cases, results):
        if 'error' in res:
            print('[PHP错误] %s: %s' % (name, res['error']))
            failed += 1
            continue
        php_out = res['output']
        py_out = run_python(options, text)
        if php_out == py_out:
            if verbose:
                print('[一致] %s' % name)
            continue
        failed += 1
        print('[不一致] %s' % name)
        print('  选项: %s' % options)
        print('  输入: %r' % text)
        print('  ' + describe_diff(php_out, py_out).replace('\n', '\n  '))

    print('\n共 %d 条用例，一致 %d 条，不一致 %d 条' % (len(cases), len(cases) - failed, failed))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
