# -*- coding: utf-8 -*-
"""M5-EX.4.1 布局结构断言（SYNC-1～3）：顺序与显隐，不跑真实导出。"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


def _index_of(layout, widget_or_layout) -> int:
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        if item.widget() is widget_or_layout or item.layout() is widget_or_layout:
            return i
    raise AssertionError("控件不在 layout 中")


def test_export_actions_before_target(qt_app):
    """SYNC-1：开始导出（actions）在结果之前，结果在目标卡之前。"""
    from export_module import ExportModule

    mod = ExportModule()
    cl = mod._content_w.layout()
    # V1.1-F2：M5-EX.7（720d915）把主操作由 `_actions()` 返回的 QHBoxLayout
    # 换成带 #Hero 底色的 QFrame，属性随之从 `_lay_actions` 改名 `_w_actions`，
    # 放进 content 布局的方式也从 addLayout 变成 addWidget。
    # 断言口径不变（仍是「主操作 → 结果 → 目标」三段顺序），只跟着改名与类型。
    i_actions = _index_of(cl, mod._w_actions)
    i_result = _index_of(cl, mod._w_result)
    i_target = _index_of(cl, mod._w_target)
    assert i_actions < i_result < i_target, (
        f"期望 actions < result < target，实际 "
        f"{i_actions},{i_result},{i_target}"
    )
    # V1.1-F2：用例跑到底之后必须把模块交还 Qt 销毁。
    # 这条断言以前一进函数就 AttributeError，`mod` 直接丢给 gc，从未跑到
    # 这里；修好之后用例真的走到底，若 `mod` 一直活到解释器退出，shiboken
    # 会在 QApplication 已析构之后再销毁它 —— 进程在退出阶段
    # 段错误（实测 EXIT=139 / "pure virtual method called"），批量跑时整批
    # 结果被吞。同包 test_export_meta_rebind.py 的 export_mod fixture 就是
    # 用 deleteLater() 收尾，这里照同一惯例补齐。
    mod.deleteLater()


def test_import_no_empty_state_safety_after_shelf(qt_app, tmp_path):
    """SYNC-2/3：无独立 empty_state；safety 在书架之后。"""
    from import_module import ImportModule

    mod = ImportModule(tmp_path / "ws")
    assert not hasattr(mod, "empty_state")
    assert hasattr(mod, "safety_card")
    # V1.1-F2：原断言用 `isVisible()`，但它要求整条父链都已 show——本用例
    # 只构建模块、没调 mod.show()，离屏下 isVisible() 恒为 False（产品其实
    # 已经把书架卡设成显示：import_module._refresh_workspace 里
    # `workspace_card.setVisible(True)`）。改用同包 test_ex2b / test_ex3a
    # 一致的 `isVisibleTo(mod)`：问的是「相对本模块，它是不是要显示」，
    # 不受祖先窗口有没有 show 影响，断言强度不变。
    assert mod.workspace_card.isVisibleTo(mod), "无书时书架卡仍显示（弱提示，不再整页空态）"

    root = mod.layout()
    assert _index_of(root, mod.workspace_card) < _index_of(root, mod.safety_card)
    mod.shutdown()
