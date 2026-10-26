"""TXT → EPUB 还原：按账本把合并文本逐章写回原包。

关键取舍：

* **以原 EPUB 为模板重打包**，而不是从零构造新包。图片、字体、样式、OPF、NCX
  全部原样保留，正文只替换 spine 指定的那些 XHTML 条目——章节顺序、
  目录结构因此天然不动，还原后的包一定能打开。
* **只替换被合并过的条目**，模板里其它条目字节不变。
* **还原前先校验切分结果**：标记索引连续、路径与账本一致、数量相符。
  任一项不符就拒绝写包，避免把错位的文本写进错误的章节。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .archive import EpubArchive, FileEntry, collect_entries, write_epub
from .bundle import (
    ChapterRecord,
    Ledger,
    SplitChunk,
    reconstruct_chapter_bytes,
    split_bundle,
    verify_bundle,
)
from .errors import BundleFormatError, RestoreError
from .package import parse_package

ENCODING = "utf-8"


@dataclass
class RestoreResult:
    epub_path: Path
    book_source: str
    chapters_written: int
    chapters_changed: int
    report: dict = field(default_factory=dict)


def restore_epub(
    text_path: str | Path,
    ledger_file: str | Path | None = None,
    template_epub: str | Path | None = None,
    output_path: str | Path | None = None,
    *,
    strict: bool = True,
    allow_modified: bool = True,
) -> RestoreResult:
    """从合并文本 + 账本还原一本 EPUB。

    :param ledger_file: 账本路径，默认按 ``<TXT 名>.bundle.json`` 找。
    :param template_epub: 作为模板的原 EPUB，默认按账本里的 source 文件名在 TXT 同目录找。
    :param output_path: 输出 EPUB，默认 ``<TXT 名>_restored.epub``。
    :param strict: 切分校验严格模式（默认开启）。
    :param allow_modified: 是否允许正文被编辑过（默认允许，改动计入报告）。
    """
    text_path = Path(text_path)
    ledger = Ledger.load(ledger_file) if ledger_file else Ledger.load(_default_ledger(text_path))
    if len(ledger.books) != 1:
        raise BundleFormatError("账本含多本书，请用 restore_many 并逐本指定模板")

    text = text_path.read_text(encoding=ENCODING, errors="replace")
    # 外部校对软件常把行尾改成 CRLF；统一回 LF 再切分，否则标记行匹配会失败
    text = text.replace("\r\n", "\n")

    chunks = split_bundle(text, ledger, strict=strict)
    book = ledger.books[0]

    if not allow_modified:
        diffs = [row for row in verify_bundle(chunks, ledger) if not row["unchanged"]]
        if diffs:
            raise RestoreError(f"{len(diffs)} 章内容与合并时不一致，且不允许改动")

    template = _resolve_template(template_epub, book.source, text_path)
    entries = _rebuild_entries(template, book.chapters, chunks)

    output = Path(output_path) if output_path else text_path.with_name(text_path.stem + "_restored.epub")
    write_epub(output, entries)

    diffs = verify_bundle(chunks, ledger)
    changed = [row for row in diffs if not row["unchanged"]]
    report = {
        "source_epub": book.source,
        "template": template.name,
        "output": output.name,
        "chapters_written": len(chunks),
        "chapters_changed": len(changed),
        "entries_total": len(entries),
        "changed_paths": [row["path"] for row in changed][:20],
        "warnings": book.warnings,
    }
    return RestoreResult(
        epub_path=output,
        book_source=book.source,
        chapters_written=len(chunks),
        chapters_changed=len(changed),
        report=report,
    )


def _default_ledger(text_path: Path) -> Path:
    candidate = text_path.with_name(text_path.stem + ".bundle.json")
    if not candidate.exists():
        raise RestoreError(f"找不到账本：{candidate}；还原必须依赖合并时生成的账本")
    return candidate


def _resolve_template(template_epub: str | Path | None, source_name: str, text_path: Path) -> Path:
    if template_epub is not None:
        path = Path(template_epub)
        if not path.exists():
            raise RestoreError(f"模板 EPUB 不存在：{path}")
        return path
    candidate = text_path.parent / source_name
    if candidate.exists():
        return candidate
    raise RestoreError(
        f"找不到模板 EPUB：{candidate}；请显式传入原 EPUB 作为模板（还原靠它保留图片/样式/目录）"
    )


def _rebuild_entries(
    template: Path,
    chapters: list[ChapterRecord],
    chunks: list[SplitChunk],
) -> list[FileEntry]:
    """按模板条目顺序重建包，只替换目标章节的内容。"""
    if len(chunks) != len(chapters):
        raise RestoreError(f"切出 {len(chunks)} 章，账本记录 {len(chapters)} 章，无法对齐")

    with EpubArchive(template) as archive:
        broken = archive.test_zip_integrity()
        if broken:
            raise RestoreError(f"模板 EPUB 的 ZIP 结构损坏：{broken}")
        info = parse_package(archive)

        replacements: dict[str, bytes] = {}
        for chunk, chapter in zip(chunks, chapters):
            if chapter.path in replacements:
                raise RestoreError(f"账本出现重复章节路径：{chapter.path}")
            replacements[chapter.path] = reconstruct_chapter_bytes(chunk, chapter)

        missing = [path for path in replacements if not archive.has(path)]
        if missing:
            raise RestoreError(f"模板 EPUB 中缺少这些章节文件，无法还原：{missing[:5]}")

        entries = collect_entries(archive)

    rebuilt = [
        FileEntry(name=entry.name, data=replacements.get(entry.name, entry.data), compress=True)
        for entry in entries
    ]
    _assert_structure_intact(rebuilt, info)
    return rebuilt


def _assert_structure_intact(entries: list[FileEntry], info) -> None:
    """写出前确认：mimetype 存在且首位、spine 中每个文件都还在包内。"""
    names = [entry.name for entry in entries]
    if not names or names[0] != "mimetype":
        raise RestoreError("重建后的条目顺序被破坏：mimetype 必须是第一个条目")
    present = set(names)
    missing = [item.path for item in info.spine if item.path not in present]
    if missing:
        raise RestoreError(f"重建后缺少 spine 文件：{missing[:5]}")


def restore_many(
    text_path: str | Path,
    ledger_file: str | Path,
    templates: list[str | Path],
    output_dir: str | Path,
    *,
    strict: bool = True,
) -> list[RestoreResult]:
    """多本书合并后的批量还原：按账本里的书顺序对齐模板。"""
    text_path = Path(text_path)
    ledger = Ledger.load(ledger_file)
    if len(templates) != len(ledger.books):
        raise BundleFormatError(f"账本含 {len(ledger.books)} 本书，但给了 {len(templates)} 个模板")

    text = text_path.read_text(encoding=ENCODING, errors="replace").replace("\r\n", "\n")
    chunks = split_bundle(text, ledger, strict=strict)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[RestoreResult] = []
    cursor = 0
    for book, template in zip(ledger.books, templates):
        slice_chunks = chunks[cursor: cursor + len(book.chapters)]
        cursor += len(book.chapters)
        entries = _rebuild_entries(Path(template), book.chapters, slice_chunks)
        output = output_dir / (Path(template).stem + "_restored.epub")
        write_epub(output, entries)

        diffs = verify_bundle(slice_chunks, Ledger(nonce=ledger.nonce, books=[book]))
        changed = sum(1 for row in diffs if not row["unchanged"])
        results.append(
            RestoreResult(
                epub_path=output,
                book_source=book.source,
                chapters_written=len(slice_chunks),
                chapters_changed=changed,
                report={"chapters": len(slice_chunks), "changed": changed},
            )
        )
    return results
