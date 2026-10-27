#!/usr/bin/env python3
"""等价性对比：Python 重实现 vs 上游 PHP 跑出的词库表。

用法::

    python3 scripts/run_equivalence.py \
        --php-maps  <FixText>/src/maps/书籍专有替换词库 \
        --py-maps   <python_out>/maps/书籍专有替换词库 \
        --report    docs/等价性对比报告.md \
        --json      docs/等价性对比结果.json

对比时会把「新增下列词条的时间点」注释中的时间戳归一化
（两次运行时间不同属于预期差异，不计入等价性判定）。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

TIME_RE = re.compile(r"/\* 新增下列词条的时间点：[^*]*\*/")


def normalize(text: str) -> str:
    """把时间点注释中的时间戳归一化。"""
    return TIME_RE.sub("/* 新增下列词条的时间点：<TIMESTAMP> */", text)


def read_text(path: str) -> str:
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def diff_lines(a: str, b: str):
    """返回两条文本的差异行清单。"""
    import difflib

    a_lines = a.splitlines()
    b_lines = b.splitlines()
    out = []
    for line in difflib.unified_diff(a_lines, b_lines, "php", "python", n=1, lineterm=""):
        out.append(line)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--php-maps", required=True)
    parser.add_argument("--py-maps", required=True)
    parser.add_argument("--report", default=None)
    parser.add_argument("--json", dest="json_out", default=None)
    parser.add_argument("--max-diff-lines", type=int, default=20)
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="排除的既有词库文件名（随 FixText 附带、无对应语料、不会重新生成）",
    )
    parser.add_argument(
        "--corpora-count",
        type=int,
        default=None,
        help="参与对比的语料份数（用于验收口径 reporting）",
    )
    args = parser.parse_args(argv)

    excluded = set(args.exclude or [])

    php_files = {
        f: os.path.join(args.php_maps, f)
        for f in sorted(os.listdir(args.php_maps))
        if f.endswith(".php") and f not in excluded
    }
    py_files = {
        f: os.path.join(args.py_maps, f)
        for f in sorted(os.listdir(args.py_maps))
        if f.endswith(".php") and f not in excluded
    }

    all_names = sorted(set(php_files) | set(py_files))
    results = []
    identical = 0

    for name in all_names:
        item = {"file": name}
        if name not in php_files:
            item.update(status="missing_in_php", entry_counts=None, diff_lines=[])
            results.append(item)
            continue
        if name not in py_files:
            item.update(status="missing_in_python", entry_counts=None, diff_lines=[])
            results.append(item)
            continue

        php_text = normalize(read_text(php_files[name]))
        py_text = normalize(read_text(py_files[name]))

        php_count = php_text.count("['before'")
        py_count = py_text.count("['before'")
        item["php_entry_count"] = php_count
        item["py_entry_count"] = py_count

        if php_text == py_text:
            item.update(status="identical", diff_lines=[])
            identical += 1
        else:
            d = diff_lines(php_text, py_text)
            item.update(status="different", diff_lines=d[: args.max_diff_lines])
            item["diff_total_lines"] = len(d)
        results.append(item)

    summary = {
        "total_files": len(all_names),
        "identical_files": identical,
        "different_files": sum(1 for r in results if r["status"] == "different"),
        "missing": sum(
            1 for r in results if r["status"].startswith("missing")
        ),
        "total_php_entries": sum(r.get("php_entry_count", 0) or 0 for r in results),
        "total_py_entries": sum(r.get("py_entry_count", 0) or 0 for r in results),
        "excluded_shipped_maps": sorted(excluded),
        "corpora_count": args.corpora_count,
        "all_identical": (
            len(all_names) > 0
            and identical == len(all_names)
            and not any(r["status"].startswith("missing") for r in results)
        ),
    }

    payload = {"summary": summary, "files": results}

    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with io.open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with io.open(args.report, "w", encoding="utf-8", newline="") as fh:
            fh.write(render_markdown(payload))

    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if summary["different_files"] == 0 and summary["missing"] == 0 else 2


def render_markdown(payload: dict) -> str:
    summary = payload["summary"]
    lines = []
    lines.append("# 等价性对比报告：Python 重实现 vs 上游 PHP\n")
    lines.append("## 结论\n")
    lines.append(
        f"- 对比文件数：{summary['total_files']}\n"
        f"- 逐字节等价（归一化时间戳后）：{summary['identical_files']}\n"
        f"- 存在差异：{summary['different_files']}\n"
        f"- 单侧缺失：{summary['missing']}\n"
        f"- PHP 侧词条总数：{summary['total_php_entries']}\n"
        f"- Python 侧词条总数：{summary['total_py_entries']}\n"
    )
    lines.append("\n## 逐文件结果\n")
    lines.append("| 词库文件 | 状态 | PHP 词条数 | Python 词条数 |\n")
    lines.append("| --- | --- | --- | --- |\n")
    for item in payload["files"]:
        lines.append(
            "| {f} | {s} | {p} | {q} |\n".format(
                f=item["file"],
                s=item["status"],
                p=item.get("php_entry_count", "-"),
                q=item.get("py_entry_count", "-"),
            )
        )
    diffs = [i for i in payload["files"] if i["status"] == "different"]
    if diffs:
        lines.append("\n## 差异明细\n")
        for item in diffs:
            lines.append(f"\n### {item['file']}\n\n```diff\n")
            lines.append("\n".join(item["diff_lines"]))
            lines.append("\n```\n")
    return "".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
