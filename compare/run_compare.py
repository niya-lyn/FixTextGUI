# -*- coding: utf-8 -*-
"""
T1.6 对照运行器：真实 PHP NoteParser vs Python 等价实现，逐输入三阶段对比。

用法（在解压后的包根目录执行）：
  python3 compare/run_compare.py \
      --src <FixText src 目录> \
      --fixtures <样例目录> \
      --corpus <语料目录（T0.4 基线集 corpus）> \
      [--out compare/report]

每输入产出：
  - PHP 侧（权威）：compare/php_note_harness.php 以子类探针调用真实 NoteParser，
    dump stage1（正则提取后）/ stage2（品牌闭包处理后）/ stage3（cleanMatches 后）。
  - Python 侧：py_note_parser.py 的同构三阶段。
  - 逐阶段 JSON 深比对（brand / ok / 异常信息 / 三阶段全部行），相异记 1 条 diff。
结果写 <out>/compare_report.json，并打印汇总。
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from py_note_parser import py_pipeline_report  # noqa: E402


def run_php_harness(src_dir, input_file, out_file, php_bin="php"):
    harness = HERE / "php_note_harness.php"
    cmd = [php_bin, str(harness), str(src_dir), str(input_file), str(out_file)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"PHP harness 失败({proc.returncode}): {proc.stderr[:500]}")
    return json.loads(Path(out_file).read_text(encoding="utf-8"))


def compare_one(php_result, py_result):
    diffs = []
    for key in ("ok", "brand", "__exception__"):
        if php_result.get(key) != py_result.get(key):
            diffs.append({"field": key, "php": php_result.get(key), "python": py_result.get(key)})
    if php_result.get("ok"):
        for stage in ("stage1_raw", "stage2_after_processor", "stage3_final"):
            a, b = php_result.get(stage), py_result.get(stage)
            if a != b:
                diffs.append({
                    "field": stage,
                    "php": a,
                    "python": b,
                    "php_rows": len(a or []),
                    "python_rows": len(b or []),
                })
    return diffs


def sha256_of(obj):
    """对象 canonical JSON 的 sha256（大输入报告瘦身用，比对本身仍是全量深比较）。"""
    canonical = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def slim_result(result):
    """大输入不内嵌全量 dump，只留指纹；小输入保留原文便于人工核对。"""
    slim = {k: v for k, v in result.items() if k in ("ok", "brand", "__exception__")}
    if result.get("ok"):
        for stage in ("stage1_raw", "stage2_after_processor", "stage3_final"):
            rows = result.get(stage) or []
            slim[stage + "_rows"] = len(rows)
            slim[stage + "_sha256"] = sha256_of(rows)
    return slim


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="FixText src 目录（含 vendor/autoload.php）")
    ap.add_argument("--fixtures", required=True, help="批注样例目录")
    ap.add_argument("--corpus", required=False, default="", help="T0.4 语料目录（可选）")
    ap.add_argument("--corpus-hybrid", required=False, default="",
                    help="混合语料目录（语料+批注块，用 gen_hybrid_corpus.py 生成；可选）")
    ap.add_argument("--out", default=str(HERE / "report"))
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "_php_out.json"

    inputs = []
    fx = Path(args.fixtures)
    for p in sorted(fx.iterdir()):
        if p.is_file():
            inputs.append((p, "fixture"))
    if args.corpus:
        for p in sorted(Path(args.corpus).iterdir()):
            if p.is_file() and p.suffix == ".txt":
                inputs.append((p, "corpus"))
    if args.corpus_hybrid:
        for p in sorted(Path(args.corpus_hybrid).iterdir()):
            if p.is_file() and p.suffix == ".txt":
                inputs.append((p, "corpus_hybrid"))

    results = []
    diff_count = 0
    SLIM_THRESHOLD = 65536  # 超过 64KB 的输入：报告只存指纹（比对仍全量）
    for path, kind in inputs:
        php_res = run_php_harness(args.src, path, tmp)
        py_res = py_pipeline_report(path.read_text(encoding="utf-8"))
        diffs = compare_one(php_res, py_res)
        if path.stat().st_size > SLIM_THRESHOLD:
            php_store = slim_result(php_res)
            py_store = slim_result(py_res)
        else:
            php_store = php_res
            py_store = py_res
        row = {
            "kind": kind,
            "file": path.name,
            "size": path.stat().st_size,
            "php": php_store,
            "python": py_store,
            "diffs": diffs,
            "equal": not diffs,
        }
        results.append(row)
        status = "EQ " if not diffs else f"DIFF({len(diffs)})"
        brand = php_res.get("brand") or php_res.get("__exception__", "")
        print(f"[{status}] {kind:8s} {path.name:36s} brand={brand!r}")
        if diffs:
            diff_count += 1

    summary = {
        "total": len(results),
        "equal": sum(1 for r in results if r["equal"]),
        "diff": diff_count,
        "inputs": [
            {
                "kind": r["kind"], "file": r["file"], "size": r["size"], "equal": r["equal"],
                "php_brand": r["php"].get("brand"),
                "php_ok": r["php"].get("ok"),
                "php_rows": len(r["php"].get("stage3_final") or []),
                "python_rows": len(r["python"].get("stage3_final") or []),
                "diffs": r["diffs"],
            }
            for r in results
        ],
        "full_results": results,
    }
    (out_dir / "compare_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n合计 {len(results)} 项：一致 {len(results) - diff_count}，相异 {diff_count}")
    print(f"明细已写入 {out_dir / 'compare_report.json'}")
    return 1 if diff_count else 0


if __name__ == "__main__":
    sys.exit(main())
