"""模块级异常类型。调用方可按类型分别处理，不必解析错误字符串。"""

from __future__ import annotations


class EpubTextError(Exception):
    """本模块所有异常的基类。"""


class EpubStructureError(EpubTextError):
    """EPUB 结构不合法：缺 container/OPF/spine、路径越界、文件缺失等。"""


class BundleFormatError(EpubTextError):
    """合并后的 TXT 不符合 bundle 约定（头部缺失、分块数量不符、索引重复等）。"""


class RestoreError(EpubTextError):
    """还原失败：模板缺少目标文件、编码无法回写、分块与账本不一致等。"""
