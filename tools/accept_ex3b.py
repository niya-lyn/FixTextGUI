"""M4-EX.3b 验收：各模块按书联动（两书实测 + 逐页截图 + 来回切换 + 已导出写点）。

全部跑真实界面路径，不做"调内部函数"式的假验证：

1. 用**真实导入链路**把两本书导进工作区（正文里埋了可区分数量的引号
   错误：甲书 10 处、乙书 20 处——检查页的数据量本身就是书的指纹）。
2. 两本书各跑一次**真实六阶段校正**（真实点击一键校正主按钮，模态进度条
   里等它跑完），运行目录必须落在 runs/<书 id>/ 下。
3. 切换当前书后逐页断言 + 截图：检查页 / 历史页 / 导出页 / 一键校正页
   只允许出现当前书的数据。
4. A/B 来回连续切换多次，数据始终正确、无崩溃。
5. 真实点击导出按钮导出甲书 → 书目录出现真实导出记录、书架「已导出」
   点亮、乙书不亮。
6. 「重启」用独立子进程重建 MainWindow，按书数据仍然正确。

用法：python3.12 tools/accept_ex3b.py [--pkg <包根>] [--out <输出目录>]
退出码 0 = 全部通过。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = Path(__file__).resolve().parent
DEFAULT_PKG = HERE.parent
QENV = "/home/gem/.aily/.cli/qtenv/lib/python3.12/site-packages"

CHECKS: list[tuple[str, str, bool, str]] = []


def record(key: str, label: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((key, label, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {key} {label}" + (f" —— {detail}" if detail else ""))


def _make_books(src_root: Path) -> tuple[Path, Path]:
    """造两本正文带引号错误的 TXT 书源（错误数可区分：甲 10 / 乙 20）。"""
    a_block = "第一章 起风\n\n他说：“今天天气不错。\n\n风更大了。\n"
    b_block = "第二章 落雨\n\n她说：“雨停了。\n\n路很滑。\n\n他又说：“再来一次。\n\n结束。\n"
    a = src_root / "北岭旧事.txt"
    a.write_text(a_block * 10, encoding="utf-8")
    b = src_root / "南川杂记.txt"
    b.write_text(b_block * 10, encoding="utf-8")
    return a, b


def _shot(win, app, out: Path, name: str) -> Path:
    p = out / name
    win.grab().save(str(p))
    return p


def _wait_export(mod, app, timeout_s: float = 120.0) -> bool:
    """等后台导出结束（界面线程轮询，不阻塞信号送达）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if not mod._running and mod.outcome is not None:
            return True
        time.sleep(0.05)
    return False


def _page_state(win) -> dict:
    """抓四页的"当前书指纹"（书名 + 数据归属），用于切换前后对比。"""
    chk = win.check_module
    hist = win.history_module
    exp = win.export_module
    one = win.oneclick_module
    return {
        "check_book": (chk.report or {}).get("book") if chk.has_data else "",
        "check_found": (chk.report or {}).get("found") if chk.has_data else 0,
        "hist_titles": [t.get("title") for t in (hist.tasks or [])],
        "export_title": (exp.source.title if exp.source else ""),
        "export_corrected": bool(exp.source and exp.source.corrected),
        "oneclick_runs_root": str(((one.run_context or {}).get("runs_root") or "")),
    }


def _assert_book_pages(win, key: str, title: str, book_id: str,
                       found: int, app, out: Path, shots: list[str]) -> None:
    """当前书必须是 <title>：四页逐项断言 + 逐页截图。"""
    st = _page_state(win)
    record(f"{key}a", f"检查页只显示《{title}》的问题",
           st["check_book"] == title and st["check_found"] == found,
           f"book={st['check_book']!r} found={st['check_found']} 期望={found}")
    record(f"{key}b", f"历史页只有《{title}》的记录",
           st["hist_titles"] and set(st["hist_titles"]) == {title},
           f"titles={st['hist_titles']}")
    record(f"{key}c", f"导出页挂的是《{title}》的最近校正产物",
           st["export_title"] == title and st["export_corrected"],
           f"title={st['export_title']!r} corrected={st['export_corrected']}")
    record(f"{key}d", f"一键校正上下文指向《{title}》的运行目录",
           st["oneclick_runs_root"].endswith(f"/{book_id}"),
           f"runs_root={st['oneclick_runs_root']!r}")
    for page, name in (("oneclick", f"{key}_1_oneclick"), ("check", f"{key}_2_check"),
                       ("history", f"{key}_3_history"), ("export", f"{key}_4_export")):
        win.go(page)
        app.processEvents()
        p = _shot(win, app, out, f"{name}.png")
        ok = p.exists() and p.stat().st_size > 8000
        shots.append(p.name)
        if not ok:
            record(f"{key}-shot-{page}", f"{page} 页截图落盘", False, str(p))
    record(f"{key}e", f"四页截图已落盘（{title}）", True, ", ".join(shots[-4:]))


def _child_probe(pkg: Path, ws: Path) -> dict:
    """独立子进程：重建 MainWindow（= 重启），报各页当前书数据。"""
    code = r"""
import json, os, sys
sys.path[:0] = [os.environ["FX_Q"], str(os.environ["FX_PKG"]),
                os.path.join(os.environ["FX_PKG"], "fixtext_ui")]
from PySide6.QtWidgets import QApplication
import fixtext_settings
app = QApplication([])
_qs = fixtext_settings.AppSettings()
_qs.setValue("wizardSeen", "1")
_qs.sync()
import main_window as mw
w = mw.MainWindow(workspace=os.environ["FX_WS"])
chk = w.check_module
print("@@RESULT@@" + json.dumps({
    "chip": w.book_chip.name.full_text(),
    "check_book": (chk.report or {}).get("book") if chk.has_data else "",
    "check_found": (chk.report or {}).get("found") if chk.has_data else 0,
    "hist_titles": [t.get("title") for t in (w.history_module.tasks or [])],
    "export_title": w.export_module.source.title if w.export_module.source else "",
    "runs_root": str(w.history_module._runs_root or ""),
}, ensure_ascii=False))
"""
    env = dict(os.environ)
    env.update({
        "FX_PKG": str(pkg), "FX_WS": str(ws),
        "QT_QPA_PLATFORM": "offscreen", "FX_Q": QENV,
    })
    proc = subprocess.run([sys.executable, "-c", code], env=env,
                          capture_output=True, text=True, timeout=180)
    for line in proc.stdout.splitlines():
        if line.startswith("@@RESULT@@"):
            return json.loads(line[len("@@RESULT@@"):])
    raise RuntimeError(f"子进程没报结果：\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr[-2000:]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", default=str(DEFAULT_PKG))
    ap.add_argument("--out", default=str(HERE.parent / "evidence" / "ex3b"))
    args = ap.parse_args()
    pkg = Path(args.pkg).resolve()
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    sys.path[:0] = [str(pkg), str(pkg / "fixtext_ui"), QENV]

    tmp = Path(tempfile.mkdtemp(prefix="ex3b_"))
    ws = tmp / "workspace"
    ws.mkdir()
    src_dir = tmp / "src"
    src_dir.mkdir()
    os.environ["FIXTEXT_SETTINGS_FILE"] = str(tmp / "settings.ini")

    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    import fixtext_settings
    app = QApplication.instance() or QApplication([])
    _qs = fixtext_settings.AppSettings()
    _qs.setValue("wizardSeen", "1")
    _qs.sync()

    import main_window as mw
    import fixtext_shelf as S
    from fixtext_import.importer import import_book, ImportOptions

    A_TITLE, B_TITLE = "北岭旧事", "南川杂记"
    A_ERRS, B_ERRS = 10, 20

    # ---------------------------------------------------- S1 真实导入两本书
    a_src, b_src = _make_books(src_dir)
    import_book(a_src, ws, ImportOptions())
    import_book(b_src, ws, ImportOptions())
    books = {b.title: b for b in S.list_books(ws)}
    record("S1a", "真实导入两本书", set(books) == {A_TITLE, B_TITLE},
           f"titles={sorted(books)}")
    a_id, b_id = books[A_TITLE].book_id, books[B_TITLE].book_id

    win = mw.MainWindow(workspace=ws)
    win.resize(1280, 860)
    win.show()

    def _run_correction_for(title: str) -> dict:
        """真实点击一键校正主按钮，阻塞到模态进度条自然关闭。"""
        win.go("oneclick")
        app.processEvents()
        assert win.oneclick_module.run_context is not None, \
            f"《{title}》的运行上下文没就绪"
        QTest.mouseClick(win.oneclick_module.run_btn, Qt.MouseButton.LeftButton)
        return dict(outcome=win.oneclick_module._outcome,
                    summary=win.oneclick_module._summary)

    # -------------------------------------------- S2 甲书跑一次真实校正
    win._on_book_ready(str(books[A_TITLE].text_path))
    app.processEvents()
    t0 = time.monotonic()
    r = _run_correction_for(A_TITLE)
    dur = round(time.monotonic() - t0, 1)
    record("S2a", f"《{A_TITLE}》真实六阶段校正完成", r["outcome"] == "ok",
           f"outcome={r['outcome']} 用时{dur}s hits={r['summary'].get('hits')}")
    run_a = Path(str(r["summary"].get("workdir") or ""))
    record("S2b", "运行目录落在该书专属目录 runs/<书 id>/ 下",
           run_a.parent == pkg / "runs" / a_id, f"{run_a}")
    record("S2c", "校正后各页立即是甲书数据（无需切换）",
           _page_state(win)["check_book"] == A_TITLE
           and _page_state(win)["hist_titles"] == [A_TITLE]
           and _page_state(win)["export_title"] == A_TITLE)

    # -------------------------------------------- S3 切到乙书并跑一次校正
    win.go("import")
    app.processEvents()
    panel = win.import_module.shelf
    row_b = next(rw for rw in panel.rows if rw.book.book_id == b_id)
    row_b.action_btn.click()
    app.processEvents()
    record("S3a", "书架切换到乙书（真实点击）",
           S.stored_current_id() == b_id and win.book_chip.name.full_text() == B_TITLE,
           f"stored={S.stored_current_id()} chip={win.book_chip.name.full_text()!r}")
    st = _page_state(win)
    record("S3b", "切换后乙书还没记录：检查页空、历史页空、导出页挂乙书原文",
           st["check_book"] == "" and st["hist_titles"] == []
           and st["export_title"] == B_TITLE and not st["export_corrected"],
           f"check={st['check_book']!r} hist={st['hist_titles']} "
           f"exp={st['export_title']!r}")
    r_b = _run_correction_for(B_TITLE)
    record("S3c", f"《{B_TITLE}》真实六阶段校正完成", r_b["outcome"] == "ok",
           f"outcome={r_b['outcome']} hits={r_b['summary'].get('hits')}")
    run_b = Path(str(r_b["summary"].get("workdir") or ""))
    record("S3d", "乙书运行目录落在 runs/<乙书 id>/ 下（与甲书隔离）",
           run_b.parent == pkg / "runs" / b_id and run_a != run_b,
           f"{run_b}")

    # -------------------------------------------- S4 当前=乙书：逐页断言+截图
    shots_b: list[str] = []
    _assert_book_pages(win, "S4", B_TITLE, b_id, B_ERRS, app, out, shots_b)
    # 甲书的运行目录还在磁盘上，但乙书的历史里不许出现
    record("S4f", "甲书的运行记录没有混进乙书的历史页",
           all(t.get("run_dir") != str(run_a) for t in win.history_module.tasks),
           f"runs={[t.get('run_dir') for t in win.history_module.tasks]}")

    # -------------------------------------------- S5 切回甲书：逐页断言+截图
    win.go("import")
    app.processEvents()
    panel = win.import_module.shelf
    row_a = next(rw for rw in panel.rows if rw.book.book_id == a_id)
    row_a.action_btn.click()
    app.processEvents()
    record("S5a", "切回甲书（真实点击）",
           S.stored_current_id() == a_id and win.book_chip.name.full_text() == A_TITLE)
    shots_a: list[str] = []
    _assert_book_pages(win, "S5", A_TITLE, a_id, A_ERRS, app, out, shots_a)
    record("S5f", "乙书的记录没有混进甲书的历史页",
           all(t.get("run_dir") != str(run_b) for t in win.history_module.tasks))

    # -------------------------------------------- S6 连续来回切换
    ok_all, seq = True, []
    for i in range(6):
        target_id, title = (b_id, B_TITLE) if i % 2 == 0 else (a_id, A_TITLE)
        win.go("import")
        app.processEvents()
        row = next(rw for rw in win.import_module.shelf.rows
                   if rw.book.book_id == target_id)
        row.action_btn.click()
        app.processEvents()
        st = _page_state(win)
        expect_found = B_ERRS if title == B_TITLE else A_ERRS
        good = (win.book_chip.name.full_text() == title
                and st["check_book"] == title and st["check_found"] == expect_found
                and set(st["hist_titles"]) == {title}
                and st["export_title"] == title
                and st["oneclick_runs_root"].endswith(f"/{target_id}"))
        ok_all = ok_all and good
        seq.append(f"{title}:{'ok' if good else 'BAD'}")
    record("S6a", "A/B 连续切换 6 次：每次四页数据都正确、无崩溃",
           ok_all, " → ".join(seq))

    # -------------------------------------------- S7 已导出写点（当前=甲书）
    win.go("export")
    app.processEvents()
    exp_mod = win.export_module
    QTest.mouseClick(exp_mod.export_btn, Qt.MouseButton.LeftButton)
    done = _wait_export(exp_mod, app)
    record("S7a", "真实点击导出：甲书导出成功",
           done and exp_mod.outcome is not None and exp_mod.outcome.ok,
           f"done={done} ok={bool(exp_mod.outcome and exp_mod.outcome.ok)}")
    rec_a = S.read_export_record(books[A_TITLE].dir)
    record("S7b", "甲书目录出现真实导出记录（exports.json）",
           bool(rec_a and rec_a.get("exported_at")),
           f"keys={sorted(rec_a) if rec_a else None}")
    record("S7c", "导出记录带成品路径与校验值",
           bool(rec_a and rec_a.get("path") and rec_a.get("exported_sha256")),
           f"path={Path(str(rec_a.get('path'))).name if rec_a else ''}")
    record("S7d", "书架甲书行亮「已导出」、乙书不亮",
           (next(rw for rw in win.import_module.shelf.rows
                 if rw.book.book_id == a_id).status.text() == "已导出")
           and (next(rw for rw in win.import_module.shelf.rows
                     if rw.book.book_id == b_id).status.text() == ""),
           "甲=已导出 乙=空")
    record("S7e", "乙书目录没有导出记录（不串书）",
           S.read_export_record(books[B_TITLE].dir) is None)
    summary_a = json.loads((run_a / "report" / "ui_run_summary.json")
                           .read_text(encoding="utf-8"))
    record("S7f", "甲书那次运行的摘要写上了导出状态",
           bool(summary_a.get("exported_at") and summary_a.get("exported_sha256")),
           f"exported_at={summary_a.get('exported_at')}")
    win.go("import")
    app.processEvents()
    p = _shot(win, app, out, "S7_shelf_exported.png")
    record("S7g", "书架「已导出」截图落盘",
           p.exists() and p.stat().st_size > 8000, p.name)

    # -------------------------------------------- S8 重启（独立子进程）
    # 先把当前书切到乙书再重启：验证按书数据跨进程仍然正确
    win.go("import")
    app.processEvents()
    next(rw for rw in win.import_module.shelf.rows
         if rw.book.book_id == b_id).action_btn.click()
    app.processEvents()
    win.deleteLater()
    app.processEvents()
    probe = _child_probe(pkg, ws)
    record("S8a", "重启后当前书仍是乙书",
           probe.get("chip") == B_TITLE, f"chip={probe.get('chip')!r}")
    record("S8b", "重启后检查页只有乙书的问题",
           probe.get("check_book") == B_TITLE and probe.get("check_found") == B_ERRS,
           f"book={probe.get('check_book')!r} found={probe.get('check_found')}")
    record("S8c", "重启后历史页只有乙书",
           set(probe.get("hist_titles") or []) == {B_TITLE},
           f"titles={probe.get('hist_titles')}")
    record("S8d", "重启后导出页挂乙书",
           probe.get("export_title") == B_TITLE, f"{probe.get('export_title')!r}")
    record("S8e", "重启后历史运行目录指向乙书专属目录",
           str(probe.get("runs_root", "")).endswith(f"/{b_id}"),
           f"runs_root={probe.get('runs_root')!r}")

    # ---------------------------------------------------------------- 汇总
    (out / "accept_ex3b.log").write_text(
        "\n".join(f"{k}\t{'PASS' if ok else 'FAIL'}\t{label}\t{detail}"
                  for k, label, ok, detail in CHECKS), encoding="utf-8")
    failed = [c for c in CHECKS if not c[2]]
    print(f"\n共 {len(CHECKS)} 项，失败 {len(failed)} 项")
    if failed:
        for k, label, _, _ in failed:
            print(f"  FAIL: {k} {label}")
    # 清理本脚本在包根 runs/ 下留下的两本书目录（不动别的）
    for book_id in (a_id, b_id):
        shutil.rmtree(pkg / "runs" / book_id, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
