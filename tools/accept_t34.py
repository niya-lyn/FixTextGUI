"""M3-T3.4 验收：历史页「恢复到任一快照」全链路（自采实跑，不做桩）。

对应排期 §2.2 入口⑥ 验收②「任一快照可完整恢复现场并重新导出」。

场景：
  S1 阶段点枚举：真实运行目录下有几个阶段点就有几个，缺的置灰并给原因
  S2 恢复到「替换完成」→ 工作正文 sha 与 03_replace/after 产物一致（两个 sha 都记）
  S3 恢复后重导出：产出 EPUB 的 sha 与基线逐字节一致，命中数不变
  S4 从恢复点续跑：前三阶段 skipped（含耗时），只补做后面阶段，成品 sha 仍是基线
  S5 恢复可撤销：撤销后当前工作区回到恢复前（指针与工作正文都对得上）
  S6 重启后阶段点仍在：全新窗口只凭磁盘重新枚举
  S7 二次确认文案：写明影响范围 + 可撤销，不再出现「降级」
  S8 界面状态呈现：当前工作区提示 = 恢复到的时点；续跑 / 导出按钮可用
  S9 技术名词零露出复扫

运行：
    QT_QPA_PLATFORM=offscreen python3.12 tools/accept_t34.py
产出：evidence/accept_t34.json + evidence/t34/*.png
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


from PySide6.QtWidgets import (                          # noqa: E402
    QApplication, QDialog, QLabel, QPushButton, QRadioButton,
)

import main_window as M                                   # noqa: E402
import fixtext_run_snapshot as snap                           # noqa: E402
import fixtext_export as fxexport                         # noqa: E402
import history_module as hm                               # noqa: E402

from _public_fixture import EPUB  # noqa: E402  M5-OS.1：公版 fixture 唯一来源
ENGINE = (PKG / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src"
          / "bin" / "replace_by_go-linux-amd64")
RULES = PKG / "data" / "rules"
BASE_SHA = "717fdfcee76fe3ee74d9a8bff20afbc84e7150bcbf5ee1a5b033a01739641dc2"
EVID = PKG / "evidence"
SHOTS = EVID / "t34"

LEAK_PATTERNS = [
    r"\bmerge\b", r"\blayout\b", r"\breplace\b", r"\bquote\b",
    r"\bbookmap\b", r"\brestore\b", r"run_pipeline", r"state\.json",
    r"subprocess", r"\bstdout\b", r"\bstderr\b", r"exit code",
    r"/home/", r"fixtext_pipeline", r"\.go\b", r"\.report\.json",
    r"\bruns/\b", r"run-\d",
]


def collect_texts(widget) -> list[str]:
    texts = []
    for w in [widget] + widget.findChildren(object):
        for attr in ("text", "toolTip", "accessibleName", "windowDescription",
                     "windowTitle", "placeholderText"):
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


def wait_until(cond, timeout_s=300.0, step=0.05):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(step)
    return False


def open_window(workspace):
    win = M.MainWindow(workspace)
    win.resize(1280, 820)
    win.show()
    QApplication.processEvents()
    return win


class _AutoConfirm:
    """自动确认对话框（离屏无头不能真人点），同时记下确认文案供 S7 断言。"""

    seen: list[dict] = []

    def __init__(self, **kw):
        self.kw = kw
        _AutoConfirm.seen.append(dict(kw))
        self.chosen = "replace"

    def exec(self):
        return QDialog.DialogCode.Accepted

    def setParent(self, *_a):
        pass


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    ws = PKG.parent / "t34_ws"
    ws.mkdir(parents=True, exist_ok=True)
    runs_root = PKG / "runs"

    import shutil
    if runs_root.exists():
        shutil.rmtree(runs_root, ignore_errors=True)
    runs_root.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    _mark_wizard_seen()
    M.load_qss(app)

    report: dict = {"card": "M3-T3.4", "base_sha": BASE_SHA}
    ok = True

    # ---------------- S0 真跑一次校正（造出真实运行目录）----------------
    win = open_window(ws)
    imp = win.import_module
    t0 = time.monotonic()
    imp._take_file(str(EPUB))  # M5-EX.3：选完即开跑
    if not wait_until(lambda: imp.has_finished() or bool(imp.error_text()), 300):
        print(json.dumps(dict(error="导入超时"), ensure_ascii=False))
        return 1
    if imp.error_text() or imp._result is None:
        print(json.dumps(dict(error=imp.error_text() or "无结果"), ensure_ascii=False))
        return 1
    import_s = round(time.monotonic() - t0, 2)

    win.go("oneclick")
    QApplication.processEvents()
    mod = win.oneclick_module
    QTest_click = None
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    t0 = time.monotonic()
    QTest.mouseClick(mod.run_btn, Qt.MouseButton.LeftButton)
    corr_s = round(time.monotonic() - t0, 2)
    QApplication.processEvents()
    summary = mod._summary or {}
    run_dir = summary.get("workdir") or ""
    print(f"[S0] 导入 {import_s}s → 校正 {corr_s}s：{summary.get('chapters')} 章 / "
          f"{summary.get('hits')} 命中 / sha={str(summary.get('restored_sha256'))[:12]}")
    report["s0_run"] = dict(import_s=import_s, correction_s=corr_s,
                            chapters=summary.get("chapters"),
                            hits=summary.get("hits"),
                            restored_sha256=summary.get("restored_sha256"),
                            workdir=run_dir,
                            stage_elapsed=summary.get("stage_elapsed"))
    if not run_dir or not Path(run_dir).is_dir():
        print(json.dumps(dict(error="校正没有产出运行目录"), ensure_ascii=False))
        return 1
    ok = ok and summary.get("restored_sha256") == BASE_SHA

    # ---------------- S1 阶段点枚举 ----------------
    pts = snap.list_points(run_dir)
    avail = [p for p in pts if p["available"]]
    print(f"[S1] 阶段点：{len(avail)}/{len(pts)} 可用 → "
          f"{[(p['name'], p['available']) for p in pts]}")
    s1_ok = len(pts) == 5 and len(avail) == 5
    report["s1_points"] = dict(total=len(pts), available=len(avail),
                               points=[dict(key=p["key"], name=p["name"],
                                            available=p["available"],
                                            reason=p["reason"])
                                       for p in pts])
    ok = ok and s1_ok

    # ---------------- S2 恢复到「替换完成」 ----------------
    win.go("history")
    QApplication.processEvents()
    hist = win.page("history")
    hist.refresh()
    QApplication.processEvents()
    idx = next(i for i, t in enumerate(hist.tasks) if t["run_dir"] == run_dir)

    _AutoConfirm.seen.clear()
    orig_dlg = hm.SnapshotDialog
    hm.SnapshotDialog = _AutoConfirm
    try:
        hist._open_snapshot_dialog(idx)
    finally:
        hm.SnapshotDialog = orig_dlg

    cur = snap.current_state(runs_root)
    src_after = snap.resolve_artifacts(run_dir)["after_text"]
    ws_sha = snap.sha256_file(cur["working_text"]) if cur else ""
    src_sha = snap.sha256_file(src_after)
    verify = {k: v["equal"] for k, v in (cur or {}).get("verify", {}).items()}
    print(f"[S2] 恢复「替换完成」：工作正文 sha={ws_sha[:16]}…，"
          f"阶段产物 sha={src_sha[:16]}…，一致={ws_sha == src_sha}，"
          f"逐项比对 {sum(1 for v in verify.values() if v)}/{len(verify)} 相等")
    s2_ok = bool(cur) and cur.get("point") == "replace" and ws_sha == src_sha \
        and all(verify.values())
    report["s2_restore"] = dict(point=(cur or {}).get("point"),
                                point_name=(cur or {}).get("point_name"),
                                working_text=ws_sha,
                                point_artifact=src_sha,
                                equal=ws_sha == src_sha,
                                verify=verify,
                                snapshot_dir=(cur or {}).get("snapshot_dir"))
    ok = ok and s2_ok

    # ---------------- S3 恢复后重导出 ----------------
    out_dir = ws / "导出结果"
    src_obj = snap.build_export_source(cur, PKG / "pipeline")
    out = fxexport.export_book(src_obj, out_dir / "from_restore",
                               fmt="epub" if src_obj.can_restore_epub else "txt",
                               baseline_sha256=BASE_SHA)
    exported = Path(out.main_file)
    out_sha = out.sha256 or snap.sha256_file(exported)
    print(f"[S3] 从恢复点导出 {exported.name}：sha={out_sha[:16]}…，"
          f"与基线一致={out_sha == BASE_SHA}，命中 {out.hits}")
    s3_ok = out_sha == BASE_SHA and out.hits == summary.get("hits")
    report["s3_export"] = dict(file=str(exported), sha256=out_sha,
                               equals_baseline=out_sha == BASE_SHA,
                               hits=out.hits, fmt=out.fmt,
                               structure=(out.structure or {}).get("ok"))
    ok = ok and s3_ok
    win.grab().save(str(SHOTS / "s2_s3_restored_replace.png"))

    # ---------------- S4 从恢复点续跑 ----------------
    ctx = dict(pipeline_root=str(PKG / "pipeline"),
               rules_before=str(RULES / "before.json"),
               rules_after=str(RULES / "after.json"),
               engine_path=str(ENGINE))
    hist.set_export_ctx(dict(ctx, import_record=None, out_dir=str(out_dir),
                             baseline_sha256=BASE_SHA))
    # 走真实界面路径（_run_continue → 后台线程 → _poll_continue 收尾），
    # 不要直接调 _do_continue：后者只是干活，撤销记录是在 _poll_continue 里
    # 登记进撤销栈的，绕过它 S5 就没有可撤销的「继续」这一步。
    _capt: dict = {}
    _orig_do_continue = hist._do_continue

    def _do_and_capture(snap_dir, job_ctx):
        out = _orig_do_continue(snap_dir, job_ctx)
        _capt["out"] = out
        return out

    hist._do_continue = _do_and_capture
    t0 = time.monotonic()
    # 等待判据必须同时看「撤销栈确实多了一项」：_capt["out"] 在 wrapper 里
    # 一赋值就有了，而撤销记录是 _poll_continue 在 QTimer 回调里才 append 的，
    # 只看 _capt 会提前放行，导致栈里没有可撤销的「继续」这一步（实测踩过）。
    _depth0 = len(hist._undo_stack)
    try:
        hist._run_continue(cur, dict(ctx))
        wait_until(lambda: ("out" in _capt and not hist._resuming
                            and len(hist._undo_stack) > _depth0), 600)
    finally:
        hist._do_continue = _orig_do_continue
    cont_s = round(time.monotonic() - t0, 2)
    cont = _capt.get("out") or {}
    stages = {k: dict(status=v.get("status"), elapsed_s=v.get("elapsed_s"),
                      summary=v.get("summary"))
              for k, v in ((cont.get("report") or {}).get("stages") or {}).items()}
    work = Path(cont.get("work_dir") or "")
    new_epub = list((work / "06_restore").glob("*.epub")) if work.is_dir() else []
    cont_sha = snap.sha256_file(new_epub[0]) if new_epub else ""
    skipped = [k for k, v in stages.items() if v["status"] == "skipped"]
    print(f"[S4] 续跑 {cont_s}s（退出码 {cont.get('exit_code')}）：跳过 {skipped}；"
          f"其余 {[(k, v['elapsed_s']) for k, v in stages.items() if v['status'] == 'done']}；"
          f"成品 sha={cont_sha[:12]} 与基线一致={cont_sha == BASE_SHA}；"
          f"撤销栈 {len(hist._undo_stack)} 项")
    s4_ok = (cont.get("exit_code") == 0 and skipped == ["merge", "layout", "replace"]
             and cont_sha == BASE_SHA and len(hist._undo_stack) >= 1)
    report["s4_resume"] = dict(seconds=cont_s, exit_code=cont.get("exit_code"),
                               skipped=skipped, stages=stages,
                               restored_sha256=cont_sha,
                               equals_baseline=cont_sha == BASE_SHA,
                               undo_stack_depth=len(hist._undo_stack),
                               work_dir=str(work))
    ok = ok and s4_ok

    # ---------------- S5 恢复可撤销 ----------------
    # 判据 = 「回到被撤销那一步操作之前的现场」：
    #   · 指针里的 prev_snapshot 就是那步操作前的现场 → 撤销后必须落到这个目录上，
    #     且时点(meta.point)与之一致；
    #   · prev_snapshot 为空 = 那步操作前是「未指定」→ 撤销后也应回到「未指定」。
    # 原断言 `after is None and after == before` 两项互斥：只有 before 也是 None 时
    # 才可能成立；过去是靠 _adopt_workspace 漏写 snapshot_dir 让 current_state() 恒返回
    # None 才"凑巧通过"，修掉该产品缺陷后必然恒假，产品本身行为是对的。
    #
    # 本场景撤销栈里有两步可撤销操作（S2 的「恢复」+ S4 的「继续」），所以这里连撤两次：
    #   1) 撤销「继续」→ 回到 S4 续跑前 = 恢复点（replace）
    #   2) 撤销「恢复」→ 回到 S2 恢复前 = 未指定
    def _read_point_of(snap_dir: str):
        try:
            return str(json.loads((Path(snap_dir) / snap.META_FILE)
                                  .read_text(encoding="utf-8")).get("point") or "") or None
        except Exception:                                # noqa: BLE001
            return None

    def _undo_once(label: str) -> dict:
        pre = snap.current_state(runs_root)
        prev_dir = str((pre or {}).get("prev_snapshot") or "")
        before = None
        if prev_dir:
            before = dict(snapshot_dir=prev_dir, point=_read_point_of(prev_dir))
        hist._undo()
        QApplication.processEvents()
        after = snap.current_state(runs_root)
        after_dir = str((after or {}).get("snapshot_dir") or "")
        after_point = str((after or {}).get("point") or "") or None
        pre_dir = str((pre or {}).get("snapshot_dir") or "")
        if before is None:
            step_ok = after is None
            rule = "撤销前是「未指定」→ 撤销后应为「未指定」"
        else:
            step_ok = (after is not None and after_dir == before["snapshot_dir"]
                       and after_point == before["point"])
            rule = "撤销后指针 = 被撤销操作之前的现场（目录 + 时点一致）"
        # 撤销必须真的动了指针，否则"什么都没做"也能满足上面的相等
        moved = (pre_dir != after_dir)
        return dict(label=label, rule=rule,
                    pre_undo_point=str((pre or {}).get("point") or "") or None,
                    pre_undo_snapshot_dir=pre_dir,
                    before=before,
                    before_point=(before or {}).get("point"),
                    before_snapshot_dir=prev_dir,
                    after=after, after_point=after_point,
                    after_snapshot_dir=after_dir,
                    point_matches_before=(after_point == (before or {}).get("point")),
                    dir_matches_before=(after_dir == prev_dir),
                    moved=moved, hint=hist._active_hint.text(),
                    export_btn_enabled=hist.export_ws_btn.isEnabled(),
                    passed=bool(step_ok and moved))

    s5_depth = len(hist._undo_stack)
    s5a = _undo_once("撤销「继续」→ 回到恢复点")
    s5b = _undo_once("撤销「恢复」→ 回到恢复前")
    for step in (s5a, s5b):
        print(f"[S5] {step['label']}：撤销前指针={step['pre_undo_point']}"
              f"（{Path(step['pre_undo_snapshot_dir']).name}），"
              f"撤销后指针={step['after_point']}"
              f"（{step['after_snapshot_dir'] and Path(step['after_snapshot_dir']).name}），"
              f"应回到={step['before_point']}，判据={step['rule']}，"
              f"指针确有变化={step['moved']}，通过={step['passed']}")
    # 撤销到底 = 回到 S2 恢复之前的状态（本场景恢复前是「未指定」）
    end_cur = snap.current_state(runs_root)
    back_to_start = (end_cur is None and not hist._undo_stack)
    print(f"[S5] 撤到底：栈深(撤销前)={s5_depth} → 现={len(hist._undo_stack)}，"
          f"当前工作区={((end_cur or {}).get('point'))}，"
          f"回到恢复前(未指定)={back_to_start}，"
          f"提示=「{hist._active_hint.text()}」")
    s5_ok = bool(s5a["passed"] and s5b["passed"] and back_to_start)
    report["s5_undo"] = dict(
        rule="撤销 = 回到被撤销操作之前的现场；未指定则回到未指定",
        undo_stack_depth_before=s5_depth,
        undo_stack_depth_after=len(hist._undo_stack),
        back_to_state_before_restore=back_to_start,
        # 顶层 before/after 取「撤销『继续』」这一跳：before/after 都是真实指针
        # （replace → replace），可直接核对；第二跳的 before 本身是 None（那步操作前
        # 就是「未指定」），若取它会得到两个 null、看不出撤销到底做了什么。
        before=s5a["before"], after=s5a["after"],
        before_point=s5a["before_point"], after_point=s5a["after_point"],
        before_snapshot_dir=s5a["before_snapshot_dir"],
        after_snapshot_dir=s5a["after_snapshot_dir"],
        point_matches_before=s5a["point_matches_before"],
        dir_matches_before=s5a["dir_matches_before"],
        # 两跳明细各存一份完整前后状态，证明撤销逐级往回退
        step1_undo_continue=s5a,
        step2_undo_restore=s5b,
        hint=s5b["hint"], export_btn_enabled=s5b["export_btn_enabled"],
        passed=s5_ok)
    ok = ok and s5_ok

    # 再恢复一次，供 S6 / S8 用（重启后仍要看到当前工作区）
    hist._apply_restore(idx, "replace", pts)
    QApplication.processEvents()

    # ---------------- S6 重启后阶段点仍在 ----------------
    win.close()
    QApplication.processEvents()
    win2 = open_window(ws)
    win2.go("history")
    QApplication.processEvents()
    hist2 = win2.page("history")
    hist2.refresh()
    QApplication.processEvents()
    pts2 = snap.list_points(run_dir)
    avail2 = [p for p in pts2 if p["available"]]
    cur2 = snap.current_state(runs_root)
    print(f"[S6] 重启后：历史 {hist2.row_count} 条，阶段点 {len(avail2)}/{len(pts2)} 可用，"
          f"当前工作区={cur2.get('point') if cur2 else None}，提示=「{hist2._active_hint.text()}」")
    s6_ok = (len(avail2) == len(avail) and bool(cur2)
             and cur2.get("point") == "replace" and hist2.row_count >= 1)
    report["s6_restart"] = dict(rows=hist2.row_count, points=len(avail2),
                                current=cur2.get("point") if cur2 else None,
                                hint=hist2._active_hint.text())
    ok = ok and s6_ok
    win2.grab().save(str(SHOTS / "s6_restarted_points.png"))

    # ---------------- S7 二次确认文案（读真实弹窗的正文）----------------
    probe = hm.SnapshotDialog(book="公版样本", when="2026-10-27 23:34",
                              points=pts)
    dlg_texts = [l.text() for l in probe.findChildren(QLabel)]
    first_note = " ".join(t for t in dlg_texts if len(t) > 20)[:400]
    has_scope = ("覆盖" in first_note and "撤销" in first_note
                 and "历史记录" in first_note and "原书" in first_note)
    # 确认按钮的文案与「这次会动什么」都要在弹窗里
    dlg_btns = [b.text() for b in probe.findChildren(QPushButton)]
    has_confirm = any("确认恢复" in t for t in dlg_btns)
    probe.reject()
    print(f"[S7] 恢复确认弹窗：{first_note[:70]}…；写明影响范围+可撤销={has_scope}，"
          f"确认按钮={has_confirm}")
    report["s7_confirm"] = dict(note=first_note, scope_and_undo=has_scope,
                                confirm_button=has_confirm,
                                buttons=dlg_btns)
    ok = ok and has_scope and has_confirm

    # ---------------- S8 界面状态呈现 ----------------
    from PySide6.QtCore import Qt  # noqa: F811
    buttons = [b for b in hist2.findChildren(QPushButton)]
    labels = [l.text() for l in hist2.findChildren(QLabel)]
    has_entry = any(b.text().strip("↺ ") == "恢复" for b in buttons)
    has_reexport = any("重新导出" in b.text() for b in buttons)
    hint_ok = any("当前工作区" in t and "替换完成" in t for t in labels)
    btns_ok = hist2.export_ws_btn.isEnabled() and hist2.continue_btn.isEnabled()
    print(f"[S8] 界面：行内「恢复」入口={has_entry}，重新导出={has_reexport}，"
          f"当前工作区提示={hint_ok}，导出/续跑按钮可用={btns_ok}")
    report["s8_ui"] = dict(restore_entry=has_entry, reexport_entry=has_reexport,
                           active_hint=hint_ok, buttons_enabled=btns_ok,
                           hint_text=hist2._active_hint.text())
    ok = ok and has_entry and has_reexport and hint_ok and btns_ok

    # ---------------- S9 零露出复扫 ----------------
    for key in ("home", "import", "oneclick", "check", "vocab", "export", "history"):
        win2.go(key)
        QApplication.processEvents()
    win2.go("history")
    QApplication.processEvents()
    texts = collect_texts(win2)
    leaks = screen_leaks(texts)
    # 历史页单独复扫「降级」口径：这个词在别处是正常文案，本卡只要求
    # 「恢复」不再写成「降级为重新导出」。
    hist_texts = collect_texts(hist2)
    degrade = [t for t in hist_texts if "降级" in t]
    print(f"[S9b] 历史页「降级」口径复扫：{len(hist_texts)} 条文本，命中 {len(degrade)}")
    report["s9b_degrade_word"] = dict(scanned=len(hist_texts), hits=degrade)
    ok = ok and not degrade
    print(f"[S9] 零露出：扫描 {len(texts)} 条界面文本，命中 {len(leaks)}")
    for l in leaks[:8]:
        print("    ", l)
    report["s9_zero_leak"] = dict(scanned=len(texts), hits=leaks)
    ok = ok and not leaks

    win2.close()
    report["passed"] = bool(ok)
    out = EVID / "accept_t34.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n验收{'通过' if ok else '未通过'} → {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
