"""日志初始化：统一格式与控制台 / 文件双通道。

骨架阶段只建立基础通道，日志目录通过 paths 模块解析，不写死路径。
"""

from __future__ import annotations

import logging
import sys

from fixtext.common.paths import log_dir

_CONSOLE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_FILE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"


def setup_logging(level: str = "INFO", log_to_file: bool = True) -> None:
    """配置根 logger。重复调用安全（幂等）。"""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not any(getattr(h, "_fixtext_console", False) for h in root.handlers):
        console = logging.StreamHandler(stream=sys.stderr)
        console.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
        console._fixtext_console = True  # type: ignore[attr-defined]
        root.addHandler(console)

    if log_to_file and not any(getattr(h, "_fixtext_file", False) for h in root.handlers):
        try:
            target = log_dir() / "fixtext.log"
            file_handler = logging.FileHandler(target, encoding="utf-8")
        except OSError:
            # 日志目录不可写时降级为仅控制台，不阻断启动
            return
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        file_handler._fixtext_file = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)
