#!/usr/bin/env python3
"""M5-OS.1 验收 · 公版 fixture 上的真实端到端（导入 → 一键校正 → 导出）。

全部走真实链路，不做桩：
  1. 导入公版 fixture（fixtext_import.import_book）→ 得到可还原账本
  2. 一键校正（fixtext_worker.CorrectionJob，六阶段真跑）
  3. 导出（fixtext_export.export_book，EPUB + TXT 两种）
并核对：原书字节未被改动、导出成品与本次运行自己还原的成品逐一比对。

产出：evidence/os1_accept.json

运行::

    PYTHONPATH=<site-packages> python3.12 tools/accept_os1.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for p in (str(PKG), str(PKG / "fixtext_ui"), str(PKG / "fixtext_import"),
          str(PKG / "pipeline"), str(PKG / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _public_fixture as PF  # noqa: E402
import fixtext_import as fi  # noqa: E402
import fixtext_export as fx  # noqa: E402
from fixtext_pipeline.engine_selector import select_engine  # noqa: E402
from fixtext_worker import CorrectionJob  # noqa: E402

EVID = PKG / "evidence"
ENGINE_BIN = PKG / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src" / "bin"
RULES = PKG / "data" / "rules"


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    assert PF.available(), PF.missing_reason()
    work = Path(tempfile.mkdtemp(prefix="os1_accept_"))
    report: dict = {"card": "M5-OS.1", "steps": {}}
    try:
        # ---- 1. 导入 ------------------------------------------------------
        src_sha_before = sha(PF.EPUB)
        t0 = time.monotonic()
        imp = fi.import_book(PF.EPUB, work / "ws")
        report["steps"]["import"] = dict(
            ok=True, elapsed_s=round(time.monotonic() - t0, 2),
            book_id=imp.book_id, epub_mode=imp.epub_mode,
            source_sha256_before=imp.source_sha256_before,
            source_sha256_after=imp.source_sha256_after,
            text_path=str(imp.text_path),
            text_chars=len(Path(imp.text_path).read_text("utf-8")),
            ledger=str(imp.ledger_path or ""),
            chapter_preview=dict(
                n=len(fi.chapter_preview(PF.EPUB).chapters),
                order_ok=fi.chapter_preview(PF.EPUB).order_ok))
        assert sha(PF.EPUB) == src_sha_before, "导入改了原书字节"
        print(f"[1] 导入 OK：{imp.book_id} / {imp.epub_mode}")

        # ---- 2. 一键校正 ---------------------------------------------------
        engine = select_engine(ENGINE_BIN)
        assert engine and engine.is_file(), f"引擎不可用：{engine}"
        t0 = time.monotonic()
        job = CorrectionJob(
            epub=PF.EPUB, workdir=work / "run",
            rules_before=RULES / "before.json",
            rules_after=RULES / "after.json",
            engine_path=engine, pipeline_root=PKG / "pipeline",
            title=PF.TITLE)
        summary = job.run()
        report["steps"]["correct"] = dict(
            ok=True, elapsed_s=round(time.monotonic() - t0, 2),
            chapters=summary["chapters"], hits=summary["hits"],
            quote_errors=summary["quote_errors"],
            restored_sha256=summary["restored_sha256"],
            workdir=str(job.workdir))
        print(f"[2] 校正 OK：{summary['chapters']} 章 / 命中 {summary['hits']} / "
              f"引号问题 {summary['quote_errors']}")

        # ---- 3. 导出 -------------------------------------------------------
        run = Path(job.workdir)
        out_dir = work / "out"
        src = fx.resolve_source_from_run(run, None, PKG / "pipeline")
        t0 = time.monotonic()
        out_epub = fx.export_book(src, out_dir, fmt="epub",
                                  baseline_sha256=summary["restored_sha256"])
        out_txt = fx.export_book(src, out_dir, fmt="txt")
        epub_path = Path(out_epub.main_file)
        txt_path = Path(out_txt.main_file)
        report["steps"]["export"] = dict(
            ok=True, elapsed_s=round(time.monotonic() - t0, 2),
            epub=dict(path=epub_path.name, bytes=epub_path.stat().st_size,
                      sha256=out_epub.sha256,
                      equals_run_baseline=(out_epub.sha256 == summary["restored_sha256"])),
            txt=dict(path=txt_path.name, bytes=txt_path.stat().st_size,
                     sha256=out_txt.sha256, hits=out_txt.hits),
            can_restore_epub=src.can_restore_epub)
        print(f"[3] 导出 OK：EPUB {epub_path.stat().st_size:,} B / "
              f"TXT {txt_path.stat().st_size:,} B")

        # ---- 4. 原书未被改动 ------------------------------------------------
        report["steps"]["source_untouched"] = dict(
            ok=(sha(PF.EPUB) == src_sha_before), sha256=sha(PF.EPUB))
        report["passed"] = (
            report["steps"]["source_untouched"]["ok"]
            and report["steps"]["export"]["epub"]["equals_run_baseline"]
            and report["steps"]["correct"]["hits"] > 0
            and report["steps"]["correct"]["chapters"] == PF.chapters())
        print(f"[4] 原书未被改动：{report['steps']['source_untouched']['ok']}")
        print(f"\n总判定：{'PASS' if report['passed'] else 'FAIL'}")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    EVID.mkdir(parents=True, exist_ok=True)
    (EVID / "os1_accept.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
