"""M5-EX.6：导出页元信息随书切换，初始化清空后不残留旧书名。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "fixtext_ui"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@pytest.fixture()
def export_mod(qt_app, tmp_path):
    from export_module import ExportModule

    mod = ExportModule()
    # 避免默认导出目录碰真实包根
    mod._default_out_dir = str(tmp_path / "导出")
    yield mod
    mod.deleteLater()


def _book(tmp_path: Path, name: str, title: str, author: str = "") -> dict:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    txt = d / "book.txt"
    txt.write_text("正文", encoding="utf-8")
    return {
        "title": title,
        "author": author,
        "text_path": str(txt),
        "kind": "txt",
    }


def test_clear_context_clears_stale_title(export_mod, tmp_path):
    """初始化后 set_context(None) 必须清掉上一本书名。"""
    export_mod.set_context(_book(tmp_path, "a", "我的玩家二周目", "甲"))
    assert export_mod.title_edit.text() == "我的玩家二周目"
    export_mod.set_context(None)
    assert export_mod.title_edit.text() == ""
    assert export_mod.author_edit.text() == ""


def test_switch_book_replaces_title(export_mod, tmp_path):
    """换书后书名必须换成新书，不能因输入框非空而留着旧名。"""
    export_mod.set_context(_book(tmp_path, "old", "我的玩家二周目", "甲"))
    export_mod.set_context(_book(tmp_path, "new", "炮火弧线", "康斯坦丁伯爵"))
    assert export_mod.title_edit.text() == "炮火弧线"
    assert export_mod.author_edit.text() == "康斯坦丁伯爵"


def test_same_book_keeps_user_edit(export_mod, tmp_path):
    """同一本书上用户改过的书名不被 refresh 冲掉。"""
    rec = _book(tmp_path, "one", "炮火弧线")
    export_mod.set_context(rec)
    export_mod.title_edit.setText("我改的书名")
    export_mod.set_context(rec)  # 同路径再注入
    assert export_mod.title_edit.text() == "我改的书名"
