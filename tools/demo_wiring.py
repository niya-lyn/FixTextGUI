#!/usr/bin/env python3
"""M2-T2.4 接线演示：错误体系如何接入主程序（T2.1–T2.3 / M3 各卡的统一形态）。

这是一个可运行的最小样例（离屏可跑）：
    QT_QPA_PLATFORM=offscreen python3.12 tools/demo_wiring.py

演示三种接法：
1. 启动时安装（init + install_app_hooks + set_dialog_host）；
2. 槽函数 @guard 包裹 —— 异常自动「归类→日志→错误卡」，界面只见人话；
3. 长任务 worker 里主动 report（含 worker 线程跨线程投递弹卡）。

真实接线时把本文件的三段代码搬进 main.py / 各模块页即可。
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

import fixtext_error_center as error_center

app = QApplication([])

# ---- 接法 1：启动时安装（真实接线放在 main.py，QApplication 之后、show 之前）----
error_center.init(os.path.join(tempfile.gettempdir(), "fixtext_demo_logs"))
error_center.install_app_hooks()

win = QMainWindow()
central = QWidget()
win.setCentralWidget(central)
lay = QVBoxLayout(central)
lay.addWidget(QLabel("演示窗口：点下面的按钮制造错误，看错误卡是否只有人话"))


# ---- 接法 2：槽函数 @guard 包裹 ----
@error_center.guard
def on_import_clicked():
    # 模拟导入时文件损坏：这里随 UI 层判定直接抛带码异常
    raise error_center.UserFacingError("U-I02", safe_hint="《下载不完整的书》.epub")


btn = QPushButton("导入（会触发文件损坏错误）")
btn.clicked.connect(on_import_clicked)
lay.addWidget(btn)


# ---- 接法 3：长任务 worker 主动上报（跨线程自动投递到主线程弹卡）----
def run_long_job():
    def worker():
        try:
            time.sleep(0.2)
            raise OSError(28, "No space left on device /dev/sda9")  # 模拟磁盘写满
        except OSError as exc:
            error_center.report(exc, context="processing")

    threading.Thread(target=worker, daemon=True).start()


btn2 = QPushButton("处理（worker 线程触发磁盘不足）")
btn2.clicked.connect(run_long_job)
lay.addWidget(btn2)

error_center.set_dialog_host(win)
win.show()

# 自动化演示（无头环境）：依次触发两个按钮路径并截图
from PySide6.QtCore import QTimer

from fixtext_error_center import qt_bridge

QTimer.singleShot(200, btn.click)
QTimer.singleShot(800, btn2.click)
QTimer.singleShot(1600, lambda: qt_bridge._active_card and qt_bridge._active_card.grab().save(
    os.path.join(BASE, "evidence", "demo_wiring.png")))
QTimer.singleShot(2000, app.quit)
app.exec()

rec = error_center.last_record()
print("最后一条日志记录：code=%s exc_type=%s" % (rec["code"], rec["exc_type"]))
print("（真实接线：把上面三段搬进 main.py 与各模块页，界面不写任何 str(exc)）")
