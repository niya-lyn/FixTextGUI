"""V1.1-EX.1-R1 验收：导出目录统一（单层口径）。

全程真实链路，不用桩：
  S0 清场：导出根 / 运行目录 / 工作区重建，保证每次从空目录起跑
  S1 导出页：真实导入公版样本EPUB → 真实点击校正 → 导出页点「开始导出」
     → 产物平铺在包根 `导出/`（书名.txt / 书名替换统计.txt / 书名替换统计.csv）
  S2 历史页：对同一本书**真的重新导出两次** → `导出/历史记录/` 下出现两个
     `<书名>_<YYYYMMDD_HHMMSS>` 目录，每个目录里三件套各一份，先导出的还在
  S3 换一本书：真实导入 TXT 样本 → 校正 → 历史页重新导出
     → 目录名里的书名与 S2 不同
  S4 书名清洗：非法字符 / 首尾空格点号 / 空名兜底 逐条给出实际结果
  S5 零露出复扫：界面文本不含内部路径与技术词

运行：
    QT_QPA_PLATFORM=offscreen python3.12 tools/accept_ex1.py
产出：evidence/accept_ex1.json + evidence/ex1/*.png
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG / "fixtext_ui"))
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 设置文件指到本脚本自己的临时目录：否则包内 workspace/settings.ini 缺失时
# wizardSeen 默认 "0"，首启向导会以模态 exec() 弹出把自动化卡死。
_SETTINGS = PKG.parent / "ex1_work" / "settings.ini"
_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
os.environ["FIXTEXT_SETTINGS_FILE"] = str(_SETTINGS)

from PySide6.QtCore import Qt, QTimer                       # noqa: E402
from PySide6.QtTest import QTest                             # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel           # noqa: E402

import fixtext_paths as paths                                # noqa: E402
import fixtext_history as histdata                           # noqa: E402
import main_window as M                                      # noqa: E402
from _public_fixture import EPUB                             # noqa: E402

EVID = PKG / "evidence"
SHOTS = EVID / "ex1"
TXT_BOOK = PKG / "tests" / "samples" / "a_utf8_lf.txt"
EXPORT_ROOT = paths.default_export_dir()
HIST_ROOT = EXPORT_ROOT / paths.HISTORY_DIRNAME

STAMP_RE = re.compile(r"^\d{8}_\d{6}$")
#: 目录名里不许出现的文件系统非法字符
ILLEGAL = set('<>:"/\\|?*')

LEAK_PATTERNS = [
    r"/home/", r"fixtext_pipeline", r"\bruns/", r"run-\d",
    r"\bmerge\b", r"\blayout\b", r"\breplace\b", r"\bquote\b",
    r"\bbookmap\b", r"\brestore\b", r"state\.json", r"subprocess",
    r"\bstdout\b", r"\bstderr\b", r"exit code", r"\.report\.json",
]


def collect_texts(widget) -> list[str]:
    texts = []
    for w in [widget] + widget.findChildren(object):
        for attr in ("text", "toolTip", "accessibleName", "windowTitle"):
            try:
                v = getattr(w, attr, None)
                v = v() if callable(v) else v
            except Exception:                                # noqa: BLE001
                v = None
            if isinstance(v, str) and v.strip():
                texts.append(v.strip())
    return texts


def screen_leaks(texts) -> list[dict]:
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


def mark_wizard_seen(workspace: Path) -> None:
    """先把「向导已看过」写进本次专用的设置文件（防止模态向导卡死自动化）。"""
    workspace.mkdir(parents=True, exist_ok=True)
    _SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS.write_text("[General]\nwizardSeen=1\n", encoding="utf-8")


def open_window(workspace: Path):
    win = M.MainWindow(str(workspace))
    win.resize(1280, 820)
    win.show()
    QApplication.processEvents()
    return win


def import_book(win, path: Path) -> dict:
    imp = win.import_module
    t0 = time.monotonic()
    imp._take_file(str(path))
    if not wait_until(lambda: imp.has_finished() or bool(imp.error_text()), 300):
        raise RuntimeError("导入超时")
    if imp.error_text() or imp._result is None:
        raise RuntimeError(imp.error_text() or "导入无结果")
    res = imp._result
    return dict(seconds=round(time.monotonic() - t0, 2),
                title=getattr(res, "title", "") or "",
                chapters=getattr(res, "chapters", None),
                text_chars=getattr(res, "text_chars", None))


def click_correction(win) -> dict:
    """真实点击「开始校正」（模态进度框内部自行轮询，不会被挡住）。"""
    mod = win.oneclick_module
    t0 = time.monotonic()
    QTest.mouseClick(mod.run_btn, Qt.MouseButton.LeftButton)
    total = round(time.monotonic() - t0, 2)
    QApplication.processEvents()
    summary = mod._summary or {}
    return dict(outcome=str(mod._outcome), seconds=total, summary=summary,
                run_dir=str(summary.get("workdir") or ""))


def export_from_page(win) -> dict:
    mod = win.export_module
    t0 = time.monotonic()
    QTest.mouseClick(mod.export_btn, Qt.MouseButton.LeftButton)
    ok = wait_until(lambda: not mod.is_busy() and mod.outcome is not None, 180)
    out = mod.outcome
    return dict(ok=bool(ok and out and out.ok), seconds=round(time.monotonic() - t0, 2),
                out_dir=str(getattr(out, "out_dir", "") or ""),
                main_file=str(getattr(out, "main_file", "") or ""),
                files=[str(p) for p in (getattr(out, "files", None) or [])],
                toast=mod.toast_label.text())


def export_from_history(win, run_dir: str) -> dict:
    """走历史页的真执行路径（_run_export → 后台线程 → exportFinished）。"""
    hist = win.page("history")
    hist.refresh()
    QApplication.processEvents()
    idx = next((i for i, t in enumerate(hist.tasks)
                if str(t.get("run_dir")) == run_dir), None)
    if idx is None:
        raise RuntimeError(f"历史页里找不到这次运行：{run_dir}")
    got: dict = {}
    hist.exportFinished.connect(lambda payload: got.setdefault("payload", payload))
    t0 = time.monotonic()
    hist._run_export(hist.tasks[idx])
    if not wait_until(lambda: "payload" in got and not hist._exporting, 180):
        raise RuntimeError("历史页导出超时")
    payload = got["payload"]
    return dict(seconds=round(time.monotonic() - t0, 2),
                success=bool(payload[1]), said=str(payload[2]),
                book=str(hist.tasks[idx].get("book") or ""))


def history_dirs() -> list[Path]:
    if not HIST_ROOT.is_dir():
        return []
    return sorted(p for p in HIST_ROOT.iterdir() if p.is_dir())


def dir_chars_ok(p: Path) -> tuple[bool, list[str]]:
    bad = sorted({ch for ch in p.name if ch in ILLEGAL})
    return (not bad), bad


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    workdir = PKG.parent / "ex1_work"
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workspace = workdir / "workspace"
    mark_wizard_seen(workspace)

    # S0 清场：导出根、运行目录都从空开始，避免上一轮产物干扰判据
    for stale in (EXPORT_ROOT, PKG / "runs"):
        if stale.exists():
            shutil.rmtree(stale, ignore_errors=True)
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    (PKG / "runs").mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    M.load_qss(app)

    report: dict = {}
    ok = True

    win = open_window(workspace)

    # ---------------- S1 导出页 → 包根 导出/ 平铺 ----------------
    win.go("import")
    QApplication.processEvents()
    info1 = import_book(win, EPUB)
    print(f"[S1] 导入 EPUB 完成 {info1['seconds']}s：书名={info1['title']!r}，"
          f"{info1['chapters']} 章 / {info1['text_chars']} 字")
    win.go("oneclick")
    QApplication.processEvents()
    cor1 = click_correction(win)
    print(f"[S1] 校正 {cor1['outcome']} {cor1['seconds']}s，命中 {cor1['summary'].get('hits')}")
    win.go("export")
    QApplication.processEvents()
    exp1 = export_from_page(win)
    out_dir = Path(exp1["out_dir"])
    flat_ok = (exp1["ok"] and out_dir == EXPORT_ROOT
               and all(Path(p).parent == EXPORT_ROOT for p in exp1["files"])
               and len(exp1["files"]) >= 3)
    print(f"[S1] 导出页导出到 {out_dir}（=包根导出={out_dir == EXPORT_ROOT}）："
          f"{[Path(p).name for p in exp1['files']]}")
    win.grab().save(str(SHOTS / "s1_export_page.png"))
    report["s1_export_page"] = dict(import_=info1, correction=dict(
        outcome=cor1["outcome"], seconds=cor1["seconds"],
        hits=cor1["summary"].get("hits")), export=exp1,
        out_dir_equals_pkg_export=out_dir == EXPORT_ROOT,
        files_flat=flat_ok, target_dir=str(out_dir))
    ok = ok and flat_ok

    title1 = info1["title"] or Path(exp1["main_file"]).stem
    report["s1_export_page"]["book_title"] = title1

    # ---------------- S2 历史页同一本书导出两次 ----------------
    win.go("history")
    QApplication.processEvents()
    hist = win.page("history")
    hist.refresh()
    QApplication.processEvents()
    before = {p.name for p in history_dirs()}
    h1 = export_from_history(win, cor1["run_dir"])
    after1 = {p.name for p in history_dirs()}
    h2 = export_from_history(win, cor1["run_dir"])
    after2 = {p.name for p in history_dirs()}
    new2 = sorted(after2 - before)
    print(f"[S2] 历史页两次导出：新增目录 {new2}")
    win.grab().save(str(SHOTS / "s2_history.png"))

    two_ok = (h1["success"] and h2["success"] and len(new2) == 2)
    contents: list[dict] = []
    for name in new2:
        d = HIST_ROOT / name
        files = sorted(p.name for p in d.iterdir() if p.is_file())
        m = re.fullmatch(rf"(.+)_{paths.HISTORY_STAMP_FORMAT.replace('%Y','(\\d{4})')}"
                         rf"", name)
        contents.append(dict(dir_name=name, parent=str(d.parent),
                             parent_is_history=d.parent == HIST_ROOT,
                             depth=len(d.relative_to(EXPORT_ROOT).parts),
                             book_part=name.rsplit("_", 2)[0],
                             stamp_part="_".join(name.rsplit("_", 2)[1:]),
                             stamp_ok=bool(STAMP_RE.match("_".join(name.rsplit("_", 2)[1:]))),
                             illegal_chars=sorted({c for c in name if c in ILLEGAL}),
                             files=files, file_count=len(files)))
    for c in contents:
        print(f"[S2]   {c['dir_name']}：三件套={c['file_count']} 个 {c['files']}；"
              f"父目录=历史记录({c['parent_is_history']})，层数={c['depth']}，"
              f"时间戳合规={c['stamp_ok']}，非法字符={c['illegal_chars']}")
    naming_ok = (len(contents) == 2
                 and all(c["parent_is_history"] and c["depth"] == 2
                         and c["stamp_ok"] and not c["illegal_chars"]
                         and c["file_count"] >= 3 for c in contents)
                 and all(c["book_part"] == paths.safe_dir_name(title1) for c in contents))
    # 先导出那次的文件必须还在（永不覆盖）
    first_kept = all(c["file_count"] >= 3 for c in contents)
    ok = ok and two_ok and naming_ok and first_kept
    report["s2_history_twice"] = dict(first=h1, second=h2, new_dirs=new2,
                                      contents=contents,
                                      naming_rule_ok=naming_ok,
                                      both_dirs_kept_files=first_kept,
                                      book_part_expected=paths.safe_dir_name(title1))

    # ---------------- S3 换一本书 → 书名不同 ----------------
    win.go("import")
    QApplication.processEvents()
    info2 = import_book(win, TXT_BOOK)
    win.go("oneclick")
    QApplication.processEvents()
    cor2 = click_correction(win)
    win.go("history")
    QApplication.processEvents()
    hist.refresh()
    QApplication.processEvents()
    h3 = export_from_history(win, cor2["run_dir"])
    dirs_now = [p.name for p in history_dirs()]
    new3 = [n for n in dirs_now if n not in after2]
    print(f"[S3] 换书（{info2['title']!r}）后新增目录 {new3}")
    win.grab().save(str(SHOTS / "s3_second_book.png"))
    other_ok = bool(new3) and all(
        n.rsplit("_", 2)[0] != paths.safe_dir_name(title1) for n in new3)
    report["s3_other_book"] = dict(import_=info2, correction=dict(
        outcome=cor2["outcome"], seconds=cor2["seconds"],
        hits=cor2["summary"].get("hits")), export=h3, new_dirs=new3,
        book_part=[n.rsplit("_", 2)[0] for n in new3],
        differs_from_first_book=other_ok)
    ok = ok and bool(h3["success"]) and other_ok

    # ---------------- S4 书名清洗用例（真函数、真结果） ----------------
    cases = [
        ("炮火弧线", "炮火弧线", "正常书名"),
        ("《炮火弧线》", "炮火弧线", "书名号只是包装"),
        ('a/b\\c:d*e?f"g<h>i|j', "abcdefghij", "九类非法字符全剔除"),
        ("  前后空格  ", "前后空格", "首尾空格"),
        ("...书名...", "书名", "首尾点号"),
        ("..  ..", "未命名", "只剩点号空白 → 兜底"),
        ("", "未命名", "空串 → 兜底"),
        ("???", "未命名", "全非法字符 → 兜底"),
        ("a\nb\tc", "abc", "控制字符剔除"),
        ("a.b.c", "a.b.c", "中间的点合法保留"),
    ]
    got = [dict(raw=raw, expected=exp, actual=paths.safe_dir_name(raw),
                why=why, pass_=paths.safe_dir_name(raw) == exp)
           for raw, exp, why in cases]
    all_clean = all(g["pass_"] for g in got)
    print("[S4] 书名清洗：" + "；".join(f"{g['raw']!r}→{g['actual']}" for g in got[:6]))
    report["s4_name_cleaning"] = dict(cases=got, all_pass=all_clean,
                                      real_dir_example=str(
                                          paths.history_export_dir(
                                              'a/b:c*?', when="20261104_173025",
                                              export_root=EXPORT_ROOT)))
    ok = ok and all_clean

    # ---------------- S5 零露出复扫 ----------------
    texts: list[str] = []
    for key in ("home", "import", "oneclick", "check", "vocab", "export", "history"):
        win.go(key)
        QApplication.processEvents()
        texts.extend(collect_texts(win.page(key)))
    leaks = screen_leaks(texts)
    print(f"[S5] 界面文本 {len(texts)} 条，技术词 / 内部路径命中 {len(leaks)}")
    if leaks[:3]:
        print("     ", leaks[:3])
    report["s5_no_leak"] = dict(texts=len(texts), hits=len(leaks), samples=leaks[:5])
    ok = ok and not leaks

    # ---------------- 收尾：路径盘点 ----------------
    tree = []
    for p in sorted(EXPORT_ROOT.rglob("*")):
        rel = p.relative_to(EXPORT_ROOT)
        tree.append(dict(path=str(rel), is_dir=p.is_dir(),
                         depth=len(rel.parts)))
    print(f"[收尾] 导出根 {EXPORT_ROOT} 下共 {len(tree)} 项")
    for t in tree[:40]:
        print("      ", ("[D]" if t["is_dir"] else "   "), t["path"])
    report["final_tree"] = dict(root=str(EXPORT_ROOT), entries=tree)

    win.close()
    QApplication.processEvents()

    report["ok"] = ok
    report["export_root"] = str(EXPORT_ROOT)
    report["history_root"] = str(HIST_ROOT)
    (EVID / "accept_ex1.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n结论：", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
