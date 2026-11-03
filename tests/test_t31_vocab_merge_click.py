"""M3-T3.1 词库管理页 · 合并操作**真实点击**链路。

与 ``test_t31_vocab_ui.py`` 的分工：那边为了断言方便直接调 ``open_merge`` /
``do_merge`` / ``_do_merge_commit`` 这三个方法；那边验的是「方法语义对不对」，
验不出「用户点按钮这条路通不通」——按钮没连上槽、弹窗按钮点不动、撤销按钮
藏起来这类问题，直接调方法照样全绿。

本用例只走用户路径：勾选框点一下 → 「合并」按钮点一下 → 弹窗里「预览写入」
点一下 → 二次确认「确认写入」点一下 → 提示条上的「撤销」点一下。
每一步都用 ``QTest.mouseClick`` 对**控件树里找到的真控件**下手，
并用 sha256 证明文件在预览阶段没动、确认后才动、撤销后逐字节回到原样。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from fixtext_ui.fixtext_vocab import VocabStore


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def mod(qapp, tmp_path):
    """自定义词库指向临时文件，内置词库仍读交付包里的真实 304,255 条。"""
    import vocab_module as vm

    m = vm.VocabModule()
    m.store = VocabStore(custom_path=tmp_path / "custom_vocab.json")
    m._page = 0
    m.search = ""
    m.dict_, m.tier = "custom", "custom"
    m._render_all()
    # 真窗口才会算布局：控件尺寸不是 0 时 QTest 的点击才落在控件身上
    m.resize(1280, 800)
    m.show()
    m.set_tier("custom")
    yield m
    for dlg in m.findChildren(vm.QDialog):
        dlg.close()
    m.close()


def _click(qapp, widget):
    """离屏环境下的真实点击：先让布局算完，再对控件中心点一下。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    qapp.processEvents()
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)


def _row_checkboxes(mod):
    """行内勾选框（排除表头那一行的全选）。

    不能用 ``isVisible()``：用例里面板没 ``show()``，离屏下所有控件都报不可见。
    改用「没被显式隐藏」判定——被换页 / 清空时表体控件会 ``setParent(None)``，
    此时 ``findChildren`` 也就找不到了，所以这里只排除顶层那几个控件即可。

    排除名单按「属性存在才算」取：原来还有一个「显示设计依据」的勾选框要排除，
    但它已经在 M5-EX.2（BUG-2）里从界面上删掉了，直接取 ``mod.basis_cb``
    会 AttributeError。改成「取不到就不排除」，界面上以后再增减顶层勾选框，
    这条用例不用跟着改。
    """
    from PySide6.QtWidgets import QCheckBox

    excluded = {id(getattr(mod, name, None)) for name in ("_chk_all", "basis_cb")}
    return [c for c in mod.findChildren(QCheckBox)
            if id(c) not in excluded and not c.isHidden()]


def _button(mod_or_dlg, text: str):
    """按可见文案找按钮——只认用户眼睛能看到的那几个字。"""
    from PySide6.QtWidgets import QPushButton

    for b in mod_or_dlg.findChildren(QPushButton):
        if b.text() == text:
            return b
    raise AssertionError(f"界面上找不到按钮「{text}」")


def test_merge_full_user_click_path(qapp, mod):
    """合并：点勾选 → 点合并 → 点预览写入 → 点确认写入 → 点撤销。"""
    from PySide6.QtWidgets import QDialog

    for w in ("甲词", "乙词", "丙词"):
        mod.store.add_entry(word=w, value=f"{w}替", typ="错词校正")
    mod._render_all()
    qapp.processEvents()

    path = mod.store.custom.path
    sha_before = _sha(path)
    assert len(mod.store.custom) == 3

    # ① 用真实勾选框选中三条（这一步同时验勾选框没被内置行的只读逻辑误伤）
    boxes = _row_checkboxes(mod)
    assert len(boxes) == 3, f"自定义分级应显示 3 行可勾选，实际 {len(boxes)}"
    for box in boxes:
        _click(qapp, box)
    assert len(mod._selected) == 3, f"三次点击后应选中 3 条，实际 {len(mod._selected)}"

    # ② 点工具栏「合并」按钮 → 弹出第一个弹窗（选主词 + 预览清单）
    _click(qapp, mod._merge_btn)
    qapp.processEvents()
    dlgs = [d for d in mod.findChildren(QDialog) if d.isVisible()]
    assert len(dlgs) == 1, f"点合并后应有 1 个弹窗，实际 {len(dlgs)}"
    first = dlgs[0]
    assert first.windowTitle() == "合并词条（先预览清单）", first.windowTitle()
    assert _sha(path) == sha_before, "弹出一级预览时不应写文件"

    # ③ 点一级弹窗的「预览写入」→ 二级确认弹窗
    _click(qapp, _button(first, "预览写入"))
    qapp.processEvents()
    assert _sha(path) == sha_before, "二级确认前不应写文件"
    assert len(mod.store.custom) == 3, "二级确认前词条数不变"

    second = [d for d in mod.findChildren(QDialog) if d.isVisible()]
    assert len(second) == 1, f"二次确认弹窗应唯一，实际 {len(second)}"
    second = second[0]
    assert second.windowTitle() == "写入词库（二次确认）", second.windowTitle()

    # ④ 点「确认写入」→ 真写盘
    _click(qapp, _button(second, "确认写入"))
    qapp.processEvents()
    assert len(mod.store.custom) == 1, f"合并后应保留 1 条，实际 {len(mod.store.custom)}"
    kept = mod.store.custom.entries()[0]["word"]
    assert kept == "甲词", f"应保留第一条为主词，实际保留「{kept}」"
    sha_after = _sha(path)
    assert sha_after != sha_before, "确认写入后文件内容必须变化"

    # ⑤ 提示条上的「撤销」按钮：合并这类批量操作必须给可点的撤销入口
    assert mod.undo_btn.isVisible(), "合并后提示条上应出现可点的撤销按钮"
    _click(qapp, mod.undo_btn)
    qapp.processEvents()
    assert len(mod.store.custom) == 3, f"撤销后应回到 3 条，实际 {len(mod.store.custom)}"
    assert _sha(path) == sha_before, "撤销后文件必须与合并前逐字节一致"
    assert [e["word"] for e in mod.store.custom.entries()] == ["甲词", "乙词", "丙词"]
