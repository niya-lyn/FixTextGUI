"""段落提取：把导入后的书正文切成「可定位的段落序列」（V1.1-E6 交付物①的输入层）。

输入是**导入后的工作正文**（D1/T2.2 的产物口径）：

* EPUB 书 → ``book.txt`` 是 ``epubtext.merge`` 的可逆合并文本：头部一行
  ``<!-- EPUBTEXT-BUNDLE ... -->``、每本书一行 ``<!-- EPUBTEXT-BOOK ... -->``、
  每章一行 ``<!-- EPUBTEXT-SPLIT:nonce:index path=... label=... chars=... sha=... -->``，
  章正文是原始 XHTML（含 ``<p>``、``<h2 class="chap-title">`` 等）。
* TXT 书 → ``book.txt`` 是规整后的纯文本（UTF-8 / LF），没有章节标记。

两条口径都由本模块吸收，**输出是同一种结构**：``ParagraphRef`` 序列。
章节标记的识别规则直接复用 ``epubtext.bundle`` 的 ``HEADER_RE`` / ``SPLIT_RE``
（与 ``split_bundle`` / ``ChapterMap`` 同一套正则）；环境里取不到 ``epubtext``
时退回本模块内的同款正则副本，解析结果一致（有测试锁这条等价性）。

段落切分规则（**排版无关**，因此同一本书每次切分结果一致）：

1. EPUB 章：只在 ``<body>`` 内部切（``<head>``、``<script>``、``<style>`` 一律不看
   ——否则 ``<title>`` 会被当成段落）。有 ``<p>`` 时按 ``<p>`` 元素切；
   没有 ``<p>`` 的章退回「按非空行切」。
2. TXT：如果空行占据足够比例（默认 >15%），按空行分块（块内多行合并成一段，
   行区间跨多行）；否则逐行成段。这覆盖了「硬换行 + 空行分段」和「一行一段」
   两种常见写书方式。

每个段落都带**两种口径**：``text`` 是给人看 / 给比对用的可读文本（标签已去、
空白已压缩），``char_start`` / ``char_end`` 与 ``line_start`` / ``line_end`` 指向
原文区间（含标签本身），供 E7 高亮选中与跳转定位。
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable

from .model import ParagraphRef
from .similarity import normalize

# ---------------------------------------------------------------------------
# 章节标记（优先复用 epubtext.bundle，取不到则用本地同款副本）
# ---------------------------------------------------------------------------

_HEADER_RE_LOCAL = re.compile(
    r"^<!--\s*EPUBTEXT-BUNDLE\s+(?P<body>.*?)\s*-->\s*$", re.IGNORECASE)
_SPLIT_RE_LOCAL = re.compile(
    r"^<!--\s*EPUBTEXT-SPLIT:(?P<nonce>[0-9a-f]{8,32}):(?P<index>\d+)\s+(?P<body>.*?)\s*-->\s*$",
    re.IGNORECASE)
_BOOK_RE_LOCAL = re.compile(
    r"^<!--\s*EPUBTEXT-BOOK:(?P<nonce>[0-9a-f]{8,32}):(?P<index>\d+)\s+(?P<body>.*?)\s*-->\s*$",
    re.IGNORECASE)
_ATTR_RE_LOCAL = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")


@lru_cache(maxsize=1)
def _bundle_regexes():
    """取章节标记正则：优先 ``epubtext.bundle``，退回本地副本。

    返回 ``(header_re, split_re, book_re, parse_attrs, 来源名)``。
    ``来源名`` 只为测试断言「两套正则等价或明确走了哪条」。

    结果缓存：``import`` 本身不便宜，而这份正则在一次切段里会被问很多次。
    """
    try:                                              # pragma: no cover - 环境相关
        from epubtext.bundle import (BOOK_RE, HEADER_RE, SPLIT_RE,
                                     parse_attrs)
        return HEADER_RE, SPLIT_RE, BOOK_RE, parse_attrs, "epubtext.bundle"
    except Exception:
        def _parse_attrs(body: str) -> dict[str, str]:
            return dict(_ATTR_RE_LOCAL.findall(body or ""))

        return (_HEADER_RE_LOCAL, _SPLIT_RE_LOCAL, _BOOK_RE_LOCAL,
                _parse_attrs, "local")


def has_bundle_header(text: str) -> bool:
    """这份正文是不是可逆合并的 EPUB 文本（看首行有没有 BUNDLE 头部）。"""
    if not text:
        return False
    header_re = _bundle_regexes()[0]
    for line in text.split("\n", 6)[:6]:
        if header_re.match(line.rstrip("\r")):
            return True
    return False


# ---------------------------------------------------------------------------
# 段落切分正则
# ---------------------------------------------------------------------------

#: ``<body ...>`` 的起止（用来把 ``<head>`` 排除在外）
_BODY_OPEN_RE = re.compile(r"<body(?:\s[^>]*)?>", re.IGNORECASE)
_BODY_CLOSE_RE = re.compile(r"</body\s*>", re.IGNORECASE)
#: 整块丢弃的元素（含内容）
_DROP_BLOCK_RE = re.compile(
    r"<(script|style|head)(?:\s[^>]*)?>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
#: ``<p ...>...</p>``；``.*?`` + DOTALL 让跨行的段落也能整段取到
_P_RE = re.compile(r"<p(?:\s[^>]*)?>(.*?)</p\s*>", re.IGNORECASE | re.DOTALL)
#: ``<h1>``–``<h6>``；``(?:\s[^>]*)?`` 吸收 class 等属性
_H_RE = re.compile(r"<(h[1-6])(?:\s[^>]*)?>(.*?)</\1\s*>", re.IGNORECASE | re.DOTALL)
#: 章标题的内联标记（与 ``fixtext_diff_view`` 的 chap-title 口径一致）
_CHAP_TITLE_RE = re.compile(
    r"<[^>]*class=[\"'][^\"']*chap-title[^\"']*[\"'][^>]*>(?P<body>.*?)</", re.DOTALL)
_TAG_ONLY_RE = re.compile(r"^\s*(?:<[^>]{0,200}>\s*)+$")
_TAG_RE = re.compile(r"<[^>]{0,200}>")

#: TXT 里「空行占多大比例」才按空行分块
BLANK_BLOCK_RATIO = 0.15


def _decode_label(value: str) -> str:
    """章节标记里的 label 是百分号编码（``epubtext`` 用 ``quote()`` 写入）。"""
    if not value:
        return ""
    try:
        from urllib.parse import unquote
        return unquote(value)
    except Exception:                                  # pragma: no cover
        return value


def clean_text(raw: str) -> str:
    """段落原文 → 可读文本：去标签、把空白序列压成一个空格、去首尾空白。

    压缩而不是全删，是为了让 ``text`` 还能被人读（清单里直接展示）；
    比对用的「去全部空白」形态由 ``similarity.normalize`` 负责，两者分工明确。
    """
    out = _TAG_RE.sub("", raw or "")
    if "&" in out:
        out = (out.replace("&nbsp;", " ").replace("&lt;", "<")
                   .replace("&gt;", ">").replace("&quot;", '"')
                   .replace("&apos;", "'").replace("&amp;", "&"))
    return re.sub(r"[\s\u3000\xa0]+", " ", out).strip()


class _LineIndex:
    """字符偏移 ↔ 行号（1 起）的换算。"""

    def __init__(self, text: str) -> None:
        self.starts: list[int] = [0]
        pos = text.find("\n")
        while pos != -1:
            self.starts.append(pos + 1)
            pos = text.find("\n", pos + 1)
        self.total = len(self.starts)

    def line_of(self, offset: int) -> int:
        """字符偏移落在第几行（1 起）。"""
        if offset < 0:
            return 1
        pos = bisect_right(self.starts, offset) - 1
        return max(1, min(self.total, pos + 1))


@dataclass
class ChapterSpan:
    """一章在正文里的位置。"""

    index: int                 # 0 起
    label: str
    path: str
    line_start: int            # 标记行之后的第一行（1 起）
    line_end: int              # 下一标记行之前（闭区间）
    char_start: int
    char_end: int
    title: str = ""

    def to_dict(self) -> dict:
        return {
            "index": self.index, "label": self.label, "path": self.path,
            "title": self.title, "line_start": self.line_start,
            "line_end": self.line_end, "char_start": self.char_start,
            "char_end": self.char_end,
        }


@dataclass
class ExtractResult:
    paragraphs: list[ParagraphRef] = field(default_factory=list)
    chapters: list[ChapterSpan] = field(default_factory=list)
    kind: str = "plain"          # "epub" | "plain"

    @property
    def chapter_count(self) -> int:
        return len(self.chapters)

    def by_index(self, index: int) -> ParagraphRef | None:
        if 0 <= index < len(self.paragraphs):
            return self.paragraphs[index]
        return None


# ---------------------------------------------------------------------------
# 章节定位
# ---------------------------------------------------------------------------

def _chapters(text: str) -> list[ChapterSpan]:
    """按 SPLIT 标记切出每章的行/字符区间（不做账本三方校验：这里只做定位）。"""
    split_re = _bundle_regexes()[1]
    parse_attrs = _bundle_regexes()[3]
    lines = text.split("\n")
    index = _LineIndex(text)

    marker_lines: list[tuple[int, dict[str, str]]] = []
    for lineno, line in enumerate(lines, start=1):
        m = split_re.match(line.rstrip("\r"))
        if m is not None:
            attrs = parse_attrs(m.group("body"))
            attrs["index"] = m.group("index")
            marker_lines.append((lineno, attrs))
    if not marker_lines:
        return []

    spans: list[ChapterSpan] = []
    for pos, (lineno, attrs) in enumerate(marker_lines):
        next_line = marker_lines[pos + 1][0] if pos + 1 < len(marker_lines) else len(lines) + 1
        body_start_line = lineno + 1
        body_end_line = max(body_start_line, next_line - 1)
        char_start = (index.starts[body_start_line - 1]
                      if body_start_line - 1 < len(index.starts) else len(text))
        char_end = (index.starts[body_end_line]
                    if body_end_line < len(index.starts) else len(text))
        spans.append(ChapterSpan(
            index=pos,
            label=_decode_label(attrs.get("label", "")),
            path=attrs.get("path", ""),
            line_start=body_start_line,
            line_end=body_end_line,
            char_start=min(char_start, char_end),
            char_end=max(char_start, char_end),
        ))
    return spans


def _body_region(body: str) -> tuple[int, int, str]:
    """章正文里 ``<body>`` 的内部区间；没有 ``<body>`` 时退回整章（先丢掉 head）。"""
    m = _BODY_OPEN_RE.search(body)
    if m is not None:
        close = _BODY_CLOSE_RE.search(body, m.end())
        end = close.start() if close is not None else len(body)
        return m.end(), max(m.end(), end), body[m.end():end]
    stripped = _DROP_BLOCK_RE.sub("", body)
    # 丢 head 之后偏移会变，退回整章时不做偏移修正（这种书极少见，取整章也安全）
    return 0, len(body), stripped


def _chapter_title(body: str, label: str) -> str:
    """章标题：优先章内 ``class="chap-title"`` 的标题，取不到退回标记 label。"""
    m = _CHAP_TITLE_RE.search(body)
    if m is not None:
        title = clean_text(m.group("body") or "")
        if title:
            return title
    return label


# ---------------------------------------------------------------------------
# 段落切分
# ---------------------------------------------------------------------------

def _spans_in(region: str, base_offset: int) -> list[tuple[int, int, str, str]]:
    """章正文里的段落 span：``(开始偏移, 结束偏移, 原文片段, 类别)``。

    偏移是**相对整份正文**的（``base_offset`` 加上章内偏移），因此与
    ``line_start`` / ``char_start`` 口径完全一致：同一段既算得出行号也算得出
    字符区间，两个值指向同一处原文。
    """
    found: list[tuple[int, int, str, str]] = []
    for m in _P_RE.finditer(region):
        found.append((base_offset + m.start(), base_offset + m.end(), m.group(0), "paragraph"))
    for m in _H_RE.finditer(region):
        found.append((base_offset + m.start(), base_offset + m.end(), m.group(0), "heading"))
    found.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    # 重叠区间只留外层：``<h2>`` 里套 ``<p>``（标题排版）时不要重复计两次
    kept: list[tuple[int, int, str, str]] = []
    for item in found:
        if kept and item[0] < kept[-1][1]:
            continue
        kept.append(item)
    return kept


def _line_paragraphs(text: str, lines: list[str], index: _LineIndex,
                     line_from: int, line_to: int,
                     blank_block: bool) -> list[tuple[int, int, str, int, int]]:
    """按行/空行分块切段：``(char_start, char_end, 原文, line_start, line_end)``。"""
    out: list[tuple[int, int, str, int, int]] = []
    block_start: int | None = None
    block_lines: list[str] = []

    def flush() -> None:
        nonlocal block_start, block_lines
        if block_start is None or not block_lines:
            block_start, block_lines = None, []
            return
        body = "\n".join(block_lines)
        cs = index.starts[block_start - 1]
        out.append((cs, cs + len(body), body, block_start,
                    block_start + len(block_lines) - 1))
        block_start, block_lines = None, []

    for lineno in range(line_from, min(line_to, len(lines)) + 1):
        raw = lines[lineno - 1].rstrip("\r")
        stripped = raw.strip()
        # 纯标签行（``<html>``、``</body>``、``<?xml?>``）不算正文
        if not stripped or _TAG_ONLY_RE.match(stripped):
            flush()
            continue
        if blank_block:
            if block_start is None:
                block_start = lineno
            block_lines.append(raw)
        else:
            cs = index.starts[lineno - 1]
            out.append((cs, cs + len(raw), raw, lineno, lineno))
    flush()
    return out


def extract_paragraphs(text: str, *, include_headings: bool = False,
                       min_chars: int = 0) -> ExtractResult:
    """把一份工作正文切成可定位的段落序列。

    :param include_headings: 是否把 ``<h1>``–``<h6>`` 也算作段落。默认不算——
        章标题重复属于「重复章节名」，与正文段落重复是两种问题。
    :param min_chars: 小于这个字数的段直接丢掉（0 = 全留，交给检测阶段按
        ``min_chars`` 过滤）。丢在这里能让 E7 的清单序号更稳定。
    """
    text = text or ""
    result = ExtractResult(kind="epub" if has_bundle_header(text) else "plain")
    lines = text.split("\n")
    index = _LineIndex(text)
    chapters = _chapters(text)

    def push(raw: str, cs: int, ce: int, first: int, last: int,
             ch_index: int, ch_no: int, title: str, label: str, source: str) -> None:
        readable = clean_text(raw)
        if not readable:
            return
        if min_chars and len(normalize(readable)) < min_chars:
            return
        result.paragraphs.append(ParagraphRef(
            index=len(result.paragraphs),
            text=readable,
            line_start=first,
            line_end=last,
            char_start=cs,
            char_end=ce,
            chapter_index=ch_index,
            chapter_no=ch_no,
            chapter_title=title,
            chapter_label=label,
            source=source,
        ))

    if chapters:
        for span in chapters:
            body = text[span.char_start:span.char_end]
            span.title = _chapter_title(body, span.label)
            start, end, region = _body_region(body)
            base = span.char_start + start
            if _P_RE.search(region):
                for cs, ce, raw, kind in _spans_in(region, base):
                    if kind == "heading" and not include_headings:
                        continue
                    push(raw, cs, ce, index.line_of(cs), index.line_of(max(cs, ce - 1)),
                         span.index, span.index + 1, span.title, span.label, kind)
            else:
                for cs, ce, raw, first, last in _line_paragraphs(
                        text, lines, index, span.line_start, span.line_end,
                        blank_block=False):
                    push(raw, cs, ce, first, last, span.index, span.index + 1,
                         span.title, span.label, "line")
        result.chapters = chapters
        return result

    # 纯文本：按空行比例决定「空行分块」还是「逐行成段」
    # 尾随空行（文件末尾的换行）不该进比例分母：三行的短文本带一个结尾换行
    # 就被算成 25% 空行、整篇并成一段，实测踩过。因此先剔掉末尾空行再统计。
    total = len(lines)
    while total > 0 and not lines[total - 1].strip():
        total -= 1
    blanks = sum(1 for ln in lines[:total] if not ln.strip())
    blank_block = (total > 0 and blanks >= 2
                   and (blanks / total) > BLANK_BLOCK_RATIO)
    for cs, ce, raw, first, last in _line_paragraphs(
            text, lines, index, 1, total, blank_block):
        push(raw, cs, ce, first, last, -1, -1, "", "",
             "block" if blank_block else "line")
    return result


def extract_from_file(path: str, *, include_headings: bool = False,
                      min_chars: int = 0) -> ExtractResult:
    """从 ``book.txt`` 读正文并切段（**只读**，不改文件）。"""
    from pathlib import Path

    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return extract_paragraphs(text, include_headings=include_headings,
                              min_chars=min_chars)


def iter_long_paragraphs(paragraphs: Iterable[ParagraphRef],
                         min_chars: int) -> Iterable[ParagraphRef]:
    """过滤出够长的段落（比对面用）。"""
    for p in paragraphs:
        if len(normalize(p.text)) >= min_chars:
            yield p
