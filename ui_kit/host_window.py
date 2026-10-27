"""FixText V1 · 导入模块的最小宿主窗口（T2.2）

**用途**：T2.1 主窗口框架若尚未交付，本文件提供一个只包含「导入书籍」一个模块
的可运行宿主，用来独立验证导入链路与界面；若 T2.1 的 `main_window.py` 已交付，
则直接把 `ImportModule` 挂进它的 `pages["import"]`（见文末 `attach_to_main_window`），
不需要两份界面。

设计：与 T2.1 骨架使用**同一套** chrome 令牌与 QSS（`fixtext_tokens` / `fixtext.qss`），
所以两边的顶栏、左轨、卡片样式天然一致，接线时不会出现视觉漂移。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtext_tokens import MODULES, c, fs
from import_module import ImportModule, install_global_drop

HERE = Path(__file__).resolve().parent
QSS_PATH = HERE / "fixtext.qss"


class HostWindow(QMainWindow):
    """最小宿主：顶栏 + 左轨（六入口可见，仅导入可用）+ 导入页。"""

    def __init__(self, workspace: str | Path | None = None):
        super().__init__()
        self.setWindowTitle("FixText · 导入书籍")
        self.resize(1180, 820)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QWidget()
        top.setObjectName("TopBar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 0, 12, 0)
        brand = QPushButton("F  FixText")
        brand.setObjectName("Brand")
        brand.setCursor(Qt.CursorShape.PointingHandCursor)
        brand.clicked.connect(lambda: self.go("import"))
        tl.addWidget(brand)
        tl.addStretch(1)
        hint = QLabel("把书拖进窗口任意位置都能导入")
        hint.setStyleSheet("color:#C2CAD6;font-size:13px")
        tl.addWidget(hint)
        root.addWidget(top)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        rail = QWidget()
        rail.setObjectName("Rail")
        rail.setFixedWidth(212)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(8, 12, 8, 12)
        rl.setSpacing(2)
        rt = QLabel("功能导航")
        rt.setObjectName("RailTitle")
        rl.addWidget(rt)
        self.rail_items: dict[str, QPushButton] = {}
        for key, icon, label in MODULES:
            item = QPushButton(f"{icon}  {label}")
            item.setObjectName("RailItem")
            item.setProperty("active", "false")
            item.setEnabled(key == "import")
            item.setMinimumHeight(34)
            if key == "import":
                item.setCursor(Qt.CursorShape.PointingHandCursor)
            self.rail_items[key] = item
            rl.addWidget(item)
        rl.addStretch(1)
        note = QLabel("本窗口只承载导入模块\n（T2.1 主框架交付后整体并入）")
        note.setStyleSheet(f"color:{c('neutral.400')};font-size:{fs('xs')}")
        note.setWordWrap(True)
        rl.addWidget(note)
        body.addWidget(rail)

        self.stack = QStackedWidget()
        self.stack.setObjectName("Content")
        self.import_module = ImportModule(workspace)
        self.stack.addWidget(self.import_module)
        body.addWidget(self.stack, 1)
        root.addLayout(body)

        install_global_drop(self, self.import_module)
        self.go("import")

    def go(self, key: str) -> None:
        self.stack.setCurrentWidget(self.import_module)
        for k, item in self.rail_items.items():
            item.setProperty("active", "true" if k == key else "false")
            item.style().unpolish(item)
            item.style().polish(item)

    def closeEvent(self, event):
        self.import_module.shutdown()
        super().closeEvent(event)


def attach_to_main_window(window, workspace: str | Path | None = None) -> ImportModule:
    """把导入模块挂进 T2.1 的 MainWindow（替换其占位页）。

    用法（T2.1 已交付后）：

        from main_window import MainWindow
        from import_module import attach_to_main_window

        win = MainWindow()
        module = attach_to_main_window(win)

    实现方式：找到 `MainWindow.pages["import"]`（滚动区），把其中的占位部件
    换成 ImportModule；同时给整个窗口装全局拖放并切页到 import。
    """
    scroll = window.pages.get("import") if hasattr(window, "pages") else None
    if scroll is None:
        raise RuntimeError("这个主窗口没有 import 页，无法挂载导入模块")

    module = ImportModule(workspace)
    holder = QWidget()
    hl = QVBoxLayout(holder)
    hl.setContentsMargins(20, 20, 20, 20)
    hl.setSpacing(16)
    hl.addWidget(module)
    hl.addStretch(1)
    scroll.setWidget(holder)

    install_global_drop(window, module, goto_page=getattr(window, "go", None))
    window.import_module = module
    original_close = window.closeEvent

    def close_event(event):
        module.shutdown()
        original_close(event)

    window.closeEvent = close_event
    return module


def main() -> None:
    app = QApplication(sys.argv)
    if QSS_PATH.exists():
        app.setStyleSheet(QSS_PATH.read_text(encoding="utf-8"))
    win = HostWindow(os.environ.get("FIXTEXT_WORKSPACE"))
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
