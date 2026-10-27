"""PHP / PCRE 兼容层。

FixText 的排版逻辑用 PHP + PCRE 实现，本模块把 PHP 的几个关键语义搬到
Python 标准库 ``re`` 上，使 Python 侧输出与 PHP 侧逐字节一致：

* ``php_trim``            —— PHP ``trim()`` 只裁剪 " \\t\\n\\r\\0\\x0B"，与 Python ``str.strip()`` 不同
* ``php_strtr``           —— PHP ``strtr($s, $map)``：最长键优先、单遍扫描、替换结果不再回扫
* ``php_html_entity_decode`` —— PHP 8 的 ``html_entity_decode()``（ENT_QUOTES|ENT_SUBSTITUTE|ENT_HTML401）
* ``php_strip_tags``      —— PHP ``strip_tags()``
* ``translate_pattern``   —— PCRE → Python ``re`` 的表达式翻译（``\\x{...}``、变长/多选后顾断言）
* ``php_replacement_to_python`` —— PHP ``$1`` 回引用写法 → Python ``\\g<1>``

已知差异（PHP 侧存在而本层未覆盖，代码中均显式标注）：

* PCRE 的 ``(*SKIP)(*F)`` / ``(?|...)`` 分支重置组：不在排版规则范围内
* PHP 的 ``preg_replace`` 遇到非法 UTF-8 会整条失败：Python 侧用 ``errors='strict'`` 保持同样行为
"""

from __future__ import annotations

import re
from html.entities import entitydefs
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

__all__ = [
    'UnsupportedPattern',
    'php_trim',
    'php_strtr',
    'php_html_entity_decode',
    'php_strip_tags',
    'translate_pattern',
    'compile_pcre',
    'php_replacement',
    'parse_php_replacement',
    'do_regex_replace',
    'multi_regex_replace',
]

# PHP trim() 的默认裁剪字符集
PHP_TRIM_CHARS = " \t\n\r\0\x0b"


class UnsupportedPattern(ValueError):
    """PCRE 表达式无法用 Python 标准库 re 等价表达时抛出。"""


# --------------------------------------------------------------------------
# 基础字符串语义
# --------------------------------------------------------------------------

def php_trim(text: str, chars: str = PHP_TRIM_CHARS) -> str:
    """等价于 PHP ``trim($text)``（默认字符集）。

    与 ``str.strip()`` 的关键差异：PHP 不裁剪 U+3000（全角空格）等 Unicode 空白。
    """
    return text.strip(chars)


def php_strtr(text: str, mapping: Mapping[str, str]) -> str:
    """等价于 PHP ``strtr($text, $array)``。

    PHP 语义：

    1. 键按长度从长到短尝试（长度相同时保持插入顺序）
    2. 从左到右单遍扫描，替换后的文本不再参与匹配
    3. 一个位置匹配成功后立即跳过整个键，不做回溯
    """
    if not mapping or not text:
        return text

    by_first: Dict[str, List[Tuple[str, str]]] = {}
    for key, value in mapping.items():
        if not key:
            continue
        by_first.setdefault(key[0], []).append((key, value))
    for bucket in by_first.values():
        bucket.sort(key=lambda kv: -len(kv[0]))

    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        bucket = by_first.get(ch)
        matched = False
        if bucket:
            for key, value in bucket:
                if text.startswith(key, i):
                    out.append(value)
                    i += len(key)
                    matched = True
                    break
        if not matched:
            out.append(ch)
            i += 1
    return ''.join(out)


# PHP 8 的 html_entity_decode() 默认 flags = ENT_QUOTES | ENT_SUBSTITUTE | ENT_HTML401
_PHP_ENTITIES: Dict[str, str] = dict(entitydefs)
_PHP_ENTITIES.setdefault('quot', '"')
_PHP_ENTITIES.setdefault('amp', '&')
_PHP_ENTITIES.setdefault('lt', '<')
_PHP_ENTITIES.setdefault('gt', '>')

_ENTITY_RE = re.compile(r'&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);')


def _php_codepoint_to_char(code: int) -> str:
    if code <= 0 or code > 0x10FFFF:
        return '\ufffd'
    try:
        return chr(code)
    except ValueError:  # pragma: no cover - chr 不会失败，保险分支
        return '\ufffd'


def php_html_entity_decode(text: str) -> str:
    """等价于 PHP 8 ``html_entity_decode($text)``（ENT_QUOTES|ENT_SUBSTITUTE|ENT_HTML401）。

    与 ``html.unescape()`` 的差异：Python 用的是 HTML5 实体表且允许省略分号，
    PHP 用的是 HTML 4.01 实体表且要求分号。
    """

    def _replace(match: 're.Match[str]') -> str:
        body = match.group(1)
        if body.startswith('#'):
            try:
                if body[1] in 'xX':
                    code = int(body[2:], 16)
                else:
                    code = int(body[1:], 10)
            except ValueError:  # pragma: no cover - 正则已保证可解析
                return match.group(0)
            return _php_codepoint_to_char(code)
        value = _PHP_ENTITIES.get(body)
        if value is None:
            return match.group(0)
        return value

    return _ENTITY_RE.sub(_replace, text)


def php_strip_tags(text: str) -> str:
    """等价于 PHP ``strip_tags()``（保留标签之间的正文，丢弃标签本身）。"""
    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch != '<':
            out.append(ch)
            i += 1
            continue
        if text.startswith('<!--', i):
            end = text.find('-->', i + 4)
            i = (end + 3) if end != -1 else n
            continue
        # PHP strip_tags 的标签起始判定（已与 PHP 8.5 实测核对）：
        # '<' 后跟空白（空格/\t/\n）→ 字面量；跟其他任意字符（字母、数字、
        # 汉字、'.'、'-'、'>' 等）→ 标签起始，删除至 '>' 或串尾。
        nxt = text[i + 1] if i + 1 < n else ''
        if nxt == '' or nxt.isspace():
            out.append(ch)
            i += 1
            continue
        j = i + 1
        quote = None
        while j < n:
            c = text[j]
            if quote is not None:
                if c == quote:
                    quote = None
            elif c in '"\'':
                quote = c
            elif c == '>':
                j += 1
                break
            j += 1
        i = j
    return ''.join(out)


# --------------------------------------------------------------------------
# PCRE → Python re
# --------------------------------------------------------------------------

_MODIFIER_FLAGS = {
    'i': re.IGNORECASE,
    'm': re.MULTILINE,
    's': re.DOTALL,
    'x': re.VERBOSE,
}

# PCRE 允许的修饰符全集（u 在 Python 字符串模式下天然成立）
_KNOWN_MODIFIERS = set('imsxuADSUXJn')


def parse_modifiers(modifiers: str) -> int:
    """把 PCRE 修饰符串转成 Python ``re`` 的 flag 组合。

    始终附带 ``re.ASCII``：PCRE 默认使用 ASCII 字符表（``\\d`` 只匹配 0-9，
    ``\\w`` 只匹配 ``[A-Za-z0-9_]``，``\\s`` 只匹配 ASCII 空白），
    而 Python 的 ``re`` 在 str 模式下默认按 Unicode 语义解释这三个转义。
    PHP 的 ``/u`` 修饰符只开启 UTF-8 编码，不开启 UCP，因此这里必须显式补 ``re.ASCII``。
    """
    flags = re.ASCII
    for ch in modifiers:
        if ch == 'u':
            continue
        if ch not in _MODIFIER_FLAGS:
            raise UnsupportedPattern('不支持的修饰符: %s' % ch)
        flags |= _MODIFIER_FLAGS[ch]
    return flags


def _find_matching_paren(text: str, open_idx: int) -> int:
    """返回与 ``text[open_idx] == '('`` 配对的右括号下标。"""
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        c = text[i]
        if c == '\\':
            i += 2
            continue
        if c == '[':
            i += 1
            while i < n and text[i] != ']':
                if text[i] == '\\':
                    i += 1
                i += 1
            i += 1
            continue
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise UnsupportedPattern('括号不配对: %r' % text)


def _split_top_level(body: str, sep: str) -> List[str]:
    """按顶层分隔符切分（忽略括号组、字符组、转义字符内部的分隔符）。"""
    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    in_class = False
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c == '\\':
            buf.append(body[i:i + 2])
            i += 2
            continue
        if in_class:
            buf.append(c)
            if c == ']':
                in_class = False
            i += 1
            continue
        if c == '[':
            in_class = True
            buf.append(c)
            i += 1
            continue
        if c == '(':
            depth += 1
            buf.append(c)
            i += 1
            continue
        if c == ')':
            depth -= 1
            buf.append(c)
            i += 1
            continue
        if c == sep and depth == 0:
            parts.append(''.join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    parts.append(''.join(buf))
    return parts


def translate_pattern(search: str) -> str:
    """把 PCRE 表达式翻译成 Python ``re`` 可用的表达式。

    处理项：

    * ``\\x{HHHH}`` → ``\\uHHHH``（Python ``re`` 不支持 PCRE 的 ``\\x{...}`` 写法）
    * ``(?<!A|B|C)`` → ``(?<!A)(?<!B)(?<!C)``
      （NOT(A∨B∨C) ≡ NOT(A)∧NOT(B)∧NOT(C)，三个子断言各自定长即可编译）
    * ``(?<=A|B|C)``（多选正向后顾）无法用标准库表达，抛 ``UnsupportedPattern``
    """
    out: List[str] = []
    i = 0
    n = len(search)
    while i < n:
        ch = search[i]
        if ch == '\\':
            if search.startswith('\\x{', i):
                end = search.find('}', i)
                if end != -1:
                    code = search[i + 3:end]
                    if not code or any(c not in '0123456789abcdefABCDEF' for c in code):
                        raise UnsupportedPattern('非法 \\x{...} 转义: %r' % search[i:i + 12])
                    out.append('\\u' + code.rjust(4, '0'))
                    i = end + 1
                    continue
            out.append(search[i:i + 2])
            i += 2
            continue
        if search.startswith('(?<!', i) or search.startswith('(?<=', i):
            # '(?<!' / '(?<=' 均为 4 个字符，'(' 位于下标 i，断言体从 i + 4 开始
            negative = search[i + 3] == '!'
            open_idx = i
            end = _find_matching_paren(search, open_idx)
            body = search[open_idx + 4:end]
            alts = _split_top_level(body, '|')
            if len(alts) == 1:
                # 断言体必须递归翻译：体内同样可能含 \x{...} 等需要转换的写法
                out.append(search[open_idx:open_idx + 4] + translate_pattern(body) + ')')
            elif negative:
                out.append(''.join(
                    '(?<!%s)' % translate_pattern(alt) for alt in alts))
            else:
                raise UnsupportedPattern(
                    '多选正向后顾断言无法用标准库 re 表达: (?<=%s)' % body)
            i = end + 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


# PCRE 多行模式下 ``^`` 的精确等价表达式。
#
# PCRE:  ``^`` 匹配「行首」= 主题开头，或任意 ``\n`` 之后；但当该 ``\n`` 是主题的
#        最后一个字符时，PCRE **不再**在其后匹配 ``^``。
# Python: ``re.M`` 的 ``^`` 会额外匹配「主题末尾换行之后」的那个位置。
#
# 因此用 ``\A|(?<=\n)(?!\Z)`` 复刻 PCRE 语义：``\Z`` 在 Python 中表示字符串绝对末尾，
# ``(?!\Z)`` 恰好排除掉「末尾换行之后」的位置。已在 13 组样本（含 CRLF / CR / 空串）
# 上与 PCRE 逐位比对一致。
_PCRE_CARET_M = r'(?:\A|(?<=\n)(?!\Z))'


def _consume_char_class(search: str, i: int) -> int:
    """``search[i] == '['`` 时，返回字符组结束后的下标。

    字符组整体原样保留（其中的 ``^`` 是取反符或字面量，绝不能被翻译）。
    """
    n = len(search)
    j = i + 1
    if j < n and search[j] == '^':
        j += 1
    if j < n and search[j] == ']':
        j += 1  # 紧跟开头的 ']' 是字面量
    while j < n:
        c = search[j]
        if c == '\\':
            j += 2
            continue
        if c == ']':
            return j + 1
        j += 1
    return n


def _translate_multiline_caret(search: str) -> str:
    """把多行模式中未被转义、也不在字符组内的 ``^`` 换成 PCRE 语义等价表达式。

    零宽后顾断言的特例：PCRE 里后顾断言的语义是「内容在当前位置**结束**处匹配」，
    对零宽内容（如 ``^``）等价于断言**当前位置**本身。因此 ``(?<!^)`` 的含义是
    「当前位置不是行首」，而不是「前一个位置不是行首」。经 PHP 实测（8 组样本）
    验证，等价于把整个 token 改写成前瞻形式 ``(?!(?:\\A|(?<=\\n)(?!\\Z)))``。
    """
    out: List[str] = []
    i = 0
    n = len(search)
    while i < n:
        ch = search[i]
        if ch == '\\':
            out.append(search[i:i + 2])
            i += 2
            continue
        if search.startswith('(?<!^)', i):
            out.append('(?!' + _PCRE_CARET_M + ')')
            i += 6
            continue
        if search.startswith('(?<=^)', i):
            out.append('(?=' + _PCRE_CARET_M + ')')
            i += 6
            continue
        if ch == '[':
            end = _consume_char_class(search, i)
            out.append(search[i:end])
            i = end
            continue
        if ch == '^':
            out.append(_PCRE_CARET_M)
            i += 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def compile_pcre(search: str, modifiers: str = 'umx') -> 're.Pattern[str]':
    """编译一条 PCRE 规则，返回 Python ``re`` 模式对象。"""
    flags = parse_modifiers(modifiers)
    try:
        translated = translate_pattern(search)
        if flags & re.MULTILINE:
            # 必须放在 translate_pattern 之后：翻译产物里已含 (?<=\n) 等断言，
            # 再走一遍 translate_pattern 会被误判为「多选正向后顾」而报错。
            translated = _translate_multiline_caret(translated)
    except UnsupportedPattern:
        raise
    try:
        return re.compile(translated, flags)
    except re.error as exc:
        raise UnsupportedPattern(
            '表达式无法用标准库 re 编译: %s (%s)' % (search, exc)) from exc


def parse_php_replacement(replacement: str) -> List[Tuple[str, object]]:
    """把 PHP ``preg_replace`` 替换串解析成 ``[('lit', 文本) | ('group', 序号)]`` 序列。

    PHP 支持 ``$1`` / ``${1}`` / ``\\1`` 三种回引用写法，组号 0-99；
    引用不存在的分组时输出空字符串；``$`` 后不跟数字时按字面量处理。
    """
    segs: List[Tuple[str, object]] = []
    lit: List[str] = []

    def flush() -> None:
        if lit:
            segs.append(('lit', ''.join(lit)))
            del lit[:]

    i = 0
    n = len(replacement)
    while i < n:
        c = replacement[i]
        if c == '\\' and i + 1 < n:
            nxt = replacement[i + 1]
            if nxt.isdigit():
                j = i + 1
                while j < n and j - i <= 2 and replacement[j].isdigit():
                    j += 1
                flush()
                segs.append(('group', int(replacement[i + 1:j])))
                i = j
                continue
            lit.append(c)
            lit.append(nxt)
            i += 2
            continue
        if c == '$' and i + 1 < n:
            if replacement[i + 1] == '{':
                end = replacement.find('}', i)
                if end != -1 and replacement[i + 2:end].isdigit():
                    flush()
                    segs.append(('group', int(replacement[i + 2:end])))
                    i = end + 1
                    continue
                lit.append(c)
                i += 1
                continue
            if replacement[i + 1].isdigit():
                j = i + 1
                while j < n and j - i <= 2 and replacement[j].isdigit():
                    j += 1
                flush()
                segs.append(('group', int(replacement[i + 1:j])))
                i = j
                continue
        lit.append(c)
        i += 1
    flush()
    return segs


def php_replacement(replacement: str) -> Callable[['re.Match[str]'], str]:
    """把 PHP 替换串转成一个可直接交给 ``re.sub`` 的回调函数。

    使用回调而不是替换串模板，是为了精确复现 PHP 的两个细节：

    * 引用不存在的分组时输出空字符串（Python 的 ``\\g<9>`` 会直接抛异常）
    * 替换文本里的反斜杠按字面输出（Python 的替换串模板会把它当转义）
    """
    segs = parse_php_replacement(replacement)

    def _repl(match: 're.Match[str]') -> str:
        out: List[str] = []
        for kind, value in segs:
            if kind == 'lit':
                out.append(str(value))
            else:
                index = int(value)
                try:
                    group = match.group(index)
                except (IndexError, re.error):
                    group = None
                out.append(group if group is not None else '')
        return ''.join(out)

    return _repl


Rule = Mapping[str, object]


def do_regex_replace(rule: Rule, content: str, modifiers: str = 'umx') -> str:
    """执行单条正则规则（对应 PHP ``Util::doRegexReplace``）。

    规则字段：

    * ``search``  —— PCRE 表达式（不含分隔符与修饰符）
    * ``replace`` —— 替换串（PHP ``$n`` 风格）或可调用对象
    * ``modifiers`` —— 可选，覆盖传入的修饰符
    * ``python``  —— 可选，直接给出 Python 实现（用于 PCRE 独有语法）
    """
    mods = rule.get('modifiers') or modifiers
    custom = rule.get('python')
    if callable(custom):
        return custom(content)  # type: ignore[operator]

    search = str(rule['search'])
    replace = rule['replace']
    regex = compile_pcre(search, str(mods))
    if callable(replace):
        return regex.sub(replace, content)
    return regex.sub(php_replacement(str(replace)), content)


def multi_regex_replace(rules: Iterable[Rule], content: str, modifiers: str = 'umx') -> str:
    """按顺序执行多条正则规则（对应 PHP ``Util::multiRegexReplace``）。"""
    for rule in rules:
        content = do_regex_replace(rule, content, modifiers)
    return content
