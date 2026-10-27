"""应用入口：构建 QApplication、装配主窗口、进入事件循环。

骨架阶段只负责生命周期，不含任何校对业务。
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from fixtext.common.app_meta import APP_NAME, ORG_NAME
from fixtext.common.logging_setup import setup_logging
from fixtext.ui.main_window import MainWindow


def build_application(argv: list[str] | None = None) -> QApplication:
    """返回进程内唯一的 QApplication 实例。

    已存在实例时复用（便于测试中多次调用），否则新建并设置应用元信息。
    """
    existing = QApplication.instance()
    if existing is not None:
        return existing  # type: ignore[return-value]

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationDisplayName(APP_NAME)
    return app


def create_main_window() -> MainWindow:
    """构建主窗口（不显示）。"""
    return MainWindow()


def parse_args(argv: list[str] | None) -> tuple[argparse.Namespace, list[str]]:
    """解析本程序的参数，未知参数原样留给 Qt。"""
    parser = argparse.ArgumentParser(prog="fixtext", description="FixText 中文小说校对工具")
    parser.add_argument(
        "--smoke-test",
        nargs="?",
        type=int,
        const=1500,
        default=None,
        metavar="MS",
        help="以无头模式启动并在指定毫秒后自动退出，用于 CI 验证启动与退出（默认 1500ms）",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别（默认 INFO）",
    )
    return parser.parse_known_args(argv)


def main(argv: list[str] | None = None) -> int:
    args, qt_args = parse_args(argv)
    setup_logging(level=args.log_level)

    app = build_application([sys.argv[0], *qt_args])
    window = create_main_window()
    window.show()

    if args.smoke_test is not None:
        QTimer.singleShot(max(0, args.smoke_test), app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
