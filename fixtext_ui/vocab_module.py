"""
FixText V1 · 词库管理模块（Qt 移植 · M3-T3.1 接真实词库）
=========================================================

对照 `FixText_V1_词库管理_原型.html` **1:1 移植**，控件语义与文案逐条对齐。

结构（页头 → 本书专有词库横幅 → 左侧词库分级 + 右侧工作区）：
- 页头：标题 / 副标题 / 分级切换（全部·自定义·内置）
- 本书专有词库横幅（2.4.2）：有真实专有词时才出现，否则整条隐藏
- 左侧词库分级（底线③ 文件不暴露 · 友好名）：我的词库（可编辑）+ 3 内置（只读）
- 右侧工作区：
  · 工具条（§2.4.1 五操作）：新增 / 检索 / 查重 / 合并 / 删除选中 / 展开核对 / 选择计数
  · 词条表格（底线③ 结构化表格 · 不露内部文件格式）+ 翻页
  · 历史与快照面板（底线② 自动快照 · 可恢复）

数据来源（M3-T3.1 起全部为真实词库）
------------------------------------
界面**不再持有任何演示数据**：检索、分页、查重、删除、合并、新增、编辑
全部通过 ``fixtext_vocab.VocabStore`` 读写真实文件——内置词库只读、
「我的词库」独立成文件（分级存储，界面只显示友好名，不露路径）。
新增 / 编辑 / 删除 / 合并都可撤销，撤销是把操作前的**原始字节**整份写回，
因此撤销后的文件与操作前逐字节一致。
"""

from __future__ import annotations

from PySide6.QtCore import (Qt, QTimer, QRect, QRectF, QEvent, Signal, QPoint,
                            QPropertyAnimation, QEasingCurve)
from PySide6.QtGui import (QKeySequence, QShortcut, QFontMetrics, QColor,
                           QPainter, QPainterPath, QPen,
                          QPixmap, QBrush)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QDialog,
    QLineEdit, QComboBox, QCheckBox, QFrame, QSizePolicy, QScrollArea,
    QApplication, QGraphicsDropShadowEffect,
)

import fixtext_settings as app_settings
from fixtext_tokens import c, fs, r, sp, FONT_WEIGHT, FONT_MONO, ICON_GLYPH_SIZE
from fixtext_widgets import (Card, Pill, hline, ConfirmDialog, Modal, page_head_shell,
                             PrimaryButton, ChkMark, enable_chrome, plain_box, repolish)

from fixtext_vocab import (
    ENTRY_TYPES, TIER_NAMES, TIER_ORDER, VocabDataError, VocabStore,
)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 词库表格每页条数（内置词库 30 万条，翻页而不是截断）。
#: 固定 20 条是为了让条目区不再出现内部滚动条：滚动条显隐会改变视口宽度，
#: 使「卡片内固定表头」与「滚动区内数据行」的列宽不一致、肉眼可见地跳动。
#: 每页行数固定 + 无内部滚动条 -> 表头与数据行永远同宽同列，不可能错位。
PAGE_SIZE = 20

#: 历史与快照抽屉分页：每张卡固定条数，避免超长内容把同行挤压、也让抽屉下方不留大片空白
SNAP_PAGE_SIZE = 5
OP_PAGE_SIZE = 5

COL_CHECK_W = 34
COL_ACT_W = 128


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _fmt_num(n: int) -> str:
    """数字加千位分隔（30 万条要看得出量级）。"""
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def _label(text: str, *, size: str = "sm", color: str = "neutral.800",
           weight: str | None = None, wrap: bool = False,
           mono: bool = False, align: str | None = None) -> QLabel:
    lab = QLabel(text)
    _apply_label_style(lab, size=size, color=color, weight=weight, wrap=wrap,
                      mono=mono, align=align)
    return lab


def _apply_label_style(lab: QLabel, *, size: str = "sm", color: str = "neutral.800",
                       weight: str | None = None, wrap: bool = False,
                       mono: bool = False, align: str | None = None) -> None:
    lab.setWordWrap(wrap)
    style = f"color:{c(color)};font-size:{fs(size)};background:transparent;"
    if weight:
        style += f"font-weight:{FONT_WEIGHT[weight]};"
    if mono:
        style += f"font-family:{FONT_MONO};"
    lab.setStyleSheet(style)
    if align == "center":
        lab.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
    elif align == "left":
        lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)


def _dot_pixmap(diameter: int, fill: str, ring: str | None = None,
                ring_w: int = 0) -> QPixmap:
    """生成一张透明背景的圆形点图（可选外环）。

    时间线/操作历史的小圆点改用预渲染的圆形 QPixmap，而不是依赖 QSS 的
    ``border-radius``——后者在部分渲染环境下不会把 QWidget 背景裁剪为圆，会显示成
    方块。用 QPainter 画椭圆则任何绘制引擎都得到正圆。
    """
    pm = QPixmap(diameter, diameter)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    if ring:
        p.setBrush(QBrush(QColor(ring)))
        p.drawEllipse(0, 0, diameter, diameter)
        inner = diameter - 2 * ring_w
        p.setBrush(QBrush(QColor(fill)))
        p.drawEllipse(ring_w, ring_w, inner, inner)
    else:
        p.setBrush(QBrush(QColor(fill)))
        p.drawEllipse(0, 0, diameter, diameter)
    p.end()
    return pm


class _ElideLabel(QLabel):
    """超长省略号截断的标签（Qt6 的 QLabel 无 setElideMode，自行在 resize 时计算）。

    - 横向吃满所在列（sizePolicy=Ignored，不被超长文本撑开、不挤压邻列）；
    - 超长时在末尾显示「…」；悬浮可看全文（`_FullTextPopover`）；
    - ``copyable=True``（原词 / 替换为）：点击复制**本格完整文本**并发 ``copyClicked``，
      不走行级过滤器，避免误伤勾选框。
    """

    copyClicked = Signal(str)

    def __init__(self, text: str = "", *, size: str = "sm", color: str = "neutral.800",
                 weight: str | None = None, mono: bool = False,
                 center: bool = True, copyable: bool = False) -> None:
        super().__init__(text)
        self._full = text
        self._is_elided = False
        self._copyable = bool(copyable)
        _apply_label_style(self, size=size, color=color, weight=weight, wrap=False, mono=mono)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setWordWrap(False)
        if center:
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._elide()

    def setText(self, t: str) -> None:  # type: ignore[override]
        self._full = t
        self._elide()

    def _elide(self) -> None:
        fm = self.fontMetrics()
        elided = fm.elidedText(self._full, Qt.TextElideMode.ElideRight, max(1, self.width()))
        self._is_elided = (elided != self._full)
        if elided != self.text():
            super().setText(elided)
        # 可复制格始终手型；否则仅超长格手型（悬停看全文）
        hand = self._copyable or self._is_elided
        self.setCursor(Qt.CursorShape.PointingHandCursor if hand
                      else Qt.CursorShape.ArrowCursor)

    def resizeEvent(self, ev) -> None:  # 控件宽度随列宽变化时重新截断
        super().resizeEvent(ev)
        self._elide()

    def mousePressEvent(self, ev) -> None:
        if self._copyable and ev.button() == Qt.MouseButton.LeftButton:
            text = self._full or ""
            try:
                cb = QApplication.clipboard()
                if cb is not None and text:
                    cb.setText(text)
            except Exception:
                pass
            _cell_popover().hide_me()
            self.copyClicked.emit(text)
            ev.accept()
            return
        super().mousePressEvent(ev)

    # ---- 悬浮显示完整文本（行为由 _FullTextPopover 单例承载）----
    def enterEvent(self, ev) -> None:
        if self._is_elided and not _cell_popover().is_pinned():
            _cell_popover().show_for(self, self._full, pinned=False)
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:
        pop = _cell_popover()
        if pop.owner_is(self) and not pop.is_pinned():
            pop.hide_me()
        super().leaveEvent(ev)


class _FullTextPopover(QWidget):
    """超长字段悬浮时显示的完整文本浮层（全局单例，同一时间只显示一个）。

    - 悬浮：临时显示，鼠标移开自动隐藏；
    - 仅用于「看全文」；点击复制由可复制格 `_ElideLabel(copyable=True)` 自行处理；
    - 鼠标移开后自动隐藏（由 `_ElideLabel` 的 leaveEvent 处理）。
    """

    _SHADOW_M = 6  # 卡片四周留白环带：给手绘阴影留空间，也让圆角外区域透明

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("CellFullText")
        self._owner = None          # 当前显示所属 _ElideLabel
        self._pinned = False
        # 真·圆角关键：透明背景 + paintEvent 自绘圆角矩形。
        # - 不能用 WA_StyledBackground（enable_chrome）：style 会用矩形把背景再填一遍，
        #   把圆角盖掉 → 看着还是方角；
        # - 不能用 QGraphicsDropShadowEffect：frameless 顶层窗其阴影被矩形窗口裁掉。
        # 改用 WA_TranslucentBackground：窗口矩形外区域天然透明 → 圆角可见；
        # 阴影在 paintEvent 里于四周留白环带内手绘（半透明圆角矩形叠几层模拟柔光）。
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        lay = QVBoxLayout(self)
        # 外圈 _SHADOW_M 留给阴影，内圈 10/8 是文字内边距
        lay.setContentsMargins(self._SHADOW_M + 10, self._SHADOW_M + 8,
                               self._SHADOW_M + 10, self._SHADOW_M + 8)
        lay.setSpacing(6)
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # 文字配色交给 fixtext.qss 的 #CellFullText QLabel（深色底 + 浅色字）
        self._text.setStyleSheet("background:transparent;")
        lay.addWidget(self._text)

    # 圆角背景由 QPainter 自绘：本环境 border-radius 不裁 QWidget 背景，
    # 且 WA_StyledBackground 会让 style 用矩形填背景盖掉圆角。故在 paintEvent 画圆角矩形
    # （深色填充 + 1px 浅边框），外圈留白环带内手绘柔光阴影，子控件（文字）叠在其上。
    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = 8  # 比 sm(4px) 更柔，避免生硬
        rect = QRectF(self.rect())
        m = self._SHADOW_M
        card = rect.adjusted(m, m, -m, -m)   # 卡片内缩，外圈 m 留给阴影
        # 柔和投影：在卡片外缘叠几层半透明圆角矩形（向下微偏移），环带内可见
        for off, alpha in ((0, 0.10), (2, 0.13), (4, 0.12), (6, 0.07)):
            sh = QPainterPath()
            sh.addRoundedRect(rect.adjusted(m - 1, m - 1 + off, -(m - 1), -(m - 1)), r, r)
            p.fillPath(sh, QColor(15, 23, 42, int(alpha * 255)))
        # 卡片本体（圆角矩形）
        path = QPainterPath()
        path.addRoundedRect(card, r, r)
        p.fillPath(path, QColor(c("neutral.900")))
        pen = QPen(QColor(c("neutral.700")))
        pen.setWidth(1)
        p.setPen(pen)
        p.drawPath(path)
        super().paintEvent(ev)

    # ---- 显隐控制（由 _ElideLabel 调用）----
    def show_for(self, label: "_ElideLabel", text: str, *, pinned: bool) -> None:
        self._updating = True                    # 防止自身 setText/show 触发过滤器
        try:
            self._owner = label
            self._pinned = pinned
            self._text.setText(text)
            self.adjustSize()
            self._place_above(label)
            self.show()
            self.raise_()
        finally:
            self._updating = False

    def hide_me(self) -> None:
        self._updating = True
        try:
            self._owner = None
            self._pinned = False
            self.hide()
        finally:
            self._updating = False

    def is_pinned(self) -> bool:
        return self._pinned and self.isVisible()

    def owner_is(self, label: "_ElideLabel") -> bool:
        return self._owner is label and self.isVisible()

    def _place_above(self, label: "_ElideLabel") -> None:
        # 优先显示在单元格正上方，空间不足则放下方；水平居中并夹在屏幕内
        screen = self.screen().availableGeometry() if self.screen() else QRect(0, 0, 1280, 800)
        gp = label.mapToGlobal(label.rect().topLeft())
        pw = min(self.width(), screen.width() - 16)
        ph = self.height()
        x = gp.x() + (label.width() - pw) // 2
        x = max(8, min(x, screen.right() - pw - 8))
        if gp.y() - ph - 6 >= screen.top():
            y = gp.y() - ph - 6
        else:
            y = gp.y() + label.height() + 6
        self.setGeometry(x, y, pw, ph)

    # ---- app 级事件过滤：点击浮层外区域 / 空白关闭 ----
    def eventFilter(self, obj, event) -> bool:
        if getattr(self, "_updating", False):
            return False
        if event.type() == QEvent.Type.MouseButtonPress and self.isVisible():
            # obj 可能是 QWindow（点击落到原生窗口）而非 QWidget，先判型再调 isAncestorOf
            if obj is self or (isinstance(obj, QWidget) and self.isAncestorOf(obj)):
                return False                      # 点到浮层自身 → 不关
            if isinstance(obj, _ElideLabel):
                return False                      # 点到其它超长格 → 交给该格处理器切换
            self.hide_me()                        # 其余外部点击（含 QWindow）→ 关闭
        return False


_cell_popover_inst: "_FullTextPopover | None" = None


def _cell_popover() -> _FullTextPopover:
    """返回全局唯一浮层实例，并挂一次 app 级事件过滤器（保证同时只一个）。"""
    global _cell_popover_inst
    if _cell_popover_inst is None:
        _cell_popover_inst = _FullTextPopover()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(_cell_popover_inst)
    return _cell_popover_inst


def _link_btn(text: str, *, danger: bool = False, enabled: bool = True) -> QPushButton:
    """行内文字按钮（编辑 / 删除）：透明底、主色或危险色、hover 反白。
    配色统一交给 fixtext.qss 的 #LinkBtn / #LinkBtn[danger="true"]（原内联收归）。"""
    btn = QPushButton(text)
    btn.setObjectName("LinkBtn")
    btn.setProperty("danger", "true" if danger else "false")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if not enabled:
        btn.setEnabled(False)
    return btn


def _mini_table(headers: list, rows: list, *, mono_cols: set | None = None) -> QWidget:
    """弹窗里的小表格（纯 QWidget 拼，样式沿用卡片感）。"""
    mono_cols = mono_cols or set()
    box = QFrame()
    box.setObjectName("MiniTable")
    # 配色交给 fixtext.qss 的 QFrame#MiniTable（原内联收归）
    vl = QVBoxLayout(box)
    vl.setContentsMargins(12, 10, 12, 10)
    vl.setSpacing(0)

    head = plain_box(QWidget())
    hl = QHBoxLayout(head)
    hl.setContentsMargins(0, 0, 0, 6)
    hl.setSpacing(10)
    for h in headers:
        hl.addWidget(_label(h, size="xs", color="neutral.600",
                            weight="semibold", align="center"), 1)
    vl.addWidget(head)
    vl.addWidget(hline())

    if not rows:
        vl.addWidget(_label("（无）", size="xs", color="neutral.500",
                            align="center"))
        return box

    for i, row in enumerate(rows):
        rw = plain_box(QWidget())
        rl = QHBoxLayout(rw)
        rl.setContentsMargins(0, 7, 0, 7)
        rl.setSpacing(10)
        for j, cell in enumerate(row):
            rl.addWidget(_label(str(cell), size="xs", color="neutral.800",
                                mono=(j in mono_cols), wrap=True,
                                align="center"), 1)
        vl.addWidget(rw)
        if i != len(rows) - 1:
            vl.addWidget(hline())
    return box


# ---------------------------------------------------------------------------
# 模块
# ---------------------------------------------------------------------------

class VocabModule(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        # ---- 数据：唯一入口，界面自己不拼路径、不直接写文件 ----
        # 存储位置由设置页决定（未配置时 None = 包内默认树）
        self.store = VocabStore(custom_path=app_settings.vocab_custom_file())

        # ---- 状态 ----
        self.tier = "all"          # all / custom / builtin
        self.dict_ = "custom"      # custom / all / b1 / b2 / b3
        self.search = ""
        self._page = 0
        self._hit_total = 0
        self._snap_page = 0      # 快照卡分页
        self._op_page = 0        # 操作历史卡分页
        self._page_rows: list = []
        self._selected: set = set()
        self._pending_add: dict | None = None
        self._merge_sel: list | None = None
        #: 上次查重清单的口径（total / shown / readonly）——验收与自检读它
        self._dup_view: dict = dict(total=0, shown=0, readonly=True)
        self._book_words: list = []       # 真实专有词（空则不显示横幅）
        self._book_title = ""
        self._book_checks: list = []

        self.basis_labels = []
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_status)
        # Ctrl+Z → 撤销（底线①）
        QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self).activated.connect(self._undo)

        # ---- 布局 ----
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        root.addWidget(self._header())
        root.addWidget(hline())
        root.addWidget(self._banner())
        root.addWidget(self._layout_grid())

        self.legend = _label(
            "新增 / 查重 / 删除 / 合并与本书专有词均受五条安全底线约束。",
            size="xs", color="neutral.500", wrap=True)
        root.addWidget(self.legend)

        self._build_status()

        # 历史与快照：改为右侧滑出抽屉（方案 D），内含「快照」与「操作历史」两张独立卡
        self._snap_card = self._snap_card()
        self._op_card = self._op_card()
        self._build_drawer()

        self._render_all()

    # ------------------------------------------------------------------ 头部

    def _header(self) -> QWidget:
        shell, body = page_head_shell()
        hl = QHBoxLayout(body)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        col = QVBoxLayout()
        col.setSpacing(2)
        title = _label("词库管理", size="xl", color="neutral.900", weight="bold")
        title.setObjectName("PageTitle")
        sub = _label(
            "新增、检索、查重、合并、删除词条，并安全维护你的校正词库。",
            size="sm", color="neutral.600", wrap=True)
        sub.setObjectName("PageSub")
        col.addWidget(title)
        col.addWidget(sub)
        hl.addLayout(col, 1)

        right = QHBoxLayout()
        right.setSpacing(14)
        right.setAlignment(Qt.AlignmentFlag.AlignTop)

        # v3 布局对齐：浅色安全徽标 + 浅色图标按钮（页头控件变体）
        safe = QLabel("  安全保护已开启")
        safe.setObjectName("SafeBadge")
        safe.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        safe.setCursor(Qt.CursorShape.PointingHandCursor)
        safe.setToolTip("词库的每一步改动都先留还原点，删错了、合并错了都能退回去")
        # QLabel 背景必须 WA_StyledBackground；样式统一由 fixtext.qss 的 #SafeBadge 提供
        right.addWidget(safe)

        self.hist_btn = self._head_icon_btn("🕑", "历史与快照", self._toggle_drawer)
        right.addWidget(self.hist_btn)
        self.undo_btn = self._head_icon_btn("↩", "撤销上一步（Ctrl+Z）", self._undo)
        right.addWidget(self.undo_btn)

        self._tier_btns = {}
        seg = QWidget()
        seg.setObjectName("TierTabs")
        # 配色交给 fixtext.qss 的 #TierTabs（原内联收归）
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        for t, label in (("all", "全部"), ("custom", "自定义"), ("builtin", "内置")):
            b = QPushButton(label)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setObjectName("TierTab")
            b.clicked.connect(lambda _c, t=t: self.set_tier(t))
            self._tier_btns[t] = b
            sl.addWidget(b)
        right.addWidget(seg)

        hl.addLayout(right)
        self._set_tier_active("all")
        return shell

    def _head_icon_btn(self, glyph: str, tip: str, slot) -> QPushButton:
        """页头浅色图标按钮（原型 .page-head .icon-btn）。
        配色统一交给 fixtext.qss 的 QPushButton#HeadIconBtn（原内联收归）。"""
        b = QPushButton(glyph)
        b.setObjectName("HeadIconBtn")
        b.setFixedSize(34, 34)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip(tip)
        b.setAccessibleName(tip)
        # 完整态（含 hover/pressed）已落在 fixtext.qss，无需控件级内联
        b.clicked.connect(slot)
        return b

    def _set_tier_active(self, t: str):
        for key, b in self._tier_btns.items():
            on = (key == t)
            # 选中态交给 fixtext.qss 的 #TierTab[active="true"]（原内联收归）
            b.setProperty("active", "true" if on else "false")
            b.style().unpolish(b)
            b.style().polish(b)

    # -------------------------------------------------- 本书专有词库横幅（2.4.2）

    def _banner(self) -> QWidget:
        self._banner_w = QWidget()
        self._banner_w.setObjectName("Banner")
        # 配色交给 fixtext.qss 的 #Banner（原内联收归）
        hl = QHBoxLayout(self._banner_w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(14)
        ico = QLabel("✨")
        ico.setObjectName("BannerIco")
        ico.setFixedSize(38, 38)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 图标方块配色交给 fixtext.qss 的 #BannerIco（原内联收归）
        hl.addWidget(ico)
        txt = QVBoxLayout()
        txt.setSpacing(2)
        self._banner_title = _label("", size="base", weight="bold", color="neutral.900")
        txt.addWidget(self._banner_title)
        txt.addWidget(_label("是否把它们加入你的自定义词库？加入后，下次校正同类错误将自动生效。",
                             size="sm", color="neutral.500"))
        hl.addLayout(txt, 1)
        add = PrimaryButton("查看并加入")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(self.open_book_words)
        later = QPushButton("稍后")
        later.setObjectName("BtnGhost")
        later.setCursor(Qt.CursorShape.PointingHandCursor)
        later.clicked.connect(self.hide_banner)
        hl.addWidget(add)
        hl.addWidget(later)
        # 没有真实专有词就不出现——不摆一条假横幅
        self._banner_w.setVisible(False)
        return self._banner_w

    def set_book_words(self, words: list, title: str = ""):
        """真实专有词入口：只有真的提取到条目时才显示横幅（2.4.2）。"""
        self._book_words = [dict(w) if isinstance(w, dict) else dict(word=w, note="")
                            for w in (words or [])]
        self._book_title = title or ""
        if not self._book_words:
            self._banner_w.setVisible(False)
            return
        head = f"《{self._book_title}》" if self._book_title else ""
        self._banner_title.setText(
            f"{head}校正完成，发现 {_fmt_num(len(self._book_words))} 条本书专有词条")
        self._banner_w.setVisible(True)

    def hide_banner(self):
        self._banner_w.setVisible(False)

    # -------------------------------------------------- 左词库列表 + 右工作区

    def _layout_grid(self) -> QWidget:
        grid = QWidget()
        gl = QHBoxLayout(grid)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(16)
        gl.setAlignment(Qt.AlignmentFlag.AlignTop)

        gl.addWidget(self._dict_list(), 0, Qt.AlignmentFlag.AlignTop)
        gl.addWidget(self._workspace(), 1)
        return grid

    # ----- 左侧词库分级（底线③ 文件不暴露 · 友好名）-----

    def _dict_list(self) -> Card:
        card = Card("词库", basis="底线③ 文件不暴露 · 友好名")
        self.basis_labels.append(card.basis)
        card.body_l.setSpacing(6)

        self._dict_items = {}
        for d in TIER_ORDER:
            item = self._dict_item(d)
            self._dict_items[d] = item
            card.body_l.addWidget(item)

        self._set_dict_active(self.dict_)
        return card

    def _dict_item(self, d: str) -> QWidget:
        item = QWidget()
        item.setObjectName("DictItem")
        item.setCursor(Qt.CursorShape.PointingHandCursor)
        hl = QHBoxLayout(item)
        hl.setContentsMargins(10, 10, 10, 10)
        hl.setSpacing(10)
        _ico = {
            "custom": "✎", "b1": "📕", "cjk": "📙", "b3": "📘",
            "b3r": "📕", "extra": "📔", "ddd": "📖", "dei2de": "📑",
            "old_style": "📜", "txt_format": "📰",
            "preprocess": "📙", "strict": "📓", "zhuyin": "📒",
        }.get(d, "📘")
        ico = QLabel(_ico)
        ico.setFixedSize(22, 22)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background:{c('success.bg') if d=='custom' else c('info.bg')};"
            f"border-radius:{r('md')};font-size:{fs('xs')}")
        hl.addWidget(ico)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(_label(TIER_NAMES[d], size="sm", weight="bold", color="neutral.800"))
        meta = _label("", size="xs", color="neutral.500")
        col.addWidget(meta)
        item._meta = meta
        hl.addLayout(col, 1)
        lock = QLabel("✎" if d == "custom" else "🔒")
        lock.setStyleSheet(
            f"color:{'transparent' if d=='custom' else c('neutral.500')};font-size:{fs('xs')}")
        hl.addWidget(lock)
        item.mousePressEvent = lambda e, d=d: self.select_dict(d)
        return item

    def counts(self) -> dict:
        return self.store.counts()

    def _set_dict_active(self, d: str):
        counts = self.counts()
        for key, item in self._dict_items.items():
            on = (key == d)
            # 选中态交给 fixtext.qss 的 #DictItem[active="true"]（原内联收归）
            item.setProperty("active", "true" if on else "false")
            item.style().unpolish(item)
            item.style().polish(item)
            item._meta.setText(
                f"{_fmt_num(counts.get(key, 0))} 条 · {'可编辑' if key=='custom' else '只读'}")

    # ----- 右侧工作区 -----

    def _workspace(self) -> QWidget:
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(16)
        col.addWidget(self._toolbar(), 0)       # 不拉伸
        col.addWidget(self._table_card(), 1)    # 吃剩余高度
        w = QWidget()
        w.setLayout(col)
        return w

    # ----- 工具条（§2.4.1 五操作）-----

    def _toolbar(self) -> Card:
        card = Card(basis="§2.4.1 五操作 · 新增为 V1 补入")
        self.basis_labels.append(card.basis)
        card.body_l.setSpacing(10)
        # M5-EX.4.2 / BUG-1d：工具条高度不随空列表撑大
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        bar = plain_box(QWidget())
        bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)   # 6 而非 8：给整页横向留出余量，避免最小窗口下仍出横向滑条

        add = PrimaryButton("＋ 新增词条")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(self.open_add)
        bl.addWidget(add)

        self._search = QLineEdit()
        self._search.setObjectName("Search")
        self._search.setPlaceholderText("检索词或替换值…（双向）")
        # 不做 setMinimumWidth：检索框以 stretch=1 自适应宽度，原本强制的 200px
        # 会把它的最小宽度顶到 200，连带整条工具条最小宽涨到 ~826px，超过默认
        # 内容区（约 1028px）使整页出现横向滚动条（真实缺陷）。现在交给布局分配。
        # 配色交给 fixtext.qss 的 #Search（原内联收归）
        self._search.textChanged.connect(self._on_search)
        bl.addWidget(self._search, 1)

        dup = QPushButton("🔁 查重")
        dup.setObjectName("BtnOutline")
        dup.setCursor(Qt.CursorShape.PointingHandCursor)
        dup.clicked.connect(self.open_dup)
        bl.addWidget(dup)

        self._merge_btn = QPushButton("合并")
        self._merge_btn.setObjectName("BtnOutline")
        self._merge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._merge_btn.clicked.connect(self.open_merge)
        bl.addWidget(self._merge_btn)

        self._del_btn = QPushButton("🗑 删除选中")
        self._del_btn.setObjectName("BtnDanger")
        self._del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._del_btn.clicked.connect(self._on_delete_selected)
        bl.addWidget(self._del_btn)

        expand = QPushButton("📋 展开核对")
        expand.setObjectName("BtnOutline")
        expand.setCursor(Qt.CursorShape.PointingHandCursor)
        expand.clicked.connect(self.open_expand)
        bl.addWidget(expand)

        card.body_l.addWidget(bar)

        # 选中计数不放在工具条这一行：文案从「未选择」变成「已选 N 条（可删 M 条）」
        # 时宽度暴涨，HBox 空间不够会反过来压缩左侧按钮和检索框（实测「查重/
        # 合并/删除选中」整体左移 67px、检索框被压到 44px）。改放反馈行右端并
        # 按最长文案钉死宽度：文案变化不再参与工具条宽度分配，按钮永远不动；
        # 右对齐使计数右边缘恒定，视觉位置也不跳。
        self._sel_count = _label("未选择", size="xs", color="neutral.500")
        self._sel_count.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        fm = QFontMetrics(self._sel_count.font())
        self._sel_count.setFixedWidth(
            fm.horizontalAdvance("已选 9999 条（可删 9999 条）") + 8)

        self._hint = _label("", size="xs", color="neutral.500", wrap=True)
        self._hint.setVisible(False)
        feedback = QHBoxLayout()
        feedback.setContentsMargins(0, 0, 0, 0)
        feedback.setSpacing(8)
        feedback.addWidget(self._hint, 1)
        feedback.addWidget(self._sel_count, 0)
        card.body_l.addLayout(feedback)
        return card

    # ----- 词条表格（底线③ 结构化表格 · 不露内部文件格式）-----

    def _table_card(self) -> Card:
        card = Card(basis="底线③ 结构化表格 · 不露内部文件格式")
        self.basis_labels.append(card.basis)
        card.body_l.setSpacing(0)
        # 列表区吃竖直剩余空间；空态也不反向撑工具条
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        # 固定表头（不随条目滚动，解决「表头没固定」）；表头自带底部分隔线，不再叠 hline
        card.body_l.addWidget(self._entry_header())

        # 条目区：不再内嵌滚动条。固定每页 PAGE_SIZE 条，翻页由底部翻页器负责。
        # 这样列宽度恒定，表头永远与数据列对齐 —— 彻底消除「纵向滚动条出现/消失
        # 时视口变窄、表头列与数据列错位跳动」的问题（之前用同步右留白补偿，真机仍抖）。
        self._scroll_inner = QWidget()
        self._scroll_inner.setObjectName("VocabScrollInner")   # 白底（衬出表头灰带）
        # 保留 _scroll_* 命名仅为少改引用；它现在只是普通容器，不是滚动区。
        self._scroll_inner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._scroll_layout = QVBoxLayout(self._scroll_inner)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(0)
        card.body_l.addWidget(self._scroll_inner, 1)

        card.body_l.addWidget(hline())
        self._pager_widget = self._pager()
        card.body_l.addWidget(self._pager_widget)

        self._render_entries()
        return card

    def _entry_header(self) -> QWidget:
        # 表头做成独立色带，跟数据行区分（背景 + 底部分隔线 + 上方圆角，
        # 见 build_qss #VocabTableHeader）。圆角沿用项目卡片的既有机制：
        # enable_chrome(WA_StyledBackground) + QSS border/border-radius，
        # 不做任何自绘。
        row = QWidget()
        row.setObjectName("VocabTableHeader")
        enable_chrome(row)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 10, 0, 10)
        hl.setSpacing(12)

        # 勾选列：容器居中，避免 ChkMark 紧贴左侧
        chk_cell = QWidget()
        cl = QHBoxLayout(chk_cell)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chk_all = ChkMark()
        self._chk_all.clicked.connect(self._toggle_all)
        cl.addWidget(self._chk_all)
        hl.addWidget(chk_cell, 0)
        chk_cell.setFixedWidth(COL_CHECK_W)

        for text, stretch in (("原词", 3), ("替换为", 3), ("类型", 2), ("来源", 2), ("命中书籍", 3)):
            lab = _label(text, size="xs", color="neutral.600", weight="semibold")
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)   # 同列居中对齐
            hl.addWidget(lab, stretch)
        act = _label("操作", size="xs", color="neutral.600", weight="semibold")
        act.setAlignment(Qt.AlignmentFlag.AlignCenter)      # 与每行操作列同宽且居中，保证表头与行对齐
        act.setFixedWidth(COL_ACT_W)   # 与每行的操作列（acts.setFixedWidth）同宽，保证表头与行对齐
        hl.addWidget(act, 0)
        return row

    def _entry_row(self, e: dict) -> QWidget:
        row = QWidget()
        row.setObjectName("VocabRow")   # 数据行白底（与表头灰带区分）
        row._entry = e                  # 供行级点击复制过滤器读取整条词条
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 12, 0, 12)
        hl.setSpacing(12)

        is_builtin = e.get("tier") == "builtin"
        # 勾选列：容器居中 + ChkMark 自绘（与表头全选同风格）
        chk_cell = QWidget()
        cl = QHBoxLayout(chk_cell)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chk = ChkMark()
        chk.setChecked(e["id"] in self._selected)
        chk.setLocked(is_builtin)            # 内置条目锁定（灰显 + 不可切换）
        chk.clicked.connect(lambda on, i=e["id"]: self._toggle_row(i, on))
        cl.addWidget(chk)
        hl.addWidget(chk_cell, 0)
        chk_cell.setFixedWidth(COL_CHECK_W)

        # 原词 + 拼音：竖向堆叠；点击原词复制本格全文
        word_col = QVBoxLayout()
        word_col.setContentsMargins(0, 0, 0, 0)   # 清掉默认边距，否则词列文字比表头右移约 9px
        word_col.setSpacing(1)
        wlab = _ElideLabel(e["word"], size="sm", weight="bold",
                           color="neutral.900", mono=True, copyable=True)
        wlab.copyClicked.connect(self._on_cell_copied)
        word_col.addWidget(wlab)
        if e.get("pinyin"):
            plab = _label(f"/{e['pinyin']}", size="xs",
                          color="neutral.500", mono=True)
            plab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            word_col.addWidget(plab)
        wbox = QWidget()
        wbox.setLayout(word_col)
        wbox.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        hl.addWidget(wbox, 3)

        # 替换为：点击复制本格全文；类型列不复制
        vlab = _ElideLabel(e["value"], size="sm", color="primary.700", mono=True,
                           copyable=True)
        vlab.copyClicked.connect(self._on_cell_copied)
        hl.addWidget(vlab, 3)

        tlab = _ElideLabel(e.get("type") or "—", size="sm", color="neutral.600")
        hl.addWidget(tlab, 2)

        # 来源列用容器包住 Pill：容器吃满 stretch 列宽（与表头对齐），
        # 徽标本身 Maximum/Fixed 不拉伸，居中显示
        src_cell = QWidget()
        sl = QHBoxLayout(src_cell)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        sl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sl.addWidget(Pill("自定义" if not is_builtin else "内置",
                          "ok" if not is_builtin else "info"))
        src_cell.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        hl.addWidget(src_cell, 2)

        # 命中书籍：超长省略号截断，居中
        bk = _ElideLabel(("📖 " + "、".join(e["books"])) if e.get("books") else "—",
                         size="xs", color="neutral.600")
        hl.addWidget(bk, 3)

        # 操作：按钮居中（与表头操作列同宽、同对齐）
        acts = QWidget()
        al = QHBoxLayout(acts)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        al.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if not is_builtin:
            edit = _link_btn("编辑")
            edit.clicked.connect(lambda _c, i=e["id"]: self.open_edit(i))
            al.addWidget(edit)
            dele = _link_btn("删除", danger=True)
            dele.clicked.connect(lambda _c, i=e["id"]: self._confirm_delete([i]))
            al.addWidget(dele)
        else:
            al.addWidget(_label("只读", size="xs", color="neutral.400"))
        hl.addWidget(acts, 0)
        acts.setFixedWidth(COL_ACT_W)
        return row

    def _pager(self) -> QWidget:
        row = plain_box(QWidget())
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 12, 0, 2)
        hl.setSpacing(10)
        self.page_label = _label("", size="xs", color="neutral.500")
        hl.addWidget(self.page_label)
        hl.addStretch(1)
        self.prev_btn = QPushButton("上一页")
        self.prev_btn.setObjectName("BtnOutline")
        self.prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_btn.clicked.connect(lambda: self.turn_page(-1))
        self.next_btn = QPushButton("下一页")
        self.next_btn.setObjectName("BtnOutline")
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.clicked.connect(lambda: self.turn_page(1))
        hl.addWidget(self.prev_btn)
        hl.addWidget(self.next_btn)
        return row

    # ----- 历史与快照（底线② 自动快照 · 可恢复 · 方案 D 右侧滑出抽屉）-----

    def _build_drawer(self):
        """构造右侧滑出抽屉（含「快照」与「操作历史」两张独立卡）。

        层级：``SnapDrawerLayer``（满铺 VocabModule，默认隐藏）→ 半透明
        ``SnapDrawerBackdrop``（点击关闭）+ ``SnapDrawerPanel``（右侧面板，
        内嵌可滚动的两张卡）。面板用 QPropertyAnimation 在 x 方向滑入/滑出。
        """
        layer = QWidget(self)
        layer.setObjectName("SnapDrawerLayer")
        layer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layer.setVisible(False)

        backdrop = QWidget(layer)
        backdrop.setObjectName("SnapDrawerBackdrop")
        backdrop.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        backdrop.mousePressEvent = lambda _e: self._close_drawer()

        panel = QWidget(layer)
        panel.setObjectName("SnapDrawerPanel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 柔和投影，增强抽屉浮起感（不依赖 QSS box-shadow）
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 0)
        shadow.setColor(QColor(15, 23, 42, 70))
        panel.setGraphicsEffect(shadow)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)

        # 抽屉头：标题 + 关闭按钮
        ph = QWidget()
        ph.setObjectName("DrawerHead")
        ph.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        phl = QHBoxLayout(ph)
        phl.setContentsMargins(20, 16, 16, 16)
        phl.setSpacing(10)
        phl.addWidget(_label("历史与快照", size="base", color="neutral.900", weight="bold"))
        phl.addStretch(1)
        close = QPushButton("✕")
        close.setObjectName("DrawerCloseBtn")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("关闭")
        close.clicked.connect(self._close_drawer)
        phl.addWidget(close)

        # 滚动区：承载两张卡
        scroll = QScrollArea()
        scroll.setObjectName("DrawerScroll")
        scroll.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("DrawerScrollInner")   # 透明，避免全局灰底盖住面板圆角与下方留白
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        cl = QVBoxLayout(content)
        cl.setContentsMargins(20, 16, 20, 20)
        cl.setSpacing(16)
        cl.addWidget(self._snap_card, 0)
        cl.addWidget(self._op_card, 0)
        scroll.setWidget(content)

        pl.addWidget(ph, 0)
        pl.addWidget(scroll, 1)

        self._drawer = layer
        self._drawer_backdrop = backdrop
        self._drawer_panel = panel
        self._drawer_anim: QPropertyAnimation | None = None
        self._drawer_pw = 380

    def _layout_drawer(self):
        """把抽屉层 / 遮罩 / 面板钉到**顶层窗口**尺寸（覆盖整页，而非仅词库模块区域）。"""
        host = self.window()
        if host is None or host is self:
            host = self
        if self._drawer.parent() is not host:
            self._drawer.setParent(host)
        self._drawer.raise_()  # 盖在页面（含左轨）之上
        w, h = host.width(), host.height()
        self._drawer.setGeometry(0, 0, w, h)
        self._drawer_backdrop.setGeometry(0, 0, w, h)
        pw = int(min(400, max(320, w - 80)))
        self._drawer_pw = pw
        self._drawer_panel.setFixedWidth(pw)
        self._drawer_panel.setGeometry(w - pw - 16, 16, pw, h - 32)

    def _toggle_drawer(self):
        if self._drawer.isVisible():
            self._close_drawer()
        else:
            self._open_drawer()

    def _open_drawer(self):
        if self._drawer.isVisible():
            return
        self._layout_drawer()
        host = self._drawer.parent()
        hw = host.width()
        self._drawer.setVisible(True)
        # 从屏幕右侧外滑入
        self._drawer_panel.move(hw, 16)
        self._animate_panel(hw - self._drawer_pw - 16)
        self.hist_btn.setProperty("active", "true")
        repolish(self.hist_btn)

    def _close_drawer(self):
        if not self._drawer.isVisible():
            return
        host = self._drawer.parent()
        self._animate_panel(host.width(), on_finish=lambda: self._drawer.setVisible(False))
        self.hist_btn.setProperty("active", "false")
        repolish(self.hist_btn)

    def _animate_panel(self, to_x: int, on_finish=None):
        if self._drawer_anim is not None:
            self._drawer_anim.stop()
        anim = QPropertyAnimation(self._drawer_panel, b"pos")
        anim.setDuration(200)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic if on_finish is None else QEasingCurve.Type.InCubic)
        anim.setEndValue(QPoint(to_x, 16))
        if on_finish:
            anim.finished.connect(on_finish)
        anim.start()
        self._drawer_anim = anim

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if getattr(self, "_drawer", None) and self._drawer.isVisible():
            self._layout_drawer()
            # 保持面板停靠在正确 x（不开动画）
            host = self._drawer.parent()
            self._drawer_panel.move(host.width() - self._drawer_pw - 16, 16)

    def _snap_card(self) -> Card:
        """「历史与快照」抽屉里**快照**那张独立卡（底线② 自动快照 · 可恢复）。

        面板头左边是「快照」标题、右边是「恢复默认词库」按钮（原型同一位置、
        同一文案）；下方是时间线（``renderSnaps`` 的 1:1 移植）。只显示人话，
        不出现路径。
        """
        card = Card(basis="底线② 自动快照 · 可恢复")
        self.basis_labels.append(card.basis)
        card.body_l.setSpacing(8)
        card.body_l.setContentsMargins(16, 10, 16, 12)

        head = plain_box(QWidget())
        enable_chrome(head)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        hl.addWidget(_label("快照", size="base", color="neutral.800", weight="semibold"))
        hl.addStretch(1)
        self._restore_btn = QPushButton("↺ 恢复默认词库（保留自定义）")
        self._restore_btn.setObjectName("BtnGhost")
        self._restore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._restore_btn.clicked.connect(self.restore_default)
        hl.addWidget(self._restore_btn)
        card.body_l.addWidget(head)

        # ---- 时间线 ----
        self._snap_list = QVBoxLayout()
        self._snap_list.setSpacing(0)
        wrap = plain_box(QWidget())
        enable_chrome(wrap)
        wrap.setLayout(self._snap_list)
        card.body_l.addWidget(wrap)

        # ---- 分页器 ----
        self._snap_pager, self._snap_prev, self._snap_pager_lab, self._snap_next = \
            self._build_pager(self._snap_prev_page, self._snap_next_page)
        card.body_l.addWidget(self._snap_pager)
        return card

    def _op_card(self) -> Card:
        """「历史与快照」抽屉里**操作历史**那张独立卡（每次变更的时间点 + 摘要）。"""
        card = Card(basis="每次改动可追溯")
        self.basis_labels.append(card.basis)
        card.body_l.setSpacing(8)
        card.body_l.setContentsMargins(16, 10, 16, 12)

        # ---- 操作历史 ----
        op_head = QHBoxLayout()
        op_head.setContentsMargins(0, 0, 0, 0)
        op_head.setSpacing(8)
        op_head.addWidget(_label("操作历史", size="base", color="neutral.800", weight="semibold"))
        self._op_summary = _label("", size="xs", color="neutral.500")
        op_head.addWidget(self._op_summary)
        op_head.addStretch(1)
        body_w = plain_box(QWidget())
        enable_chrome(body_w)
        body_w.setLayout(op_head)
        card.body_l.addWidget(body_w)

        self._op_list = QVBoxLayout()
        self._op_list.setSpacing(0)
        ops_wrap = plain_box(QWidget())
        enable_chrome(ops_wrap)
        ops_wrap.setLayout(self._op_list)
        card.body_l.addWidget(ops_wrap)

        # ---- 分页器 ----
        self._op_pager, self._op_prev, self._op_pager_lab, self._op_next = \
            self._build_pager(self._op_prev_page, self._op_next_page)
        card.body_l.addWidget(self._op_pager)
        return card

    def _build_pager(self, prev_slot, next_slot):
        """抽屉内卡片底部的「上一页 / 第 x / y 页 / 下一页」分页器。"""
        box = QWidget()
        box.setObjectName("DrawerPager")
        hl = QHBoxLayout(box)
        hl.setContentsMargins(0, 8, 0, 0)
        hl.setSpacing(8)
        prev = QPushButton("‹ 上一页")
        prev.setObjectName("BtnGhost")
        prev.setCursor(Qt.CursorShape.PointingHandCursor)
        prev.clicked.connect(prev_slot)
        lab = _label("", size="xs", color="neutral.500")
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nxt = QPushButton("下一页 ›")
        nxt.setObjectName("BtnGhost")
        nxt.setCursor(Qt.CursorShape.PointingHandCursor)
        nxt.clicked.connect(next_slot)
        hl.addStretch(1)
        hl.addWidget(prev)
        hl.addWidget(lab)
        hl.addWidget(nxt)
        hl.addStretch(1)
        return box, prev, lab, nxt

    def _snap_prev_page(self):
        if self._snap_page > 0:
            self._snap_page -= 1
            self._render_snaps()

    def _snap_next_page(self):
        self._snap_page += 1
        self._render_snaps()

    def _op_prev_page(self):
        if self._op_page > 0:
            self._op_page -= 1
            self._render_ops()

    def _op_next_page(self):
        self._op_page += 1
        self._render_ops()

    # ------------------------------------------------------------------ 渲染

    def _scope(self) -> str:
        """当前选择折算成数据层的检索范围。"""
        if self.dict_ == "custom":
            return "custom"
        if self.dict_ in TIER_NAMES and self.dict_ != "custom":
            return self.dict_
        if self.tier == "custom":
            return "custom"
        if self.tier == "builtin":
            return "builtin"
        return "all"

    def _render_all(self):
        self._render_entries()
        self._set_dict_active(self.dict_)
        self._render_snaps()
        self._render_ops()
        self._update_sel_state()
        self._render_hint()

    def _render_hint(self):
        warn = self.store.warning() if hasattr(self.store, "warning") else ""
        if warn:
            self._hint.setText(warn)
            self._hint.setVisible(True)
        else:
            self._hint.setVisible(False)

    def get_filtered(self) -> list:
        """当前页的行（真实数据；不再是内存里的假列表）。"""
        return list(self._page_rows)

    def pages(self) -> int:
        return max(1, (self._hit_total + PAGE_SIZE - 1) // PAGE_SIZE)

    def _render_entries(self):
        # 表头 / 分页是卡片内固定部件，这里只重建当前页的条目区（固定 PAGE_SIZE 行）
        self._clear_layout(self._scroll_layout)

        total, rows = self.store.query(self.search, scope=self._scope(),
                                       offset=self._page * PAGE_SIZE, limit=PAGE_SIZE)
        self._hit_total = total
        self._page_rows = rows
        # 页码越界（删完 / 检索变少）时回到最后一页
        if self._page >= self.pages():
            self._page = self.pages() - 1
            total, rows = self.store.query(self.search, scope=self._scope(),
                                           offset=self._page * PAGE_SIZE, limit=PAGE_SIZE)
            self._hit_total = total
            self._page_rows = rows

        if not rows:
            # 空态紧凑贴顶，不把卡片撑大（解决「没数据时变得很大」）
            self._scroll_layout.addWidget(self._empty_state())
            self._scroll_layout.addStretch(1)
            self._pager_widget.setVisible(False)
            return

        self._pager_widget.setVisible(True)
        for i, e in enumerate(rows):
            self._scroll_layout.addWidget(self._entry_row(e))
            if i != len(rows) - 1:
                self._scroll_layout.addWidget(hline())
        # 末尾留弹性空白：行数不满一屏时把多余高度沉到底部，
        # 否则 QVBoxLayout 会把所有行等分拉伸（数据行被撑成半屏高，视觉上「列表长度不定」）
        self._scroll_layout.addStretch(1)
        self._update_pager()

    def _empty_state(self) -> QWidget:
        """空状态给人话，不摆假词条（底线：无数据就说无数据）。"""
        q = self.search.strip()
        if q:
            msg = (f"没有找到包含「{q}」的词条。\n"
                   "换个词试试，或切到别的分级（自定义 / 内置）再看。")
        elif self._scope() == "custom":
            msg = ("我的词库还没有词条。\n"
                   "点左上「＋ 新增词条」把常错的词加进来，下次校正会自动生效。")
        else:
            msg = "当前分级下没有可显示的词条。"
        lab = _label(msg, size="sm", color="neutral.500", wrap=True)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setContentsMargins(0, 32, 0, 32)
        return lab

    def _update_pager(self):
        total = self._hit_total
        pages = self.pages()
        if total == 0:
            self.page_label.setText("共 0 条")
        else:
            start = self._page * PAGE_SIZE + 1
            end = min(total, (self._page + 1) * PAGE_SIZE)
            self.page_label.setText(
                f"第 {start}–{end} 条 / 共 {_fmt_num(total)} 条 · 第 {self._page + 1}/{pages} 页")
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page + 1 < pages)

    def turn_page(self, delta: int):
        target = self._page + delta
        if target < 0 or target >= self.pages():
            return
        self._page = target
        self._render_entries()

    @staticmethod
    def _clear_layout(lay: QVBoxLayout):
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _render_snaps(self):
        """时间线：对齐原型 ``renderSnaps()``，按 ``SNAP_PAGE_SIZE`` 分页。

        原型语义逐条对齐：
        * 最新一个在前，圆点高亮 + 时间带「· 当前工作区」，且不显示「恢复到此」；
        * 其余每个时间点都带「恢复到此」链接；
        * 左侧导轨 + 节点构成连续时间线（原型 ``.timeline::before`` 的竖向连接线）；
        * 一条记录都没有时，给空状态说明（不写任何内部概念）。
        """
        self._clear_layout(self._snap_list)
        all_recs = self.store.timeline(limit=None)
        total = len(all_recs)
        pages = max(1, (total + SNAP_PAGE_SIZE - 1) // SNAP_PAGE_SIZE)
        self._snap_page = min(self._snap_page, pages - 1)
        start = self._snap_page * SNAP_PAGE_SIZE
        records = all_recs[start:start + SNAP_PAGE_SIZE]

        if not records:
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 12, 0, 12)
            v.setSpacing(4)
            t = _label("还没有可恢复的时间点", size="sm", color="neutral.800", weight="semibold")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sub = _label("新增 / 编辑 / 删除 / 合并词条时，会自动留一份，随时能回到当时的样子。",
                         size="xs", color="neutral.500", wrap=True)
            sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(t)
            v.addWidget(sub)
            self._snap_list.addWidget(box)
            self._snap_pager.setVisible(False)
            return

        n = len(records)
        for i, rec in enumerate(records):
            cur = bool(rec.get("is_current"))
            item = QWidget()
            item.setObjectName("SnapRow")
            if i == n - 1:
                item.setProperty("last", "true")
            hl = QHBoxLayout(item)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(0)

            # ---- 左侧导轨 + 节点（连续时间线：直线贯穿圆形）----
            # 关键：导轨必须纵向撑满整行高度（否则塌成 9px 灰块，看着像「直角框」），
            # 且横向居中，使竖线与圆点同心 → 直线从圆点正中穿过（对齐原型）。
            gutter = plain_box(QWidget())
            enable_chrome(gutter)
            gutter.setFixedWidth(22)
            gl = QGridLayout(gutter)
            gl.setContentsMargins(0, 0, 0, 0)
            gl.setSpacing(0)
            gl.setRowStretch(0, 1)
            rail = QFrame()
            rail.setObjectName("TimelineRail")
            rail.setFixedWidth(2)
            rail.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            gl.addWidget(rail, 0, 0, Qt.AlignmentFlag.AlignHCenter)
            dot = QLabel()
            dot.setObjectName("SnapDot")
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # 用预渲染圆形 QPixmap（不依赖 QSS border-radius）：
            # 当前点 16px、绿色实心 10px + 浅绿外环；常态 10px 灰色。
            if cur:
                dot.setPixmap(_dot_pixmap(20, c("success"), ring=c("success.bg"), ring_w=3))
                dot.setFixedSize(20, 20)
            else:
                dot.setPixmap(_dot_pixmap(10, c("neutral.200")))
                dot.setFixedSize(10, 10)
            gl.addWidget(dot, 0, 0, Qt.AlignmentFlag.AlignCenter)
            hl.addWidget(gutter)

            # ---- 内容（超长标签省略，避免挤压右侧时间与「恢复到此」）----
            cl = QHBoxLayout()
            cl.setContentsMargins(10, 9, 4, 9)
            cl.setSpacing(10)
            cl.addWidget(_ElideLabel(rec["label"], size="sm", weight="semibold",
                                     color="neutral.800", center=False), 1)
            txt = rec.get("time", "")
            cl.addWidget(_label(f"{txt} · 当前工作区" if cur else txt, size="xs",
                                color="neutral.500"))
            if not cur:
                b = _link_btn("恢复到此")
                b.setToolTip(f"回到 {rec.get('time', '')} 这一刻的词库内容")
                b.clicked.connect(lambda _c, pid=int(rec["id"]): self.restore_point(pid))
                cl.addWidget(b)
            hl.addLayout(cl)
            repolish(item)
            self._snap_list.addWidget(item)

        self._snap_pager.setVisible(total > SNAP_PAGE_SIZE)
        self._snap_pager_lab.setText(f"第 {self._snap_page + 1} / {pages} 页")
        self._snap_prev.setEnabled(self._snap_page > 0)
        self._snap_next.setEnabled(self._snap_page < pages - 1)

    def _render_ops(self):
        """操作历史：每次变更的时间点 + 摘要（对齐原型 ``renderOpHistory()``），按
        ``OP_PAGE_SIZE`` 分页。

        每行固定为「圆点 + 类型徽标 + 摘要（超长省略）+ 时间/当前」，不再带
        「回到这里」按钮（原型即无此按钮）；当前时间点只标「当前」徽标。
        """
        self._clear_layout(self._op_list)
        all_rows = self.store.ops(limit=None)
        total = len(all_rows)
        pages = max(1, (total + OP_PAGE_SIZE - 1) // OP_PAGE_SIZE)
        self._op_page = min(self._op_page, pages - 1)
        start = self._op_page * OP_PAGE_SIZE
        rows = all_rows[start:start + OP_PAGE_SIZE]
        self._op_summary.setText(f"共 {_fmt_num(total)} 次变更" if total else "")

        if not rows:
            lab = _label("还没有操作记录。每次改动都会记下时间与内容，可随时回到某个时间点。",
                         size="xs", color="neutral.500", wrap=True)
            lab.setContentsMargins(0, 6, 0, 2)
            self._op_list.addWidget(lab)
            self._op_pager.setVisible(False)
            return

        current_pid = self.store.current_point_id()
        n = len(rows)
        for i, op in enumerate(rows):
            item = QWidget()
            item.setObjectName("OpRow")
            if i == n - 1:
                item.setProperty("last", "true")
            hl = QHBoxLayout(item)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(0)

            # ---- 左侧圆点列：与上方快照时间轴同宽同列（蓝色原点落在同一 x），
            #        仅保留圆点、不画竖线（用户要求：操作历史不要竖线）----
            gutter = plain_box(QWidget())
            enable_chrome(gutter)
            gutter.setFixedWidth(22)
            gl = QGridLayout(gutter)
            gl.setContentsMargins(0, 0, 0, 0)
            gl.setSpacing(0)
            gl.setRowStretch(0, 1)
            dot = QLabel()
            dot.setObjectName("OpDot")
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setPixmap(_dot_pixmap(8, c("primary.400")))
            dot.setFixedSize(8, 8)
            gl.addWidget(dot, 0, 0, Qt.AlignmentFlag.AlignCenter)
            hl.addWidget(gutter)

            # ---- 内容 ----
            cl = QHBoxLayout()
            cl.setContentsMargins(10, 7, 4, 7)
            cl.setSpacing(10)
            kind = str(op.get("act") or "note")
            badge = QLabel(op.get("act_name", "变更"))
            badge.setObjectName("OpKind")
            badge.setProperty("kind", kind)
            enable_chrome(badge)
            cl.addWidget(badge)

            # 摘要超长省略（否则会挤压右侧时间/「当前」徽标）
            cl.addWidget(_ElideLabel(op.get("summary", ""), size="sm",
                                     color="neutral.800", center=False), 1)

            pid = int(op.get("point_id") or 0)
            if pid and pid == current_pid:
                tag = QLabel("当前")
                tag.setObjectName("TagCurrent")
                enable_chrome(tag)
                cl.addWidget(tag)
            else:
                cl.addWidget(_label(op.get("time", ""), size="xs", color="neutral.500"))
            hl.addLayout(cl)
            repolish(item)
            self._op_list.addWidget(item)

        self._op_pager.setVisible(total > OP_PAGE_SIZE)
        self._op_pager_lab.setText(f"第 {self._op_page + 1} / {pages} 页")
        self._op_prev.setEnabled(self._op_page > 0)
        self._op_next.setEnabled(self._op_page < pages - 1)

    def _update_sel_state(self):
        valid = [i for i in self._selected if self._is_custom(i)]
        self._sel_count.setText(
            f"已选 {_fmt_num(len(self._selected))} 条（可删 {_fmt_num(len(valid))}）"
            if self._selected else "未选择")
        self._del_btn.setEnabled(len(valid) > 0)
        self._merge_btn.setEnabled(len(valid) >= 2)

    # ------------------------------------------------------------------ 选择

    def _is_custom(self, i) -> bool:
        """内置词条用负数 id，天然与自定义（正 id）区分。"""
        try:
            return int(i) > 0
        except (TypeError, ValueError):
            return False

    def _by_id(self, i) -> dict | None:
        return self.store.row_by_id(int(i))

    def _toggle_row(self, i: int, on: bool):
        if on:
            self._selected.add(i)
        else:
            self._selected.discard(i)
        self._update_sel_state()

    def _toggle_all(self, on: bool):
        for e in self._page_rows:
            if not self._is_custom(e["id"]):
                continue
            if on:
                self._selected.add(e["id"])
            else:
                self._selected.discard(e["id"])
        self._render_entries()
        self._update_sel_state()

    def reload_store(self):
        """设置里改了自定义词库存储位置后：按新位置重建数据入口并整页重渲染。"""
        self.store = VocabStore(custom_path=app_settings.vocab_custom_file())
        self._selected.clear()
        self._merge_sel = None
        self._page = 0
        self._render_all()

    def set_tier(self, t: str):
        self.tier = t
        if t == "custom":
            self.dict_ = "custom"
        elif t == "builtin":
            self.dict_ = "all"
        self._page = 0
        self._set_dict_active(self.dict_)
        self._set_tier_active(t)
        self._render_entries()
        self._update_sel_state()

    def select_dict(self, d: str):
        self.dict_ = d
        if d in ("custom", "all"):
            self.tier = "custom" if d == "custom" else "all"
            self._set_tier_active(self.tier)
        else:
            self.tier = "all"
            self._set_tier_active("all")
        self._page = 0
        self._set_dict_active(d)
        self._render_entries()
        self._update_sel_state()

    def _on_search(self, text: str):
        self.search = text
        self._page = 0
        self._render_entries()
        self._update_sel_state()

    # ------------------------------------------------------------------ 撤销

    def _undo(self):
        self._hide_status()
        rec = self.store.undo()
        if not rec:
            self._toast("没有可撤销的操作")
            return
        self._selected = {i for i in self._selected if self._by_id(i)}
        self._render_all()
        if rec.get("builtin_restored") is False:
            self._toast("已撤销上一步，内置词库未能一并还原")
        else:
            self._toast(f"已撤销「{rec['label']}」，词库回到操作前")

    def restore_point(self, point_id: int):
        """「恢复到此」：把该时间点的内容原样写回（原型 ``restoreSnap`` 的落点）。"""
        self._hide_status()
        rec = self.store.restore_point(point_id)
        if not rec:
            self._toast("这个时间点已无法恢复")
            return
        self._selected = {i for i in self._selected if self._by_id(i)}
        self._page = 0
        self._render_all()
        if rec.get("identical"):
            self._toast("已恢复到所选时间点", with_undo=True)
        else:
            self._toast("已恢复，但没能在恢复后与记录核对一致，建议再核对一次")

    def restore_snap(self, idx: int):
        """按「历史与快照」里第 ``idx`` 条记录退回它之前的状态。"""
        self._hide_status()
        rec = self.store.undo_to(idx)
        if not rec:
            self._toast("这份记录已无法恢复")
            return
        self._selected = {i for i in self._selected if self._by_id(i)}
        self._page = 0
        self._render_all()
        self._toast(f"已退回「{rec['label']}」之前")

    # ------------------------------------------------------------------ 新增词条

    def open_add(self):
        if self.dict_ != "custom":
            self.select_dict("custom")
        modal = Modal(icon="＋", title="新增词条", parent=self)
        modal.add_note(
            "写入「我的词库」（自定义分级）；加入前自动查重；操作可撤销（同五条安全底线）。", "info")
        word = QLineEdit()
        word.setPlaceholderText("例如：萧衍")
        val = QLineEdit()
        val.setPlaceholderText("例如：萧彦")
        typ = QComboBox()
        typ.addItems(ENTRY_TYPES)
        py = QLineEdit()
        py.setPlaceholderText("例如：xiāo yàn")
        modal.add_widget(self._field("原词（词 / 角色名）", word))
        modal.add_widget(self._field("替换为", val))
        modal.add_widget(self._field("类型", typ))
        modal.add_widget(self._field("注音（可选）", py))
        modal.add_foot("取消", "ghost", modal.reject)
        modal.add_foot("预览并查重", "primary",
                       lambda: self.preview_add(modal, word.text(), val.text(),
                                                typ.currentText(), py.text()))
        modal.show()

    def preview_add(self, parent_modal, word: str, value: str, typ: str, pinyin: str):
        word = (word or "").strip()
        value = (value or "").strip()
        pinyin = (pinyin or "").strip()
        if not word:
            self._toast("请填写原词")
            return
        if not value:
            self._toast("请填写替换为")
            return
        if word == value:
            self._toast("原词与替换值相同，无需新增")
            return
        self._pending_add = dict(word=word, value=value, typ=typ, pinyin=pinyin)
        conflicts = self.store.conflicts_for_add(word, value)

        m = Modal(icon="✍", title="写入词库（二次确认）", parent=self)
        m.add_note("底线④：批量 / 写动作先预览再执行；新增可撤销。", "warn")
        rows = [(cf["kind"], cf["word"], cf["value"], cf["where"]) for cf in conflicts]
        m.add_widget(_mini_table(["冲突", "原词", "替换为", "所在"], rows, mono_cols={1, 2}))
        if rows:
            kinds = sorted({cf["kind"] for cf in conflicts})
            m.add_note("加入前查重：发现冲突（" + "、".join(kinds) +
                       "），请确认是否仍要写入「我的词库」。", "warn")
        else:
            m.add_note("查重通过：未发现同词 / 同值冲突。", "info")
        m.add_widget(_label("本次将写入 1 条到自定义词库；与内置词库分开管理（底线⑤）。",
                            size="xs", color="neutral.500"))
        m.add_foot("返回修改", "ghost", parent_modal.show)
        m.add_foot("确认写入", "primary", lambda: self.confirm_add(m))
        m.show()

    def confirm_add(self, modal: Modal):
        f = self._pending_add
        if not f:
            self._toast("没有待写入的词条")
            return
        try:
            self.store.add_entry(word=f["word"], value=f["value"],
                                 typ=f["typ"], pinyin=f.get("pinyin", ""))
        except VocabDataError as exc:
            self._toast(f"没有写入：{exc}")
            return
        self._pending_add = None
        self.dict_ = "custom"
        self.tier = "custom"
        self._page = 0
        self._set_dict_active("custom")
        self._set_tier_active("custom")
        modal.accept()
        self._render_all()
        self._toast(f"已新增「{f['word']}」到我的词库", with_undo=True)

    # ------------------------------------------------------------------ 编辑

    def open_edit(self, i: int):
        e = self._by_id(i)
        if not e or not self._is_custom(i):
            return
        modal = Modal(icon="✎", title="编辑词条", parent=self)
        word = QLineEdit(e["word"])
        val = QLineEdit(e["value"])
        typ = QComboBox()
        typ.addItems(ENTRY_TYPES)
        typ.setCurrentText(e.get("type") or ENTRY_TYPES[0])
        py = QLineEdit(e.get("pinyin", ""))
        modal.add_widget(self._field("原词", word))
        modal.add_widget(self._field("替换为", val))
        modal.add_widget(self._field("类型", typ))
        modal.add_widget(self._field("注音（可选）", py))
        modal.add_note("修改后自动留一份变更记录，可撤销（底线①②）。", "info")
        modal.add_foot("取消", "ghost", modal.reject)
        modal.add_foot("保存", "primary",
                       lambda: self.save_edit(i, word.text(), val.text(),
                                              typ.currentText(), py.text(), modal))
        modal.show()

    def save_edit(self, i: int, word: str, value: str, typ: str, pinyin: str, modal: Modal):
        try:
            self.store.update_entry(int(i), word=word, value=value, typ=typ, pinyin=pinyin)
        except VocabDataError as exc:
            self._toast(f"没有保存：{exc}")
            return
        modal.accept()
        self._render_all()
        self._toast("已保存修改", with_undo=True)

    # ------------------------------------------------------------------ 查重

    def open_dup(self) -> list:
        """查重清单（M3-T3.7 收口：只读清单，不再给"假按钮"）。

        这里的定位是**看清单**：把「我的词库」里的重复分组、以及与内置词库
        撞车的条目**全量**列出来，一条不截断；处理动作由工具条上的「合并」
        「删除选中」执行（各自先预览、二次确认、可撤销）。因此弹窗不再出现
        「确认后处理」这类会让人以为点了就动手的措辞，底部只留一个「关闭」。

        大于 20 组时不再截断，而是把这部分装进可滚动的清单里——用户能看到
        全部条目，不需要再去找"查看全部"的入口。
        """
        groups = self.store.dup_groups()
        if not groups:
            self._dup_view = dict(total=0, shown=0, readonly=True)
            self._toast("未发现重复词条")
            return groups

        m = Modal(icon="🔁", title="查重清单（只读，不会改动词库）", parent=self)
        m.add_note(
            f"一共 {len(groups)} 组重复或冲突，下面**全部列出**。本窗口只看不改："
            "要处理请关掉它，用工具条上的「合并」或「删除选中」——那两处会先给"
            "预览清单、二次确认后才写，做完还能撤销。", "info")

        holder = plain_box(QWidget())
        hv = QVBoxLayout(holder)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(8)
        for gi, g in enumerate(groups, start=1):
            box = QFrame()
            box.setObjectName("DupGroup")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(8)
            bl.addWidget(_label(f"{gi}. {g['kind']}：{g['key']}", size="sm",
                                color="warning", weight="bold"))
            bl.addWidget(_mini_table(
                ["原词", "替换为", "来源"],
                [(row["word"], row["value"], TIER_NAMES[row["dict"]]) for row in g["items"]],
                mono_cols={0, 1}))
            hv.addWidget(box)
        hv.addStretch(1)

        # 组数多时给滚动条（全量都在里面，不是截断）
        if len(groups) > 3:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setMaximumHeight(430)
            area.setWidget(holder)
            m.add_widget(area)
        else:
            m.add_widget(holder)

        m.add_foot("关闭", "ghost", m.reject)
        #: 弹窗本体（自检与验收要读它的控件；也避免被提前回收）
        self._dup_modal = m
        self._dup_view = dict(total=len(groups), shown=len(groups), readonly=True)
        m.show()
        return groups

    def _compute_dups(self) -> list:
        return self.store.dup_groups()

    # ------------------------------------------------------------------ 合并

    def open_merge(self):
        sel = [i for i in self._selected if self._is_custom(i) and self._by_id(i)]
        if len(sel) < 2:
            self._toast("请至少选择 2 条自定义词条进行合并")
            return
        self._merge_sel = sel
        items = [self._by_id(i) for i in sel]
        m = Modal(icon="➕", title="合并词条（先预览清单）", parent=self)
        m.add_note("底线④：合并前给预览清单（改哪些、删哪些、留哪个）；合并可撤销。", "warn")
        target = QComboBox()
        target.addItems([f"{e['word']} → {e['value']}" for e in items])
        m.add_widget(self._field("合并为「原词」（保留其一作为主词，其余并入其替换值）", target))
        m.add_widget(_mini_table(["处理", "原词", "替换为"],
                                 [("并入", e["word"], e["value"]) for e in items],
                                 mono_cols={1, 2}))
        m.add_widget(_label("合并后需「写入词库」二次确认（展示将写入条数）。",
                            size="xs", color="neutral.500"))
        m.add_foot("取消", "ghost", m.reject)
        m.add_foot("预览写入", "primary",
                   lambda: self.do_merge(m, target.currentText().split(" → ")[0]))
        m.show()

    def do_merge(self, parent_modal, target_word: str) -> dict | None:
        sel = [i for i in (self._merge_sel or []) if self._by_id(i)]
        if len(sel) < 2:
            return None
        items = [self._by_id(i) for i in sel]
        removed = len([e for e in items if e["word"] != target_word])
        # 先给二次确认清单，确认后才真的写文件（底线④）
        m = Modal(icon="✍", title="写入词库（二次确认）", parent=self)
        m.add_note(
            f"将把合并结果写入「我的词库」，主词保留「{target_word}」，移除 {removed} 条重复词条。", "info")
        m.add_widget(_label(f"本次将保留 1 条主词、移除 {removed} 条（合并动作可撤销）。",
                            size="sm", color="neutral.700"))
        m.add_foot("取消", "ghost", m.reject)
        m.add_foot("确认写入", "primary",
                   lambda: self._do_merge_commit(m, sel, target_word))
        m.show()
        parent_modal.accept()
        return dict(pending=True, removed=removed, target=target_word)

    def _do_merge_commit(self, modal: Modal, ids: list, target_word: str) -> dict | None:
        try:
            res = self.store.merge_entries(ids, target_word)
        except VocabDataError as exc:
            modal.reject()
            self._toast(f"没有写入：{exc}")
            return None
        self._merge_sel = None
        self._selected = {i for i in self._selected if self._by_id(i)}
        modal.accept()
        self._render_all()
        self._toast(f"已合并为「{target_word}」，移除 {res['removed']} 条", with_undo=True)
        return res

    # ------------------------------------------------------------------ 展开核对

    def open_expand(self):
        rows = self._page_rows
        m = Modal(icon="📋", title="展开核对（只读）", parent=self, min_width=620)
        m.add_note("结果以结构化表格呈现，不展示内部文件内容 / 行号（底线③）。", "info")
        m.add_widget(_mini_table(
            ["#", "原词", "替换为", "来源"],
            [(self._page * PAGE_SIZE + i + 1, e["word"], e["value"], TIER_NAMES[e["dict"]])
             for i, e in enumerate(rows)], mono_cols={1, 2}))
        m.add_widget(_label(
            f"当前页共 {len(rows)} 条；整体命中 {_fmt_num(self._hit_total)} 条，翻页可看全部。",
            size="xs", color="neutral.500"))
        m.add_foot("关闭", "primary", m.accept)
        m.show()

    # ------------------------------------------------------------------ 删除（底线①④）

    def _on_delete_selected(self):
        targets = [i for i in self._selected if self._is_custom(i) and self._by_id(i)]
        if not targets:
            self._toast("没有可删除的自定义词条")
            return
        self._confirm_delete(targets)

    def _confirm_delete(self, ids: list):
        targets = [self._by_id(i) for i in ids if self._is_custom(i) and self._by_id(i)]
        if not targets:
            self._toast("没有可删除的自定义词条")
            return
        book_map = {}
        for e in targets:
            for b in e.get("books") or []:
                book_map[b] = book_map.get(b, 0) + 1
        book_lines = "；".join(f"{b}：涉及 {n} 条" for b, n in book_map.items()) or \
            "无（这些词条尚未在任何校正中命中）"
        m = Modal(icon="🗑", title="删除确认（批量先预览）", parent=self)
        m.add_note("底线④：批量删除必须先给预览清单，确认后执行；底线①：误删可撤销。", "warn")
        m.add_widget(_label(
            f"即将删除 {len(targets)} 条自定义词条，删除后可通过「撤销」恢复。",
            size="sm", color="neutral.800"))
        m.add_widget(_label("影响范围（命中过哪些书）：", size="sm",
                            weight="semibold", color="neutral.700"))
        m.add_note(book_lines, "info")
        m.add_widget(_mini_table(["原词", "替换为"],
                                 [(e["word"], e["value"]) for e in targets],
                                 mono_cols={0, 1}))
        m.add_foot("取消", "ghost", m.reject)
        m.add_foot(f"确认删除 {len(targets)} 条", "danger",
                   lambda: self.do_delete(ids, m))
        m.show()

    def do_delete(self, ids: list, modal: Modal | None = None) -> dict | None:
        try:
            res = self.store.delete_entries(ids)
        except VocabDataError as exc:
            self._toast(f"没有删除：{exc}")
            return None
        self._selected = {i for i in self._selected if self._by_id(i)}
        if modal is not None:
            modal.accept()
        self._render_all()
        self._toast(f"已删除 {res['removed']} 条自定义词条", with_undo=True)
        return res

    # ------------------------------------------------------------------ 本书专有词（2.4.2）

    def open_book_words(self):
        """本书专有词条 · 加入预览（§2.4.2 第 2 条）。

        清单列**词条 / 类型 / 替换值 / 出现次数**，逐条可勾选并可整组全选；
        **条数等于引擎实际抽出的条数**（引擎侧不截断，见 bookmap 阶段的
        条数守恒门禁），不做「只显示前 N 条」的静默丢条。
        """
        if not self._book_words:
            # 空状态走人话说明，不显示一张空表格
            self._toast("这本书校正后没有提取到可加入的专有词条，无需操作")
            return
        total = len(self._book_words)
        m = Modal(icon="✨", title="本书专有词条（加入预览）", parent=self,
                  min_width=780)
        m.add_note(
            f"共 {_fmt_num(total)} 条，全部列在下方，可在下面逐条勾选或整组选择；"
            "加入后下次校正自动生效，加入动作可以撤销。", "info")

        # ---- 整组选择行 ----
        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(10)
        all_cb = QCheckBox("整组全选")
        all_cb.setChecked(True)
        all_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        tl.addWidget(all_cb)
        self._book_all_cb = all_cb
        self._book_pick_label = _label("", size="xs", color="neutral.500")
        tl.addWidget(self._book_pick_label, 1)
        m.add_widget(top)

        # ---- 清单（可滚动，但内容是全量） ----
        checks: list[QCheckBox] = []
        rows = QVBoxLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        head = plain_box(QWidget())
        hl = QHBoxLayout(head)
        hl.setContentsMargins(2, 0, 2, 4)
        hl.setSpacing(10)
        for txt, stretch in (("加入", 0), ("词条", 3), ("类型", 1),
                             ("替换值", 3), ("出现次数", 1)):
            lab = _label(txt, size="xs", color="neutral.600",
                         weight="semibold", align="center")
            if stretch == 0:
                # 与数据行勾选列同宽：表头文字宽度与 QCheckBox 宽度本就不同，
                # 不钉死会带着后面所有列整体偏移 2px。
                lab.setFixedWidth(COL_CHECK_W)
            hl.addWidget(lab, stretch)
        rows.addWidget(head)
        rows.addWidget(hline())
        for i, w in enumerate(self._book_words):
            rw = plain_box(QWidget())
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(2, 5, 2, 5)
            rl.setSpacing(10)
            cb = QCheckBox()
            cb.setChecked(True)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            cb.toggled.connect(self._book_sync_pick_label)
            checks.append(cb)
            cb_cell = plain_box(QWidget())
            cb_l = QHBoxLayout(cb_cell)
            cb_l.setContentsMargins(0, 0, 0, 0)
            cb_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_l.addWidget(cb)
            cb_cell.setFixedWidth(COL_CHECK_W)
            rl.addWidget(cb_cell, 0)
            rl.addWidget(_label(w.get("word") or "", size="xs",
                                color="neutral.900", weight="bold", mono=True,
                                align="center"), 3)
            rl.addWidget(_label(w.get("type") or "专有名词", size="xs",
                                color="neutral.600", align="center"), 1)
            rl.addWidget(_label(w.get("value") or w.get("word") or "", size="xs",
                                color="neutral.700", mono=True,
                                align="center"), 3)
            rl.addWidget(_label(f"{int(w.get('count') or 1)} 次", size="xs",
                                color="neutral.500", mono=True,
                                align="center"), 1)
            rows.addWidget(rw)
            if i != len(self._book_words) - 1:
                rows.addWidget(hline())
        rows_box = plain_box(QWidget())
        rows_box.setLayout(rows)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setMinimumHeight(320)
        area.setMaximumHeight(420)
        area.setWidget(rows_box)
        area.setStyleSheet(
            f"QScrollArea{{border:1px solid {c('neutral.200')};"
            f"border-radius:{r('lg')};background:{c('neutral.0')}}}")
        m.add_widget(area)

        self._book_checks = checks
        all_cb.toggled.connect(
            lambda on: [cb.setChecked(bool(on)) for cb in checks])
        self._book_sync_pick_label()
        m.add_foot("取消", "ghost", m.reject)
        m.add_foot("加入选中词条到「我的词库」", "primary",
                   lambda: self.add_book_words(m))
        m.show()

    def _book_sync_pick_label(self):
        """实时反映「已勾选 X / 共 Y 条」，让用户确认加入范围。"""
        lbl = getattr(self, "_book_pick_label", None)
        if lbl is None:
            return
        picks = [cb for cb in (self._book_checks or []) if cb.isChecked()]
        total = len(self._book_words)
        self._book_all_cb_guard(picks, total)
        lbl.setText(f"已勾选 {_fmt_num(len(picks))} / 共 {_fmt_num(total)} 条")

    def _book_all_cb_guard(self, picks: list, total: int):
        cb = getattr(self, "_book_all_cb", None)
        if cb is None:
            return
        prev = cb.blockSignals(True)
        cb.setChecked(bool(total) and len(picks) == total)
        cb.blockSignals(prev)

    def add_book_words(self, modal: Modal | None = None) -> int:
        """整批一起写：一次还原点覆盖整批，撤销时整批一起回去。

        查重结果**必须显式展示**：写进去几条、跳过几条、哪几条冲突、
        冲突是同词同值 / 同词异值 / 同值异词——不静默跳过、不静默覆盖。
        """
        picked = []
        for i, cb in enumerate(self._book_checks or []):
            if cb.isChecked() and i < len(self._book_words):
                picked.append(self._book_words[i])
        if not picked:
            self._toast("还没有勾选任何词条，请先在清单里勾选要加入的词条")
            return 0
        try:
            res = self.store.add_book_words(picked, self._book_title)
        except VocabDataError as exc:
            self._toast(f"没有加入：{exc}")
            return 0
        added = int(res.get("added") or 0)
        skipped = list(res.get("skipped_exists") or [])
        conflicts = list(res.get("conflicts") or [])
        if modal is not None:
            modal.accept()
        self.hide_banner()
        self._render_all()
        self._book_report(res, added, skipped, conflicts)
        return added

    def _book_report(self, res: dict, added: int,
                     skipped: list, conflicts: list):
        """把加入结果（含全部冲突明细）摆到界面，不静默跳过。"""
        if not skipped and not conflicts:
            self._toast(f"已加入 {added} 条专有词条到「我的词库」",
                        with_undo=added > 0)
            return
        # 有跳过 / 冲突 → 用弹窗把明细一条条列出来
        m = Modal(icon="ℹ️", title="加入结果（含未加入的词条）", parent=self,
                  min_width=720)
        m.add_note(
            f"本次提交 {int(res.get('requested') or 0)} 条："
            f"已加入 {added} 条，跳过 {len(skipped)} 条，冲突 {len(conflicts)} 条。",
            "warn" if conflicts else "info")
        if skipped:
            rows = [(w.get("word", ""), w.get("value", ""),
                     str(w.get("reason") or "词库里已有同词同值的词条"))
                    for w in skipped[:50]]
            m.add_widget(_label(f"已在词库里（无需重复加入）· {len(skipped)} 条",
                                size="sm", weight="bold", color="neutral.900"))
            m.add_widget(_mini_table(["词条", "替换值", "说明"], rows,
                                     mono_cols={0, 1}))
            if len(skipped) > 50:
                m.add_widget(_label(
                    f"（另有 {len(skipped) - 50} 条同类，未逐条列出）",
                    size="xs", color="neutral.500"))
        if conflicts:
            m.add_widget(_label(
                f"与已有词条冲突，未写入（避免覆盖）· {len(conflicts)} 条",
                size="sm", weight="bold", color="error"))
            rows = []
            for c0 in conflicts[:50]:
                kinds = "、".join(sorted({str(h.get("kind") or "") for h in
                                          (c0.get("hits") or []) if h.get("kind")}))
                wheres = "、".join(sorted({str(h.get("where") or "") for h in
                                           (c0.get("hits") or []) if h.get("where")}))
                rows.append((c0.get("word", ""), c0.get("value", ""),
                             kinds or "冲突", wheres or "词库"))
            m.add_widget(_mini_table(
                ["词条", "想加入的替换值", "冲突种类", "已在哪一级"], rows,
                mono_cols={0, 1}))
            if len(conflicts) > 50:
                m.add_widget(_label(
                    f"（另有 {len(conflicts) - 50} 条同类，未逐条列出）",
                    size="xs", color="neutral.500"))
        m.add_foot("知道了", "primary", m.accept)
        m.show()
        self._toast(
            f"已加入 {added} 条；跳过 {len(skipped)} 条；冲突 {len(conflicts)} 条未写入",
            with_undo=added > 0)

    # ------------------------------------------------------------------ 恢复默认（底线⑤）

    def open_restore_default(self) -> dict | None:
        """第一步：预览（只读）——把会影响什么先摊开，不写任何东西。"""
        pv = self.store.preview_restore_default()
        self._restore_preview = pv
        m = Modal(icon="↺", title="恢复默认词库", parent=self)
        m.add_note("底线⑤：恢复默认词库只重置内置词库，不影响你的自定义词条。", "info")
        m.add_widget(_label(
            "将把内置词库重置为出厂版本，自定义词条保持不变。可撤销。",
            size="sm", color="neutral.700", wrap=True))
        rows = [
            ("内置词条", f"{_fmt_num(pv['total_entries'])} 条（"
                         f"常规 {_fmt_num(pv['tier_counts'].get('b1', 0))} / "
                         f"CJK {_fmt_num(pv['tier_counts'].get('cjk', 0))} / "
                         f"繁简 {_fmt_num(pv['tier_counts'].get('b3', 0))}）"),
            ("与出厂版本的差异", "已是出厂状态（无需改动）" if pv["already_default"]
                                 else f"{pv['changed_files']} 份内容与出厂版本不同"),
            ("我的词库", f"{_fmt_num(pv['custom_entries'])} 条，保持不动"),
            ("可以撤销", "可以，恢复后仍能撤回"),
        ]
        m.add_widget(_mini_table(["项目", "影响"], rows))
        m.add_foot("取消", "ghost", m.reject)
        m.add_foot("确认恢复", "primary",
                   lambda: self.do_restore_default(mv=m))
        m.show()
        return pv

    def do_restore_default(self, *, mv=None) -> dict:
        """第二步：执行恢复（写内置词库的工作副本，自定义词条一个字节都不动）。"""
        self._hide_status()
        before_custom = len(self.store.custom)
        try:
            res = self.store.restore_default()
        except VocabDataError as exc:
            self._toast(f"没有恢复：{exc}")
            return dict(ok=False, reason=str(exc))
        if mv is not None:
            try:
                mv.accept()
            except RuntimeError:
                pass
        self._page = 0
        self._render_all()
        if not res["custom_untouched"]:
            self._toast("已恢复内置词库，但自定义词库内容有变化，请核对")
            return dict(res, ok=False)
        tail = "（与出厂版本一致）" if res["identical_to_factory"] else ""
        self._toast(f"已恢复默认词库{tail}，自定义 {_fmt_num(before_custom)} 条保留",
                    with_undo=True)
        return dict(res, ok=True)

    def restore_default(self):
        """入口：先预览、再二次确认、最后执行（底线④ 批量先预览）。"""
        self.open_restore_default()

    # ------------------------------------------------------------------ 公共

    def _field(self, label_text: str, control: QWidget) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        lab = QLabel(label_text)
        lab.setStyleSheet(f"font-weight:600;font-size:{fs('sm')};color:{c('neutral.800')}")
        v.addWidget(lab)
        v.addWidget(control)
        return w

    def _build_status(self) -> None:
        """对齐词库原型 ``.toast-wrap`` / ``.toast``：视口底居中浮层，不进文档流。"""
        self.status_box = QWidget(self)
        self.status_box.setObjectName("Toast")
        self.status_box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 原型 --sh-lg；QSS box-shadow 会被裁剪，改用投影效果
        eff = QGraphicsDropShadowEffect(self.status_box)
        eff.setOffset(0, 8)
        eff.setBlurRadius(24)
        eff.setColor(QColor(21, 25, 31, 48))
        self.status_box.setGraphicsEffect(eff)

        sl = QHBoxLayout(self.status_box)
        sl.setContentsMargins(16, 12, 16, 12)
        sl.setSpacing(14)
        self.status = QLabel("")
        self.status.setStyleSheet(
            f"color:{c('on.fill')};font-size:{fs('sm')};background:transparent;")
        self.status.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.undo_btn = QPushButton("撤销")
        self.undo_btn.setObjectName("ToastUndo")
        self.undo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.undo_btn.clicked.connect(self._undo)
        sl.addWidget(self.status)
        sl.addWidget(self.undo_btn)
        self.status_box.hide()
        self._toast_host: QWidget | None = None

    def _toast_anchor(self) -> QWidget:
        """挂到内容区滚动视口（对齐原型 position:fixed 相对整页）。"""
        w: QWidget | None = self.parentWidget()
        while w is not None:
            if isinstance(w, QScrollArea):
                return w.viewport()
            w = w.parentWidget()
        return self.window() or self

    def _ensure_toast_host(self) -> None:
        host = self._toast_anchor()
        if self._toast_host is host:
            return
        if self._toast_host is not None:
            self._toast_host.removeEventFilter(self)
        self.status_box.setParent(host)
        self._toast_host = host
        host.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if obj is self._toast_host and self.status_box.isVisible():
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                self._place_toast()
        return super().eventFilter(obj, event)

    def _place_toast(self) -> None:
        """视口水平居中、距底 24px（原型 ``.toast-wrap``）。"""
        host = self.status_box.parentWidget()
        if host is None:
            return
        self.status_box.adjustSize()
        tw = self.status_box.sizeHint().width()
        th = self.status_box.sizeHint().height()
        self.status_box.resize(tw, th)
        x = max(8, (host.width() - tw) // 2)
        y = max(8, host.height() - th - 24)
        self.status_box.move(x, y)
        self.status_box.raise_()

    def _on_cell_copied(self, _text: str = "") -> None:
        self._toast("已复制")

    def _toast(self, msg: str, with_undo: bool = False):
        self._ensure_toast_host()
        self.status.setText(msg)
        self.undo_btn.setVisible(with_undo)
        self.status_box.show()
        self._place_toast()
        # 原型：普通 3000ms / 带撤销 6000ms
        self._toast_timer.start(6000 if with_undo else 3000)

    def _hide_status(self):
        self.status_box.hide()
