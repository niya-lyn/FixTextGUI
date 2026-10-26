"""校验器与归档层测试：结构判定、mimetype 规范、字节比对、大文本。"""

from __future__ import annotations

import time
import zipfile
from pathlib import Path

import pytest

from epubtext.archive import EpubArchive, collect_entries, write_epub
from epubtext.bundle import Ledger
from epubtext.merge import merge_epub
from epubtext.restore import restore_epub
from epubtext.validate import check_epub, compare_bytes, compare_content

from .fixtures import build_epub, corpus_text, sample_or_skip


def _simple(tmp_path: Path) -> Path:
    return build_epub(
        tmp_path / "book.epub",
        [("c1.xhtml", "第1章", "内容一"), ("c2.xhtml", "第2章", "内容二")],
    )


def test_check_ok_on_valid_epub(tmp_path):
    report = check_epub(_simple(tmp_path))
    assert report.ok
    assert report.stats["content_items"] == 2
    assert report.stats["ncx"] is True


def test_check_detects_missing_mimetype(tmp_path):
    epub = _simple(tmp_path)
    with zipfile.ZipFile(epub) as zf:
        names = {n: zf.read(n) for n in zf.namelist()}
    names.pop("mimetype")
    target = tmp_path / "nomime.epub"
    with zipfile.ZipFile(target, "w") as zf:
        for name, data in names.items():
            zf.writestr(name, data)
    report = check_epub(target)
    assert report.ok is False
    assert any("mimetype" in error for error in report.errors)


def test_check_detects_compressed_mimetype(tmp_path):
    """mimetype 被压缩的包很多阅读器会拒绝，必须能识别出来。"""
    epub = _simple(tmp_path)
    with zipfile.ZipFile(epub) as zf:
        names = [(n, zf.read(n)) for n in zf.namelist()]
    target = tmp_path / "compressed.epub"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in names:
            zf.writestr(name, data)
    report = check_epub(target)
    assert report.ok is False
    assert any("STORED" in error or "压缩" in error for error in report.errors)


def test_check_detects_missing_chapter_file(tmp_path):
    epub = _simple(tmp_path)
    with zipfile.ZipFile(epub) as zf:
        names = {n: zf.read(n) for n in zf.namelist()}
    names.pop("OEBPS/c2.xhtml")
    target = tmp_path / "missing.epub"
    with zipfile.ZipFile(target, "w") as zf:
        for name, data in names.items():
            zf.writestr(name, data)
    report = check_epub(target)
    assert report.ok is False
    assert any("spine" in error for error in report.errors)


def test_check_rejects_non_zip(tmp_path):
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"this is not a zip file")
    report = check_epub(bad)
    assert report.ok is False


def test_write_epub_puts_mimetype_first_uncompressed(tmp_path):
    from epubtext.archive import FileEntry

    entries = [
        FileEntry(name="mimetype", data=b"application/epub+zip", compress=False),
        FileEntry(name="META-INF/container.xml", data=b"<container/>"),
    ]
    target = tmp_path / "out.epub"
    write_epub(target, entries)
    with zipfile.ZipFile(target) as zf:
        infos = zf.infolist()
    assert infos[0].filename == "mimetype"
    assert infos[0].compress_type == zipfile.ZIP_STORED
    assert infos[0].extra == b""


def test_write_epub_rejects_duplicate_entries(tmp_path):
    from epubtext.archive import FileEntry
    from epubtext.errors import EpubStructureError

    entries = [
        FileEntry(name="mimetype", data=b"application/epub+zip", compress=False),
        FileEntry(name="a.xhtml", data=b"1"),
        FileEntry(name="a.xhtml", data=b"2"),
    ]
    with pytest.raises(EpubStructureError, match="重复"):
        write_epub(tmp_path / "dup.epub", entries)


def test_compare_bytes_detects_change(tmp_path):
    epub = _simple(tmp_path)
    merged = merge_epub(epub, tmp_path / "b.txt", nonce="aabbccddeeff0011")
    restored = restore_epub(merged.text_path, merged.ledger_path, epub, tmp_path / "r.epub")
    assert compare_bytes(epub, restored.epub_path)["byte_identical"] is True

    text = merged.text_path.read_text(encoding="utf-8").replace(">内容一<", ">改过<")
    merged.text_path.write_text(text, encoding="utf-8")
    restored2 = restore_epub(merged.text_path, merged.ledger_path, epub, tmp_path / "r2.epub")
    diff = compare_bytes(epub, restored2.epub_path)
    assert diff["byte_identical"] is False
    assert diff["differing_entries"] == ["OEBPS/c1.xhtml"]


def test_compare_content_flags_empty_chapter(tmp_path):
    """空章节必须被识别为内容缺失，而不是"文本不同"。"""
    epub = _simple(tmp_path)
    merged = merge_epub(epub, tmp_path / "b.txt", nonce="aabbccddeeff0011")
    text = merged.text_path.read_text(encoding="utf-8")
    # 把第一章正文清空
    text = text.replace("<h1>第1章</h1><p>内容一</p>", "")
    merged.text_path.write_text(text, encoding="utf-8")
    restored = restore_epub(merged.text_path, merged.ledger_path, epub, tmp_path / "r.epub")
    result = compare_content(epub, restored.epub_path)
    assert "OEBPS/c1.xhtml" in result["missing_text_chapters"]
    assert result["content_ok"] is False


def test_compare_content_ignores_head_title(tmp_path):
    """正文清空但 <head><title> 还在时，仍须判为正文缺失（不能因标题还算"文本不同"）。"""
    from epubtext.validate import _normalize_ws, _text_content

    xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        "<head><title>第1章</title></head><body></body></html>"
    ).encode("utf-8")
    assert _normalize_ws(_text_content(xhtml)) == ""

    epub = _simple(tmp_path)
    merged = merge_epub(epub, tmp_path / "b.txt", nonce="aabbccddeeff0011")
    text = merged.text_path.read_text(encoding="utf-8")
    # 只清空 body，保留 head/title
    broken = text.replace("<body><h1>第1章</h1><p>内容一</p></body>", "<body></body>")
    assert broken != text
    merged.text_path.write_text(broken, encoding="utf-8")
    restored = restore_epub(merged.text_path, merged.ledger_path, epub, tmp_path / "r.epub")
    result = compare_content(epub, restored.epub_path)
    assert result["missing_text_chapters"] == ["OEBPS/c1.xhtml"]
    assert result["content_ok"] is False


def test_large_text_bundle_scales(tmp_path):
    """大文本场景：把公版书整本切成多章，走一遍合并→还原，验证吞吐与一致。"""
    text = corpus_text("hongloumeng")  # 语料实际文件名，勿按书名匹配
    if text is None:
        pytest.skip("语料 TXT 不存在")
    assert text and len(text) > 500_000

    # 按 20000 字符切章，构造一个"大书"场景（模拟大文本合并）
    chunk_size = 20_000
    pieces = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
    chapters = [
        (f"part{index:04d}.xhtml", f"第{index}章", piece.replace("\n", " ")) for index, piece in enumerate(pieces)
    ]
    epub = build_epub(tmp_path / "big.epub", chapters, opf_dir="OEBPS")

    started = time.perf_counter()
    merged = merge_epub(epub, tmp_path / "big.txt", nonce="0011223344556677")
    merge_seconds = time.perf_counter() - started

    started = time.perf_counter()
    restored = restore_epub(merged.text_path, merged.ledger_path, epub, tmp_path / "big_r.epub")
    restore_seconds = time.perf_counter() - started

    assert restored.chapters_changed == 0
    assert compare_bytes(epub, restored.epub_path)["byte_identical"]
    assert merged.text_path.stat().st_size > 500_000
    # 记录耗时（不做断言，只确保不会慢到不可用）
    assert merge_seconds < 120 and restore_seconds < 120


@pytest.mark.parametrize("sample", ["paohuo", "wanjia"])
def test_real_sample_check_passes(sample):
    epub = sample_or_skip(sample)
    if epub is None:
        pytest.skip(f"样本 {sample} 不存在")
    report = check_epub(epub)
    assert report.ok, report.errors
    assert report.stats["spine_items"] > 400
