"""M2-T2.8 首次使用向导 · 单元级验证。

覆盖：
  1. 向导本身：三步内容齐、步骤指示条节点数、可前进/后退、完成 accept、跳过 reject
  2. 向导只消费令牌：源码不出现六位十六进制色值字面量
  3. 向导文案零技术词：口径与验收脚本 tools/verify_m2t21.py 一致
     （books / spine / OPF / rules.json 等内部目录与内部术语；
     编码名 UTF-8 / GBK / GB18030 属用户能听懂的人话，按任务口径不计入）
  4. 主窗口接线：构造尾部 singleShot 真的会触发、wizardSeen 控首启只弹一次、
     完成跳「导入书籍」页、跳过留原页但同样记已看过、☰ 菜单里有重看入口

关键防挂死：主窗口构造尾部 `QTimer.singleShot(0, self._maybe_first_run)` 会在
**之后的**事件循环里触发。若此时 FirstRunWizard 已恢复成真类，模态 `exec()` 会把
测试进程永久卡住（本文件第一版就卡了 600s）。因此本模块在**会话级**统一把
`main_window.QSettings` / `main_window.FirstRunWizard` 换成替身，任何时刻都不会
建出真模态窗；真弹窗路径由 tools/accept_t28.py 在离屏事件循环里跑。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMenu, QPushButton

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import first_run_wizard as W
import main_window as M
import verify_m2t21 as V          # 零露出词表以验收脚本为准，不另立第二套口径

UI_DIR = Path(M.__file__).resolve().parent


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
    """FirstRunWizard 替身：记录弹了几次，可指定用户点了完成还是跳过。"""
    calls = 0
    result = int(QDialog.DialogCode.Accepted)

    def __init__(self, parent=None):
        _FakeWizard.calls += 1

    def exec(self):
        return _FakeWizard.result


@pytest.fixture(scope="session", autouse=True)
def _no_real_wizard():
    """整个会话都不允许建出真模态向导（含构造尾部残留的 singleShot）。"""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(M, "QSettings", _FakeSettings)
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
    QApplication.processEvents()                     # 消费构造时排队的 singleShot
    QApplication.processEvents()
    # 兜底：把状态摆到「已看过」，任何后续残留调用都不会再弹
    _FakeSettings.store = {"wizardSeen": "1"}
    _FakeWizard.calls = 0
    yield win
    win.close()
    win.deleteLater()


def _texts(root) -> list[str]:
    """控件树里一切会显示给用户的字符串。"""
    out: list[str] = [root.windowTitle()]
    for w in root.findChildren(QLabel):
        out.append(w.text())
    for w in root.findChildren(QPushButton):
        out += [w.text(), w.toolTip(), w.accessibleName()]
    return [t for t in out if t]


# ---------------------------------------------------------------- 1. 向导本身

def test_wizard_has_three_steps(qt_app):
    w = W.FirstRunWizard()
    assert [s[1] for s in W.STEPS] == ["导入", "处理", "导出"]
    assert len(W.STEP_BODY) == 3
    assert w.step == 0
    assert len(w.step_bar._nodes) == 3
    assert "第 1 步 · 导入" in " ".join(_texts(w))
    w.deleteLater()


def test_wizard_next_prev_and_finish(qt_app):
    """真实点击「下一步」走完三步，末步按钮变「开始使用」并 accept。"""
    w = W.FirstRunWizard()
    accepted = {"n": 0}
    w.accepted.connect(lambda: accepted.__setitem__("n", accepted["n"] + 1))

    assert not w._prev.isEnabled()          # 第一步不能后退
    for expect_step in (1, 2):
        QTest.mouseClick(w._next, Qt.MouseButton.LeftButton)
        assert w.step == expect_step
    assert w._next.text() == "开始使用"
    assert w._prev.isEnabled()

    QTest.mouseClick(w._next, Qt.MouseButton.LeftButton)
    assert accepted["n"] == 1
    assert w.result() == int(QDialog.DialogCode.Accepted)
    w.deleteLater()


def test_wizard_prev_works(qt_app):
    w = W.FirstRunWizard()
    w.go_step(2)
    QTest.mouseClick(w._prev, Qt.MouseButton.LeftButton)
    assert w.step == 1
    w.deleteLater()


def test_wizard_rerender_does_not_stack(qt_app):
    """翻页重渲染不得叠加旧内容（真实缺陷回归：标题行是嵌套布局，曾被漏清）。

    用户原稿 `_render_step` 只清 `item.widget()`，而「第 N 步 · XX」标题行是
    `addLayout` 加进去的嵌套布局，`item.widget()` 返回 None → 旧标题留在面板上，
    截图里能看到「第 2 步 · 处理」和「第 1 步 · 导入」叠字。
    """
    app = QApplication.instance()
    w = W.FirstRunWizard()
    w.show()
    for _ in range(3):
        app.processEvents()

    w.go_step(1)
    for _ in range(6):
        app.processEvents()
    labels = [c.text() for c in w.panel.findChildren(QLabel)]
    assert not any("第 1 步" in t for t in labels), f"翻到第 2 步仍有第 1 步残留：{labels}"
    assert any("第 2 步 · 处理" in t for t in labels)

    w.go_step(2)
    for _ in range(6):
        app.processEvents()
    labels = [c.text() for c in w.panel.findChildren(QLabel)]
    stale = [t for t in labels if "第 1 步" in t or "第 2 步" in t]
    assert not stale, f"翻到第 3 步仍有旧步骤残留：{stale}"
    assert sum(1 for t in labels if t.startswith("第 ")) == 1, "标题应只有一条"
    w.close()
    w.deleteLater()


def test_wizard_skip_rejects(qt_app):
    """「跳过」= reject（主窗口据此只标已看过、不跳页）。"""
    w = W.FirstRunWizard()
    seen = {"n": 0}
    w.rejected.connect(lambda: seen.__setitem__("n", seen["n"] + 1))
    skip = [b for b in w.findChildren(QPushButton) if b.text() == "跳过"][0]
    QTest.mouseClick(skip, Qt.MouseButton.LeftButton)
    assert seen["n"] == 1
    assert w.result() == int(QDialog.DialogCode.Rejected)
    w.deleteLater()


# ---------------------------------------------------------------- 2. 令牌约束

def test_wizard_uses_tokens_only():
    """除三位缩写白（#fff）外的六位色值字面量一律不许出现。"""
    src = (UI_DIR / "first_run_wizard.py").read_text(encoding="utf-8")
    six = re.findall(r"#[0-9a-fA-F]{6}\b", src)
    assert not six, f"向导出现硬编码六位色值：{six}"
    assert "fixtext_tokens" in src and "c(" in src


# ---------------------------------------------------------------- 3. 文案零技术词

def test_wizard_texts_have_no_tech_terms(qt_app):
    w = W.FirstRunWizard()
    hits = []
    for step in range(3):
        w.go_step(step)
        for t in _texts(w):
            hits += [(step, pat, t[:80])
                     for pat in V.FORBIDDEN if re.search(pat, t)]
    assert not hits, f"向导文案出现内部技术词：{hits[:5]}"
    w.deleteLater()


# ---------------------------------------------------------------- 4. 主窗口接线

def test_qtimer_hook_really_fires(qt_app, tmp_path):
    """构造尾部 singleShot 不是摆设：建好窗后跑事件循环就应自动弹出。"""
    _FakeSettings.store = {}
    _FakeWizard.calls = 0
    win = M.MainWindow(tmp_path / "ws2")
    assert _FakeWizard.calls == 0, "构造时只排队，不立即弹"
    QApplication.processEvents()
    QApplication.processEvents()
    assert _FakeWizard.calls == 1, "singleShot 没触发向导"
    assert win.current_key == "import", "完成后应跳到「导入书籍」页"
    assert _FakeSettings.store["wizardSeen"] == "1"
    win.close()
    win.deleteLater()


def test_first_run_pops_once(main_win):
    """已看过 → 不再自动弹；把标记清掉 → 再弹一次。"""
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
    """跳过（reject）→ 不跳页，但同样记已看过。"""
    _FakeSettings.store = {}
    _FakeWizard.result = int(QDialog.DialogCode.Rejected)
    before = main_win.current_key
    main_win._open_wizard()
    assert main_win.current_key == before, "跳过不该跳页"
    assert _FakeSettings.store["wizardSeen"] == "1"


def test_finish_jumps_to_import(main_win):
    _FakeSettings.store = {}
    _FakeWizard.result = int(QDialog.DialogCode.Accepted)
    main_win.go("home")
    main_win._open_wizard()
    assert main_win.current_key == "import"
    assert _FakeSettings.store["wizardSeen"] == "1"


def test_more_menu_has_wizard_entry(main_win, monkeypatch):
    """☰ 菜单里必须有重看入口（扫真实构建出来的菜单动作文案）。

    离屏后端下真弹 QMenu 会抓键盘并阻塞（实测挂死），所以用记录型 QMenu 替身：
    菜单项仍由 `_act_more()` 自己 addAction 出来，验的是真实构建逻辑。
    """
    class _FakeMenu:
        instances: list["_FakeMenu"] = []

        def __init__(self, *a, **kw):
            self.actions: list[str] = []
            self.separators: list[int] = []
            _FakeMenu.instances.append(self)

        def addAction(self, text=""):
            self.actions.append(text)
            return type("_A", (), {"triggered": type("_S", (), {"connect": lambda *a, **k: None})()})()

        def addSeparator(self):
            self.separators.append(len(self.actions))

        def exec(self, *a, **kw):
            return None

    monkeypatch.setattr(M, "QMenu", _FakeMenu)
    main_win._act_more()
    assert _FakeMenu.instances, "☰ 没构建菜单"
    texts = _FakeMenu.instances[0].actions
    assert "新手向导（重新观看）" in texts
    assert texts[0] == "新手向导（重新观看）", "重看入口应为菜单首项（与用户接线意图一致）"
