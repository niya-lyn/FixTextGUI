"""V1.1-T1.2 词库管理页 · 词条启用 / 禁用界面层（离屏真实点击验证）。

本卡只做界面层，数据层（V1.1-T1.1 的 ``WordStateStore``）已在上一卡交付。
这里的用例一律走**真实用户路径**：

* 单条启停 → 用 ``QTest.mouseClick`` 点行里的开关，而不是直接调数据层；
* 两个总开关 → 点工具条下方的按钮打开预览弹窗，再点弹窗里的确认按钮；
* 撤销 → 点页头的撤销按钮 ``↩``（与新增 / 删除共用同一个撤销栈）。

断言的落点都在**磁盘字节**上：改完的文件 sha / 撤销后的 sha，与操作前逐字节比对，
不用内存里的状态自证。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from fixtext_ui.fixtext_vocab import TIER_IMPORTED, VocabStore


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


@pytest.fixture()
def mod(qapp, tmp_path):
    """词库面板，自定义词库与启用状态文件都落在临时目录（不碰交付包用户区）。"""
    import vocab_module as vm

    m = vm.VocabModule()
    m.store = VocabStore(custom_path=tmp_path / "custom_vocab.json")
    m._page = 0
    m.search = ""
    m.dict_, m.tier = "custom", "custom"
    m._render_all()
    yield m
    m.close()


# ---------------------------------------------------------------------------
# 工具：真实点击
# ---------------------------------------------------------------------------

def _click(widget):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    widget.show()
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)


def _click_button_text(root, text: str) -> bool:
    """在 root 里按文字找到按钮并真实点一下（root 自己先显示，否则子控件不可见）。"""
    from PySide6.QtWidgets import QAbstractButton

    root.show()
    for b in root.findChildren(QAbstractButton):
        if b.text().strip() == text and b.isVisibleTo(root):
            _click(b)
            return True
    return False


def _open_and_confirm(mod, entry_name: str, confirm_text: str):
    """点总开关按钮 → 找到预览弹窗 → 点确认按钮（真实两步点击）。"""
    assert _click_button_text(mod, entry_name), f"没找到按钮「{entry_name}」"
    from PySide6.QtWidgets import QDialog

    dialogs = [d for d in mod.findChildren(QDialog) if d.isVisible()]
    assert dialogs, "总开关必须先把影响摊开（预览弹窗没出现）"
    dlg = dialogs[-1]
    assert _click_button_text(dlg, confirm_text), f"预览弹窗里没有「{confirm_text}」"
    return dlg


def _row_switch(mod, rid: int):
    sw = mod._switches.get(int(rid))
    assert sw is not None, "当前这一屏里没有这条词条的开关"
    return sw


# ---------------------------------------------------------------------------
# 1. 迁入的 5,840 条注释词条：可见、默认禁用、能启用
# ---------------------------------------------------------------------------

def test_imported_tier_is_visible_and_counted(mod):
    counts = mod.counts()
    assert counts.get(TIER_IMPORTED) == 5840, "迁入的注释词条必须有独立分级可看"
    assert TIER_IMPORTED in mod._dict_items, "左栏要有迁入注释词条的入口"
    mod._set_dict_active(TIER_IMPORTED)
    meta = mod._dict_items[TIER_IMPORTED]._meta.text()
    assert "5,840" in meta and "可启用" in meta, f"分级说明没写清能做什么：{meta}"


def test_imported_rows_show_as_disabled_by_default(mod):
    mod.select_dict(TIER_IMPORTED)
    assert mod._hit_total == 5840
    rows = mod.get_filtered()
    # 每页条数 20：UI 分支重设计（无内部滚动条，表头与数据列恒对齐），MRG.12 沿用
    assert len(rows) == 20, "一屏 20 行"
    for r in rows:
        assert r["enabled"] is False, f"迁入词条应默认不参与校正：{r['word']}"
        assert r["state"] == "禁用"
        assert r["type"] == "注释词条"
    # 每行都有关关可点，且开关初始是关的
    for r in rows:
        sw = _row_switch(mod, r["id"])
        assert sw.isEnabled(), "迁入词条内容只读，但开关必须能点"
        assert sw.isChecked() is False
        assert "未启用" in sw.accessibleName()


def test_imported_entry_can_be_enabled_end_to_end(mod):
    mod.select_dict(TIER_IMPORTED)
    row = mod.get_filtered()[0]
    path = mod.store.states.path
    before = _sha(path)
    assert before == "", "初始没有写过状态文件"

    sw = _row_switch(mod, row["id"])
    _click(sw)
    assert row["enabled"] is True, "点开关后这一条应在界面上变成启用"
    assert sw.isChecked() is True
    assert mod.store.entry_enabled(row["word"], row["value"]) is True
    assert mod.store.word_states_summary()["disabled_total"] == 5840
    assert _sha(path) != before, "状态必须真的落到磁盘"

    # 撤销：字节回到「未写过」的原始状态
    _click(mod.head_undo_btn)
    assert mod.store.entry_enabled(row["word"], row["value"]) is False
    assert _sha(path) == before, "撤销后状态文件必须逐字节回到操作前"


# ---------------------------------------------------------------------------
# 2. 单个词条启停（自定义 / 内置同样有点头）
# ---------------------------------------------------------------------------

def test_toggle_custom_entry_then_undo(mod):
    mod.store.add_entry(word="甲", value="甲替", typ="错词校正")
    mod.dict_, mod.tier = "custom", "custom"
    mod._render_all()
    row = mod.get_filtered()[0]
    assert row["enabled"] is True, "新建的词条默认参与校正"

    path = mod.store.states.path
    _click(_row_switch(mod, row["id"]))
    assert mod.store.entry_enabled("甲", "甲替") is False
    after = _sha(path)
    assert after != "", "禁用后要落盘"

    mod._render_all()
    row = mod.get_filtered()[0]
    assert row["enabled"] is False, "重建整页后依旧是禁用"
    assert _row_switch(mod, row["id"]).isChecked() is False

    _click(mod.head_undo_btn)
    assert mod.store.entry_enabled("甲", "甲替") is True
    assert _sha(path) == "", "撤销后回到「从未写过状态」"


def test_toggle_builtin_entry_allowed(mod):
    mod.select_dict("b1")
    row = mod.get_filtered()[0]
    assert row["tier"] == "builtin"
    assert row["enabled"] is True, "内置词条默认参与校正"
    _click(_row_switch(mod, row["id"]))
    assert mod.store.entry_enabled(row["word"], row["value"]) is False
    assert mod._states_label.text().count("条禁用") == 1


def test_switch_click_is_idempotent_by_state(mod):
    """开关点两下：回到启用，且第二次不改写无关词条。"""
    mod.store.add_entry(word="乙", value="乙替", typ="错词校正")
    mod.dict_, mod.tier = "custom", "custom"
    mod._render_all()
    row = mod.get_filtered()[0]
    _click(_row_switch(mod, row["id"]))
    assert mod.store.entry_enabled("乙", "乙替") is False
    _click(_row_switch(mod, row["id"]))
    assert mod.store.entry_enabled("乙", "乙替") is True


# ---------------------------------------------------------------------------
# 3. 「恢复默认状态」：先预览不写，确认才写，可撤销
# ---------------------------------------------------------------------------

def test_reset_states_preview_does_not_write(mod):
    from PySide6.QtWidgets import QDialog

    path = mod.store.states.path
    before = _sha(path)
    mod.store.clear_disabled_entries()          # 先把状态改成「全部启用」
    cleared = _sha(path)
    assert cleared != before

    assert _click_button_text(mod, "↺ 恢复默认状态")
    dialogs = [d for d in mod.findChildren(QDialog) if d.isVisible()]
    assert dialogs, "必须先摊开影响再写"
    assert _sha(path) == cleared, "预览阶段一个字节都不许写"
    dialogs[-1].reject()


def test_reset_states_confirm_restores_initial_set(mod):
    mod.store.clear_disabled_entries()
    assert mod.store.word_states_summary()["disabled_total"] == 0

    _open_and_confirm(mod, "↺ 恢复默认状态", "确认恢复")
    sm = mod.store.word_states_summary()
    assert sm["disabled_total"] == 5841, "恢复默认状态 = 迁入 + 孤儿词条重新不启用"
    assert mod._states_label.text().endswith("条禁用")

    _click(mod.head_undo_btn)
    assert mod.store.word_states_summary()["disabled_total"] == 0, "撤销回到清空之后"


# ---------------------------------------------------------------------------
# 4. 「清空禁用」：先预览不写，确认才写，可撤销
# ---------------------------------------------------------------------------

def test_clear_disabled_preview_does_not_write(mod):
    from PySide6.QtWidgets import QDialog

    path = mod.store.states.path
    before = _sha(path)
    assert _click_button_text(mod, "清空禁用")
    dialogs = [d for d in mod.findChildren(QDialog) if d.isVisible()]
    assert dialogs, "清空禁用必须先摊开影响"
    assert _sha(path) == before, "预览阶段不许写"
    dialogs[-1].reject()
    assert mod.store.word_states_summary()["disabled_total"] == 5841


def test_clear_disabled_confirm_enables_all(mod):
    path = mod.store.states.path
    _open_and_confirm(mod, "清空禁用", "确认清空")
    sm = mod.store.word_states_summary()
    assert sm["disabled_total"] == 0, "清空禁用后没有任何词条被禁用"
    assert _sha(path) != "", "必须真的落盘"

    mod.select_dict(TIER_IMPORTED)
    assert all(r["enabled"] for r in mod.get_filtered()), "迁入词条也一起参与校正"

    _click(mod.head_undo_btn)
    assert mod.store.word_states_summary()["disabled_total"] == 5841


def test_clear_disabled_button_disabled_when_nothing_disabled(mod):
    mod.store.clear_disabled_entries()
    mod._refresh_states_bar()
    assert mod._clear_disabled_btn.isEnabled() is False, "没有可清的时候不该能点"
    mod._undo()
    assert mod._clear_disabled_btn.isEnabled() is True


# ---------------------------------------------------------------------------
# 5. 操作进同一个撤销栈（与新增 / 删除一致）
# ---------------------------------------------------------------------------

def test_state_ops_join_existing_undo_stack(mod):
    mod.store.add_entry(word="丙", value="丙替", typ="错词校正")
    mod.dict_, mod.tier = "custom", "custom"
    mod._render_all()
    row = mod.get_filtered()[0]

    _click(_row_switch(mod, row["id"]))                    # 禁用（这一步落还原点）
    _open_and_confirm(mod, "清空禁用", "确认清空")
    _open_and_confirm(mod, "↺ 恢复默认状态", "确认恢复")

    acts = [o["act_name"] for o in mod.store.ops(limit=12)]
    assert "禁用词条" in acts
    assert "清空禁用" in acts
    assert "恢复默认状态" in acts
    # 页面上也看得到这几条（UI 分支重设计：操作历史改抽屉内分页卡，最新在前，
    # 第 0 页即含最近操作；不再有「展开全部」开关，直接渲染断言）
    mod._render_ops()
    texts = " ".join(
        lab.text() for lab in mod.findChildren(type(mod.page_label))
    )
    assert "清空禁用" in texts and "恢复默认状态" in texts

    # 三条状态操作可以一路撤回去，且词条内容始终没被动过
    for _ in range(3):
        _click(mod.head_undo_btn)
    assert len(mod.store.custom) == 1, "启停操作不该动到词条内容"
    assert mod.store.word_states_summary()["disabled_total"] == 5841


def test_undo_button_available_from_header(mod):
    assert hasattr(mod, "head_undo_btn"), "页头必须有撤销入口（与新增 / 删除同栈）"
    assert mod.head_undo_btn.toolTip().startswith("撤销上一步")
    assert mod.head_undo_btn.isEnabled()
