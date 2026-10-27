"""fixtext_import —— FixText V1 导入链路（M2-T2.2）。

对外只暴露这几样：

    from fixtext_import import import_book, ImportOptions, chapter_preview

    result = import_book("book.txt", "workspace/")
    preview = chapter_preview("book.epub")     # 章节只读预览（给用户看）

界面层不直接碰编码探测、复制、合并，全部经 `import_book` 一次完成，
这样"原文件不被修改"只有一个执行入口，验收可复算。
"""

from __future__ import annotations

from .dropguard import detect_kind_safe
from .encoding import ProbeResult, probe
from .epub_import import ChapterInfo, EpubImportError, PreviewResult, chapter_preview
from .importer import (
    ImportError_, ImportOptions, ImportResult, detect_kind, import_book,
    load_record, verify_untouched, workspace_usage,
)
from .textfile import copy_verbatim, normalize, sha256_file, write_text_atomic

__all__ = [
    "ChapterInfo",
    "EpubImportError",
    "ImportError_",
    "ImportOptions",
    "ImportResult",
    "PreviewResult",
    "ProbeResult",
    "chapter_preview",
    "copy_verbatim",
    "detect_kind",
    "detect_kind_safe",
    "import_book",
    "load_record",
    "normalize",
    "probe",
    "sha256_file",
    "verify_untouched",
    "workspace_usage",
]
__version__ = "1.0.0"
