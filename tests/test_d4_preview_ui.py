"""V1.1-D4 · 预览弹窗的冲突处置与二次确认（真实点击，不看自报）。

判据：
① 三种处置都能在界面上操作，状态可见，可撤销到导入前；
② 「确认执行」前弹二次确认，正文是影响预览的四个数字（与预演实测一致）；
③ 还有冲突没处置时，确认被拦下并给出人话原因。
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
from fixtext_vocab_import.parse import parse_text                     # noqa: E402
from fixtext_vocab_preview import (ACTION_DISABLE, ACTION_EDIT,       # noqa: E402
                                   ACTION_SKIP, EFFECT_ADD, EFFECT_DISABLED,
                                   EFFECT_SKIPPED, GROUP_CONFLICT, GROUP_NEW,
                                   preview_from_sheet)

TEXT = "错词,正确写法\n乙乙,乙\n甲的异体,甲\n,空的\n重复,值一\n重复,值二\n丙丙,丙\n"


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


def _buttons(sec, line_no, text):
    """取某一行上文字为 `text` 的按钮（行与控件按同一顺序排列）。

    一行的按钮顺序固定：改值 / 跳过 / 设为禁用 / 撤销 / 取消，
    所以按「所有行同一文字的第 idx 个」取，与 D3 的取法同构。
    """
    from PySide6.QtWidgets import QPushButton

    idx = [r["line_no"] for r in sec.rows].index(line_no)
    btns = [b for b in sec.box.findChildren(QPushButton) if b.text() == text]
    return btns[idx]


# ---------- ① 三种处置在界面上可操作、状态可见 ----------

def test_conflict_rows_have_three_action_buttons(qt_app, dialog):
    """冲突组每行都有改值 / 跳过 / 设为禁用三个按钮，新增组没有。"""
    from PySide6.QtWidgets import QPushButton

    dlg, model = dialog
    sec = dlg._sections[GROUP_CONFLICT]
    labels = [b.text() for b in sec.box.findChildren(QPushButton)]
    for want in ("改值", "跳过", "设为禁用"):
        assert want in labels, f"冲突行缺少「{want}」按钮"
    assert len(sec.rows) == 3
    # 新增组只有取消，不给处置按钮（它本来就不冲突）
    new_labels = [b.text() for b in dlg._sections[GROUP_NEW].box.findChildren(QPushButton)]
    assert "改值" not in new_labels and "跳过" not in new_labels


def test_click_edit_uses_the_typed_value(qt_app, dialog):
    """真实操作「改值」：填的新写法被采纳，该条按新值重判。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dlg, model = dialog
    sec = dlg._sections[GROUP_CONFLICT]
    line = [r["line_no"] for r in sec.rows if r["word"] == "乙乙"][0]
    inp = sec.inputs[line]
    inp.setText("乙乙乙")                       # 用户真在这个框里打字
    QTest.mouseClick(_buttons(sec, line, "改值"), Qt.MouseButton.LeftButton)

    item = model.find(line)
    assert item.action == ACTION_EDIT
    assert item.effective_value == "乙乙乙"
    assert item.effect == EFFECT_ADD
    # 状态在那一行上看得见（不是只有内部状态变了）
    row = [r for r in dlg._sections[GROUP_CONFLICT].rows + dlg._sections[GROUP_NEW].rows
           if r["line_no"] == line]
    assert any("乙乙乙" in (r["state"] or "") for r in row)
    # 数字跟着变：影响预览里新增多了这一条
    assert "新增" in dlg.impact_label.text()


def test_click_skip_removes_item_from_write_list(qt_app, dialog):
    """真实点「跳过」：该条不进写入清单，界面写着它被跳过。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dlg, model = dialog
    sec = dlg._sections[GROUP_CONFLICT]
    line = [r["line_no"] for r in sec.rows if r["word"] == "重复"][0]
    QTest.mouseClick(_buttons(sec, line, "跳过"), Qt.MouseButton.LeftButton)

    item = model.find(line)
    assert item.action == ACTION_SKIP
    assert item.effect == EFFECT_SKIPPED
    assert line not in {d["line_no"] for d in model.write_list()}
    state = [r["state"] for r in sec.rows if r["line_no"] == line][0]
    assert "跳过" in state


def test_click_disable_marks_item_disabled(qt_app, dialog):
    """真实点「设为禁用」：写入清单里该条带禁用标记，状态栏看得到。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dlg, model = dialog
    sec = dlg._sections[GROUP_CONFLICT]
    line = [r["line_no"] for r in sec.rows if r["word"] == "重复"][0]
    QTest.mouseClick(_buttons(sec, line, "设为禁用"), Qt.MouseButton.LeftButton)

    item = model.find(line)
    assert item.action == ACTION_DISABLE
    assert item.effect == EFFECT_DISABLED
    wl = {d["line_no"]: d for d in model.write_list()}
    assert wl[line]["disabled"] is True
    state = [r["state"] for r in sec.rows if r["line_no"] == line][0]
    assert "禁用" in state
    assert "禁用 1 条" in dlg.impact_label.text()


def test_undo_button_returns_row_to_undisposed(qt_app, dialog):
    """处置后「撤销」：退回还没处置，影响预览跟着退回去。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dlg, model = dialog
    sec = dlg._sections[GROUP_CONFLICT]
    line = [r["line_no"] for r in sec.rows if r["word"] == "重复"][0]
    before = dict(model.write_plan())

    QTest.mouseClick(_buttons(sec, line, "跳过"), Qt.MouseButton.LeftButton)
    assert model.action_of(line) == ACTION_SKIP

    # 重画之后行还是同一行，取它现在那颗「撤销」
    sec = dlg._sections[GROUP_CONFLICT]
    QTest.mouseClick(_buttons(sec, line, "撤销"), Qt.MouseButton.LeftButton)
    assert model.action_of(line) == ""
    assert model.write_plan() == before


def test_restore_all_clears_dispositions(qt_app, dialog):
    """「全部撤销」把处置与取消一起退掉，回到刚打开预览的样子。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dlg, model = dialog
    sec = dlg._sections[GROUP_CONFLICT]
    line = [r["line_no"] for r in sec.rows if r["word"] == "重复"][0]
    QTest.mouseClick(_buttons(sec, line, "设为禁用"), Qt.MouseButton.LeftButton)
    assert model.dispositions

    QTest.mouseClick(dlg.restore_btn, Qt.MouseButton.LeftButton)
    assert model.dispositions == {}
    assert model.write_plan()["pending"] == 3          # 三条冲突都还没处置
    assert model.write_plan()["disabled"] == 0


# ---------- ② 二次确认与影响预览 ----------

def test_confirm_is_blocked_while_conflicts_undisposed(qt_app, dialog):
    """还有冲突没处置：不弹确认，页内给一句人话原因。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dlg, model = dialog
    assert len(model.pending_items()) == 3
    QTest.mouseClick(dlg.confirm_btn, Qt.MouseButton.LeftButton)
    assert dlg._confirmed is False
    assert dlg.tip_label.isVisible() or not dlg.isVisible()
    assert "还没处置" not in dlg.tip_label.text() or "条冲突" in dlg.tip_label.text()
    assert "3" in dlg.tip_label.text()


def test_confirm_opens_second_dialog_with_impact_numbers(qt_app, dialog):
    """处置完冲突后点「确认执行」：先弹二次确认，正文是四个数字。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dlg, model = dialog
    sec = dlg._sections[GROUP_CONFLICT]
    by_word = {r["word"]: r["line_no"] for r in sec.rows}
    # 三条冲突各给一个处置：乙乙改值、甲的异体跳过、重复设禁用
    sec.inputs[by_word["乙乙"]].setText("乙乙乙")
    QTest.mouseClick(_buttons(sec, by_word["乙乙"], "改值"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_buttons(dlg._sections[GROUP_CONFLICT], by_word["甲的异体"], "跳过"),
                     Qt.MouseButton.LeftButton)
    QTest.mouseClick(_buttons(dlg._sections[GROUP_CONFLICT], by_word["重复"], "设为禁用"),
                     Qt.MouseButton.LeftButton)
    assert model.pending_items() == []

    plan = dict(model.write_plan())
    QTest.mouseClick(dlg.confirm_btn, Qt.MouseButton.LeftButton)

    conf = dlg.confirm_dialog
    assert conf is not None, "没有弹出二次确认"
    assert dlg._confirmed is False, "确认弹窗还没被确认，不该已经算确认"
    text = conf.windowTitle() + "|" + "|".join(
        lab.text() for lab in conf.findChildren(type(dlg.counts_label)))
    assert "确认执行" in text
    for n in (plan["write"], plan["add"], plan["update"], plan["disabled"],
              plan["skipped"]):
        assert str(n) in text, f"影响预览里少了数字 {n}"
    # 文案就是模型的 impact_text，不是界面自己拼的
    assert model.impact_text() in text

    conf.accept()                        # 用户点确认
    assert dlg._confirmed is True
    assert dlg._confirmed_plan["write"] == plan["write"]
    assert len(dlg._write_list) == plan["write"]


def test_cancel_in_second_dialog_does_not_confirm(qt_app, dialog):
    """二次确认里点取消：不进入写入流程。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dlg, model = dialog
    for line in [it.line_no for it in model.pending_items()]:
        model.skip(line)
    dlg.refresh()

    QTest.mouseClick(dlg.confirm_btn, Qt.MouseButton.LeftButton)
    assert dlg.confirm_dialog is not None
    dlg.confirm_dialog.reject()
    assert dlg._confirmed is False
    assert dlg._write_list == []


def test_impact_numbers_equal_rehearsal_numbers(qt_app, dialog):
    """影响预览的四个数字 = 预演实测的四个数字（同一份来源，两列对照）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dlg, model = dialog
    sec = dlg._sections[GROUP_CONFLICT]
    by_word = {r["word"]: r["line_no"] for r in sec.rows}
    sec.inputs[by_word["乙乙"]].setText("乙乙乙")
    QTest.mouseClick(_buttons(sec, by_word["乙乙"], "改值"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_buttons(dlg._sections[GROUP_CONFLICT], by_word["甲的异体"], "跳过"),
                     Qt.MouseButton.LeftButton)
    QTest.mouseClick(_buttons(dlg._sections[GROUP_CONFLICT], by_word["重复"], "设为禁用"),
                     Qt.MouseButton.LeftButton)

    plan = dict(model.write_plan())
    QTest.mouseClick(dlg.rehearse_btn, Qt.MouseButton.LeftButton)
    res = dlg._rehearsal
    assert res.identical, res.text()
    assert res.measured_update == plan["update"]
    assert res.measured_disabled == plan["disabled"]
    assert res.measured_skipped == plan["skipped"]
    assert res.measured_new == plan["new"]
    # 影响预览那一行写的也是这几个数
    assert model.impact_text() == dlg.impact_label.text()
