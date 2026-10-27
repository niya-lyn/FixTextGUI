"""epubtext —— EPUB 文本合并与还原（供编排器调用的独立模块）。

对外 API::

    from epubtext import merge_epub, restore_epub, check_epub

    result = merge_epub("book.epub")                 # -> book.txt + book.bundle.json
    restore_epub(result.text_path, result.ledger_path, "book.epub")   # -> book_restored.epub

设计约定见各子模块文档；此处只导出稳定入口。
"""

from __future__ import annotations

from .archive import EpubArchive, FileEntry, collect_entries, write_epub
from .bundle import (
    BookRecord,
    ChapterRecord,
    Ledger,
    SplitChunk,
    ledger_path_for,
    reconstruct_chapter_bytes,
    split_bundle,
    verify_bundle,
)
from .errors import BundleFormatError, EpubStructureError, EpubTextError, RestoreError
from .merge import MergeResult, merge_directory, merge_epub, merge_many
from .package import PackageInfo, SpineItem, parse_ncx, parse_package, reading_order, verify_order_against_ncx
from .restore import RestoreResult, restore_epub, restore_many
from .validate import CheckReport, check_epub, compare_bytes, compare_content

__all__ = [
    "BookRecord",
    "BundleFormatError",
    "ChapterRecord",
    "CheckReport",
    "EpubArchive",
    "EpubStructureError",
    "EpubTextError",
    "FileEntry",
    "Ledger",
    "MergeResult",
    "PackageInfo",
    "RestoreError",
    "RestoreResult",
    "SpineItem",
    "SplitChunk",
    "check_epub",
    "collect_entries",
    "compare_bytes",
    "compare_content",
    "ledger_path_for",
    "merge_directory",
    "merge_epub",
    "merge_many",
    "parse_ncx",
    "parse_package",
    "reading_order",
    "reconstruct_chapter_bytes",
    "restore_epub",
    "restore_many",
    "split_bundle",
    "verify_bundle",
    "verify_order_against_ncx",
    "write_epub",
]

__version__ = "1.0.0"
