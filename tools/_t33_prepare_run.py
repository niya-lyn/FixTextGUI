"""M3-T3.3 预跑：走一次真实六阶段链路，落出带全量专有词清单的运行产物。

只做「取证」，不做断言——验收脚本 accept_t33.py 读这里跑出来的目录。
跑法：
    QT_QPA_PLATFORM=offscreen PYTHONPATH=<pkg>:<pkg>/fixtext_ui python3.12 tools/_t33_prepare_run.py
产出：runs/t33_real/<阶段目录>，并把运行摘要写成 evidence/t33_run_summary.json
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for p in (str(PKG), str(PKG / "fixtext_ui"), str(PKG / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from _public_fixture import EPUB  # noqa: E402  M5-OS.1：公版 fixture 唯一来源
PIPELINE_ROOT = PKG / "pipeline"
RULES_DIR = PKG / "data" / "rules"
RUNS_ROOT = PKG / "runs" / "t33_real"
EVID = PKG / "evidence"


def main() -> int:
    from fixtext_worker import CorrectionJob

    if RUNS_ROOT.exists():
        shutil.rmtree(RUNS_ROOT)
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    EVID.mkdir(parents=True, exist_ok=True)

    job = CorrectionJob(
        epub=EPUB,
        workdir=RUNS_ROOT / "work",
        rules_before=RULES_DIR / "before.json",
        rules_after=RULES_DIR / "after.json",
        engine_path=(PIPELINE_ROOT / "vendor" / "fixtext" / "engine" /
                     "go_src" / "bin" / "replace_by_go-linux-amd64"),
        pipeline_root=PIPELINE_ROOT,
        title="示例书稿",
    )
    t0 = time.monotonic()
    summary = job.run()
    elapsed = time.monotonic() - t0

    out = dict(
        elapsed_s=round(elapsed, 2),
        workdir=str(job.workdir),
        book_words=len(summary.get("book_words") or []),
        book_words_declared_total=summary.get("book_words_declared_total"),
        book_words_unique=summary.get("book_words_unique"),
        bookmap_entries=summary.get("bookmap_entries"),
        chapters=summary.get("chapters"),
        quote_errors=summary.get("quote_errors"),
        domains=summary.get("domains"),
        restored_sha256=summary.get("restored_sha256"),
    )
    (EVID / "t33_run_summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
