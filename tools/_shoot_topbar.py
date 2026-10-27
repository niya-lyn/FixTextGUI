"""按 M2-T2.6 同口径重拍顶栏三张展开态截图（无正式脚本，此处补齐可复现）。

顶栏三个按钮都是 exec() 阻塞弹窗，所以用 QTimer 在弹窗出现后抓图再关。
产出 screenshots/08_topbar_help_open.png / 09_topbar_settings_open.png /
10_topbar_menu_open.png
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(PKG), str(PKG / "fixtext_ui"), str(PKG / "fixtext_import")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer                      # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMenu  # noqa: E402

app = QApplication.instance() or QApplication([])
import main_window as mw                              # noqa: E402

SHOTS = PKG / "screenshots"
SHOTS.mkdir(exist_ok=True)


def shoot_modal(fn, name: str) -> str:
    """点开一个模态弹窗，抓它本体后关掉。"""
    holder: dict = {}

    def grab_and_close():
        for w in app.topLevelWidgets():
            if isinstance(w, QDialog) and w.isVisible():
                holder["p"] = str(SHOTS / name)
                w.grab().save(holder["p"])
                w.accept()
                return
        QTimer.singleShot(120, grab_and_close)

    QTimer.singleShot(220, grab_and_close)
    fn()
    return holder.get("p", "")


win = mw.MainWindow()
app.processEvents()

made = []
p = shoot_modal(win._act_help, "08_topbar_help_open.png")
made.append(("08_topbar_help_open.png", p))

# 设置：Modal 也是 exec()；用同样办法抓
p2 = shoot_modal(lambda: win._act_settings(), "09_topbar_settings_open.png")
made.append(("09_topbar_settings_open.png", p2))

# 菜单：QMenu 是弹出层，exec 阻塞，用 showEvent 抓
menu_holder: dict = {}


def grab_menu():
    for w in win.findChildren(QMenu):
        if w.isVisible():
            menu_holder["p"] = str(SHOTS / "10_topbar_menu_open.png")
            w.grab().save(menu_holder["p"])
            w.close()
            return
    QTimer.singleShot(120, grab_menu)


QTimer.singleShot(220, grab_menu)
win._act_more()
made.append(("10_topbar_menu_open.png", menu_holder.get("p", "")))

for n, path in made:
    ok = bool(path) and Path(path).is_file() and Path(path).stat().st_size > 2000
    print(f"{'OK ' if ok else 'FAIL'} {n}  bytes={Path(path).stat().st_size if path and Path(path).is_file() else 0}")
win.close()
