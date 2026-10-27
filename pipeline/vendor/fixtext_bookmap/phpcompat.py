"""PHP 语义兼容基础函数。

FixText 的上游实现是 PHP，本模块在 Python 中逐条复刻了若干 PHP 特有语义
（字符集 trim、真值判断、strip_tags、PCRE 的 ``^`` 多行行为等），
每一处都在函数 docstring 中标注了对应的上游源码位置。

对应上游源码（FixText/src）：
- app/Util/Util.php            : trimUnicodeChars / changeEncodingAndNewLineType
- app/Service/Diff/Extractor.php: stripHtmlTag
- PHP 官方函数行为              : ltrim / rtrim / trim / strip_tags / preg_replace
"""

from __future__ import annotations

import re

# PHP 默认 trim 字符集：" \t\n\r\0\x0B"
# 见 PHP 手册 trim()：默认字符为 " "、"\t"、"\n"、"\r"、"\0"、"x0B"。
PHP_DEFAULT_TRIM_CHARS = " \t\n\r\x00\x0b"

# 上游 Util::changeEncodingAndNewLineType() 中被移除的不可见字符
_INVISIBLE_RE = re.compile(
    "[\\ufeff\\u200b\\u200c\\u2028-\\u202f\\u205f-\\u206f\\x7f]"
)


def php_ltrim(s: str, chars: str = PHP_DEFAULT_TRIM_CHARS) -> str:
    """等价于 PHP ``ltrim($s, $chars)``。

    PHP 的 trim 系列函数把 ``$chars`` 当作**字符集合**（而非子串），
    反复剥离首部/尾部属于该集合的字符。Python 的 ``str.lstrip`` 语义相同，
    但默认空白集合与 PHP 不同（Python 会剥离 U+00A0 等 Unicode 空白），
    因此这里显式按字符集实现。
    """
    if not s:
        return s
    i = 0
    n = len(s)
    while i < n and s[i] in chars:
        i += 1
    return s[i:]


def php_rtrim(s: str, chars: str = PHP_DEFAULT_TRIM_CHARS) -> str:
    """等价于 PHP ``rtrim($s, $chars)``。"""
    if not s:
        return s
    j = len(s)
    while j > 0 and s[j - 1] in chars:
        j -= 1
    return s[:j]


def php_trim(s: str, chars: str = PHP_DEFAULT_TRIM_CHARS) -> str:
    """等价于 PHP ``trim($s, $chars)``。"""
    return php_rtrim(php_ltrim(s, chars), chars)


def php_truthy(value) -> bool:
    """等价于 PHP 的布尔真值判断。

    PHP 中 ``""``、``"0"``、``0``、``0.0``、``false``、``null``、空数组均为假值。
    上游 ``genDiffWordsMap`` 中的 ``if (!$before || !$after) continue;``
    因此会丢弃取值恰好为字符串 ``"0"`` 的词条——这一行为在此显式复刻。
    """
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return value not in ("", "0")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True


def trim_unicode_chars(
    s: str, chars_to_trim: str = " \n\r\t\v\0", direction: str = "both"
) -> str:
    """等价于上游 ``App\\Util\\Util::trimUnicodeChars()``。

    上游使用 ``/u`` 正则按 Unicode 字符处理，可正确裁剪全角空格（U+3000）等
    非 ASCII 空白；PHP 原生 trim 是按字节处理，无法裁剪多字节空白，
    因此上游才有这个 Unicode 版实现。
    """
    if s == "" or chars_to_trim == "":
        return s

    escaped = re.escape(chars_to_trim)
    if direction == "left":
        pattern = rf"^[{escaped}]+"
    elif direction == "right":
        pattern = rf"[{escaped}]+$"
    elif direction == "both":
        pattern = rf"^[{escaped}]+|[{escaped}]+$"
    else:
        return s

    return re.sub(pattern, "", s)


def change_encoding_and_new_line_type(content: str) -> str:
    """等价于上游 ``Util::changeEncodingAndNewLineType()``（仅保留 UTF-8 路径）。

    上游在转 UTF-8 之后会：
    1. 把 CRLF / CR 统一成 LF；
    2. 删除 BOM、零宽字符、部分不可见控制字符。

    编码检测与转码（GB18030 / UTF-16 等）由上游 ``convertEncoding()`` 完成，
    本模块只接受 UTF-8 输入；非法字节以 surrogateescape 保留。
    """
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    return _INVISIBLE_RE.sub("", content)


_PHP_TAG_WS = " \t\r\n\v\f"


def _skip_html_comment(s: str, i: int) -> int:
    """跳过从 ``s[i]`` 开始的 ``<!-- ... -->`` 注释，返回注释后的位置。

    前提：``s[i:i+4] == "<!--"``。PHP 规则（实测）：
    - ``<!-->`` 与 ``<!--->`` 本身是完整注释；
    - 其余以字面 ``-->`` 结束（``--!>`` 不算结束）；
    - 未闭合则吞到字符串结尾。
    """
    end = len(s)
    if s[i + 4 : i + 5] == ">":
        return i + 5
    if s[i + 4 : i + 6] == "->":
        return i + 6
    j = s.find("-->", i + 4)
    return j + 3 if j != -1 else end


def _skip_pi(s: str, i: int) -> int:
    """跳过 ``<? ... ?>`` 处理指令，``i`` 指向 ``?``，返回其后的位置。

    PHP 规则（实测）：以字面 ``?>`` 结束（裸 ``>`` 不结束，
    例：``'<?php x > y?>z'`` → ``"z"``）；未闭合吞到串尾。
    """
    end = len(s)
    j = s.find("?>", i + 1)
    return j + 2 if j != -1 else end


def php_strip_tags(s: str) -> str:
    """等价于 PHP 的 ``strip_tags()``（PHP 8.5，行为经 130+ 条探针实测对齐）。

    状态机（深度 depth：0 = 纯文本 PLAIN；≥1 = 标签 TAG；emit = 注释后
    的输出模式，即「状态 E」；quote = 引号态）：

    纯文本态（depth == 0）：

    - ``<`` 后跟**空白**（空格/\\t/\\r/\\n/\\v/\\f）→ ``<`` 字面输出；
    - ``<`` 后跟其他任意字符 → 进入标签（深度 1）。数字/``.``/``-``/``:``/
      ``"``/CJK 等都算（例：``"<3 个苹果>不是标签"`` → ``"不是标签"``）；
    - ``<!--`` → 注释（见 :func:`_skip_html_comment`）；
    - ``<?`` → 处理指令，以字面 ``?>`` 结束（见 :func:`_skip_pi`）；
    - 末尾孤立 ``<`` 丢弃（``"尾<"`` → ``"尾"``）；
    - ``<!`` 非注释按普通标签处理（引号保护生效，
      ``'<!DOCTYPE "a>b">x'`` → ``"x"``）。

    标签态（depth ≥ 1，普通跳过模式）：

    - ``>`` → 深度减 1，减到 0 回纯文本；
    - ``<`` → 深度加 1（例：``"<<a>>x"`` → ``"x"``、``"<<<x>>>y"`` → ``"y"``）；
    - ``<`` 后紧跟 ``<!--`` → 注释跳过后进入**状态 E**：深度不变、
      切输出模式（``'<a<x<!--b-->>c>y'`` → ``"cy"``、
      ``'<a<x<!--b-->q>r'`` → ``"qr"``、``'<a<!--b-->c>d'`` → ``"cd"``）；
    - ``<`` 后紧跟 ``?`` → PI 跳过后**深度加 1**（``'<a<?b?>c>d'`` → ``""``）；
    - ``"``/``'`` 在跳过模式**任意深度**都触发引号保护（Model B）：
      进入引号态记住当前深度；
    - 其余字符跳过。

    状态 E（TAG + emit，注释后的输出模式）：

    - 字符照常输出（``'<a<!--b-->c>d'`` → ``"cd"``）；
    - ``>`` 仍是深度减 1（d2 时 ``'…<x<!--b-->>c>y'`` → ``"cy"``，减到
      0 回纯文本）；
    - 嵌套 ``<``（含 ``<!`` 非注释、``<?`` PI）终止输出模式回到普通跳过
      （``'<a<!--b-->c<x>>y'`` → ``"cy"``、``'<a<!--b--><?x?>y>z'`` →
      ``""``）；
    - E 中的 ``<!--`` 仍是注释且**保持 E**（``'<a<!--b--><!--c-->d'`` →
      ``"d"``）；
    - E 中引号**不**触发引号保护，按字面输出
      （``'<a<!--b-->x="q>z">w'`` → ``'x="qz">w'``：首个 ``>`` 深度减 1
      后被吞，其余原样）。

    引号态（quote，从跳过模式的 TAG 进入）：

    - 同字符引号关闭引号，回到 TAG 跳过模式（当前深度），**可再开新
      引号**（``'<a<x="q>z"p="r">w'`` → ``"w"``）；
    - ``>`` 在引号内**仅当前深度 ≥ 2 时**深度减 1（按**当前**深度判断，
      引号内多次 ``>`` 逐次递减：``'<a<x="q>z>y">w'`` → ``"w"``；
      深度 1 时 ``>`` 不减：``'<a x="1>2">z'`` → ``"z"``）；
    - ``<`` 不增加深度（``'<a x="<b>">y'`` → ``"y"``）；
    - ``<!--`` 在引号内仍触发注释，注释后**放弃引号**回到 TAG 跳过
      模式（``'<a x="<!--c-->" >y'`` → ``""``）；
    - 未闭合吞到串尾。
    """
    out = []
    end = len(s)
    i = 0
    depth = 0  # 0 = 纯文本；>=1 = 标签嵌套深度
    emit = False  # 状态 E：注释后的输出模式（仅在 TAG 内有意义）
    quote = None  # 当前引号字符；None = 不在引号态

    while i < end:
        ch = s[i]

        if quote is not None:
            # 引号态
            if ch == quote:
                quote = None
                i += 1
                continue
            if ch == "<" and s[i + 1 : i + 2] == "!" and s[i + 2 : i + 4] == "--":
                # 引号内注释：吞注释、放弃引号、回 TAG 跳过模式
                i = _skip_html_comment(s, i)
                quote = None
                emit = False
                continue
            if ch == ">" and depth >= 2:
                depth -= 1
            i += 1
            continue

        if depth == 0:
            if ch != "<":
                out.append(ch)
                i += 1
                continue
            if i + 1 >= end:
                # 末尾孤立 '<'：丢弃
                i += 1
                continue
            nxt = s[i + 1]
            if nxt in _PHP_TAG_WS:
                out.append(ch)
                i += 1
                continue
            if nxt == "!" and s[i + 2 : i + 4] == "--":
                i = _skip_html_comment(s, i)
                continue
            if nxt == "?":
                i = _skip_pi(s, i + 1)
                continue
            depth = 1
            emit = False
            i += 1
            continue

        # depth >= 1：标签内部（跳过模式或 E 输出模式）
        if ch == ">":
            depth -= 1
            if depth == 0:
                emit = False
            i += 1
            continue
        if ch == "<":
            nxt = s[i + 1] if i + 1 < end else ""
            if nxt == "!" and s[i + 2 : i + 4] == "--":
                # 注释：深度不变，进入/保持 E 输出模式
                i = _skip_html_comment(s, i)
                emit = True
                continue
            if nxt == "?":
                i = _skip_pi(s, i + 1)
                depth += 1
                emit = False
                continue
            depth += 1
            emit = False
            i += 1
            continue
        if (ch == '"' or ch == "'") and not emit:
            # 跳过模式下任意深度都触发引号保护；E 中引号按字面输出
            quote = ch
            i += 1
            continue
        if emit:
            out.append(ch)
        i += 1

    return "".join(out)


def php_preg_replace_multiline_start(s: str, repl: str = "    ") -> str:
    """等价于 PHP ``preg_replace('/^/m', $repl, $s)``。

    PCRE 的 ``/m`` 下 ``^`` 匹配「字符串开头」以及「每个 ``\\n`` 之后、
    且其后仍有字符」的位置。经 PHP 8.5 实测（含 11 条边界向量）：

    - 空字符串也匹配串首，结果为 ``repl`` 本身；
    - **末尾换行之后不再插入**（``"行一\\n"`` → ``"    行一\\n"``）；
    - 连续换行逐行插入（``"a\\n\\nb"`` → ``"    a\\n    \\n    b"``）。

    注意 Python 的 ``re.sub(r"^", repl, s, flags=re.M)`` 对空串返回空串，
    与 PHP 返回 ``repl`` 不同，因此这里显式实现。
    """
    if s == "":
        return repl

    out = [repl]
    last = len(s) - 1
    for idx, ch in enumerate(s):
        out.append(ch)
        # 仅在换行之后仍有字符时才插入前缀
        if ch == "\n" and idx < last:
            out.append(repl)
    return "".join(out)


def mb_str_split(s: str) -> list:
    """等价于 ``mb_str_split($s)``（UTF-8，按码点切分）。"""
    return list(s)


def mb_substr(s: str, start: int, length: int | None = None) -> str:
    """等价于 ``mb_substr($s, $start, $length)``。"""
    if length is None:
        return s[start:]
    if length < 0:
        raise ValueError("mb_substr length must not be negative")
    return s[start:start + length]


def mb_strlen(s: str) -> int:
    """等价于 ``mb_strlen($s)``（按码点计数）。"""
    return len(s)
