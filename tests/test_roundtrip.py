"""往返测试：合并 → 还原 → 结构与内容校验，含真实样本回归。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from epubtext.merge import merge_directory, merge_epub, merge_many
from epubtext.restore import restore_epub, restore_many
from epubtext.validate import check_epub, compare_bytes, compare_content

from .fixtures import build_epub, sample_or_skip

NONCE = "feedfacecafebeef"


def _book(tmp_path: Path, *, eol: str = "\n", bom: bool = False, spine=None, with_nav: bool = False) -> Path:
    chapters = [
        ("ch1.xhtml", "第1章 开局", "正文一"),
        ("ch2.xhtml", "第2章 发展", "正文二"),
        ("ch10.xhtml", "第10章 转折", "正文十"),
        ("ch11.xhtml", "第11章 收尾", "正文十一"),
    ]
    return build_epub(
        tmp_path / "book.epub",
        chapters,
        spine=spine,
        eol=eol,
        bom=bom,
        with_nav=with_nav,
        extra_entries={"OEBPS/style.css": b"body{}", "OEBPS/Images/pic.jpg": b"\xff\xd8fakejpg"},
    )


def test_roundtrip_is_byte_identical(tmp_path):
    epub = _book(tmp_path)
    merged = merge_epub(epub, tmp_path / "book.txt", nonce=NONCE)
    restored = restore_epub(merged.text_path, merged.ledger_path, epub, tmp_path / "out.epub")

    assert restored.chapters_written == 4
    assert restored.chapters_changed == 0

    report = check_epub(restored.epub_path)
    assert report.ok, report.errors

    content = compare_content(epub, restored.epub_path)
    assert content["spine_order_equal"] is True
    assert content["text_equal_chapters"] == 4

    binary = compare_bytes(epub, restored.epub_path)
    assert binary["byte_identical"], binary["differing_entries"]


def test_roundtrip_with_crlf_source(tmp_path):
    """CRLF 原文往返后必须仍然 CRLF，字节一致。"""
    epub = _book(tmp_path / "crlf", eol="\r\n")
    merged = merge_epub(epub, tmp_path / "crlf" / "book.txt", nonce=NONCE)
    restored = restore_epub(merged.text_path, merged.ledger_path, epub, tmp_path / "crlf" / "out.epub")
    assert compare_bytes(epub, restored.epub_path)["byte_identical"]


def test_roundtrip_with_bom_source(tmp_path):
    epub = _book(tmp_path / "bom", bom=True)
    merged = merge_epub(epub, tmp_path / "bom" / "book.txt", nonce=NONCE)
    restored = restore_epub(merged.text_path, merged.ledger_path, epub, tmp_path / "bom" / "out.epub")
    assert compare_bytes(epub, restored.epub_path)["byte_identical"]


def test_spine_order_preserved_even_when_filenames_sort_differently(tmp_path):
    """spine 给出非字典序时，合并与还原都必须守住 spine 顺序。"""
    spine = ["ch10.xhtml", "ch1.xhtml", "ch11.xhtml", "ch2.xhtml"]
    epub = _book(tmp_path / "perm", spine=spine)
    merged = merge_epub(epub, tmp_path / "perm" / "book.txt", nonce=NONCE)

    ledger = json.loads(merged.ledger_path.read_text(encoding="utf-8"))
    chapters = [c["path"].rsplit("/", 1)[-1] for c in ledger["books"][0]["chapters"]]
    assert chapters == spine
    assert chapters != sorted(chapters)

    # TXT 里章节出现顺序也应与 spine 一致
    text = merged.text_path.read_text(encoding="utf-8")
    positions = [text.index(f"path=OEBPS/{name} ") for name in spine]
    assert positions == sorted(positions), "合并文本里的章节顺序必须与 spine 一致"

    restored = restore_epub(merged.text_path, merged.ledger_path, epub, tmp_path / "perm" / "out.epub")
    content = compare_content(epub, restored.epub_path)
    assert content["spine_order_equal"] is True
    assert compare_bytes(epub, restored.epub_path)["byte_identical"]


def test_restore_applies_edited_text(tmp_path):
    """校对场景：改了正文再还原，改动必须落到对应章节。"""
    epub = _book(tmp_path)
    merged = merge_epub(epub, tmp_path / "book.txt", nonce=NONCE)

    text = merged.text_path.read_text(encoding="utf-8")
    # 用带标签边界的锚点，避免 "正文十" 命中 "正文十一"
    assert text.count(">正文十<") == 1
    text = text.replace(">正文十<", ">正文十（已校对）<")
    merged.text_path.write_text(text, encoding="utf-8")

    restored = restore_epub(merged.text_path, merged.ledger_path, epub, tmp_path / "out.epub")
    assert restored.chapters_changed == 1
    assert restored.report["changed_paths"] == ["OEBPS/ch10.xhtml"]

    content = compare_content(epub, restored.epub_path)
    assert content["spine_order_equal"] is True
    assert content["text_equal_chapters"] == 3
    assert content["text_diff_chapters"][0]["path"] == "OEBPS/ch10.xhtml"
    assert content["missing_text_chapters"] == []

    # 改动确实写进了那一章，且其它章没被动过
    from epubtext.archive import EpubArchive

    with EpubArchive(restored.epub_path) as archive:
        assert "已校对" in archive.read_bytes("OEBPS/ch10.xhtml").decode("utf-8")
        assert "已校对" not in archive.read_bytes("OEBPS/ch1.xhtml").decode("utf-8")


def test_restore_rejects_when_markers_removed(tmp_path):
    """删掉一个章节标记时必须报错，而不是把两章正文写进同一文件。"""
    from epubtext.errors import BundleFormatError

    epub = _book(tmp_path)
    merged = merge_epub(epub, tmp_path / "book.txt", nonce=NONCE)
    text = merged.text_path.read_text(encoding="utf-8")
    lines = [line for line in text.split("\n") if not line.startswith("<!-- EPUBTEXT-SPLIT")]
    merged.text_path.write_text("\n".join(lines), encoding="utf-8")

    with pytest.raises(BundleFormatError):
        restore_epub(merged.text_path, merged.ledger_path, epub, tmp_path / "out.epub")


def test_restore_strict_content_blocks_unedited_mismatch(tmp_path):
    from epubtext.errors import RestoreError

    epub = _book(tmp_path)
    merged = merge_epub(epub, tmp_path / "book.txt", nonce=NONCE)
    text = merged.text_path.read_text(encoding="utf-8").replace(">正文一<", ">改过的正文一<")
    merged.text_path.write_text(text, encoding="utf-8")

    with pytest.raises(RestoreError, match="不一致"):
        restore_epub(merged.text_path, merged.ledger_path, epub, tmp_path / "out.epub", allow_modified=False)


def test_restore_requires_template(tmp_path):
    from epubtext.errors import RestoreError

    epub = _book(tmp_path / "src")
    merged = merge_epub(epub, tmp_path / "txt" / "book.txt", nonce=NONCE)
    with pytest.raises(RestoreError, match="模板"):
        restore_epub(merged.text_path, merged.ledger_path, None, tmp_path / "out.epub")


def test_nav_document_not_merged_but_spine_preserved(tmp_path):
    epub = _book(tmp_path, with_nav=True, spine=["nav.xhtml", "ch1.xhtml", "ch2.xhtml", "ch10.xhtml", "ch11.xhtml"])
    merged = merge_epub(epub, tmp_path / "book.txt", nonce=NONCE)
    assert merged.report["chapters"] == 4
    assert merged.report["skipped_spine_items"] == 1

    restored = restore_epub(merged.text_path, merged.ledger_path, epub, tmp_path / "out.epub")
    assert compare_content(epub, restored.epub_path)["spine_order_equal"] is True
    # nav 未参与合并，故它保持模板原样
    assert compare_bytes(epub, restored.epub_path)["byte_identical"]


def test_merge_directory_batch(tmp_path):
    src = tmp_path / "books"
    src.mkdir()
    for idx in range(3):
        build_epub(
            src / f"b{idx}.epub",
            [("c1.xhtml", "第1章", f"书{idx}正文一"), ("c2.xhtml", "第2章", f"书{idx}正文二")],
        )
    results = merge_directory(src, tmp_path / "out")
    assert len(results) == 3
    for result in results:
        assert result.text_path.exists()
        assert result.ledger_path.exists()


def test_merge_many_books_and_restore(tmp_path):
    first = build_epub(tmp_path / "a.epub", [("c1.xhtml", "第1章", "甲一"), ("c2.xhtml", "第2章", "甲二")])
    second = build_epub(tmp_path / "b.epub", [("d1.xhtml", "第1章", "乙一"), ("d2.xhtml", "第2章", "乙二")])
    merged = merge_many([first, second], tmp_path / "both.txt", nonce=NONCE)
    assert merged.report["chapters"] == 4

    results = restore_many(merged.text_path, merged.ledger_path, [first, second], tmp_path / "out")
    assert len(results) == 2
    for original, restored in zip([first, second], results):
        assert compare_bytes(original, restored.epub_path)["byte_identical"]


@pytest.mark.parametrize("sample", ["paohuo", "wanjia"])
def test_real_sample_roundtrip(sample, tmp_path):
    """真实样本回归：合并→还原后逐字节一致、可打开、顺序不乱。"""
    epub = sample_or_skip(sample)
    if epub is None:
        pytest.skip(f"样本 {sample} 不存在")

    merged = merge_epub(epub, tmp_path / f"{sample}.txt")
    restored = restore_epub(merged.text_path, merged.ledger_path, epub, tmp_path / f"{sample}_r.epub")

    report = check_epub(restored.epub_path)
    assert report.ok, report.errors
    content = compare_content(epub, restored.epub_path)
    assert content["content_ok"], content
    assert compare_bytes(epub, restored.epub_path)["byte_identical"]


@pytest.mark.parametrize("sample", ["paohuo", "wanjia"])
def test_real_sample_spine_is_not_filename_order(sample):
    """证明样本上的顺序确实来自 spine：与文件名排序结果不同。"""
    import re

    from epubtext.bundle import Ledger

    epub = sample_or_skip(sample)
    if epub is None:
        pytest.skip(f"样本 {sample} 不存在")

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        merged = merge_epub(epub, Path(tmp) / "x.txt", nonce=NONCE)
        ledger = Ledger.load(merged.ledger_path)
        spine_order = [chapter.path for chapter in ledger.chapters]

    def natural(path: str):
        return [int(token) if token.isdigit() else token for token in re.split(r"(\d+)", path)]

    assert spine_order != sorted(spine_order), "若相同则说明样本无法暴露文件名排序问题"
    assert spine_order != sorted(spine_order, key=natural)
