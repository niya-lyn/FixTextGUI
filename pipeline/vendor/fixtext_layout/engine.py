"""排版引擎 —— FixText 排版逻辑的 Python 移植。

对应 PHP 侧 ``App\\Service\\Formatting\\FileProcessor`` 的以下方法：

===========================  ==========================================
PHP                          Python
===========================  ==========================================
changeTextFormat()           LayoutEngine.change_text_format()
normalizePunctuations()      LayoutEngine.normalize_punctuations()
changeQuotationType()        LayoutEngine.change_quotation_type()
changeConsecutiveQuotations() LayoutEngine.change_consecutive_quotations()
formatHeadings()             LayoutEngine.format_headings()
rmSpacesBetweenChnChars()    LayoutEngine.rm_spaces_between_chn_chars()
Util::pangu()                LayoutEngine.pangu()
===========================  ==========================================

主入口 :meth:`LayoutEngine.format` 复刻 ``FileProcessor::processFile()`` 中
与排版相关的变换顺序（跳过替换域的大小写/数字转换/分词等步骤——那些属于
T1.1 编排器的替换引擎职责）。

PHP/PCRE 与 Python ``re`` 的两处系统性差异已在 :mod:`fixtext_layout.php_compat`
中统一处理：

1. PCRE 的 ``\\x{...}`` 码点写法 → Python ``\\uXXXX``
2. PCRE 默认使用 ASCII 字符表（``\\d`` 只匹配 0-9）→ Python 统一加 ``re.ASCII``

所有正则替换统一走 :func:`fixtext_layout.php_compat.do_regex_replace`，
以便复用同一套翻译逻辑（不要在本模块内直接使用 ``re.sub`` 处理 PCRE 表达式）。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .options import LayoutOptions
from .php_compat import (
    compile_pcre,
    do_regex_replace,
    multi_regex_replace,
    php_html_entity_decode,
    php_replacement,
    php_strtr,
    php_strip_tags,
    php_trim,
)
from .rules_data import (
    HTML_CHAPTER_MARK,
    PUNCTUATION_MAP,
    PUNCTUATION_PATTERNS,
    SPACE_PATTERN,
)

__all__ = ['LayoutEngine', 'format_text']


def _rule(search: str, replace: str, modifiers: str = 'um') -> Dict[str, object]:
    """构造一条规则（``search`` 不含分隔符）。"""
    return {'search': search, 'replace': replace, 'modifiers': modifiers}


# --------------------------------------------------------------------------
# Util::pangu —— 中文字符与英文字母、数字之间加空格
# --------------------------------------------------------------------------

#: PHP ``Util::pangu()`` 中 $cjk 变量的内容（PCRE 码点写法）
CJK_RANGES_PCRE = (
    '\\x{2e80}-\\x{2eff}'
    '\\x{2f00}-\\x{2fdf}'
    '\\x{3040}-\\x{309f}'
    '\\x{30a0}-\\x{30ff}'
    '\\x{3100}-\\x{312f}'
    '\\x{3200}-\\x{32ff}'
    '\\x{3400}-\\x{4dbf}'
    '\\x{4e00}-\\x{9fff}'
    '\\x{f900}-\\x{faff}'
)

_CJK = CJK_RANGES_PCRE

#: pangu 的规则顺序与 PHP 一致（``bracket`` 分支在 PHP 中有特殊处理，单独实现）
_PANGU_RULES: Tuple[Tuple[str, str], ...] = (
    ('([' + _CJK + '])(["\'])', '$1 $2'),
    ('(["\'])([' + _CJK + '])', '$1 $2'),
    ('(["\']+)(\\s*)(.+?)(\\s*)(["\']+)', '$1$3$5'),
    ('([' + _CJK + '])(#(\\S+))', '$1 $2'),
    ('((\\S+)#)([' + _CJK + '])', '$1 $3'),
    ('([' + _CJK + '])([a-zA-ZΑ-Ωα-ω0-9])([\\+\\-\\*\\/=&\\\\|<>])', '$1 $2 $3'),
    ('([\\+\\-\\*\\/=&\\\\|<>])([a-zA-ZΑ-Ωα-ω0-9])([' + _CJK + '])', '$1 $2 $3'),
    ('([' + _CJK + '])([<\\[\\{\\(]+(.*?)[>\\]\\}\\)]+)([' + _CJK + '])', '$1 $2 $4'),
    ('([<\\[\\{\\(]+)(\\s*)(.+?)(\\s*)([>\\]\\}\\)]+)', '$1$3$5'),
    ('([' + _CJK + '])([a-zA-ZΑ-Ωα-ω0-9`@&%\\=\\$\\^\\*\\-\\+\\/|\\\\])', '$1 $2'),
    ('([a-zA-ZΑ-Ωα-ω0-9`~!%&=;\\|\\,\\.\\:\\?\\$\\^\\*\\-\\+\\/\\\\])([' + _CJK + '])', '$1 $2'),
)

#: pangu 的 bracket 分支：主规则未命中时才使用的两个兜底规则
_PANGU_BRACKET_FALLBACKS: Tuple[Tuple[str, str], ...] = (
    ('([' + _CJK + '])([<>[\\]\\{\\}\\(\\)])', '$1 $2'),
    ('([<>\\[\\]\\{\\}\\(\\)])([' + _CJK + '])', '$1 $2'),
)


# --------------------------------------------------------------------------
# 标点规则中需要 Python 侧单独实现的一条
# --------------------------------------------------------------------------

#: punctuationPatterns[17] 的语义：
#:   (?<![注释註釋批解答案问题目：:])(?<=\d\.\d|\d{3}|[6-9]\d)[：:](?=\d)  ->  ∶
#: 变长后顾断言（宽度 3/3/2）无法用 Python 标准库 re 表达，这里按原语义手写。
_PP17_EXCLUDE = frozenset('注释註釋批解答案问题目：:')


def _pp17_lookbehind_ok(content: str, pos: int) -> bool:
    """判断 pos 之前是否构成 ``\\d.\\d`` / ``\\d{3}`` / ``[6-9]\\d``。"""
    if pos >= 3:
        a, b, c = content[pos - 3], content[pos - 2], content[pos - 1]
        if '0' <= a <= '9' and b == '.' and '0' <= c <= '9':
            return True
        if '0' <= a <= '9' and '0' <= b <= '9' and '0' <= c <= '9':
            return True
    if pos >= 2:
        a, b = content[pos - 2], content[pos - 1]
        if '6' <= a <= '9' and '0' <= b <= '9':
            return True
    return False


def _pp17_python(content: str) -> str:
    """等价于 punctuationPatterns[17]。

    规则：把「紧跟在 ``\\d.\\d`` / ``\\d{3}`` / ``[6-9]\\d`` 之后、
    且后面紧跟数字、且前一个字符不在注释类字符集中」的 ``：`` 或 ``:`` 换成 ``∶``。
    """
    out: List[str] = []
    i = 0
    n = len(content)
    while i < n:
        ch = content[i]
        if ch in '：:' and i + 1 < n and '0' <= content[i + 1] <= '9':
            if i > 0 and content[i - 1] not in _PP17_EXCLUDE:
                if _pp17_lookbehind_ok(content, i):
                    out.append('∶')
                    i += 1
                    continue
        out.append(ch)
        i += 1
    return ''.join(out)


def _build_punctuation_rules() -> List[Dict[str, object]]:
    """把 rules_data 中的 44 条标点规则组装成可执行规则列表。"""
    rules: List[Dict[str, object]] = []
    for index, (search, replace) in enumerate(PUNCTUATION_PATTERNS):
        if index == 17:
            rules.append({'search': search, 'replace': replace, 'python': _pp17_python})
        else:
            rules.append({'search': search, 'replace': replace})
    return rules


PUNCTUATION_RULES: List[Dict[str, object]] = _build_punctuation_rules()


# --------------------------------------------------------------------------
# FileProcessor::formatHeadings 的 9 条标题分级规则
# --------------------------------------------------------------------------

HEADINGS_RULES: Tuple[Tuple[str, str], ...] = (
    ('^(?!第.*?[章回卷部集节篇册])(?=[^ 　\n章卷部集节篇册◎=+])(.*?)$', '◎$1'),
    ('^◎([^◎]{0,30000})^◎◎([^◎]{0,30000})^◎◎◎([^◎]*?)\n',
     '第0.0部 ◎$1\n\n\n第0.0卷 ◎$2\n\n\n第0.0章 ◎$3\n'),
    ('^◎(.*?)\n+◎(.*?)\n+◎(.*?)\n', '第0.0部 ◎$1\n\n\n第0.0卷 ◎$2\n\n\n第0.0章 ◎$3\n'),
    ('^◎(.*?)\n+◎(.*?)\n+([第章][\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾至到.\-—]+[章回节篇话])',
     '第0.0部 ◎$1\n\n\n第0.0卷 ◎$2\n\n\n$3'),
    ('^◎(.*?)\n+([第卷][\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾.\-—]+[卷部集册])',
     '第0.0部 ◎$1\n\n\n$2$3$4'),
    ('^◎([^◎]{0,30000})^◎◎([^◎]*?)\n', '第0.0卷 ◎$1\n\n\n第0.0章 ◎$2\n'),
    ('^◎(.*?)\n+◎(.*?)\n', '第0.0卷 ◎$1\n\n\n第0.0章 ◎$2\n'),
    ('^◎(.*?)\n+([第章][\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾至到.\-—]+[章回节篇话])',
     '第0.0卷 ◎$1\n\n\n$2'),
    ('^◎(.*?)\n', '第0.0章 ◎$1\n'),
)


#: changeTextFormat 中「章节标题」的识别表达式（PHP 原样转写，去掉 /.../um 分隔符）
CHAPTER_HEADING_PATTERN = (
    r'^[ 　]*((?:(?:[第卷章续]之?[\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾.\-—至到章]+'
    r'[章回卷部集节篇册话]?)|[（(][\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾.\-—至到章]+[)）]'
    r'|楔子|引[言子]?|前言|序[\d言曲章]?|续[篇章]?|跋|后记|番外篇?|篇外篇|特别篇|后日谈|小剧场|间章'
    r'|.{0,8}总结|最?终[卷篇]|大?结局[卷篇]?|终章|.{0,6}感言|后记|尾声|内容简介)'
    r'(?:[ 　]|(?<=[章回卷部集节篇册话记跋])[：:]|(?<![.\-])$)+)'
)


class LayoutEngine:
    """FixText 排版引擎的 Python 实现。"""

    def __init__(self, options: Optional[LayoutOptions] = None) -> None:
        self.options = options if options is not None else LayoutOptions()

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def format(self, content: str) -> str:
        """执行排版流水线，返回排版后的文本。

        顺序与 PHP ``FileProcessor::processFile()`` 中排版相关的步骤一致。
        """
        opt = self.options
        if opt.rm_spaces_between_chn_chars:
            content = self.rm_spaces_between_chn_chars(content)
        if opt.normalize_punctuations:
            content = self.normalize_punctuations(content)
        content = self.change_quotation_type(content)
        if (opt.change_text_format or opt.extract_text_from_html) \
                and opt.is_default_encoding() \
                and opt.consecutive_quotations_type == 0:
            content = self.change_text_format(content)
        if opt.format_headings and opt.is_txt_file:
            content = self.format_headings(content)
        if opt.paranoid_text_spacing and opt.is_txt_file:
            content = self.pangu(content)
        return php_trim(content) + opt.new_line_type

    # ------------------------------------------------------------------
    # 单步实现
    # ------------------------------------------------------------------

    def change_text_format(self, content: str) -> str:
        """等价于 PHP ``FileProcessor::changeTextFormat()``。

        职责：行首行尾空白清理、空行清理、首行缩进、章节标题分隔、HTML 标签处理。
        """
        opt = self.options
        if opt.add_html_tag == 1:
            content = do_regex_replace(
                _rule(r'^(?![ 　\n])(.+)$', '<title>$1</title>', 'umi'), content)
        elif opt.add_html_tag == 2:
            opt.add_indentation = True
            content = do_regex_replace(
                _rule(r'<title>(.*?)</title>\n<title>.*?</title>', '◎$1', 'umi'), content)
            content = php_strip_tags(content)

        space = SPACE_PATTERN
        # 移除所有空行和行首行尾空格
        content = do_regex_replace(_rule(r'^[%s]*$\n' % space, '', 'um'), content)
        content = do_regex_replace(_rule(r'^[%s]+' % space, '', 'um'), content)
        content = do_regex_replace(_rule(r'[%s]+$' % space, '', 'um'), content)

        if opt.add_indentation:
            # 增加首行缩进
            content = do_regex_replace(_rule(r'^', '　　', 'um'), content)
            # 章节标题行不缩进，且与正文之间空两行
            content = do_regex_replace(
                _rule(CHAPTER_HEADING_PATTERN, '\n\n$1', 'um'), content)
            # 其他特殊章节统一加 ◎ 标记
            content = do_regex_replace(
                _rule(r'^[ 　]*◎(.*)', '\n\n◎$1', 'um'), content)

        if opt.add_html_tag == 1:
            content = do_regex_replace(
                _rule(r'^(?!<title>)(.*)$', '<p>$1</p>', 'umi'), content)
            content = do_regex_replace(
                _rule(r'<p>※※※</p>',
                      '<p class="brline"><img alt="" src="../Images/transpacep.png"/>　</p>',
                      'umi'), content)
            content = do_regex_replace(
                _rule(r'^<title>.*?</title>', '$0\n$0', 'umi'), content)
        elif opt.add_html_tag == 2:
            content = do_regex_replace(_rule(r'^◎(?!◎)', '', 'umi'), content)

        if HTML_CHAPTER_MARK in content:
            content = content.replace(HTML_CHAPTER_MARK, '')
        return content

    def normalize_punctuations(self, content: str) -> str:
        """等价于 PHP ``FileProcessor::normalizePunctuations()``。

        职责：全角/半角与标点形态统一（strtr 映射表）、HTML 实体解码、
        44 条标点规范正则、连续引号形式调整。
        """
        # 先统一转换一些标点（含全角数字/字母转半角）
        content = php_strtr(content, PUNCTUATION_MAP)
        if self.options.is_txt_file:
            content = php_html_entity_decode(content)
        # 规范中文内容的常见标点
        content = multi_regex_replace(PUNCTUATION_RULES, content)
        if self.options.consecutive_quotations_type != 0:
            content = self.change_consecutive_quotations(
                content, self.options.consecutive_quotations_type)
        return content

    def change_quotation_type(self, content: str) -> str:
        """等价于 PHP ``FileProcessor::changeQuotationType()``。"""
        quotation_map: Dict[str, str] = {}
        if self.options.quotation_type == 1:
            quotation_map = {'「': '“', '」': '”', '『': '‘', '』': '’'}
        elif self.options.quotation_type == 2:
            quotation_map = {'“': '「', '”': '」', '‘': '『', '’': '』'}
        if quotation_map:
            content = php_strtr(content, quotation_map)
        return content

    def change_consecutive_quotations(self, content: str, quotation_type: int) -> str:
        """等价于 PHP ``FileProcessor::changeConsecutiveQuotations()``。"""
        configs = {
            1: {
                'searchPattern': r'((?<!“)“[^”“]*?\n+)(.*?)”',
                'searchModifiers': 'us',
                'htmlPattern': r'([ 　]*)(<p[^/>]*?>)(?!“)',
                'htmlReplacement': '$1$2“',
                'txtPattern': r'^([ 　]*)(?!“)([^ 　]+)',
                'txtReplacement': '$1“$2',
            },
            2: {
                'searchPattern': r'((?<!“)“[^”]*?\n+)(.*?)”',
                'searchModifiers': 'us',
                'htmlPattern': r'([ 　]*)(<p[^/>]*?>)“',
                'htmlReplacement': '$1$2',
                'txtPattern': r'^([ 　]*?)“',
                'txtReplacement': '$1',
            },
        }
        config = configs[quotation_type]
        is_html = not self.options.is_txt_file
        line_pattern = config['htmlPattern'] if is_html else config['txtPattern']
        line_replacement = config['htmlReplacement'] if is_html else config['txtReplacement']
        line_regex = compile_pcre(line_pattern, 'um')
        line_repl = php_replacement(line_replacement)
        search_regex = compile_pcre(config['searchPattern'], config['searchModifiers'])

        def _replace(match: 're.Match[str]') -> str:
            lines = match.group(2).split('\n')
            lines = [line_regex.sub(line_repl, line) for line in lines]
            return match.group(1) + '\n'.join(lines) + '”'

        return search_regex.sub(_replace, content)

    def format_headings(self, content: str) -> str:
        """等价于 PHP ``FileProcessor::formatHeadings()``。"""
        rules = [{'search': s, 'replace': r, 'modifiers': 'um'} for s, r in HEADINGS_RULES]
        content = multi_regex_replace(rules, content, 'um')
        self.options.add_indentation = True
        return self.change_text_format(content)

    def rm_spaces_between_chn_chars(self, content: str) -> str:
        """等价于 PHP ``FileProcessor::rmSpacesBetweenChnChars()``。"""
        space = SPACE_PATTERN
        # 先将不在行首的连续空格转为一个空格
        content = do_regex_replace(
            _rule(r'(?<!^)(?<=[^%s])[%s]+(?=[^%s])' % (space, space, space), ' ', 'um'),
            content)

        # 需要排除掉一些英文标点，避免误伤正常的英文句子
        pattern = (
            r'([^\n 　]{0,20})'
            r'(?:(?<![\n 　章卷册集◎,.!?;:\'\"{}])[%s]+(?![\da-zA-Z 　第\"\'{}])'
            r'|(?<![\n\da-zA-Z 　章回卷部集节篇册◎,.!?;:\'\"{}])[%s]+(?![第\"\'{}]))'
            % (space, space)
        )
        regex = compile_pcre(pattern, 'um')
        keep_head = ('章', '卷', '册', '集', '◎')

        def _replace(match: 're.Match[str]') -> str:
            first = match.group(1)[:1]
            if first in keep_head:
                return match.group(0)
            return match.group(1)

        return regex.sub(_replace, content)

    def pangu(self, content: str) -> str:
        """等价于 PHP ``Util::pangu()``：在中文字符和英文/数字之间加空格。"""
        for search, replace in _PANGU_RULES[:7]:
            content = do_regex_replace(_rule(search, replace, 'iu'), content)
        # bracket 分支：主规则未命中时才走兜底规则
        old = content
        content = do_regex_replace(_rule(_PANGU_RULES[7][0], _PANGU_RULES[7][1], 'iu'), content)
        if old == content:
            for search, replace in _PANGU_BRACKET_FALLBACKS:
                content = do_regex_replace(_rule(search, replace, 'iu'), content)
        for search, replace in _PANGU_RULES[8:]:
            content = do_regex_replace(_rule(search, replace, 'iu'), content)
        return content


def format_text(content: str, options: Optional[LayoutOptions] = None) -> str:
    """排版入口：等价于 ``LayoutEngine(options).format(content)``。

    T1.1 一键校正编排器直接调用本函数即可。
    """
    return LayoutEngine(options).format(content)
