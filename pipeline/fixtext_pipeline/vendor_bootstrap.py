"""vendor 引擎的导入引导。

编排器本身不含任何引擎实现，全部复用 M1 各卡的模块：

* ``epubtext``            —— T1.3 EPUB 合并 / 还原 / 校验
* ``fixtext_layout``      —— T1.2 排版引擎
* ``fixtext_quotation``   —— T1.4 引号检查
* ``fixtext_bookmap``     —— T1.5 专有词库生成
* ``fixtext.engine``      —— T0.3 Go 引擎子进程协议

引擎既可以装进 site-packages，也可以直接放在产品目录的 ``vendor/`` 下。
本模块在两种情况下都能工作：先试直接 import，失败再把 ``vendor/`` 加进
``sys.path`` 重试一次。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

#: 需要引导的模块 -> 缺少时的提示
REQUIRED_MODULES = {
    "epubtext": "T1.3 EPUB 合并/还原模块",
    "fixtext_layout": "T1.2 排版引擎",
    "fixtext_quotation": "T1.4 引号检查模块",
    "fixtext_bookmap": "T1.5 专有词库生成模块",
    "fixtext.engine": "T0.3 Go 引擎集成层",
}


def vendor_dir(root: Path | None = None) -> Path:
    """产品目录下的 ``vendor/`` 路径。"""
    if root is None:
        root = Path(__file__).resolve().parent.parent
    return Path(root) / "vendor"


def bootstrap(root: Path | None = None, *, strict: bool = True) -> list[str]:
    """保证所有引擎模块可导入。

    :return: 实际从 ``vendor/`` 引导成功的模块名列表（空列表表示环境里已装好）。
    :raises ImportError: ``strict=True`` 且仍缺模块时抛出。
    """
    vdir = vendor_dir(root)
    if vdir.is_dir() and str(vdir) not in sys.path:
        sys.path.insert(0, str(vdir))

    missing: list[str] = []
    for name in REQUIRED_MODULES:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)

    if missing and strict:
        detail = "、".join(f"{m}（{REQUIRED_MODULES[m]}）" for m in missing)
        raise ImportError(
            f"缺少引擎模块：{detail}。请把对应引擎包放到 {vdir} 下，"
            "或先安装到当前 Python 环境。"
        )
    return [m for m in REQUIRED_MODULES if m not in missing]
