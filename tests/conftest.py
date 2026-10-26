"""先于 Qt 插件的测试环境准备：强制无头平台，避免 CI/容器缺少显示服务。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 必须在导入 PySide6 之前设置
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
