# -*- coding: utf-8 -*-
"""按当前系统挑选替换引擎 —— 全工程唯一的引擎选择入口。

为什么需要这个模块：包里同时带了两个平台的 Go 引擎二进制
（``replace_by_go-linux-amd64`` 与 ``replace_by_go-windows-amd64.exe``）。
在 Windows 上如果还按 Linux 的文件名去取，``exists()`` 会返回真（那个文件
确实在包里），于是一路放行到真正执行时才炸：Windows 会报
``OSError: [WinError 193] %1 不是有效的 Win32 应用程序``。
所以取引擎必须**按平台判断**，而且只能有这一处判断，避免两处各写一份再走岔。

对外只暴露 ``select_engine(bin_dir)`` 与 ``unsupported_reason()`` 两个函数。
"""

from __future__ import annotations

import sys
from pathlib import Path

#: Linux 引擎文件名
LINUX_NAME = "replace_by_go-linux-amd64"
#: Windows 引擎文件名
WINDOWS_NAME = "replace_by_go-windows-amd64.exe"


def select_engine(bin_dir: Path) -> Path | None:
    """按当前平台返回该用的引擎路径；找不到或系统不支持时返回 ``None``。

    关键点：**先按平台定文件名，再看文件在不在**。绝不写成
    「把两个名字都试一遍、谁先存在用谁」——那样在两个引擎并存的包里，
    Windows 会先命中 Linux 版，又回到 WinError 193 的老路上。
    """
    bin_dir = Path(bin_dir)
    if sys.platform == "win32":
        candidate = bin_dir / WINDOWS_NAME
    elif sys.platform.startswith("linux"):
        candidate = bin_dir / LINUX_NAME
    else:
        # macOS 等：包里没有对应二进制，明确返回 None，由上层给出人话提示
        return None
    return candidate if candidate.is_file() else None


def unsupported_reason() -> str:
    """取不到引擎时给人看的原因（不要暴露堆栈，也不要说「检查 chmod +x」这类 Linux 专属建议）。"""
    if sys.platform == "win32":
        return (
            "缺少替换引擎：包里应带 replace_by_go-windows-amd64.exe。"
            "请确认软件目录完整（可能被杀毒软件误删），或重新解压一份。"
        )
    if sys.platform.startswith("linux"):
        return (
            "缺少替换引擎：包里应带 replace_by_go-linux-amd64。"
            "请确认软件目录完整；若文件存在却无法运行，可能需要执行权限（chmod +x）。"
        )
    return (
        f"当前系统（{sys.platform}）暂不支持自动校正："
        "软件包里只提供了 Windows 与 Linux 的替换引擎。"
    )
