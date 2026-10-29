# -*- coding: utf-8 -*-
"""M5-EX.3 定向自测：导入去向导 + EPUB 统一可逆。"""

from __future__ import annotations

from pathlib import Path

import pytest

import fixtext_import as fi


def test_epub_default_has_ledger(tmp_path, workdir, samples_dir):
    src = tmp_path / "book.epub"
    src.write_bytes((samples_dir / "book_paohuo.epub").read_bytes())
    result = fi.import_book(src, workdir)
    assert result.epub_mode == "direct"
    assert result.ledger_path and Path(result.ledger_path).is_file()
    assert Path(result.text_path).is_file()


def test_txt_import_still_works(sample, tmp_path, workdir):
    src = tmp_path / "a.txt"
    src.write_bytes(sample("a_utf8_lf.txt").read_bytes())
    result = fi.import_book(src, workdir)
    assert result.epub_mode == "text"
    assert result.ledger_path is None
    assert Path(result.text_path).read_text(encoding="utf-8")


def test_import_module_no_wizard_attrs(qt_app, tmp_path):
    """界面不再暴露向导步骤控件。"""
    pytest.importorskip("PySide6")
    from import_module import ImportModule

    mod = ImportModule(tmp_path / "ws")
    assert not hasattr(mod, "choose_pane")
    assert not hasattr(mod, "chapter_pane")
    assert not hasattr(mod, "dots")
    assert hasattr(mod, "drop_zone")
    assert hasattr(mod, "status_card")
    assert hasattr(mod, "result_pane")
    mod.shutdown()
