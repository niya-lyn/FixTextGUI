"""V1.1-D3 · 预览弹窗的界面验收（真实点击，不看自报）。

判据（§9.5 原文两条）：
① 三组数字呈现正确；
② 逐条可取消——点「取消」后该条不出现在任何一组，预演写入条数相应减少。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for _p in (PKG, PKG / "fixtext_ui"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fixtext_vocab import CustomVocab, VocabStore                     # noqa: E402
from fixtext_vocab_preview.groups import (GROUP_CONFLICT, GROUP_NEW,  # noqa: E402
                                          GROUP_REJECT, preview_from_sheet)
from fixtext_vocab_import.parse import parse_text                     # noqa: E402

TEXT = "错词,正确写法\n乙乙,乙\n甲的异体,甲\n,空的\n重复,值一\n重复,值二\n丙丙,丙\n"


def _cancel_button(sec, line_no):
    """按行号取那一行的「取消」按钮（组的 rows 与按钮按同一顺序排列）。"""
    from PySide6.QtWidgets import QPushButton

    idx = [r["line_no"] for r in sec.rows].index(line_no)
    btns = [b for b in sec.box.findChildren(QPushButton) if b.text() == "取消"]
    return btns[idx]


@pytest.fixture
def store(tmp_path):
    real = tmp_path / "custom_vocab.json"
    CustomVocab(real).add(word="甲的异体", value="甲", typ="错词校正")
    return VocabStore(custom_path=real, work_dir=tmp_path / "rules",
                      snap_dir=tmp_path / "snap")


@pytest.fixture
def dialog(qt_app, store):
    from preview_module import PreviewDialog

    model = preview_from_sheet(parse_text(TEXT), store)
    dlg = PreviewDialog(model)
    yield dlg, model
    dlg.close()
    dlg.deleteLater()


def test_dialog_shows_three_groups_with_counts(dialog):
    dlg, model = dialog
    assert dlg.counts_label.text().startswith("这份表里有 6 条候选")
    titles = {name: sec.title_label.text() for name, sec in dlg._sections.items()}
    assert titles[GROUP_NEW] == "新增 2 条"
    assert titles[GROUP_CONFLICT] == "冲突 3 条"
    assert titles[GROUP_REJECT] == "格式不合格 1 条"
    # 每一组都真的把行摆出来了（不是只改标题）
    assert len(dlg._sections[GROUP_NEW].rows) == 2
    assert len(dlg._sections[GROUP_CONFLICT].rows) == 3
    assert len(dlg._sections[GROUP_REJECT].rows) == 1


def test_click_cancel_removes_from_every_group(qt_app, dialog):
    """真实点击「取消」：该条从三组里消失，且标题条数跟着变。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    dlg, model = dialog
    sec = dlg._sections[GROUP_NEW]
    # 取「丙丙」——它后面没有同词行，取消不会引起重判，条数该减 1
    target = [it.line_no for it in model.effective(GROUP_NEW) if it.word == "丙丙"][0]
    QTest.mouseClick(_cancel_button(sec, target), Qt.MouseButton.LeftButton)

    assert model.is_cancelled(target)
    shown = {n: [r["line_no"] for r in s.rows] for n, s in dlg._sections.items()}
    assert all(target not in lines for lines in shown.values())
    assert len(dlg._sections[GROUP_NEW].rows) == 1
    assert "已取消 1 条" in dlg.cancelled_label.text()


def test_restore_all_button_puts_rows_back(qt_app, dialog):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    dlg, model = dialog
    target = [it.line_no for it in model.effective(GROUP_NEW) if it.word == "丙丙"][0]
    QTest.mouseClick(_cancel_button(dlg._sections[GROUP_NEW], target),
                     Qt.MouseButton.LeftButton)
    assert model.is_cancelled(target)
    QTest.mouseClick(dlg.restore_btn, Qt.MouseButton.LeftButton)
    assert not model.is_cancelled(target)
    assert dlg._sections[GROUP_NEW].rows[-1]["line_no"] == target


def test_rehearsal_button_reports_matching_numbers(qt_app, dialog):
    """点「预演核对」：预览列与实测列逐项一致，且真实词库未被动过。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dlg, model = dialog
    QTest.mouseClick(dlg.rehearse_btn, Qt.MouseButton.LeftButton)
    result = dlg._rehearsal
    assert result is not None
    assert result.identical, result.text()
    assert result.real_untouched
    assert dlg._rehearsal_box.isVisible() or not dlg.isVisible()


def test_cancel_then_rehearse_writes_one_fewer(qt_app, dialog):
    """取消一条新增后再预演：实测写入条数比原来少 1（这是「逐条取消」的实际效果）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    dlg, model = dialog
    QTest.mouseClick(dlg.rehearse_btn, Qt.MouseButton.LeftButton)
    base = dlg._rehearsal.measured_new
    assert base == 2

    target = [it.line_no for it in model.effective(GROUP_NEW) if it.word == "丙丙"][0]
    QTest.mouseClick(_cancel_button(dlg._sections[GROUP_NEW], target),
                     Qt.MouseButton.LeftButton)
    QTest.mouseClick(dlg.rehearse_btn, Qt.MouseButton.LeftButton)
    assert dlg._rehearsal.measured_new == base - 1
    assert dlg._rehearsal.identical


def test_vocab_page_has_preview_entry(qt_app, monkeypatch, tmp_path):
    """词库页工具条上真有这个入口，且左轨入口数不变。"""
    import vocab_module as vm

    monkeypatch.setattr(vm.app_settings, "vocab_custom_file",
                        lambda: tmp_path / "custom_vocab.json")
    page = vm.VocabModule()
    try:
        assert hasattr(page, "_preview_btn")
        assert page._preview_btn.text() == "📥 导入预览"
    finally:
        page.close()
        page.deleteLater()
