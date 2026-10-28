"""M4-T4.2 验收：Python greedy 引擎双轨与 Go 降级路径（真实语料实测）。

验收口径（任务卡 M4-T4.2）：

  S1 全量等价   《炮火弧线》788 章（约 314 万字符）分别用 go / python
                引擎跑完整六阶段：替换后正文与还原 EPUB sha256 逐字节一致。
  S2 基线集等价 T0.4 回归基线集 15 语料 × count=2：Python 引擎输出与
                基线 expected/go 逐字节一致（304,256 条规则）。
  S3 降级演练   人为改名 Go 引擎 → 界面预检发现 → 弹人话确认（明示耗时
                差异）→ 探针点「改用 Python 引擎」→ 完整六阶段完成，
                输出与 Go 版逐字节一致；记录弹窗文案与用户动作。
  S4 拒绝降级   同 S3 但探针点「取消」→ 明确报错（toast 文案实录）、
                不产生任何 runs 目录，不硬跑。
  S5 引擎切换   设置键切 python → 下次校正（不带 engine 参数）日志/报告
                可证走 python；切回 go 恢复。
  S6 CLI 口径   引擎缺失时 CLI 明确报错非零退出；--replace-engine python
                小样本成功且报告 engine=python。
  S7 性能对照   Python 引擎全量耗时实测，与排期 §3.1 基准（3.09 MB/s、
                最大单册 17.9 秒，Go）对照，如实记录差距。

产出：evidence/t42_evidence.json（全部数字为实测，不凑数）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
PIPELINE_ROOT = PKG / "pipeline"
RULES_DIR = PKG / "data" / "rules"
ENGINE = (PIPELINE_ROOT / "vendor" / "fixtext" / "engine" / "go_src" / "bin"
          / "replace_by_go-linux-amd64")
EVID = PKG / "evidence"
RUNS_ROOT = PKG.parent / "t42_runs"

for p in (PKG, PKG / "fixtext_ui", PIPELINE_ROOT, PIPELINE_ROOT / "vendor"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# 语料位置：优先环境变量，其次常见落点（验收语料不进交付包）
_CAND_EPUB = [
    Path(os.environ.get("FIXTEXT_T42_EPUB", "")) if os.environ.get("FIXTEXT_T42_EPUB") else None,
    PKG.parent.parent / "media" / "paohuo.epub",
    Path("/tmp/t42/paohuo.epub"),
]
_CAND_BASELINE = [
    Path(os.environ.get("FIXTEXT_T42_BASELINE", "")) if os.environ.get("FIXTEXT_T42_BASELINE") else None,
    PKG.parent.parent / "media" / "baseline",
    Path("/tmp/t42/t04/FixText_T0.4_回归基线集_v1/baseline"),
]
EPUB = next((p for p in _CAND_EPUB if p and p.is_file()), None)
BASELINE = next((p for p in _CAND_BASELINE if p and p.is_dir()), None)
SMALL_EPUB = PKG / "tests" / "samples" / "book_paohuo.epub"

#: 排期 §3.1 的 Go 基准（对照用，不是本卡的实测）
GO_BASELINE_MBPS = 3.09
GO_BASELINE_MAX_BOOK_S = 17.9


def sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fresh(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_job(epub: Path, workdir: Path, *, engine=None, settings_file=None) -> dict:
    """跑一次六阶段（与界面共用 CorrectionJob 链路）。"""
    if settings_file is not None:
        os.environ["FIXTEXT_SETTINGS_FILE"] = str(settings_file)
    try:
        from fixtext_worker import CorrectionJob

        job = CorrectionJob(
            epub=epub, workdir=workdir,
            rules_before=RULES_DIR / "before.json",
            rules_after=RULES_DIR / "after.json",
            engine_path=ENGINE, pipeline_root=PIPELINE_ROOT,
            engine=engine,
            custom_vocab_path=workdir.parent / "custom_vocab.json",
            derived_rules_dir=workdir.parent / "derived_rules",
        )
        summary = job.run()
        summary["_engine_used"] = job.engine_used
        summary["_replace_report"] = job.stage_reports.get("replace", {})
        return summary
    finally:
        if settings_file is not None:
            os.environ.pop("FIXTEXT_SETTINGS_FILE", None)


# --------------------------------------------------------------------------- #
# S1 / S2：逐字节等价
# --------------------------------------------------------------------------- #

def _py_replace_same_input(go_run: Path, out_dir: Path) -> dict:
    """同输入精确等价：用 Python 引擎直跑 Go 那次的 replace 输入。

    全量跑两次各生成新的 merge nonce（bundle 头部随机 hex），after_text 原始
    sha 天然不等（Go vs Go 也不等）；故用 Go 跑落盘的 03_replace/before 作为
    同一输入、同一份派生规则、同 count 直跑 Python 引擎，与 Go 的 after 逐字
    节对比。端到端一致性另由 restored_epub sha（跨 nonce 稳定）证明。
    """
    rep = json.loads((go_run / "03_replace" / "replace_report.json")
                     .read_text(encoding="utf-8"))
    before_file = Path(rep["before_path"])
    assert before_file.is_file(), before_file
    derived = go_run.parent / "derived_rules"
    rule_before = derived / "before.json"
    rule_after = derived / "after.json"
    if not rule_before.is_file():   # 无自定义词时可能不落派生目录
        rule_before, rule_after = RULES_DIR / "before.json", RULES_DIR / "after.json"

    from fixtext.engine import EngineRequest, InputMode, OutputMode, RuleSet
    from fixtext.engine.py_engine import PyGreedyEngineClient

    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "after_same_input.txt"
    rules = RuleSet.from_files(rule_before, rule_after)
    request = EngineRequest(
        rules=rules, count=rep.get("count", 2),
        input_mode=InputMode.FILE, output_mode=OutputMode.FILE,
        input_path=before_file, output_path=out_file,
    )
    t0 = time.perf_counter()
    result = PyGreedyEngineClient().run(request)
    elapsed = time.perf_counter() - t0
    return dict(
        sha=sha256_file(out_file),
        sha_in=sha256_file(before_file),
        go_sha_in=rep.get("sha256_in"),
        go_sha_out=rep.get("sha256_out"),
        elapsed_s=round(elapsed, 2),
        rules=rep.get("rules"), count=rep.get("count"),
    )


def s1_full_equivalence(ev: dict) -> dict:
    assert EPUB is not None, "找不到《炮火弧线》语料（FIXTEXT_T42_EPUB）"
    root = fresh(RUNS_ROOT / "s1")
    print("[S1] go 引擎全量 788 章跑起 …", flush=True)
    t0 = time.perf_counter()
    go = run_job(EPUB, root / "go", engine="go")
    go_wall = time.perf_counter() - t0

    print("[S1] python 引擎全量 788 章跑起 …", flush=True)
    t0 = time.perf_counter()
    py = run_job(EPUB, root / "py", engine="python")
    py_wall = time.perf_counter() - t0

    go_rep, py_rep = go["_replace_report"], py["_replace_report"]
    # 同输入直跑：Go 那次的 before → Python 引擎 → 与 Go 的 after 逐字节比
    direct = _py_replace_same_input(root / "go", root / "py_direct")
    same = {
        "restored_epub": sha256_file(Path(go["artifacts"]["restored_epub"]))
        == sha256_file(Path(py["artifacts"]["restored_epub"])),
        "after_text_same_input": direct["sha"] == direct["go_sha_out"],
        "same_input_verified": direct["sha_in"] == direct["go_sha_in"],
        "after_sha_go": go_rep.get("after_sha256"),
        "after_sha_py": direct["sha"],
        "restored_sha_go": go.get("restored_sha256"),
        "restored_sha_py": py.get("restored_sha256"),
    }
    assert all(same[k] for k in ("restored_epub", "after_text_same_input",
                                 "same_input_verified")), same
    assert go_rep.get("engine") == "go" and py_rep.get("engine") == "python"
    assert py_rep.get("engine_path") == "python:pyahocorasick-greedy"

    mb = go_rep.get("bytes_in", 0) / 1e6
    data = dict(
        chapters=go.get("chapters"),
        bytes_in=go_rep.get("bytes_in"),
        go=dict(
            replace_elapsed_s=go_rep.get("engine_elapsed_s"),
            total_wall_s=round(go_wall, 1),
            mbps=round(mb / max(go_rep.get("engine_elapsed_s", 1e-9), 1e-9), 2),
        ),
        python=dict(
            replace_elapsed_s=py_rep.get("engine_elapsed_s"),
            direct_elapsed_s=direct["elapsed_s"],
            total_wall_s=round(py_wall, 1),
            mbps=round(mb / max(py_rep.get("engine_elapsed_s", 1e-9), 1e-9), 2),
        ),
        rules=direct["rules"], count=direct["count"],
        note="after_text 等价比对口径：同一 before 输入直跑两引擎（merge nonce 是每跑随机的，"
             "跨全量跑的原始 sha 含 nonce 不具备可比性）；端到端由 restored_epub sha 相等证明",
        **same,
    )
    ev["S1_full_equivalence"] = data
    print(f"[S1] PASS  同输入 after {same['after_sha_go'][:16]}… == {same['after_sha_py'][:16]}…；"
          f"restored {same['restored_sha_go'][:16]}… 一致；"
          f"replace go {data['go']['replace_elapsed_s']}s / py {data['python']['replace_elapsed_s']}s",
          flush=True)
    return data


def s2_baseline_equivalence(ev: dict) -> None:
    assert BASELINE is not None, "找不到 T0.4 基线集（FIXTEXT_T42_BASELINE）"
    from fixtext.engine import EngineRequest, InputMode, OutputMode, RuleSet
    from fixtext.engine.py_engine import PyGreedyEngineClient

    rules = RuleSet.from_files(BASELINE / "rules/before.json",
                               BASELINE / "rules/after.json")
    manifest = json.loads((BASELINE / "manifest/baseline_manifest.json")
                          .read_text(encoding="utf-8"))
    out_dir = fresh(RUNS_ROOT / "s2")
    rows = []
    client = PyGreedyEngineClient(default_timeout_s=1800)
    for item in manifest["items"]:
        name = item["file"]
        src = BASELINE / "corpus" / name
        expect = BASELINE / "expected" / "go" / name
        dst = out_dir / name
        t0 = time.perf_counter()
        resp = client.run(EngineRequest(
            rules=rules, count=2,
            input_mode=InputMode.FILE, input_path=src,
            output_mode=OutputMode.FILE, output_path=dst,
            encoding="utf-8", timeout_s=1800,
        ))
        dt = time.perf_counter() - t0
        assert resp.ok, f"{name}: {resp.error.as_dict() if resp.error else resp}"
        got = sha256_file(dst)
        want = sha256_file(expect)
        assert got == want, f"{name}: py {got[:16]}… != expected/go {want[:16]}…"
        rows.append(dict(file=name, bytes=src.stat().st_size,
                         sha256=got, elapsed_s=round(dt, 2)))
        print(f"[S2] {name}: {src.stat().st_size/1e6:.2f}MB {dt:.2f}s sha={got[:12]}… 一致",
              flush=True)
    total_bytes = sum(r["bytes"] for r in rows)
    total_s = sum(r["elapsed_s"] for r in rows)
    ev["S2_baseline_equivalence"] = dict(
        rules=manifest["rules"]["meta"]["total_rules"],
        replace_count=manifest["replace_count"],
        corpora=len(rows),
        total_bytes=total_bytes,
        total_elapsed_s=round(total_s, 1),
        mbps=round(total_bytes / 1e6 / max(total_s, 1e-9), 2),
        rows=rows,
    )
    print(f"[S2] PASS  {len(rows)}/{len(manifest['items'])} 语料逐字节一致 "
          f"（{total_bytes/1e6:.1f}MB / {total_s:.1f}s）", flush=True)


# --------------------------------------------------------------------------- #
# S3 / S4：降级演练（UI 预检路径，真实点击）
# --------------------------------------------------------------------------- #

def _ui_ctx(runs_root: Path) -> dict:
    return dict(
        pipeline_root=str(PIPELINE_ROOT),
        rules_before=str(RULES_DIR / "before.json"),
        rules_after=str(RULES_DIR / "after.json"),
        engine_path=str(ENGINE),
        runs_root=str(runs_root),
        title="炮火弧线",
        author="远瞳",
        suffix=".epub",
        epub=str(EPUB),
        template_epub=str(EPUB),
        custom_vocab_path=str(runs_root / "custom_vocab.json"),
        derived_rules_dir=str(runs_root / "derived_rules"),
    )


def _schedule_confirm_probe(action: str, captured: dict) -> None:
    """离屏探针：找到降级确认弹窗，记录文案并真实点击按钮。"""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton

    from fixtext_widgets import ConfirmDialog

    def _tick(tries: int = 300):
        for w in list(QApplication.topLevelWidgets()):
            if isinstance(w, ConfirmDialog) and w.isVisible():
                notes = [l.text() for l in w.findChildren(QLabel)]
                captured["dialog_title"] = w.windowTitle()
                captured["dialog_note"] = max(notes, key=len, default="")
                btns = w.findChildren(QPushButton)
                texts = [b.text() for b in btns]
                captured["dialog_buttons"] = texts
                if action == "accept":
                    target = next((b for b in btns if b.text() not in ("取消", "关闭")), btns[-1])
                else:
                    target = next((b for b in btns if b.text() == "取消"), btns[0])
                captured["clicked"] = target.text()
                target.click()
                return
        if tries > 0:
            QTimer.singleShot(200, lambda: _tick(tries - 1))

    QTimer.singleShot(200, _tick)


def _s3s4(ev: dict, *, accept: bool) -> dict:
    from PySide6.QtWidgets import QApplication

    from oneclick_module import OneClickModule

    app = QApplication.instance() or QApplication([])
    assert ENGINE.exists(), "Go 引擎不在（S3/S4 需要先有再改名）"
    quarantine = ENGINE.with_name(ENGINE.name + ".quarantined-by-accept")
    assert not quarantine.exists()
    runs_root = fresh(RUNS_ROOT / ("s3" if accept else "s4"))
    settings = runs_root / "settings.ini"          # 不存在 = 默认 go
    os.environ["FIXTEXT_SETTINGS_FILE"] = str(settings)

    mod = OneClickModule()
    mod.run_context = _ui_ctx(runs_root)
    captured: dict = {}
    _schedule_confirm_probe("accept" if accept else "reject", captured)

    ENGINE.rename(quarantine)
    try:
        os.environ["FIXTEXT_SETTINGS_FILE"] = str(settings)
        mod.do_correction()
    finally:
        if quarantine.exists():
            quarantine.rename(ENGINE)
        os.environ.pop("FIXTEXT_SETTINGS_FILE", None)

    toast = mod.status.text()
    run_dirs = sorted(p.name for p in runs_root.glob("run-*"))
    result = dict(
        dialog_title=captured.get("dialog_title"),
        dialog_note=captured.get("dialog_note"),
        dialog_buttons=captured.get("dialog_buttons"),
        user_action=captured.get("clicked"),
        toast_after=toast,
        run_dirs=run_dirs,
    )
    if accept:
        assert captured.get("clicked") not in (None, "取消"), captured
        assert "数十秒" in captured.get("dialog_note", ""), captured   # 耗时差异提示
        summary = mod._summary
        assert summary is not None, "降级确认后未完成校正"
        assert summary.get("replace_engine") == "python", summary.get("replace_engine")
        result["restored_sha256"] = summary.get("restored_sha256")
        result["chapters"] = summary.get("chapters")
        result["replace_engine"] = summary.get("replace_engine")
        # 降级确认不改长期设置：settings.ini 仍无 engine 键（或为 go）
        assert not settings.exists() or "python" not in settings.read_text(encoding="utf-8")
    else:
        assert captured.get("clicked") == "取消", captured
        assert "校正未开始" in toast or "不可用" in toast, toast
        assert not run_dirs, f"拒绝降级后仍产生 runs：{run_dirs}"
    return result


def s3_fallback_accept(ev: dict, go_restored_sha: str) -> None:
    print("[S3] 改名 Go 引擎 → 界面降级确认（探针点「改用 Python 引擎」）…", flush=True)
    result = _s3s4(ev, accept=True)
    assert result["restored_sha256"] == go_restored_sha, (
        f"降级输出 {result['restored_sha256'][:16]}… != Go 版 {go_restored_sha[:16]}…")
    ev["S3_fallback_accept"] = result
    print(f"[S3] PASS  六阶段经 Python 引擎完成，还原 EPUB 与 Go 版逐字节一致；"
          f"弹窗按钮={result['dialog_buttons']} 用户点了「{result['user_action']}」",
          flush=True)


def s4_fallback_decline(ev: dict) -> None:
    print("[S4] 改名 Go 引擎 → 用户拒绝降级 → 明确报错不硬跑 …", flush=True)
    result = _s3s4(ev, accept=False)
    ev["S4_fallback_decline"] = result
    print(f"[S4] PASS  报错文案：「{result['toast_after']}」；runs 产生 {result['run_dirs']}",
          flush=True)


# --------------------------------------------------------------------------- #
# S5：引擎切换（配置键 engine，下次校正生效）
# --------------------------------------------------------------------------- #

def s5_engine_switch(ev: dict) -> None:
    from fixtext_pipeline import engine_choice as ec

    root = fresh(RUNS_ROOT / "s5")
    settings = root / "settings.ini"
    rows = []
    for choice in ("python", "go"):
        ec.set_engine_choice(choice, file=settings)
        assert ec.get_engine_choice(file=settings) == choice
        summary = run_job(SMALL_EPUB, root / choice, settings_file=settings)
        rep = summary["_replace_report"]
        assert summary["_engine_used"] == choice, (choice, summary["_engine_used"])
        assert rep.get("engine") == choice, rep.get("engine")
        rows.append(dict(
            setting=choice,
            engine_used=summary["_engine_used"],
            report_engine=rep.get("engine"),
            report_engine_path=rep.get("engine_path"),
            restored_sha256=summary.get("restored_sha256"),
        ))
    assert rows[0]["restored_sha256"] == rows[1]["restored_sha256"], \
        "两个引擎对同一本小书输出不一致"
    ev["S5_engine_switch"] = dict(rows=rows, both_engines_same_output=True)
    print(f"[S5] PASS  python→{rows[0]['report_engine']} / go→{rows[1]['report_engine']}，"
          f"输出 sha 一致 {rows[0]['restored_sha256'][:16]}…", flush=True)


# --------------------------------------------------------------------------- #
# S6：CLI 口径（明确报错 / --replace-engine python）
# --------------------------------------------------------------------------- #

def s6_cli(ev: dict) -> None:
    root = fresh(RUNS_ROOT / "s6")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PIPELINE_ROOT)
    env.pop("FIXTEXT_ENGINE", None)
    env.pop("FIXTEXT_SETTINGS_FILE", None)

    quarantine = ENGINE.with_name(ENGINE.name + ".quarantined-by-accept")
    assert ENGINE.exists() and not quarantine.exists()

    # 引擎缺失 + 默认 go → 明确报错非零退出（不硬跑）
    ENGINE.rename(quarantine)
    try:
        p = subprocess.run(
            [sys.executable, "-m", "fixtext_pipeline", "run",
             "--epub", str(SMALL_EPUB), "--workdir", str(root / "missing"),
             "--rules-before", str(RULES_DIR / "before.json"),
             "--rules-after", str(RULES_DIR / "after.json")],
            capture_output=True, text=True, cwd=str(PIPELINE_ROOT),
            env=env, timeout=120,
        )
        missing_rc, missing_err = p.returncode, (p.stderr or p.stdout).strip()
    finally:
        quarantine.rename(ENGINE)
    assert missing_rc != 0, missing_err
    assert "Go 引擎" in missing_err or "找不到" in missing_err, missing_err

    # --replace-engine python → 成功，报告可证
    p = subprocess.run(
        [sys.executable, "-m", "fixtext_pipeline", "run",
         "--epub", str(SMALL_EPUB), "--workdir", str(root / "py"),
         "--rules-before", str(RULES_DIR / "before.json"),
         "--rules-after", str(RULES_DIR / "after.json"),
         "--replace-engine", "python", "--json"],
        capture_output=True, text=True, cwd=str(PIPELINE_ROOT),
        env=env, timeout=600,
    )
    assert p.returncode == 0, p.stderr[-800:]
    # stdout 前段是各阶段日志（含单引号 dict），报告 JSON 从行首 "{\n" 开始，其后还有收尾输出
    idx = p.stdout.rfind("\n{\n")
    assert idx >= 0, p.stdout[-500:]
    report, _ = json.JSONDecoder().raw_decode(p.stdout[idx + 1:])
    # 引擎字段在 stages.replace.report（阶段汇总的内层报告）里
    py_engine_field = report.get("stages", {}).get("replace", {}).get("report", {}).get("engine")
    assert py_engine_field == "python", py_engine_field

    # doctor：python 模式下缺 Go 引擎只提示不算问题
    # 注：bin/ 里同时有 linux 与 windows 两个二进制（基线 discover_engine 的回落序），
    # 要验证「缺引擎仅提示」须把两个都隔离；词库参数也要传，否则词库缺失会算问题。
    engine_win = ENGINE.with_name("replace_by_go-windows-amd64.exe")
    quarantine_win = quarantine.with_name(quarantine.name + ".win")
    ENGINE.rename(quarantine)
    engine_win.rename(quarantine_win)
    try:
        env2 = dict(env)
        env2["FIXTEXT_ENGINE"] = "python"
        p2 = subprocess.run(
            [sys.executable, "-m", "fixtext_pipeline", "doctor",
             "--rules-before", str(RULES_DIR / "before.json"),
             "--rules-after", str(RULES_DIR / "after.json")],
            capture_output=True, text=True, cwd=str(PIPELINE_ROOT),
            env=env2, timeout=120,
        )
        doctor_py = (p2.stdout + p2.stderr)
    finally:
        quarantine_win.rename(engine_win)
        quarantine.rename(ENGINE)

    ev["S6_cli"] = dict(
        missing_engine_exit_code=missing_rc,
        missing_engine_message=missing_err[:300],
        python_run_exit_code=p.returncode,
        python_report_engine=py_engine_field,
        doctor_python_mode_says_go_missing_ok=("仅作提示" in doctor_py),
    )
    assert ev["S6_cli"]["doctor_python_mode_says_go_missing_ok"], doctor_py
    print(f"[S6] PASS  缺引擎 rc={missing_rc}（明确报错）；--replace-engine python rc=0 "
          f"报告 engine=python；doctor 对 python 模式提示不算问题", flush=True)


# --------------------------------------------------------------------------- #
# S7：性能对照
# --------------------------------------------------------------------------- #

def s7_performance(ev: dict, s1: dict | None = None) -> None:
    if s1 is None:  # 分段续跑时从 evidence 恢复 S1 结果
        s1 = ev["S1_full_equivalence"]
    py = s1["python"]
    go = s1["go"]
    ev["S7_performance"] = dict(
        python_replace_s=py["replace_elapsed_s"],
        python_mbps=py["mbps"],
        go_replace_s=go["replace_elapsed_s"],
        go_mbps=go["mbps"],
        schedule_baseline=dict(mbps=GO_BASELINE_MBPS, max_book_s=GO_BASELINE_MAX_BOOK_S,
                               note="排期 §3.1 的 Go 基准（对照口径，非本卡实测）"),
        python_vs_go=round(py["replace_elapsed_s"] / max(go["replace_elapsed_s"], 1e-9), 1),
    )
    print(f"[S7] Python 引擎 {py['mbps']} MB/s（{py['replace_elapsed_s']}s / "
          f"{s1['bytes_in']/1e6:.1f}MB）vs Go {go['mbps']} MB/s；"
          f"排期基准 {GO_BASELINE_MBPS} MB/s", flush=True)


SCENARIOS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")


def main() -> int:
    from PySide6.QtWidgets import QApplication

    # 分段续跑（t33 范式）：evidence 文件即状态文件。
    # 显式传场景名（如 `accept_t42.py S1 S2`）只跑指定段并把结果合并进 evidence；
    # 不带参数 = 全量跑（7 段全部执行后才能 ALL PASS）。
    wanted = [a.upper() for a in sys.argv[1:] if a.upper() in SCENARIOS]
    if not wanted:
        wanted = list(SCENARIOS)
    evid_path = EVID / "t42_evidence.json"
    ev: dict = {"corpus": {
        "full": "炮火弧线（EPUB，788 章 / 约 314 万字符）",
        "baseline": "T0.4 回归基线集 15 语料（304,256 条规则 × 2 趟）",
    }}
    if wanted != list(SCENARIOS) and evid_path.exists():
        prev = json.loads(evid_path.read_text(encoding="utf-8"))
        ev.update({k: v for k, v in prev.items() if k not in ("result", "corpus")})

    QApplication.instance() or QApplication([])   # S3/S4 弹窗必须先有离屏 app
    EVID.mkdir(parents=True, exist_ok=True)
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)

    def run_s(name: str) -> None:
        if name == "S1":
            s1_full_equivalence(ev)
        elif name == "S2":
            s2_baseline_equivalence(ev)
        elif name == "S3":
            s3_fallback_accept(
                ev, go_restored_sha=ev["S1_full_equivalence"]["restored_sha_go"])
        elif name == "S4":
            s4_fallback_decline(ev)
        elif name == "S5":
            s5_engine_switch(ev)
        elif name == "S6":
            s6_cli(ev)
        elif name == "S7":
            s7_performance(ev)

    try:
        for name in wanted:
            print(f"=== {name} start ===", flush=True)
            run_s(name)
            _flush(ev, evid_path)
        ev["executed"] = sorted(set(ev.get("executed", [])) | set(wanted))
        _flush(ev, evid_path)
        if set(ev["executed"]) >= set(SCENARIOS):
            ev["result"] = "ALL PASS"
            _flush(ev, evid_path)
    finally:
        _flush(ev, evid_path)
        print(f"evidence -> {evid_path}", flush=True)

    if ev.get("result") != "ALL PASS":
        print(f"NOT COMPLETE (executed: {ev.get('executed', [])})", flush=True)
        return 1
    print("ALL PASS", flush=True)
    return 0


def _flush(ev: dict, path) -> None:
    path.write_text(json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
