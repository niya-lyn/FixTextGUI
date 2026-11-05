"""M3-T3.1 词库管理页 · 去重合并**真实点击**链路（V1.1-EX.2R 重定向）。

与 ``test_t31_vocab_ui.py`` 的分工：那边为了断言方便直接调 ``_dup_keep_one`` /
``_dup_dedup_same`` 这类方法；那边验的是「方法语义对不对」，验不出「用户点
按钮这条路通不通」——按钮没连上槽、弹窗按钮点不动、撤销按钮藏起来这类问题，
直接调方法照样全绿。

V1.1-EX.2R 起，「合并」不再是工具条上的独立按钮（整块下线），它成为查重
清单里的组内动作。所以本用例只走用户路径：

  点「查重」→ 清单里那一组的「保留这一条」→ 改动清单「确认保留」→ 提示条「撤销」

每一步都用 ``QTest.mouseClick`` 对**控件树里找到的真控件**下手，并用 sha256
证明文件在预览阶段没动、确认后才动、撤销后逐字节回到原样。
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
    # MRG.12：行内勾选由 QCheckBox 换成 ChkMark 自绘件（UI 分支视觉，主干选择语义不变）
    from fixtext_widgets import ChkMark

    excluded = {id(getattr(mod, name, None)) for name in ("_chk_all", "basis_cb")}
    return [c for c in mod.findChildren(ChkMark)
            if id(c) not in excluded and not c.isHidden()]


def _button(mod_or_dlg, text: str):
    """按可见文案找按钮——只认用户眼睛能看到的那几个字。"""
    from PySide6.QtWidgets import QPushButton

    for b in mod_or_dlg.findChildren(QPushButton):
        if b.text() == text:
            return b
    raise AssertionError(f"界面上找不到按钮「{text}」")


def test_merge_via_dup_dialog_full_user_click_path(qapp, mod):
    """合并（新路径）：点查重 → 组内选一条 → 确认保留 → 撤销。"""
    from PySide6.QtWidgets import QComboBox, QDialog

    for v in ("甲替", "乙替", "丙替"):
        mod.store.add_entry(word="甲词", value=v, typ="错词校正")
    mod._render_all()
    qapp.processEvents()

    path = mod.store.custom.path
    sha_before = _sha(path)
    assert len(mod.store.custom) == 3

    # ① 点工具条「查重」按钮 → 清单弹窗（这一步不许动文件）
    dup_btn = _button(mod, "🔁 查重")
    _click(qapp, dup_btn)
    qapp.processEvents()
    dlgs = [d for d in mod.findChildren(QDialog) if d.isVisible()]
    assert len(dlgs) == 1, f"点查重后应有 1 个弹窗，实际 {len(dlgs)}"
    dlg = dlgs[0]
    assert dlg.windowTitle() == "查重清单（可逐条处理）", dlg.windowTitle()
    assert _sha(path) == sha_before, "打开查重清单不应写文件"
    assert mod._dup_view["readonly"] is False, "查重清单已改为可处理"

    # ② 组内：在清单里把下拉选到「甲词 → 乙替」，再点「保留这一条」
    combo = dlg.findChildren(QComboBox)[0]
    idx = next(i for i in range(combo.count()) if combo.itemText(i).endswith("乙替"))
    combo.setCurrentIndex(idx)
    qapp.processEvents()
    _click(qapp, _button(dlg, "保留这一条"))
    qapp.processEvents()
    assert _sha(path) == sha_before, "组内动作第一层只是改动清单"
    assert len(mod.store.custom) == 3

    # ③ 改动清单里点「确认保留「乙替」」→ 真写盘
    # 清单弹窗本身也还开着，改动清单是后建的那个（取最后一个可见弹窗）
    confirm = [d for d in mod.findChildren(QDialog) if d.isVisible()]
    confirm = confirm[-1]
    assert confirm.windowTitle() == "合并确认（先看改动）", confirm.windowTitle()
    _click(qapp, _button(confirm, "确认保留「乙替」"))
    qapp.processEvents()
    assert len(mod.store.custom) == 1, f"合并后应保留 1 条，实际 {len(mod.store.custom)}"
    kept = mod.store.custom.entries()[0]
    assert kept["word"] == "甲词" and kept["value"] == "乙替", kept
    sha_after = _sha(path)
    assert sha_after != sha_before, "确认写入后文件内容必须变化"

    # ④ 提示条上的「撤销」：批量动作必须给可点的撤销入口
    assert mod.undo_btn.isVisible(), "合并后提示条上应出现可点的撤销按钮"
    _click(qapp, mod.undo_btn)
    qapp.processEvents()
    assert len(mod.store.custom) == 3, f"撤销后应回到 3 条，实际 {len(mod.store.custom)}"
    assert _sha(path) == sha_before, "撤销后文件必须与合并前逐字节一致"
    assert [e["value"] for e in mod.store.custom.entries()] == ["甲替", "乙替", "丙替"]


def test_dedup_same_value_via_dup_dialog_full_user_click_path(qapp, mod):
    """去重（新路径）：点查重 → 组内「一键去重」→ 确认去重 → 撤销。"""
    from PySide6.QtWidgets import QDialog

    for _ in range(3):
        mod.store.add_entry(word="乙词", value="同值", typ="错词校正")
    mod._render_all()
    qapp.processEvents()

    path = mod.store.custom.path
    sha_before = _sha(path)

    _click(qapp, _button(mod, "🔁 查重"))
    qapp.processEvents()
    dlg = [d for d in mod.findChildren(QDialog) if d.isVisible()][0]
    assert _sha(path) == sha_before, "打开查重清单不应写文件"

    _click(qapp, _button(dlg, "一键去重"))
    qapp.processEvents()
    assert _sha(path) == sha_before, "组内动作第一层只是改动清单"

    confirm = [d for d in mod.findChildren(QDialog) if d.isVisible()][-1]
    assert confirm.windowTitle() == "去重确认（先看改动）", confirm.windowTitle()
    _click(qapp, _button(confirm, "确认去重 2 条"))
    qapp.processEvents()
    assert len(mod.store.custom) == 1, f"去重后应剩 1 条，实际 {len(mod.store.custom)}"
    assert _sha(path) != sha_before, "确认后文件内容必须变化"

    assert mod.undo_btn.isVisible(), "去重后提示条上应出现可点的撤销按钮"
    _click(qapp, mod.undo_btn)
    qapp.processEvents()
    assert len(mod.store.custom) == 3
    assert _sha(path) == sha_before, "撤销后文件必须与去重前逐字节一致"
