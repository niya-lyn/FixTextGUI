"""M3-T3.7 验收：自定义词生效（词库→引擎桥）与查重清单收口。

全部判据取实测字节，不写"应该可以"：

  S1 正向      真实整本公版样本＋在第一章插入 3 处「萧衍」的语料，
               「我的词库」加一条「萧衍 → 萧彦」，跑**完整六阶段**校正
               （与界面同一条链路），导出纯文本，统计导出文件 sha256、
               「萧衍 / 萧彦」出现次数与命中数。
  S2 反向对照  同一份输入、同一个引擎，喂给**移除桥接**的代码（/tmp 里的
               基线副本，替换阶段直接读随包词库原件）——「萧衍」一个不少。
  S3 原件只读  跑完全部用例后，随包词库两份原件的 sha256 与开工前一致。
  S4 指纹      自定义词的替换值改一个字，替换阶段指纹必须变（否则断点恢复
               会把旧正文当新结果复用）。
  S5 查重清单  25 组冲突：界面全量渲染、按钮只剩「关闭」、点完文件 sha 不变。
  S6 执行位    /tmp 干净目录解压后，引擎文件仍带可执行位且能真跑。

运行：
    QT_QPA_PLATFORM=offscreen python3.12 tools/accept_t37.py
产出：evidence/accept_t37.json
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
EVID = PKG / "evidence"
RUNS = PKG.parent / "t37_runs"
BOOK = PF.EPUB
RULES = PKG / "data" / "rules"
WORDS = ("萧衍", "萧彦")
INSERT = "萧衍 起身，众人皆看萧衍，唯萧衍旧部尚在。"

for _p in (PKG, PKG / "fixtext_ui", PKG / "fixtext_import", PKG / "pipeline",
           PKG / "tests", HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from accept_env import env_dir, select_go_engine, tmp_root  # noqa: E402
import _public_fixture as PF  # noqa: E402  M5-OS.1：公版 fixture 唯一来源

BASELINE = env_dir("FIXTEXT_T37_BASELINE", tmp_root("m37_baseline")) or tmp_root("m37_baseline")
_ENGINE = select_go_engine(PKG)
ENGINE_REL = (
    _ENGINE.relative_to(PKG) if _ENGINE is not None
    else Path("pipeline/vendor/fixtext/engine/go_src/bin/__no_platform_engine__")
)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_corpus(dst: Path) -> tuple[Path, int]:
    """把真实整本电子书复制一份，只在第 1 章正文里插入一处「萧衍」句。

    其余字节原样复制——这不是"造一本书"，是给真实语料加一个自定义词要校的
    错词，好让"生效与否"在正文里可数。
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    inserted = 0
    with zipfile.ZipFile(BOOK) as src, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.endswith((".xhtml", ".html")):
                text = data.decode("utf-8")
                if inserted == 0 and "<body" in text:
                    text = text.replace("<body", f"<body", 1)
                    idx = text.find(">", text.find("<body")) + 1
                    text = text[:idx] + f"<p>{INSERT}</p>" + text[idx:]
                    inserted = 1
                data = text.encode("utf-8")
            out.writestr(info, data)
    return dst, inserted


def custom_vocab(path: Path, value: str = "萧彦") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(
        product="FixText", kind="custom_vocab", version=1,
        entries=[dict(id=1, word="萧衍", value=value, type="角色名")],
    ), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def run_pipeline(pkg: Path, epub: Path, run_dir: Path, vocab: Path,
                 derived: Path, title: str) -> dict:
    """跑完整六阶段（与界面 CorrectionJob 同一条链路）。

    用完把本函数临时插入的路径**全部摘掉**：反向对照会临时把基线副本的目录
    塞到 sys.path 最前面，留着会影响后面 S5 导入的是哪一份界面代码。
    """
    pre = set(sys.path)
    added = [a for a in (str(pkg / "fixtext_ui"), str(pkg / "fixtext_import"))
             if a not in pre]
    sys.path[:0] = added
    try:
        return _run_pipeline_inner(pkg, epub, run_dir, vocab, derived, title)
    finally:
        for a in added:
            while a in sys.path:
                sys.path.remove(a)
        for name in ("fixtext_worker", "plain_book", "fixtext_export",
                     "fixtext_pipeline", "vocab_module", "fixtext_vocab"):
            sys.modules.pop(name, None)


def _run_pipeline_inner(pkg: Path, epub: Path, run_dir: Path, vocab: Path,
                        derived: Path, title: str) -> dict:
    for name in list(sys.modules):
        if name.split(".")[0] in ("fixtext_worker", "plain_book", "fixtext_export"):
            sys.modules.pop(name, None)
    import importlib
    worker = importlib.import_module("fixtext_worker")
    kwargs = dict(
        epub=epub, workdir=run_dir, rules_before=pkg / "data/rules/before.json",
        rules_after=pkg / "data/rules/after.json", engine_path=pkg / ENGINE_REL,
        pipeline_root=pkg / "pipeline", title=title)
    # 基线副本没有桥接：它的执行器压根不接受这两个参数（正是"桥接缺失"的证据）
    import inspect
    if "custom_vocab_path" in inspect.signature(worker.CorrectionJob).parameters:
        kwargs.update(custom_vocab_path=vocab, derived_rules_dir=derived)
    job = worker.CorrectionJob(**kwargs)
    t0 = time.time()
    summary = job.run()
    return dict(summary, elapsed_s=round(time.time() - t0, 2), pkg=str(pkg))


def export_txt(pkg: Path, run_dir: Path, out_dir: Path) -> dict:
    pre = set(sys.path)
    added = [a for a in (str(pkg / "fixtext_ui"),) if a not in pre]
    sys.path[:0] = added
    try:
        return _export_txt_inner(pkg, run_dir, out_dir)
    finally:
        for a in added:
            while a in sys.path:
                sys.path.remove(a)
        for name in ("fixtext_export", "fixtext_pipeline"):
            sys.modules.pop(name, None)


def _export_txt_inner(pkg: Path, run_dir: Path, out_dir: Path) -> dict:
    import importlib
    fx = importlib.import_module("fixtext_export")
    src = fx.resolve_source_from_run(run_dir, None, pkg / "pipeline")
    outcome = fx.export_book(src, out_dir, fmt="txt", title="示例书稿")
    main = Path(outcome.main_file)
    text = main.read_text(encoding="utf-8")
    return dict(file=str(main), sha256=sha256_file(main),
                bytes=main.stat().st_size,
                chars=len(text),
                counts={w: text.count(w) for w in WORDS})


def stage_report(run_dir: Path) -> dict:
    p = run_dir / "03_replace" / "replace_report.json"
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# S1 正向
# ---------------------------------------------------------------------------

def s1_positive() -> dict:
    work = RUNS / "positive"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    epub, inserted = build_corpus(work / "paohuo_with_word.epub")
    vocab = custom_vocab(work / "custom_vocab.json")
    summary = run_pipeline(PKG, epub, work / "run", vocab, work / "derived", "示例书稿")
    rep = stage_report(work / "run")
    out = export_txt(PKG, work / "run", work / "out")
    before_text = Path(rep["before_path"]).read_text(encoding="utf-8")
    after_text = Path(rep["after_path"]).read_text(encoding="utf-8")
    derived = rep.get("derived_rules") or {}
    return dict(
        corpus=str(epub), corpus_sha256=sha256_file(epub),
        inserted_sentences=inserted,
        chapters=summary.get("chapters"), elapsed_s=summary.get("elapsed_s"),
        hits=summary.get("hits"),
        text_before_counts={w: before_text.count(w) for w in WORDS},
        text_after_counts={w: after_text.count(w) for w in WORDS},
        exported=out,
        exported_counts=out["counts"],
        derived_rules={k: derived.get(k) for k in (
            "compose_key", "base_rules", "custom_input", "custom_applied",
            "total_rules", "reused", "applied_words",
            "derived_before_sha256", "derived_after_sha256")},
        pass_=(
            out["counts"]["萧衍"] == 0
            and out["counts"]["萧彦"] == 3
            and before_text.count("萧衍") == 3
            and derived.get("custom_applied") == 1
        ),
    )


# ---------------------------------------------------------------------------
# S2 反向对照（同一输入、同一引擎、桥接缺失的代码）
# ---------------------------------------------------------------------------

def s2_negative() -> dict:
    if not (BASELINE / "pipeline" / "fixtext_pipeline").is_dir():
        return dict(skipped=f"缺少基线副本：{BASELINE}")
    work = RUNS / "negative"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    epub = RUNS / "positive" / "paohuo_with_word.epub"
    if not epub.exists():
        epub, _ = build_corpus(work / "paohuo_with_word.epub")
    vocab = custom_vocab(work / "custom_vocab.json")
    summary = run_pipeline(BASELINE, epub, work / "run", vocab, work / "derived", "示例书稿")
    rep = stage_report(work / "run")
    out = export_txt(BASELINE, work / "run", work / "out")
    after_text = Path(rep["after_path"]).read_text(encoding="utf-8")
    return dict(
        baseline_pkg=str(BASELINE),
        bridge_present=(BASELINE / "pipeline/fixtext_pipeline/vocab_bridge.py").exists(),
        chapters=summary.get("chapters"), elapsed_s=summary.get("elapsed_s"),
        hits=summary.get("hits"),
        text_after_counts={w: after_text.count(w) for w in WORDS},
        exported=out, exported_counts=out["counts"],
        derived_rules_present="derived_rules" in rep,
        pass_=(not (BASELINE / "pipeline/fixtext_pipeline/vocab_bridge.py").exists()
               and out["counts"]["萧衍"] == 3 and out["counts"]["萧彦"] == 0),
        note="同一语料、同一引擎；只是这份代码没有桥接，替换阶段直接读随包词库原件。",
    )


# ---------------------------------------------------------------------------
# S3 原件只读 / S4 指纹
# ---------------------------------------------------------------------------

def s3_rules_readonly(before_shas: dict) -> dict:
    after = {n: sha256_file(RULES / n) for n in ("before.json", "after.json")}
    return dict(before=before_shas, after=after,
                pass_=all(before_shas.get(k) == v for k, v in after.items()))


def s4_fingerprint() -> dict:
    work = RUNS / "fingerprint"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    epub, _ = build_corpus(work / "corpus.epub")
    vocab = custom_vocab(work / "custom_vocab.json", "萧彦")
    from fixtext_pipeline.config import PipelineConfig
    from fixtext_pipeline.logsetup import StageLogger
    from fixtext_pipeline.stages import STAGES
    from fixtext_pipeline.stages.replace import ReplaceStage

    cfg = PipelineConfig(epub=epub, workdir=work / "run",
                         rules_before=RULES / "before.json",
                         rules_after=RULES / "after.json",
                         engine_path=PKG / ENGINE_REL, replace_count=2,
                         layout_profile="html-safe",
                         stages=("merge", "layout", "replace"), resume=False,
                         force=False, custom_vocab_path=vocab,
                         derived_rules_dir=work / "derived")
    for key in ("merge", "layout", "replace"):
        cfg.stage_dir(key).mkdir(parents=True, exist_ok=True)
        logger = StageLogger(cfg.paths.stage_log(key), echo=False)
        try:
            STAGES[key](cfg, logger).run()
        finally:
            logger.close()
    stage = ReplaceStage(cfg, StageLogger(cfg.paths.stage_log("replace"), echo=False))
    fp1 = stage.fingerprint()
    custom_vocab(work / "custom_vocab.json", "萧彦二")
    fp2 = ReplaceStage(cfg, StageLogger(cfg.paths.stage_log("replace"), echo=False)).fingerprint()
    return dict(fp_before=fp1, fp_after_change=fp2, changed=fp1 != fp2, pass_=fp1 != fp2)


# ---------------------------------------------------------------------------
# S5 查重清单（真实界面点击）
# ---------------------------------------------------------------------------

def s5_dup_dialog() -> dict:
    import tempfile

    from PySide6.QtWidgets import QApplication, QDialog, QFrame, QPushButton
    import vocab_module as vm
    from fixtext_vocab import VocabStore

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="t37-dup-"))
    mod = vm.VocabModule()
    mod.store = VocabStore(custom_path=tmp / "custom_vocab.json")
    mod._page, mod.search = 0, ""
    mod.dict_, mod.tier = "custom", "custom"
    try:
        for i in range(25):
            mod.store.add_entry(word=f"词{i}", value=f"甲{i}", typ="错词校正")
            mod.store.add_entry(word=f"词{i}", value=f"乙{i}", typ="错词校正")
        mod._render_all()
        sha_before = sha256_file(mod.store.custom.path)
        groups = mod.open_dup()
        sha_after = sha256_file(mod.store.custom.path)
        dlg = getattr(mod, "_dup_modal", None)
        if dlg is None:
            dlgs = [w for w in app.topLevelWidgets()
                    if isinstance(w, QDialog) and w.windowTitle().startswith("查重清单")]
            dlg = dlgs[0]
        boxes = dlg.findChildren(QFrame, "DupGroup")
        buttons = [b.text() for b in dlg.findChildren(QPushButton)]
        shot = EVID / "t37_dup_dialog.png"
        try:
            dlg.grab().save(str(shot))
        except Exception:
            shot = None
        dlg.reject()
        # V1.1-EX.2R：清单由只读改为可逐条处理，每组自带处置动作；
        # 「打开清单不动文件」这条底线不变，仍以 sha 相等为证。
        actionable = buttons.count("保留这一条")
        return dict(total_groups=len(groups), rendered_groups=len(boxes),
                    view=mod._dup_view, buttons=buttons,
                    actionable_groups=actionable,
                    file_sha_before=sha_before, file_sha_after=sha_after,
                    file_untouched=sha_before == sha_after,
                    screenshot=str(shot) if shot else "",
                    pass_=(len(boxes) == len(groups) == 25
                           and sha_before == sha_after
                           and actionable == 25
                           and "我知道了" not in buttons
                           and "暂时不处理" not in buttons
                           and mod._dup_view.get("readonly") is False))
    finally:
        mod.close()


# ---------------------------------------------------------------------------
# S6 干净目录解压 + 执行位
# ---------------------------------------------------------------------------

def s6_exec_bit() -> dict:
    clean = tmp_root("t37_clean")
    shutil.rmtree(clean, ignore_errors=True)
    clean.mkdir(parents=True)
    archive = RUNS / "pkg_snapshot.zip"
    if not archive.exists():
        # 用 zip 命令行打包：它记录 Unix 权限位，unzip 解出来执行位还在
        import subprocess
        subprocess.run(["zip", "-qr", str(archive), ".", "-x",
                        ".git/*", "*__pycache__*", "runs/*", "evidence/*"],
                       cwd=PKG, check=True, timeout=600)
    import subprocess
    subprocess.run(["unzip", "-q", str(archive), "-d", str(clean)],
                   check=True, timeout=600)
    engine = clean / ENGINE_REL
    mode = oct(engine.stat().st_mode)[-3:] if engine.exists() else ""
    run = None
    if engine.exists():
        proc = subprocess.run([str(engine), "-h"], capture_output=True, text=True, timeout=60)
        run = dict(returncode=proc.returncode,
                   stdout_head=(proc.stdout or proc.stderr or "").strip().splitlines()[:2])
    return dict(dir=str(clean), engine_exists=engine.exists(), mode=mode,
                executable=os.access(engine, os.X_OK) if engine.exists() else False,
                dry_run=run,
                pass_=engine.exists() and os.access(engine, os.X_OK)
                and (run or {}).get("returncode") is not None)


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rules_before = {n: sha256_file(RULES / n) for n in ("before.json", "after.json")}

    print("[S1] 正向：真实整本 + 自定义词 萧衍→萧彦 ...", flush=True)
    s1 = s1_positive()
    print("     exported sha256 =", s1["exported"]["sha256"])
    print("     counts:", s1["exported_counts"], "hits:", s1["hits"], flush=True)

    print("[S2] 反向对照：同一语料喂给无桥接代码 ...", flush=True)
    s2 = s2_negative()
    print("     negative counts:", s2.get("exported_counts"), flush=True)

    print("[S3] 随包词库原件只读 ...", flush=True)
    s3 = s3_rules_readonly(rules_before)

    print("[S4] 指纹随自定义词变化 ...", flush=True)
    s4 = s4_fingerprint()

    print("[S5] 查重清单全量只读 ...", flush=True)
    s5 = s5_dup_dialog()

    print("[S6] 干净目录解压执行位 ...", flush=True)
    s6 = s6_exec_bit()

    report = dict(
        card="M3-T3.7", generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        total_elapsed_s=round(time.time() - t0, 2),
        s1_positive=s1, s2_negative=s2, s3_rules_readonly=s3,
        s4_fingerprint=s4, s5_dup_dialog=s5, s6_exec_bit=s6,
    )
    (EVID / "accept_t37.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = all([s1.get("pass_"), s2.get("pass_"), s3.get("pass_"),
              s4.get("pass_"), s5.get("pass_")])
    print("\n== 结果 ==")
    for k in ("s1_positive", "s2_negative", "s3_rules_readonly",
              "s4_fingerprint", "s5_dup_dialog"):
        print(f"{k:20s}", "PASS" if report[k].get("pass_") else "FAIL")
    print("s6_exec_bit          ", "PASS" if s6["pass_"] else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
