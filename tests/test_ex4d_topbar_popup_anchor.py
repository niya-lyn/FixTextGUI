"""M4-EX.4d 回归：顶栏 ☰ / ? / ⚙ 三颗按钮的弹层必须贴在按钮上。

反馈 #9：右上角 ☰ 点开后菜单弹在窗口左下角。根因是顶栏三颗按钮用
`lambda _=False, s=slot: s()` 中转信号 —— Qt 的 clicked 在中转 lambda 里
就把发送者丢了，槽里 `self.sender()` 恒为 None，锚点回退主窗口，
于是 `menu.exec(self.mapToGlobal(QPoint(0, self.height())))` 落在左下角。

本文件的断言口径（都走"用户真实路径"而不是内部调用）：
1. 用 `QTest.mouseClick` 真实点击按钮，弹层在事件循环内实际显示时才采样；
2. 弹层纵向必须与按钮底边齐平（`y == anchor.y`），不是屏幕顶 / 窗口底；
3. 弹层横向必须与按钮重叠，禁止被推成离按钮很远的样子。

离屏平台屏幕固定 800×800，而窗口最小宽 1220，所以用例先把窗口移成
负坐标（窗口整体仍在屏内），右侧按钮才不会触发 Qt 的屏幕自动收边，
断言才能拿到确定值。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtext_ui"))

PKG = Path(__file__).resolve().parents[1]

#: 顶栏允许的纵向偏差（布局 / 样式像素级抖动）
Y_TOL = 2
#: 横向邻接允许的偏差
X_TOL = 2


@pytest.fixture()
def window(qapp, tmp_path):
    """构建真实主窗口：先关掉首启向导，再摆到整窗可见的位置。"""
    import main_window as M
    from fixtext_settings import AppSettings

    # 首启向导会在 processEvents 时 exec() 阻塞，先标已看过
    st = AppSettings("FixText", "V1")
    st.setValue("wizardSeen", "1")
    st.sync()

    win = M.MainWindow(workspace=tmp_path / "ws")
    win.resize(M.WINDOW_MIN_W, M.WINDOW_MIN_H)
    # 移到负坐标：1220 宽的窗口在 800 宽的离屏屏上右半边会越界，
    # 越界会让 Qt 把弹层自动收进屏幕，锚点断言就不确定了。
    win.move(-(M.WINDOW_MIN_W - 780), 0)
    win.show()
    qapp.processEvents()
    return win


def _top_acts(win) -> dict:
    from PySide6.QtWidgets import QPushButton

    out = {}
    for b in win.findChildren(QPushButton):
        if b.objectName() == "TopAct":
            out[b.toolTip()] = b
    assert set(out) == {"更多", "帮助", "设置"}, f"顶栏按钮不全：{list(out)}"
    return out


def _click_and_sample(qapp, button):
    """真实点击按钮，在弹层打开的事件循环里采样它的全局位置。"""
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog, QMenu

    seen: list[dict] = []

    def sample():
        for w in qapp.topLevelWidgets():
            if not w.isVisible():
                continue
            if isinstance(w, QMenu) and type(w).__name__ == "QMenu":
                seen.append({"kind": "menu", "pos": w.pos(), "size": w.size()})
                w.close()
                return
            if isinstance(w, QDialog) and w.isModal():
                seen.append({"kind": "dialog", "pos": w.pos(), "size": w.size()})
                w.reject()
                return
        seen.append({"kind": "none"})

    # 弹层是 exec() 阻塞的，采样必须先在事件循环里排好队
    QTimer.singleShot(160, sample)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert len(seen) == 1, f"弹层采样失败：{seen}"
    return seen[0]


def _assert_hangs_under(win, button, pop):
    """弹层贴着按钮：纵向齐按钮底边，横向与按钮重叠，且远离窗口左下角。"""
    from PySide6.QtCore import QPoint

    anchor = button.mapToGlobal(QPoint(0, button.height()))
    right = button.mapToGlobal(QPoint(button.width(), button.height()))

    assert abs(pop["pos"].y() - anchor.y()) <= Y_TOL, (
        f"弹层没贴在按钮下方：y={pop['pos'].y()} 按钮底边 y={anchor.y()}")
    assert pop["pos"].x() <= anchor.x() + X_TOL, (
        f"弹层跑到按钮左侧去了：x={pop['pos'].x()} 按钮左边 x={anchor.x()}")
    assert pop["pos"].x() + pop["size"].width() >= right.x() - X_TOL, (
        f"弹层与按钮横向不重叠：右边缘={pop['pos'].x() + pop['size'].width()} "
        f"按钮右边 x={right.x()}")

    # 反面：绝不能回到窗口左下角
    win_bottom = win.mapToGlobal(QPoint(0, win.height()))
    dist = ((pop["pos"].x() - win_bottom.x()) ** 2
            + (pop["pos"].y() - win_bottom.y()) ** 2) ** 0.5
    assert dist > 200, f"弹层落在窗口左下角附近（距 {dist:.0f}px）：{pop['pos']}"
    assert pop["size"].width() > 0 and pop["size"].height() > 0, "弹层尺寸为 0"


# ---------------------------------------------------------------- ☰ 更多菜单

def test_more_menu_pops_under_its_button(qapp, window):
    """☰ 菜单必须弹在 ☰ 按钮正下方，不是窗口左下角（反馈 #9 本体）。"""
    menu = _click_and_sample(qapp, _top_acts(window)["更多"])
    assert menu["kind"] == "menu", f"☰ 应该弹菜单，实际：{menu}"
    _assert_hangs_under(window, _top_acts(window)["更多"], menu)


def test_more_menu_items_still_work(qapp, window):
    """菜单内容是重点：四项动作与两条分隔线都不能在修锚点时被改没。"""
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMenu

    captured: list[list[str]] = []
    texts: list[str] = []

    def sample():
        try:
            for w in qapp.topLevelWidgets():
                if isinstance(w, QMenu) and w.isVisible() and type(w).__name__ == "QMenu":
                    acts = w.actions()
                    texts.extend(a.text() for a in acts if not a.isSeparator())
                    captured.append(["" for a in acts if a.isSeparator()])
                    w.close()
                    return
        finally:
            if not captured:
                captured.append(["<no menu>"])

    QTimer.singleShot(160, sample)
    QTest.mouseClick(_top_acts(window)["更多"], Qt.MouseButton.LeftButton)
    qapp.processEvents()

    # V1.1-F2：「打开设计依据目录」这一项已被产品在 M5-EX.2（655f47b，BUG-2）
    # 移除——「显示设计依据」整套入口连同菜单项、设置项一并删掉，只剩
    # Card 的 basis 标签保留但恒隐藏；本测试随后没有跟着更新，仍在断言四
    # 项。按产品现在的真实菜单（三项 + 两条分隔线）对齐，断言口径不变：
    # 仍是「逐项列出菜单文案」且「分隔线数量固定」——三项少一项或多一项
    # 都会照旧判失败，没有放宽。
    assert texts == [
        "新手向导（重新观看）", "重新生成样式表", "关于 FixTextGUI",
    ], f"☰ 菜单项变了：{texts}"
    assert len(captured[0]) == 2, f"☰ 菜单分隔线数量变了：{captured}"


# ---------------------------------------------------------------- ? 帮助弹窗

def test_help_modal_opens_under_help_button(qapp, window):
    """? 弹的是帮助弹窗，同样要贴按钮（旧代码直接 exec()，落在屏幕左上角）。"""
    pop = _click_and_sample(qapp, _top_acts(window)["帮助"])
    assert pop["kind"] == "dialog", f"? 应该弹帮助弹窗，实际：{pop}"
    _assert_hangs_under(window, _top_acts(window)["帮助"], pop)


def test_help_modal_keeps_its_content(qapp, window):
    """帮助弹窗的正文与关闭按钮不能被改丢（修定位时只该动位置）。"""
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog

    labels: list[str] = []
    foot: list[str] = []

    def sample():
        try:
            for w in qapp.topLevelWidgets():
                if isinstance(w, QDialog) and w.isModal() and w.isVisible():
                    from PySide6.QtWidgets import QLabel, QPushButton

                    labels.extend(l.text() for l in w.findChildren(QLabel))
                    foot.extend(b.text() for b in w.findChildren(QPushButton))
                    w.reject()
                    return
        finally:
            if not labels:
                labels.append("<no dialog>")

    QTimer.singleShot(160, sample)
    QTest.mouseClick(_top_acts(window)["帮助"], Qt.MouseButton.LeftButton)
    qapp.processEvents()

    body = "\n".join(labels)
    assert "六个入口" in body, f"帮助正文丢了核心说明：{body[:80]}"
    assert "关闭" in foot, f"帮助弹窗没有关闭按钮：{foot}"


# ---------------------------------------------------------------- ⚙ 设置路由

def test_settings_button_routes_to_page_without_popup(qapp, window):
    """⚙ 是路由不是弹层：点了必须进设置页，且不弹出任何窗口。

    ⚙ 与 ☰/? 走同一处代码（同一次 lambda 中转受影响），必须一起验回归。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog, QMenu

    QTest.mouseClick(_top_acts(window)["设置"], Qt.MouseButton.LeftButton)
    qapp.processEvents()

    assert window.current_key == "settings", f"⚙ 没进设置页：{window.current_key}"
    assert not [w for w in qapp.topLevelWidgets()
                if isinstance(w, (QMenu, QDialog)) and w.isVisible()
                and type(w).__name__ in ("QMenu", "Modal")], "⚙ 不该弹窗口"


# ---------------------------------------------------------------- 直接调用兜底

def test_direct_call_still_anchors_to_button(qapp, window):
    """脚本 / 测试直接调 `_act_more()` 时 sender() 为 None，也要贴按钮。

    既有工具（_shoot_topbar / 首启向导测试）就是直接调用槽，这条守住它们
    不会因为"只认 sender()"而在无点击入口时退回窗口左下角。
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMenu

    seen: list[dict] = []

    def sample():
        try:
            for w in qapp.topLevelWidgets():
                if isinstance(w, QMenu) and w.isVisible() and type(w).__name__ == "QMenu":
                    seen.append({"pos": w.pos(), "size": w.size()})
                    w.close()
                    return
        finally:
            if not seen:
                seen.append({"none": True})

    QTimer.singleShot(160, sample)
    window._act_more()
    qapp.processEvents()

    assert seen and "pos" in seen[0], f"直接调用没弹出菜单：{seen}"
    _assert_hangs_under(window, _top_acts(window)["更多"], seen[0])


# ---------------------------------------------------------------- 源码守卫

def _code_lines(src: str) -> str:
    """只留代码行：注释里提到旧写法是在讲历史，不算违规。"""
    return "\n".join(
        line for line in src.splitlines()
        if line.strip() and not line.strip().startswith("#")
    )


def test_topbar_buttons_are_directly_connected():
    """守卫：三颗顶栏按钮不许再用 lambda 中转，否则 sender() 会再次失效。

    这不是风格洁癖 —— 一旦有人把直连改回 `lambda ...: s()`，
    ☰ 菜单就会立刻重新弹回窗口左下角，上面的行为用例也会一起红。
    """
    import main_window as M

    code = _code_lines(inspect.getsource(M.MainWindow._build_topbar))
    assert "lambda _=False, s=slot: s()" not in code, \
        "顶栏按钮又用 lambda 中转了：sender() 会失效，菜单会弹回左下角"
    assert "act.clicked.connect(slot)" in code, \
        f"顶栏按钮没有直连槽函数：{code}"


def test_no_sender_less_anchor_fallback_to_window():
    """守卫：弹层锚点不允许再直接回退主窗口（那就是左下角的成因）。"""
    import main_window as M

    code = _code_lines(inspect.getsource(M.MainWindow._act_more))
    assert "mapToGlobal(QPoint(0, self.height()))" not in code, \
        "☰ 菜单锚点又退回主窗口左下角了"
    assert "_popup_anchor" in code, "☰ 菜单应经 _popup_anchor 解析锚点"
