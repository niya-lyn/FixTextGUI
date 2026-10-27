"""命令行入口：供编排器以子进程方式调用，也方便人工排查。

用法::

    python -m epubtext merge book.epub [-o out.txt]
    python -m epubtext restore book.txt [--ledger book.bundle.json] [--template book.epub] [-o out.epub]
    python -m epubtext check book.epub [--no-deep]
    python -m epubtext roundtrip book.epub
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .merge import merge_directory, merge_epub
from .restore import restore_epub
from .validate import check_epub, compare_bytes, compare_content


def _print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_merge(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if target.is_dir():
        results = merge_directory(target, args.output_dir)
        _print(
            {
                "ok": True,
                "count": len(results),
                "items": [result.report for result in results],
            }
        )
        return 0
    result = merge_epub(target, args.output, nonce=args.nonce)
    _print({"ok": True, **result.report, "ledger": str(result.ledger_path)})
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    result = restore_epub(
        args.text,
        args.ledger,
        args.template,
        args.output,
        strict=not args.loose,
        allow_modified=not args.strict_content,
    )
    _print({"ok": True, **result.report})
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    report = check_epub(args.path, deep=not args.no_deep)
    _print(report.to_dict())
    return 0 if report.ok else 1


def cmd_roundtrip(args: argparse.Namespace) -> int:
    """合并 → 还原 → 校验，一条命令给出完整往返结论。"""
    workbook = Path(args.path)
    out_dir = Path(args.output_dir) if args.output_dir else workbook.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    merged = merge_epub(workbook, out_dir / (workbook.stem + ".txt"), nonce=args.nonce)
    restored = restore_epub(
        merged.text_path,
        merged.ledger_path,
        workbook,
        out_dir / (workbook.stem + "_restored.epub"),
    )
    structural = check_epub(restored.epub_path, deep=True)
    content = compare_content(workbook, restored.epub_path)
    binary = compare_bytes(workbook, restored.epub_path)

    payload = {
        "ok": structural.ok and content["content_ok"] and binary["byte_identical"],
        "merge": merged.report,
        "restore": restored.report,
        "check": structural.to_dict(),
        "content": content,
        "bytes": binary,
    }
    _print(payload)
    return 0 if payload["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="epubtext", description="EPUB 文本合并与还原")
    sub = parser.add_subparsers(dest="command", required=True)

    p_merge = sub.add_parser("merge", help="EPUB → TXT 合并")
    p_merge.add_argument("path", help="EPUB 文件或目录")
    p_merge.add_argument("-o", "--output", default=None, help="输出 TXT 路径")
    p_merge.add_argument("--output-dir", default=None, help="目录模式下输出目录")
    p_merge.add_argument("--nonce", default=None, help="固定标记随机串（复现用）")
    p_merge.set_defaults(func=cmd_merge)

    p_restore = sub.add_parser("restore", help="TXT → EPUB 还原")
    p_restore.add_argument("text", help="合并后的 TXT")
    p_restore.add_argument("--ledger", default=None, help="账本 JSON（默认同名 .bundle.json）")
    p_restore.add_argument("--template", default=None, help="模板 EPUB（默认账本 source 同目录）")
    p_restore.add_argument("-o", "--output", default=None, help="输出 EPUB")
    p_restore.add_argument("--loose", action="store_true", help="关闭严格切分校验（不推荐）")
    p_restore.add_argument("--strict-content", action="store_true", help="正文有改动时拒绝还原")
    p_restore.set_defaults(func=cmd_restore)

    p_check = sub.add_parser("check", help="校验 EPUB 结构与正文")
    p_check.add_argument("path")
    p_check.add_argument("--no-deep", action="store_true", help="跳过逐章 XHTML 解析")
    p_check.set_defaults(func=cmd_check)

    p_rt = sub.add_parser("roundtrip", help="合并→还原→校验 全流程")
    p_rt.add_argument("path")
    p_rt.add_argument("--output-dir", default=None)
    p_rt.add_argument("--nonce", default=None)
    p_rt.set_defaults(func=cmd_roundtrip)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001 - CLI 边界统一兜底，输出可解析的错误
        _print({"ok": False, "error": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
