"""把随包分发的 `epubtext`（M1-T1.3）加入 sys.path。

打包后 `epubtext` 与本包同级放在 `vendor/` 下，源码运行与 PyInstaller 打包都用这一处，
避免在别处再写一遍路径拼接。
"""

from __future__ import annotations

import sys
from pathlib import Path

_ADDED = False


def vendor_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "vendor"


def ensure_vendor_path() -> None:
    global _ADDED
    if _ADDED:
        return
    d = vendor_dir()
    if d.is_dir() and str(d) not in sys.path:
        sys.path.insert(0, str(d))
    _ADDED = True
