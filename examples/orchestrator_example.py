"""编排器调用示例：把本模块接进批处理流程。

三种典型接法：逐本往返自检、批量合并、目录批处理。
"""

from __future__ import annotations

import json
from pathlib import Path

from epubtext import (
    check_epub,
    compare_bytes,
    compare_content,
    merge_directory,
    merge_epub,
    merge_many,
    restore_epub,
    restore_many,
)


def roundtrip_one(epub: Path, work_dir: Path) -> dict:
    """单本：合并 → 还原 → 三层校验。返回可直接落日志的报告。"""
    merged = merge_epub(epub, work_dir / f"{epub.stem}.txt")
    restored = restore_epub(merged.text_path, merged.ledger_path, epub, work_dir / f"{epub.stem}_r.epub")

    structural = check_epub(restored.epub_path)
    content = compare_content(epub, restored.epub_path)
    binary = compare_bytes(epub, restored.epub_path)

    return {
        "book": epub.name,
        "chapters": merged.report["chapters"],
        "spine_items": merged.report["spine_items"],
        "check_ok": structural.ok,
        "errors": structural.errors,
        "order_equal": content["spine_order_equal"],
        "text_equal_chapters": content["text_equal_chapters"],
        "missing_text_chapters": content["missing_text_chapters"],
        "byte_identical": binary["byte_identical"],
        "chapters_changed": restored.chapters_changed,
        "ok": structural.ok and content["content_ok"] and binary["byte_identical"],
    }


def merge_into_one_txt(epubs: list[Path], out_txt: Path, templates_out: Path) -> list[dict]:
    """把多本书合并成一个 TXT，再各自还原。账本按书分组，章索引全局连续。"""
    merged = merge_many(epubs, out_txt)
    results = restore_many(merged.text_path, merged.ledger_path, epubs, templates_out)
    return [
        {
            "book": r.book_source,
            "chapters_written": r.chapters_written,
            "chapters_changed": r.chapters_changed,
            "check_ok": check_epub(r.epub_path).ok,
        }
        for r in results
    ]


def batch_directory(in_dir: Path, out_dir: Path) -> dict:
    """整个目录：每本各生成一份 TXT（互不合并）。"""
    results = merge_directory(in_dir, out_dir)
    return {
        "count": len(results),
        "failed": [r.report for r in results if r.report.get("warnings")],
        "total_chapters": sum(r.report.get("chapters", 0) for r in results),
    }


if __name__ == "__main__":
    import sys

    work = Path("work")
    work.mkdir(exist_ok=True)
    for argument in sys.argv[1:]:
        print(json.dumps(roundtrip_one(Path(argument), work), ensure_ascii=False, indent=2))
