"""包根解析（``fixtext_pipeline`` 子树自用，M4-T4.1b）。

这一棵子树要求「脱离上层 UI 也能单独跑」（命令行管线可用），所以不依赖上层
的 ``fixtext_paths``，自带一份等价逻辑：源码态 ``parents[2]`` 是包根，
打包态是可执行文件所在目录；同样支持 ``FIXTEXT_PKG_ROOT`` 覆盖。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

#: 包根覆盖环境变量名（与上层 ``fixtext_paths`` 保持一致）
ENV_PKG_ROOT = "FIXTEXT_PKG_ROOT"


def pkg_root() -> Path:
    """包根目录：环境变量 > 打包后的可执行文件目录 > 源码目录。"""
    override = os.environ.get(ENV_PKG_ROOT)
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # 本文件位于 <包根>/pipeline/fixtext_pipeline/ 下，向上两级即包根
    return Path(__file__).resolve().parents[2]
