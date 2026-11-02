#!/usr/bin/env python3
"""M5-OS.1 · 从公版 fixture 的**真实运行**导出测试用元数据与引号样本。

为什么不把这些数字写进测试里
----------------------------
仓库原先的测试样本是一本盗版站来源的网文全文（788 章 / 108 处引号问题 /
5100 命中）。换样本之后，任何"抄一个新的魔法数字"的做法都只是把旧毛病换
成新毛病：产品少跑一章、少报一处，测试也跟着抄少一个数，就再也发现不了。

所以这里做的是：**真的跑一次**（导入 → 合并 → 排版 → 替换 → 引号 → 书图 →
还原），把它自己产出的数字与正文落成 fixture 的元数据，测试再从这个文件
读期望值。断言于是变成"与本次运行自己的产物一致"，而不是"与某个记下来的
数字一致"。

产物
----
``tests/samples/fixture_run_meta.json``
    一次真实运行的章数 / spine 项数 / 命中数 / 引号问题数 / 成品指纹。
``tests/samples/fixture_quote_report.json``
    同一轮跑出来的引号报告（检查页用例的数据源）。
``tests/samples/fixture_quote_lines.txt``
    报告所指向的正文行，按原行号补空行落盘（只留被引用的那些行，
    仓库体积可控；行号与 ``char`` 偏移保持原样，读回来能对上）。

运行::

    PYTHONPATH=<site-packages> python3.12 tools/make_fixture_meta.py

语料出处：``tests/samples/book_public_domain.epub`` 由
``tools/build_fixture_epub.py`` 从 Project Gutenberg #51828《聊齋志異》
（公有领域）现场合成。
"""
from __future__ import annotations

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
          str(PKG / "fixtext_error_center"), str(PKG / "pipeline")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

EPUB = PKG / "tests" / "samples" / "book_public_domain.epub"
RULES = PKG / "data" / "rules"
SAMPLES = PKG / "tests" / "samples"
META_OUT = SAMPLES / "fixture_run_meta.json"
REPORT_OUT = SAMPLES / "fixture_quote_report.json"
LINES_OUT = SAMPLES / "fixture_quote_lines.txt"

#: 报告里 ``file`` 字段写什么——不写沙箱绝对路径，免得上游 lint 扫到 /home/
REPORT_FILE_LABEL = "tests/samples/fixture_quote_lines.txt"


def _pad_lines(source: Path, line_nos: set[int]) -> str:
    """按原行号补空行：只保留被引用的行，其余留空，行号不前移。"""
    top = max(line_nos)
    kept: dict[int, str] = {}
    with open(source, "r", encoding="utf-8", newline="") as fh:
        for i, raw in enumerate(fh, start=1):
            if i in line_nos:
                kept[i] = raw.rstrip("\r\n")
            if i >= top:
                break
    out = [kept.get(i, "") for i in range(1, top + 1)]
    return "\n".join(out) + "\n"


def main() -> int:
    from fixtext_worker import CorrectionJob

    if not EPUB.is_file():
        print(f"[FAIL] 缺少 fixture：{EPUB}")
        return 1

    work = Path(tempfile.mkdtemp(prefix="fixture_meta_"))
    try:
        job = CorrectionJob(
            epub=EPUB,
            workdir=work / "run",
            rules_before=RULES / "before.json",
            rules_after=RULES / "after.json",
            engine_path=(
                PKG / "pipeline" / "vendor" / "fixtext" / "engine" /
                "go_src" / "bin" / "replace_by_go-linux-amd64"),
            pipeline_root=PKG / "pipeline",
            title="聊齋志異（公有領域選篇）",
        )
        t0 = time.monotonic()
        summary = job.run()
        elapsed = round(time.monotonic() - t0, 2)

        run = Path(job.workdir)
        merge = json.loads((run / "01_merge" / "merge_report.json").read_text("utf-8"))
        replace = json.loads((run / "03_replace" / "replace_report.json").read_text("utf-8"))
        quote_sum = json.loads((run / "04_quote" / "quote_summary.json").read_text("utf-8"))
        rep_path = run / "04_quote" / Path(quote_sum["report_json"]).name
        quote_rep = json.loads(rep_path.read_text("utf-8"))

        events = quote_rep.get("events") or []
        err = int(quote_sum.get("error_count") or quote_rep.get("errCount") or 0)
        assert err == len(events) == int(quote_rep.get("errCount") or 0), (
            f"引号报告自相矛盾：summary={err} events={len(events)} "
            f"report.errCount={quote_rep.get('errCount')}")

        line_nos = {int(e["line"]) for e in events if e.get("line")}
        body = _pad_lines(Path(replace["after_path"]), line_nos)

        meta = dict(
            card="M5-OS.1",
            note=("由 tools/make_fixture_meta.py 在公版 fixture 上真实跑一次得到；"
                  "测试从这里读期望值，不抄数字"),
            fixture=EPUB.name,
            fixture_bytes=EPUB.stat().st_size,
            title=merge["title"],
            chapters=int(merge["chapters"]),
            spine_items=int(merge["spine_items"]),
            ncx_entries=int(merge["ncx_entries"]),
            hits=int(summary["hits"]),
            quote_errors=err,
            quote_events=len(events),
            restored_sha256=summary["restored_sha256"],
            replaced_chars_in=int(replace.get("chars_in") or 0),
            replaced_chars_out=int(replace.get("chars_out") or 0),
            rules=int(replace.get("rules") or 0),
            elapsed_s=elapsed,
            generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        META_OUT.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")

        quote_rep["file"] = REPORT_FILE_LABEL
        REPORT_OUT.write_text(json.dumps(quote_rep, ensure_ascii=False),
                              encoding="utf-8")
        LINES_OUT.write_text(body, encoding="utf-8")

        print(json.dumps(meta, ensure_ascii=False, indent=2))
        print(f"[OK] {META_OUT.relative_to(PKG)} / {REPORT_OUT.relative_to(PKG)} / "
              f"{LINES_OUT.relative_to(PKG)}（行数 {body.count(chr(10))}，"
              f"非空 {sum(1 for ln in body.splitlines() if ln.strip())}）")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
