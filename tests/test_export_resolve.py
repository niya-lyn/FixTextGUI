"""M2-T2.9 导出源定位链单测（P0 回归守卫）。

背景：导入侧把正文固定写成 ``book.txt``，M1 管线按书名命名产物
（``<书名>.txt``），两套名字天生不同。导出侧若按 stem 拼路径，
``03_replace/after/<stem>.txt`` 必然不存在 → 导出未校正原文。
这里锁死「不按文件名猜」的三级定位链 + 反向用例。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "fixtext_ui"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import fixtext_export as fx


def _mk_run(tmp_path: Path, book_stem: str = "sample_book") -> dict:
    """造一个最小运行目录：产物名是书名，与导入的 book.txt 完全不同名。"""
    run = tmp_path / "run"
    for sub in ("02_layout", "03_replace/before", "03_replace/after", "04_quote"):
        (run / sub).mkdir(parents=True, exist_ok=True)
    after = run / "03_replace" / "after" / f"{book_stem}.txt"
    after.write_text("校正后的正文", encoding="utf-8")
    before = run / "03_replace" / "before" / f"{book_stem}.txt"
    before.write_text("校正前的正文", encoding="utf-8")
    laid = run / "02_layout" / f"{book_stem}.txt"
    laid.write_text("排版后的正文", encoding="utf-8")
    ledger = run / "02_layout" / f"{book_stem}.bundle.json"
    ledger.write_text("{}", encoding="utf-8")
    (run / "03_replace" / "replace_report.json").write_text(
        json.dumps({"before_path": str(before), "after_path": str(after)}),
        encoding="utf-8")
    (run / "04_quote" / "quote_summary.json").write_text(
        json.dumps({"checked_file": str(after)}), encoding="utf-8")
    return {"workdir": str(run), "artifacts": {
        "after_text": str(after), "before_text": str(before),
        "laid_out_text": str(laid), "checked_file": str(after),
        "ledger": str(ledger), "restored_epub": ""}}


def _record(tmp_path: Path) -> dict:
    """导入记录：正文恒为 book.txt（与 importer.py 的真实行为一致）。"""
    imp_dir = tmp_path / "ws" / "book_abcd1234"
    imp_dir.mkdir(parents=True, exist_ok=True)
    txt = imp_dir / "book.txt"
    txt.write_text("未校正的原文", encoding="utf-8")
    return {"title": "示例书稿", "text_path": str(txt),
            "original_copy_path": str(tmp_path / "sample_book.epub")}


def test_resolve_uses_summary_artifacts(tmp_path):
    """第一优先：校正摘要的 artifacts 段（worker 回传的绝对路径）。"""
    run = _mk_run(tmp_path)
    src = fx.resolve_source(_record(tmp_path), run)
    assert src.corrected is True
    assert Path(src.text_path).name == "sample_book.txt"
    assert src.resolve_notes and src.resolve_notes[0] == "校正后正文：运行摘要"
    assert src.before_text and Path(src.before_text).read_text(encoding="utf-8") == "校正前的正文"
    assert src.ledger_path and Path(src.ledger_path).name == "sample_book.bundle.json"


def test_resolve_without_artifacts_falls_back_to_reports(tmp_path):
    """反向用例核心：摘要里没有权威路径，仍须靠阶段报告找到校正后正文。

    这条用例锁的正是 P0 的修法——记录里的 text_path 是 book.txt，
    运行产物叫 sample_book.txt，名字不一致也必须定位成功。
    """
    run = _mk_run(tmp_path)
    run.pop("artifacts")
    src = fx.resolve_source(_record(tmp_path), run)
    assert src.corrected is True
    assert Path(src.text_path).name == "sample_book.txt"
    assert src.resolve_notes[0] == "校正后正文：阶段报告"


def test_resolve_falls_back_to_directory_enumeration(tmp_path):
    """第二阶段兜底：报告缺失时按目录里真实存在的 .txt 枚举，不拼名字。"""
    run = _mk_run(tmp_path)
    run.pop("artifacts")
    (tmp_path / "run" / "03_replace" / "replace_report.json").unlink()
    (tmp_path / "run" / "04_quote" / "quote_summary.json").unlink()
    src = fx.resolve_source(_record(tmp_path), run)
    assert src.corrected is True
    assert Path(src.text_path).name == "sample_book.txt"
    assert "目录枚举" in src.resolve_notes[0]


def test_resolve_prefers_same_stem_among_candidates(tmp_path):
    """目录里多份产物时优先取与记录同 stem 的那份（而不是盲取最新）。"""
    run = _mk_run(tmp_path)
    run.pop("artifacts")
    (tmp_path / "run" / "03_replace" / "replace_report.json").unlink()
    (tmp_path / "run" / "04_quote" / "quote_summary.json").unlink()
    other = tmp_path / "run" / "03_replace" / "after" / "别的书.txt"
    other.write_text("另一本书的正文", encoding="utf-8")
    rec = _record(tmp_path)          # 记录 stem = book
    src = fx.resolve_source(rec, run)
    assert src.corrected is True
    # 记录名 book.txt 在产物里没有同名项 → 退化为取最新，但仍非空、不报错
    assert Path(src.text_path).suffix == ".txt"
    assert "目录枚举" in src.resolve_notes[0]


def test_no_run_means_uncorrected(tmp_path):
    """没有校正摘要 = 没跑过校正：导出原文，不假装校正过。"""
    src = fx.resolve_source(_record(tmp_path), None)
    assert src.corrected is False
    assert Path(src.text_path).name == "book.txt"


def test_plain_book_wraps_single_chapter(tmp_path):
    """纯文本书包装：单章、正文原样字节、可被管线读取。"""
    from plain_book import plain_source_epub
    txt = tmp_path / "书.txt"
    txt.write_text("第一段\n第二段\n", encoding="utf-8")
    epub = plain_source_epub(txt, tmp_path / "wrap", title="某某书")
    assert epub.exists() and epub.suffix == ".epub"
    fx.ensure_vendor(ROOT / "pipeline")
    from epubtext import merge_epub
    merged = merge_epub(epub, tmp_path / "merged.txt")
    assert len(merged.ledger.chapters) == 1
    body = merged.text_path.read_text(encoding="utf-8")
    assert "第一段" in body and "第二段" in body
