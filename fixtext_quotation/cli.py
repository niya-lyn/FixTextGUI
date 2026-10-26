"""命令行入口：python -m fixtext_quotation check <files...> [--json] [--out DIR]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .checker import QuotationChecker
from .report import render_json, render_report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="fixtext_quotation",
        description="FixText 引号检查（Python 重实现）：中文单双引号配对、跨行闭合等检测与报告",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="检查一个或多个文本文件")
    p_check.add_argument("files", nargs="+", help="待检查的文本文件")
    p_check.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    p_check.add_argument("--out", default=None, help="报告输出目录（默认仅打印到 stdout）")

    args = parser.parse_args(argv)

    if args.cmd == "check":
        out_dir = Path(args.out) if args.out else None
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
        total = 0
        for f in args.files:
            path = Path(f)
            checker = QuotationChecker()
            try:
                errors = checker.check_file(path)
            except (OSError, UnicodeDecodeError) as exc:
                print(f"读取失败：{path.name}：{exc}", file=sys.stderr)
                return 2
            total += len(errors)
            if args.json:
                print(render_json(str(path), errors))
            else:
                print(render_report(str(path), path.read_text(encoding="utf-8"), errors))
            if out_dir:
                (out_dir / (path.stem + ".report.txt")).write_text(
                    render_report(str(path), path.read_text(encoding="utf-8"), errors),
                    encoding="utf-8",
                )
                (out_dir / (path.stem + ".report.json")).write_text(
                    render_json(str(path), errors), encoding="utf-8"
                )
        print(f"共检查 {len(args.files)} 个文件，引号错误段落共 {total} 处", file=sys.stderr)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
