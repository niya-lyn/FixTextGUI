"""M2-T2.5 端到端冒烟（验收④）：合并后的完整用户路径。

路径全部走真实链路，不做桩：
  1. 主窗口（六入口 + 三个真模块挂载）
  2. 导入《炮火弧线》EPUB：选择文件 → 章节预览（验证封面不再被叫「未命名章节」）
     → 直接处理 → 导入完成 → bookReady 接力把运行上下文交给一键校正页
  3. 一键校正：真实点击主按钮 → 「整理排版」阶段真实点击取消 →
     验证取消后 runs 目录无脏状态（半成品 run-* 目录必须被清理）
  4. 复跑：再次真实点击 → 完整跑完六阶段，成品 EPUB 存在，原书 sha 不变
  5. 异常注入：worker 风格的意外异常经 error_center.report → 人话错误卡，
     卡上文本不含堆栈 / 类名 / 沙箱路径
  6. 全窗零露出扫描（控件树文本，口径同 accept_t23）

运行：
    QT_QPA_PLATFORM=offscreen python3.12 tools/smoke_e2e.py 2> evidence/smoke_stderr.log
产出：evidence/smoke_e2e.json
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG / "fixtext_ui"))
sys.path.insert(0, str(PKG))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QListWidget

import fixtext_error_center as error_center
import main_window as M

EPUB = PKG.parent / "in" / "paohuo.epub"
# 【M2-T2.7】布局适配：语料与包同级时直接用同级文件
if not EPUB.exists():
    EPUB = PKG.parent / "paohuo.epub"
WS = PKG.parent / "e2e_ws"
RUNS_ROOT = PKG / "runs"
EVID = PKG / "evidence"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_texts(widget) -> list[str]:
    """收控件树上所有用户可见文本（text/toolTip/placeholder/windowTitle）。"""
    from PySide6.QtWidgets import QWidget
    texts = []
    for w in [widget] + widget.findChildren(QWidget):
        for name in ("text", "toolTip", "placeholderText", "windowTitle"):
            try:
                v = getattr(w, name)()
            except Exception:
                continue
            if v:
                texts.append(v)
    return [t for t in texts if t]


def wait_until(cond, timeout_s: float = 120.0, step: float = 0.05):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        if cond():
            return True
        QApplication.processEvents()
        time.sleep(step)
    return False


LEAK_PATTERNS = [
    r"\bmerge\b", r"\blayout\b", r"\breplace\b", r"\bquote\b",
    r"\bbookmap\b", r"\brestore\b", r"run_pipeline", r"state\.json",
    r"subprocess", r"\bstdout\b", r"\bstderr\b", r"exit code",
    r"/home/", r"fixtext_pipeline", r"\.go\b",
]


def scan_leaks(texts):
    bad = []
    for t in texts:
        for pat in LEAK_PATTERNS:
            if re.search(pat, t):
                bad.append({"pattern": pat, "text": t[:120]})
    return bad


def run_correction_with_click(win, cancel_at_stage: int | None):
    """真实点击主按钮跑校正；可选在目标阶段真实点击取消。

    复用 accept_t23 的 exec 内轮询模式（QTimer 在模态对话框的事件循环里跑）。
    """
    mod = win.oneclick_module
    events = []
    state = {"cancel_click": None, "cancelled": None}

    def poll():
        w = mod._worker
        dlg = mod._dlg
        if w is None or dlg is None:
            return
        events.append({
            "t": round(time.monotonic(), 2),
            "stage": w.job.current_index,
            "percent": w.snapshot()["percent"],
            "ui_step": dlg.step_name.text(),
        })

    def watch_cancel():
        w = mod._worker
        dlg = mod._dlg
        if w is None or dlg is None or state["cancel_click"] is not None:
            return
        if w.job.current_index == cancel_at_stage:
            state["cancel_click"] = time.monotonic()
            QTest.mouseClick(dlg.cancel_btn, Qt.MouseButton.LeftButton)

    poller = QTimer(); poller.setInterval(100); poller.timeout.connect(poll)
    if cancel_at_stage is not None:
        watcher = QTimer(); watcher.setInterval(50); watcher.timeout.connect(watch_cancel)
        watcher.start()
    poller.start()

    t0 = time.monotonic()
    QTest.mouseClick(mod.run_btn, Qt.MouseButton.LeftButton)   # 真实用户路径
    total_s = round(time.monotonic() - t0, 2)

    poller.stop()
    if cancel_at_stage is not None:
        watcher.stop()
    return dict(outcome=mod._outcome, total_s=total_s, events=events,
                summary=mod._summary, toast=mod.status.text())


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    WS.mkdir(parents=True, exist_ok=True)
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    log_dir = PKG.parent / "e2e_logs"
    error_center.init(str(log_dir))
    error_center.install_app_hooks()

    report: dict = {}
    ok = True

    app = QApplication.instance() or QApplication([])
    M.load_qss(app)
    win = M.MainWindow(WS)
    win.resize(M.WINDOW_W if hasattr(M, "WINDOW_W") else 1280, 820)
    win.show()
    error_center.set_dialog_host(win)
    QApplication.processEvents()

    imp = win.import_module
    oc = win.oneclick_module

    # ---- 1. 真实导入（选择文件通道 → 三步向导全自动走完）----
    t0 = time.monotonic()
    imp._take_file(str(EPUB))
    assert imp._kind == "epub", "应为 EPUB"
    # 第 2 步：直接处理（默认单选），点下一步 → 章节预览
    imp._next()
    if not wait_until(lambda: imp._step == 2, 120):
        report["import"] = {"error": "预览超时", "step": imp._step}
        print(json.dumps(report, ensure_ascii=False)); return 1
    lst = imp.chapter_pane.list
    first_row = lst.item(0).text()
    rows = [lst.item(i).text() for i in range(min(3, lst.count()))]
    cover_ok = first_row == "封面"
    print(f"[1] 预览完成：共 {lst.count()} 行，首行 = {first_row!r}，"
          f"封面标注正确 = {cover_ok}，前3行 = {rows}")
    report["preview"] = dict(rows_total=lst.count(), first_row=first_row,
                             cover_labeled=cover_ok, first_rows=rows)
    ok = ok and cover_ok

    # 第 3 步：开始导入
    imp._next()
    if not wait_until(lambda: imp._step == 4, 300):
        report["import"] = {"error": "导入超时", "step": imp._step}
        print(json.dumps(report, ensure_ascii=False)); return 1
    import_s = round(time.monotonic() - t0, 2)
    result = imp._result
    ctx_ready = bool(oc.run_context)
    print(f"[1] 导入完成 {import_s}s：{result.chapters} 章 / 约 {result.text_chars:,} 字"
          f" → 一键校正上下文已就绪 = {ctx_ready}")
    report["import"] = dict(seconds=import_s, chapters=result.chapters,
                            text_chars=result.text_chars,
                            title=result.title, context_ready=ctx_ready,
                            epub_mode=result.epub_mode)
    ok = ok and ctx_ready and result.epub_mode == "direct"

    # ---- 2. 一键校正：排版阶段取消 → 脏状态检查 ----
    before_runs = set(p.name for p in RUNS_ROOT.iterdir())
    r1 = run_correction_with_click(win, cancel_at_stage=1)
    leftover = [p.name for p in RUNS_ROOT.iterdir() if p.name not in before_runs]
    cancel_clean = (r1["outcome"] == "cancelled" and not leftover)
    print(f"[2] 取消场景：outcome={r1['outcome']} {r1['total_s']}s，"
          f"runs 残留 = {leftover}，无脏状态 = {cancel_clean}")
    report["cancel"] = dict(outcome=r1["outcome"], seconds=r1["total_s"],
                            runs_leftover=leftover, clean=cancel_clean,
                            toast=r1["toast"])
    ok = ok and cancel_clean

    # ---- 3. 复跑完整完成 ----
    orig_sha_before = sha256_file(EPUB)
    r2 = run_correction_with_click(win, cancel_at_stage=None)
    summary = r2["summary"] or {}
    stage_elapsed = summary.get("stage_elapsed", {})
    workdir = summary.get("workdir") or ""
    restored = Path(workdir) / "06_restore" / "paohuo_restored.epub" if workdir else None
    restored_ok = restored is not None and restored.exists()
    orig_intact = sha256_file(EPUB) == orig_sha_before
    print(f"[3] 复跑完成：outcome={r2['outcome']} {r2['total_s']}s，"
          f"成品存在 = {restored_ok}，原书未动 = {orig_intact}，"
          f"阶段耗时 = { {k: round(v,1) for k,v in stage_elapsed.items()} }")
    report["rerun"] = dict(outcome=r2["outcome"], seconds=r2["total_s"],
                           restored_epub=str(restored) if restored else None,
                           restored_exists=restored_ok, original_intact=orig_intact,
                           stage_elapsed={k: round(v, 2) for k, v in stage_elapsed.items()},
                           total_elapsed_s=summary.get("total_elapsed_s"))
    ok = ok and r2["outcome"] == "ok" and restored_ok and orig_intact

    # ---- 4. 异常注入 → 人话错误卡 ----
    error_center.report(ValueError("secret-internal: /home/gem/x.py boom"),
                        context="import")
    QApplication.processEvents()
    card_texts = []
    for w in QApplication.topLevelWidgets():
        if isinstance(w, QDialog) and w.isVisible():
            card_texts += [t for t in collect_texts(w) if t]
    blob = " ".join(card_texts)
    human_ok = bool(card_texts) and "ValueError" not in blob and "/home/" not in blob
    print(f"[4] 错误卡：采集 {len(card_texts)} 条文本，人话且无内部细节 = {human_ok}")
    report["error_card"] = dict(text_count=len(card_texts),
                                human_only=human_ok, texts=card_texts[:12])
    ok = ok and human_ok
    # 关掉卡，继续
    for w in QApplication.topLevelWidgets():
        if isinstance(w, QDialog) and w.isVisible():
            w.close()
    QApplication.processEvents()

    # 诊断日志真的写了（技术细节只进日志）
    rec = error_center.last_record()
    log_written = bool(rec) and rec.get("code") == "U-R00"
    print(f"[4] 诊断日志：code={rec.get('code') if rec else None}，已写入 = {log_written}")
    report["diaglog"] = dict(record=rec is not None,
                             code=rec.get("code") if rec else None,
                             has_traceback=bool(rec and rec.get("traceback")))
    ok = ok and log_written

    # ---- 5. 全窗零露出 ----
    win.show()
    QApplication.processEvents()
    for key in ("home", "import", "oneclick", "check", "vocab", "export", "history"):
        win.go(key); QApplication.processEvents()
    texts = collect_texts(win)
    leaks = scan_leaks(texts)
    print(f"[5] 零露出：扫描 {len(texts)} 条界面文本，命中 {len(leaks)}")
    report["zero_leak"] = dict(scanned=len(texts), hits=leaks)
    ok = ok and not leaks

    # ---- 收尾 ----
    win.close()
    QApplication.processEvents()
    report["passed"] = ok
    (EVID / "smoke_e2e.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SMOKE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
