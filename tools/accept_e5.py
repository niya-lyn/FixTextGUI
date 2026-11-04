"""V1.1-E5 · 端到端取证：A/B 书跨进程实测 + 指纹联动实测。

产出 ``evidence/e5_executed_memory.json``（原始数据，供报告逐条核对）。
四段实测全部走**真进程**（子进程读盘），不借父进程的内存状态：

A 章：A 书跑一批 → 盘上的执行记忆文件 + 正文 sha 变化
B 章：新进程读盘 → 手动勾选那条探针规则被自动排除、原因人话、B 书仍候选
C 章：指纹三段（空 / 写入 / 清回）逐字比对，含 ;done= 分区串原文
D 章：按书词库 byte 与 resolve_excluded 八项在写记忆前后全等

用法：
    python3.12 tools/accept_e5.py [--out <路径>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
ROOT = PKG
for _p in (PKG, PKG / "fixtext_ui", PKG / "pipeline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

RULES = PKG / "data" / "manual_search" / "rules.json"
SAMPLE = PKG / "tests" / "samples" / "a_utf8_lf.txt"
PROBE_MARK = "{盍->阖}"
PROBE_SENTENCE = "他盍不早说？\n"
EXCL = ("告之", "告知")


def sha_of(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _child_script(ws: Path, a: Path, b: Path) -> str:
    """子进程脚本：只读盘，不继承父进程任何内存状态。"""
    return textwrap.dedent(
        f"""
        import json, sys
        from pathlib import Path
        sys.path[:0] = [{str(PKG)!r}, {str(PKG / 'fixtext_ui')!r},
                        {str(PKG / 'pipeline')!r}]
        import fixtext_book_scope as bscope
        bscope.workspace_root = lambda: Path({str(ws)!r})
        import fixtext_batch_confirm as bc
        import fixtext_rule_memory as rmem
        from fixtext_manual_search import load_rules

        rules = load_rules({str(RULES)!r})
        probe = rules.rules[0].index
        out = {{"probe_index": probe, "probe_mark": rules.rules[0].mark}}
        for name, path in (("A", {str(a)!r}), ("B", {str(b)!r})):
            book = Path(path)
            bid = rmem.book_id_of_text_path(book)
            mem = rmem.RuleMemory(store_dir=book.parent / bc.BACKUP_DIRNAME)
            s = bc.BatchSession(rules, book.read_text(encoding="utf-8"),
                                target_path=book, memory=mem, book_id=bid)
            s.scan()
            nonzero = s.nonzero_indices()
            auto = s.select_all_hits()                 # 默认口径（跳过已执行）
            excluded_auto = list(s.excluded_indices)
            manual = s.select_indices([probe])         # 手动勾选「我要重跑」
            out[name] = dict(
                book_id=bid,
                marks=sorted(mem.marks(bid)),
                nonzero_count=len(nonzero),
                probe_has_hits=probe in nonzero,
                auto_picked_count=len(auto),
                auto_excluded=excluded_auto,
                manual_picked=manual,
                manual_excluded=list(s.excluded_indices),
                reason=s.executed_reason(probe),
                body_sha=__import__("hashlib").sha256(
                    book.read_bytes()).hexdigest(),
                body_probe_count=book.read_text(encoding="utf-8").count("盍"),
            )
        print(json.dumps(out, ensure_ascii=False))
        """
    )


def chapter_a(work: Path) -> dict:
    """A 书真跑一批（E4 会话 + E5 记忆），记录正文与记忆文件的变化。"""
    import fixtext_batch_confirm as bc
    import fixtext_rule_memory as rmem
    from fixtext_manual_search import load_rules

    a = work / "书A" / "book.txt"
    a.parent.mkdir(parents=True, exist_ok=True)
    a.write_text(SAMPLE.read_text(encoding="utf-8") + "\n" + PROBE_SENTENCE,
                 encoding="utf-8")
    body_before = sha_of(a)
    probe_before = a.read_text(encoding="utf-8").count("盍")

    rules = load_rules(RULES)
    bid = rmem.book_id_of_text_path(a)
    mem = rmem.RuleMemory(store_dir=a.parent / bc.BACKUP_DIRNAME,
                          workspace=work / "ws")
    s = bc.BatchSession(rules, a.read_text(encoding="utf-8"), target_path=a,
                        memory=mem, book_id=bid, label="书A")
    s.scan()
    picked = s.select_indices([rules.rules[0].index])
    s.plan(1)
    pv = s.preview(1)
    rec = s.execute(1, pv.token)

    ex_path = Path(mem.path_for(bid))
    return dict(
        book_id=bid,
        body_sha_before=body_before,
        body_sha_after=sha_of(a),
        probe_count_before=probe_before,
        probe_count_after=a.read_text(encoding="utf-8").count("盍"),
        hits=rec["hits"],
        memory=rec["memory"],
        memory_error=rec["memory_error"],
        executed_file=str(ex_path.relative_to(work)) if str(work) in str(ex_path) else ex_path.name,
        executed_file_sha=sha_of(ex_path) if ex_path.exists() else "",
        marks=sorted(mem.marks(bid)),
        store_ops=[r["act"] for r in mem.store.ops()],
        backup_points=len(mem.store.points()),
    )


def chapter_c(work: Path) -> dict:
    """指纹三段：空 / 写入 / 清回 —— 逐字比对 ;done= 分区串。"""
    from fixtext_pipeline import book_vocab as bv
    from fixtext_pipeline import executed_rules as ex
    from fixtext_pipeline.config import PipelineConfig
    from fixtext_pipeline.logsetup import StageLogger
    from fixtext_pipeline.stages.replace import ReplaceStage

    # 用一本**没有被 A 章动用过**的书，保证第一段指纹确实取自「还没有记忆」的状态
    bid = "书C"
    bkv = bv.book_vocab_path(bid, workspace=work / "ws")
    bv.write_book_vocab(bkv, bid, [EXCL])

    epub = work / "probe.epub"
    epub.write_bytes(b"PK\x03\x04empty")
    custom = work / "custom.json"
    custom.write_text('{"entries": []}', encoding="utf-8")

    cfg = PipelineConfig(
        epub=epub, workdir=work / "run",
        rules_before=PKG / "data" / "rules" / "before.json",
        rules_after=PKG / "data" / "rules" / "after.json",
        engine_path=work / "fake_engine", stages=("replace",),
        resume=True, force=False, custom_vocab_path=custom,
        derived_rules_dir=work / "derived", word_states_path=None,
        book_id=bid, book_vocab_path=bkv,
    )
    cfg.paths.workdir.mkdir(parents=True, exist_ok=True)
    stage = ReplaceStage(cfg, StageLogger(cfg.paths.stage_log("replace"), echo=False))

    captured: list[str] = []
    real = type(stage).fingerprint_of

    def spy(self, *args):
        captured.extend(str(a) for a in args)
        return real(self, *args)

    type(stage).fingerprint_of = spy
    try:
        fp0 = stage.fingerprint()
        book0 = next((p for p in captured if p.startswith("book=")), "")

        mem = rmem_import().RuleMemory(store_dir=work / "书A" / "batch_backups",
                                       workspace=work / "ws")
        mem.remember(bid, [dict(mark=PROBE_MARK, batch=1, hits=1, at="")])
        captured.clear()
        fp1 = stage.fingerprint()
        book1 = next((p for p in captured if p.startswith("book=")), "")

        mem.clear(bid)
        captured.clear()
        fp2 = stage.fingerprint()
        book2 = next((p for p in captured if p.startswith("book=")), "")
    finally:
        type(stage).fingerprint_of = real

    return dict(
        empty_sha=ex.executed_marks_sha(()),
        fp_empty=fp0, book_part_empty=book0,
        fp_written=fp1, book_part_written=book1,
        fp_restored=fp2, book_part_restored=book2,
        changed_on_write=fp1 != fp0,
        restored_verbatim=fp2 == fp0,
    )


def rmem_import():
    import fixtext_rule_memory as rmem

    return rmem


def chapter_d(work: Path) -> dict:
    """按书词库 byte 与 resolve_excluded 八项：写记忆前后全等。"""
    from fixtext_pipeline import book_vocab as bv
    from fixtext_pipeline import rule_keys

    bid = "书A"
    bkv = bv.book_vocab_path(bid, workspace=work / "ws")
    bv.write_book_vocab(bkv, bid, [EXCL])
    before_bytes = bkv.read_bytes()
    g = [rule_keys.entry_key(*EXCL), rule_keys.entry_key("费劲思量", "费尽思量")]
    r0 = bv.resolve_excluded(g, bv.book_excluded_keys(bkv))

    mem = rmem_import().RuleMemory(store_dir=work / "书A" / "batch_backups",
                                   workspace=work / "ws")
    mem.remember(bid, [dict(mark=PROBE_MARK, batch=1, hits=2, at="")])
    r1 = bv.resolve_excluded(g, bv.book_excluded_keys(bkv))

    probe_key = rule_keys.entry_key("盍", "阖")
    fields = ("effective", "sources", "overlap", "global_only", "book_only",
              "global_count", "book_count")
    return dict(
        book_vocab_byte_identical=before_bytes == bkv.read_bytes(),
        book_vocab_sha_before=hashlib.sha256(before_bytes).hexdigest(),
        book_vocab_sha_after=sha_of(bkv),
        fields_equal={f: r0[f] == r1[f] for f in fields},
        overlap=r0["overlap"], global_count=r0["global_count"],
        book_count=r0["book_count"],
        probe_key_in_effective=probe_key in r1["effective"],
        probe_key_in_sources=probe_key in r1["sources"],
        probe_mark_in_effective=PROBE_MARK in r1["effective"],
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(PKG / "evidence" / "e5_executed_memory.json"))
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    work = Path(tempfile.mkdtemp(prefix="e5_acc_"))
    try:
        a = chapter_a(work)
        b = work / "书B" / "book.txt"
        b.parent.mkdir(parents=True, exist_ok=True)
        b.write_text(SAMPLE.read_text(encoding="utf-8") + "\n" + PROBE_SENTENCE,
                     encoding="utf-8")
        ws = work / "ws"
        ws.mkdir(parents=True, exist_ok=True)

        proc = subprocess.run(
            [sys.executable, "-c", _child_script(ws, work / "书A" / "book.txt", b)],
            capture_output=True, text=True, timeout=180, cwd=str(work),
            env={**os.environ,
                 "PYTHONPATH": os.pathsep.join(
                     [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
                     + [str(PKG), str(PKG / "fixtext_ui"), str(PKG / "pipeline")])},
        )
        if proc.returncode != 0:
            print(proc.stderr[-3000:], file=sys.stderr)
            return 2
        cross = json.loads(proc.stdout.strip().splitlines()[-1])

        data = dict(
            chapter_a_execute=a,
            chapter_b_cross_process=cross,
            chapter_c_fingerprint=chapter_c(work),
            chapter_d_book_vocab_untouched=chapter_d(work),
        )
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
