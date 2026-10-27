"""FixText V1 · 导入模块的兼容入口（M2-T2.5 合并后）

T2.2 交付时，本文件提供一个「只含导入书籍一个模块」的最小宿主，用于主窗口
框架尚未交付时独立验证导入链路；并另外提供 `attach_to_main_window()` 把导入
模块挂进主窗口。

M2-T2.5 合并后，宿主已经统一为 `main_window.MainWindow`（顶栏 + 六入口左轨 +
内容区，唯一一份 chrome）。本文件因此只剩两件事：

1. `HostWindow` 作为 `MainWindow` 的别名——旧调用点（脚本 / 文档里的
   `from host_window import HostWindow`）继续可用，但拿到的就是合并后的主窗口，
   不再有第二套界面；
2. `attach_to_main_window()` 保留为薄转发——真实挂载逻辑只有一份，在
   `main_window.MainWindow.mount_import()` 里。

**不再引用任何双份常量**：T2.2 的宿主原本从令牌取 `MODULES`（7 项 tuple 列表），
而 T2.1 的令牌把这组数据叫 `ENTRIES`（带 status / 人话文案的 dict）。
合并口径是「以 `ENTRIES` 为唯一来源」，本文件与全包因此都不再出现 `MODULES`。
"""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from main_window import MainWindow, load_qss

#: 旧名字的别名（同一个类，不是第二套界面）
HostWindow = MainWindow


def attach_to_main_window(window, workspace: str | os.PathLike | None = None):
    """把导入模块挂进主窗口的「导入书籍」页（转发到 MainWindow.mount_import）。"""
    mount = getattr(window, "mount_import", None)
    if mount is None:
        raise RuntimeError("这个主窗口没有导入页，无法挂载导入模块")
    return mount(workspace)


def main() -> None:
    app = QApplication(sys.argv)
    load_qss(app)
    win = MainWindow()
    win.show()
    win.go("import")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
