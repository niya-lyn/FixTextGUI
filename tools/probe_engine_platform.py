# -*- coding: utf-8 -*-
"""纯逻辑探针：验证按平台选引擎、两引擎并存时 Windows 不回落 Linux。

用法：``python3.12 tools/probe_engine_platform.py``（无需 Qt，无需真窗口）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src" / "bin"

sys.path.insert(0, str(ROOT / "pipeline"))

from fixtext_pipeline import engine_selector  # noqa: E402


def run_as(platform: str, bin_dir: Path) -> tuple[str, str]:
    """把 ``sys.platform`` 换成给定值跑一次选择，返回 (结果, 说明)。"""
    real = sys.platform
    sys.platform = platform
    try:
        got = engine_selector.select_engine(bin_dir)
        reason = "" if got else engine_selector.unsupported_reason()
        return (str(got) if got else "None"), reason
    finally:
        sys.platform = real


def main() -> int:
    ok = True

    print(f"引擎目录: {BIN}")
    print(f"  实际存在的引擎: {sorted(p.name for p in BIN.glob('replace_by_go-*'))}")
    has_win = (BIN / engine_selector.WINDOWS_NAME).is_file()
    has_linux = (BIN / engine_selector.LINUX_NAME).is_file()
    print(f"  Windows 引擎在: {has_win} / Linux 引擎在: {has_linux}")
    if has_win and has_linux:
        print("  → 两种引擎并存，这正是最容易选错的场景")
    print()

    cases = [
        ("win32", "replace_by_go-windows-amd64.exe"),
        ("linux", "replace_by_go-linux-amd64"),
        ("linux2", "replace_by_go-linux-amd64"),   # 老版本 Python 报 linux2，应等同 linux
        ("darwin", None),
        ("freebsd13", None),
    ]
    for plat, expect_name in cases:
        got, reason = run_as(plat, BIN)
        base = Path(got).name if got != "None" else "None"
        if expect_name is None:
            passed = base == "None"
        else:
            passed = base == expect_name
        ok = ok and passed
        print(f"[{'PASS' if passed else 'FAIL'}] {plat:10s} -> {base}")
        if reason:
            print(f"            提示={reason}")

    # 反向对照：把 Linux 引擎藏起来，Windows 必须仍然选到 .exe（不能因为没有 Linux 版就报无引擎）
    print()
    print("--- 反向对照：只有 Windows 引擎时，Windows 必须选到它 ---")
    tmp = ROOT / "_probe_only_win"
    tmp.mkdir(exist_ok=True)
    if has_win:
        import shutil
        shutil.copy2(BIN / engine_selector.WINDOWS_NAME, tmp / engine_selector.WINDOWS_NAME)
        got, reason = run_as("win32", tmp)
        base = Path(got).name if got != "None" else "None"
        passed = base == engine_selector.WINDOWS_NAME
        ok = ok and passed
        print(f"[{'PASS' if passed else 'FAIL'}] win32(仅.exe) -> {base}")
        if reason:
            print(f"            提示={reason}")
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        print("[SKIP] 包里没有 Windows 引擎，跳过该项")

    # 反向对照：目录里只有 Linux 版时，Windows 必须返回 None（说明它没有回落 Linux）
    print()
    print("--- 反向对照：目录里只有 Linux 版时，Windows 必须返回 None（证明不回落）---")
    tmp2 = ROOT / "_probe_only_linux"
    tmp2.mkdir(exist_ok=True)
    if has_linux:
        import shutil
        shutil.copy2(BIN / engine_selector.LINUX_NAME, tmp2 / engine_selector.LINUX_NAME)
        got, reason = run_as("win32", tmp2)
        passed = got == "None"
        ok = ok and passed
        print(f"[{'PASS' if passed else 'FAIL'}] win32(仅ELF) -> {got}  ← 必须是 None")
        if reason:
            print(f"            提示={reason}")
        shutil.rmtree(tmp2, ignore_errors=True)
    else:
        print("[SKIP] 包里没有 Linux 引擎，跳过该项")

    print()
    print("PROBE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
