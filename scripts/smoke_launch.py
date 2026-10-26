#!/usr/bin/env python3
"""空壳应用启动冒烟：以 QT_QPA_PLATFORM=offscreen 真实启停一次。

与单测不同，这里走独立进程，验证的是「双击启动 → 正常退出」这条真实路径，
而不是进程内构造窗口。

用法：
    python scripts/smoke_launch.py [--timeout 30]
退出码：0 = 正常退出；非 0 = 启动失败或超时。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FixText 空壳应用启动冒烟")
    parser.add_argument("--timeout", type=int, default=30, help="超时秒数（默认 30）")
    parser.add_argument("--auto-exit-ms", type=int, default=1200, help="自动退出前运行毫秒数")
    args = parser.parse_args(argv)

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC) + (os.pathsep + existing if existing else "")

    cmd = [
        sys.executable,
        "-m",
        "fixtext.app",
        "--smoke-test",
        str(args.auto_exit_ms),
        "--log-level",
        "WARNING",
    ]
    print(f"启动：QT_QPA_PLATFORM=offscreen {' '.join(cmd)}")
    try:
        proc = subprocess.run(  # noqa: S603 - 固定命令
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"失败：启动超过 {args.timeout}s 未退出", file=sys.stderr)
        return 1

    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        print(f"失败：退出码 {proc.returncode}", file=sys.stderr)
        if output:
            print(output, file=sys.stderr)
        return proc.returncode or 1

    print("通过：进程已正常启动并退出，退出码 0")
    if output:
        print("进程输出：")
        for line in output.splitlines():
            print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
