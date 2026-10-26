"""解析层测试：container/OPF/spine/NCX 的解析与顺序语义。"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from epubtext.archive import EpubArchive, candidate_names, normalize_name, resolve_href
from epubtext.errors import EpubStructureError
from epubtext.package import (
    looks_like_chapter_title,
    parse_package,
    reading_order,
    verify_order_against_ncx,
)

from .fixtures import build_epub


def _make(tmp_path: Path, **kwargs) -> Path:
    chapters = [
        ("ch1.xhtml", "第1章 开局", "正文一"),
        ("ch2.xhtml", "第2章 发展", "正文二"),
        ("ch10.xhtml", "第10章 转折", "正文十"),
        ("ch11.xhtml", "第11章 收尾", "正文十一"),
    ]
    return build_epub(tmp_path / "book.epub", chapters, **kwargs)


def test_normalize_name_strips_dot_and_backslash():
    assert normalize_name("./OEBPS/a.xhtml") == "OEBPS/a.xhtml"
    assert normalize_name("OEBPS\\a.xhtml") == "OEBPS/a.xhtml"
    assert normalize_name("/a/b.xhtml") == "a/b.xhtml"
    assert normalize_name("OEBPS/") == ""


def test_resolve_href_handles_parent_and_percent_encoding():
    assert resolve_href("OEBPS", "chapter1.html") == "OEBPS/chapter1.html"
    assert resolve_href("OEBPS/Text", "../Images/a.jpg") == "OEBPS/Images/a.jpg"
    # href 可能是百分号编码；解析保留原形态，由 candidate_names/real_name 负责匹配包内实际条目
    assert resolve_href("OEBPS", "%E7%AC%AC1%E7%AB%A0.xhtml") == "OEBPS/%E7%AC%AC1%E7%AB%A0.xhtml"
    assert "OEBPS/第1章.xhtml" in candidate_names("OEBPS/%E7%AC%AC1%E7%AB%A0.xhtml")
    assert resolve_href("OEBPS", "a.xhtml#frag") == "OEBPS/a.xhtml"


def test_resolve_href_rejects_escape():
    with pytest.raises(EpubStructureError):
        resolve_href("", "../../etc/passwd")


def test_parse_package_uses_spine_order_not_filename(tmp_path):
    """核心验收点：顺序必须来自 spine，文件名排序只是干扰项。"""
    epub = _make(tmp_path, spine=["ch1.xhtml", "ch2.xhtml", "ch10.xhtml", "ch11.xhtml"])
    with EpubArchive(epub) as archive:
        info = parse_package(archive)
    assert [item.path for item in info.spine] == [
        "OEBPS/ch1.xhtml",
        "OEBPS/ch2.xhtml",
        "OEBPS/ch10.xhtml",
        "OEBPS/ch11.xhtml",
    ]
    # 朴素字符串排序会得到不同的顺序，证明确实没有依赖文件名
    assert [item.path for item in info.spine] != sorted(item.path for item in info.spine)


def test_parse_package_respects_custom_spine_permutation(tmp_path):
    """spine 给出的顺序可以与文件名顺序完全不同。"""
    epub = _make(tmp_path, spine=["ch10.xhtml", "ch1.xhtml", "ch11.xhtml", "ch2.xhtml"])
    with EpubArchive(epub) as archive:
        info = parse_package(archive)
    assert [item.path.rsplit("/", 1)[-1] for item in info.spine] == ["ch10.xhtml", "ch1.xhtml", "ch11.xhtml", "ch2.xhtml"]
    assert [node.label for node in info.toc] == ["第10章 转折", "第1章 开局", "第11章 收尾", "第2章 发展"]


def test_ncx_labels_map_to_paths(tmp_path):
    epub = _make(tmp_path)
    with EpubArchive(epub) as archive:
        info = parse_package(archive)
    assert info.label_for("OEBPS/ch2.xhtml") == "第2章 发展"
    assert info.title == "测试书"
    assert info.identifier == "test-book-id"


def test_ncx_order_diverging_from_spine_is_reported(tmp_path):
    """NCX 与 spine 顺序冲突时应被识别，而不是静默接受。"""
    epub = _make(tmp_path, ncx=["ch2.xhtml", "ch1.xhtml", "ch10.xhtml", "ch11.xhtml"])
    with EpubArchive(epub) as archive:
        info = parse_package(archive)
    consistent, notes = verify_order_against_ncx(info)
    assert consistent is False
    assert any("冲突" in note for note in notes)


def test_ncx_subset_of_spine_is_consistent(tmp_path):
    """前置页可以不在 NCX 里：NCX 为 spine 子序列视为一致。"""
    epub = _make(tmp_path, ncx=["ch1.xhtml", "ch2.xhtml"])
    with EpubArchive(epub) as archive:
        info = parse_package(archive)
    consistent, notes = verify_order_against_ncx(info)
    assert consistent is True
    assert any("不在 NCX" in note for note in notes)


def test_nav_document_excluded_from_content_items(tmp_path):
    """EPUB3 nav 文档带 properties=nav，不得混进正文合并。"""
    epub = _make(tmp_path, with_nav=True, spine=["nav.xhtml", "ch1.xhtml", "ch2.xhtml", "ch10.xhtml", "ch11.xhtml"])
    with EpubArchive(epub) as archive:
        info = parse_package(archive)
    assert len(info.spine) == 5
    assert all("nav.xhtml" not in item.path for item in info.content_items)
    assert len(info.content_items) == 4
    assert reading_order(info, include_nav=True)[0] == "OEBPS/nav.xhtml"


def test_linear_no_item_kept_in_spine_but_flag_false(tmp_path):
    """linear="no" 的条目仍在 spine 里（顺序不变），只是标记为非主要阅读顺序。"""
    epub = _make(tmp_path)
    with zipfile.ZipFile(epub) as zf:
        names = {n: zf.read(n) for n in zf.namelist()}
    names["OEBPS/content.opf"] = names["OEBPS/content.opf"].replace(
        b'<itemref idref="item_1"/>', b'<itemref idref="item_1" linear="no"/>'
    )
    target = tmp_path / "linear.epub"
    with zipfile.ZipFile(target, "w") as zf:
        for name, data in names.items():
            zf.writestr(name, data)

    with EpubArchive(target) as archive:
        info = parse_package(archive)
    assert [item.path for item in info.spine] == [
        "OEBPS/ch1.xhtml",
        "OEBPS/ch2.xhtml",
        "OEBPS/ch10.xhtml",
        "OEBPS/ch11.xhtml",
    ]
    assert info.spine[1].linear is False
    assert info.spine[0].linear is True


def test_missing_spine_raises(tmp_path):
    epub = _make(tmp_path)
    with zipfile.ZipFile(epub) as zf:
        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        names = {n: zf.read(n) for n in zf.namelist()}
    broken = opf.replace("<spine toc=\"ncx\">", "<spine-less toc=\"ncx\">").replace("</spine>", "</spine-less>")
    names["OEBPS/content.opf"] = broken.encode("utf-8")
    target = tmp_path / "nospine.epub"
    with zipfile.ZipFile(target, "w") as zf:
        for name, data in names.items():
            zf.writestr(name, data)
    with EpubArchive(target) as archive:
        with pytest.raises(EpubStructureError, match="spine"):
            parse_package(archive)


def test_missing_container_raises(tmp_path):
    target = tmp_path / "nocontainer.epub"
    with zipfile.ZipFile(target, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
    with EpubArchive(target) as archive:
        with pytest.raises(EpubStructureError, match="container"):
            parse_package(archive)


def test_spine_referencing_unknown_id_is_skipped_with_warning(tmp_path):
    epub = _make(tmp_path)
    with zipfile.ZipFile(epub) as zf:
        names = {n: zf.read(n) for n in zf.namelist()}
    names["OEBPS/content.opf"] = names["OEBPS/content.opf"].replace(
        b'<itemref idref="item_1"/>', b'<itemref idref="item_1"/><itemref idref="ghost"/>'
    )
    target = tmp_path / "ghost.epub"
    with zipfile.ZipFile(target, "w") as zf:
        for name, data in names.items():
            zf.writestr(name, data)
    with EpubArchive(target) as archive:
        info = parse_package(archive)
    assert len(info.spine) == 4
    assert any("ghost" in w for w in info.warnings)


def test_chapter_title_detection():
    assert looks_like_chapter_title("第1章 开局")
    assert looks_like_chapter_title("第十二回 风云再起")
    assert looks_like_chapter_title("Chapter 12 The End")
    assert not looks_like_chapter_title("这是一段很长的正文内容，不应该被当成章节标题来处理掉的文字")
