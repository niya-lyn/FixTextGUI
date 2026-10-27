"""FixText V1 · 导入模块的「可接受？」快捷判断（T2.2）

拖放时需要在**不读文件内容**的前提下回答"这个文件我能接吗"，只在 dragEnter
阶段用；真正导入前仍会走 `detect_kind` 的完整校验。
"""

from __future__ import annotations

from pathlib import Path

SUPPORTED_SUFFIXES = {".txt", ".epub"}


def detect_kind_safe(path: str | Path) -> bool:
    """文件后缀是 TXT / EPUB 且确实存在，返回 True（不做内容校验）。"""
    p = Path(path)
    try:
        return p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    except OSError:
        return False
