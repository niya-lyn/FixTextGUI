#!/usr/bin/env python3
"""一键 CI：lint + 门禁静态检查 + 单元测试 + 回归基线。

设计目标：
- 跨平台一致（Windows / Linux 同一入口），不依赖 bash 专有语法；
- 无参数即「全量跑一遍」，任一环节失败即非 0 退出；
- 各环节可单独跳过，便于本地只跑一部分。

用法：
    python scripts/ci.py               # 全量：lint → 门禁 → 单测 → 回归基线
    python scripts/ci.py --only baseline   # 只跑回归基线（T0.4）
    python scripts/ci.py --skip lint
退出码：0 = 全部通过；1 = 有环节失败。
（回归基线环节在缺 php/go 依赖或 baseline/ 未并入时按 SKIP 处理，不算失败。）
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"

STAGES = ("lint", "format-check", "gates", "tests", "baseline")

BASELINE_SKIP_CODE = 77  # ci_baseline.py 约定：77 = 环节跳过（非失败）


@dataclass
class StageResult:
    name: str
    ok: bool
    seconds: float
    detail: str = ""
    skipped: bool = False


def _python() -> str:
    return sys.executable


def _run(cmd: list[str], env: dict[str, str] | None = None) -> tuple[bool, str, int]:
    """执行子进程并回传 (是否成功, 合并输出, 退出码)。"""
    merged_env = os.environ.copy()
    merged_env.setdefault("PYTHONIOENCODING", "utf-8")
    # 保证未安装包时也能以源码布局运行
    existing = merged_env.get("PYTHONPATH", "")
    merged_env["PYTHONPATH"] = str(SRC) + (os.pathsep + existing if existing else "")
    if env:
        merged_env.update(env)

    proc = subprocess.run(  # noqa: S603 - 固定命令，无外部输入
        cmd,
        cwd=str(PROJECT_ROOT),
        env=merged_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output.strip(), proc.returncode


def stage_lint() -> StageResult:
    started = time.time()
    ok, output, _ = _run([_python(), "-m", "ruff", "check", "."])
    return StageResult("lint", ok, time.time() - started, output)


def stage_format_check() -> StageResult:
    started = time.time()
    ok, output, _ = _run([_python(), "-m", "ruff", "format", "--check", "."])
    return StageResult("format-check", ok, time.time() - started, output)


def stage_gates() -> StageResult:
    started = time.time()
    ok, output, _ = _run([_python(), str(PROJECT_ROOT / "scripts" / "check_gates.py")])
    return StageResult("gates", ok, time.time() - started, output)


def stage_tests() -> StageResult:
    started = time.time()
    ok, output, _ = _run(
        [_python(), "-m", "pytest", "-q"],
        env={"QT_QPA_PLATFORM": "offscreen"},
    )
    return StageResult("tests", ok, time.time() - started, output)


def stage_baseline() -> StageResult:
    """T0.4 回归基线重跑比对：Go + PHP 双后端 × 15 语料 vs 冻结基线。"""
    started = time.time()
    script = PROJECT_ROOT / "scripts" / "ci_baseline.py"
    if not script.exists():
        return StageResult(
            "baseline", True, time.time() - started,
            "SKIP：未找到 scripts/ci_baseline.py", skipped=True,
        )
    ok, output, code = _run([_python(), str(script)])
    if code == BASELINE_SKIP_CODE:
        return StageResult("baseline", True, time.time() - started, output, skipped=True)
    return StageResult("baseline", ok, time.time() - started, output)


RUNNERS = {
    "lint": stage_lint,
    "format-check": stage_format_check,
    "gates": stage_gates,
    "tests": stage_tests,
    "baseline": stage_baseline,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FixText CI：lint + 门禁 + 单测 + 回归基线")
    parser.add_argument(
        "--only",
        action="append",
        choices=STAGES,
        help="只运行指定环节（可重复）",
    )
    parser.add_argument(
        "--skip",
        action="append",
        choices=STAGES,
        help="跳过指定环节",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="始终打印各环节完整输出（默认仅打印失败环节输出）",
    )
    args = parser.parse_args(argv)

    selected = list(args.only) if args.only else list(STAGES)
    if args.skip:
        selected = [name for name in selected if name not in args.skip]
    if not selected:
        print("没有需要运行的环节。")
        return 1

    print(f"FixText CI · 环节：{' → '.join(selected)}")
    print(f"工程根目录：{PROJECT_ROOT}")
    print("-" * 62)

    results: list[StageResult] = []
    for name in selected:
        result = RUNNERS[name]()
        results.append(result)
        if result.skipped:
            print(f"[SKIP] {result.name:<13} {result.seconds:6.2f}s")
        else:
            mark = "PASS" if result.ok else "FAIL"
            print(f"[{mark}] {result.name:<13} {result.seconds:6.2f}s")
        if result.detail and (args.verbose or not result.ok):
            for line in result.detail.splitlines():
                print("    " + line)

    print("-" * 62)
    failed = [r.name for r in results if not r.ok]
    if failed:
        print(f"CI 失败：{', '.join(failed)}")
        return 1

    total = sum(r.seconds for r in results)
    ran = [r for r in results if not r.skipped]
    print(f"CI 全部通过（{len(ran)} 个环节执行，{len(results) - len(ran)} 个跳过，合计 {total:.2f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
