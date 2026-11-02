#!/usr/bin/env python3
"""合成测试用的多章 EPUB 样本（**公版书**，无版权风险）。

为什么有这支脚本
================
仓库曾经内置过一本**盗版站来源的完整网文**当测试样本（OPF 里出现了盗版站点
的 publisher / subject 字段），它不能随开源仓库一起公开。开源前已经把它移除，
所有依赖它的用例改为依赖一份**公有领域**的样本。这份样本由本脚本当场合成，
**不落原文进仓库**：

* 原文：``聊齋志異``（蒲松齡，清代），取自 Project Gutenberg 电子书 **#51828**
  （https://www.gutenberg.org/ebooks/51828），**公有领域（Public Domain）**；
  Gutenberg 页面语言标注 Chinese，正文按「卷」+「〈篇名〉」分篇。
* 用法：先在本地准备好这份 Gutenberg TXT（不下载到仓库、也不从外网抓），
  然后

      python3.12 tools/build_fixture_epub.py \
          --source /path/to/pg51828_liaozhai.txt \
          --output tests/samples/book_public_domain.epub \
          --chapters 300

  脚本只用标准库 + 包里自带的 ``vendor/epubtext``（写包的 ZIP 规范由它负责：
  ``mimetype`` 必须是首个条目且不压缩）。

章节怎么切
==========
Gutenberg 那本书的正文用一行一个 ``〈篇名〉`` 作为每篇的开头，另有 ``卷一``
「卷二」…这类卷标题。本脚本**按篇切**：以 ``〈…〉`` 行作为章节起点、到下一个
``〈…〉`` 行为止，因此：

* 一篇一章，章标题就是篇名（如「考城隍」），与阅读顺序严格一致；
* 章节数 = 取的篇数，默认 300 篇（原书 497 篇，取前 300 篇 ≈ 29 万汉字）；
* 只取正文，不取 Gutenberg 的页头 / 页脚（那两个 ``*** START/END ***`` 标记之间
  只保留有正文的部分），页头里的版权声明不会进 fixture。

为什么 300 篇够用
=================
现有用例对样本的要求是「章数量级够大、正文够长、替换与引号检查都有活儿干」：

* 章节数 300 > 全套用例里最高的「> 100 章」门槛（``test_import`` 的章节预览）；
* 正文约 29 万汉字，替换阶段能命中 3 万处上下、引号检查能报几十处——
  两项都不是空跑；
* 合成后的包约 1 MB 级，pytest 全量跑不会被样本体积拖慢。

它**不是**为了让数字接近原书——任何「788 章 / 108 处」这类具体数字都不该
写进测试（那是旧样本的指纹，不是产品行为）。

输出包结构
==========
沿用最小合规结构（与真实电子书一致，能被 ``epubtext`` 正常解析）：

    mimetype                     （首个条目、STORED）
    META-INF/container.xml
    OEBPS/content.opf            （EPUB 2.0，manifest + spine + DC 元数据）
    OEBPS/toc.ncx                （目录，标题与章节一一对应）
    OEBPS/stylesheet.css
    OEBPS/titlepage.xhtml        （封面页，无正文文字）
    OEBPS/chapter001.xhtml …     （逐章正文）
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG / "vendor"))

from epubtext import FileEntry, write_epub  # noqa: E402

#: fixture 的书名与作者——公版书原信息，不含任何平台/站点字样
BOOK_TITLE = "聊齋志異（公有領域選篇）"
BOOK_AUTHOR = "蒲松齡"

#: 原文出处（写进 OPF 的 dc:source，便于后续核查）
BOOK_SOURCE = "Project Gutenberg eBook #51828（https://www.gutenberg.org/ebooks/51828）"

START_RE = re.compile(r"\*\*\*\s*START OF.*?\*\*\*", re.S)
END_RE = re.compile(r"\*\*\*\s*END OF.*?\*\*\*", re.S)
#: 篇名行：〈考城隍〉 / 〈耳中人〉 …（篇名不超过 20 字，避免误吞引用句）
PIAN_RE = re.compile(r"〈[^〈〉\n]{1,20}〉")
#: 卷标题行（卷一 / 卷二 …），合成时丢弃（篇名已是章节边界）
JUAN_RE = re.compile(r"^卷[一二三四五六七八九十]+$")


def _gutenberg_body(raw: str) -> str:
    """裁掉 Gutenberg 的页头 / 页脚，只留正文。"""
    start = START_RE.search(raw)
    end = END_RE.search(raw)
    if not start or not end:
        raise SystemExit(
            "输入文件不像 Project Gutenberg 的 TXT：找不到 "
            "*** START/END OF THE PROJECT GUTENBERG EBOOK ... *** 标记。\n"
            "请确认 --source 指向 gutenberg.org 下载的 .txt（UTF-8）。"
        )
    return raw[start.end():end.start()]


def split_chapters(body: str, wanted: int) -> list[tuple[str, str]]:
    """按 ``〈篇名〉`` 切篇，返回 ``[(篇名, 正文)]``，最多 ``wanted`` 篇。

    第一个 ``〈…〉`` 之前的文字（通常是卷标题与空行）不属于任何一篇，丢弃。
    """
    marks = list(PIAN_RE.finditer(body))
    if not marks:
        raise SystemExit("正文里没有找到任何 〈篇名〉 标记，无法切篇。")

    chapters: list[tuple[str, str]] = []
    for idx, mark in enumerate(marks):
        title = mark.group().strip("〈〉").strip()
        begin = mark.end()
        end = marks[idx + 1].start() if idx + 1 < len(marks) else len(body)
        text = body[begin:end]
        # 每行去首尾空白；丢弃空行与卷标题行（「卷一」之类属卷结构，不是正文）
        lines = [ln.strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if ln and not JUAN_RE.match(ln)]
        if not lines:
            continue                       # 空篇不占章节位（宁可少一章也不造空章）
        chapters.append((title, "\n".join(lines)))
        if len(chapters) >= wanted:
            break

    if len(chapters) < wanted:
        raise SystemExit(
            f"只切出 {len(chapters)} 篇，少于要求的 {wanted} 篇："
            "请换一份篇数更多的 Gutenberg 公版书，或调小 --chapters。"
        )
    return chapters


def _chapter_xhtml(index: int, title: str, text: str) -> bytes:
    paragraphs = "\n".join(f"    <p>{escape(ln)}</p>" for ln in text.splitlines())
    return f"""<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
  <head>
    <title>{escape(title)}</title>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
    <link href="stylesheet.css" rel="stylesheet" type="text/css"/>
  </head>
  <body>
    <h2 class="chap-title">{escape(title)}</h2>
{paragraphs}
  </body>
</html>
""".encode("utf-8")


def _titlepage_xhtml() -> bytes:
    """封面页：只有书名（在 ``<head><title>``），``<body>`` 里不放正文文字。

    真实电子书的封面页就是一张图、没有可读正文，``<body>`` 空着；合并时会因此
    得到一页零字的章节，导入预览把它标成「封面」——这正是产品对该类页面的既有
    处理，样本要覆盖它，而不是绕开它。
    """
    return f"""<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
  <head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
    <title>{escape(BOOK_TITLE)}</title>
    <link href="stylesheet.css" rel="stylesheet" type="text/css"/>
  </head>
  <body class="cover">
  </body>
</html>
""".encode("utf-8")


def _stylesheet() -> bytes:
    return """body { margin: 0 5pt; font-size: 1em; }
.cover { text-align: center; padding-top: 30%; }
h1 { font-size: 1.6em; }
h2.chap-title { font-size: 1.125em; margin: 1em 0; }
.author { font-size: 1.05em; }
p { line-height: 1.4; text-indent: 2em; margin: 0.35em 0; }
""".encode("utf-8")


def _container_xml() -> bytes:
    return b"""<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _opf(chapters: list[tuple[str, str]]) -> bytes:
    manifest = [
        '    <item id="titlepage" href="titlepage.xhtml" media-type="application/xhtml+xml"/>',
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '    <item id="css" href="stylesheet.css" media-type="text/css"/>',
    ]
    spine = ['    <itemref idref="titlepage"/>']
    for i in range(len(chapters)):
        name = f"chapter{i + 1:03d}"
        manifest.append(
            f'    <item id="{name}" href="{name}.xhtml" media-type="application/xhtml+xml"/>')
        spine.append(f'    <itemref idref="{name}"/>')
    return f"""<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{escape(BOOK_TITLE)}</dc:title>
    <dc:creator opf:role="aut">{escape(BOOK_AUTHOR)}</dc:creator>
    <dc:language>zh</dc:language>
    <dc:identifier id="bookid" opf:scheme="URI">{escape(BOOK_SOURCE)}</dc:identifier>
    <dc:source>{escape(BOOK_SOURCE)}</dc:source>
    <dc:rights>Public Domain</dc:rights>
  </metadata>
  <manifest>
{chr(10).join(manifest)}
  </manifest>
  <spine toc="ncx">
{chr(10).join(spine)}
  </spine>
</package>
""".encode("utf-8")


def _ncx(chapters: list[tuple[str, str]]) -> bytes:
    points = []
    for i, (title, _text) in enumerate(chapters):
        name = f"chapter{i + 1:03d}"
        points.append(f"""    <navPoint id="navPoint-{i + 1}" playOrder="{i + 1}">
      <navLabel>
        <text>{escape(title)}</text>
      </navLabel>
      <content src="{name}.xhtml"/>
    </navPoint>""")
    return f"""<?xml version='1.0' encoding='utf-8'?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta content="fixture-public-domain" name="dtb:uid"/>
    <meta content="1" name="dtb:depth"/>
    <meta content="0" name="dtb:totalPageCount"/>
    <meta content="0" name="dtb:maxPageNumber"/>
  </head>
  <docTitle>
    <text>{escape(BOOK_TITLE)}</text>
  </docTitle>
  <navMap>
{chr(10).join(points)}
  </navMap>
</ncx>
""".encode("utf-8")


def build(source: Path, output: Path, wanted: int = 300) -> dict:
    """合成 fixture，返回一份给人工看的统计。"""
    try:
        raw = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"{source} 不是 UTF-8 文本：{exc}") from exc

    body = _gutenberg_body(raw)
    chapters = split_chapters(body, wanted)

    entries = [
        FileEntry(name="mimetype", data=b"application/epub+zip", compress=False),
        FileEntry(name="META-INF/container.xml", data=_container_xml()),
        FileEntry(name="OEBPS/content.opf", data=_opf(chapters)),
        FileEntry(name="OEBPS/toc.ncx", data=_ncx(chapters)),
        FileEntry(name="OEBPS/stylesheet.css", data=_stylesheet()),
        FileEntry(name="OEBPS/titlepage.xhtml", data=_titlepage_xhtml()),
    ]
    for i, (title, text) in enumerate(chapters):
        entries.append(FileEntry(
            name=f"OEBPS/chapter{i + 1:03d}.xhtml",
            data=_chapter_xhtml(i + 1, title, text)))

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    write_epub(output, entries)

    chars = sum(len(t) for _title, t in chapters)
    return {
        "output": str(output),
        "bytes": output.stat().st_size,
        "chapters": len(chapters),
        "chars": chars,
        "first_title": chapters[0][0],
        "last_title": chapters[-1][0],
        "source": BOOK_SOURCE,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="用 Project Gutenberg 公版书合成多章 EPUB 测试样本")
    parser.add_argument("--source", required=True,
                        help="Gutenberg 的 .txt（UTF-8），如 pg51828 聊齋志異")
    parser.add_argument("--output", required=True, help="输出 EPUB 路径")
    parser.add_argument("--chapters", type=int, default=300, help="取多少篇（默认 300）")
    args = parser.parse_args(argv)

    stats = build(Path(args.source), Path(args.output), args.chapters)
    for key, value in stats.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
