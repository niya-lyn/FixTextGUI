"""命令行入口。

    python -m fixtext_pipeline run \\
        --epub 你的书.epub \\
        --workdir ./runs/mybook \\
        --wordbank-dir .../build/dictionary/rules \\
        --engine .../replace_by_go-linux-amd64

子命令：

* ``run``     —— 跑全链路（默认子命令）
* ``doctor``  —— 体检：检查 EPUB / 词库 / Go 引擎 / 引擎模块是否齐备
* ``report``  —— 打印上一次运行的报告（Markdown）

退出码：

* ``0`` 全链路成功
* ``1`` 某个阶段失败
* ``2`` 参数或环境不满足（输入缺失、引擎不可用等）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import engine_selector
from .config import LAYOUT_PROFILES, STAGE_META, PipelineConfig

EXIT_OK = 0
EXIT_STAGE_FAILED = 1
EXIT_USAGE = 2

#: 引擎二进制在 vendor 下的相对目录
_ENGINE_BIN_REL = Path("fixtext/engine/go_src/bin")


def _engine_rel() -> Path:
    """本平台引擎在 vendor 下的相对位置。

    平台判断只在 ``engine_selector`` 一处，这里按它给的常量拼文件名——
    绝不再写死 Linux 文件名（Windows 上会拿到 ELF，执行时才炸 WinError 193）。
    """
    name = (engine_selector.WINDOWS_NAME if sys.platform == "win32"
            else engine_selector.LINUX_NAME)
    return _ENGINE_BIN_REL / name


# --------------------------------------------------------------------------- #
# 路径自动发现
# --------------------------------------------------------------------------- #


def _product_root() -> Path:
    """产品根目录（``fixtext_pipeline`` 的上一级）。"""
    return Path(__file__).resolve().parent.parent


def discover_engine() -> Path | None:
    """找 Go 引擎：按本平台取 vendor 里的那一个，取不到再看 PATH。

    注意**不要**写成「把两个平台的文件名都试一遍、谁先存在用谁」：
    包里两个引擎是并存的，先试 Linux 会让 Windows 拿到 ELF，最终在执行时
    报 ``WinError 193``。平台判断统一交给 ``engine_selector``。
    """
    root = _product_root()
    bin_dir = root / "vendor" / "fixtext" / "engine" / "go_src" / "bin"
    picked = engine_selector.select_engine(bin_dir)
    if picked is not None:
        return picked
    # 兜底：PATH 里装了同名引擎（开发机上常见）
    names = (engine_selector.WINDOWS_NAME, engine_selector.LINUX_NAME) \
        if sys.platform == "win32" else \
        (engine_selector.LINUX_NAME, engine_selector.WINDOWS_NAME)
    for name in ("replace_by_go",) + names:
        found = shutil_which(name)
        if found:
            return Path(found)
    return None


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def resolve_rules(args: argparse.Namespace) -> tuple[Path, Path]:
    """解析 before.json / after.json 的位置。"""
    if args.rules_before and args.rules_after:
        return Path(args.rules_before), Path(args.rules_after)
    if args.rules_before or args.rules_after:
        raise SystemExit(
            "错误：--rules-before 与 --rules-after 必须成对给出；"
            "或改用 --wordbank-dir 指定同时包含 before.json/after.json 的目录。"
        )
    if not args.wordbank_dir:
        raise SystemExit(
            "错误：需要 --wordbank-dir（或成对的 --rules-before/--rules-after）指定词库规则文件。"
        )
    base = Path(args.wordbank_dir)
    before, after = base / "before.json", base / "after.json"
    if not before.is_file() or not after.is_file():
        # 也接受直接指到 build/dictionary/rules 的父目录
        nested = base / "build" / "dictionary" / "rules"
        before, after = nested / "before.json", nested / "after.json"
    return before, after


def parse_layout_overrides(items: list[str] | None) -> dict[str, Any]:
    """把 ``--layout-option key=value`` 解析成 dict（值按 JSON 尝试）。"""
    overrides: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"错误：--layout-option 需要 key=value 形式，收到 {item!r}")
        key, _, raw = item.partition("=")
        key = key.strip()
        try:
            overrides[key] = json.loads(raw)
        except json.JSONDecodeError:
            overrides[key] = raw
    unknown = [k for k in overrides if k not in LAYOUT_PROFILES["html-safe"]]
    if unknown:
        raise SystemExit(f"错误：未知的排版选项 {unknown}；可用选项见 LAYOUT_PROFILES。")
    return overrides


# --------------------------------------------------------------------------- #
# 子命令
# --------------------------------------------------------------------------- #


def cmd_run(args: argparse.Namespace) -> int:
    rules_before, rules_after = resolve_rules(args)

    # M4-T4.2：替换引擎选择。--replace-engine 显式指定优先；缺省读持久化
    # 配置键 ``engine``（环境变量 FIXTEXT_ENGINE 可临时覆盖），默认 go。
    from .engine_choice import get_engine_choice
    replace_engine = getattr(args, "replace_engine", None) or get_engine_choice()

    engine = Path(args.engine) if args.engine else discover_engine()
    if engine is None:
        # Python 引擎模式不要求 Go 二进制存在；Go 模式在下面按缺失报错
        engine = _product_root() / "vendor" / _engine_rel()
    if replace_engine == "go":
        if not Path(args.engine or "").is_file() and args.engine:
            print(f"错误：Go 引擎不存在：{engine}", file=sys.stderr)
            return EXIT_USAGE
        if not args.engine and not engine.is_file():
            print(
                "错误：找不到 Go 引擎二进制。请用 --engine 指定，或把引擎放到 "
                f"{_product_root() / 'vendor' / _engine_rel()}；"
                "也可用 --replace-engine python 改走 Python 替换引擎（较慢）。",
                file=sys.stderr,
            )
            return EXIT_USAGE

    stages = tuple(s.strip() for s in (args.stages or "").split(",") if s.strip())
    unknown = [s for s in stages if s not in STAGE_META]
    if unknown:
        print(f"错误：未知阶段 {unknown}；可选：{list(STAGE_META)}", file=sys.stderr)
        return EXIT_USAGE

    cfg = PipelineConfig(
        epub=Path(args.epub),
        workdir=Path(args.workdir),
        rules_before=rules_before,
        rules_after=rules_after,
        engine_path=engine,
        engine=replace_engine,
        replace_count=args.replace_count,
        engine_timeout_s=args.engine_timeout,
        layout_profile=args.layout_profile,
        layout_overrides=parse_layout_overrides(args.layout_option),
        bookmap_add_current_time=args.bookmap_add_current_time,
        stages=stages or tuple(STAGE_META),
        resume=not args.no_resume,
        force=args.force,
        keep_going=args.keep_going,
    )

    from .runner import run_pipeline

    exit_code, report = run_pipeline(cfg)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    print("")
    print("=" * 72)
    print(f"运行状态：{report['status']}　总耗时 {report['total_elapsed_s']}s")
    for name, meta in STAGE_META.items():
        stage = report["stages"].get(name)
        if not stage:
            continue
        print(
            f"  {meta[0]}  {meta[1]:<28} {stage['status']:<8} "
            f"{stage.get('elapsed_s', 0):>8.2f}s  {stage.get('summary', '')}"
        )
    print(f"报告：{cfg.paths.report / 'run_report.md'}")
    print("=" * 72)
    return exit_code


def cmd_doctor(args: argparse.Namespace) -> int:
    """跑之前先体检，把「缺什么」一次说清。"""
    from .vendor_bootstrap import REQUIRED_MODULES, bootstrap

    problems: list[str] = []
    print("FixTextGUI 一键校正编排器 · 环境体检")
    print("-" * 60)

    print(f"Python            : {sys.version.split()[0]}")
    print(f"产品目录          : {_product_root()}")

    # 引擎模块
    try:
        bootstrap()
        print(f"引擎模块          : 全部就绪 {list(REQUIRED_MODULES)}")
    except ImportError as exc:
        print(f"引擎模块          : 缺失 -> {exc}")
        problems.append(str(exc))

    # EPUB
    epub = Path(args.epub) if args.epub else None
    if epub is None:
        print("EPUB              : （未指定，跳过）")
    elif epub.is_file():
        print(f"EPUB              : {epub}（{epub.stat().st_size:,} 字节）")
    else:
        print(f"EPUB              : 缺失 -> {epub}")
        problems.append(f"EPUB 不存在：{epub}")

    # 词库
    try:
        before, after = resolve_rules(args)
        missing = [p for p in (before, after) if not p.is_file()]
        if missing:
            print(f"词库规则          : 缺失 -> {missing}")
            problems.append(f"词库规则缺失：{missing}")
        else:
            print(f"词库规则          : {before} / {after}")
    except SystemExit as exc:
        print(f"词库规则          : {exc}")
        problems.append(str(exc))

    # Go 引擎（M4-T4.2：配置选 python 时缺失只作提示，不算问题）
    from .engine_choice import get_engine_choice
    chosen = get_engine_choice()
    print(f"替换引擎选择      : {chosen}（配置键 engine，缺省 go）")
    engine = Path(args.engine) if args.engine else discover_engine()
    if engine is None:
        print("Go 引擎           : 未找到")
        if chosen == "go":
            problems.append("找不到 Go 引擎二进制")
        else:
            print("                  : 当前选 Python 引擎，仅作提示")
    elif not engine.is_file():
        print(f"Go 引擎           : 缺失 -> {engine}")
        if chosen == "go":
            problems.append(f"Go 引擎不存在：{engine}")
        else:
            print("                  : 当前选 Python 引擎，仅作提示")
    else:
        mode = engine.stat().st_mode
        executable = os.access(engine, os.X_OK)
        print(
            f"Go 引擎           : {engine}（{engine.stat().st_size:,} 字节，"
            f"mode {mode & 0o777:o}，可执行={executable}）"
        )
        if not executable and os.name != "nt":
            print("                  : 缺执行位，运行时会自动补 chmod +x")

    # Python 引擎依赖（M4-T4.2）
    try:
        import ahocorasick  # noqa: F401

        print("Python 引擎依赖   : pyahocorasick 已安装")
    except ImportError:
        print("Python 引擎依赖   : 缺失（pyahocorasick，--replace-engine python 需要）")
        if chosen == "python":
            problems.append("缺少 pyahocorasick（Python 替换引擎依赖）")

    # lxml
    try:
        import lxml  # noqa: F401

        print(f"lxml              : {lxml.__version__}")
    except ImportError:
        print("lxml              : 缺失（排版守卫与 EPUB 校验需要）")
        problems.append("缺少 lxml")

    print("-" * 60)
    if problems:
        print(f"体检未通过，共 {len(problems)} 项问题：")
        for p in problems:
            print(f"  - {p}")
        return EXIT_USAGE
    print("体检通过，可以开跑。")
    return EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    workdir = Path(args.workdir)
    md = workdir / "report" / "run_report.md"
    js = workdir / "report" / "run_report.json"
    if not md.is_file() and not js.is_file():
        print(f"错误：找不到运行报告（{workdir / 'report'}）", file=sys.stderr)
        return EXIT_USAGE
    if md.is_file():
        print(md.read_text(encoding="utf-8"))
    else:
        print(json.dumps(json.loads(js.read_text(encoding="utf-8")), ensure_ascii=False, indent=2))
    return EXIT_OK


# --------------------------------------------------------------------------- #
# 参数解析
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fixtext-pipeline",
        description="FixTextGUI 一键校正编排器：合并 → 排版 → 替换 → 引号检查 → 专有词库 → 还原",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m fixtext_pipeline run \\\n"
            "      --epub 你的书.epub \\\n"
            "      --workdir ./runs/mybook \\\n"
            "      --wordbank-dir ./wordbank/rules \\\n"
            "      --engine ./vendor/fixtext/engine/go_src/bin/replace_by_go-linux-amd64\n"
        ),
    )
    sub = parser.add_subparsers(dest="command")

    # ---- run ----
    run_p = sub.add_parser("run", help="跑全链路")
    run_p.add_argument("--epub", required=True, help="输入 EPUB 路径")
    run_p.add_argument("--workdir", required=True, help="工作目录（状态、产物、日志都落这里）")
    run_p.add_argument("--wordbank-dir", help="词库规则目录（含 before.json / after.json）")
    run_p.add_argument("--rules-before", help="before.json 路径（与 --rules-after 成对）")
    run_p.add_argument("--rules-after", help="after.json 路径（与 --rules-before 成对）")
    run_p.add_argument("--engine", help="Go 引擎二进制路径（默认自动发现 vendor 里的）")
    run_p.add_argument(
        "--replace-engine", choices=("go", "python"), default=None,
        help="替换引擎（M4-T4.2）：go=Go 引擎（默认），python=Python greedy 引擎"
             "（较慢）；缺省读配置键 engine（FIXTEXT_ENGINE 可临时覆盖）",
    )
    run_p.add_argument("--layout-profile", default="html-safe", choices=sorted(LAYOUT_PROFILES))
    run_p.add_argument(
        "--layout-option",
        action="append",
        metavar="KEY=VALUE",
        help="覆盖排版选项，可重复，如 --layout-option normalize_punctuations=false",
    )
    run_p.add_argument("--replace-count", type=int, default=2, help="替换趟数（默认 2）")
    run_p.add_argument("--engine-timeout", type=float, default=1800.0, help="Go 引擎超时秒数")
    run_p.add_argument("--stages", help="只跑指定阶段，逗号分隔，如 merge,layout")
    run_p.add_argument("--no-resume", action="store_true", help="不跳过已完成阶段")
    run_p.add_argument("--force", action="store_true", help="强制重跑（忽略已有状态）")
    run_p.add_argument("--keep-going", action="store_true", help="某阶段失败后继续跑后面的阶段")
    run_p.add_argument(
        "--bookmap-add-current-time",
        action="store_true",
        help="专有词库写入时间点注释（默认关闭以保证产物可复现）",
    )
    run_p.add_argument("--json", action="store_true", help="额外把运行报告 JSON 打到 stdout")
    run_p.set_defaults(func=cmd_run)

    # ---- doctor ----
    doc_p = sub.add_parser("doctor", help="环境体检")
    doc_p.add_argument("--epub", help="要检查的 EPUB")
    doc_p.add_argument("--wordbank-dir", help="词库规则目录")
    doc_p.add_argument("--rules-before", help="before.json 路径")
    doc_p.add_argument("--rules-after", help="after.json 路径")
    doc_p.add_argument("--engine", help="Go 引擎二进制路径")
    doc_p.set_defaults(func=cmd_doctor)

    # ---- report ----
    rep_p = sub.add_parser("report", help="打印上一次运行报告")
    rep_p.add_argument("--workdir", required=True, help="工作目录")
    rep_p.set_defaults(func=cmd_report)

    return parser


def normalize_argv(argv: list[str]) -> list[str]:
    """没显式给子命令时默认走 ``run``。

    ``fixtext-pipeline --epub a.epub --workdir w`` 等价于
    ``fixtext-pipeline run --epub a.epub --workdir w``。
    """
    known = {"run", "doctor", "report"}
    if not argv or argv[0] not in known:
        return ["run"] + argv
    return list(argv)


def main(argv: list[str] | None = None) -> int:
    argv = normalize_argv(list(sys.argv[1:] if argv is None else argv))
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE
    try:
        return int(args.func(args))
    except SystemExit as exc:  # argparse / 内部校验的退出
        code = exc.code
        if isinstance(code, int):
            return code
        print(str(code), file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("\n已中断：状态已落盘，可用同一命令加 --resume 续跑。", file=sys.stderr)
        return EXIT_STAGE_FAILED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
