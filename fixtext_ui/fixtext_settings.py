"""应用设置落点（M4-T4.4 写路径收口）。

问题：原先首启向导的「看过没有」用 ``QSettings("FixText", "V1")`` 存，
Qt 会把它写到**操作系统的配置目录**（Linux ``~/.config/FixText/V1.conf``、
Windows 注册表或 ``%APPDATA%``、macOS ``~/Library/Preferences``）——那是
包根之外的位置，与「绿色分发、整棵包搬走即可」冲突，也过不了写路径审计
（写点只允许 workspace / runs / logs / 用户显式选择的导出目录）。

做法：设置一律存进**用户区** ``<包根>/workspace/settings.ini``（IniFormat，
纯文本、可随包搬走）。``FIXTEXT_SETTINGS_FILE`` 可显式指定文件，
验收脚本用它把每个阶段的状态隔离开。

兼容：对外仍是 ``QSettings`` 的子类，``QSettings("FixText", "V1")`` 这种
两参数调用照旧可用（参数被忽略，落点固定为用户区文件），所以界面代码与
既有脚本不需要改调用形态。
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings

PKG_ROOT = Path(__file__).resolve().parent.parent
#: 用户区里的设置文件名（不是内置词库那棵 ``data/rules/`` 子树）
SETTINGS_FILE = "settings.ini"


def settings_path() -> Path:
    """设置文件路径：``FIXTEXT_SETTINGS_FILE`` 优先，否则用户区 ``workspace/``。"""
    override = os.environ.get("FIXTEXT_SETTINGS_FILE")
    if override:
        target = Path(override)
    else:
        target = PKG_ROOT / "workspace" / SETTINGS_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


class AppSettings(QSettings):
    """固定落在用户区的设置对象（IniFormat，忽略组织 / 应用名参数）。"""

    def __init__(self, *args, **kwargs):        # noqa: D401 - 参数仅为调用形态兼容
        super().__init__(str(settings_path()), QSettings.Format.IniFormat)
