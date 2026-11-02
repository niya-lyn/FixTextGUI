"""M2-T2.10 验收：检查页与历史页的真实数据链路（自采实跑）。

全程真实链路，不做桩：
  S1 空状态：未校正时两页给人话引导，一条假数据都没有
  S2 真实导入公版样本EPUB（三步向导全自动走完）
  S3 一键校正：真实点击主按钮，完整跑完六阶段
  S4 检查页：注入本次运行的引号报告 → 条目数与 error_count 一致
  S5 历史页：本次运行成为一条记录（书名 / 时间 / 命中数 / 状态）
  S6 重启进程：全新窗口只凭磁盘重扫 → 历史记录仍在
  S7 重新导出：走真实导出执行层，产出 EPUB 的 sha256 与基线逐字节一致
  S8 技术名词零露出复扫

运行：
    QT_QPA_PLATFORM=offscreen python3.12 tools/accept_t210.py
产出：evidence/accept_t210.json + evidence/t210/*.png
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG / "fixtext_ui"))
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _mark_wizard_seen():
    try:
        from PySide6.QtCore import QSettings
        s = QSettings("FixText", "V1")
        s.setValue("wizardSeen", "1")
        s.sync()
    except Exception:                                   # noqa: BLE001
        pass


from PySide6.QtCore import Qt, QTimer, QSettings          # noqa: E402
from PySide6.QtTest import QTest                          # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton  # noqa: E402

import main_window as M                                   # noqa: E402
import fixtext_check as checkdata                          # noqa: E402
import fixtext_history as histdata                         # noqa: E402
import fixtext_export as fxexport                          # noqa: E402

from _public_fixture import EPUB  # noqa: E402  M5-OS.1：公版 fixture 唯一来源
BASE_SHA = "717fdfcee76fe3ee74d9a8bff20afbc84e7150bcbf5ee1a5b033a01739641dc2"
EVID = PKG / "evidence"
SHOTS = EVID / "t210"

LEAK_PATTERNS = [
    r"\bmerge\b", r"\blayout\b", r"\breplace\b", r"\bquote\b",
    r"\bbookmap\b", r"\brestore\b", r"run_pipeline", r"state\.json",
    r"subprocess", r"\bstdout\b", r"\bstderr\b", r"exit code",
    r"/home/", r"fixtext_pipeline", r"\.go\b", r"\.report\.json",
    r"\bruns/\b", r"run-\d",
]


def sha256_file(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_texts(widget) -> list[str]:
    texts = []
    for w in [widget] + widget.findChildren(object):
        for attr in ("text", "toolTip", "accessibleName", "windowTitle"):
            try:
                v = getattr(w, attr, None)
                v = v() if callable(v) and attr in ("text", "toolTip") else v
            except Exception:                            # noqa: BLE001
                v = None
            if isinstance(v, str) and v.strip():
                texts.append(v.strip())
    return texts


def screen_leaks(texts) -> list[dict]:
    import re
    bad = []
    for t in texts:
        for pat in LEAK_PATTERNS:
            if re.search(pat, t):
                bad.append({"pattern": pat, "text": t[:110]})
    return bad


def wait_until(cond, timeout_s=180.0, step=0.05):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(step)
    return False


def click_correction(win):
    """真实点击「开始校正」并等它跑完（模态进度框，用 exec 内轮询）。"""
    mod = win.oneclick_module
    holder = {"done": False}

    def poll():
        if mod._worker is None and mod._dlg is None and mod._outcome:
            holder["done"] = True

    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(poll)
    timer.start()
    t0 = time.monotonic()
    QTest.mouseClick(mod.run_btn, Qt.MouseButton.LeftButton)
    total = round(time.monotonic() - t0, 2)
    timer.stop()
    QApplication.processEvents()
    return dict(outcome=mod._outcome, total_s=total,
                summary=mod._summary or {}, toast=mod.status.text())


def open_window(workspace):
    """新窗口 = 新进程语义：只给工作区，其余全靠磁盘。"""
    win = M.MainWindow(workspace)
    win.resize(1280, 820)
    win.show()
    QApplication.processEvents()
    return win


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    ws = PKG.parent / "t210_ws"
    ws.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    _mark_wizard_seen()
    M.load_qss(app)

    # 每轮从干净的运行目录起跑：S1 要验「未校正时的空状态」，
    # 上一轮留下的 run-* 会让它误判（历史页本来就会扫到它们）。
    import shutil
    runs_root = PKG / "runs"
    if runs_root.exists():
        shutil.rmtree(runs_root, ignore_errors=True)
    runs_root.mkdir(parents=True, exist_ok=True)
    for stale in (ws / "导出结果",):
        if stale.exists():
            shutil.rmtree(stale, ignore_errors=True)

    report: dict = {}
    ok = True

    # ---------------- S1 空状态 ----------------
    win = open_window(ws)
    win.go("check")
    QApplication.processEvents()
    chk = win.page("check")
    hist = win.page("history")
    check_empty_ok = (chk.has_data is False and chk.probs == []
                      and "校正" in chk._empty_text())
    win.go("history")
    QApplication.processEvents()
    hist_texts = [l.text() for l in hist.findChildren(QLabel)]
    hist_empty_ok = (hist.row_count == 0
                     and any("还没有校正记录" in t for t in hist_texts))
    fakes = [t for t in hist_texts if any(k in t for k in
             ("星河彼端", "旧巷杂记", "灯下漫笔"))]
    win.grab().save(str(SHOTS / "s1_empty_history.png"))
    win.go("check")
    QApplication.processEvents()
    win.grab().save(str(SHOTS / "s1_empty_check.png"))
    print(f"[S1] 空状态：检查页无假数据={check_empty_ok}，"
          f"历史页人话引导={hist_empty_ok}，残留假书名={len(fakes)}")
    report["s1_empty"] = dict(check_empty=check_empty_ok,
                              history_empty=hist_empty_ok,
                              fake_books_left=len(fakes),
                              check_hint=chk._empty_text())
    ok = ok and check_empty_ok and hist_empty_ok and not fakes

    # ---------------- S2 真实导入 ----------------
    imp = win.import_module
    t0 = time.monotonic()
    imp._take_file(str(EPUB))  # M5-EX.3：选完即开跑
    assert imp._kind == "epub", "应为 EPUB"
    if not wait_until(lambda: imp.has_finished() or bool(imp.error_text()), 300):
        print(json.dumps(dict(error="导入超时"), ensure_ascii=False))
        return 1
    if imp.error_text() or imp._result is None:
        print(json.dumps(dict(error=imp.error_text() or "无结果"), ensure_ascii=False))
        return 1
    import_s = round(time.monotonic() - t0, 2)
    res = imp._result
    print(f"[S2] 导入完成 {import_s}s：{res.chapters} 章 / {res.text_chars:,} 字，"
          f"mode={res.epub_mode}，校正上下文={'有' if win.oneclick_module.run_context else '无'}")
    report["s2_import"] = dict(seconds=import_s, chapters=res.chapters,
                               text_chars=res.text_chars, epub_mode=res.epub_mode)
    ok = ok and bool(win.oneclick_module.run_context)

    # ---------------- S3 一键校正 ----------------
    win.go("oneclick")
    QApplication.processEvents()
    r = click_correction(win)
    summary = r["summary"]
    print(f"[S3] 校正 {r['outcome']} {r['total_s']}s：{summary.get('chapters')} 章 / "
          f"{summary.get('quote_errors')} 问题 / {summary.get('hits')} 命中 / "
          f"sha={str(summary.get('restored_sha256'))[:12]}")
    report["s3_correction"] = dict(outcome=r["outcome"], seconds=r["total_s"],
                                   chapters=summary.get("chapters"),
                                   quote_errors=summary.get("quote_errors"),
                                   hits=summary.get("hits"),
                                   restored_sha256=summary.get("restored_sha256"),
                                   workdir=summary.get("workdir"))
    ok = ok and r["outcome"] == "ok"

    run_dir = summary.get("workdir") or ""

    # ---------------- S4 检查页真实条目 ----------------
    win.go("check")
    QApplication.processEvents()
    chk = win.page("check")
    shown = len(chk.probs)
    declared = summary.get("quote_errors")
    raw = checkdata.load_report(run_dir)
    print(f"[S4] 检查页：清单 {shown} 条 / 报告声明 {declared} / 直接读数 "
          f"{raw['found']}（一致={raw['consistent']}）；可自动改 {raw['auto_fixable']}，"
          f"需人工 {raw['manual']}；分页 {chk.pages} 页×{__import__('check_module').PAGE_SIZE}")
    s4_ok = (shown == declared == raw["found"] and chk.has_data)
    win.grab().save(str(SHOTS / "s4_check_real.png"))
    report["s4_check"] = dict(items=shown, declared=declared, found=raw["found"],
                              consistent=raw["consistent"],
                              auto_fixable=raw["auto_fixable"],
                              manual=raw["manual"], pages=chk.pages,
                              first_item={k: raw["items"][0][k]
                                          for k in ("line", "type", "advice")})
    ok = ok and s4_ok

    # ---------------- S5 历史页出现本次记录 ----------------
    win.go("history")
    QApplication.processEvents()
    hist = win.page("history")
    hist.refresh()
    QApplication.processEvents()
    rec = histdata.find_by_run_dir(histdata.scan_runs(PKG / "runs"), run_dir)
    print(f"[S5] 历史页：{hist.row_count} 条记录；本次 = "
          f"{rec['book'] if rec else None} / {rec['time'] if rec else None} / "
          f"命中 {rec['hits'] if rec else None} / 状态 {rec['status'] if rec else None}")
    s5_ok = bool(rec) and rec["hits"] == summary.get("hits") and rec["status"] == "ok"
    win.grab().save(str(SHOTS / "s5_history_real.png"))
    report["s5_history"] = dict(rows=hist.row_count, record=rec)
    ok = ok and s5_ok

    # ---------------- S6 重启后历史仍在 ----------------
    win.close()
    QApplication.processEvents()
    win2 = open_window(ws)
    win2.go("history")
    QApplication.processEvents()
    hist2 = win2.page("history")
    hist2.refresh()
    QApplication.processEvents()
    rec2 = histdata.find_by_run_dir(histdata.scan_runs(PKG / "runs"), run_dir)
    print(f"[S6] 重启后：历史 {hist2.row_count} 条，本次记录还在 = {bool(rec2)}，"
          f"书名 {rec2['book'] if rec2 else None}")
    s6_ok = bool(rec2) and hist2.row_count >= 1
    win2.grab().save(str(SHOTS / "s6_history_restarted.png"))
    report["s6_restart"] = dict(rows=hist2.row_count, found=bool(rec2),
                                book=rec2["book"] if rec2 else None)
    ok = ok and s6_ok

    # ---------------- S7 重新导出（sha 对齐基线）----------------
    hist2.set_export_ctx({
        "import_record": None,          # 模拟重启：没有导入记录在内存
        "pipeline_root": str(PKG / "pipeline"),
        "out_dir": str(ws / "导出结果"),
        "baseline_sha256": summary.get("restored_sha256") or "",
    })
    got: dict = {}

    def on_export(payload):
        got["payload"] = payload
    hist2.exportFinished.connect(on_export)

    idx = next(i for i, t in enumerate(hist2.tasks) if t["run_dir"] == run_dir)
    hist2._run_export(hist2.tasks[idx])
    if not wait_until(lambda: "payload" in got, 300):
        print(json.dumps(dict(error="重新导出超时"), ensure_ascii=False))
        return 1
    exported = None
    for p in (ws / "导出结果").rglob("*"):
        if p.is_file() and p.suffix.lower() == ".epub":
            exported = p
            break
    sha = sha256_file(exported) if exported else ""
    print(f"[S7] 重新导出：{exported.name if exported else None}，"
          f"sha={sha[:12]}，与基线一致={sha == BASE_SHA}")
    s7_ok = bool(exported) and sha == BASE_SHA
    report["s7_reexport"] = dict(file=str(exported) if exported else None,
                                 sha256=sha,
                                 equals_baseline=sha == BASE_SHA,
                                 signal=got.get("payload"))
    ok = ok and s7_ok

    # ---------------- S8 零露出复扫 ----------------
    win2.show()
    QApplication.processEvents()
    for key in ("home", "import", "oneclick", "check", "vocab", "export", "history"):
        win2.go(key)
        QApplication.processEvents()
    texts = collect_texts(win2)
    leaks = screen_leaks(texts)
    print(f"[S8] 零露出：扫描 {len(texts)} 条界面文本，命中 {len(leaks)}")
    for l in leaks[:8]:
        print("    ", l)
    report["s8_zero_leak"] = dict(scanned=len(texts), hits=leaks)
    ok = ok and not leaks

    win2.close()
    report["passed"] = bool(ok)
    out = EVID / "accept_t210.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n验收{'通过' if ok else '未通过'} → {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
