"""M4-EX.2c-R3 验收：只跑三个场景（S4 取消二次确认 / S5 ☰ 重开从第 2 步 / S6 完成页跳历史）。

用法（离屏）：
    QT_QPA_PLATFORM=offscreen PYTHONPATH=<PySide6 site-packages> \\
    python3.12 -u tools/accept_ex2c.py [--only S4,S5,S6]

设计要点（上一轮踩过的坑，本版据此重写驱动）：

1. **嵌套模态里的点击必须经 ``QTimer.singleShot(0, ...)`` 派发**。
   在心跳定时器回调里直接 ``QTest.mouseClick`` 会进入目标窗口的嵌套
   ``exec()``，该回调不返回 ⇒ 同一个定时器再也不触发 ⇒ 页面"卡死"
   （这正是 R2 的 S4 跳不出确认框的真因）。改成「回调只探测 + 排队一次点击」后，
   心跳保持空闲，嵌套循环里的模态窗口能被继续驱动。

2. **心跳必须先于事件循环启动**。``MainWindow.__init__`` 挂了
   ``QTimer.singleShot(0, _maybe_first_run)``，首次 ``processEvents()`` 就会进
   向导的模态 ``exec()``；先起心跳才不会一进 exec 就无人驱动。

3. **不碰原生 ``QFileDialog.getOpenFileName``**（offscreen 下会无限等待），
   用 ``patch_file_dialog`` 注入测试文件路径，点的仍是真实主按钮。

4. **S4 分两段独立会话**：A 段点「继续校正」跑到完成；B 段点「确认放弃」，
   断言弹窗关闭且不留半成品。两段各自全新事件循环、全新主窗口。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
SRC = PKG / "fixtext_ui"
EVID = PKG / "evidence"
SHOTS = PKG / "screenshots"

WORK = PKG.parent / "in"
if not WORK.is_dir():
    WORK = PKG.parent
EPUB = WORK / "paohuo.epub"
BASELINE_EPUB = WORK / "baseline_paohuo" / "06_restore" / "paohuo_restored.epub"

ACC = PKG.parent / "ex2c_r4_acc"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(PKG))

#: 与原型一字不差的四段文案（任务书已确认，逐字断言）
CONFIRM_COPY = {
    "title": "确认放弃本次校正？",
    "note": ("校正前已自动创建快照，放弃不会留下任何半成品文件；"
             "但当前进度将丢失，需要重新运行校正。"),
    "resume": "继续校正",
    "confirm": "确认放弃",
}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fresh_env(tag: str, *, wizard_seen: bool) -> Path:
    """每个场景一套干净工作区 + 设置文件（同一进程内可反复重置）。"""
    root = ACC / tag
    shutil.rmtree(root, ignore_errors=True)
    ws = root / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    os.environ["FIXTEXT_SETTINGS_FILE"] = str(root / "settings.ini")
    if wizard_seen:
        from fixtext_settings import AppSettings
        s = AppSettings()
        s.setValue("wizardSeen", "1")
        s.sync()
    return ws


def patch_file_dialog(path: Path) -> None:
    from PySide6.QtWidgets import QFileDialog

    def fake(*_a, **_k):
        return (str(path), "")

    QFileDialog.getOpenFileName = staticmethod(fake)


def collect_texts(widget) -> list[str]:
    from PySide6.QtWidgets import QLabel, QPushButton, QWidget
    out: list[str] = []
    for w in widget.findChildren(QWidget) + [widget]:
        if isinstance(w, (QLabel, QPushButton)):
            try:
                t = type(w).text(w)
            except Exception:
                t = ""
            if isinstance(t, str) and t:
                out.append(t)
        for prop in ("toolTip", "placeholderText", "accessibleName"):
            v = getattr(w, prop, "")
            if isinstance(v, str) and v:
                out.append(v)
    return out


def shot(widget, name: str) -> str:
    SHOTS.mkdir(parents=True, exist_ok=True)
    target = SHOTS / name
    widget.adjustSize()
    widget.grab().save(str(target), "PNG")
    return str(target.relative_to(PKG))


def label_texts(widget) -> list[str]:
    from PySide6.QtWidgets import QLabel
    return [x.text() for x in widget.findChildren(QLabel)]


def snapshot_run_dirs() -> set[str]:
    """runs 下所有运行目录，键为 ``<书目录>/<运行目录>``。

    必须是 **run 级**：3b 起 ``runs/<书id>/`` 这个书容器本就是该书的常驻目录，
    取消只清掉里面那一个 run 子目录，拿根目录当残留会永远判成有残留。
    """
    root = PKG / "runs"
    if not root.is_dir():
        return set()
    out: set[str] = set()
    for book in root.iterdir():
        if not book.is_dir():
            continue
        for run in book.iterdir():
            if run.is_dir():
                out.add(f"{book.name}/{run.name}")
    return out


def clone(ops: list[dict], texts: list[str]) -> dict:
    """把一个会话的操作/文本序列整成可 JSON 落盘的快照。"""
    return {"ops": list(ops), "texts_count": len(texts)}


def find_window(app, cls):
    for w in app.topLevelWidgets():
        if isinstance(w, cls) and w.isVisible():
            return w
    return None


def topbar_more_button(win):
    from PySide6.QtWidgets import QPushButton
    for b in win.findChildren(QPushButton):
        if b.objectName() == "TopAct" and b.toolTip() == "更多":
            return b
    for b in win.findChildren(QPushButton):
        if b.text() == "☰":
            return b
    raise AssertionError("顶栏找不到 ☰ 按钮")


# ---------------------------------------------------------------------------
# 会话驱动骨架：心跳只探测 + 点击一律 singleShot 派发
# ---------------------------------------------------------------------------

class Session:
    """一次「新建主窗口 → 驱动到收尾」的独立会话。

    ``step_fn(sess)`` 每 150ms 调一次；它只做探测与决策，任何会进入嵌套事件
    循环的点击都必须走 ``sess.click_later(btn)``（内部 ``QTimer.singleShot(0)``）。
    """

    def __init__(self, app, *, wizard_seen: bool, tag: str, timeout_s: float = 300):
        self.app = app
        self.tag = tag
        self.timeout_s = timeout_s
        self.ws = fresh_env(tag, wizard_seen=wizard_seen)
        self.t0 = time.monotonic()
        self.ops: list[dict] = []
        self.texts: list[str] = []
        self.shots: dict[str, str] = {}
        #: 已派发过的点击 tag（防重复派发，永久）
        self._seen_tags: set[str] = set()
        #: 当前**在途**（已派发但回调还没执行完）的点击 tag。
        # 语义必须是「有没有在途点击」，不能做成永久标记——否则校正跑起来后
        # `if not sess._pending` 永远为 False，「取消」永远不会被派发（实测死锁）。
        self._pending: set[str] = set()

    # -- 记录 ---------------------------------------------------------------
    def now(self) -> float:
        return round(time.monotonic() - self.t0, 2)

    def note(self, action: str, **extra) -> None:
        rec = {"t": self.now(), "action": action}
        rec.update(extra)
        self.ops.append(rec)

    # -- 点击派发（关键） ---------------------------------------------------
    def click_later(self, btn, tag: str) -> None:
        from PySide6.QtCore import QTimer, Qt
        from PySide6.QtTest import QTest
        if tag in self._seen_tags:
            return
        self._seen_tags.add(tag)
        self._pending.add(tag)
        self.note(f"schedule_click:{tag}")

        def do():
            try:
                self.note(f"click:{tag}", enabled=bool(btn.isEnabled()),
                          visible=bool(btn.isVisible()))
                QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
                self.note(f"click_done:{tag}")
            finally:
                # 关键：点击执行完就从在途集合里移除，`_pending` 只表示
                # 「此刻有点击正在派发」，不代表「这个 tag 点过了」。
                self._pending.discard(tag)

        QTimer.singleShot(0, do)

    def close(self) -> None:
        """会话收尾：关掉窗口，收集界面文本（零露出扫描用）。"""
        try:
            if getattr(self, "wizard", None) is not None:
                self.texts += collect_texts(self.wizard)
            self.texts += collect_texts(self.win)
        except Exception:
            pass
        try:
            self.win.close()
            self.app.processEvents()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# S4 · 校正取消二次确认（两段独立会话）
# ---------------------------------------------------------------------------

def _await_wizard_step(sess, step: int, *, busy_ok: bool = False) -> bool:
    w = sess.state["wizard"]
    return w.step == step and (busy_ok or not w._busy) and w._primary.isEnabled()


def s4(app) -> dict:
    from first_run_wizard import FirstRunWizard

    patch_file_dialog(EPUB)
    copy_a: dict = {}
    copy_b: dict = {}

    # ---------------- A 段：取消 → 确认框 → 「继续校正」 → 跑到完成 ----------
    def plan_a(sess, w):
        mod = sess.win.oneclick_module
        ph = sess.phase
        if ph == "start":
            if _await_wizard_step(sess, 0):
                sess.phase = "importing"
                sess.click_later(w._primary, "A.import")
            return False
        if ph == "importing":
            if _await_wizard_step(sess, 1):
                sess.phase = "correcting"
                sess.click_later(w._primary, "A.correct")
            return False
        if ph == "correcting":
            dlg = mod._dlg
            if dlg is None:
                return False
            conf = getattr(dlg, "_confirm_dlg", None)
            if conf is not None:
                if "A.confirm" not in sess.shots:
                    lb = label_texts(conf)
                    copy_a.update({
                        "title_class": type(conf).TITLE,
                        "note_class": type(conf).NOTE,
                        "window_title": conf.windowTitle(),
                        "modal": bool(conf.isModal()),
                        "resume_btn": conf.resume_btn.text(),
                        "confirm_btn": conf.confirm_btn.text(),
                        "labels": lb,
                        "title_in_dialog": CONFIRM_COPY["title"] in lb,
                        "note_in_dialog": CONFIRM_COPY["note"] in lb,
                        "progress_dlg_present": True,
                    })
                    sess.shots["A.confirm"] = shot(conf, "r3_s4a_confirm.png")
                    sess.phase = "resuming"
                    sess.click_later(conf.resume_btn, "A.resume")
                return False
            # 门控必须用「是否派发过」（_seen_tags），不能用「是否有在途点击」：
            # 向导路径下点「开始校正」的回调会阻塞在嵌套 exec 里直到校正跑完
            # （实测 16.4s 才返回），用 _pending 作门控会让「取消」永远不派发。
            if "A.cancel" not in sess._seen_tags:
                sess.click_later(dlg.cancel_btn, "A.cancel")
            return False
        if ph == "resuming":
            if mod._dlg is None:
                copy_a["resume_outcome"] = mod._outcome
                copy_a["resume_hits"] = (mod._summary or {}).get("hits")
                copy_a["wizard_step_after_resume"] = w.step
                sess.shots["A.after_resume"] = shot(w, "r3_s4a_after_resume.png")
                sess.phase = "done"
                sess.click_later(w._skip, "A.skip")
                return True
            return False
        return False

    s_a = Session(app, wizard_seen=False, tag="s4a", timeout_s=300)
    s_a.phase = "start"
    # Session.run 里 wizard 类由参数给出
    res_a = _run_session(s_a, plan_a, FirstRunWizard)
    s_a.wizard = s_a.state["wizard"]
    s_a.close()

    # A 段结束后才拍照：A 是一条完整跑到底的校正，它自己的运行目录本就该留着；
    # 残留只该看 B 段的「新增」。
    runs_snapshot_before_b = snapshot_run_dirs()

    # ---------------- B 段：取消 → 确认框 → 「确认放弃」 → 干净停下 ----------
    def plan_b(sess, w):
        mod = sess.win.oneclick_module
        ph = sess.phase
        if ph == "start":
            if _await_wizard_step(sess, 0):
                sess.phase = "importing"
                sess.click_later(w._primary, "B.import")
            return False
        if ph == "importing":
            if _await_wizard_step(sess, 1):
                sess.phase = "correcting"
                sess.click_later(w._primary, "B.correct")
            return False
        if ph == "correcting":
            dlg = mod._dlg
            if dlg is None:
                return False
            conf = getattr(dlg, "_confirm_dlg", None)
            if conf is not None:
                if "B.confirm" not in sess.shots:
                    lb = label_texts(conf)
                    copy_b.update({
                        "title_in_dialog": CONFIRM_COPY["title"] in lb,
                        "note_in_dialog": CONFIRM_COPY["note"] in lb,
                        "resume_btn": conf.resume_btn.text(),
                        "confirm_btn": conf.confirm_btn.text(),
                        "labels": lb,
                    })
                    sess.shots["B.confirm"] = shot(conf, "r3_s4b_confirm.png")
                    sess.phase = "discarding"
                    sess.click_later(conf.confirm_btn, "B.confirm")
                return False
            if "B.cancel" not in sess._seen_tags:
                sess.click_later(dlg.cancel_btn, "B.cancel")
            return False
        if ph == "discarding":
            if mod._dlg is None:
                copy_b["outcome"] = mod._outcome
                copy_b["toast"] = mod.status.text()
                copy_b["wizard_step_after"] = w.step
                copy_b["confirm_dlg_gone"] = True
                sess.shots["B.after_discard"] = shot(w, "r3_s4b_after_discard.png")
                sess.phase = "done"
                sess.click_later(w._skip, "B.skip")
                return True
            return False
        return False

    s_b = Session(app, wizard_seen=False, tag="s4b", timeout_s=300)
    s_b.phase = "start"
    res_b = _run_session(s_b, plan_b, FirstRunWizard)
    s_b_wizard = s_b.state.get("wizard")
    win_b = res_b["window"]
    s_b.wizard = s_b_wizard
    s_b.close()

    # 半成品检查：跑完取消后该次运行目录必须被清掉
    ctx = win_b.oneclick_module.run_context or {}
    runs_root = Path(str(ctx.get("runs_root") or ""))
    runs_snapshot_after_b = snapshot_run_dirs()
    # 残留只看 **B 段新增** 的运行目录。A 段是一条完整跑到底的校正，它自己的
    # run 目录本来就会留在 runs 根下（两段共用同一本书的 runs_root）——拿根目录
    # 全量当残留会把 A 段的正常产物误判成半成品（上一轮 t23 踩过同一个坑）。
    residue = sorted(runs_snapshot_after_b - runs_snapshot_before_b)
    book_dir = Path(win_b._current_text_path).parent if win_b._current_text_path else None
    book_txt = Path(win_b._current_text_path) if win_b._current_text_path else None

    copy_all = bool(
        copy_a.get("title_class") == CONFIRM_COPY["title"]
        and copy_a.get("note_class") == CONFIRM_COPY["note"]
        and copy_a.get("resume_btn") == CONFIRM_COPY["resume"]
        and copy_a.get("confirm_btn") == CONFIRM_COPY["confirm"]
        and copy_a.get("title_in_dialog") and copy_a.get("note_in_dialog")
        and copy_b.get("title_in_dialog") and copy_b.get("note_in_dialog")
        and copy_b.get("resume_btn") == CONFIRM_COPY["resume"]
        and copy_b.get("confirm_btn") == CONFIRM_COPY["confirm"]
    )

    return {
        "scenario": "S4 校正取消二次确认（两段独立会话）",
        "A_resume_path": clone(s_a.ops, s_a.texts),
        "B_discard_path": clone(s_b.ops, s_b.texts),
        "A_elapsed_s": res_a["elapsed_s"], "B_elapsed_s": res_b["elapsed_s"],
        "confirm_copy_expected": CONFIRM_COPY,
        "A_copy_observed": copy_a,
        "B_copy_observed": copy_b,
        "copy_all_match": copy_all,
        "A_resume_outcome": copy_a.get("resume_outcome"),
        "A_resume_hits": copy_a.get("resume_hits"),
        "A_wizard_step_after_resume": copy_a.get("wizard_step_after_resume"),
        "B_discard_outcome": copy_b.get("outcome"),
        "B_discard_toast": copy_b.get("toast"),
        "B_wizard_step_after": copy_b.get("wizard_step_after"),
        "B_run_residue_runs": residue,
        "runs_before_B": sorted(runs_snapshot_before_b),
        "runs_after_B": sorted(runs_snapshot_after_b),
        "runs_root": str(runs_root),
        "B_run_residue_ok": not residue,
        "B_book_txt": str(book_txt) if book_txt else "",
        "B_book_txt_sha256": sha256_file(book_txt) if book_txt and book_txt.exists() else "",
        "B_book_dir": str(book_dir) if book_dir else "",
        "shots": {"A": s_a.shots, "B": s_b.shots},
        "texts": s_a.texts + s_b.texts,
        "passed": bool(copy_all
                       and copy_a.get("resume_outcome") == "ok"
                       and copy_b.get("outcome") == "cancelled"
                       and not residue),
    }


# ---------------------------------------------------------------------------
# 会话包装：Session.run 需要 wizard 类
# ---------------------------------------------------------------------------

def _run_session(sess: Session, step_fn, wizard_cls) -> dict:
    from PySide6.QtCore import QTimer
    from main_window import MainWindow

    win = MainWindow(workspace=sess.ws)
    sess.win = win
    win.show()

    sess.state = {"done": False, "wizard": None}

    def tick():
        w = sess.state["wizard"] or find_window(sess.app, wizard_cls)
        if w is None:
            return
        sess.state["wizard"] = w
        if step_fn(sess, w):
            sess.state["done"] = True

    poll = QTimer()
    poll.setInterval(150)
    poll.timeout.connect(tick)
    poll.start()                     # 心跳先起：首次 processEvents 会进向导 exec

    deadline = time.monotonic() + sess.timeout_s
    while not sess.state["done"] and time.monotonic() < deadline:
        sess.app.processEvents()
        time.sleep(0.01)
    poll.stop()
    sess.app.processEvents()
    sess.elapsed_s = round(time.monotonic() - sess.t0, 2)
    sess.timed_out = not sess.state["done"]
    return {"window": win, "elapsed_s": sess.elapsed_s,
            "timed_out": sess.timed_out}


# ---------------------------------------------------------------------------
# S5 · ☰ 菜单重开：有当前书 → 从第 2 步开始
# ---------------------------------------------------------------------------

WIZARD_MENU_ITEM = "新手向导（重新观看）"


def s5(app) -> dict:
    """真实导入一本书成为「当前书」→ 真实点顶栏 ☰ → 真实触发菜单项 → 断言起始步。

    ``QMenu.exec`` 是 Qt 静态绑定，猴子补丁拦不住（实测补丁后仍走原生实现）。
    所以这里不拦 exec：点 ☰ 后菜单会真的弹出来（阻塞在信号处理里的嵌套循环，
    主循环仍在跑），心跳从 ``findChildren(QMenu)`` 里拿到这个**真实可见**的菜单，
    读出真实菜单项并触发 —— 与用户点菜单项同一条路径。
    """
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMenu
    from main_window import MainWindow
    from first_run_wizard import FirstRunWizard

    patch_file_dialog(EPUB)
    ws = fresh_env("s5", wizard_seen=True)      # 已看过 → 首启不自动弹
    win = MainWindow(workspace=ws)
    win.show()
    app.processEvents()

    # ---- 真实导入一本书，成为「当前书」----
    mod = win.import_module
    win.go("import")
    app.processEvents()
    mod.take_file(str(EPUB))
    t0 = time.monotonic()
    mod.click_next()
    while time.monotonic() - t0 < 180:
        app.processEvents()
        if mod.step() in (1, 2) and not mod.is_busy() and mod.next_enabled():
            mod.click_next()
        if mod.has_finished() or mod.error_text():
            break
        time.sleep(0.03)
    app.processEvents()
    import_ok = mod.has_finished()
    current_book = win._current_text_path

    opened: dict = {}
    menu_info: dict = {"items": [], "found": False}

    def tick():
        # 阶段 1：从真实弹出的菜单里读菜单项，并触发「新手向导」
        if not menu_info["found"]:
            menus = [m for m in win.findChildren(QMenu) if m.isVisible()]
            if not menus:
                return
            m = menus[0]
            menu_info["items"] = [x.text() for x in m.actions() if x.text()]
            acts = [x for x in m.actions() if x.text() == WIZARD_MENU_ITEM]
            if not acts:
                m.close()
                return
            menu_info["found"] = True
            act = acts[0]

            def fire():
                act.trigger()            # 与用户点菜单项完全同一条路径
                m.close()

            QTimer.singleShot(0, fire)
            return
        # 阶段 2：向导开窗 → 记录起始步后关窗
        ws_ = [x for x in app.topLevelWidgets()
               if isinstance(x, FirstRunWizard) and x.isVisible()]
        if not ws_ or opened:
            return
        w = ws_[0]
        opened.update({
            "start_step": w.step,
            "has_current_book": bool(getattr(w, "has_current_book", False)),
            "bars": list(w.bars.values()),
            "primary_text": w._primary.text(),
            "prev_visible": bool(w._prev.isVisible()),
            "banner": w._pending_hint(),
            "panel_texts": label_texts(w),
        })
        opened["shot"] = shot(w, "r3_s5_reopen.png")
        QTimer.singleShot(0, lambda: QTest.mouseClick(
            w._skip, Qt.MouseButton.LeftButton))

    poll = QTimer()
    poll.setInterval(120)
    poll.timeout.connect(tick)
    poll.start()
    QTimer.singleShot(0, lambda: QTest.mouseClick(
        topbar_more_button(win), Qt.MouseButton.LeftButton))

    deadline = time.monotonic() + 60
    while (not opened or wiz_still_visible(app, FirstRunWizard)) \
            and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    poll.stop()
    app.processEvents()

    texts = collect_texts(win) + (opened.get("panel_texts") or [])
    win.close()
    app.processEvents()

    return {
        "scenario": "S5 ☰ 菜单重开（有当前书从第 2 步开始）",
        "import_ok": import_ok,
        "current_book": Path(current_book).name if current_book else "",
        "current_book_path_exists": bool(current_book) and Path(current_book).exists(),
        "menu_items": menu_info["items"],
        "menu_item_found": menu_info["found"],
        "reopen_start_step": opened.get("start_step"),
        "has_current_book_flag": opened.get("has_current_book"),
        "starts_at_step2": opened.get("start_step") == 1,
        "step_bars": opened.get("bars"),
        "bars_expected": [100, 50, 0],
        "step2_primary_text": opened.get("primary_text"),
        "prev_button_visible": opened.get("prev_visible"),
        "step2_banner": opened.get("banner"),
        "shot": opened.get("shot"),
        "texts": texts,
        "passed": bool(import_ok and menu_info["found"]
                       and opened.get("start_step") == 1
                       and opened.get("has_current_book") is True
                       and opened.get("bars") == [100, 50, 0]),
    }


def wiz_still_visible(app, cls) -> bool:
    return any(isinstance(x, cls) and x.isVisible() for x in app.topLevelWidgets())


# ---------------------------------------------------------------------------
# S6 · 完成页跳历史记录页
# ---------------------------------------------------------------------------

def s6(app) -> dict:
    from first_run_wizard import FirstRunWizard

    patch_file_dialog(EPUB)
    st: dict = {}

    def plan(sess, w):
        ph = sess.phase
        if ph == "start":
            if _await_wizard_step(sess, 0):
                sess.phase = "importing"
                sess.click_later(w._primary, "S6.import")
            return False
        if ph == "importing":
            if _await_wizard_step(sess, 1):
                sess.phase = "correcting"
                sess.click_later(w._primary, "S6.correct")
            return False
        if ph == "correcting":
            if _await_wizard_step(sess, 2):
                st["correct_hits"] = (sess.win.oneclick_module._summary or {}).get("hits")
                sess.phase = "exporting"
                sess.click_later(w._primary, "S6.export")
            return False
        if ph == "exporting":
            if _await_wizard_step(sess, 3):
                st["complete_shot"] = shot(w, "r3_s6_complete.png")
                st["page_before_finish"] = sess.win.current_key
                st["export_path"] = w._export_path
                sess.phase = "finishing"
                sess.click_later(w._primary, "S6.finish")
                return True
            return False
        return False

    sess = Session(app, wizard_seen=False, tag="s6", timeout_s=400)
    sess.phase = "start"
    res = _run_session(sess, plan, FirstRunWizard)
    win = res["window"]
    sess.wizard = sess.state.get("wizard")
    sess.close()

    page_after = win.current_key
    hist = win.history_module
    rows = 0
    if hist is not None:
        from PySide6.QtWidgets import QLabel
        for lab in hist.findChildren(QLabel):
            t = lab.text() or ""
            if t.startswith("《") or ("替换" in t and "命中" in t):
                rows += 1
    out = Path(str(st.get("export_path") or ""))
    base_sha = sha256_file(BASELINE_EPUB) if BASELINE_EPUB.exists() else ""
    out_sha = sha256_file(out) if out.exists() else ""

    return {
        "scenario": "S6 完成页跳历史记录页",
        "elapsed_s": res["elapsed_s"],
        "ops": [dict(x) for x in sess.ops],
        "correction_hits": st.get("correct_hits"),
        "export_file": str(out),
        "export_exists": out.exists(),
        "export_size": out.stat().st_size if out.exists() else 0,
        "export_sha256": out_sha,
        "export_md5": md5_file(out) if out.exists() else "",
        "baseline_sha256": base_sha,
        "baseline_md5": md5_file(BASELINE_EPUB) if BASELINE_EPUB.exists() else "",
        "content_identical": bool(out_sha and base_sha and out_sha == base_sha),
        "page_before_finish": st.get("page_before_finish"),
        "page_after_finish": page_after,
        "jumped_to_history": page_after == "history",
        "history_rows": rows,
        "shots": {"complete": st.get("complete_shot")},
        "texts": sess.texts,
        "passed": bool(page_after == "history" and rows > 0
                       and out.exists() and (out_sha == base_sha if base_sha else True)),
    }


# ---------------------------------------------------------------------------
# 零露出扫描
# ---------------------------------------------------------------------------

#: 内部概念（与 tools/verify_m2t21.py 的 FORBIDDEN 同口径）：必须为 0
FORBIDDEN_CONCEPTS = [
    r"booksBak", r"booksFix", r"\bbooks\b", r"books/", r"books\\",
    r"\bspine\b", r"\bOPF\b", r"\bNCX\b", r"\bmanifest\b", r"\btoc\.ncx\b",
    r"rules\.json", r"\bphp\b", r"\bbat\b", r"\bpy\b",
    r"loadMapFromCsv", r"useMapsConfig", r"\bCSV\b",
    r"src/maps", r"logs/", r"\.tmp\b", r"\bMap::", r"\bCsv::",
    r"\bfixtext\.engine\b", r"\bEngineRequest\b", r"\bRuleSet\b",
]

#: 绝对路径（含沙箱路径）：超集检查，单独记账——baseline 在设置页「日志目录」
#: 与包根相关处本就有绝对值标签，不属于本卡引入，如实列出不并入断言。
ABS_PATH = [r"/home/", r"/tmp/", r"C:\\"]


def scan_leaks(texts: list[str]) -> dict:
    """两桶扫描：内部概念（断言）与绝对路径（记账、如实披露）。"""
    import re
    concepts: list[dict] = []
    paths: list[dict] = []
    for text in texts:
        for pat in FORBIDDEN_CONCEPTS:
            if re.search(pat, text):
                concepts.append({"pattern": pat, "text": text[:120]})
        for pat in ABS_PATH:
            if re.search(pat, text):
                paths.append({"pattern": pat, "text": text[:120]})
    return {
        "texts_scanned": len(texts),
        "concept_hits": concepts,
        "absolute_path_hits": paths,
        "concepts_clean": not concepts,
    }


# ---------------------------------------------------------------------------
# S1 · 新用户全路径（首启自动弹 → 导入 → 校正 → 导出 → 完成跳历史）
# ---------------------------------------------------------------------------

def s1(app) -> dict:
    """全新用户（设置里没有 wizardSeen）从首启向导真实走完一本书。

    每一步都是**真实点击**向导主按钮：文件选择对话框被替换成固定路径，
    导入 / 校正 / 导出走的是三个模块自己的既有流程，向导只负责调用。
    """
    from first_run_wizard import FirstRunWizard

    patch_file_dialog(EPUB)
    st: dict = {"t0": None}

    def mark(key: str, sess) -> None:
        st.setdefault(key, sess.now())

    def plan(sess, w):
        ph = sess.phase
        if ph == "start":
            if _await_wizard_step(sess, 0):
                st["t_wizard_shown"] = sess.now()
                sess.phase = "importing"
                sess.click_later(w._primary, "S1.import")
            return False
        if ph == "importing":
            if _await_wizard_step(sess, 1):
                mark("t_step1", sess)
                st["import_result"] = {
                    "title": getattr(w._import_result, "title", ""),
                    "chars": getattr(w._import_result, "text_chars", 0),
                }
                st["step1_panel"] = label_texts(w)
                st["shot_step1"] = shot(w, "r4_s1_step1_imported.png")
                sess.phase = "correcting"
                sess.click_later(w._primary, "S1.correct")
            return False
        if ph == "correcting":
            if _await_wizard_step(sess, 2):
                mark("t_step2", sess)
                summary = sess.win.oneclick_module._summary or {}
                st["correction"] = {
                    "hits": summary.get("hits"),
                    "chapters": summary.get("chapters"),
                    "elapsed_s": summary.get("elapsed_s"),
                }
                st["step2_panel"] = label_texts(w)
                st["shot_step2"] = shot(w, "r4_s1_step2_corrected.png")
                sess.phase = "exporting"
                sess.click_later(w._primary, "S1.export")
            return False
        if ph == "exporting":
            if _await_wizard_step(sess, 3):
                mark("t_step3", sess)
                st["export_path"] = str(w._export_path or "")
                st["step3_panel"] = label_texts(w)
                st["shot_step3"] = shot(w, "r4_s1_step3_exported.png")
                sess.phase = "finishing"
                sess.click_later(w._primary, "S1.finish")
            return False
        if ph == "finishing":
            if not wiz_still_visible(app, FirstRunWizard):
                mark("t_finish", sess)
                return True
            return False
        return False

    sess = Session(app, wizard_seen=False, tag="s1", timeout_s=600)
    sess.phase = "start"
    res = _run_session(sess, plan, FirstRunWizard)
    win = res["window"]
    sess.wizard = sess.state.get("wizard")
    sess.close()

    out = Path(str(st.get("export_path") or ""))
    base_sha = sha256_file(BASELINE_EPUB) if BASELINE_EPUB.exists() else ""
    out_sha = sha256_file(out) if out.exists() else ""

    def delta(a: str, b: str) -> float | None:
        if a in st and b in st:
            return round(st[b] - st[a], 2)
        return None

    return {
        "scenario": "S1 新用户全路径（首启向导自动弹出 → 三步真实完成 → 跳历史）",
        "elapsed_s": res["elapsed_s"],
        "ops": [dict(x) for x in sess.ops],
        "wizard_auto_shown": "t_wizard_shown" in st,
        "start_step": 0,
        "import_result": st.get("import_result"),
        "correction": st.get("correction"),
        "step_timing_s": {
            "wizard_shown": st.get("t_wizard_shown"),
            "import": delta("t_wizard_shown", "t_step1"),
            "correct": delta("t_step1", "t_step2"),
            "export": delta("t_step2", "t_step3"),
            "finish": delta("t_step3", "t_finish"),
        },
        "total_s": st.get("t_finish"),
        "export_file": str(out),
        "export_exists": out.exists(),
        "export_size": out.stat().st_size if out.exists() else 0,
        "export_sha256": out_sha,
        "export_md5": md5_file(out) if out.exists() else "",
        "baseline_sha256": base_sha,
        "baseline_md5": md5_file(BASELINE_EPUB) if BASELINE_EPUB.exists() else "",
        "content_identical": bool(out_sha and base_sha and out_sha == base_sha),
        "page_after_finish": win.current_key,
        "jumped_to_history": win.current_key == "history",
        "wizard_seen_after": str(__import__("fixtext_settings").AppSettings()
                                 .value("wizardSeen", "0")),
        "shots": {k: st.get(k) for k in ("shot_step1", "shot_step2", "shot_step3")},
        "texts": sess.texts,
        "passed": bool(
            "t_wizard_shown" in st
            and st.get("import_result") and st["import_result"].get("chars")
            and (st.get("correction") or {}).get("hits") is not None
            and out.exists() and (out_sha == base_sha if base_sha else False)
            and win.current_key == "history"
        ),
    }


# ---------------------------------------------------------------------------
# S2 · 跳过（不完成任何一步，只记已看过）
# ---------------------------------------------------------------------------

def s2(app) -> dict:
    from first_run_wizard import FirstRunWizard
    from fixtext_settings import AppSettings
    import first_run_wizard as frw

    st: dict = {}
    runs_before = snapshot_run_dirs()

    def plan(sess, w):
        if sess.phase == "start":
            if _await_wizard_step(sess, 0):
                st["start_step"] = w.step
                st["panel_texts"] = label_texts(w)
                st["shot"] = shot(w, "r4_s2_wizard_step1.png")
                sess.phase = "skipping"
                sess.click_later(w._skip, "S2.skip")
            return False
        if sess.phase == "skipping":
            if not wiz_still_visible(app, FirstRunWizard):
                st["closed"] = True
                return True
            return False
        return False

    sess = Session(app, wizard_seen=False, tag="s2", timeout_s=120)
    sess.phase = "start"
    res = _run_session(sess, plan, FirstRunWizard)
    win = res["window"]
    sess.wizard = sess.state.get("wizard")
    sess.close()

    seen_value = str(AppSettings().value("wizardSeen", "0"))
    runs_after = snapshot_run_dirs()
    new_runs = sorted(runs_after - runs_before)

    return {
        "scenario": "S2 跳过向导（只记已看过，不产生任何运行产物）",
        "elapsed_s": res["elapsed_s"],
        "ops": [dict(x) for x in sess.ops],
        "start_step": st.get("start_step"),
        "wizard_closed": bool(st.get("closed")),
        "wizard_seen_value": seen_value,
        "opens_on_first_run": frw.opens_on_first_run(),
        "page_after_skip": win.current_key,
        "new_run_dirs": new_runs,
        "shot": st.get("shot"),
        "texts": sess.texts,
        "passed": bool(st.get("closed") and seen_value == "1"
                       and not frw.opens_on_first_run()
                       and not new_runs),
    }


# ---------------------------------------------------------------------------
# S3 · 重启后不再自动弹（独立子进程，真重启）
# ---------------------------------------------------------------------------

S3_CHILD_CODE = '''
import json, os, sys, time
sys.path.insert(0, os.environ["S3_SRC"])
sys.path.insert(0, os.environ["S3_PKG"])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from main_window import MainWindow
from first_run_wizard import FirstRunWizard
win = MainWindow(workspace=os.environ["S3_WS"])
win.show()
visible = []
t0 = time.monotonic()
while time.monotonic() - t0 < 2.0:
    app.processEvents()
    time.sleep(0.01)
    visible.append(any(isinstance(x, FirstRunWizard) and x.isVisible()
                       for x in app.topLevelWidgets()))
print(json.dumps({"wizard_visible_samples": int(sum(visible)),
                  "samples_total": len(visible),
                  "page": win.current_key,
                  "wizard_seen": str(__import__("fixtext_settings")
                                    .AppSettings().value("wizardSeen", "0")),
                  "pid": os.getpid()}))
'''


def s3(app, *, settings_file: Path, ws: Path) -> dict:
    """起一个**新解释器进程**，在同一套设置下看首启向导还弹不弹。"""
    import subprocess

    ACC.mkdir(parents=True, exist_ok=True)
    child = ACC / "s3_child.py"
    child.write_text(S3_CHILD_CODE, encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "QT_QPA_PLATFORM": "offscreen",
        "FIXTEXT_SETTINGS_FILE": str(settings_file),
        "S3_SRC": str(SRC), "S3_PKG": str(PKG), "S3_WS": str(ws),
    })
    # 子进程沿用父进程的 PYTHONPATH（PySide6 装在 py312 site-packages 下）
    t0 = time.monotonic()
    proc = subprocess.run([sys.executable, "-u", str(child)],
                          capture_output=True, text=True, env=env, timeout=180)
    elapsed = round(time.monotonic() - t0, 2)
    payload: dict = {}
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except Exception:
                pass
    return {
        "scenario": "S3 重启后不再自动弹向导（独立子进程）",
        "child_rc": proc.returncode,
        "child_pid": payload.get("pid"),
        "restart_elapsed_s": elapsed,
        "wizard_visible_samples": payload.get("wizard_visible_samples"),
        "samples_total": payload.get("samples_total"),
        "wizard_seen_in_child": payload.get("wizard_seen"),
        "page": payload.get("page"),
        "stdout_tail": (proc.stdout or "").strip().splitlines()[-3:],
        "stderr_tail": (proc.stderr or "").strip().splitlines()[-3:],
        "passed": bool(proc.returncode == 0
                       and payload.get("wizard_visible_samples") == 0
                       and payload.get("wizard_seen") == "1"),
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="逗号分隔：S1,S2,S3,S4,S5,S6")
    args = ap.parse_args()
    only = [x.strip().upper() for x in args.only.split(",") if x.strip()]

    EVID.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    base = {
        "task": "M4-EX.2c-R4 六场景收口验收",
        "sample_input": str(EPUB),
        "sample_sha256": sha256_file(EPUB) if EPUB.exists() else "",
        "baseline_epub": str(BASELINE_EPUB),
        "baseline_sha256": sha256_file(BASELINE_EPUB) if BASELINE_EPUB.exists() else "",
        "baseline_md5": md5_file(BASELINE_EPUB) if BASELINE_EPUB.exists() else "",
        "qt_platform": os.environ.get("QT_QPA_PLATFORM"),
        "python": sys.version.split()[0],
        "pyside": __import__("PySide6").__version__,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    summary: dict = {}
    rc = 0

    def emit(tag: str, r: dict, extra_scan: bool = True) -> None:
        nonlocal rc
        texts = r.pop("texts", []) if extra_scan else []
        if extra_scan:
            r["text_scan"] = scan_leaks(texts)
        out = EVID / f"ex2c_r4_{tag.lower()}.json"
        out.write_text(json.dumps({**base, tag: r}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        summary[tag] = {"passed": bool(r.get("passed")), "evidence": out.name}
        rc |= 0 if r.get("passed") else 1
        print(f"[{tag}] PASS={r.get('passed')} -> {out}", flush=True)

    if not only or "S1" in only:
        r = s1(app)
        print(f"[S1] 首启弹窗={r['wizard_auto_shown']} 计时={r['step_timing_s']} "
              f"总={r['total_s']}s 导出md5={r['export_md5']} "
              f"与基线一致={r['content_identical']} 落地页={r['page_after_finish']} "
              f"PASS={r['passed']}", flush=True)
        emit("S1", r)

    if not only or "S2" in only:
        r = s2(app)
        print(f"[S2] 起始步={r['start_step']} 关窗={r['wizard_closed']} "
              f"wizardSeen={r['wizard_seen_value']} "
              f"仍会弹={r['opens_on_first_run']} 新运行目录={r['new_run_dirs']} "
              f"PASS={r['passed']}", flush=True)
        emit("S2", r)

    if not only or "S3" in only:
        s2_dir = ACC / "s2"
        r = s3(app, settings_file=s2_dir / "settings.ini", ws=s2_dir / "ws")
        print(f"[S3] 子进程rc={r['child_rc']} 弹窗样本={r['wizard_visible_samples']}"
              f"/{r['samples_total']} wizardSeen={r['wizard_seen_in_child']} "
              f"耗时={r['restart_elapsed_s']}s PASS={r['passed']}", flush=True)
        emit("S3", r, extra_scan=False)

    if not only or "S4" in only:
        r = s4(app)
        print(f"[S4] 文案逐字={r['copy_all_match']} 继续={r['A_resume_outcome']}"
              f" 放弃={r['B_discard_outcome']} 残留={r['B_run_residue_runs']} "
              f"PASS={r['passed']}", flush=True)
        emit("S4", r)

    if not only or "S5" in only:
        r = s5(app)
        print(f"[S5] 起始步={r['reopen_start_step']} 有书={r['has_current_book_flag']}"
              f" 菜单项={r['menu_item_found']} PASS={r['passed']}", flush=True)
        emit("S5", r)

    if not only or "S6" in only:
        r = s6(app)
        print(f"[S6] 落地页={r['page_after_finish']} 历史条数={r['history_rows']} "
              f"成品={r['export_size']}B sha={r['export_sha256'][:16]} "
              f"与基线一致={r['content_identical']} PASS={r['passed']}", flush=True)
        emit("S6", r)

    summary["OVERALL"] = ("PASS" if rc == 0 else "FAIL")
    (EVID / "ex2c_r4_summary.json").write_text(
        json.dumps({"generated_at": base["generated_at"], **summary},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nOVERALL: {'PASS' if rc == 0 else 'FAIL'}", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
