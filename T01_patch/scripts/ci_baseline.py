#!/usr/bin/env python3
"""CI 环节：FixText 回归基线重跑比对（T0.4 交付物并入 T0.1 骨架）。

前置：仓库根目录下存在 baseline/（T0.4 回归基线集，可直接整目录放入）。
行为：
  - 检查 php（CLI）与 go（工具链或随包预编译二进制）是否可用；
  - 调用 baseline/scripts/run_baseline.py 一键重跑比对（Go + PHP 双后端 × 15 语料）；
  - 缺依赖或缺 baseline/ 时以退出码 77 报 SKIP（不视为 CI 失败，适用于无 php/go 的矩阵位）；
  - 比对不一致时退出码 1（视为 CI 失败——这正是回归基线的意义）。

用法：
    python scripts/ci_baseline.py [--keep-json]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = PROJECT_ROOT / "baseline"
RUNNER = BASELINE_DIR / "scripts" / "run_baseline.py"

SKIP_CODE = 77  # 与 ci.py 约定：77 = 环节跳过（非失败）


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CI 环节：回归基线重跑比对")
    ap.add_argument("--keep-json", action="store_true", help="把比对结果 JSON 保留在 baseline/results/ 下")
    args = ap.parse_args(argv)

    if not RUNNER.exists():
        print("[SKIP] 未找到 baseline/scripts/run_baseline.py（回归基线集未并入本仓库）")
        return SKIP_CODE

    php = shutil.which("php")
    go = shutil.which("go")
    prebuilt = (BASELINE_DIR / "scripts" / "go" / "replace_by_go.bin").exists() and \
        (BASELINE_DIR / "scripts" / "go" / "count_hits.bin").exists()
    if not php:
        print("[SKIP] 未检测到 php CLI（本机无法运行 PHP 后端基线）")
        return SKIP_CODE
    if not go and not prebuilt:
        print("[SKIP] 未检测到 go 工具链，且无随包预编译二进制（仅限 linux/amd64）")
        return SKIP_CODE
    print(f"[INFO] php={'✓' if php else '✗'} go={'✓' if go else '预编译二进制'}")

    cmd = [sys.executable, str(RUNNER)]
    json_path = None
    if args.keep_json:
        results_dir = BASELINE_DIR / "results"
        results_dir.mkdir(exist_ok=True)
        json_path = results_dir / "ci_baseline_check.json"
        cmd += ["--json", str(json_path)]

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env)  # noqa: S603 - 固定脚本
    if proc.returncode == 0 and json_path:
        print(f"[INFO] 比对结果 JSON：{json_path}")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
