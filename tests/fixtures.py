"""测试夹具：按需构造最小但结构完整的 EPUB，以及定位真实样本。"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

from epubtext.archive import FileEntry, write_epub

SAMPLES = {
    "paohuo": Path("in/paohuo.epub"),
    "wanjia": Path("in/wanjia.epub"),
}
CORPUS_DIR = Path("in")


def chapter_xhtml(title: str, body: str, eol: str = "\n") -> bytes:
    text = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        f"<head><title>{title}</title></head>\n"
        f"<body><h1>{title}</h1><p>{body}</p></body>\n"
        "</html>\n"
    )
    if eol == "\r\n":
        text = text.replace("\n", "\r\n")
    return text.encode("utf-8")


def build_epub(
    path: Path,
    chapters: list[tuple[str, str, str]],
    *,
    spine: list[str] | None = None,
    ncx: list[str] | None = None,
    opf_dir: str = "OEBPS",
    eol: str = "\n",
    bom: bool = False,
    extra_entries: dict[str, bytes] | None = None,
    with_nav: bool = False,
) -> Path:
    """构造 EPUB。

    :param chapters: [(文件名, 标题, 正文)]，文件名相对 opf_dir。
    :param spine: 自定义 spine 顺序（文件名列表），默认按 chapters 顺序。
    :param ncx: 自定义 NCX 顺序；默认与 spine 一致。
    """
    spine_order = spine or [name for name, _t, _b in chapters]
    ncx_order = ncx if ncx is not None else spine_order
    titles = {name: title for name, title, _body in chapters}
    if with_nav:
        titles.setdefault("nav.xhtml", "目录")

    manifest = ['    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>']
    entries: list[FileEntry] = []

    if with_nav:
        manifest.append('    <item id="nav" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/>')
        entries.append(
            FileEntry(
                name=f"{opf_dir}/nav.xhtml",
                data=chapter_xhtml("目录", "导航页", eol).replace(b'<html', b'<html lang="zh"', 1),
            )
        )

    for index, (name, title, body) in enumerate(chapters):
        item_id = f"item_{index}"
        manifest.append(f'    <item id="{item_id}" href="{name}" media-type="application/xhtml+xml"/>')
        data = chapter_xhtml(title, body, eol)
        if bom and index == 0:
            data = b"\xef\xbb\xbf" + data
        entries.append(FileEntry(name=f"{opf_dir}/{name}", data=data))

    for name, data in (extra_entries or {}).items():
        entries.append(FileEntry(name=name, data=data))

    # spine 用 idref 指向 manifest；这里 id → 文件名映射一一对应
    id_for = {name: f"item_{i}" for i, (name, _t, _b) in enumerate(chapters)}
    if with_nav:
        id_for["nav.xhtml"] = "nav"
    spine_xml = "\n".join(f'    <itemref idref="{id_for[name]}"/>' for name in spine_order)

    if with_nav and not any(name == f"{opf_dir}/style.css" for name in (extra_entries or {})):
        manifest.append('    <item id="style" href="style.css" media-type="text/css"/>')
        entries.append(FileEntry(name=f"{opf_dir}/style.css", data=b"body{font-size:1em;}"))

    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>测试书</dc:title>
    <dc:identifier id="bookid">test-book-id</dc:identifier>
  </metadata>
  <manifest>
{chr(10).join(manifest)}
  </manifest>
  <spine toc="ncx">
{spine_xml}
  </spine>
</package>
"""
    nav_points = "\n".join(
        f"""    <navPoint id="np{i}" playOrder="{i + 1}">
      <navLabel><text>{titles[name]}</text></navLabel>
      <content src="{name}"/>
    </navPoint>"""
        for i, name in enumerate(ncx_order)
    )
    ncx_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="test-book-id"/></head>
  <docTitle><text>测试书</text></docTitle>
  <navMap>
{nav_points}
  </navMap>
</ncx>
"""

    container = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="{opf_path}" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""".format(opf_path=f"{opf_dir}/content.opf")

    package_entries = [
        FileEntry(name="mimetype", data=b"application/epub+zip", compress=False),
        FileEntry(name="META-INF/container.xml", data=container.encode("utf-8")),
        FileEntry(name=f"{opf_dir}/content.opf", data=opf.encode("utf-8")),
        FileEntry(name=f"{opf_dir}/toc.ncx", data=ncx_xml.encode("utf-8")),
        *entries,
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    return write_epub(path, package_entries)


def sample_or_skip(name: str) -> Path | None:
    """返回真实样本路径；不存在则返回 None（供 skipif 使用）。"""
    path = Path(os.environ.get("EPUBTEXT_SAMPLE_DIR", ".")) / SAMPLES[name]
    return path if path.exists() else None


def corpus_text(name_hint: str) -> str | None:
    """读取语料 TXT（按文件名包含匹配，含子目录）。"""
    directory = Path(os.environ.get("EPUBTEXT_CORPUS_DIR", str(CORPUS_DIR)))
    if not directory.exists():
        return None
    for path in sorted(directory.glob("**/*.txt")):
        if name_hint in path.name:
            return path.read_text(encoding="utf-8", errors="replace")
    return None
