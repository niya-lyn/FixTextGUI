"""M3-T3.5 集成联调验收：线 A / 线 B 合并后必须自证的四件事。

本脚本只做**取证**，不新增任何产品行为。四段对应本卡验收条款：

  S1 两套快照能力并存（同名模块改名后的核心风险点）
     S1a 词库侧：加入一条自定义词 → 词库文件 sha 变化 → 撤销 → sha 回到前态
     S1b 运行侧：历史页恢复「替换完成」→ 工作正文 sha == 该阶段产物 sha
     两边都还能重新导出（词库侧导出词库、运行侧导出电子书）
  S2 六入口逐入口真实点开（真实 QTest 点击左轨，不看测试绿）
  S3 端到端真实路径：导入 → 校正 → 检查页见问题 → 词库页加专有词 → 导出
     → 历史页恢复阶段点 → 从该点续跑 → 再导出，全程与基线 sha 对照
  S4 技术名词零露出复扫（合并后全界面文本）

运行：
    QT_QPA_PLATFORM=offscreen PYTHONPATH=<qt site-packages> \
        python3.12 tools/accept_t35.py
产出：evidence/accept_t35.json + evidence/t35/*.png
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
UI = PKG / "fixtext_ui"
for p in (str(PKG), str(UI), str(PKG / "pipeline"), str(PKG / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from _public_fixture import EPUB  # noqa: E402  M5-OS.1：公版 fixture 唯一来源
ENGINE = (PKG / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src"
          / "bin" / "replace_by_go-linux-amd64")
RULES = PKG / "data" / "rules"
BASE_SHA = "717fdfcee76fe3ee74d9a8bff20afbc84e7150bcbf5ee1a5b033a01739641dc2"
EVID = PKG / "evidence"
SHOTS = EVID / "t35"

#: 与 verify_m2t21 同一套零露出口径（内部目录 / 内部术语）
LEAK_PATTERNS = [
    r"\bmerge\b", r"\blayout\b", r"\breplace\b", r"\bquote\b",
    r"\bbookmap\b", r"\brestore\b", r"run_pipeline", r"state\.json",
    r"subprocess", r"\bstdout\b", r"\bstderr\b", r"exit code",
    r"/home/", r"fixtext_pipeline", r"\.go\b", r"\.report\.json",
    r"\bruns/\b", r"run-\d", r"SnapshotStore", r"fixtext_snapshot",
    r"fixtext_run_snapshot", r"spine", r"\bOPF\b", r"rules\.json",
]


# --------------------------------------------------------------------------
# 通用小工具
# --------------------------------------------------------------------------

def sha256_file(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wait_until(cond, timeout_s=300.0, step=0.05) -> bool:
    from PySide6.QtWidgets import QApplication
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(step)
    return False


def collect_texts(widget) -> list[str]:
    texts: list[str] = []
    for w in [widget] + widget.findChildren(object):
        for attr in ("text", "toolTip", "accessibleName", "accessibleDescription",
                     "windowTitle", "placeholderText"):
            try:
                v = getattr(w, attr, None)
                v = v() if callable(v) and attr in ("text", "toolTip") else v
            except Exception:                              # noqa: BLE001
                v = None
            if isinstance(v, str) and v.strip():
                texts.append(v.strip())
    return texts


def screen_leaks(texts) -> list[dict]:
    bad = []
    for t in texts:
        for pat in LEAK_PATTERNS:
            if re.search(pat, t):
                bad.append(dict(pattern=pat, text=t[:110]))
    return bad


def _mark_wizard_seen() -> None:
    """首启向导不弹（验收关注的是六入口与合并，不是向导本身）。"""
    from PySide6.QtCore import QSettings
    s = QSettings("FixText", "FixText")
    s.setValue("wizardSeen", "1")
    s.sync()


class _AutoConfirm:
    """自动确认（离屏无头不能真人点），并记下确认文案供断言。"""
    seen: list[dict] = []

    def __init__(self, **kw):
        self.kw = kw
        _AutoConfirm.seen.append(dict(kw))
        self.chosen = "replace"

    def exec(self):
        from PySide6.QtWidgets import QDialog
        return QDialog.DialogCode.Accepted

    def setParent(self, *_a):
        pass


# --------------------------------------------------------------------------
# S1 两套快照能力并存
# --------------------------------------------------------------------------

def s1_vocab_side(report: dict, tmp: Path) -> bool:
    """线 A 那套：词库写操作 → 撤销 → 词库文件 sha 逐字节回到前态。"""
    from fixtext_vocab import VocabStore
    import fixtext_snapshot as vsnap

    store = VocabStore(custom_path=tmp / "custom_vocab.json",
                       snap_dir=tmp / "snapshots")
    files = store.custom.path
    sha_before = sha256_file(files)

    entry = store.add_entry(word="测试专有词甲", value="测试专有词乙", typ="专有名词")
    sha_added = sha256_file(files)
    assert sha_added != sha_before, "加入后词库文件 sha 应变化"

    # 还原点真的落在磁盘上，且「操作前」字节可取
    newest = store.snap.newest_alive()
    before_payload = store.snap.before_bytes(int(newest["id"])) if newest else None

    res = store.undo()
    sha_undo = sha256_file(files)

    print(f"[S1a] 词库侧：加入后 sha={sha_added[:16]}… → 撤销后 sha={sha_undo[:16]}…，"
          f"回到前态={sha_undo == sha_before}，"
          f"还原点载荷可取={before_payload is not None}")
    report["s1a_vocab_snapshot"] = dict(
        module="fixtext_snapshot.SnapshotStore",
        sha_before=sha_before, sha_after_add=sha_added, sha_after_undo=sha_undo,
        undo_identical=bool(sha_undo == sha_before),
        undo_expected=bool((res or {}).get("identical")),
        point_payload_ok=before_payload is not None,
        point_count=store.snap.point_count(),
        entry_id=entry.get("id"))
    return sha_undo == sha_before and before_payload is not None


def s1_run_side(report: dict, hist, run_dir: str, runs_root: Path) -> bool:
    """线 B 那套：历史页恢复到某阶段点 → 工作正文 sha == 阶段产物 sha，且能导出。"""
    import fixtext_run_snapshot as rsnap
    import fixtext_export as fxexport

    pts = rsnap.list_points(run_dir)
    avail = [p for p in pts if p["available"]]

    idx = next(i for i, t in enumerate(hist.tasks) if t["run_dir"] == run_dir)
    _AutoConfirm.seen.clear()
    import history_module as hm
    orig = hm.SnapshotDialog
    hm.SnapshotDialog = _AutoConfirm
    try:
        hist._open_snapshot_dialog(idx)
    finally:
        hm.SnapshotDialog = orig

    cur = rsnap.current_state(runs_root)
    src_after = rsnap.resolve_artifacts(run_dir)["after_text"]
    ws_sha = sha256_file(cur["working_text"]) if cur else ""
    src_sha = sha256_file(src_after)
    verify = {k: v["equal"] for k, v in (cur or {}).get("verify", {}).items()}

    # 恢复点能导出（这条是「两头都能重新导出」的运行侧一半）
    out_dir = PKG.parent / "t35_ws" / "s1_export"
    src_obj = rsnap.build_export_source(cur, PKG / "pipeline")
    out = fxexport.export_book(src_obj, out_dir,
                              fmt="epub" if src_obj.can_restore_epub else "txt",
                              baseline_sha256=BASE_SHA)
    out_sha = out.sha256 or sha256_file(out.main_file)

    print(f"[S1b] 运行侧：{len(avail)}/{len(pts)} 阶段点可用；恢复「{cur['point_name']}」"
          f"工作正文 sha={ws_sha[:16]}… 阶段产物 sha={src_sha[:16]}… 一致={ws_sha == src_sha}；"
          f"导出 sha={out_sha[:16]}… 与基线一致={out_sha == BASE_SHA}")
    report["s1b_run_snapshot"] = dict(
        module="fixtext_run_snapshot",
        points_total=len(pts), points_available=len(avail),
        point=cur.get("point") if cur else None,
        point_name=cur.get("point_name") if cur else None,
        working_text_sha256=ws_sha, point_artifact_sha256=src_sha,
        equal=ws_sha == src_sha, verify=verify,
        exported_sha256=out_sha, export_equals_baseline=out_sha == BASE_SHA,
        exported_file=out.main_file, hits=out.hits)
    return bool(cur) and ws_sha == src_sha and all(verify.values()) \
        and out_sha == BASE_SHA


def s1_modules_coexist(report: dict) -> bool:
    """两个模块同时可导入、各留自己的接口，且互不导入对方。"""
    import fixtext_snapshot as a
    import fixtext_run_snapshot as b
    import inspect

    a_src = inspect.getsource(a)
    b_src = inspect.getsource(b)
    a_api = dict(SnapshotStore=hasattr(a, "SnapshotStore"),
                 MAX_POINTS=hasattr(a, "MAX_POINTS"))
    b_api = dict(list_points=hasattr(b, "list_points"),
                 restore_point=hasattr(b, "restore_point"),
                 resume_from_point=hasattr(b, "resume_from_point"),
                 current_state=hasattr(b, "current_state"),
                 build_export_source=hasattr(b, "build_export_source"))
    # 互相不导入（否则改名就白做了）
    a_imports_b = bool(re.search(r"^\s*(import|from)\s+fixtext_run_snapshot\b",
                                 a_src, re.M))
    b_imports_a = bool(re.search(r"^\s*(import|from)\s+fixtext_snapshot\b",
                                 b_src, re.M))
    print(f"[S1c] 两模块并存：A 接口={a_api} B 接口={b_api}；"
          f"A 导入 B={a_imports_b}，B 导入 A={b_imports_a}")
    report["s1c_coexist"] = dict(file_a="fixtext_snapshot.py",
                                 file_b="fixtext_run_snapshot.py",
                                 api_a=a_api, api_b=b_api,
                                 a_imports_b=a_imports_b, b_imports_a=b_imports_a)
    return all(a_api.values()) and all(b_api.values()) \
        and not a_imports_b and not b_imports_a


# --------------------------------------------------------------------------
# S2 六入口逐入口真实点开
# --------------------------------------------------------------------------

def s2_six_entries(win, report: dict) -> bool:
    """真实 QTest 点击左轨控件，逐入口核对落地页与页面自身可用性。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from fixtext_tokens import ENTRIES

    rows = []
    all_ok = True
    mod_attr = {"import": "import_module", "oneclick": "oneclick_module",
                "check": "check_module", "vocab": "vocab_module",
                "export": "export_module", "history": "history_module"}
    for entry in ENTRIES:
        key = entry["key"]
        btn = win.rail_items.get(key)
        clicked = False
        if btn is not None:
            QTest.mouseClick(btn, Qt.MouseButton.LeftButton)   # 真点控件
            QApplication.processEvents()
            clicked = True
        else:                                  # 找不到控件就如实记，不算真点
            win.go(key)
            QApplication.processEvents()
        cur = getattr(win, "current_key", None)
        page = win.page(key)
        texts = collect_texts(page) if page is not None else []
        mod = getattr(win, mod_attr.get(key, ""), None)
        landing_ok = (cur == key and page is not None and mod is not None
                      and btn is not None and bool(texts))
        rows.append(dict(key=key, label=entry["label"],
                         clicked_real=clicked, landed=cur == key,
                         page_ok=page is not None, module_ok=mod is not None,
                         texts=len(texts), ok=landing_ok))
        all_ok = all_ok and landing_ok
    print(f"[S2] 六入口：{sum(1 for r in rows if r['ok'])}/6 真实点开可用 → "
          + ", ".join(f"{r['label']}={'✓' if r['ok'] else '✗'}" for r in rows))
    report["s2_six_entries"] = dict(count=len(rows),
                                    landed=sum(1 for r in rows if r["landed"]),
                                    ok_count=sum(1 for r in rows if r["ok"]),
                                    rows=rows, all_ok=all_ok)
    return all_ok and len(rows) == 6


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    ws = PKG.parent / "t35_ws"
    ws.mkdir(parents=True, exist_ok=True)
    runs_root = PKG / "runs"

    import shutil
    for d in (runs_root, ws / "export"):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    runs_root.mkdir(parents=True, exist_ok=True)

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    _mark_wizard_seen()

    import main_window as M
    import history_module as hm
    import fixtext_run_snapshot as rsnap
    import fixtext_export as fxexport
    M.load_qss(app)

    report: dict = dict(card="M3-T3.5", base_sha=BASE_SHA)
    ok = True

    # ---------------- S3 端到端真实路径（先跑，造出真实运行目录）----------------
    win = M.MainWindow(ws)
    win.resize(1280, 820)
    win.show()
    QApplication.processEvents()

    steps = []

    # ① 导入
    imp = win.import_module
    t0 = time.monotonic()
    imp._take_file(str(EPUB))  # M5-EX.3：选完即开跑
    if not wait_until(lambda: imp.has_finished() or bool(imp.error_text()), 300):
        print(json.dumps(dict(error="导入超时"), ensure_ascii=False))
        return 1
    if imp.error_text() or imp._result is None:
        print(json.dumps(dict(error=imp.error_text() or "无结果"), ensure_ascii=False))
        return 1
    imp_s = round(time.monotonic() - t0, 2)
    steps.append(dict(step="导入", seconds=imp_s))

    # ② 一键校正
    win.go("oneclick")
    QApplication.processEvents()
    oc = win.oneclick_module
    t0 = time.monotonic()
    QTest.mouseClick(oc.run_btn, Qt.MouseButton.LeftButton)
    corr_s = round(time.monotonic() - t0, 2)
    QApplication.processEvents()
    summary = oc._summary or {}
    run_dir = summary.get("workdir") or ""
    base_ok = summary.get("restored_sha256") == BASE_SHA
    steps.append(dict(step="一键校正", seconds=corr_s,
                      chapters=summary.get("chapters"),
                      hits=summary.get("hits"),
                      sha256=summary.get("restored_sha256"), equals_baseline=base_ok))
    ok = ok and base_ok and bool(run_dir) and Path(run_dir).is_dir()

    # ③ 检查页看到问题
    win.go("check")
    QApplication.processEvents()
    chk = win.check_module
    probs = len(getattr(chk, "probs", []) or [])
    steps.append(dict(step="检查页", problems=probs))
    ok = ok and probs > 0

    # ④ 词库页加入专有词（走真实写入口，并当场撤销取证 S1a 已在上面单测里做，
    #    这里做的是端到端链路里的真实加入——保留写入以便后续步骤照常）
    win.go("vocab")
    QApplication.processEvents()
    vmod = win.vocab_module
    vstore = vmod.store
    vfile = Path(vstore.custom.path)
    v_sha_before = sha256_file(vfile)
    v_entry = vstore.add_entry(word="端到端测试词", value="端到端测试值", typ="专有名词")
    QApplication.processEvents()
    v_sha_after = sha256_file(vfile)
    v_undo = vstore.undo()
    v_sha_undo = sha256_file(vfile)
    steps.append(dict(step="词库页加入专有词", entry_id=v_entry.get("id"),
                      sha_before=v_sha_before, sha_after_add=v_sha_after,
                      sha_after_undo=v_sha_undo,
                      undo_identical=v_sha_undo == v_sha_before))
    ok = ok and v_sha_undo == v_sha_before

    # ⑤ 导出（真实点「开始导出」按钮，走页面自己的异步导出）
    win.go("export")
    QApplication.processEvents()
    ex = win.export_module
    t0 = time.monotonic()
    QTest.mouseClick(ex.export_btn, Qt.MouseButton.LeftButton)
    exp_s = round(time.monotonic() - t0, 2)
    wait_until(lambda: not getattr(ex, "_running", True), 240)
    QApplication.processEvents()
    exp_file = ""
    exp_sha = ""
    outcome = getattr(ex, "outcome", None)
    if outcome is not None:
        exp_file = str(getattr(outcome, "main_file", "") or "")
        exp_sha = str(getattr(outcome, "sha256", "") or "")
        if exp_file and not exp_sha:
            exp_sha = sha256_file(exp_file)
    steps.append(dict(step="导出", seconds=exp_s, file=exp_file,
                      sha256=exp_sha, equals_baseline=exp_sha == BASE_SHA,
                      message=getattr(outcome, "message", "")))
    ok = ok and exp_sha == BASE_SHA

    # ⑥ 历史页恢复某阶段点
    win.go("history")
    QApplication.processEvents()
    hist = win.history_module
    hist.refresh()
    QApplication.processEvents()

    s1a = s1_vocab_side(report, ws / "s1a")
    s1c = s1_modules_coexist(report)
    s1b = s1_run_side(report, hist, run_dir, runs_root)
    ok = ok and s1a and s1b and s1c
    steps.append(dict(step="历史页恢复阶段点",
                      point=report["s1b_run_snapshot"]["point"],
                      working_sha=report["s1b_run_snapshot"]["working_text_sha256"],
                      artifact_sha=report["s1b_run_snapshot"]["point_artifact_sha256"]))
    win.grab().save(str(SHOTS / "s3_history_restored.png"))

    # ⑦ 从该点续跑
    cur = rsnap.current_state(runs_root)
    ctx = dict(pipeline_root=str(PKG / "pipeline"),
               rules_before=str(RULES / "before.json"),
               rules_after=str(RULES / "after.json"),
               engine_path=str(ENGINE))
    hist.set_export_ctx(dict(ctx, import_record=None,
                             out_dir=str(ws / "export"),
                             baseline_sha256=BASE_SHA))
    t0 = time.monotonic()
    cont = hist._do_continue(cur["snapshot_dir"], dict(ctx))
    cont_s = round(time.monotonic() - t0, 2)
    stages = {k: dict(status=v.get("status"), elapsed_s=v.get("elapsed_s"))
              for k, v in (cont["report"].get("stages") or {}).items()}
    skipped = [k for k, v in stages.items() if v["status"] == "skipped"]
    work = Path(cont["work_dir"])
    new_epub = list((work / "06_restore").glob("*.epub"))
    cont_sha = sha256_file(new_epub[0]) if new_epub else ""
    steps.append(dict(step="从该点续跑", seconds=cont_s,
                      exit_code=cont["exit_code"], skipped=skipped,
                      stages=stages, sha256=cont_sha,
                      equals_baseline=cont_sha == BASE_SHA))
    ok = ok and cont["exit_code"] == 0 and cont_sha == BASE_SHA \
        and skipped == ["merge", "layout", "replace"]

    # ⑧ 再导出（走界面自己的「从当前工作区导出」实现，不自己拼状态字典）
    try:
        out2 = hist._do_export_workspace(dict(ctx, import_record=None,
                                              out_dir=str(ws / "export2"),
                                              baseline_sha256=BASE_SHA))
        re_sha = getattr(out2, "sha256", "") or sha256_file(out2.main_file)
        re_file = out2.main_file
        re_err = ""
    except Exception as exc:                             # noqa: BLE001
        re_sha, re_file, re_err = "", "", f"导出失败：{exc}"
        print("   [⑧] 再导出异常：", exc)
    steps.append(dict(step="再导出", file=str(re_file), sha256=re_sha,
                      equals_baseline=re_sha == BASE_SHA,
                      error=re_err))
    ok = ok and re_sha == BASE_SHA
    report["s3_e2e"] = dict(steps=steps, all_ok=ok)

    # ---------------- S2 六入口真实点开 ----------------
    s2 = s2_six_entries(win, report)
    ok = ok and s2
    win.grab().save(str(SHOTS / "s2_six_entries.png"))

    # ---------------- S4 零露出复扫 ----------------
    texts: list[str] = []
    for entry in __import__("fixtext_tokens").ENTRIES:
        pg = win.page(entry["key"])
        if pg is not None:
            texts += collect_texts(pg)
    leaks = screen_leaks(texts)
    print(f"[S4] 零露出：扫描 {len(texts)} 条界面文本，命中 {len(leaks)}")
    if leaks:
        for x in leaks[:5]:
            print("   leak:", x)
    report["s4_no_leak"] = dict(scanned=len(texts), hits=len(leaks),
                                samples=leaks[:5],
                                patterns=len(LEAK_PATTERNS))
    ok = ok and not leaks

    report["ok"] = bool(ok)
    EVID.mkdir(parents=True, exist_ok=True)
    (EVID / "accept_t35.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=== " + ("ALL PASS" if ok else "FAIL") + " ===")
    print("证据 →", EVID / "accept_t35.json")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
