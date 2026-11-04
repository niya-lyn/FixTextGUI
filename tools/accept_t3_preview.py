"""V1.1-D3 验收：预览三组数字、逐条取消、预演对账（临时副本真写入）。

四个场景，每个都给出可复现的实测记录：

A 组数字自证：同一份表，预览数 / 预演实测数 / 真实库前后指纹三项并排；
B 取消证明：取消一条后该条不在任何组，预演实测条数相应减少；
C 大表：1000+ 行，量出预览耗时与分批声明（证明索引改造后预览不是十几秒）；
D 反证：预览数字若被篡改，对账必须报不一致（否则这套核对是空转）。

用法：python tools/accept_t3_preview.py
输出：evidence/d3/accept_t3_report.md + 控制台逐行记录
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
for p in (PKG, PKG / "fixtext_ui"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fixtext_vocab import CustomVocab, VocabStore                        # noqa: E402
from fixtext_vocab_import.batching import BatchPolicy                    # noqa: E402
from fixtext_vocab_import.parse import parse_text                        # noqa: E402
from fixtext_vocab_preview.groups import (GROUP_CONFLICT, GROUP_NEW,     # noqa: E402
                                          GROUP_REJECT, preview_from_sheet)
from fixtext_vocab_preview.rehearsal import rehearse                     # noqa: E402

OUT = PKG / "evidence" / "d3"
TABLE = "错词,正确写法\n乙乙,乙\n甲的异体,甲\n,空的\n重复,值一\n重复,值二\n丙丙,丙\n"


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else ""


def new_store(tmp: Path, seed=(("甲的异体", "甲"),)):
    real = tmp / "custom_vocab.json"
    vocab = CustomVocab(real)
    for w, v in seed:
        vocab.add(word=w, value=v, typ="错词校正")
    return real, VocabStore(custom_path=real, work_dir=tmp / "rules", snap_dir=tmp / "snap")


def table_rows(model) -> str:
    lines = ["| 行号 | 组 | 错词 | 正确写法 | 说明 |", "| --- | --- | --- | --- | --- |"]
    for it in model.effective():
        lines.append(f"| {it.line_no} | {it.group} | {it.word or '—'} | "
                     f"{it.value or '—'} | {it.label()} |")
    return "\n".join(lines)


def diff_table(res) -> str:
    lines = ["| 项目 | 预览数字 | 预演实测数字 | 判定 |", "| --- | --- | --- | --- |"]
    for name, preview, measured, verdict in res.diff_columns():
        lines.append(f"| {name} | {preview} | {measured} | {verdict} |")
    return "\n".join(lines)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    log: list[str] = []
    ok = True

    def say(line: str = "") -> None:
        print(line)
        log.append(line)

    # ---- A：三组数字 + 预演对账 ----
    say("## A 三组数字与预演对账")
    with tempfile.TemporaryDirectory(prefix="t3_a_") as td:
        tmp = Path(td)
        real, store = new_store(tmp)
        before = sha(real)
        model = preview_from_sheet(parse_text(TABLE), store)
        counts = model.counts()
        say(f"预览：新增 {counts[GROUP_NEW]} / 冲突 {counts[GROUP_CONFLICT]} / "
            f"格式不合格 {counts[GROUP_REJECT]}；三组守恒 {model.conserved()}")
        say(f"分批声明：{model.batch_note()}")
        res = rehearse(model)
        say("")
        say(diff_table(res))
        say("")
        say(f"真实词库指纹 前 {before[:16]}… / 后 {sha(real)[:16]}…；未改动 {res.real_untouched}")
        ok &= res.identical and res.real_untouched
        say("")
        say("分组明细：")
        say(table_rows(model))
        say("")
        kept = (f"A1 结果：{'PASS' if res.identical and res.real_untouched else 'FAIL'}")

    # ---- B：逐条取消 ----
    say("## B 逐条取消（取消后不进任何一组）")
    with tempfile.TemporaryDirectory(prefix="t3_b_") as td:
        tmp = Path(td)
        real, store = new_store(tmp)
        model = preview_from_sheet(parse_text(TABLE), store)
        base = rehearse(model)
        target = [it.line_no for it in model.effective(GROUP_NEW) if it.word == "丙丙"][0]
        model.cancel(target)
        in_groups = {g: [i.line_no for i in model.effective(g)] for g in
                     (GROUP_NEW, GROUP_CONFLICT, GROUP_REJECT)}
        after = rehearse(model)
        say(f"取消行 {target}（丙丙）。")
        say(f"三组剩余行号：{in_groups}")
        say(f"该条出现在任何一组里：{any(target in v for v in in_groups.values())}")
        say(f"预演写入条数：取消前 {base.measured_new} → 取消后 {after.measured_new}"
            f"（少 {base.measured_new - after.measured_new}）")
        say(f"取消后对账仍一致：{after.identical}；真实库未改动：{after.real_untouched}")
        ok &= (not any(target in v for v in in_groups.values())
               and after.measured_new == base.measured_new - 1 and after.identical)
        b_ok = not any(target in v for v in in_groups.values()) and after.identical
        say(f"B1 结果：{'PASS' if b_ok else 'FAIL'}")

    # ---- C：大表性能与分批 ----
    say("## C 大表（1500 行）：预览耗时与分批声明")
    with tempfile.TemporaryDirectory(prefix="t3_c_") as td:
        tmp = Path(td)
        real, store = new_store(tmp)
        rows = "错词,正确写法\n" + "".join(f"新词{i},新写法{i}\n" for i in range(1, 1501))
        rows += "甲的异体,甲\n" + "重复词,重复值\n重复词,另一个值\n"
        t0 = time.perf_counter()
        model = preview_from_sheet(parse_text(rows), store)
        build_ms = (time.perf_counter() - t0) * 1000
        c = model.counts()
        say(f"表 1503 行 → 新增 {c[GROUP_NEW]} / 冲突 {c[GROUP_CONFLICT]} / "
            f"格式不合格 {c[GROUP_REJECT]}；预览构建 {build_ms:.0f} ms")
        say(f"分批：{model.batch_note()}（batch_count={model.batch_count()}）")
        ok &= build_ms < 3000 and model.conserved()
        say(f"C1 结果：{'PASS' if build_ms < 3000 and model.conserved() else 'FAIL'}")

    # ---- D：反证（篡改预览数字必须被判出来）----
    say("## D 反证：篡改预览数字后对账必须报不一致")
    with tempfile.TemporaryDirectory(prefix="t3_d_") as td:
        tmp = Path(td)
        real, store = new_store(tmp)
        model = preview_from_sheet(parse_text(TABLE), store)
        snapshot = dict(model.counts())
        snapshot[GROUP_NEW] += 1
        res = rehearse(model, preview_snapshot=snapshot)
        say(f"把预览的「新增」人为 +1 后：identical={res.identical}，"
            f"新增一列判定={res.diff_columns()[0][3]}")
        ok &= not res.identical
        say(f"D1 结果：{'PASS' if not res.identical else 'FAIL'}")

    say("")
    say(f"总判定：{'PASS' if ok else 'FAIL'}")

    (OUT / "accept_t3_report.md").write_text(
        "# V1.1-D3 验收记录（预览与查重分组）\n\n"
        + "\n".join(log) + "\n", encoding="utf-8")
    (OUT / "accept_t3_console.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
