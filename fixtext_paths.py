"""包根解析的唯一入口（M4-T4.1b 打包适配）。

源码运行时包根就是本文件所在目录；打包（PyInstaller onedir）后 ``__file__``
指向程序内部目录，各模块靠 ``Path(__file__).parent.parent`` 反推会算错一层，
词库 / 引擎 / 用户区全都找不到。这里统一按可执行文件所在目录解析，
并允许用环境变量 ``FIXTEXT_PKG_ROOT`` 覆盖（便于把用户区搬到别处）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

#: 包根覆盖环境变量名
ENV_PKG_ROOT = "FIXTEXT_PKG_ROOT"


def is_frozen() -> bool:
    """当前进程是否由 PyInstaller 打包运行。"""
    return bool(getattr(sys, "frozen", False))


def pkg_root() -> Path:
    """包根目录：环境变量 > 打包后的可执行文件目录 > 源码目录。"""
    override = os.environ.get(ENV_PKG_ROOT)
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent
