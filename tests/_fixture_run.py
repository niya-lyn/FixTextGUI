"""M2-T2.10 测试夹具：在临时目录里造一个**真实结构**的运行目录。

不是编造数据：引号报告与正文来自 `samples/fixture_quote_report.json` /
`samples/fixture_quote_lines.txt`——同一份报告与正文由
`tools/make_fixture_meta.py` 在公版样本上**真实跑一次**导出（见
`tests/_public_fixture.py` 的说明）。

M5-OS.1 的改造口径（三处）
-------------------------
① **正文与报告换成公版**：旧样本是盗版站来源的网文全文，这份"裁剪正文"
   里每一行都是那本书的原句，必须一并换掉；
② **数字不再写死**：`chapters` / `hits` / 成品指纹一律取自
   `samples/fixture_run_meta.json`（真实运行记录），并允许调用方显式覆盖
   （历史页用例要造两条不同的记录来区分）；
③ **书名中性**：默认书名不再借用任何版权作品的名字。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
SAMPLES = Path(__file__).resolve().parent / "samples"

import sys

if str(SAMPLES.parent) not in sys.path:  # 让 _public_fixture 可导入
    sys.path.insert(0, str(SAMPLES.parent))

import _public_fixture as PF  # noqa: E402

#: 旧版把成品指纹 / 命中数 / 书名写死在这里；现在从 fixture 的真实运行记录读。
BASE_SHA = PF.restored_sha256()
BASE_HITS = PF.hits()
BASE_TITLE = PF.TITLE


def build_run(root: Path, *, name: str = "run-1", hits: int | None = None,
              sha: str | None = None, title: str | None = None,
              chapters: int | None = None) -> Path:
    """在 ``root`` 下造一个运行目录，返回它的路径。

    默认值全部来自 fixture 的真实运行记录；显式传参用于造「另一条记录」。
    """
    hits = PF.hits() if hits is None else hits
    sha = BASE_SHA if sha is None else sha
    title = PF.TITLE if title is None else title
    chapters = PF.chapters() if chapters is None else chapters

    run = Path(root) / name
    (run / "report").mkdir(parents=True, exist_ok=True)
    (run / "03_replace" / "after").mkdir(parents=True, exist_ok=True)
    (run / "03_replace" / "before").mkdir(parents=True, exist_ok=True)
    (run / "04_quote").mkdir(parents=True, exist_ok=True)

    body = PF.QUOTE_LINES.read_text(encoding="utf-8")
    after = run / "03_replace" / "after" / "fixture_book.txt"
    before = run / "03_replace" / "before" / "fixture_book.txt"
    after.write_text(body, encoding="utf-8")
    before.write_text(body, encoding="utf-8")

    report = json.loads(PF.QUOTE_REPORT.read_text(encoding="utf-8"))
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
        chapters=chapters, restored_sha256=sha,
        artifacts=dict(
            after_text=str(after), before_text=str(before),
            checked_file=str(after), ledger="", restored_epub="",
        ),
    ), ensure_ascii=False, indent=2), encoding="utf-8")
    return run


def cleanup(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)
