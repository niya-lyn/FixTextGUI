"""运行时目录解析。

原则（承接排期文档 2.3「只读保护」）：应用产生的数据一律落在用户数据目录，
绝不写入安装目录，也不触碰用户导入的原始文件路径。

骨架阶段只提供路径解析能力，不创建业务目录结构。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "FixText"


def _base_data_dir() -> Path:
    """按平台返回用户数据根目录。"""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base)
        return Path.home() / "AppData" / "Local"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".local" / "share"


def app_data_dir() -> Path:
    """应用数据根目录（不存在时按需创建）。"""
    target = _base_data_dir() / APP_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def log_dir() -> Path:
    """日志目录。"""
    target = app_data_dir() / "logs"
    target.mkdir(parents=True, exist_ok=True)
    return target
