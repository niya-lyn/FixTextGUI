"""界面截图脚本（T2.2 证据采集）

用离屏 Qt 依次走到各个界面状态并抓图，供验收核对：
- 01 初始（空态）
- 02 选中 TXT（拖放通道的等价状态）
- 03 EPUB 处理方式询问
- 04 EPUB 章节预览
- 05 EPUB 导入完成
- 06 TXT 导入完成（含技术核对展开）

用法：
    PYTHONPATH=.:ui_kit:<pyside6路径> QT_QPA_PLATFORM=offscreen python3 tools/shoot.py <样本目录> <输出目录>
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_kit"))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from host_window import HostWindow  # noqa: E402

SHOTS = Path(sys.argv[2] if len(sys.argv) > 2 else ROOT / "evidence" / "shots")
SAMPLES = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "tests" / "samples")
SHOTS.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv[:1])
app.setStyleSheet((ROOT / "ui_kit" / "fixtext.qss").read_text(encoding="utf-8"))

workspace = Path(os.environ.get("FIXTEXT_SHOT_WS", "/tmp/fixtext_shot_ws"))
win = HostWindow(workspace)
win.resize(1180, 940)
win.show()


def settle(ms: int = 240) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def shot(name: str) -> None:
    settle()
    path = SHOTS / name
    win.grab().save(str(path))
    print(f"[shot] {name}  {path.stat().st_size / 1024:.0f} KB")


def wait_idle(timeout: float = 60.0) -> None:
    """等待后台导入线程结束（界面回到可操作状态）。"""
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if win.import_module._thread is None:
            settle(400)
            return
        time.sleep(0.02)
    raise SystemExit("后台任务超时")


m = win.import_module

# 01 初始
shot("01_initial.png")

# 02 选中 TXT（走 _take_file，等价于拖放 / 选择文件两条通道的汇合点）
m._take_file(str(SAMPLES / "e_gbk_lf.txt"))
shot("02_txt_selected.png")

# 03 EPUB 处理方式询问
m._take_file(str(SAMPLES / "book_paohuo.epub"))
shot("03_epub_choice.png")

# 04 EPUB 章节预览（点「看一下章节」）
m._next()
wait_idle()
shot("04_epub_chapters.png")

# 05 EPUB 导入完成（章节预览页点「开始导入」）
m._next()
shot("05_epub_progress.png")
wait_idle(120)
shot("06_epub_result.png")

# 06b 结果页展开技术核对
m.result_pane.detail_toggle.setChecked(True)
m.result_pane._toggle_detail()
shot("07_epub_result_detail.png")

# 07 TXT 导入完成
m._reset()
m._take_file(str(SAMPLES / "d_gbk_crlf.txt"))
m._next()
wait_idle()
shot("08_txt_result.png")
m.result_pane.detail_toggle.setChecked(True)
m.result_pane._toggle_detail()
shot("09_txt_result_detail.png")

print("done")
