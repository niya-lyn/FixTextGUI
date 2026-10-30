"""M5-EX.7 · UI 对齐抽查（无书胶囊 / EmptyState / 令牌 / QSS）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "fixtext_ui"
sys.path.insert(0, str(UI))


def test_on_fill_token():
    from fixtext_tokens import c
    assert c("on.fill") == "#FFFFFF"
    assert c("on.fill") == c("neutral.0")


def test_qss_no_bookchip_empty_wash():
    qss = (UI / "fixtext.qss").read_text(encoding="utf-8")
    assert '#BookChip[empty="true"]' not in qss
    assert "opacity: 0.5" in qss
    assert "#BtnGhost:pressed" in qss
    # 勿用 #PageHead QLabel / border-bottom（会压标题字号、贴副标题）
    assert "#PageHead QLabel" not in qss
    assert "border-bottom" not in qss or "#PageHead {" not in qss


def test_import_page_title_uses_page_title(qapp, tmp_path):
    from PySide6.QtWidgets import QLabel, QWidget
    import import_module as im

    page = im.ImportModule(workspace_root=tmp_path)
    titles = [l for l in page.findChildren(QLabel) if l.objectName() == "PageTitle"]
    assert len(titles) == 1 and titles[0].text() == "导入书籍"
    heads = [w for w in page.findChildren(QWidget) if w.objectName() == "PageHead"]
    assert heads, "页头须走 page_head_shell"
    page.shutdown()


def test_book_chip_empty_same_glass(qapp):
    import fixtext_shelf_ui as SU

    chip = SU.BookChip()
    chip.set_book(None)
    ss = chip.styleSheet()
    assert "rgba(255,255,255,.10)" not in ss.replace(" ", "")
    assert "qlineargradient" in ss
    assert chip.name.text() == "未选择书"


def test_empty_state_step7_visual(qapp):
    from fixtext_widgets import EmptyState
    from fixtext_tokens import c

    es = EmptyState("⚡", "还没有可校正的书", "描述")
    ss = es.styleSheet()
    assert c("neutral.200") in ss
    assert "dashed" in ss
    assert c("neutral.300") not in ss
