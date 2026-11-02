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
- `ConfirmDialog` 需二次确认的动作（删除 / 恢复 / 清理）的确认弹窗
- `Modal`     通用模态弹窗（头 / 体 / 脚可组合），设置、帮助与各模块表单共用
- `ProgressDialog` 长任务进度弹窗（timer / live 两种模式）

`ConfirmDialog` 与 `Modal` 于 M2-T2.6 从 UI v4 骨架提升为共享部件，供词库 /
历史 / 主窗口顶栏统一复用——三处不再各写一套弹窗，样式与行为只在这里改一次。
"""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QPropertyAnimation, Qt, QSize, QPoint,
    QRect, Signal, QTimer,
)
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath
from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QAbstractButton, QSizePolicy, QDialog, QProgressBar, QPushButton,
    QLayout, QLayoutItem,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect
from PySide6.QtWidgets import QGraphicsDropShadowEffect

from fixtext_tokens import c, sp, r, fs, FONT_WEIGHT, FONT_MONO


def px(value: str) -> int:
    """'12px' -> 12"""
    return int(str(value).replace("px", ""))


class PrimaryButton(QPushButton):
    """带品牌投影的主操作按钮（Qt 单源实现）。

    `#BtnPrimary` 的配色（背景 / 悬停 / 按下 / 禁用）仍由 fixtext.qss 提供；
    品牌投影则用 QGraphicsDropShadowEffect 实现——Qt QSS 的 ``box-shadow``
    在子控件上会被裁剪、无法外溢渲染，故不能走 qss。阴影参数对应
    fixtext_tokens.SHADOW["primary-sm"]（0 2px 6px rgba(79,89,192,.22)）。
    与 EmptyState 图标阴影同机制，在真实窗口下正常合成。
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("BtnPrimary")
        # 必须以 self 为父：否则 effect 仅由构造期局部变量持有，__init__ 返回后即被
        # GC，C++ 端 effect 一并销毁，运行时 graphicsEffect() 返回 None（阴影不渲染）。
        eff = QGraphicsDropShadowEffect(self)
        eff.setOffset(0, 2)
        eff.setBlurRadius(6)
        eff.setColor(QColor(79, 89, 192, 56))   # primary.500 @ .22，对应 SHADOW["primary-sm"]
        self.setGraphicsEffect(eff)


def enable_chrome(widget: QWidget) -> None:
    """启用面板外框绘制（背景 / 边框 / 圆角）。

    Qt 上 ``QFrame``/``QWidget`` 若不设 ``WA_StyledBackground``，样式表里的
    ``border-radius`` 经常不生效，外部边框会呈直角——「从文件导入」「工作区书架」
    等卡片外框不对，多半是这个原因。
    """
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)


def hline(color_key: str = "neutral.100") -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{c(color_key)};border:none")
    return f


def page_head_shell() -> tuple[QWidget, QWidget]:
    """页头外壳（原型 .page-head）。

    返回 ``(shell, body)``：标题/副标题/右侧控件建在 ``body`` 上；
    ``shell`` 底部用独立 1px 线分隔（不用 QSS border-bottom，避免贴字）。
    """
    shell = QWidget()
    shell.setObjectName("PageHead")
    outer = QVBoxLayout(shell)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(px(sp("3")))  # 副标题与分隔线之间留白
    body = QWidget()
    outer.addWidget(body)
    outer.addWidget(hline("neutral.100"))
    return shell, body


def repolish(widget: QWidget) -> None:
    """动态属性变更后让 QSS 属性选择器重新生效。

    Qt 的 QSS 属性选择器（如 ``#ShelfBadge[current="true"]``）只在 polish 阶段
    匹配一次；运行时改 ``setProperty`` 后必须 unpolish/polish 才会重绘。
    """
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def no_badge(n) -> QLabel:
    lab = QLabel(str(n))
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lab.setFixedSize(22, 22)
    lab.setStyleSheet(
        f"background:{c('neutral.100')};color:{c('neutral.500')};"
        f"border-radius:{r('md')};font-size:{fs('xs')};font-weight:700"
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
        self.setObjectName("Pill")
        # 语义色交给 fixtext.qss 的 #Pill[kind="x"]（闭集 ok/info/warn/err/neutral）
        self.setProperty("kind", kind)
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
        p.setBrush(QColor(c("neutral.0")))
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
        enable_chrome(self)  # 外部圆角边框（对齐原型 .card）
        # 原型 .card 有 box-shadow:var(--sh-sm)；Qt QSS 的 box-shadow 在子控件上
        # 会被裁剪、无法外溢，故用 QGraphicsDropShadowEffect 实现（参数对应 SHADOW["sm"]）。
        eff = QGraphicsDropShadowEffect(self)
        eff.setOffset(0, 1)
        eff.setBlurRadius(3)
        eff.setColor(QColor(21, 25, 31, 15))   # rgba(21,25,31,.06)
        self.setGraphicsEffect(eff)
        self._collapsible = collapsible
        self._open = open_
        self._chev = None
        self._sep = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        if title:
            head = QWidget()
            head.setObjectName("CardHead")
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
        self.body.setObjectName("CardBody")
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
                f"border-radius:{r('full')};padding:{sp('1')} {sp('2')};"
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

        self._chip = None
        if chip is not None:
            # 原型 .auto-chip（校正页「导入时自动」）。仅此芯片用半高像素圆角：
            # Qt 对 border-radius:999px 常画成方块（书架胶囊同理）；不动全局 Pill。
            chip_h = 20
            shell = QFrame()
            shell.setObjectName("AutoChip")
            enable_chrome(shell)
            shell.setFixedHeight(chip_h)
            shell.setStyleSheet(
                f"QFrame#AutoChip{{background:{c('neutral.100')};"
                f"border:none;border-radius:{chip_h // 2}px;}}"
            )
            shell.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            sh_l = QHBoxLayout(shell)
            sh_l.setContentsMargins(9, 0, 9, 0)
            sh_l.setSpacing(0)
            cp = QLabel(chip)
            cp.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            cp.setStyleSheet(
                f"background:transparent;border:none;color:{c('neutral.500')};"
                f"font-size:{fs('xs')};font-weight:700"
            )
            sh_l.addWidget(cp)
            hl.addWidget(shell)
            self._chip = cp

        if control is not None:
            hl.addWidget(control)

    def set_chip(self, text: str) -> None:
        """更新右侧统计小标签（数据变了就地改，不重建整行）。"""
        if self._chip is not None:
            self._chip.setText(str(text))


class RadioDot(QFrame):
    """圆形单选指示器：外环 + 内点。

    不用 ○ / ● 字形——字形基线在字体里偏低，垂直居中会跑偏，
    且纯颜色区分选中态对色觉障碍不友好，这里补一个形状信号。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RadioDot")
        self.setFixedSize(15, 15)
        self._inner = QFrame(self)
        self._inner.setObjectName("RadioDotInner")
        self._inner.setFixedSize(7, 7)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._inner, 0, Qt.AlignmentFlag.AlignCenter)
        self.set_selected(False)

    def set_selected(self, on: bool):
        # 选中态完全交给 fixtext.qss 的 #RadioDot[selected="true"] 及其子选择器
        self.setProperty("selected", "true" if on else "false")
        self._inner.setVisible(on)
        self.style().unpolish(self)
        self.style().polish(self)
        self._inner.style().unpolish(self._inner)
        self._inner.style().polish(self._inner)


class FlowLayout(QLayout):
    """横向自动换行（对齐原型 ``.chk-group { flex-wrap: wrap }``）。"""

    def __init__(self, parent=None, *, hspacing: int = 8, vspacing: int = 8):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._hs = hspacing
        self._vs = vspacing

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y = effective.x(), effective.y()
        line_h = 0
        for item in self._items:
            wh = item.sizeHint()
            next_x = x + wh.width() + self._hs
            if line_h and next_x - self._hs > effective.right():
                x = effective.x()
                y = y + line_h + self._vs
                next_x = x + wh.width() + self._hs
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), wh))
            x = next_x
            line_h = max(line_h, wh.height())
        return y + line_h - rect.y() + m.bottom()


class ChkMark(QFrame):
    """词库勾选指示器（对齐原型 ``.chk`` 内 15px 主色 checkbox）。

    原生 ``QCheckBox`` 的指示器是系统方块勾选，与原型「主色小方块 + 白勾」的
    胶囊风格不一致；这里用 QPainter 自绘，不依赖原生样式与图片资源。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChkMark")
        self.setFixedSize(16, 16)
        self._on = False
        self._locked = False
        self._enabled = True

    def setChecked(self, on: bool) -> None:
        self._on = bool(on)
        self.update()

    def isChecked(self) -> bool:
        return self._on

    def setLocked(self, v: bool) -> None:
        self._locked = bool(v)
        self.update()

    def setEnabled(self, v: bool) -> None:
        self._enabled = bool(v)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = 5
        if self._locked:
            # 锁定态：灰显（原型 .chk.locked input opacity:.5），不随 on/off 变色
            p.setPen(QPen(QColor(c("neutral.300")), 1.5))
            p.setBrush(QColor(c("neutral.100")))
            p.drawRoundedRect(0.75, 0.75, 14.5, 14.5, r, r)
            if self._on:
                pen = QPen(QColor(c("neutral.400")), 2, Qt.PenStyle.SolidLine)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawLine(4, 8, 7, 11)
                p.drawLine(7, 11, 12, 5)
            p.end()
            return
        if self._on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c("primary.500")))
            p.drawRoundedRect(0, 0, 16, 16, r, r)
            pen = QPen(QColor(c("neutral.0")), 2, Qt.PenStyle.SolidLine)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(4, 8, 7, 11)
            p.drawLine(7, 11, 12, 5)
        else:
            p.setPen(QPen(QColor(c("neutral.300")), 1.5))
            p.setBrush(QColor(c("neutral.0")))
            p.drawRoundedRect(0.75, 0.75, 14.5, 14.5, r, r)
        p.end()


class LockTag(QLabel):
    """「锁定」小徽标（原型 ``.lock-tag``）：QPainterPath 自绘圆角胶囊底。

    QLabel 的 QSS ``border-radius`` 同样不裁切背景（与 QFrame 同源问题），
    故此处自绘圆角底，再由 QLabel 叠加文字（文字颜色/内边距仍由 QSS 提供）。
    """

    def __init__(self, text: str = "锁定", parent=None):
        super().__init__(text, parent)
        self.setObjectName("BagLockTag")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rr = self.height() / 2.0
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), rr, rr)
        p.fillPath(path, QColor(c("primary.700")))
        p.end()
        super().paintEvent(event)


class BagChk(QFrame):
    """词库多选胶囊（对齐原型 ``label.chk`` / ``.lock-tag``）。"""

    toggled = Signal(bool)

    def __init__(self, label: str, *, checked: bool = False,
                 locked: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("BagChk")
        # 背景/边框改由 paintEvent 用 QPainterPath 自绘圆角。
        # 不设 WA_StyledBackground（enable_chrome）：否则全局 QWidget{background:#F7F8FA}
        # 会以直角方块方式填进圆角外的四角，出现「方角」；QFrame 的 QSS
        # border-radius 本就不裁切背景，故完全交给 paintEvent 处理；
        # 容器默认边框/背景由 fixtext.qss 的 #BagChk 规则清空。
        self._locked = locked
        self._on = bool(checked)
        self._hover = False
        self.setCursor(
            Qt.CursorShape.ArrowCursor if locked else Qt.CursorShape.PointingHandCursor)
        hl = QHBoxLayout(self)
        hl.setContentsMargins(13, 7, 13, 7)
        hl.setSpacing(7)
        self.mark = ChkMark()
        self.mark.setChecked(self._on)
        self.mark.setLocked(self._locked)
        hl.addWidget(self.mark)
        self.txt = QLabel(label)
        self.txt.setObjectName("BagChkText")
        hl.addWidget(self.txt)
        if locked:
            # 锁定项整项置灰（原型 .chk.locked input opacity:.5）
            self.txt.setStyleSheet(f"color:{c('neutral.400')}")
            tag = LockTag("锁定")
            hl.addWidget(tag)
        self._sync_props()

    def isChecked(self) -> bool:
        return self._on

    def setChecked(self, on: bool) -> None:
        self._on = bool(on)
        self.mark.setChecked(self._on)
        self._sync_props()

    def setEnabled(self, v: bool) -> None:
        super().setEnabled(v)
        self.mark.setEnabled(v)
        self.txt.setEnabled(v)

    def _sync_props(self) -> None:
        self.setProperty("on", "true" if self._on else "false")
        self.setProperty("locked", "true" if self._locked else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        """自绘圆角胶囊背景 + 边框（QFrame 的 QSS border-radius 不裁切背景，故自绘）。

        与 ChkMark / Switch 一致，用 QPainterPath 画圆角矩形，保证四角真正透明
        （圆角外露出父级背景），而非被全局 QWidget 背景填成方角。
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = c("neutral.0")          # 白 #FFFFFF（off）
        bd = c("neutral.200")        # #DDE2EA（off 边框）
        if self._on:
            bg = c("primary.50"); bd = c("primary.500")
        elif self._locked:
            if self._hover:
                bg = c("primary.50"); bd = c("primary.500")
        elif self._hover:
            bg = c("primary.50"); bd = c("primary.300")
        r = self.height() / 2.0      # 全胶囊（等价于 border-radius:999px）
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, self.width() - 1, self.height() - 1, r, r)
        p.fillPath(path, QColor(bg))
        pen = QPen(QColor(bd), 1)
        pen.setCosmetic(True)
        p.strokePath(path, pen)
        p.end()

    def mousePressEvent(self, event):
        if not self._locked and event.button() == Qt.MouseButton.LeftButton:
            self._on = not self._on
            self.mark.setChecked(self._on)
            self._sync_props()
            self.toggled.emit(self._on)
            event.accept()
            return
        super().mousePressEvent(event)


class RadioCard(QFrame):
    """可点击的单选卡片（标题 + 说明 + 圆形指示器）。chosen 携带 value。

    注意：内联 QSS 必须用 `#RadioCard` 精确选择器。写成裸 `QFrame{}` 会连带
    命中卡片内的 QLabel（QLabel 是 QFrame 子类），出现多层边框。
    """

    chosen = Signal(str)

    def __init__(self, title: str, desc: str, value: str, parent=None):
        super().__init__(parent)
        self.value = value
        self.setObjectName("RadioCard")
        enable_chrome(self)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(58)

        hl = QHBoxLayout(self)
        hl.setContentsMargins(12, 12, 12, 12)
        hl.setSpacing(10)

        self._dot = RadioDot()
        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel(title)
        t.setStyleSheet(
            f"font-weight:700;font-size:{fs('sm')};color:{c('neutral.800')}")
        d = QLabel(desc)
        d.setStyleSheet(f"font-size:{fs('xs')};color:{c('neutral.500')}")
        col.addWidget(t)
        col.addWidget(d)
        hl.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        hl.addLayout(col, 1)

        self.set_selected(False)

    def set_selected(self, on: bool):
        self._dot.set_selected(on)
        # 选中态底边框交给 fixtext.qss 的 #RadioCard / #RadioCard[selected="true"]
        self.setProperty("selected", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        self.chosen.emit(self.value)
        super().mousePressEvent(event)


class _WrapLabel(QLabel):
    """定宽自动换行的说明文字（对齐原型 es-d 的 max-width:440px 行为）。

    坑：中文长句上 ``QLabel.sizeHint()`` 不按换行后的行数给高度，且加进布局后
    Qt 只分到单行高度（实测 h=16，而 440 宽下实际需要 32~48px），后半句引导
    文案被直接裁掉；覆写 sizeHint / minimumSizeHint 也不被布局采纳。
    因此这里改走「按实际字体度量算好高度再 setFixedHeight」，排版结果确定。
    ``fix_height()`` 需在样式（字号）生效后调用。
    """

    def __init__(self, text: str, width: int, parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.setFixedWidth(width)

    def fix_height(self) -> int:
        self.ensurePolished()
        fm = self.fontMetrics()
        need = fm.boundingRect(
            0, 0, self.width(), 100000,
            int(Qt.TextFlag.TextWordWrap), self.text()).height()
        need = max(need, fm.lineSpacing())
        self.setFixedHeight(need)
        return need


class EmptyState(QFrame):
    """统一空状态（原型 v3 更新记录 §4 + §10 Step7）。

    结构对齐原型 ``.empty-state``：图标（es-ico，60px + primary-50 6px 光晕）/
    标题（es-t，fs-md / semibold）/ 描述（es-d，fs-sm，最宽 460px）/
    双按钮居中（es-acts，主按钮 BtnPrimary + 次按钮 BtnGhost）。
    没有收起按钮（§4 明确去掉）。按钮点击经 primaryClicked /
    secondaryClicked 交给外层接线（去导入页 / 打开新手向导），
    控件本身不持有业务逻辑。
    """

    primaryClicked = Signal()
    secondaryClicked = Signal()

    def __init__(self, icon: str, title: str, desc: str, *,
                 primary: str | None = "📥 去导入第一本书",
                 secondary: str | None = "🧭 打开新手向导",
                 parent=None):
        super().__init__(parent)
        self.setObjectName("EmptyState")
        enable_chrome(self)
        # M5-EX.7 §10 Step7：dashed neutral-200、padding 44/28；外框配色交 fixtext.qss 的 QFrame#EmptyState（原内联收归）

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 44, 28, 44)
        root.setSpacing(14)

        # 外环：primary-50 6px 光晕（Qt 无多 box-shadow，用外框模拟）
        ico_ring = QFrame()
        ico_ring.setObjectName("EsIcoRing")
        ico_ring.setFixedSize(72, 72)  # 60 + 6*2
        # 外环配色交给 fixtext.qss 的 #EsIcoRing（原内联收归）
        ring_l = QVBoxLayout(ico_ring)
        ring_l.setContentsMargins(6, 6, 6, 6)
        ring_l.setSpacing(0)
        ico = QLabel(icon)
        ico.setObjectName("EsIco")
        ico.setFixedSize(60, 60)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 图标方块配色交给 fixtext.qss 的 #EsIco（原内联收归）
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(3)
        shadow.setOffset(1, 1)
        shadow.setColor(QColor(21, 25, 31, 15))  # sh-sm
        ico.setGraphicsEffect(shadow)
        ring_l.addWidget(ico)
        root.addWidget(ico_ring, 0, Qt.AlignmentFlag.AlignHCenter)

        t = QLabel(title)
        t.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        t.setStyleSheet(
            f"color:{c('neutral.800')};font-size:{fs('sm')};"
            f"font-weight:{FONT_WEIGHT['semibold']}")
        root.addWidget(t, 0, Qt.AlignmentFlag.AlignHCenter)

        d = _WrapLabel(desc, 460)
        d.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('sm')}")
        d.fix_height()  # 样式生效后按实际字体度量定高，避免第二句被裁
        root.addWidget(d, 0, Qt.AlignmentFlag.AlignHCenter)

        if primary or secondary:
            acts = QWidget()
            al = QHBoxLayout(acts)
            al.setContentsMargins(0, 6, 0, 0)
            al.setSpacing(10)
            if primary:
                b1 = PrimaryButton(primary)
                b1.setCursor(Qt.CursorShape.PointingHandCursor)
                b1.clicked.connect(lambda _=False: self.primaryClicked.emit())
                al.addWidget(b1)
            if secondary:
                b2 = QPushButton(secondary)
                b2.setObjectName("BtnGhost")
                b2.setCursor(Qt.CursorShape.PointingHandCursor)
                b2.clicked.connect(lambda _=False: self.secondaryClicked.emit())
                al.addWidget(b2)
            root.addWidget(acts, 0, Qt.AlignmentFlag.AlignHCenter)


class ProgressDialog(QDialog):
    """长任务进度弹窗：步骤列表 + 进度条 + 预计剩余，可取消。

    两种模式：

    * ``mode="timer"``（默认，旧用法）：steps 为
      ``[{"name":..., "desc":..., "dur":毫秒}, ...]``，QTimer 按时长推步骤。
      取消即 ``reject()``，由调用方负责「不留半成品」的语义。
    * ``mode="live"``（M2-T2.3，真实事件驱动）：steps 为
      ``[{"name":..., "desc":...}, ...]``，由真实后台任务的信号驱动：
      ``start_live(state_provider)`` 启动后，调用方把任务信号接到
      ``live_stage_started / live_stage_finished``，百分比与剩余时间由
      ``state_provider() -> dict``（含 percent/elapsed_s/eta_s）每 200ms 轮询。
      点「取消」不直接关窗：先回调 ``on_cancel_request``（让任务终止并清理），
      窗口进入「正在取消…」状态，等调用方确认清理完成后再
      ``live_close_cancelled()`` 关闭——保证用户看到的是干净收场，而不是
      窗口先关、后台还在跑。
    """

    def __init__(self, *, icon: str, title: str, note: str, steps: list,
                 on_finish=None, cancel_text: str = "取消（不留半成品）",
                 finish_text: str = "完成", parent=None,
                 mode: str = "timer", on_cancel_request=None,
                 confirm_cancel: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(480)
        self.steps = steps
        self.on_finish = on_finish
        self._finish_text = finish_text
        self._mode = mode
        self._on_cancel_request = on_cancel_request
        #: 点「取消」先出二次确认（原型 #corrConfirm），确认放弃才真停
        self._confirm_cancel = confirm_cancel
        self._confirm_dlg = None
        self._i = 0
        self._total = sum(s.get("dur", 0) for s in steps)
        self._acc = 0
        self._cancelled = False
        self._closing = False
        self._state_provider = None
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(200)
        self._live_timer.timeout.connect(self._live_tick)
        self._build(icon, title, note, cancel_text)

    def _build(self, icon: str, title: str, note: str, cancel_text: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head.setObjectName("ModalHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(18, 16, 18, 16)
        ico = QLabel(icon)
        ico.setFixedSize(30, 30)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background:{c('primary.100')};color:{c('primary.700')};"
            f"border-radius:{r('md')};font-size:{fs('md')}")
        htitle = QLabel(title)
        htitle.setStyleSheet(
            f"font-weight:700;font-size:{fs('lg')};color:{c('neutral.900')}")
        hl.addWidget(ico)
        hl.addWidget(htitle)
        root.addWidget(head)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(18, 16, 18, 16)
        bl.setSpacing(12)

        if note:
            nl = QLabel(note)
            nl.setWordWrap(True)
            nl.setStyleSheet(
                f"background:{c('info.bg')};border:1px solid {c('info.border')};"
                f"color:{c('info')};border-radius:{r('lg')};padding:{sp('3')} {sp('4')};"
                f"font-size:{fs('sm')}")
            bl.addWidget(nl)

        self.list_w = QWidget()
        self.list_l = QVBoxLayout(self.list_w)
        self.list_l.setContentsMargins(0, 0, 0, 0)
        self.list_l.setSpacing(0)
        self.step_rows = []
        for s in self.steps:
            self.step_rows.append(self._step_row(s["name"], s.get("desc", "")))
            self.list_l.addWidget(self.step_rows[-1])
        bl.addWidget(self.list_w)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setStyleSheet(
            f"QProgressBar{{background:{c('neutral.100')};border-radius:{r('full')};"
            f"height:10px;text-align:none}}"
            f"QProgressBar::chunk{{background:{c('primary.500')};"
            f"border-radius:{r('full')}}}")
        bl.addWidget(self.bar)

        meta = QHBoxLayout()
        self.step_name = QLabel("准备中…")
        self.step_name.setStyleSheet(f"font-size:{fs('xs')};color:{c('neutral.600')}")
        self.eta = QLabel("—")
        self.eta.setStyleSheet(f"font-size:{fs('xs')};color:{c('neutral.500')}")
        meta.addWidget(self.step_name)
        meta.addStretch(1)
        meta.addWidget(self.eta)
        bl.addLayout(meta)

        root.addWidget(body)

        foot = QWidget()
        foot.setObjectName("ModalFoot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(18, 14, 18, 14)
        fl.addStretch(1)
        self.cancel_btn = QPushButton(cancel_text)
        self.cancel_btn.setObjectName("BtnDanger")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._cancel)
        fl.addWidget(self.cancel_btn)
        root.addWidget(foot)

    def _step_row(self, name: str, desc: str):
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 10, 0, 10)
        hl.setSpacing(12)
        dot = QLabel()
        dot.setFixedSize(22, 22)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        n = QLabel(name)
        n.setStyleSheet(f"font-weight:600;font-size:{fs('sm')};color:{c('neutral.600')}")
        d = QLabel(desc)
        d.setStyleSheet(f"font-size:{fs('xs')};color:{c('neutral.500')}")
        hl.addWidget(dot)
        hl.addWidget(n, 0)
        hl.addWidget(d, 1)
        w._dot = dot
        w._name = n
        return w

    def _paint(self):
        for idx, row in enumerate(self.step_rows):
            if idx < self._i:
                row._dot.setText("✓")
                row._dot.setStyleSheet(
                    f"background:{c('success')};color:{c('on.fill')};"
                    f"border-radius:{r('full')};font-size:{fs('xs')};font-weight:700")
                row._name.setStyleSheet(
                    f"font-weight:600;font-size:{fs('sm')};color:{c('neutral.600')}")
            elif idx == self._i:
                row._dot.setText(str(idx + 1))
                row._dot.setStyleSheet(
                    f"background:{c('primary.500')};color:{c('on.fill')};"
                    f"border-radius:{r('full')};font-size:{fs('xs')};font-weight:700")
                row._name.setStyleSheet(
                    f"font-weight:700;font-size:{fs('sm')};color:{c('primary.700')}")
            else:
                row._dot.setText(str(idx + 1))
                row._dot.setStyleSheet(
                    f"background:{c('neutral.100')};color:{c('neutral.500')};"
                    f"border-radius:{r('full')};font-size:{fs('xs')};font-weight:700")
                row._name.setStyleSheet(
                    f"font-weight:600;font-size:{fs('sm')};color:{c('neutral.500')}")

    # ---------------------------------------------------------------- timer 模式

    def start(self):
        self._paint()
        self._advance()

    def _advance(self):
        if self._cancelled:
            return
        if self._i >= len(self.steps):
            self._finish()
            return
        s = self.steps[self._i]
        self._paint()
        self.step_name.setText(s["name"] + "…")
        remain = max(1, round((self._total - self._acc) / 1000))
        self.eta.setText(f"预计 {remain} 秒")
        QTimer.singleShot(s["dur"], self._step_done)

    def _step_done(self):
        if self._cancelled:
            return
        s = self.steps[self._i]
        self._acc += s["dur"]
        self.bar.setValue(int(self._acc / self._total * 100))
        self._i += 1
        self._advance()

    def _finish(self):
        self.bar.setValue(100)
        self.step_name.setText(self._finish_text)
        self.eta.setText("0 秒")
        self._paint()
        QTimer.singleShot(500, self._done)

    def _done(self):
        if self._cancelled:
            return
        if self.on_finish:
            self.on_finish()
        self.accept()

    # ---------------------------------------------------------------- live 模式

    def start_live(self, state_provider=None):
        """启动事件驱动模式：state_provider 返回含 percent/elapsed_s/eta_s 的 dict。"""
        self._state_provider = state_provider
        self._paint()
        self.step_name.setText("准备中…")
        self.eta.setText("正在估算剩余时间…")
        self._live_timer.start()

    def live_stage_started(self, i: int):
        self._i = i
        self._paint()
        if 0 <= i < len(self.steps):
            self.step_name.setText(self.steps[i]["name"] + "…")

    def live_stage_finished(self, i: int, elapsed_s: float):
        self._i = i + 1
        self._paint()

    def _live_tick(self):
        if self._closing:
            return
        provider = self._state_provider
        if provider is None:
            return
        try:
            state = provider()
        except Exception:
            return
        self.bar.setValue(int(min(100.0, state.get("percent", 0.0))))
        if not self._cancelled:
            eta_s = state.get("eta_s")
            elapsed = state.get("elapsed_s", 0.0)
            self.eta.setText(
                f"已用 {self._fmt_sec(elapsed)} · 预计剩余 {self._fmt_sec(eta_s)}"
                if eta_s is not None else "—")

    @staticmethod
    def _fmt_sec(sec) -> str:
        if sec is None:
            return "—"
        sec = max(0, int(sec))
        if sec < 60:
            return f"{sec} 秒"
        return f"{sec // 60} 分 {sec % 60} 秒"

    def live_finish(self):
        """全部完成：进度条满格，短暂展示后接受关闭。"""
        self._closing = True
        self._live_timer.stop()
        self._i = len(self.steps)
        self._paint()
        self.bar.setValue(100)
        self.step_name.setText(self._finish_text)
        self.eta.setText("已完成")
        if self.on_finish:
            self.on_finish()
        QTimer.singleShot(400, self.accept)

    def live_begin_cancelling(self):
        """用户点了取消：进入「正在取消」状态，等待后台清理完成再关窗。"""
        self._cancelled = True
        self._live_timer.stop()
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("正在取消…")
        self.step_name.setText("正在取消本次校正…")
        self.eta.setText("正在清理已生成的临时文件")

    def live_close_cancelled(self):
        """后台确认清理完成：关窗（结果码 Rejected，cancelled=True）。"""
        self._closing = True
        self.reject()

    # ---------------------------------------------------------------- 取消入口

    def _cancel(self):
        if self._mode == "live" and self._on_cancel_request is not None:
            if self._cancelled or self._closing:
                return
            if self._confirm_cancel and not self._ask_confirm_cancel():
                return                       # 用户选了「继续校正」：什么都不做
            self.live_begin_cancelling()
            self._on_cancel_request()
            return
        self._cancelled = True
        self.reject()

    def _ask_confirm_cancel(self) -> bool:
        """二次确认（原型层级表：确认层 56 高于进度弹窗 50）。

        以本弹窗为父窗口，一定盖在进度弹窗之上；返回 True 表示用户确认放弃。
        """
        dlg = CancelConfirmDialog(parent=self)
        self._confirm_dlg = dlg
        try:
            return dlg.exec() == QDialog.DialogCode.Accepted
        finally:
            self._confirm_dlg = None

    def closeEvent(self, event):                 # noqa: N802 - Qt 命名
        """关窗 / Esc 也走取消路径（含二次确认），避免后台还在跑窗口先没。"""
        if self._mode == "live" and self._on_cancel_request is not None \
                and not self._closing:
            event.ignore()
            self._cancel()
            return
        super().closeEvent(event)



# ---------------------------------------------------------------------------
# 确认弹窗 / 通用模态弹窗（M2-T2.6 自 UI v4 骨架提升为共享部件）
# ---------------------------------------------------------------------------

class CancelConfirmDialog(QDialog):
    """校正「取消」的二次确认（原型 `#corrConfirm`）。

    文案与原型一致：说明「已自动创建快照、放弃不留半成品」，但当前进度会丢。
    左侧「继续校正」= 什么都不做继续跑；右侧「确认放弃」= 真的停下并清理。
    以进度弹窗为父窗口，天然盖在它上面（原型层级表里确认层 56 > 弹窗 50）。
    """

    TITLE = "确认放弃本次校正？"
    NOTE = ("校正前已自动创建快照，放弃不会留下任何半成品文件；"
            "但当前进度将丢失，需要重新运行校正。")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.TITLE)
        self.setModal(True)
        self.setMinimumWidth(480)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head.setObjectName("ModalHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(18, 16, 18, 16)
        ico = QLabel("⚠️")
        ico.setFixedSize(30, 30)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background:{c('warning.bg')};color:{c('warning')};"
            f"border-radius:{r('md')};font-size:{fs('md')}")
        t = QLabel(self.TITLE)
        t.setStyleSheet(
            f"font-weight:700;font-size:{fs('lg')};color:{c('neutral.900')}")
        hl.addWidget(ico)
        hl.addWidget(t)
        root.addWidget(head)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(18, 16, 18, 16)
        note = QLabel(self.NOTE)
        note.setWordWrap(True)
        note.setStyleSheet(
            f"background:{c('warning.bg')};border:1px solid {c('warning.border')};"
            f"color:{c('warning')};border-radius:{r('lg')};padding:{sp('3')} {sp('4')};"
            f"font-size:{fs('sm')}")
        bl.addWidget(note)
        root.addWidget(body)

        foot = QWidget()
        foot.setObjectName("ModalFoot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(18, 14, 18, 14)
        fl.addStretch(1)
        self.resume_btn = QPushButton("继续校正")
        self.resume_btn.setObjectName("BtnGhost")
        self.resume_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.resume_btn.clicked.connect(self.reject)
        fl.addWidget(self.resume_btn)
        self.confirm_btn = QPushButton("确认放弃")
        self.confirm_btn.setObjectName("BtnDanger")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.clicked.connect(self.accept)
        fl.addWidget(self.confirm_btn)
        root.addWidget(foot)


class ConfirmDialog(QDialog):
    """带「取消 / 确认」的操作确认弹窗，用于破坏性或需二次确认的动作。

    note_kind="warn" 用琥珀底（破坏性操作），否则用信息底。
    confirm_kind="danger" 用危险按钮（红边），否则用主色按钮。
    """

    def __init__(self, *, icon: str, title: str, note: str,
                 note_kind: str = "info", confirm_text: str = "确认",
                 confirm_kind: str = "primary", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(480)
        self._build(icon, title, note, note_kind, confirm_text, confirm_kind)

    def _build(self, icon, title, note, note_kind, confirm_text, confirm_kind):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head.setObjectName("ModalHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(18, 16, 18, 16)
        ico = QLabel(icon)
        ico.setFixedSize(30, 30)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background:{c('primary.100')};color:{c('primary.700')};"
            f"border-radius:{r('md')};font-size:{fs('md')}")
        htitle = QLabel(title)
        htitle.setStyleSheet(
            f"font-weight:700;font-size:{fs('lg')};color:{c('neutral.900')}")
        hl.addWidget(ico)
        hl.addWidget(htitle)
        root.addWidget(head)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(18, 16,18, 16)
        bl.setSpacing(12)
        nl = QLabel(note)
        nl.setWordWrap(True)
        if note_kind == "warn":
            nl.setStyleSheet(
                f"background:{c('warning.bg')};border:1px solid {c('warning.border')};"
                f"color:{c('warning')};border-radius:{r('lg')};padding:{sp('3')} {sp('4')};"
                f"font-size:{fs('sm')}")
        else:
            nl.setStyleSheet(
                f"background:{c('info.bg')};border:1px solid {c('info.border')};"
                f"color:{c('info')};border-radius:{r('lg')};padding:{sp('3')} {sp('4')};"
                f"font-size:{fs('sm')}")
        bl.addWidget(nl)
        root.addWidget(body)

        foot = QWidget()
        foot.setObjectName("ModalFoot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(18, 14, 18, 14)
        fl.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("BtnGhost")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        fl.addWidget(cancel)
        if confirm_kind == "primary":
            confirm = PrimaryButton(confirm_text)
        else:
            confirm = QPushButton(confirm_text)
            confirm.setObjectName("BtnDanger")
        confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm.clicked.connect(self.accept)
        fl.addWidget(confirm)
        root.addWidget(foot)


class Modal(QDialog):
    """通用模态弹窗：头（图标 + 标题 + 关闭）× 体（可组合）× 脚（按钮）。

    用于设置、帮助、关于等富交互弹窗，以及各模块内的新增 / 编辑 / 查重 /
    合并 / 删除预览 / 展开核对等。复用共享样式（ModalHead / ModalFoot /
    BtnPrimary / BtnDanger / BtnGhost），只消费令牌，不硬编码颜色。
    """

    def __init__(self, *, icon: str, title: str, parent=None, min_width: int = 560):
        super().__init__(parent)
        # 标题栏也要有字：v4 原码只在头部标签里写标题，窗口标题留空，
        # 在任务栏 / 无头截图里看是一片空白。这里补上。
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(min_width)
        self._build(icon, title)

    def _build(self, icon, title):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head.setObjectName("ModalHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(18, 16, 18, 16)
        ico = QLabel(icon)
        ico.setFixedSize(30, 30)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background:{c('primary.100')};color:{c('primary.700')};"
            f"border-radius:{r('md')};font-size:{fs('md')}")
        htitle = QLabel(title)
        htitle.setStyleSheet(
            f"font-weight:700;font-size:{fs('lg')};color:{c('neutral.900')}")
        hl.addWidget(ico)
        hl.addWidget(htitle)
        hl.addStretch(1)
        close = QPushButton("×")
        close.setObjectName("ModalClose")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setFixedSize(30, 30)
        close.clicked.connect(self.reject)
        hl.addWidget(close)
        root.addWidget(head)

        self.body = QWidget()
        self.body_l = QVBoxLayout(self.body)
        self.body_l.setContentsMargins(18, 16, 18, 16)
        self.body_l.setSpacing(12)
        root.addWidget(self.body)

        self.foot = QWidget()
        self.foot.setObjectName("ModalFoot")
        self.fl = QHBoxLayout(self.foot)
        self.fl.setContentsMargins(18, 14, 18, 14)
        self.fl.addStretch(1)
        root.addWidget(self.foot)

    def add_note(self, text: str, kind: str = "info") -> QLabel:
        nl = QLabel(text)
        nl.setWordWrap(True)
        if kind == "warn":
            bg, bd, fg = c("warning.bg"), c("warning.border"), c("warning")
        elif kind == "info":
            bg, bd, fg = c("info.bg"), c("info.border"), c("info")
        else:
            bg, bd, fg = c("neutral.100"), c("neutral.200"), c("neutral.600")
        nl.setStyleSheet(
            f"background:{bg};border:1px solid {bd};color:{fg};"
            f"border-radius:{r('lg')};padding:{sp('3')} {sp('4')};font-size:{fs('sm')}")
        self.body_l.addWidget(nl)
        return nl

    def add_widget(self, w: QWidget) -> QWidget:
        self.body_l.addWidget(w)
        return w

    def add_spacing(self, px: int):
        self.body_l.addSpacing(px)

    def add_foot(self, text: str, kind: str = "primary", slot=None) -> QPushButton:
        if kind == "primary":
            btn = PrimaryButton(text)
        else:
            btn = QPushButton(text)
            btn.setObjectName({"danger": "BtnDanger", "ghost": "BtnGhost"}[kind])
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if slot is not None:
            btn.clicked.connect(slot)
        else:
            btn.clicked.connect(self.accept)
        self.fl.addWidget(btn)
        return btn


# ---------------------------------------------------------------------------
# 卡片级联入场（v3 质感层 cardIn 的 Qt 等效）
# ---------------------------------------------------------------------------

def cascade_in(widgets, *, step_ms: int = 55, dur_ms: int = 420) -> None:
    """一组部件错落淡入：第 i 张延迟 i*step_ms，dur_ms 内淡入到不透明。

    原型用 CSS animation cardIn .42s backwards + 每张 55ms 延迟；Qt 侧用
    QGraphicsOpacityEffect + QPropertyAnimation 等效表达。动画结束后摘掉
    effect，避免常驻图形效果影响后续渲染。
    """
    for i, w in enumerate(widgets):
        if w is None or not w.isVisible():
            continue
        eff = QGraphicsOpacityEffect(w)
        eff.setOpacity(0.0)
        w.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", w)
        anim.setDuration(dur_ms)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _done(target=w):
            target.setGraphicsEffect(None)

        anim.finished.connect(_done)
        QTimer.singleShot(i * step_ms, anim.start)
        # 引用挂到部件上，防止局部变量回收导致动画中途失效
        if not hasattr(w, "_cascade_anims"):
            w._cascade_anims = []
        w._cascade_anims.append(anim)
