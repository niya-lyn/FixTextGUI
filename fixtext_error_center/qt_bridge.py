"""错误卡的 Qt 呈现层（M2-T2.4）——只显示人话，永不含技术细节。

- ``show_error_card(resolved, parent=None)``：非模态弹出错误卡（不 exec，
  避免无头环境卡死；同一时刻只保留一张，新卡替换旧卡）；
- ``open_log_dir()``：设置页「打开诊断日志目录」动作（QDesktopServices）。

样式优先取 ``fixtext_tokens``（Qt 骨架同目录）；独立部署/测试时退回
内置的同值令牌（数值与薄地基 :root 一致，见 fixtext_tokens.py 注释）。
"""

from __future__ import annotations

import queue
import threading
from typing import Any

# ---------------------------------------------------------------------------
# 令牌（与 FixText_V1_设计系统_薄地基.html 的 :root 逐字一致；
# 独立运行无 fixtext_tokens 时使用这份等值副本）
# ---------------------------------------------------------------------------

_FALLBACK = {
    "warning":       "#B45309",
    "warning.bg":    "#FBF1DF",
    "warning.border": "#F0D6A8",
    "error":         "#C0392B",
    "error.bg":      "#FBEAE8",
    "error.border":  "#F1C4BD",
    "info":          "#3F48A2",
    "info.bg":       "#ECEEF9",
    "info.border":   "#C8CDEC",
    "neutral.0":     "#FFFFFF",
    "neutral.100":   "#EEF1F5",
    "neutral.300":   "#C2CAD6",
    "neutral.500":   "#6B7585",
    "neutral.600":   "#4A5363",
    "neutral.700":   "#333B48",
    "neutral.800":   "#222831",
    "neutral.900":   "#15191F",
    "primary.500":   "#4F59C0",
    "primary.700":   "#333B83",
}

_FALLBACK_FS = {"xs": "12px", "sm": "13px", "md": "16px", "lg": "18px", "2xl": "24px"}

_active_card = None  # 同一时刻只保留一张错误卡

# ---- 跨线程投递：worker 线程的异常也要弹卡，但 Qt 控件只能在主线程创建 ----
_PENDING = queue.Queue()
_DRAIN_TIMER = None   # 主线程 QTimer（100ms 轮询 _PENDING）


def ensure_bridge() -> bool:
    """在主线程启动卡片投递轮询（应用初始化时调用；Qt 不可用返回 False）。"""
    global _DRAIN_TIMER
    if _DRAIN_TIMER is not None:
        return True
    if threading.current_thread() is not threading.main_thread():
        return False
    try:
        from PySide6.QtCore import QTimer
    except Exception:
        return False

    def _drain() -> None:
        while True:
            try:
                resolved, parent = _PENDING.get_nowait()
            except queue.Empty:
                return
            try:
                show_error_card(resolved, parent)
            except Exception:
                pass

    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(_drain)
    timer.start()
    _DRAIN_TIMER = timer
    return True


def show_error_card_threadsafe(resolved, parent=None) -> None:
    """任意线程可调用：主线程直接弹卡，worker 线程投递到主线程（经 ensure_bridge）。"""
    if threading.current_thread() is threading.main_thread():
        show_error_card(resolved, parent)
        return
    _PENDING.put((resolved, parent))


def _c(key: str) -> str:
    try:
        from fixtext_tokens import c

        return c(key)
    except Exception:
        return _FALLBACK[key]


def _fs(key: str) -> str:
    try:
        from fixtext_tokens import fs

        return fs(key)
    except Exception:
        return _FALLBACK_FS[key]


class _Card:  # 仅用于类型注释占位（避免模块级 import PySide6）
    pass


def show_error_card(resolved, parent: Any = None) -> Any:
    """弹出人话错误卡。返回卡控件（便于测试截图）；无 Qt 环境返回 None。"""
    global _active_card
    try:
        from PySide6.QtCore import Qt
        if threading.current_thread() is threading.main_thread():
            ensure_bridge()
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
        )
    except Exception:
        return None

    # 旧卡先关（同一时刻一张）
    _close_active()

    dlg = QDialog(parent if parent is not None else None)
    dlg.setWindowTitle("FixText")
    dlg.setModal(False)
    dlg.setMinimumWidth(460)

    root = QVBoxLayout(dlg)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    # ---- 头部：⚠ + 标题 ----
    head = QWidget()
    head.setObjectName("ErrCardHead")
    hl = QHBoxLayout(head)
    hl.setContentsMargins(20, 18, 20, 14)
    hl.setSpacing(12)
    ico = QLabel("⚠")
    ico.setFixedSize(36, 36)
    ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
    ico.setStyleSheet(
        f"background:{_c('warning.bg')};color:{_c('warning')};"
        f"border:1px solid {_c('warning.border')};border-radius:10px;"
        f"font-size:18px;font-weight:700")
    title = QLabel(resolved.title)
    title.setWordWrap(True)
    title.setStyleSheet(
        f"font-weight:700;font-size:{_fs('lg')};color:{_c('neutral.900')};"
        f"background:transparent")
    hl.addWidget(ico)
    hl.addWidget(title, 1)
    root.addWidget(head)

    body = QWidget()
    bl = QVBoxLayout(body)
    bl.setContentsMargins(20, 4, 20, 16)
    bl.setSpacing(12)

    what = QLabel(resolved.what)
    what.setWordWrap(True)
    what.setStyleSheet(
        f"font-size:{_fs('md')};color:{_c('neutral.800')};background:transparent")
    bl.addWidget(what)

    if resolved.safe_hint:
        hint = QLabel(resolved.safe_hint)
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"font-size:{_fs('sm')};color:{_c('neutral.600')};"
            f"background:{_c('neutral.100')};border-radius:8px;"
            f"padding:6px 10px;background-color:{_c('neutral.100')}")
        bl.addWidget(hint)

    # ---- 下一步指引 ----
    guide = QWidget()
    gl = QVBoxLayout(guide)
    gl.setContentsMargins(14, 10, 14, 12)
    gl.setSpacing(4)
    glabel = QLabel("下一步可以这样做")
    glabel.setStyleSheet(
        f"font-size:{_fs('xs')};font-weight:700;color:{_c('info')};"
        f"background:transparent")
    gtext = QLabel(resolved.guidance)
    gtext.setWordWrap(True)
    gtext.setStyleSheet(
        f"font-size:{_fs('sm')};color:{_c('neutral.700')};background:transparent")
    gl.addWidget(glabel)
    gl.addWidget(gtext)
    guide.setStyleSheet(
        f"background:{_c('info.bg')};border:1px solid {_c('info.border')};"
        f"border-radius:10px")
    bl.addWidget(guide)

    # ---- 脚注：参考码 + 日志指引 ----
    foot = QLabel(
        f"参考码 {resolved.code} · 详细技术信息已自动记录到诊断日志"
        f"（左上角「设置 ⚙」可打开日志文件夹）")
    foot.setWordWrap(True)
    foot.setStyleSheet(
        f"font-size:{_fs('xs')};color:{_c('neutral.500')};background:transparent")
    bl.addWidget(foot)

    root.addWidget(body)

    btn_row = QWidget()
    pl = QHBoxLayout(btn_row)
    pl.setContentsMargins(20, 0, 20, 16)
    pl.addStretch(1)
    ok = QPushButton("知道了")
    ok.setCursor(Qt.CursorShape.PointingHandCursor)
    ok.setFixedHeight(34)
    ok.setStyleSheet(
        f"QPushButton{{background:{_c('primary.500')};color:#fff;border:none;"
        f"border-radius:8px;padding:0 22px;font-weight:600;"
        f"font-size:{_fs('sm')}}}"
        f"QPushButton:hover{{background:{_c('primary.700')}}}")
    ok.clicked.connect(dlg.close)
    pl.addWidget(ok)
    root.addWidget(btn_row)

    dlg.setStyleSheet(
        f"QDialog{{background:{_c('neutral.0')};"
        f"border:1px solid {_c('neutral.300')};border-radius:12px}}")
    dlg.adjustSize()

    _active_card = dlg
    dlg.show()
    return dlg


def _close_active() -> None:
    global _active_card
    if _active_card is None:
        return
    try:
        _active_card.close()
        _active_card.deleteLater()
    except RuntimeError:  # C++ 对象已销毁
        pass
    _active_card = None


def close_active_card() -> None:
    """测试 / 自动化用：立即关掉当前错误卡。"""
    _close_active()


def open_log_dir() -> bool:
    """用系统文件管理器打开诊断日志目录（设置页动作）。"""
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from .diaglog import log_dir
        return QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir()))
    except Exception:
        return False
