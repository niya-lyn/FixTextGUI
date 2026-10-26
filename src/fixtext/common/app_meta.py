"""应用级常量：名称、组织、版本占位。

集中在此处，避免窗口、日志、打包脚本各自硬编码。
"""

from __future__ import annotations

from fixtext import __version__

APP_NAME = "FixText"
ORG_NAME = "FixText"
APP_VERSION = __version__

# 首屏六个入口（对应排期文档 2.2），骨架阶段仅占位，不代表已实现功能。
ENTRY_LABELS: tuple[str, ...] = (
    "导入书籍",
    "一键校正",
    "检查问题",
    "词库管理",
    "导出结果",
    "历史记录",
)
