"""M4-EX.2b 回归：五页统一空状态（真实触发）+ 词库页不做空状态 + 交互细节。

口径来源：原型 v3（合并版）更新记录 §4（空状态整改）与 §5（两个原型 bug
的修复版行为：toggleCard 折叠、排版下拉 onchange 回写）。
"""

import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtext_ui"))

FAKE_NAMES = ("星河彼端", "旧巷杂记", "灯下漫笔")


def _texts(widget) -> list[str]:
    return [l.text() for l in widget.findChildren(QLabel)]


# ---------------------------------------------------------------- 控件本体

def test_empty_state_widget_shape(qapp):
    """双按钮居中形态：主按钮 BtnPrimary + 次按钮 BtnGhost；没有收起按钮。"""
    from fixtext_widgets import EmptyState

    es = EmptyState("⚡", "还没有可校正的书", "描述文字")
    btns = es.findChildren(QPushButton)
    assert [b.objectName() for b in btns] == ["BtnPrimary", "BtnGhost"], \
        "空状态必须是双按钮：主按钮去导入 + 次按钮打开新手向导"
    # §4：空状态没有收起按钮——控件里除这两个按钮外不允许有任何 QPushButton
    assert len(btns) == 2, "空状态不允许出现第三个按钮（含收起按钮）"
    # 信号通路
    fired = []
    es.primaryClicked.connect(lambda: fired.append("p"))
    es.secondaryClicked.connect(lambda: fired.append("s"))
    btns[0].click()
    btns[1].click()
    assert fired == ["p", "s"], "两个按钮必须各自发出信号，由外层接线"


# ------------------------------------------------------------------ 五页触发

def test_import_page_empty_state_real_trigger(qapp, tmp_path):
    """导入页：工作区真的一本书都没有 → 空状态；工作区卡收起。"""
    import import_module as im

    mod = im.ImportModule(workspace_root=tmp_path)
    assert mod.empty_state.isVisibleTo(mod), "空工作区必须触发空状态"
    assert not mod.workspace_card.isVisibleTo(mod), "无书时工作区卡收起"
    texts = _texts(mod)
    assert any("还没有导入的书" in t for t in texts)
    assert any("拖放区" in t for t in texts), "描述要指明导入入口"
    for fake in FAKE_NAMES:
        assert not any(fake in t for t in texts)


def test_oneclick_page_empty_state_real_trigger(qapp):
    """一键校正页：没有运行上下文 → 空状态；常规内容收起。"""
    import oneclick_module as om

    mod = om.OneClickModule()
    assert mod.run_context is None
    assert mod.empty_state.isVisibleTo(mod), "无运行上下文必须触发空状态"
    for w in (mod._book_w, mod._hero_w, mod._fmt_w, mod._adv_w, mod.legend):
        assert not w.isVisibleTo(mod), f"无书时 {w.objectName() or w} 应收起"
    texts = _texts(mod)
    assert any("还没有可校正的书" in t for t in texts)
    for fake in FAKE_NAMES:
        assert not any(fake in t for t in texts)


def test_check_page_empty_state_real_trigger(qapp):
    """检查页：没有检查报告 → 空状态；内容区收起。"""
    import check_module as cm

    mod = cm.CheckModule()
    assert mod.report is None
    assert mod.empty_state.isVisibleTo(mod), "无报告必须触发空状态"
    assert not mod._content_w.isVisibleTo(mod), "无报告时内容区应收起"
    texts = _texts(mod)
    assert any("还没有可检查的书" in t for t in texts)
    for fake in FAKE_NAMES:
        assert not any(fake in t for t in texts)


def test_export_page_empty_state_real_trigger(qapp):
    """导出页：没有可导出书源 → 空状态；内容区收起。"""
    import export_module as em

    mod = em.ExportModule()
    assert mod.source is None
    assert mod.empty_state.isVisibleTo(mod), "无书源必须触发空状态"
    assert not mod._content_w.isVisibleTo(mod), "无书源时内容区应收起"
    texts = _texts(mod)
    assert any("还没有可导出的书" in t for t in texts)
    for fake in FAKE_NAMES:
        assert not any(fake in t for t in texts)


def test_history_page_empty_state_real_trigger(qapp, tmp_path):
    """历史页：磁盘扫描结果为空 → 空状态；任务表与快照面板收起。"""
    import history_module as hm

    runs = tmp_path / "runs"
    runs.mkdir()
    mod = hm.HistoryModule()
    mod.set_runs_root(runs)
    mod.refresh()
    assert mod.row_count == 0
    assert mod.empty_state.isVisibleTo(mod), "无历史必须触发空状态"
    assert not mod._task_w.isVisibleTo(mod)
    assert not mod._snap_w.isVisibleTo(mod)
    texts = _texts(mod)
    assert any("还没有校正历史" in t for t in texts)
    for fake in FAKE_NAMES:
        assert not any(fake in t for t in texts)


def test_vocab_page_has_no_empty_state(qapp):
    """词库页不做空状态（§4：内置词库随时可用，不存在无书可管的空状态）。"""
    import vocab_module as vm

    mod = vm.VocabModule()
    assert not hasattr(mod, "empty_state"), "词库页不允许出现统一空状态"


# ------------------------------------------------------------------ 交互细节

def test_card_collapse_toggle(qapp):
    """卡片折叠：切换展开/收起（原型 toggleCard 修复版行为）。

    Card 的标题行 mousePressEvent 被替换为 toggle()（等效原型修复版
    ``el.closest('.card')||el`` 的整卡切换），这里直接走同一入口验证
    折叠态、箭头方向与正文显隐三者同步。
    """
    from fixtext_widgets import Card

    card = Card("可折叠卡", collapsible=True, open_=True)
    assert card._open is True
    assert card._chev.text() == "▼", "展开时箭头朝下"
    card.toggle()
    assert card._open is False, "折叠后状态翻转"
    assert not card.body.isVisibleTo(card), "折叠时正文收起"
    assert card._chev.text() == "▶", "折叠时箭头朝右"
    card.toggle()
    assert card._open is True, "再切一次应重新展开"
    assert card.body.isVisibleTo(card), "展开时正文可见"


def test_fmt_combo_writeback(qapp, tmp_path):
    """排版下拉回写：选新值 → 写回 fmt_state 并持久化（原型 setFmtVal 修复版）。"""
    import oneclick_module as om

    mod = om.OneClickModule()
    # 找一个真下拉（dropdown 型排版项，选项在 opts 里）
    for n, combo in mod._combos.items():
        item = mod.fmt_state[n]
        old = item["val"]
        new = [v for v in item["opts"] if v != old]
        if not new:
            continue
        combo.setCurrentText(new[0])
        assert mod.fmt_state[n]["val"] == new[0], \
            f"排版项 n={n} 选新值后必须回写 fmt_state"
        assert mod.status.isVisible() or mod.status.text(), \
            "排版改动应给出 toast 反馈"
        return
    pytest.fail("一键校正页应至少有一个 dropdown 型排版下拉")


def test_empty_state_desc_not_clipped(qapp):
    """描述文案必须完整显示（原型 es-d 是 440px 内换行，不是单行截断）。

    回归点：中文长句上 QLabel 的 sizeHint 不给换行后的高度，EmptyState 按
    sizeHint 定高时描述只拿到单行 16px，第二句引导语被裁掉（本卡实测五页全中招）。

    注意：这里必须走真实布局路径——把 EmptyState 放进「布局 + addStretch」的宿主里，
    让它自己按 sizeHint 决定高度；如果人为 resize 给一大块空间，QLabel 会吸收
    多余空间把高度撑够，缺陷就被掩盖掉了（那样写出来的用例是假绿的）。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from fixtext_widgets import EmptyState

    desc = ("请先导入一本书，才能跑「一键校正」。"
            "当前页面在有书状态下展示；无书时仅显示此引导。")
    host = QWidget()
    host.resize(720, 500)
    lay = QVBoxLayout(host)
    es = EmptyState("⚡", "还没有可校正的书", desc)
    lay.addWidget(es)
    lay.addStretch(1)          # 与主窗口 _wrap 的布局一致：空状态按 sizeHint 定高
    host.show()
    qapp.processEvents()

    lbl = [l for l in es.findChildren(QLabel) if l.text() == desc][0]
    need = lbl.fontMetrics().boundingRect(
        0, 0, lbl.width(), 100000,
        int(Qt.TextFlag.TextWordWrap), desc).height()
    assert lbl.height() >= need, (
        f"描述文案被裁切：实际 {lbl.height()}px < 需要 {need}px")
    assert lbl.height() >= lbl.fontMetrics().lineSpacing() * 2, \
        "描述文案应至少容纳两行（两句引导语）"
    host.hide()
