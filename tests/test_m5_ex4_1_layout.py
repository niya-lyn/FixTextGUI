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
    i_actions = _index_of(cl, mod._lay_actions)
    i_result = _index_of(cl, mod._w_result)
    i_target = _index_of(cl, mod._w_target)
    assert i_actions < i_result < i_target, (
        f"期望 actions < result < target，实际 "
        f"{i_actions},{i_result},{i_target}"
    )


def test_import_no_empty_state_safety_after_shelf(qt_app, tmp_path):
    """SYNC-2/3：无独立 empty_state；safety 在书架之后。"""
    from import_module import ImportModule

    mod = ImportModule(tmp_path / "ws")
    assert not hasattr(mod, "empty_state")
    assert hasattr(mod, "safety_card")
    assert mod.workspace_card.isVisible()

    root = mod.layout()
    assert _index_of(root, mod.workspace_card) < _index_of(root, mod.safety_card)
    mod.shutdown()
