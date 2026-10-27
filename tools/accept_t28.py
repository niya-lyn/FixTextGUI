"""M2-T2.8 首次使用向导 · 验收脚本（离屏，真实模态弹窗）

验收口径（任务卡 3.2 向导专项）：
  S1 首启自动弹一次    全新配置目录起一个真进程，建真主窗口，不得手动调用任何
                       内部方法；事件循环一跑，向导就应自己弹出。记录弹出次数。
  S2 完成三步 → 跳导入 真点「下一步」三次（末步「开始使用」），断言主窗口切到
                        「导入书籍」页；三步各截一张图。
  S3 之后不再自动弹    同一配置目录再起一个**新进程**，事件循环跑满观察窗口，
                       向导不得再自己弹（这一条同时验 QSettings 持久化）。
  S4 ☰ 重看            已看过状态下，☰ 菜单里的「新手向导（重新观看）」必须能
                       再次弹出向导（真实菜单、真实 action.trigger）。
  S5 跳过也算已看过    全新配置目录、跳过路径：不跳页，但 wizardSeen 落成 1，
                       且同目录再起新进程不再自动弹。
  S6 零露出            向导全部界面文案过 verify_m2t21 的内部术语词表，命中 0。

为什么用真进程而不是同进程多轮：QSettings 的配置目录在进程启动时定死
（实测 `QSettings.setPath` 对 NativeFormat 不生效），「重启进程仍不弹」这条
只有在真新进程里才成立。

运行：
    QT_QPA_PLATFORM=offscreen python3.12 tools/accept_t28.py
产出：
    evidence/t28_evidence.json + screenshots/t28_step{1,2,3}.png
退出码：全部通过 0，任一失败 1。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
TOOLS = HERE
#: 沙箱里 PySide6 装在持久工具目录（不在默认 site-packages）；直接跑脚本时补齐，
#: 免得「父进程能跑、子进程能跑、只有收尾这段 No module named PySide6」
QT_SITE = "/home/gem/.aily/.cli/qtenv/lib/python3.12/site-packages"
if Path(QT_SITE).exists() and QT_SITE not in sys.path:
    sys.path.insert(0, QT_SITE)
EVID = PKG / "evidence"
SHOTS = PKG / "screenshots"
UI = PKG / "fixtext_ui"

sys.path.insert(0, str(UI))
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(TOOLS))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

WIZ_MENU_LABEL = "新手向导（重新观看）"
PY = sys.executable
TIMEOUT_S = 120


# ---------------------------------------------------------------------------
# 子进程侧：单个阶段（每个阶段都是一个全新进程 + 独立配置目录）
# ---------------------------------------------------------------------------

def _prep():
    """统一前置：导入 Qt 与主窗口。配置目录由父进程经 XDG_CONFIG_HOME 注入。"""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import main_window as M
    return app, M


def _counted_wizard(M):
    """把 FirstRunWizard 换成「真类 + 计数」：弹的仍是真向导，只多记次数。"""
    real = M.FirstRunWizard
    seen = {"pops": 0, "instances": []}

    class Counting(real):
        def __init__(self, parent=None):
            super().__init__(parent)
            seen["pops"] += 1
            seen["instances"].append(self)

    M.FirstRunWizard = Counting
    return seen


class Driver:
    """在模态 exec 的嵌套事件循环里点按钮（离屏无用户，只能这样驱动真弹窗）。"""

    def __init__(self, plan, shots=None, tag=""):
        from PySide6.QtCore import QTimer
        self.plan = list(plan)
        self.shots = shots or []
        self.i = 0
        self.tag = tag
        self.done = {"n": 0}
        self.shot_steps: list[int] = []      # 每张截图当时的步骤号（自证图对不对）
        self._timer = QTimer()
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _tick(self):
        from PySide6.QtWidgets import QApplication
        w = QApplication.activeModalWidget()
        if w is None or not w.isVisible():
            return
        if self.i >= len(self.plan):
            self._timer.stop()
            return
        action = self.plan[self.i]
        if self.i < len(self.shots):
            # 截图前先把上一轮 _render_step 的 deleteLater 排空，否则旧子控件
            # 还在画面里，会拍出「新旧文字叠在一起」的假象（实测过）。
            for _ in range(4):
                QApplication.processEvents()
            w.grab().save(str(self.shots[self.i]))   # 抓弹窗本体（不是主窗口）
            self.shot_steps.append(int(getattr(w, "step", -1)))
        action(w)
        self.i += 1
        self.done["n"] = self.i


def _click_next(w):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    QTest.mouseClick(w._next, Qt.MouseButton.LeftButton)


def _click_skip(w):
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    btn = [b for b in w.findChildren(QPushButton) if b.text() == "跳过"][0]
    QTest.mouseClick(btn, Qt.MouseButton.LeftButton)


def _pump(app, seconds: float, until=None):
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.02)
    app.processEvents()
    return until() if until is not None else True


def _settings_file() -> str:
    from PySide6.QtCore import QSettings
    return QSettings("FixText", "V1").fileName()


def _wizard_seen() -> str:
    from PySide6.QtCore import QSettings
    return str(QSettings("FixText", "V1").value("wizardSeen", "0"))


def _texts(root) -> list[str]:
    from PySide6.QtWidgets import QLabel, QPushButton
    out = [root.windowTitle()]
    for w in root.findChildren(QLabel):
        out.append(w.text())
    for w in root.findChildren(QPushButton):
        out += [w.text(), w.toolTip(), w.accessibleName()]
    return [t for t in out if t]


# --------------------------------------------------------------------------- 阶段实现
def phase_first(shots_dir: Path) -> dict:
    """S1+S2：首启自动弹一次；点完三步跳「导入书籍」；三步各截一张图。"""
    app, M = _prep()
    seen = _counted_wizard(M)
    import main_window as MW
    win = MW.MainWindow(PKG / "_t28_ws")
    win.show()

    shots = [shots_dir / "t28_step1.png", shots_dir / "t28_step2.png",
             shots_dir / "t28_step3.png"]
    drv = Driver([_click_next, _click_next, _click_next], shots=shots)
    drv.start()
    _pump(app, 20, until=lambda: seen["pops"] == 1 and drv.done["n"] >= 3
          and not any(w.isVisible() for w in app.topLevelWidgets()))
    drv.stop()

    steps_seen = []
    if seen["instances"]:
        steps_seen = [i.step for i in seen["instances"]]
    res = dict(
        pops=seen["pops"],
        driver_clicks=drv.done["n"],
        current_page=win.current_key,
        wizard_seen=_wizard_seen(),
        settings_file=_settings_file(),
        shots=[str(p) for p in shots if p.exists()],
        shot_steps=drv.shot_steps,
        wizard_step_after_each_click=steps_seen,
    )
    win.close()
    return res


def phase_second() -> dict:
    """S3：同一配置目录的新进程，向导不得再自动弹。"""
    app, M = _prep()
    seen = _counted_wizard(M)
    import main_window as MW
    win = MW.MainWindow(PKG / "_t28_ws2")
    win.show()
    _pump(app, 3.0)                       # 观察窗口：足够任何 singleShot 触发
    res = dict(pops=seen["pops"], current_page=win.current_key,
               wizard_seen=_wizard_seen(), settings_file=_settings_file())
    win.close()
    return res


def phase_reopen() -> dict:
    """S4：已看过状态下，☰ 菜单的重看入口必须能再次弹出向导。

    两个离屏坑都绕开：
      ① 真 popup QMenu 会抓键盘并永久阻塞 → 用 `QMenu` 子类覆盖 `exec`，
         菜单对象与 action 仍是真的，只是「弹出」换成直接扫 action；
      ② 直接给 `QMenu.exec` 赋函数在 PySide 里不生效（实测仍是原生 exec），
         所以必须走子类，不能 patch 类属性。
    触发的是真 action → 真 `_open_wizard()` → 真模态向导（由 Driver 点「跳过」关闭）。
    """
    from PySide6.QtWidgets import QMenu
    app, M = _prep()
    seen = _counted_wizard(M)
    import main_window as MW
    win = MW.MainWindow(PKG / "_t28_ws3")
    win.show()
    _pump(app, 2.0)
    pops_before_menu = seen["pops"]

    hits: dict = {"label_found": False, "is_first": False, "labels": []}

    class ProbeMenu(QMenu):
        def exec(self, *a, **kw):                     # noqa: A003
            labels = [x.text() for x in self.actions()]
            hits["labels"] = labels
            hits["label_found"] = WIZ_MENU_LABEL in labels
            hits["is_first"] = bool(labels) and labels[0] == WIZ_MENU_LABEL
            for act in self.actions():
                if act.text() == WIZ_MENU_LABEL:
                    act.trigger()                     # 真触发 → 真弹向导
                    break
            return None

    drv = Driver([_click_skip])
    drv.start()
    orig = M.QMenu
    M.QMenu = ProbeMenu
    try:
        win._act_more()
        _pump(app, 15, until=lambda: pops_before_menu < seen["pops"]
              and drv.done["n"] >= 1)
    finally:
        M.QMenu = orig
        drv.stop()

    res = dict(pops_before_menu=pops_before_menu,
               pops_after_menu=seen["pops"],
               menu_labels=hits["labels"],
               menu_label_found=hits["label_found"],
               wizard_label_is_first=hits["is_first"],
               driver_clicks=drv.done["n"],
               wizard_seen=_wizard_seen(),
               settings_file=_settings_file())
    win.close()
    return res


def phase_skip() -> dict:
    """S5：全新配置目录走「跳过」：不跳页、但同样记为已看过。"""
    app, M = _prep()
    seen = _counted_wizard(M)
    import main_window as MW
    win = MW.MainWindow(PKG / "_t28_ws4")
    win.show()
    drv = Driver([_click_skip])
    drv.start()
    _pump(app, 20, until=lambda: seen["pops"] == 1 and drv.done["n"] >= 1
          and not any(w.isVisible() for w in app.topLevelWidgets()))
    drv.stop()
    res = dict(pops=seen["pops"], driver_clicks=drv.done["n"],
               current_page=win.current_key,          # 跳过不该跳页 → home
               wizard_seen=_wizard_seen(), settings_file=_settings_file())
    win.close()
    return res


def phase_skip_restart() -> dict:
    """S5 续：跳过后再起新进程，同样不得自动弹。"""
    return phase_second()


PHASES = {
    "first": phase_first,
    "second": phase_second,
    "reopen": phase_reopen,
    "skip": phase_skip,
    "skip_restart": phase_skip_restart,
}


def run_phase(name: str) -> dict:
    fn = PHASES[name]
    if name == "first":
        out = fn(SHOTS)
    else:
        out = fn()
    print("PHASE_JSON " + json.dumps({"phase": name, "result": out},
                                     ensure_ascii=False), flush=True)
    return out


# ---------------------------------------------------------------------------
# 父进程侧：编排 + 汇总
# ---------------------------------------------------------------------------

def spawn(name: str, config_home: Path) -> dict:
    env = dict(os.environ)
    env["XDG_CONFIG_HOME"] = str(config_home)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path("/home/gem/.aily/.cli/qtenv/lib/python3.12/site-packages")),
         str(UI), str(PKG), str(TOOLS)])
    proc = subprocess.run([PY, str(Path(__file__)), "--phase", name],
                          capture_output=True, text=True, timeout=TIMEOUT_S, env=env)
    for line in proc.stdout.splitlines():
        if line.startswith("PHASE_JSON "):
            return json.loads(line[len("PHASE_JSON "):])
    return dict(phase=name, error="子进程未返回结果",
                stdout=proc.stdout[-2000:], stderr=proc.stderr[-2000:],
                returncode=proc.returncode)


def scan_wizard_leak() -> dict:
    """S6：向导文案过基线内部术语词表。"""
    import verify_m2t21 as V
    import first_run_wizard as W
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    w = W.FirstRunWizard()
    hits, scanned = [], 0
    for step in range(3):
        w.go_step(step)
        for t in _texts(w):
            scanned += 1
            for pat in V.FORBIDDEN:
                m = re.search(pat, t)
                if m:
                    hits.append(dict(step=step, pattern=pat,
                                     matched=m.group(0), text=t[:120]))
    w.close()
    return dict(passed=not hits, scanned=scanned,
                forbidden_patterns=len(V.FORBIDDEN), hits=hits)


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    tmp_root = Path(tempfile.mkdtemp(prefix="t28_cfg_"))

    rep: dict = {}
    ok = True

    def say(tag, msg, good):
        nonlocal ok
        ok = ok and good
        print(f"[{tag}] {msg} -> {'PASS' if good else 'FAIL'}", flush=True)

    # ---- S1+S2 首启 + 三步 + 跳页 ----
    cfg1 = tmp_root / "cfg_first"
    cfg1.mkdir()
    r1 = spawn("first", cfg1)["result"]
    rep["S1S2_first_run"] = r1
    say("S1", f"首启自动弹 {r1['pops']} 次（应恰好 1 次），驱动点 {r1['driver_clicks']} 下",
        r1["pops"] == 1 and r1["driver_clicks"] == 3)
    say("S2", f"完成三步后当前页 = {r1['current_page']}（应为 import）",
        r1["current_page"] == "import")
    say("S2", f"三步截图 {len(r1['shots'])} 张", len(r1["shots"]) == 3)

    # ---- S3 重启不再弹（同一配置目录，新进程）----
    r2 = spawn("second", cfg1)["result"]
    rep["S3_restart"] = r2
    say("S3", f"重启进程后自动弹 {r2['pops']} 次（应 0），wizardSeen={r2['wizard_seen']}",
        r2["pops"] == 0 and r2["wizard_seen"] == "1")

    # ---- S4 ☰ 重看 ----
    r3 = spawn("reopen", cfg1)["result"]
    rep["S4_reopen"] = r3
    say("S4", f"重看前弹 {r3['pops_before_menu']} 次、点菜单后 {r3['pops_after_menu']} 次；"
              f"入口存在={r3['menu_label_found']}，首项={r3['wizard_label_is_first']}",
        r3["pops_before_menu"] == 0 and r3["pops_after_menu"] == 1
        and r3["menu_label_found"] and r3["wizard_label_is_first"])

    # ---- S5 跳过 ----
    cfg2 = tmp_root / "cfg_skip"
    cfg2.mkdir()
    r4 = spawn("skip", cfg2)["result"]
    rep["S5_skip"] = r4
    say("S5", f"跳过路径：弹 {r4['pops']} 次，停留页 = {r4['current_page']}（应 home），"
              f"wizardSeen={r4['wizard_seen']}",
        r4["pops"] == 1 and r4["wizard_seen"] == "1" and r4["current_page"] == "home")

    r5 = spawn("skip_restart", cfg2)["result"]
    rep["S5_skip_restart"] = r5
    say("S5", f"跳过后的新进程再弹 {r5['pops']} 次（应 0）", r5["pops"] == 0)

    # ---- S6 零露出 ----
    r6 = scan_wizard_leak()
    rep["S6_zero_leak"] = r6
    say("S6", f"向导文案扫描 {r6['scanned']} 条 / 词表 {r6['forbidden_patterns']} 项，"
              f"命中 {len(r6['hits'])}", r6["passed"])

    rep["passed"] = ok
    rep["config_roots"] = [str(cfg1), str(cfg2)]
    (EVID / "t28_evidence.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n证据 -> {EVID / 't28_evidence.json'}", flush=True)
    print(f"T2.8 向导专项: {'PASS' if ok else 'FAIL'}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    if "--phase" in sys.argv:
        idx = sys.argv.index("--phase")
        run_phase(sys.argv[idx + 1])
        sys.exit(0)
    sys.exit(main())
