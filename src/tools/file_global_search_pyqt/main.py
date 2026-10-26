import os
import sys
import ctypes
import logging

TARGET_API = os.environ.get("QT_API", "pyqt5").lower()

if TARGET_API == "pyqt5":
    import PyQt5

    dirname = os.path.dirname(PyQt5.__file__)
    plugin_path = os.path.join(dirname, "Qt5", "plugins")
elif TARGET_API == "pyside6":
    import PySide6

    dirname = os.path.dirname(PySide6.__file__)
    plugin_path = os.path.join(dirname, "Qt", "plugins")

os.environ["QT_PLUGIN_PATH"] = plugin_path

from qtpy.QtWidgets import QApplication
from qtpy.QtGui import QIcon, QFont, QGuiApplication
from qtpy.QtCore import Qt, QCoreApplication

import resources.resources_rc

from main_window import MainWindow
from config import QT_SCALE_FACTOR


def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
    """全局捕获【Python 未处理异常】，自动写入日志"""
    if issubclass(exc_type, KeyboardInterrupt):
        # 忽略 Ctrl+C 关闭程序的中断，不记日志
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # 自动记录异常堆栈
    logging.critical("未捕获的 Python 异常", exc_info=(exc_type, exc_value, exc_traceback))


# 自定义 Qt 应用类，捕获【Qt 事件循环/信号槽异常】
class ExceptionApp(QApplication):
    def notify(self, receiver, event):
        """重写 Qt 核心方法，所有界面操作/信号槽都会走这里"""
        try:
            return super().notify(receiver, event)
        except Exception:
            logging.critical("未捕获的 Qt 界面/信号槽异常", exc_info=True)
            return False


def main():
    if sys.platform == "win32":
        myappid = "fix_text.file_global_search"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    os.environ["QT_SCALE_FACTOR"] = QT_SCALE_FACTOR

    if TARGET_API == "pyside6":
        if hasattr(QGuiApplication, "setHighDpiScaleFactorRoundingPolicy"):
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)
    else:
        if hasattr(Qt, "AA_EnableHighDpiScaling"):
            QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        if hasattr(Qt, "AA_UseHighDpiPixmaps"):
            QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        if hasattr(QCoreApplication, "setHighDpiScaleFactorRoundingPolicy"):
            QCoreApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)

    log_file = "运行日志.log"
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.INFO,
        handlers=[
            logging.FileHandler(log_file, mode="w"),  # 文件输出
            logging.StreamHandler(sys.stdout),  # 控制台同步输出
        ],
    )

    sys.excepthook = handle_uncaught_exception

    app = ExceptionApp(sys.argv)
    app.setStyle("Fusion")

    font = QFont()
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)

    window = MainWindow()
    window.setWindowIcon(QIcon("resources/icon.png"))
    window.show()
    window.init_ui_state()  # 在 show 后调用，避免影响图标显示
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
