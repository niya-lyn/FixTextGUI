"""FixText V1 · EPUB 导入适配层（T2.2）

**复用 M1-T1.3 的 `epubtext` 模块**，本文件只做三件 M1 没做过的事：

1. `chapter_preview()` —— 把 spine 顺序翻译成「第 N 章 · 标题 · 大致字数」的
   只读列表给用户看。给用户的字段**只有**章节标题、序号、字数，
   不出现 spine / OPF / NCX / manifest 等内部概念（验收③）。
2. `order_check()` —— 顺序是否与书里目录一致；不一致时提供"顺序有问题"信号。
3. `merge_to_plain_text()` —— 「先转成 TXT」路径：把各章正文提取成纯文本
   （这条路径不可还原成 EPUB，所以剥标签是有意为之；可还原路径走 M1 的
   `merge_epub`，保留原始 XHTML 以便逐字节还原）。

设计约束：不复制、不重写 M1 的任何合并/还原/校验逻辑；M1 抛的异常在此翻译成人话。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from ._vendor import ensure_vendor_path

ensure_vendor_path()

from epubtext import EpubArchive, merge_epub, parse_package, verify_order_against_ncx  # noqa: E402
from epubtext.errors import EpubTextError  # noqa: E402
from epubtext.package import XHTML_MEDIA_TYPES, looks_like_chapter_title  # noqa: E402

from . import messages  # noqa: E402

CHAPTER_SEPARATOR = "─" * 18

#: 只提取正文用：这些块级元素结束时应断行
BLOCK_TAGS = frozenset({
    "p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "tr", "section", "article", "blockquote", "pre", "hr",
})
#: 完全不取内容的元素
SKIP_TAGS = frozenset({"script", "style", "head"})

_XML_PARSER = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)


class EpubImportError(Exception):
    """EPUB 导入失败（消息已是人话，可直接展示）。"""


@dataclass
class ChapterInfo:
    """给用户看的一章：只有序号、标题、字数三样。"""

    index: int          # 从 1 开始，界面上显示用
    title: str
    chars: int
    named: bool         # 书里是否给了标题


@dataclass
class PreviewResult:
    title: str
    chapters: list[ChapterInfo] = field(default_factory=list)
    order_ok: bool = True
    order_notes: list[str] = field(default_factory=list)
    has_toc: bool = True


def _localname(el) -> str:
    if not isinstance(el.tag, str):
        return ""
    return etree.QName(el).localname.lower()


def xhtml_to_text(data: bytes) -> str:
    """把一章 XHTML 提取成纯文本。

    只做「块级元素断行 + 丢标签」，不重排、不补缩进、不智能合并段落：
    同一章每次提取结果一致（可复现），便于对比和回归。
    """
    try:
        root = etree.fromstring(data, parser=_XML_PARSER)
    except etree.XMLSyntaxError:
        return ""
    if root is None:
        return ""

    out: list[str] = []

    def walk(el) -> None:
        tag = _localname(el)
        if tag in SKIP_TAGS:
            if el.tail:
                out.append(el.tail)
            return
        if el.text:
            out.append(el.text)
        for child in el:
            walk(child)
        if tag in BLOCK_TAGS and out and not out[-1].endswith("\n"):
            out.append("\n")
        if el.tail:
            out.append(el.tail)

    walk(root)

    text = "".join(out).replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in text.split("\n")]
    cleaned: list[str] = []
    for ln in lines:
        if not ln and (not cleaned or cleaned[-1] == ""):
            continue
        cleaned.append(ln)
    return "\n".join(cleaned).strip()


def _open_package(path: Path):
    archive = EpubArchive(path)
    archive.__enter__()
    try:
        broken = archive.test_zip_integrity()
        if broken:
            raise EpubImportError(messages.not_a_book())
        info = parse_package(archive)
    except EpubTextError as exc:
        archive.__exit__(None, None, None)
        raise EpubImportError(messages.not_a_book()) from exc
    except Exception:
        archive.__exit__(None, None, None)
        raise
    return archive, info


def chapter_preview(path: str | Path) -> PreviewResult:
    """读取 EPUB 的章节清单（给用户看的形态）。"""
    path = Path(path)
    try:
        archive, info = _open_package(path)
    except EpubTextError as exc:
        raise EpubImportError(messages.not_a_book()) from exc

    try:
        items = [i for i in info.spine
                 if i.media_type.lower() in XHTML_MEDIA_TYPES and not i.is_nav]
        chapters: list[ChapterInfo] = []
        for idx, item in enumerate(items, start=1):
            raw = archive.read_bytes(item.path)
            label = info.label_for(item.path) or ""
            text = xhtml_to_text(raw)
            chars = len(re.sub(r"\s+", "", text))
            if not label and text:
                first = text.split("\n", 1)[0].strip()
                if looks_like_chapter_title(first):
                    label = first
            title = label
            if not title:
                # 没有任何文字的页不是「未命名章节」：第一页通常是封面（只有图），
                # 其余是分隔页 / 空白插页 —— 标出来，用户才不会以为丢了一章。
                if chars == 0:
                    title = (messages.epub_cover_page() if idx == 1
                             else messages.epub_blank_page())
                else:
                    title = messages.epub_unnamed_chapter()
            chapters.append(ChapterInfo(
                index=idx,
                title=title,
                chars=chars,
                named=bool(label),
            ))
    finally:
        archive.__exit__(None, None, None)

    if not chapters:
        raise EpubImportError(messages.not_a_book())

    ok, notes = verify_order_against_ncx(info)
    return PreviewResult(
        title=info.title or path.stem,
        chapters=chapters,
        order_ok=ok,
        order_notes=list(notes),
        has_toc=bool(info.toc),
    )


def merge_reversible(path: str | Path, out_txt: str | Path):
    """可还原路径：调用 M1 `merge_epub`（保留原始 XHTML + 账本）。"""
    try:
        return merge_epub(path, out_txt)
    except EpubTextError as exc:
        raise EpubImportError(messages.not_a_book()) from exc
    except OSError as exc:
        raise EpubImportError(messages.epub_broken(str(exc))) from exc


def merge_to_plain_text(path: str | Path, out_txt: str | Path) -> tuple[str, int]:
    """「先转成 TXT」路径：逐章提取纯文本，带章节标题与分隔线。

    返回 (文本, 章节数)。这条路径**不可还原**为 EPUB —— 这是它相对
    「直接处理」的取舍：干净、可直接投稿，但不再保留原书版式与插图。
    """
    path, out_txt = Path(path), Path(out_txt)
    try:
        archive, info = _open_package(path)
    except EpubTextError as exc:
        raise EpubImportError(messages.not_a_book()) from exc

    try:
        items = [i for i in info.spine
                 if i.media_type.lower() in XHTML_MEDIA_TYPES and not i.is_nav]
        if not items:
            raise EpubImportError(messages.not_a_book())
        title = info.title or path.stem
        parts: list[str] = [title, "", messages.epub_merged_note(len(items)), ""]
        for idx, item in enumerate(items, start=1):
            label = info.label_for(item.path) or messages.epub_unnamed_chapter()
            body = xhtml_to_text(archive.read_bytes(item.path))
            parts.append(CHAPTER_SEPARATOR)
            parts.append(f"第 {idx} 章 · {label}")
            parts.append(CHAPTER_SEPARATOR)
            parts.append("")
            parts.append(body)
            parts.append("")
    finally:
        archive.__exit__(None, None, None)

    text = "\n".join(parts).replace("\r\n", "\n")
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text(text, encoding="utf-8", newline="\n")
    return text, len(items)
