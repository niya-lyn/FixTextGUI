# -*- coding: utf-8 -*-
"""验收脚本的跨平台环境探测（P2-4）。

原先若干 ``accept_*.py`` 写死 Linux 路径（``/home/gem/...``、``/tmp/...``、
``replace_by_go-linux-amd64``），在 Windows 上直接失败或误取引擎。
本模块统一：

* Qt site-packages：环境变量 ``FX_Q`` / ``FIXTEXT_QT_SITE`` → 已安装的 PySide6
* 临时目录：``tempfile.gettempdir()``，不再假定 ``/tmp``
* 替换引擎：走 ``select_engine``，按平台取二进制
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def qt_site_packages() -> str:
    """PySide6 所在的 site-packages 目录；找不到返回空串。"""
    for key in ("FX_Q", "FIXTEXT_QT_SITE"):
        raw = (os.environ.get(key) or "").strip()
        if raw and Path(raw).is_dir():
            return str(Path(raw).resolve())
    try:
        import PySide6  # noqa: PLC0415
        return str(Path(PySide6.__file__).resolve().parent.parent)
    except Exception:  # noqa: BLE001
        return ""


def tmp_root(*parts: str) -> Path:
    """本机临时目录下的路径（Windows / Linux / macOS 通用）。"""
    return Path(tempfile.gettempdir()).joinpath(*parts)


def env_file(name: str, *candidates: Path) -> Path | None:
    """优先读环境变量 ``name``；否则取第一个存在的候选文件。"""
    raw = (os.environ.get(name) or "").strip()
    if raw:
        p = Path(raw)
        if p.is_file():
            return p
    for c in candidates:
        if c is not None and Path(c).is_file():
            return Path(c)
    return None


def env_dir(name: str, *candidates: Path) -> Path | None:
    """优先读环境变量 ``name``；否则取第一个存在的候选目录。"""
    raw = (os.environ.get(name) or "").strip()
    if raw:
        p = Path(raw)
        if p.is_dir():
            return p
    for c in candidates:
        if c is not None and Path(c).is_dir():
            return Path(c)
    return None


def select_go_engine(pkg: Path) -> Path | None:
    """按当前平台取包内 Go 替换引擎；不支持的系统返回 ``None``。"""
    bin_dir = (Path(pkg) / "pipeline" / "vendor" / "fixtext"
               / "engine" / "go_src" / "bin")
    try:
        from fixtext_pipeline.engine_selector import select_engine  # noqa: PLC0415
        return select_engine(bin_dir)
    except Exception:  # noqa: BLE001
        # 退化：直接按平台拼文件名（与 engine_selector 口径一致）
        if sys.platform == "win32":
            name = "replace_by_go-windows-amd64.exe"
        elif sys.platform.startswith("linux"):
            name = "replace_by_go-linux-amd64"
        else:
            return None
        cand = bin_dir / name
        return cand if cand.is_file() else None
