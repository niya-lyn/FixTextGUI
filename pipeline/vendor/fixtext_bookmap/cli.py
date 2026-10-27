"""命令行入口（供编排器以子进程方式调用）。

用法示例::

    python -m fixtext_bookmap generate-book-maps \
        --book-fix-dir ./booksFix --book-dir ./books --map-root .

    python -m fixtext_bookmap extract \
        --before-file ./booksFix/x.txt --after-file ./books/x.txt

    python -m fixtext_bookmap replace-count-report \
        --book-dir ./books --book-bak-dir ./booksBak \
        --report-dir ./logs/report --temp-map-file ./maps/5.临时校对表.php

所有子命令均向 stdout 输出 JSON，便于编排器解析。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .generator import BookMapGenerator
from .option import Option
from .wordmap import gen_diff_words_map


def _option_from_args(args: argparse.Namespace) -> Option:
    option = Option()
    for name in (
        "replace_count_threshold",
        "context_len",
        "remove_l_or_r_char",
        "filter_keywords",
        "get_multi_line_content",
        "trim_punctuations",
        "add_html_stripped_copy",
        "add_current_time",
    ):
        value = getattr(args, name, None)
        if value is not None:
            setattr(option, name, value)
    return option


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fixtext_bookmap", description="FixText 专有词库生成（Python 重实现）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--replace-count-threshold", type=int, default=None)
    common.add_argument("--context-len", type=int, default=None)
    common.add_argument("--remove-l-or-r-char", type=int, default=None)
    common.add_argument("--filter-keywords", action="store_true", default=None)
    common.add_argument("--get-multi-line-content", action="store_true", default=None)
    common.add_argument("--trim-punctuations", action="store_true", default=None)
    common.add_argument(
        "--add-html-stripped-copy",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    common.add_argument(
        "--add-current-time", action=argparse.BooleanOptionalAction, default=None
    )

    p1 = sub.add_parser(
        "generate-book-maps", parents=[common], help="生成专有词库表"
    )
    p1.add_argument(
        "--book-fix-dir", required=True, help="改前文本目录（词条 before 侧，对应上游 booksFix）"
    )
    p1.add_argument(
        "--book-dir", required=True, help="改后文本目录（词条 after 侧，对应上游 books）"
    )
    p1.add_argument("--map-root", default=".", help="FixText 根目录（含 maps/）")
    p1.add_argument("--timestamp", type=float, default=None, help="写入的时间戳")

    p2 = sub.add_parser("extract", parents=[common], help="提取单个文件的专有词条")
    p2.add_argument("--before-file", required=True, help="改前文本（词条 before 侧）")
    p2.add_argument("--after-file", required=True, help="改后文本（词条 after 侧）")
    p2.add_argument("--patch-file", default=None, help="patch 文件输出路径")
    p2.add_argument("--context-len-override", type=int, default=5)

    p3 = sub.add_parser(
        "replace-count-report", parents=[common], help="专有词频率统计（替换次数报告）"
    )
    p3.add_argument("--book-dir", required=True, help="改后文本目录（对应上游 books）")
    p3.add_argument("--book-bak-dir", required=True, help="改前文本目录（对应上游 booksBak）")
    p3.add_argument("--report-dir", required=True, help="报告 / patch 输出目录")
    p3.add_argument("--temp-map-file", required=True, help="汇总临时词库文件")

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    option = _option_from_args(args)

    if args.command == "generate-book-maps":
        gen = BookMapGenerator(option=option, map_root=args.map_root)
        result = gen.generate_book_maps(
            args.book_fix_dir, args.book_dir, timestamp=args.timestamp
        )
        payload = {
            "books": result["books"],
            "skipped": result["skipped"],
            "entry_counts": {
                k: len(v) for k, v in result["entries"].items()
            },
        }

    elif args.command == "extract":
        patch_file = args.patch_file or (
            os.path.join(
                os.path.dirname(args.before_file),
                "【专有词条】"
                + os.path.splitext(os.path.basename(args.before_file))[0]
                + ".patch",
            )
        )
        entries = gen_diff_words_map(
            patch_file,
            args.before_file,
            args.after_file,
            context_len=args.context_len_override,
            trim_orig_str=False,
            option=option,
        )
        payload = {"entries": entries, "count": len(entries)}

    else:  # replace-count-report
        gen = BookMapGenerator(option=option, map_root=".")
        result = gen.gen_replace_count_report(
            args.book_dir, args.book_bak_dir, args.report_dir, args.temp_map_file
        )
        payload = {
            "reports": result["reports"],
            "entry_counts": {k: len(v) for k, v in result["entries"].items()},
        }

    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
