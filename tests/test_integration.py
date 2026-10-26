"""真实样本与多书场景的集成测试：覆盖验收标准 1/2/3 的可重复验证。

这些测试依赖 ``in/`` 目录里的云盘材料（EPUB 样本 + 公版书语料）；
材料不存在时 skip，而不是伪造数据。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from epubtext.archive import EpubArchive
from epubtext.merge import merge_epub, merge_many
from epubtext.package import parse_package, verify_order_against_ncx
from epubtext.restore import restore_epub, restore_many
from epubtext.validate import check_epub, compare_bytes, compare_content

from .fixtures import build_epub, corpus_text, sample_or_skip

SAMPLES = ["paohuo", "wanjia"]


def _natural_sort_key(name: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


@pytest.mark.parametrize("sample", SAMPLES)
def test_spine_order_is_not_filename_order(sample, tmp_path):
    """验收标准 3：章节顺序必须由 spine/NCX 决定，不能等价于文件名排序。

    两个样本同时验证「spine 既不等于字典序，也不等于自然序」——
    否则"按文件名排"恰好也能通过，这条标准就没被真正检验。
    """
    epub = sample_or_skip(sample)
    if epub is None:
        pytest.skip(f"样本 {sample} 不存在")

    with EpubArchive(epub) as archive:
        info = parse_package(archive)
        spine = [item.path for item in info.content_items]

    assert spine == [item.path for item in info.spine]
    assert len(spine) > 400
    assert spine != sorted(spine), "spine 恰好等于字典序，样本无法证明顺序来源"
    assert spine != sorted(spine, key=_natural_sort_key), "spine 恰好等于自然序，样本无法证明顺序来源"


@pytest.mark.parametrize("sample", SAMPLES)
def test_spine_order_matches_ncx_subsequence(sample):
    """NCX 必须是 spine 的子序列（前置页只出现在 spine 里属正常）。"""
    epub = sample_or_skip(sample)
    if epub is None:
        pytest.skip(f"样本 {sample} 不存在")

    with EpubArchive(epub) as archive:
        info = parse_package(archive)
        consistent, notes = verify_order_against_ncx(info)

    assert consistent, f"NCX 与 spine 顺序冲突：{notes}"


@pytest.mark.parametrize("sample", SAMPLES)
def test_real_sample_full_roundtrip_is_byte_identical(sample, tmp_path):
    """验收标准 1/2：合并→还原后结构与正文完全一致（比"无丢失"更强的逐字节相等）。"""
    epub = sample_or_skip(sample)
    if epub is None:
        pytest.skip(f"样本 {sample} 不存在")

    merged = merge_epub(epub, tmp_path / f"{sample}.txt")
    restored = restore_epub(merged.text_path, merged.ledger_path, epub, tmp_path / f"{sample}_r.epub")

    report = check_epub(restored.epub_path)
    assert report.ok, report.errors

    content = compare_content(epub, restored.epub_path)
    assert content["spine_order_equal"] is True
    assert content["missing_text_chapters"] == []
    assert content["missing_files"] == []
    assert content["text_equal_chapters"] == content["compared_chapters"]
    assert content["total_src_text_chars"] == content["total_dst_text_chars"]

    diff = compare_bytes(epub, restored.epub_path)
    assert diff["only_in_src"] == [] and diff["only_in_dst"] == []
    assert diff["byte_identical"] is True
    assert restored.chapters_changed == 0


def test_merge_order_follows_spine_not_sort(tmp_path):
    """用一个刻意打乱文件名的包，证明合并顺序取自 spine。"""
    chapters = [(f"c{i}.xhtml", f"第{i}章", f"正文{i}") for i in range(1, 6)]
    # spine 顺序 = 文件名的自然序反过来，与字典序、自然序都不同
    epub = build_epub(tmp_path / "b.epub", chapters, spine=["c3.xhtml", "c1.xhtml", "c5.xhtml", "c2.xhtml", "c4.xhtml"])
    merged = merge_epub(epub, tmp_path / "b.txt")

    order = [row.path for row in merged.ledger.books[0].chapters]
    assert order == [f"OEBPS/{name}" for name in ["c3.xhtml", "c1.xhtml", "c5.xhtml", "c2.xhtml", "c4.xhtml"]]
    text = merged.text_path.read_text(encoding="utf-8")
    assert text.index("正文3") < text.index("正文1") < text.index("正文5")


def test_multi_book_merge_restores_each_book_independently(tmp_path):
    """多书合并：账本按书分组、章索引全局连续，还原时各自回到原书。"""
    books = {}
    for stem, title in [("bookA", "甲书"), ("bookB", "乙书"), ("bookC", "丙书")]:
        chapters = [(f"p{i:02d}.xhtml", f"{title}{i}", f"{title} 第{i}节正文") for i in range(4)]
        books[stem] = build_epub(tmp_path / f"{stem}.epub", chapters)

    merged = merge_many(list(books.values()), tmp_path / "all.txt", nonce="0011aabbccdd2233")
    assert len(merged.ledger.books) == 3
    assert merged.report["chapters"] == 12
    # 全局索引必须连续覆盖 0..11
    indexes = [c.index for book in merged.ledger.books for c in book.chapters]
    assert indexes == list(range(12))

    restored = restore_many(merged.text_path, merged.ledger_path, list(books.values()), tmp_path / "out")
    assert len(restored) == 3
    for result, stem in zip(restored, ["bookA", "bookB", "bookC"]):
        assert result.book_source == f"{stem}.epub"
        assert result.chapters_changed == 0
        diff = compare_bytes(books[stem], result.epub_path)
        assert diff["byte_identical"] is True
        assert check_epub(result.epub_path).ok


def test_corpus_large_text_multi_book(tmp_path):
    """大文本场景（语料文件夹真实公版书）：多本大书合并→还原，正文零丢失。"""
    stems = ["jinpingmei", "sanguo", "shuihu", "xiyouji"]
    texts = {stem: corpus_text(stem) for stem in stems}
    available = {k: v for k, v in texts.items() if v}
    if len(available) < 2:
        pytest.skip("语料 TXT 不足，跳过大文本场景")

    epubs = {}
    total_chars = 0
    for stem, text in available.items():
        total_chars += len(text)
        chunk = 20_000
        pieces = [text[i : i + chunk] for i in range(0, len(text), chunk)]
        chapters = [(f"part{i:04d}.xhtml", f"{stem} 第{i}节", p.replace("\n", " ").strip() or " ") for i, p in enumerate(pieces)]
        epubs[stem] = build_epub(tmp_path / f"{stem}.epub", chapters)

    assert total_chars > 1_000_000

    merged = merge_many(list(epubs.values()), tmp_path / "all.txt", nonce="feedfacecafe0123")
    restored = restore_many(merged.text_path, merged.ledger_path, list(epubs.values()), tmp_path / "out")
    by_source = {r.book_source: r for r in restored}

    for stem in epubs:
        result = by_source[f"{stem}.epub"]
        assert result.chapters_changed == 0
        content = compare_content(epubs[stem], result.epub_path)
        assert content["missing_text_chapters"] == []
        assert content["text_equal_chapters"] == content["compared_chapters"]
        assert compare_bytes(epubs[stem], result.epub_path)["byte_identical"] is True
