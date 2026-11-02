"""FixText 图标加载器：把 resources/icons/*.svg 渲染为 QIcon / QPixmap。

- 轮廓图标用 ``currentColor``，调用时可指定 ``color`` 着色（浅色主题用中性文字色）。
- 语义图标（x-circle / info 已烘焙品牌色）忽略 ``color`` 参数，保持原色。
- 全部图标统一 24×24 viewBox、2px 描边，与 HTML 原型 <symbol> 同源。

H2 任务：用本模块替换 Qt 骨架里散落的 emoji（🔍📤📂＋× 等）。
"""
from __future__ import annotations

import os
from functools import lru_cache

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from fixtext_tokens import c

# 仓库根 / resources/icons
_ICON_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "icons"
)

# 浅色主题默认描边色（中性文字）；语义图标已烘焙，忽略此值
_DEFAULT_STROKE = c("neutral.700")

# 语义色映射：命中时改用对应品牌色（轮廓图标）
_SEMANTIC = {
    "alert": "warning",
    "x-circle": "error",
    "check-circle": "success",
    "check": "success",
}

# 2x 渲染，保证 HiDPI 清晰
_SCALE = 2


@lru_cache(maxsize=256)
def _read_svg(name: str) -> str | None:
    p = os.path.join(_ICON_DIR, f"{name}.svg")
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def has_icon(name: str) -> bool:
    """name 是否对应一个已存在的 SVG（用于调用点判断 emoji / SVG 名）。"""
    return _read_svg(name) is not None


def _stroke_color(name: str, color: str | None) -> str:
    if color:
        return color
    if name in _SEMANTIC:
        return c(_SEMANTIC[name])
    return _DEFAULT_STROKE


def icon(name: str, color: str | None = None, size: int = 20) -> QIcon:
    """返回渲染好的 QIcon；找不到 name 时返回空 QIcon。

    color: 替换 currentColor 的十六进制色（如 '#333B48'）；None 用默认中性色。
    """
    raw = _read_svg(name)
    if raw is None:
        return QIcon()
    svg = raw.replace("currentColor", _stroke_color(name, color))
    renderer = QSvgRenderer(svg.encode("utf-8"))
    if not renderer.isValid():
        return QIcon()
    pm = QPixmap(size * _SCALE, size * _SCALE)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    pm.setDevicePixelRatio(_SCALE)
    return QIcon(pm)


def pixmap(name: str, size: int = 20, color: str | None = None) -> QPixmap:
    """返回逻辑尺寸为 size×size 的 QPixmap（已含 2x 分辨率，setPixmap 即用）。"""
    return icon(name, color=color, size=size).pixmap(QSize(size, size))
