"""EPUB → TXT 合并：按 spine 顺序把各个 XHTML 章节拼成一份可校对文本。

不解析、不改写 HTML 正文，只做「原样搬运 + 边界标记」：
校对的目的是改字，任何 DOM 重排都会让还原变得不可信。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .archive import EpubArchive
from .bundle import (
    BookRecord,
    ChapterRecord,
    Ledger,
    build_book_marker,
    build_header,
    build_split_marker,
    detect_eol,
    ledger_path_for,
    new_nonce,
    sha256_bytes,
    strip_trailing_newlines,
)
from .errors import EpubStructureError
from .package import PackageInfo, parse_package

ENCODING = "utf-8"
BOM = b"\xef\xbb\xbf"


@dataclass
class MergeResult:
    text_path: Path
    ledger_path: Path
    ledger: Ledger
    report: dict = field(default_factory=dict)


def _read_payload(archive: EpubArchive, path: str, warnings: list[str]) -> tuple[bytes, bytes, bytes, bool]:
    """读取章节原始字节。

    返回 ``(原始字节, 去 BOM 后的字节, 章末换行, 是否带 BOM)``。
    账本始终记录**原始字节**的 sha256/size，这样「还原后与原文件逐字节相同」
    就是可直接验证的事实，而不是近似判断。
    """
    raw = archive.read_bytes(path)
    has_bom = raw.startswith(BOM)
    payload = raw[3:] if has_bom else raw
    if has_bom:
        warnings.append(f"{path} 带 UTF-8 BOM：合并时剥除，还原时补回")
    body, tail = strip_trailing_newlines(payload)
    return raw, body, tail, has_bom


def _merge_one(archive: EpubArchive, info: PackageInfo, book_index: int) -> tuple[BookRecord, list[bytes]]:
    """按 spine 顺序构建一本书的账本记录与逐章正文（已统一为 LF、无 BOM）。"""
    chapters: list[ChapterRecord] = []
    bodies: list[bytes] = []

    for order, item in enumerate(info.spine):
        if item.media_type.lower() not in {"application/xhtml+xml", "text/html"} or item.is_nav:
            continue
        raw, body, tail, has_bom = _read_payload(archive, item.path, info.warnings)
        chapters.append(
            ChapterRecord(
                index=len(chapters),
                path=item.path,
                label=info.label_for(item.path),
                media_type=item.media_type,
                size=len(raw),
                sha256=sha256_bytes(raw),
                eol=detect_eol(payload_probe(raw)),
                tail=tail.decode("latin-1"),
                bom=has_bom,
                order=order,
                linear=item.linear,
                book_index=book_index,
            )
        )
        bodies.append(body.replace(b"\r\n", b"\n"))

    book = BookRecord(
        source=archive.path.name,
        title=info.title,
        identifier=info.identifier,
        opf_path=info.opf_path,
        opf_dir=info.opf_dir,
        sha256=archive.sha256(),
        spine=[item.path for item in info.spine],
        chapters=chapters,
        warnings=list(info.warnings),
    )
    return book, bodies


def payload_probe(raw: bytes) -> bytes:
    """剥掉 BOM 后再判断行尾，避免 BOM 干扰首行判断。"""
    return raw[3:] if raw.startswith(BOM) else raw


def merge_epub(
    epub_path: str | Path,
    output_path: str | Path | None = None,
    *,
    nonce: str | None = None,
) -> MergeResult:
    """把一本 EPUB 的章节按 spine 顺序合并成 TXT，并落盘账本。

    :param output_path: 输出 TXT 路径，默认与 EPUB 同目录同名 ``.txt``。
    :param nonce: 标记随机串，默认每次随机生成；测试可固定以复现。
    """
    epub_path = Path(epub_path)
    ledger_nonce = nonce or new_nonce()

    with EpubArchive(epub_path) as archive:
        broken = archive.test_zip_integrity()
        if broken:
            raise EpubStructureError(f"{epub_path.name} 的 ZIP 结构损坏：{broken}")
        info = parse_package(archive)
        book, bodies = _merge_one(archive, info, book_index=0)

    chapter_count = len(book.chapters)
    lines: list[str] = [
        build_header(ledger_nonce, 1, chapter_count),
        build_book_marker(ledger_nonce, 0, book.title or epub_path.stem, epub_path.name, chapter_count),
    ]
    for chapter, body in zip(book.chapters, bodies):
        lines.append(
            build_split_marker(ledger_nonce, chapter.index, chapter.path, chapter.label, chapter.size, chapter.sha256)
        )
        lines.append(body.decode(ENCODING, errors="replace"))
        lines.append("")

    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"

    text_path = Path(output_path) if output_path else epub_path.with_suffix(".txt")
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(text, encoding=ENCODING, newline="\n")

    ledger = Ledger(nonce=ledger_nonce, books=[book], text_path=text_path.name)
    ledger_file = ledger_path_for(text_path)
    ledger.save(ledger_file)

    report = {
        "epub": epub_path.name,
        "text": text_path.name,
        "title": book.title,
        "chapters": chapter_count,
        "spine_items": len(info.spine),
        "skipped_spine_items": len(info.spine) - chapter_count,
        "ncx_entries": sum(len(list(node.walk())) for node in info.toc),
        "text_bytes": text_path.stat().st_size,
        "warnings": info.warnings,
    }
    return MergeResult(text_path=text_path, ledger_path=ledger_file, ledger=ledger, report=report)


def merge_many(
    epub_paths: list[str | Path],
    output_path: str | Path,
    *,
    nonce: str | None = None,
) -> MergeResult:
    """把多本 EPUB 合并进同一份 TXT（书标记分隔，章标记按全局连续索引）。"""
    if not epub_paths:
        raise EpubStructureError("合并多本时至少要给一本 EPUB")
    ledger_nonce = nonce or new_nonce()

    prepared: list[tuple[BookRecord, list[bytes], PackageInfo]] = []
    total = 0
    for book_index, epub_path in enumerate(epub_paths):
        epub_path = Path(epub_path)
        with EpubArchive(epub_path) as archive:
            broken = archive.test_zip_integrity()
            if broken:
                raise EpubStructureError(f"{epub_path.name} 的 ZIP 结构损坏：{broken}")
            info = parse_package(archive)
            book, bodies = _merge_one(archive, info, book_index=book_index)
        prepared.append((book, bodies, info))
        total += len(book.chapters)

    lines: list[str] = [build_header(ledger_nonce, len(prepared), total)]
    cursor = 0
    books: list[BookRecord] = []
    for book_index, (book, bodies, _info) in enumerate(prepared):
        lines.append(
            build_book_marker(
                ledger_nonce, book_index, book.title or Path(book.source).stem, book.source, len(book.chapters)
            )
        )
        for chapter, body in zip(book.chapters, bodies):
            chapter.index = cursor
            cursor += 1
            lines.append(
                build_split_marker(
                    ledger_nonce, chapter.index, chapter.path, chapter.label, chapter.size, chapter.sha256
                )
            )
            lines.append(body.decode(ENCODING, errors="replace"))
            lines.append("")
        books.append(book)

    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"

    text_path = Path(output_path)
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(text, encoding=ENCODING, newline="\n")

    ledger = Ledger(nonce=ledger_nonce, books=books, text_path=text_path.name)
    ledger_file = ledger_path_for(text_path)
    ledger.save(ledger_file)

    report = {
        "books": [book.source for book in books],
        "chapters": total,
        "text_bytes": text_path.stat().st_size,
        "warnings": [w for book in books for w in book.warnings],
    }
    return MergeResult(text_path=text_path, ledger_path=ledger_file, ledger=ledger, report=report)


def merge_directory(
    source_dir: str | Path,
    output_dir: str | Path | None = None,
    *,
    recursive: bool = True,
) -> list[MergeResult]:
    """批量合并目录下的 EPUB，每本产出同名 TXT + 账本。"""
    source_dir = Path(source_dir)
    if not source_dir.exists():
        raise EpubStructureError(f"目录不存在：{source_dir}")
    output_dir = Path(output_dir) if output_dir else source_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    pattern = "**/*.epub" if recursive else "*.epub"
    results: list[MergeResult] = []
    for epub in sorted(source_dir.glob(pattern)):
        if not epub.is_file():
            continue
        target = output_dir / (epub.stem + ".txt")
        results.append(merge_epub(epub, target))
    return results
