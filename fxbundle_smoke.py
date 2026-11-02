#!/usr/bin/env python3
"""打包冒烟（M4-T4.1b）：在**冻结后的程序内部**跑通「导入 → 一键校正 → 导出」。

只在试打包包里存在（构建脚本以字节码形式放入，正式绿色包不含）。用法：

    QT_QPA_PLATFORM=offscreen ./FixTextGUI --smoke

断言的是一条完整用户路径，不是某个函数：

1. `opens_on_first_run()` 必须为 True（**打包正确性的关键断言**：包内若夹带
   `workspace/settings.ini` 且带 `wizardSeen=1`，新用户永远看不到向导）；
2. 导入一本 EPUB（优先环境变量 FIXTEXT_SMOKE_EPUB；否则源码树里那份
   公版样本 tests/samples/book_public_domain.epub）：章数与正文字数都是真数；
3. 一键校正：六阶段真跑，得到「已还原」的电子书；
4. 导出：EPUB 落盘、命中数 > 0、字节数 > 0。

产品包不附带「示例书」目录；冻结包冒烟请自行设置 FIXTEXT_SMOKE_EPUB。

为避免把运行时状态写进包（那会让下一份包带着残留），本模块把用户区设置文件
指向临时目录；包目录本身只被读。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path


def _pkg_root() -> Path:
    try:
        from fixtext_paths import pkg_root  # noqa: PLC0415

        return Path(pkg_root())
    except Exception:                                   # noqa: BLE001
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)
    print(msg, flush=True)


def _wait_until(cond, timeout: float, step: float = 0.1) -> bool:
    """轮询等待（不让 Qt 事件循环停摆，否则后台线程的信号投递不到）。"""
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    end = time.time() + timeout
    app = QApplication.instance()
    while time.time() < end:
        if app is not None:
            app.processEvents()
        if cond():
            return True
        time.sleep(step)
    if app is not None:
        app.processEvents()
    return bool(cond())


def main() -> int:
    root = _pkg_root()
    result: dict = {"frozen": bool(getattr(sys, "frozen", False)),
                    "pkg_root": str(root), "steps": {}}
    ok = True

    # ---- 0. 先把用户区设置指到临时目录：绝不在包里留运行时状态 ----
    tmpdir = tempfile.mkdtemp(prefix="fixtext-smoke-")
    os.environ["FIXTEXT_SETTINGS_FILE"] = str(Path(tmpdir) / "settings.ini")

    # ---- 1. 首次启动会不会看到向导（在设置文件就位之前判定）----
    try:
        from first_run_wizard import opens_on_first_run  # noqa: PLC0415

        # 判定用的仍是包内真实状态：临时设置文件尚未写入任何值
        opens = bool(opens_on_first_run())
    except Exception as exc:                            # noqa: BLE001
        opens = None
        result["steps"]["wizard"] = {"ok": False,
                                     "error": f"{type(exc).__name__}: {exc}"}
    carried = (root / "workspace" / "settings.ini").is_file()
    if "wizard" not in result["steps"]:
        result["steps"]["wizard"] = {
            "opens_on_first_run": opens,
            "settings_carried": carried,
            "ok": opens is True and not carried,
        }
        ok = ok and opens is True and not carried
    else:
        ok = False
    _log(f"[smoke] 首次启动会弹向导 = {opens} · 包内夹带 settings.ini = {carried}")

    # 之后把向导标记置为已看过：否则首启向导的模态 exec() 会卡住无头自动化
    try:
        from fixtext_settings import AppSettings  # noqa: PLC0415

        s = AppSettings()
        s.setValue("wizardSeen", "1")
        s.sync()
    except Exception as exc:                            # noqa: BLE001
        _log(f"[smoke] 写向导标记失败（不影响后续）：{type(exc).__name__}: {exc}")

    from PySide6.QtWidgets import QApplication     # noqa: PLC0415
    from PySide6.QtTest import QTest                # noqa: PLC0415
    from PySide6.QtCore import Qt, QTimer           # noqa: PLC0415

    app = QApplication.instance() or QApplication(sys.argv[:1])

    from main_window import MainWindow, load_qss    # noqa: PLC0415

    load_qss(app)
    win = MainWindow(root / "workspace")
    win.show()
    app.processEvents()

    # ---- 2. 导入一本 EPUB（产品不附带示例书）----
    env_epub = os.environ.get("FIXTEXT_SMOKE_EPUB", "").strip()
    candidates = []
    if env_epub:
        candidates.append(Path(env_epub))
    # 源码 / 未冻结：用包内公版测试样本；冻结绿包需靠环境变量
    candidates.append(root / "tests" / "samples" / "book_public_domain.epub")
    # 兼容旧布局（若有人仍自备 示例书/）
    candidates.extend(sorted((root / "示例书").glob("*.epub"))
                      if (root / "示例书").is_dir() else [])
    epub = next((p for p in candidates if p.is_file()), None)
    if epub is None:
        result["steps"]["import"] = {
            "ok": False,
            "error": "缺少冒烟用 EPUB：请设置 FIXTEXT_SMOKE_EPUB=路径，"
                     "或在源码树保留公版样本 "
                     "tests/samples/book_public_domain.epub"
                     "（可用 tools/build_fixture_epub.py 现场合成）",
        }
        result["passed"] = False
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    imp = win.import_module
    t0 = time.time()
    # M5-EX.3：选文件即开跑，无向导 / 章节预览步骤
    imp._take_file(str(epub))
    app.processEvents()
    imported = _wait_until(lambda: imp._thread is None and imp._result is not None, 300)
    if not imported:
        _log(f"[smoke] 导入未完成（step={imp._step} · 失败提示={imp._fail_text!r}）")
    app.processEvents()
    res = imp._result
    n_chars = 0
    n_chapters = 0
    if res is not None:
        n_chapters = int(getattr(res, "chapters", 0) or 0)
        n_chars = int(getattr(res, "text_chars", 0) or 0)
    result["steps"]["import"] = {
        "ok": bool(imported and res is not None and n_chapters > 0 and n_chars > 0),
        "chapters": n_chapters,
        "chars": n_chars,
        "seconds": round(time.time() - t0, 2),
        "epub": epub.name,
    }
    ok = ok and result["steps"]["import"]["ok"]
    _log(f"[smoke] 导入：{n_chapters} 章 / {n_chars} 字 / "
         f"{result['steps']['import']['seconds']}s")

    # ---- 3. 一键校正（六阶段真跑）----
    mod = win.oneclick_module
    mod.run_btn.setEnabled(True)
    t0 = time.time()
    # 用户路径：真实点击按钮（不是调内部函数）
    QTimer.singleShot(0, lambda: QTest.mouseClick(mod.run_btn, Qt.MouseButton.LeftButton))
    done = _wait_until(lambda: mod._outcome is not None and not mod._running, 420, 0.2)
    app.processEvents()
    summary = mod._summary
    outcome = mod._outcome
    workdir = ""
    if isinstance(summary, dict):
        workdir = str(summary.get("workdir") or "")
    restored = []
    if workdir:
        restored = sorted((Path(workdir) / "06_restore").glob("*_restored.epub"))
    stages = {}
    total_s = None
    if isinstance(summary, dict):
        total_s = summary.get("total_elapsed_s")
        for k, v in (summary.get("stage_elapsed") or {}).items():
            stages[k] = round(float(v), 2)
    result["steps"]["correct"] = {
        "ok": bool(done and outcome == "ok" and restored),
        "outcome": outcome,
        "seconds": round(time.time() - t0, 2),
        "stage_elapsed": stages,
        "total_elapsed_s": total_s,
        "restored": restored[0].name if restored else "",
        "restored_bytes": restored[0].stat().st_size if restored else 0,
    }
    ok = ok and result["steps"]["correct"]["ok"]
    _log(f"[smoke] 校正：outcome={outcome} · "
         f"{result['steps']['correct']['seconds']}s · 阶段 {stages}")

    # ---- 4. 导出 ----
    exp = win.export_module
    out_dir = Path(tmpdir) / "导出"
    exp.set_out_dir(str(out_dir))
    app.processEvents()
    exp.export_now()
    # 等**导出真正结束**：先写主文件、再写统计 txt/csv，按「目录里有东西」判会
    # 撞上导出前的权限探针 .fixtext-write-probe-<pid>，按「有主文件」判会少统计。
    _wait_until(lambda: (getattr(exp, "outcome", None) is not None
                         and not getattr(exp, "_running", False)), 180, 0.2)
    app.processEvents()
    files = sorted(p.name for p in out_dir.iterdir()
                   if not p.name.startswith(".")) if out_dir.is_dir() else []
    main_file = next((n for n in files
                      if n.lower().endswith((".epub", ".txt"))), "")
    hits = 0
    for n in files:
        if n.endswith("替换统计.csv"):
            try:
                hits = sum(1 for _ in (out_dir / n).open(encoding="utf-8")) - 1
            except Exception:                            # noqa: BLE001
                hits = 0
    result["steps"]["export"] = {
        "ok": bool(main_file) and bool(files),
        "files": files[:6],
        "main_file": main_file,
        "main_bytes": (out_dir / main_file).stat().st_size if main_file else 0,
        "stats_rows": max(0, hits),
        "hits": int(getattr(getattr(exp, "outcome", None), "hits", 0) or 0),
    }
    ok = ok and result["steps"]["export"]["ok"]
    _log(f"[smoke] 导出：{main_file} · {result['steps']['export']['main_bytes']} 字节 · "
         f"统计行 {result['steps']['export']['stats_rows']}")

    result["passed"] = bool(ok)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
