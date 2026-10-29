# -*- coding: utf-8 -*-
"""Windows 子进程启动参数 —— 避免 CUI 引擎弹出黑控制台窗口。

Go 替换引擎（``replace_by_go-windows-amd64.exe``）链接为 CUI 子系统。
在 GUI / 绿色版（无控制台）里用默认 ``subprocess.Popen`` / ``run`` 启动时，
Windows 会闪一下黑窗口。本模块集中提供 ``CREATE_NO_WINDOW`` 参数，
调用方用 ``**hidden_kwargs()`` 并入即可；非 Windows 返回空字典。
"""

from __future__ import annotations

import subprocess
import sys


#: Win32：不为此进程创建控制台窗口（与 subprocess.CREATE_NO_WINDOW 同值）
_CREATE_NO_WINDOW = 0x08000000


def hidden_kwargs() -> dict:
    """供 ``subprocess.run`` / ``Popen`` 解包的隐藏窗口参数。

    只在 ``win32`` 上返回 ``creationflags``；其它平台返回 ``{}``，
    避免把 Windows 专属参数传到 POSIX。
    """
    if sys.platform != "win32":
        return {}
    flag = getattr(subprocess, "CREATE_NO_WINDOW", _CREATE_NO_WINDOW)
    return {"creationflags": flag}
