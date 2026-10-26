"""等价性比对：PHP 原版（未修改检测逻辑 + harness 驱动） vs Python 重实现。

用法：
  python3 run_equivalence.py --fixtext-src <FixText/src 目录> --corpus <语料目录> [--php <php 可执行文件>]

输出（写入本目录 results/）：
  php_results.json / py_results.json   两侧原始事件流
  comparison_report.md                  逐文件等价性结论与差异明细
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from fixtext_quotation.checker import QuotationChecker  # noqa: E402


def run_php(php: str, fixtext_src: str, files: list) -> dict:
    cmd = [php, str(HERE / "php_harness.php"), fixtext_src] + [str(f) for f in files]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(f"PHP harness 失败：{proc.stderr[-2000:]}")
    out = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        out[rec["file"]] = rec
    return out


def run_py(files: list) -> dict:
    out = {}
    for f in files:
        checker = QuotationChecker()
        errors = checker.check_file(f)
        out[f.name] = {
            "file": f.name,
            "errCount": len(errors),
            "events": [e.to_dict() for e in errors],
        }
    return out


def compare(php: dict, py: dict) -> tuple:
    """逐文件比较事件流（行号、字符下标、报错文案三要素完全相等才视为等价）。"""
    rows = []
    all_equal = True
    for fname in php:
        a, b = php[fname], py.get(fname)
        if b is None:
            rows.append((fname, False, php[fname]["errCount"], None, "Python 侧无结果"))
            all_equal = False
            continue
        ev_a, ev_b = a["events"], b["events"]
        equal = ev_a == ev_b
        diffs = []
        if not equal:
            n = max(len(ev_a), len(ev_b))
            for i in range(n):
                ea = ev_a[i] if i < len(ev_a) else None
                eb = ev_b[i] if i < len(ev_b) else None
                if ea != eb:
                    diffs.append((i + 1, ea, eb))
        rows.append((fname, equal, a["errCount"], b["errCount"], diffs))
        all_equal = all_equal and equal
    return all_equal, rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtext-src", required=True, help="FixText/src 目录（含 vendor/autoload.php）")
    ap.add_argument("--corpus", required=True, help="语料目录")
    ap.add_argument("--php", default="php")
    args = ap.parse_args()

    corpus_dir = Path(args.corpus)
    files = sorted(p for p in corpus_dir.iterdir() if p.is_file() and p.suffix == ".txt")
    if not files:
        print(f"语料目录无 txt 文件：{corpus_dir}", file=sys.stderr)
        return 1

    print(f"共 {len(files)} 份语料，先跑 PHP 原版参照…", file=sys.stderr)
    php_res = run_php(args.php, args.fixtext_src, files)
    print("PHP 完成，跑 Python 实现…", file=sys.stderr)
    py_res = run_py(files)
    print("Python 完成，比对中…", file=sys.stderr)

    all_equal, rows = compare(php_res, py_res)

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "php_results.json").write_text(
        json.dumps(php_res, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (out_dir / "py_results.json").write_text(
        json.dumps(py_res, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    lines = []
    lines.append("# T1.4 引号检查 · PHP 原版 vs Python 重实现 等价性比对报告")
    lines.append("")
    lines.append(f"- 比对对象：PHP `{args.fixtext_src}/app/Service/Quotation/QuotationChecker.php`（检测逻辑未修改，")
    lines.append("  经 php_harness.php 以统计模式单遍语义驱动）vs Python `fixtext_quotation/checker.py`")
    lines.append(f"- 语料：{corpus_dir} 下 {len(files)} 份 txt")
    lines.append(f"- 比对口径：逐文件事件流（行号 + 行内字符下标 + 报错文案）完全相等")
    lines.append("")
    lines.append("## 逐文件结论")
    lines.append("")
    lines.append("| 语料 | PHP 错误数 | Python 错误数 | 等价 |")
    lines.append("| --- | --- | --- | --- |")
    for fname, equal, cnt_a, cnt_b, _ in rows:
        lines.append(f"| {fname} | {cnt_a} | {cnt_b if cnt_b is not None else '—'} | {'✅' if equal else '❌'} |")
    lines.append("")
    if all_equal:
        lines.append(f"**结论：{len(rows)}/{len(rows)} 份语料事件流逐条完全一致，等价性通过。**")
    else:
        lines.append("## 差异明细")
        lines.append("")
        for fname, equal, cnt_a, cnt_b, diffs in rows:
            if equal:
                continue
            lines.append(f"### {fname}")
            for idx, ea, eb in diffs:
                lines.append(f"- 第 {idx} 条：PHP={json.dumps(ea, ensure_ascii=False)} / Python={json.dumps(eb, ensure_ascii=False)}")
            lines.append("")
        lines.append(f"**结论：{sum(1 for r in rows if r[1])}/{len(rows)} 份一致。**")
    (out_dir / "comparison_report.md").write_text("\n".join(lines), encoding="utf-8")

    print((out_dir / "comparison_report.md").read_text(encoding="utf-8"))
    return 0 if all_equal else 1


if __name__ == "__main__":
    sys.exit(main())
