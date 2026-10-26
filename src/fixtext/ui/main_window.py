"""主窗口：首屏六个入口的承载框架。

T0.1 边界：只做窗口骨架、六入口导航与关闭行为，不接任何校对业务逻辑。
后续 T2.1 在此框架上接面板路由，本文件保持结构可扩展。
"""

from __future__ import annotations

import logging

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from fixtext.common.app_meta import APP_NAME, APP_VERSION, ENTRY_LABELS

logger = logging.getLogger(__name__)

WINDOW_MIN_WIDTH = 960
WINDOW_MIN_HEIGHT = 640
NAV_WIDTH = 180


class PlaceholderPanel(QWidget):
    """占位面板：只声明该入口「属于后续任务卡」，不实现功能。"""

    def __init__(self, title: str, note: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(heading)

        body = QLabel(note)
        body.setWordWrap(True)
        body.setStyleSheet("color: #666666;")
        layout.addWidget(body)
        layout.addStretch(1)


class MainWindow(QMainWindow):
    """FixText 主窗口骨架。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        self._nav = self._build_nav()
        self._stack = QStackedWidget()
        self._populate_panels()

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._nav)
        layout.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        self._install_menu()
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("工程骨架 · 尚未实现校对功能")

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)
        logger.info("主窗口已构建，入口数=%d", self._nav.count())

    # --- 构建 ---------------------------------------------------------------

    def _build_nav(self) -> QListWidget:
        nav = QListWidget()
        nav.setObjectName("entryNav")
        nav.setFixedWidth(NAV_WIDTH)
        nav.setStyleSheet(
            "QListWidget { border: none; background: #f5f6f8; }"
            "QListWidget::item { padding: 12px 16px; }"
            "QListWidget::item:selected { background: #e2e8f5; color: #1a4b8c; }"
        )
        for label in ENTRY_LABELS:
            QListWidgetItem(label, nav)
        return nav

    def _populate_panels(self) -> None:
        for label in ENTRY_LABELS:
            self._stack.addWidget(
                PlaceholderPanel(
                    label,
                    f"「{label}」的界面与逻辑由后续任务卡交付；当前为工程骨架占位页。",
                )
            )

    def _install_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件(&F)")
        quit_action = QAction("退出(&Q)", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("帮助(&H)")
        about_action = QAction("关于(&A)", self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    # --- 行为 ---------------------------------------------------------------

    def current_entry_index(self) -> int:
        """当前选中的入口序号（供测试与后续路由使用）。"""
        return self._nav.currentRow()

    def select_entry(self, index: int) -> None:
        """按序号切换入口（供测试与外部跳转使用）。"""
        if 0 <= index < self._nav.count():
            self._nav.setCurrentRow(index)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            f"关于 {APP_NAME}",
            f"{APP_NAME} {APP_VERSION}\n工程骨架版本，尚未包含校对功能。",
        )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名约定
        logger.info("主窗口关闭")
        app = QApplication.instance()
        if app is not None and not app.quitOnLastWindowClosed():
            app.quit()
        super().closeEvent(event)
        event.accept()
