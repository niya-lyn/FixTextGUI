"""运行时目录解析（M4-T4.4 写路径收口）。

原则（承接排期文档 2.3「只读保护」，M4-T4.4 写路径审计）：

* 应用产生的数据**只允许**落在这四类位置：
  ``<包根>/workspace/``（用户区）、``<包根>/runs/``（运行产物）、
  ``<包根>/logs/``（日志）、以及用户显式选择的导出目录；
* **不写系统用户数据目录**（``~/.local/share`` / ``LOCALAPPDATA`` /
  ``Application Support`` / ``XDG_DATA_HOME``）——绿色分发要求整棵包搬走即可，
  数据跟着包走；写系统目录属于越界写，M4-T4.4 起已修掉；
* 也不触碰用户导入的原始文件路径。

``FIXTEXT_LOG_DIR`` 可显式覆盖日志目录（验收脚本用它把日志指到临时目录，
避免污染交付包）。
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "FixText"

_HERE = Path(__file__).resolve().parent
_PKG_MARKERS = ("main_app.py", "data", "fixtext_ui")


def app_root() -> Path:
    """包根（绿色分发的可搬走目录）。

    按「向上找标记」解析，源码树与解包后的分发树都能定位到同一个根；
    找不到标记时退回本文件所在的 ``.../fixtext/common/paths.py`` 的第四层父目录。
    """
    for cand in _HERE.parents:
        if all((cand / m).exists() for m in _PKG_MARKERS):
            return cand
    parents = _HERE.parents
    return parents[4] if len(parents) > 4 else parents[-1]


def app_data_dir() -> Path:
    """应用数据根目录（= 包根；数据跟着包走，不写系统用户目录）。"""
    target = app_root()
    target.mkdir(parents=True, exist_ok=True)
    return target


def log_dir() -> Path:
    """日志目录：``<包根>/logs/``（可用 FIXTEXT_LOG_DIR 覆盖）。"""
    override = os.environ.get("FIXTEXT_LOG_DIR")
    target = Path(override) if override else (app_data_dir() / "logs")
    target.mkdir(parents=True, exist_ok=True)
    return target
