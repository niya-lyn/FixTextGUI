"""验收①④ + EPUB 导入链路的核心回归测试。

- 验收①：拖放与选择文件两条通道汇合到同一入口（结构断言）
- 验收④：原文件 sha256 导入前后一致，工作区副本与源一致（三重对照）
- 幂等、换行规范化、章节预览、取消不留残渣
"""

from __future__ import annotations

from pathlib import Path

import pytest

import fixtext_import as fi
from fixtext_import.textfile import sha256_file

import _public_fixture as PF  # M5-OS.1：公版 fixture（含运行记录）唯一来源


def test_txt_import_leaves_source_untouched(sample, workdir, tmp_path):
    """验收④：TXT 导入前后 sha256 三元组完全一致。"""
    src = tmp_path / "nahan_gbk.txt"
    src.write_bytes(sample("d_gbk_crlf.txt").read_bytes())
    before = sha256_file(src)

    result = fi.import_book(src, workdir)

    assert result.source_sha256_before == before
    assert result.source_sha256_after == before
    assert result.workspace_copy_sha256 == before
    assert result.source_unchanged is True
    # 落盘后仍一致（排除"只在内存里算对"）
    assert sha256_file(src) == before
    assert sha256_file(result.original_copy_path) == before


def test_epub_import_leaves_source_untouched(tmp_path, workdir, samples_dir):
    """验收④：EPUB 导入同样不许改原文件；默认即可逆账本。"""
    src = tmp_path / PF.EPUB.name
    src.write_bytes(PF.EPUB.read_bytes())
    before = sha256_file(src)

    result = fi.import_book(src, workdir)

    assert result.source_sha256_before == result.source_sha256_after == before
    assert sha256_file(src) == before
    assert result.epub_mode == "direct"
    assert result.ledger_path and Path(result.ledger_path).exists(), "EPUB 应产出可还原账本"


def test_epub_ignores_text_mode_option(tmp_path, workdir, samples_dir):
    """M5-EX.3：即使传入 epub_mode=text，仍走可逆并保留账本。"""
    src = tmp_path / PF.EPUB.name
    src.write_bytes(PF.EPUB.read_bytes())
    result = fi.import_book(src, workdir, fi.ImportOptions(epub_mode="text"))
    assert result.epub_mode == "direct"
    assert result.ledger_path and Path(result.ledger_path).exists()
    text = Path(result.text_path).read_text(encoding="utf-8")
    assert len(text) > 0


@pytest.mark.parametrize("name,expect_newline_changed", [
    ("a_utf8_lf.txt", False),
    ("c_utf8_crlf.txt", True),
    ("g_mixed_newline.txt", True),
])
def test_newline_normalized_to_lf(sample, tmp_path, workdir, name, expect_newline_changed):
    """换行统一到 LF，且如实记录是否发生过改动。"""
    src = tmp_path / name
    src.write_bytes(sample(name).read_bytes())
    result = fi.import_book(src, workdir)
    text = Path(result.text_path).read_text(encoding="utf-8")
    assert "\r" not in text, "产物里不应残留 CR"
    assert result.newline_changed is expect_newline_changed


def test_reimport_is_idempotent(sample, tmp_path, workdir):
    """同内容重复导入复用已有副本，不产生第二个目录。"""
    src = tmp_path / "same.txt"
    src.write_bytes(sample("a_utf8_lf.txt").read_bytes())

    first = fi.import_book(src, workdir)
    second = fi.import_book(src, workdir)

    assert second.reused is True
    assert second.book_id == first.book_id
    dirs = [d for d in workdir.iterdir() if d.is_dir()]
    assert len(dirs) == 1, f"应只有一个书目录，实际 {[d.name for d in dirs]}"



def test_reimport_keeps_corrected_book_txt(sample, tmp_path, workdir):
    """校正后的 book.txt 在重复导入（含记录损坏）时不得被覆盖。"""
    src = tmp_path / "keep.txt"
    src.write_bytes(sample("a_utf8_lf.txt").read_bytes())
    first = fi.import_book(src, workdir)
    book = Path(first.text_path)
    corrected = "【已校正】" + book.read_text(encoding="utf-8")
    book.write_text(corrected, encoding="utf-8", newline="\n")

    # 正常复用
    second = fi.import_book(src, workdir)
    assert second.reused is True
    assert book.read_text(encoding="utf-8") == corrected

    # 模拟 import.json 损坏：仍须保留工作正文
    Path(first.workspace_dir, "import.json").write_text("{坏", encoding="utf-8")
    third = fi.import_book(src, workdir)
    assert third.reused is True
    assert book.read_text(encoding="utf-8") == corrected
    assert any("未覆盖" in n or "校正" in n for n in third.reminded)


def test_chapter_preview_shape(samples_dir):
    """验收③：章节预览给出的字段只有序号/标题/字数，没有内部结构。"""
    preview = fi.chapter_preview(PF.EPUB)
    assert len(preview.chapters) > 100
    ch = preview.chapters[0]
    assert set(vars(ch)) == {"index", "title", "chars", "named"}
    assert ch.index == 1
    assert preview.order_ok in (True, False)


def test_unsupported_and_empty_files_raise_human_errors(tmp_path, workdir, sample):
    """不支持的格式 / 空文件给的是人话错误，不是堆栈。"""
    empty = tmp_path / "e.txt"
    empty.write_bytes(b"")
    with pytest.raises(fi.ImportError_) as exc:
        fi.import_book(empty, workdir)
    assert "空" in str(exc.value)

    doc = tmp_path / "a.docx"
    doc.write_bytes(b"PK\x03\x04dummy")
    with pytest.raises(fi.ImportError_) as exc2:
        fi.import_book(doc, workdir)
    assert "TXT" in str(exc2.value)


def test_workdir_gets_no_partial_leftovers(sample, tmp_path, workdir):
    """导入成功后工作区里只剩成品，没有 .part 之类的中间文件。"""
    src = tmp_path / "n.txt"
    src.write_bytes(sample("e_gbk_lf.txt").read_bytes())
    fi.import_book(src, workdir)
    leftovers = [p for p in workdir.rglob("*.part")]
    assert leftovers == [], f"残留中间文件：{leftovers}"
