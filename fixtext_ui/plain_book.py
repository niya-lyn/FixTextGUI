"""FixText V1 · 纯文本进校正链路的接线适配（M2-T2.9）
=====================================================

**为什么需要这一层**

M1 编排器的输入是 EPUB（合并 → 排版 → 替换 → 检查 → 专名 → 还原），
纯文本书没有章节包结构，进不了这条链路；但用户在导入页选了 TXT 书之后，
一键校正页与导出页仍要能用——否则 TXT 书永远拿不到校正结果，
导出统计只能写「命中数 0」。

本层只做**接线**，不重写任何引擎：

1. 把导入后的正文原样（逐字节）包成一份**单章电子书**——
   章节条目用 ``text/html`` 承载纯文本字节，``merge_epub`` 会把它当作
   一章原样取出，于是纯文本也能走同一条六阶段链路；
2. 校正结束后，把还原出来的单章电子书再摊回纯文本（仍走同一份账本切分）。

**命名约定**：包装用的电子书放在本次运行目录里、以原书名命名
（``<书名>.source.epub``），这样管线各阶段产物 ``<书名>.txt`` 与
运行目录一致，导出侧不必再猜名字。包装文件是内部中间产物，
用完即随运行目录一起管理，不写进用户的导入文件夹。
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

CONTAINER_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<container version="1.0" '
    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
    '  <rootfiles><rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles>\n'
    '</container>\n'
)

_PACKAGE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
    'unique-identifier="bookid">\n'
    '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
    '    <dc:title>{title}</dc:title>\n'
    '    <dc:creator>{author}</dc:creator>\n'
    '    <dc:identifier id="bookid">{ident}</dc:identifier>\n'
    '    <dc:language>zh-CN</dc:language>\n'
    '  </metadata>\n'
    '  <manifest><item id="body" href="body.html" media-type="text/html"/></manifest>\n'
    '  <spine><itemref idref="body"/></spine>\n'
    '</package>\n'
)


def build_plain_source(text_path: str | Path,
                       out_epub: str | Path,
                       title: str = "",
                       author: str = "") -> Path:
    """把一份纯文本原样包成单章电子书，供校正链路当输入用。

    正文按**字节**写入，不做任何转义或重排：管线取出的一定是与导入时
    完全相同的那份正文（后续的改动全部发生在管线的替换阶段）。
    """
    text_path = Path(text_path)
    out_epub = Path(out_epub)
    body = text_path.read_bytes()
    safe_title = escape(title or text_path.stem)
    package = _PACKAGE_XML.format(
        title=safe_title,
        author=escape(author or ""),
        # 标识只用书名派生，同一本书每次包装一致（可复现）
        ident=escape("fixtext-plain-" + (title or text_path.stem)),
    )

    out_epub.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_epub, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        info = zipfile.ZipInfo("mimetype", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_STORED
        info.external_attr = 0o644 << 16
        info.extra = b""
        archive.writestr(info, "application/epub+zip")
        archive.writestr("META-INF/container.xml", CONTAINER_XML.encode("utf-8"))
        archive.writestr("OEBPS/content.opf", package.encode("utf-8"))
        archive.writestr("OEBPS/body.html", body)
    return out_epub


def plain_source_epub(text_path: str | Path,
                      run_dir: str | Path,
                      title: str = "",
                      author: str = "") -> Path:
    """在运行目录里准备本次校正用的单章电子书，返回其路径。"""
    stem = (title or Path(text_path).stem).strip() or "book"
    safe = "".join(ch for ch in stem if ch not in '\\/:*?"<>|').strip() or "book"
    return build_plain_source(text_path, Path(run_dir) / f"{safe}.source.epub",
                              title=title or stem, author=author)


def describe(text_path: str | Path, run_dir: str | Path) -> dict[str, Any]:
    """这层做了什么（供结果摘要与验收引用）。"""
    return {
        "mode": "plain-wrapped",
        "text_path": str(text_path),
        "wrapped_epub": str(Path(run_dir) / f"{Path(text_path).stem}.source.epub"),
    }
