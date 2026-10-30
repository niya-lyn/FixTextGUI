"""M4-EX.2c 任务式新手向导 · 单元级验证（替代 M2-T2.8 的只读演示向导用例）

覆盖：
  1. 向导本体：三步定义、进度条状态、左右分栏按钮、跳 / 返回 / 完成语义
  2. 「示例书」不再是产品功能：源码里不得出现示例书相关文案与常量
  3. 只消费设计令牌（不出现六位十六进制色值），文案零内部术语
  4. 翻页不叠加旧内容（真实缺陷回归：标题行是嵌套布局，曾被漏清）
  5. 校正取消二次确认：确认层与进度弹窗的关系 + 两个按钮的真实语义
  6. 主窗口接线：首启自动弹一次、跳过不跳页、完成跳历史页、☰ 重看入口首项

关键防挂死：主窗口构造尾部 `QTimer.singleShot(0, self._maybe_first_run)`
会在**之后**的事件循环里触发；若此时 FirstRunWizard 是真类，模态 `exec()`
会把测试进程卡死。所以本模块在会话级把 `main_window.FirstRunWizard` 换成
替身；真弹窗与真实三步链路由 `tools/accept_ex2c.py` 在离屏事件循环里跑。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import first_run_wizard as W
import main_window as M
import verify_m2t21 as V          # 零露出词表以验收脚本为准，不另立第二套口径

UI_DIR = Path(M.__file__).resolve().parent


def _shown(widget) -> bool:
    """「按当前步骤该不该出现在界面上」——只看 setVisible 的显式位，
    不要求整个窗口已 show（单元测试不弹真实窗口）。"""
    return not widget.isHidden()


class _FakeSettings:
    """QSettings 替身：只记内存，不落盘（测试不污染真实配置目录）。"""

    store: dict[str, str] = {}

    def __init__(self, *a, **kw):
        pass

    def value(self, key, default=None):
        return self.store.get(key, default)

    def setValue(self, key, value):
        self.store[key] = value

    def sync(self):
        pass


class _FakeWizard:
    """向导替身：记弹了几次，可指定用户点了完成还是跳过。"""

    calls = 0
    result = int(QDialog.DialogCode.Accepted)

    def __init__(self, parent=None, **kwargs):
        _FakeWizard.calls += 1
        _FakeWizard.last_kwargs = dict(kwargs)

    def exec(self):
        return _FakeWizard.result


@pytest.fixture(scope="session", autouse=True)
def _no_real_wizard():
    """整个会话都不允许建出真模态向导（含构造尾部残留的 singleShot）。"""
    monkeypatch = pytest.MonkeyPatch()
    # P2-6：主窗口经 mark_seen / opens_on_first_run 写 wizardSeen，不再直写 QSettings
    monkeypatch.setattr(
        M, "opens_on_first_run",
        lambda: _FakeSettings.store.get("wizardSeen", "0") != "1")
    monkeypatch.setattr(
        M, "mark_seen",
        lambda: _FakeSettings.store.__setitem__("wizardSeen", "1"))
    monkeypatch.setattr(M, "FirstRunWizard", _FakeWizard)
    yield
    monkeypatch.undo()


@pytest.fixture()
def main_win(qt_app, tmp_path):
    """真建一个主窗口；构造期间排队的 singleShot 先在这里消费掉。"""
    _FakeSettings.store = {}
    _FakeWizard.calls = 0
    _FakeWizard.result = int(QDialog.DialogCode.Accepted)
    win = M.MainWindow(tmp_path / "ws")
    QApplication.processEvents()
    QApplication.processEvents()
    _FakeSettings.store = {"wizardSeen": "1"}
    _FakeWizard.calls = 0
    yield win
    win.close()
    win.deleteLater()


def _texts(root) -> list[str]:
    out: list[str] = [root.windowTitle()]
    for w in root.findChildren(QLabel):
        out.append(w.text())
    for w in root.findChildren(QPushButton):
        out += [w.text(), w.toolTip(), w.accessibleName()]
    return [t for t in out if t]


# ------------------------------------------------------- 1. 向导本体（三步）

def test_wizard_has_three_task_steps(qt_app):
    w = W.FirstRunWizard()
    assert [s[1] for s in W.STEPS] == ["导入书籍", "一键校正", "导出结果"]
    assert w.step == 0
    assert w.bars.values() == [50, 0, 0]
    assert "第 1 步 · 导入一本书" in " ".join(_texts(w))
    w.deleteLater()


def test_step_bars_track_current(qt_app):
    w = W.FirstRunWizard()
    for step, expect in ((1, [100, 50, 0]), (2, [100, 100, 50]),
                         (3, [100, 100, 100])):
        w.go_step(step)
        assert w.bars.values() == expect
    w.deleteLater()


def test_actions_split_left_right(qt_app):
    """第 1 步：左侧「跳过」、右侧主操作；第 2 步起左侧多一个「上一步」。"""
    w = W.FirstRunWizard()
    assert w._primary.text() == "📥 选择我的书…"
    assert not _shown(w._prev)
    assert _shown(w._skip)
    assert w._prev.text() == "上一步"
    w.go_step(1)
    assert w._primary.text() == "⚡ 开始校正"
    assert _shown(w._prev) and _shown(w._skip)
    w.go_step(2)
    assert w._primary.text() == "📤 导出并生成历史"
    w.go_step(3)
    assert w._primary.text() == "完成"
    assert not _shown(w._prev) and not _shown(w._skip), \
        "完成页只留「完成」（与原型一致）"
    w.deleteLater()


def test_back_returns_previous_step(qt_app):
    w = W.FirstRunWizard()
    w.go_step(2)
    QTest.mouseClick(w._prev, Qt.MouseButton.LeftButton)
    assert w.step == 1
    QTest.mouseClick(w._prev, Qt.MouseButton.LeftButton)
    assert w.step == 0
    w.deleteLater()


def test_back_then_next_resumes_without_rerun(qt_app):
    """上一步后主按钮变「下一步」，点一下回到离开前的步（不跑业务）。"""
    w = W.FirstRunWizard()
    w.go_step(2)
    QTest.mouseClick(w._prev, Qt.MouseButton.LeftButton)
    assert w.step == 1
    assert w._primary.text() == "下一步"
    QTest.mouseClick(w._primary, Qt.MouseButton.LeftButton)
    assert w.step == 2
    assert w._primary.text() == "📤 导出并生成历史"
    w.deleteLater()


def test_rewatch_always_starts_at_step0(qt_app):
    """M5-EX.5：即使传 has_current_book=True，也从第 1 步起。"""
    w = W.FirstRunWizard(has_current_book=True)
    assert w.step == 0
    assert w.bars.values() == [50, 0, 0]
    assert not any(x.objectName() == "OnbCurrentBookHint" for x in w.findChildren(QLabel))
    w.deleteLater()


def test_finish_accepts(qt_app):
    w = W.FirstRunWizard()
    w.go_step(3)
    accepted = {"n": 0}
    w.accepted.connect(lambda: accepted.__setitem__("n", accepted["n"] + 1))
    QTest.mouseClick(w._primary, Qt.MouseButton.LeftButton)
    assert accepted["n"] == 1
    assert w.result() == int(QDialog.DialogCode.Accepted)
    w.deleteLater()


def test_skip_rejects(qt_app):
    """跳过 = reject（主窗口据此只记已看过、不跳页）。"""
    w = W.FirstRunWizard()
    seen = {"n": 0}
    w.rejected.connect(lambda: seen.__setitem__("n", seen["n"] + 1))
    QTest.mouseClick(w._skip, Qt.MouseButton.LeftButton)
    assert seen["n"] == 1
    assert w.result() == int(QDialog.DialogCode.Rejected)
    w.deleteLater()


def test_step_without_modules_reports_honestly(qt_app):
    """没有真实模块时不假装完成：给出人话原因，仍停在原步。"""
    w = W.FirstRunWizard()
    w._do_import()
    assert w.step == 0 and "没准备好" in w._error
    w.deleteLater()


# --------------------------------------------- 2. 「示例书」不是要实现的功能

def test_no_sample_book_affordance():
    """示例书只是原型的演示数据（用户 2026-10-28 明确指出），不得成为功能。"""
    src = (UI_DIR / "first_run_wizard.py").read_text(encoding="utf-8")
    for word in ("示例书", "SAMPLE", "星河彼端"):
        assert word not in src, f"向导里仍残留「{word}」：示例书不是要实现的功能"


# ------------------------------------------------------- 3. 令牌与文案约束

def test_wizard_uses_tokens_only():
    src = (UI_DIR / "first_run_wizard.py").read_text(encoding="utf-8")
    six = re.findall(r"#[0-9a-fA-F]{6}\b", src)
    assert not six, f"向导出现硬编码六位色值：{six}"
    assert "fixtext_tokens" in src and "c(" in src


def test_wizard_texts_have_no_tech_terms(qt_app):
    w = W.FirstRunWizard()
    hits = []
    for step in range(4):
        w.go_step(step)
        for t in _texts(w):
            hits += [(step, pat, t[:80])
                     for pat in V.FORBIDDEN if re.search(pat, t)]
    assert not hits, f"向导文案出现内部技术词：{hits[:5]}"
    w.deleteLater()


# ---------------------------------------------------- 4. 翻页不叠加旧内容

def test_rerender_does_not_stack(qt_app):
    app = QApplication.instance()
    w = W.FirstRunWizard()
    w.show()
    for _ in range(3):
        app.processEvents()
    w.go_step(1)
    for _ in range(6):
        app.processEvents()
    labels = [c.text() for c in w.panel.findChildren(QLabel)]
    assert not any("第 1 步" in t for t in labels), f"第 1 步残留：{labels}"
    w.go_step(2)
    for _ in range(6):
        app.processEvents()
    labels = [c.text() for c in w.panel.findChildren(QLabel)]
    assert not [t for t in labels if "第 1 步" in t or "第 2 步" in t]
    w.close()
    w.deleteLater()


def test_result_block_shows_real_facts(qt_app):
    """每步完成后展示这一步的真实结果，而不是固定文案。"""
    class _Res:
        title = "测试书"
        text_chars = 1234
        chapters = 7
        encoding_label = "UTF-8"
        source_unchanged = True

    w = W.FirstRunWizard()
    w._import_result = _Res()
    w.go_step(0)
    texts = " ".join(_texts(w))
    assert "测试书" in texts and "1234 字" in texts and "7 个章节" in texts
    w.deleteLater()


# ------------------------------------------------- 5. 校正取消：二次确认

def test_cancel_confirm_dialog_copy_and_buttons(qt_app):
    from fixtext_widgets import CancelConfirmDialog

    d = CancelConfirmDialog()
    assert d.windowTitle() == "确认放弃本次校正？"
    texts = " ".join(_texts(d))
    assert "继续校正" in texts and "确认放弃" in texts
    assert "快照" in texts and "半成品" in texts
    d.deleteLater()


def test_cancel_confirm_resume_keeps_running(qt_app):
    """选「继续校正」= 不取消：进度弹窗不进入取消态。"""
    from fixtext_widgets import CancelConfirmDialog, ProgressDialog

    dlg = ProgressDialog(icon="⚡", title="t", note="", steps=[dict(name="a", desc="")],
                         mode="live", on_cancel_request=lambda: None,
                         confirm_cancel=True)
    asked = {}
    from PySide6.QtWidgets import QDialog as _Q

    def fake_exec(self):
        asked["resume"] = True
        return int(_Q.DialogCode.Rejected)

    CancelConfirmDialog.exec = fake_exec            # type: ignore[method-assign]
    dlg._cancel()
    assert asked, "没有出二次确认"
    assert dlg._cancelled is False, "选「继续校正」后不应进入取消态"
    dlg.deleteLater()


def test_cancel_confirm_accept_stops(qt_app):
    """选「确认放弃」= 真的停下并回调清理入口。"""
    from fixtext_widgets import CancelConfirmDialog, ProgressDialog
    from PySide6.QtWidgets import QDialog as _Q

    stopped = {"n": 0}
    dlg = ProgressDialog(icon="⚡", title="t", note="", steps=[dict(name="a", desc="")],
                         mode="live", on_cancel_request=lambda: stopped.__setitem__(
                             "n", stopped["n"] + 1),
                         confirm_cancel=True)
    CancelConfirmDialog.exec = lambda self: int(_Q.DialogCode.Accepted)  # type: ignore
    dlg._cancel()
    assert stopped["n"] == 1
    assert dlg._cancelled is True
    dlg.deleteLater()


def test_correction_entry_defaults_to_confirm():
    """主按钮 / 向导走同一个入口，默认就要二次确认（不留一条静默取消的路）。"""
    import inspect

    import oneclick_module as O
    sig = inspect.signature(O.OneClickModule.do_correction)
    assert sig.parameters["confirm_cancel"].default is True


# ------------------------------------------------------------- 6. 主窗口接线

def test_qtimer_hook_really_fires(qt_app, tmp_path):
    _FakeSettings.store = {}
    _FakeWizard.calls = 0
    win = M.MainWindow(tmp_path / "ws2")
    assert _FakeWizard.calls == 0, "构造时只排队，不立即弹"
    QApplication.processEvents()
    QApplication.processEvents()
    assert _FakeWizard.calls == 1, "singleShot 没触发向导"
    assert win.current_key == "history", "完成后应跳到「历史记录」页"
    assert _FakeSettings.store["wizardSeen"] == "1"
    win.close()
    win.deleteLater()


def test_wizard_gets_real_modules(main_win):
    """向导拿到三个真实模块（它要靠它们把三步做实，不是只读演示）。"""
    _FakeSettings.store = {}
    main_win._open_wizard()
    kwargs = _FakeWizard.last_kwargs
    assert kwargs.get("import_module") is main_win.import_module
    assert kwargs.get("oneclick_module") is main_win.oneclick_module
    assert kwargs.get("export_module") is main_win.export_module


def test_first_run_pops_once(main_win):
    main_win._maybe_first_run()
    assert _FakeWizard.calls == 0, "已看过时不应弹"
    _FakeSettings.store = {}
    _FakeWizard.calls = 0
    main_win._maybe_first_run()
    assert _FakeWizard.calls == 1
    assert _FakeSettings.store["wizardSeen"] == "1"
    main_win._maybe_first_run()
    assert _FakeWizard.calls == 1, "第二次启动不应再自动弹"


def test_skip_stays_and_marks_seen(main_win):
    _FakeSettings.store = {}
    _FakeWizard.result = int(QDialog.DialogCode.Rejected)
    before = main_win.current_key
    main_win._open_wizard()
    assert main_win.current_key == before, "跳过不该跳页"
    assert _FakeSettings.store["wizardSeen"] == "1"


def test_finish_jumps_to_history(main_win):
    _FakeSettings.store = {}
    _FakeWizard.result = int(QDialog.DialogCode.Accepted)
    main_win.go("home")
    main_win._open_wizard()
    assert main_win.current_key == "history"
    assert _FakeSettings.store["wizardSeen"] == "1"


def test_more_menu_has_wizard_entry(main_win, monkeypatch):
    """☰ 菜单里必须有重看入口，且是首项（与用户接线意图一致）。"""

    class _FakeMenu:
        instances: list["_FakeMenu"] = []

        def __init__(self, *a, **kw):
            self.actions: list[str] = []
            self.separators: list[int] = []
            _FakeMenu.instances.append(self)

        def sizeHint(self):
            """M4-EX.4d：真实 QMenu 一直有 sizeHint，替身补齐即可。

            产品侧按它算弹层落点（越界时才向内收）；替身给 0 尺寸，
            `_popup_target` 就不做边界收敛，等价于"直接贴锚点"。
            """
            from PySide6.QtCore import QSize

            return QSize(0, 0)

        def addAction(self, text=""):
            self.actions.append(text)
            return type("_A", (), {"triggered": type(
                "_S", (), {"connect": lambda *a, **k: None})()})()

        def addSeparator(self):
            self.separators.append(len(self.actions))

        def exec(self, *a, **kw):
            return None

    monkeypatch.setattr(M, "QMenu", _FakeMenu)
    main_win._act_more()
    texts = _FakeMenu.instances[0].actions
    assert texts[0] == "新手向导（重新观看）"
