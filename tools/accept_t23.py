"""M2-T2.3 验收测试：可视化进度与取消（真实大语料实测）。

场景：
  A  完整跑一次（真实点击主按钮）——采集每阶段耗时、进度条采样、ETA 文案、
     结果卡真实数字。
  B  在「替换词语」阶段点真实取消（Go 引擎子进程被终止）——测取消生效
     延迟、工作区清理、原书未动；随后完整重跑，成品 sha256 与首次对照。
  C  在「整理排版」阶段点真实取消（纯 Python 阶段，阶段边界生效）——同上
     口径清理与复跑对照。
  D  界面文案零露出扫描（控件树 + 弹窗 + 结果卡），不允许出现内部阶段名
     /命令行输出/内部路径。

产出：evidence/t23_evidence.json（供交付包引用，数字均为实测）。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QProgressBar

# 【M2-T2.5 集成调整】原脚本按 T2.3 独立包目录布局取路径；合并后：
#   - 源码在 build/pkg/fixtext_ui（oneclick_module / fixtext_worker 等）
#   - M1 编排器与词库用合并包自带的 build/pkg/pipeline 与 build/pkg/data/rules
#     —— 这样验收跑的就是「合并后的真实交付物」，而不是外部旧目录
#   - 语料与基线仍在 build/in/（未随包分发）
#   - 运行产物与 evidence 不进交付 zip：runs 放 build/t23_runs
PKG = Path(__file__).resolve().parent.parent          # build/pkg
# 【M2-T2.7】布局适配：语料与包同级（artifacts/in 下直接放 paohuo.epub /
# baseline_paohuo）时不再要求 build/in 子目录；两种布局都能跑。
WORK = PKG.parent / "in"                              # build/in
if not WORK.is_dir() and (PKG.parent / "paohuo.epub").exists():
    WORK = PKG.parent
SRC = PKG / "fixtext_ui"
EVID = PKG / "evidence"

EPUB = WORK / "paohuo.epub"
PIPELINE_ROOT = PKG / "pipeline"
RULES_DIR = PKG / "data" / "rules"
RUNS_ROOT = PKG.parent / "t23_runs"

#: 基线成品（M1 编排器直接跑出的全量结果，非本次 UI 运行）：main() 里运行时计算指纹，避免转写误差
BASELINE_EPUB = WORK / "baseline_paohuo" / "06_restore" / "paohuo_restored.epub"

sys.path.insert(0, str(SRC))
sys.path.insert(0, str(PKG))                          # fixtext_import / fixtext_error_center


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    return app


def collect_texts(widget) -> list[str]:
    """收控件树上所有用户可见文本（text/toolTip/placeholder/windowTitle）。"""
    from PySide6.QtWidgets import QWidget
    texts: list[str] = []
    for w in widget.findChildren(QWidget) + [widget]:
        if isinstance(w, QLabel):
            texts.append(w.text())
        if isinstance(w, QPushButton):
            texts.append(w.text())
        for prop in ("toolTip", "placeholderText", "accessibleName"):
            v = getattr(w, prop, "")
            if isinstance(v, str) and v:
                texts.append(v)
    texts.append(widget.windowTitle() if hasattr(widget, "windowTitle") else "")
    return [t for t in texts if t]


def run_scenario(app, name: str, *, cancel_at_stage: int | None = None,
                 timeout_s: float = 180.0) -> dict:
    """跑一次 UI 场景：真实点击主按钮 →（可选）目标阶段真实点击取消 → 弹窗关闭。"""
    from oneclick_module import OneClickModule

    mod = OneClickModule()
    mod.resize(1100, 950)
    mod.show()
    mod.set_run_context(dict(
        epub=EPUB, pipeline_root=PIPELINE_ROOT,
        rules_before=RULES_DIR / "before.json",
        rules_after=RULES_DIR / "after.json",
        engine_path=PIPELINE_ROOT / "vendor" / "fixtext" / "engine" / "go_src" / "bin" / "replace_by_go-linux-amd64",
        runs_root=RUNS_ROOT, title="示例书稿",
    ))
    app.processEvents()

    events: list[dict] = []
    stage_marks: dict[str, dict] = {}
    t0 = time.monotonic()
    state = {
        "t_cancel_click": None,
        "t_confirm_click": None,
        "t_confirm_scheduled": False,
        "t_cancelled_signal": None,
        "workdir": None,
        "dialog_texts": set(),
        "hooked": False,
    }

    dlg_holder: dict = {}

    def poll():
        w = mod._worker
        dlg = mod._dlg
        if w is None or dlg is None:
            return
        if not state["hooked"]:
            # worker 一就位就挂阶段信号（比 singleShot(0) 可靠：不受点击派发次序影响）
            state["hooked"] = True
            w.stage_started.connect(on_stage_started)
            w.stage_finished.connect(on_stage_finished)
            w.cancelled.connect(on_cancelled)
            state["workdir"] = str(w.job.workdir)
        job = w.job
        snap = w.snapshot()
        events.append({
            "t": round(time.monotonic() - t0, 2),
            "stage": job.current_index,
            "percent": snap["percent"],
            "eta_s": snap["eta_s"],
            "elapsed_s": snap["elapsed_s"],
            "ui_step": dlg.step_name.text(),
            "ui_eta": dlg.eta.text(),
        })
        # 弹窗打开期间的全量控件文本（进入零露出扫描）
        state["dialog_texts"].update(collect_texts(dlg))

    def watch_cancel():
        w = mod._worker
        dlg = mod._dlg
        if w is None or dlg is None:
            return
        # 【M4-EX.2c 适配】取消按钮自本卡起会先弹「确认放弃本次校正确认？」
        # 模态框（CancelConfirmDialog）。老脚本只点 cancel 不点确认，会卡在
        # dialog.exec() 的嵌套事件循环里直到脚本超时——这里补上「点确认放弃」。
        # 两个点击都必须经 QTimer.singleShot(0, ...) 派发：在定时器槽里直接
        # QTest.mouseClick 会同步进入 exec()，把本槽和后续轮询一起卡住。
        from PySide6.QtCore import QTimer as _QTimer
        confirm = getattr(dlg, "_confirm_dlg", None)
        if confirm is not None and not state["t_confirm_scheduled"]:
            btn = getattr(confirm, "confirm_btn", None)
            if btn is not None:
                state["t_confirm_scheduled"] = True
                state["t_confirm_click"] = time.monotonic()
                _QTimer.singleShot(
                    0, lambda b=btn: QTest.mouseClick(b, Qt.MouseButton.LeftButton))
            return
        if state["t_cancel_click"] is not None:
            return
        if w.job.current_index == cancel_at_stage:
            state["t_cancel_click"] = time.monotonic()
            btn2 = dlg.cancel_btn
            _QTimer.singleShot(
                0, lambda b=btn2: QTest.mouseClick(b, Qt.MouseButton.LeftButton))

    def on_stage_started(i):
        stage_marks[f"s{i}"] = {"start": round(time.monotonic() - t0, 3)}

    def on_stage_finished(i, sec):
        stage_marks.setdefault(f"s{i}", {})["elapsed_s"] = sec
        stage_marks[f"s{i}"]["end"] = round(time.monotonic() - t0, 3)

    def on_cancelled():
        state["t_cancelled_signal"] = time.monotonic()

    # 先挂信号钩子，再点击主按钮（点击会同步进入 exec 循环）
    poller = QTimer()
    poller.setInterval(100)
    poller.timeout.connect(poll)
    if cancel_at_stage is not None:
        watcher = QTimer()
        watcher.setInterval(50)
        watcher.timeout.connect(watch_cancel)
        watcher.start()

    poller.start()

    t_start = time.monotonic()
    QTest.mouseClick(mod.run_btn, Qt.MouseButton.LeftButton)   # 真实用户路径
    t_end = time.monotonic()

    poller.stop()
    if cancel_at_stage is not None:
        watcher.stop()
    total_ui = round(t_end - t_start, 2)

    result = {
        "scenario": name,
        "cancel_at_stage": cancel_at_stage,
        "outcome": mod._outcome,
        "total_s": total_ui,
        "stage_marks": stage_marks,
        "poll_samples": len(events),
        "workdir": state["workdir"],
        "workdir_exists_after": (Path(state["workdir"]).exists()
                                 if state["workdir"] else None),
        "toast": mod.status.text(),
        "summary": mod._summary,
        "events": events,       # 全量采样，供证据引用
    }
    if state["t_cancel_click"] is not None:
        # 【M4-EX.2c 适配】现在取消是两段：点「取消」→ 确认框 → 点「确认放弃」。
        # 以「确认放弃」为计时起点，才反映真实的取消生效延迟。
        t_effective = state["t_confirm_click"] or state["t_cancel_click"]
        result["confirm_dialog_shown"] = state["t_confirm_click"] is not None
        result["confirm_click_latency_s"] = (
            round(state["t_confirm_click"] - state["t_cancel_click"], 3)
            if state["t_confirm_click"] else None)
        result["cancel_close_latency_s"] = round(t_end - t_effective, 3)
        if state["t_cancelled_signal"] is not None:
            result["cancel_signal_latency_s"] = round(
                state["t_cancelled_signal"] - t_effective, 3)
    # 界面文本采集（模块控件树 + 弹窗打开期间采到的全量文本）
    result["module_texts"] = collect_texts(mod)
    result["dialog_texts"] = sorted(state["dialog_texts"])
    mod.hide()
    mod.deleteLater()
    app.processEvents()
    return result


def scan_leaks(texts: list[str]) -> list[str]:
    """内部阶段名 / 命令行词 / 内部路径 → 不允许出现在任何界面文本里。"""
    import re
    bad = []
    patterns = [
        r"\bmerge\b", r"\blayout\b", r"\breplace\b", r"\bquote\b",
        r"\bbookmap\b", r"\brestore\b", r"run_pipeline", r"state\.json",
        r"subprocess", r"\bstdout\b", r"\bstderr\b", r"exit code",
        r"/home/", r"fixtext_pipeline", r"\.go\b", r"nonce",
    ]
    for text in texts:
        for pat in patterns:
            if re.search(pat, text):
                bad.append({"pattern": pat, "text": text[:120]})
    return bad


def _stages_reached(events: list[dict]) -> dict:
    """从轮询采样还原取消场景实际推进到哪一步（阶段信号钩子时序不可靠，以采样为准）。"""
    stages = sorted({e["stage"] for e in events})
    return {
        "stage_indexes": stages,
        "max_stage_index": stages[-1] if stages else None,
        "ui_step_labels_seen": sorted({e["ui_step"] for e in events if e["ui_step"]}),
        "max_percent": max((e["percent"] for e in events), default=None),
    }


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    # 【M4-T4.4】幂等：先记下场景开始前 runs 目录里已有的目录名，之后只看
    # 「本次新增的目录」——上一轮成功运行留下的同名工作区不算本轮残留，
    # 于是本脚本连跑多次结果一致（以前用「允许名单」判残留，第二轮必假失败）。
    pre_existing_dirs = {d.name for d in RUNS_ROOT.iterdir() if d.is_dir()}
    BASELINE_SHA = sha256_file(BASELINE_EPUB)
    original_sha_before = sha256_file(EPUB)
    all_texts: list[str] = []

    app = make_app()

    # ---- 场景 A：完整运行 ----
    a = run_scenario(app, "A_full_run")
    print(f"[A] 完整运行 {a['total_s']}s outcome={a['outcome']} "
          f"poll={a['poll_samples']} workdir_left={a['workdir_exists_after']}")
    assert a["outcome"] == "ok", a
    assert a["workdir_exists_after"] is True, "成功运行应保留工作区（成品所在）"
    restored_a = Path(a["workdir"]) / "06_restore" / "paohuo_restored.epub"
    sha_a = sha256_file(restored_a)
    all_texts += a["module_texts"]
    all_texts += a["dialog_texts"]
    all_texts += [e["ui_step"] for e in a["events"]]
    all_texts += [e["ui_eta"] for e in a["events"]]

    # 超过 3 秒的阶段在运行期间是否有进度反馈：
    # 阶段实际耗时取自作业自身上报的 stage_elapsed（summary），轮询采样提供 UI 侧证据
    stage_elapsed = (a["summary"] or {}).get("stage_elapsed", {}) or {}
    long_stage_evidence = {}
    for i, key in enumerate(["merge", "layout", "replace", "quote", "bookmap", "restore"]):
        el = stage_elapsed.get(key)
        if el and el >= 2.5:   # 3 秒线附近的阶段一并取证（replace 单次约 3 秒上下浮动）
            during = [e for e in a["events"] if e["stage"] == i]
            from collections import Counter
            step_counter = Counter(e["ui_step"] for e in during if e["ui_step"])
            long_stage_evidence[key] = {
                "elapsed_s": round(el, 3),
                "over_3s": bool(el > 3.0),
                "ui_step_label": step_counter.most_common(1)[0][0] if step_counter else None,
                "ui_step_labels_during": [s for s, _ in step_counter.most_common()],
                "eta_texts_sample": sorted({e["ui_eta"] for e in during})[:6],
                "progress_updates_during": len(during),
                "percent_first_last": [during[0]["percent"], during[-1]["percent"]] if during else None,
            }
            # 硬断言：该阶段运行期间界面有进度反馈（步骤文案 + 更新次数 > 0）
            assert during, f"阶段 {i}（{key}）超过 3 秒但界面无进度采样"
            assert step_counter, f"阶段 {i}（{key}）无步骤文案"
            assert step_counter.most_common(1)[0][0] != "准备中…", \
                f"阶段 {i}（{key}）的界面步骤文案停留在「准备中…」"
            assert len(during) >= 3, f"阶段 {i}（{key}）进度更新少于 3 次"
    print("[A] >3s 阶段进度证据:", json.dumps(long_stage_evidence, ensure_ascii=False))

    # ---- 场景 B：替换阶段取消（Go 子进程被杀）----
    b = run_scenario(app, "B_cancel_in_replace", cancel_at_stage=2)
    print(f"[B] 替换阶段取消 outcome={b['outcome']} "
          f"close={b.get('cancel_close_latency_s')}s signal={b.get('cancel_signal_latency_s')}s "
          f"workdir_exists={b['workdir_exists_after']}")
    assert b["outcome"] == "cancelled", b
    assert b["workdir_exists_after"] is False, "取消后工作区必须被清理"
    assert b["toast"] == "已取消，工作区已清理，未留下半成品（原书完好）", b["toast"]
    all_texts += b["module_texts"]
    all_texts += b["dialog_texts"]
    all_texts += [e["ui_step"] for e in b["events"]]
    all_texts += [e["ui_eta"] for e in b["events"]]

    # 取消后：本轮新增的目录里只允许保留「成功运行」的工作区，不允许有取消残留。
    # 判据是「场景前集合的差集」——既排除历史遗留，也排除本轮自己的成功运行。
    allowed_b = {Path(a["workdir"]).name}
    newcomers_b = {d.name for d in RUNS_ROOT.iterdir() if d.is_dir()} - pre_existing_dirs
    leftovers = sorted(newcomers_b - allowed_b)
    assert not leftovers, f"取消后 runs 目录残留: {leftovers}"

    # ---- 场景 B2：取消后完整重跑（sha256 对照）----
    b2 = run_scenario(app, "B2_rerun_after_cancel")
    assert b2["outcome"] == "ok", b2
    restored_b2 = Path(b2["workdir"]) / "06_restore" / "paohuo_restored.epub"
    sha_b2 = sha256_file(restored_b2)
    all_texts += b2["module_texts"]
    all_texts += b2["dialog_texts"]
    print(f"[B2] 复跑 {b2['total_s']}s sha={sha_b2[:16]}…")

    # ---- 场景 C：排版阶段取消（纯 Python 阶段，边界生效）----
    c = run_scenario(app, "C_cancel_in_layout", cancel_at_stage=1)
    print(f"[C] 排版阶段取消 outcome={c['outcome']} "
          f"close={c.get('cancel_close_latency_s')}s workdir_exists={c['workdir_exists_after']}")
    assert c["outcome"] == "cancelled", c
    assert c["workdir_exists_after"] is False
    all_texts += c["module_texts"]
    all_texts += c["dialog_texts"]
    all_texts += [e["ui_step"] for e in c["events"]]
    all_texts += [e["ui_eta"] for e in c["events"]]
    allowed_c = {Path(a["workdir"]).name, Path(b2["workdir"]).name}
    newcomers_c = {d.name for d in RUNS_ROOT.iterdir() if d.is_dir()} - pre_existing_dirs
    leftovers_c = sorted(newcomers_c - allowed_c)
    assert not leftovers_c, f"取消后 runs 目录残留: {leftovers_c}"

    # ---- 场景 C2：再复跑一次对照 ----
    c2 = run_scenario(app, "C2_rerun_after_cancel2")
    assert c2["outcome"] == "ok", c2
    restored_c2 = Path(c2["workdir"]) / "06_restore" / "paohuo_restored.epub"
    sha_c2 = sha256_file(restored_c2)
    all_texts += c2["module_texts"]
    all_texts += c2["dialog_texts"]

    original_sha_after = sha256_file(EPUB)

    # ---- 露出扫描 ----
    leaks = scan_leaks(all_texts)
    print(f"[D] 露出扫描：{len(all_texts)} 条界面文本，命中 {len(leaks)}")

    # ---- 汇总判定 ----
    evidence = {
        "corpus": {
            "book": "公版样本整本（EPUB）",
            "rules": "304,255 条规则 × 2 趟",
            "epub_bytes": EPUB.stat().st_size,
        },
        "baseline_sha_restored_epub": BASELINE_SHA,
        "scenario_A_full": {
            "total_s": a["total_s"],
            "stage_elapsed": stage_elapsed,
            "summary": a["summary"],
            "restored_sha256": sha_a,
            "long_stage_progress": long_stage_evidence,
            "poll_events": a["events"],   # 全量轮询采样（阶段/百分比/步骤文案/ETA 原文），供复核
        },
        "scenario_B_cancel_in_replace": {
            "cancel_close_latency_s": b.get("cancel_close_latency_s"),
            "cancel_signal_latency_s": b.get("cancel_signal_latency_s"),
            "workdir_exists_after": b["workdir_exists_after"],
            "toast": b["toast"],
            "stages_reached": _stages_reached(b["events"]),
        },
        "scenario_B2_rerun": {"total_s": b2["total_s"], "restored_sha256": sha_b2},
        "scenario_C_cancel_in_layout": {
            "cancel_close_latency_s": c.get("cancel_close_latency_s"),
            "cancel_signal_latency_s": c.get("cancel_signal_latency_s"),
            "workdir_exists_after": c["workdir_exists_after"],
            "toast": c["toast"],
            "stages_reached": _stages_reached(c["events"]),
        },
        "scenario_C2_rerun": {"total_s": c2["total_s"], "restored_sha256": sha_c2},
        "determinism": {
            "A_vs_baseline": sha_a == BASELINE_SHA,
            "B2_vs_A": sha_b2 == sha_a,
            "C2_vs_A": sha_c2 == sha_a,
            "all_equal": sha_a == BASELINE_SHA == sha_b2 == sha_c2,
        },
        "original_epub_untouched": original_sha_before == original_sha_after,
        "idempotency": {
            "pre_existing_runs_dirs": sorted(pre_existing_dirs),
            "new_runs_dirs_after_b": sorted(newcomers_b),
            "new_runs_dirs_after_c": sorted(newcomers_c),
            "judgement": "只对「场景前集合的差集」判残留，历史目录不参与",
        },
        "original_epub_sha256": original_sha_after,
        "leak_scan": {
            "texts_scanned": len(all_texts),
            "violations": leaks,
        },
    }
    (EVID / "t23_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = (
        evidence["determinism"]["all_equal"]
        and evidence["original_epub_untouched"]
        and not leaks
        and b["workdir_exists_after"] is False
        and c["workdir_exists_after"] is False
    )
    print("ACCEPT:", "PASS" if ok else "FAIL")
    print(json.dumps(evidence["determinism"], ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
