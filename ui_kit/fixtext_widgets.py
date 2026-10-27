"""
FixText V1 · 复用部件库（Qt）
================================

从 HTML 原型提炼的可复用控件，全部**只消费 `fixtext_tokens.py` 的令牌**，
不硬编码任何颜色/尺寸字面值（避免再次漂移）。

- `Card`      白底圆角卡片，可带标题行 / 折叠 / 「设计依据」标签
- `Switch`    胶囊开关（40×22，自绘，无动画）
- `Pill`      状态徽标（ok / info / warn / err / neutral）
- `FieldRow`  编号 + 名称 + 描述 + 控件 的一行（检查项、规则开关都用它）
- `no_badge`  行首序号方块
- `hline`     1px 分隔线
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QAbstractButton, QSizePolicy,
)

from fixtext_tokens import c, sp, r, fs, FONT_WEIGHT, FONT_MONO


def px(value: str) -> int:
    """'12px' -> 12"""
    return int(str(value).replace("px", ""))


def hline(color_key: str = "neutral.100") -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{c(color_key)};border:none")
    return f


def no_badge(n) -> QLabel:
    lab = QLabel(str(n))
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lab.setFixedSize(22, 22)
    lab.setStyleSheet(
        f"background:{c('neutral.100')};color:{c('neutral.500')};"
        f"border-radius:6px;font-size:11px;font-weight:700"
    )
    return lab


_PILL = {
    "ok":      ("success",       "success.bg",    "success.border"),
    "info":    ("info",          "info.bg",       "info.border"),
    "warn":    ("warning",       "warning.bg",    "warning.border"),
    "err":     ("error",         "error.bg",      "error.border"),
    "neutral": ("neutral.500",   "neutral.100",   "neutral.200"),
}


class Pill(QLabel):
    """状态徽标。kind ∈ ok/info/warn/err/neutral。"""

    def __init__(self, text: str, kind: str = "info", parent=None):
        super().__init__(text, parent)
        fg, bg, _bd = _PILL.get(kind, _PILL["neutral"])
        self.setStyleSheet(
            f"color:{c(fg)};background:{c(bg)};"
            f"border-radius:{r('full')};padding:2px 9px;"
            f"font-size:{fs('xs')};font-weight:700"
        )
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


class Switch(QAbstractButton):
    """胶囊开关：选中为主色轨道 + 白色滑块。"""

    def __init__(self, checked: bool = True, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(40, 22)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c("primary.500") if self.isChecked() else c("neutral.200")))
        p.drawRoundedRect(0, 0, 40, 22, 11, 11)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(20 if self.isChecked() else 2, 2, 18, 18)
        p.end()


class Card(QFrame):
    """白底圆角卡片。

    title / sub    标题行（sub 为灰字补充）
    collapsible    标题行可点击折叠
    open_          初始展开状态
    basis          「设计依据」标签文案（默认隐藏，由调用方统一控制显隐）
    """

    def __init__(self, title: str = "", sub: str = "", *,
                 collapsible: bool = False, open_: bool = True,
                 basis: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._collapsible = collapsible
        self._open = open_
        self._chev = None
        self._sep = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        if title:
            head = QWidget()
            hl = QHBoxLayout(head)
            hl.setContentsMargins(18, 14, 18, 14)
            hl.setSpacing(10)
            t = QLabel(title)
            t.setStyleSheet(
                f"color:{c('neutral.800')};font-size:{fs('base')};"
                f"font-weight:{FONT_WEIGHT['semibold']}"
            )
            hl.addWidget(t)
            if sub:
                s = QLabel(sub)
                s.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('xs')}")
                hl.addWidget(s)
            hl.addStretch(1)
            if collapsible:
                self._chev = QLabel("▼" if open_ else "▶")
                self._chev.setStyleSheet(
                    f"color:{c('neutral.500')};font-size:{fs('sm')}"
                )
                hl.addWidget(self._chev)
                head.setCursor(Qt.CursorShape.PointingHandCursor)
                head.mousePressEvent = lambda e: self.toggle()
            root.addWidget(head)

            self._sep = hline()
            root.addWidget(self._sep)

        self.body = QWidget()
        self.body_l = QVBoxLayout(self.body)
        self.body_l.setContentsMargins(18, 14, 18, 18)
        self.body_l.setSpacing(0)
        root.addWidget(self.body)

        # 「设计依据」标签：放进可整体显隐的容器，隐藏时间距一并消失
        self.basis = None          # 容器（供外部 setVisible 控制）
        self.basis_label = None
        if basis:
            text = basis if basis.lstrip().startswith("§") else f"§ {basis}"
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(0)
            self.basis_label = QLabel(text)
            self.basis_label.setStyleSheet(
                f"color:{c('primary.700')};background:{c('primary.50')};"
                f"border-radius:{r('full')};padding:2px 9px;"
                f"font-size:{fs('xs')};font-weight:700"
            )
            self.basis_label.setSizePolicy(
                QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
            )
            bl.addWidget(self.basis_label)
            bl.addSpacing(12)
            box.setVisible(False)
            self.body_l.addWidget(box)
            self.basis = box

        if collapsible:
            self.set_open(open_)

    def set_open(self, v: bool):
        self._open = v
        self.body.setVisible(v)
        if self._sep is not None:
            self._sep.setVisible(v)
        if self._chev is not None:
            self._chev.setText("▼" if v else "▶")

    def toggle(self):
        self.set_open(not self._open)


class FieldRow(QWidget):
    """编号 + 名称 + 描述 + （chip / 控件）的一行。

    idx=None 时不显示行首序号（如批量操作行）。
    """

    def __init__(self, idx, name: str, desc: str = "", *,
                 control: QWidget | None = None, chip: str | None = None,
                 name_width: int = 150, parent=None):
        super().__init__(parent)
        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 11, 0, 11)
        hl.setSpacing(12)

        if idx is not None:
            hl.addWidget(no_badge(idx))

        n = QLabel(name)
        n.setStyleSheet(
            f"color:{c('neutral.800')};font-weight:600;font-size:{fs('sm')}"
        )
        n.setMinimumWidth(name_width)
        hl.addWidget(n)

        if desc:
            d = QLabel(desc)
            d.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('xs')}")
            d.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            hl.addWidget(d, 1)
        else:
            hl.addStretch(1)

        if chip is not None:
            cp = QLabel(chip)
            cp.setStyleSheet(
                f"background:{c('neutral.100')};color:{c('neutral.500')};"
                f"border-radius:{r('full')};padding:3px 9px;"
                f"font-size:11px;font-weight:700"
            )
            cp.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            hl.addWidget(cp)

        if control is not None:
            hl.addWidget(control)
