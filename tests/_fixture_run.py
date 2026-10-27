"""M2-T2.10 测试夹具：在临时目录里造一个**真实结构**的运行目录。

不是编造数据：引号报告与正文来自 `samples/fixture_quote_report.json` /
`samples/fixture_quote_lines.txt`，那份报告是《炮火弧线》真实跑出来的
108 条引号事件（与 `error_count` 一致），正文只裁剪到事件所在行以控制仓库体积。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
SAMPLES = Path(__file__).resolve().parent / "samples"
BASE_SHA = "717fdfcee76fe3ee74d9a8bff20afbc84e7150bcbf5ee1a5b033a01739641dc2"


def build_run(root: Path, *, name: str = "run-1", hits: int = 5100,
              sha: str = BASE_SHA, title: str = "炮火弧线") -> Path:
    """在 ``root`` 下造一个运行目录，返回它的路径。"""
    run = Path(root) / name
    (run / "report").mkdir(parents=True, exist_ok=True)
    (run / "03_replace" / "after").mkdir(parents=True, exist_ok=True)
    (run / "03_replace" / "before").mkdir(parents=True, exist_ok=True)
    (run / "04_quote").mkdir(parents=True, exist_ok=True)

    body = (SAMPLES / "fixture_quote_lines.txt").read_text(encoding="utf-8")
    after = run / "03_replace" / "after" / "fixture_book.txt"
    before = run / "03_replace" / "before" / "fixture_book.txt"
    after.write_text(body, encoding="utf-8")
    before.write_text(body, encoding="utf-8")

    report = json.loads((SAMPLES / "fixture_quote_report.json").read_text(encoding="utf-8"))
    report["file"] = str(after)
    (run / "04_quote" / "fixture_book.report.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8")
    (run / "04_quote" / "quote_summary.json").write_text(json.dumps(dict(
        checked_file=str(after), chars=len(body),
        error_count=int(report.get("errCount") or 0),
        #: 只留前 20 条：真实现场的坑，检查页必须不依赖它
        first_errors=[dict(line=e.get("line"), msg=e.get("msg"))
                      for e in (report.get("events") or [])[:20]],
    ), ensure_ascii=False), encoding="utf-8")

    (run / "report" / "ui_run_summary.json").write_text(json.dumps(dict(
        book="fixture_book", title=title, workdir=str(run),
        started_at="2026-10-27T23:34:00", hits=hits,
        quote_errors=int(report.get("errCount") or 0),
        chapters=788, restored_sha256=sha,
        artifacts=dict(
            after_text=str(after), before_text=str(before),
            checked_file=str(after), ledger="", restored_epub="",
        ),
    ), ensure_ascii=False, indent=2), encoding="utf-8")
    return run


def cleanup(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)
