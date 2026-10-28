#!/usr/bin/env python3
"""FixText V1 · 主程序入口（M2-T2.5 四卡集成）

一个入口把四张卡拼成可运行的程序：

    python main_app.py

启动顺序（与 T2.4 的接线形态一致）：
1. 把包根与 `fixtext_ui/` 放进 `sys.path`（模块之间是平级 import：`fixtext_tokens`
   / `import_module` / `oneclick_module` / `fixtext_import` / `fixtext_error_center`）；
2. 建 QApplication + 加载 `fixtext.qss`；
3. 初始化错误中心：`init(日志目录)` → `install_app_hooks()`；
4. 建主窗口，`set_dialog_host(win)`，show。

目录约定（绿色分发，整体搬走即可）：
    workspace/   导入的书副本与导入记录（用户可见）
    runs/        每次校正的工作目录与替换报告
    logs/        诊断日志（设置页可一键打开）
    data/rules/  词库规则（before / after）
    pipeline/    M1 编排器与引擎（一键校正的真链路）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
UI = HERE / "fixtext_ui"
for p in (str(UI), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", ""))


def ensure_dirs() -> None:
    for name in ("workspace", "runs", "logs"):
        (HERE / name).mkdir(parents=True, exist_ok=True)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from main_window import MainWindow, load_qss  # noqa: PLC0415

    ensure_dirs()
    app = QApplication(sys.argv)
    app.setApplicationName("FixText")
    load_qss(app)

    try:
        import fixtext_error_center as error_center
    except Exception:
        error_center = None

    if error_center is not None:
        try:
            error_center.init(str(HERE / "logs"))
        except Exception:
            pass
        try:
            error_center.install_app_hooks()
        except Exception:
            pass

    win = MainWindow(HERE / "workspace")
    if error_center is not None:
        try:
            error_center.set_dialog_host(win)
        except Exception:
            pass
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
