"""FixText V1 · 书架列表与顶栏「当前书」胶囊（M4-EX.3a 界面层）

数据全部来自 `fixtext_shelf`（工作区里真实的书 + 持久化的当前书），
本模块只负责渲染与交互，不自己算当前书、也不新增任何导入副本。

两个控件：

- `ShelfPanel`：导入页的书架列表。一行一本书（书名 / 格式 / 大小 / 导入时间 /
  当前标记），行内右侧固定宽度的操作位放「设为当前」或「当前」标记。
  状态位只保留「已导出」一处，且只由真实导出记录驱动（本卡没有写入方，
  所以正常情况下不出现，不是先摆个状态占位）。
- `BookChip`：顶栏常驻的当前书胶囊。只展示、不切换；点击跳导入页书架，
  切换动作在书架里完成（用户约束）。

对齐约定（原型 v3 §6）：状态位与操作位都是固定宽度，切换当前书时
其它行的文字不会因「按钮 ↔ 徽标」互换而左右位移。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

import fixtext_shelf as shelf_data
from fixtext_tokens import (
    BOOKCHIP_H, BOOKCHIP_MAX_W, SHELF_ACTION_W, SHELF_BADGE_H, SHELF_ROW_H,
    SHELF_STATUS_W, c, px, sp,
)
from fixtext_widgets import repolish

#: 书架状态位固定宽度（够放「已导出」，空着也占位）
STATUS_SLOT_W = SHELF_STATUS_W
#: 书架操作位固定宽度（「设为当前」按钮与「当前」徽标同宽，切换不抖）
ACTION_SLOT_W = SHELF_ACTION_W
#: 顶栏胶囊宽度上限（原型 .book-chip max-width:320px）
CHIP_MAX_W = BOOKCHIP_MAX_W
#: 胶囊高度（原型 .book-chip height:34px）
CHIP_H = BOOKCHIP_H
#: 书架行高
ROW_H = SHELF_ROW_H
#: 行内小圆点直径（原型 .bs-dot / .bc-dot 8px）
DOT_SIZE = px(sp("2"))
#: 书名文字区最大自然宽度（超过就省略，全文进 tooltip）
NAME_MAX_W = 248
#: 省略标签的最小宽度（再窄也不至于把文字挤没）
NAME_MIN_W = 36


class ShelfDot(QWidget):
    """原型 .bs-dot：8px 实心圆 + 3px 光晕（自绘，避免 QSS 999px 在 Qt 里变方）。"""

    #: 光晕环宽（原型 box-shadow 0 0 0 3px）
    HALO = 3

    def __init__(self, exported: bool = False, parent=None):
        super().__init__(parent)
        self._exported = bool(exported)
        side = DOT_SIZE + self.HALO * 2
        self.setFixedSize(side, side)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_exported(self, exported: bool) -> None:
        self._exported = bool(exported)
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        # 光晕
        halo = QColor(c("success.bg") if self._exported else c("neutral.100"))
        p.setBrush(halo)
        p.drawEllipse(self.rect())
        # 实心圆（居中 8px）
        fill = QColor(c("success") if self._exported else c("neutral.300"))
        p.setBrush(fill)
        inset = float(self.HALO)
        p.drawEllipse(QRectF(inset, inset, float(DOT_SIZE), float(DOT_SIZE)))
        p.end()


class ElidedLabel(QLabel):
    """单行省略标签：宽度不够时右侧出省略号，全文交给 tooltip。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._full = str(text or "")
        self._max_w = NAME_MAX_W
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Preferred)
        self._apply()

    def full_text(self) -> str:
        return self._full

    def set_full_text(self, text: str) -> None:
        self._full = str(text or "")
        self.updateGeometry()
        self._apply()

    def sizeHint(self) -> QSize:                     # noqa: N802 - Qt 覆写
        fm = self.fontMetrics()
        return QSize(min(fm.horizontalAdvance(self._full), self._max_w) + 2,
                     fm.height() + 2)

    def minimumSizeHint(self) -> QSize:              # noqa: N802 - Qt 覆写
        return QSize(NAME_MIN_W, self.fontMetrics().height() + 2)

    def resizeEvent(self, event):                    # noqa: N802 - Qt 覆写
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        fm = self.fontMetrics()
        self.setText(fm.elidedText(self._full, Qt.TextElideMode.ElideRight,
                                   max(0, self.width())))


class ShelfRow(QFrame):
    """书架里的一行：圆点 · 书名 · 状态位 · 操作位（对齐原型 .ws-row）。"""

    requestCurrent = Signal(str)      # 行内「设为当前」或整行点击 → 切换当前书

    def __init__(self, book: shelf_data.Book, *, current: bool,
                 separator: bool = False, parent=None):
        super().__init__(parent)
        self.book = book
        self._current = bool(current)
        self.setObjectName("ShelfRow")
        self.setProperty("current", "true" if current else "false")
        self.setProperty("separator", "true" if separator else "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(ROW_H)

        lay = QHBoxLayout(self)
        # 原型 .ws-row：padding 10px 12px；gap 8px
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        # 圆点：按「已导出」着色（自绘正圆 + 光晕）
        self.dot = ShelfDot(exported=bool(book.exported_at))
        lay.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)

        # 单行书名；格式/大小/时间进 tooltip
        self.name = ElidedLabel(f"《{book.title}》{book.suffix}")
        self.name.setObjectName("ShelfName")
        lay.addWidget(self.name, 1)

        # 状态位：固定宽占位，透明无边框（空时绝不能露出方框）
        self.status = QLabel("已导出" if book.exported_at else "")
        self.status.setObjectName("ShelfStatus")
        self.status.setFixedWidth(STATUS_SLOT_W)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)

        # 操作位：固定宽、透明无框；内部只放胶囊，勿再套可见容器
        self.action_slot = QWidget()
        self.action_slot.setObjectName("ShelfAct")
        self.action_slot.setFixedWidth(ACTION_SLOT_W)
        self.action_slot.setFixedHeight(SHELF_BADGE_H)
        self.action_slot.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sl = QHBoxLayout(self.action_slot)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        sl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if current:
            self.badge = QLabel("当前")
            self.badge.setObjectName("ShelfBadge")
            self.badge.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.badge.setFixedHeight(SHELF_BADGE_H)
            # padding 只左右：上下由固定高度居中，避免底边被裁；
            # 配色交给 fixtext.qss 的 QLabel#ShelfBadge（原内联收归）
            sl.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignCenter)
            self.action_btn = None
        else:
            self.badge = None
            self.action_btn = QPushButton("设为当前")
            self.action_btn.setObjectName("BtnSetCurrent")
            self.action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            # 去掉系统焦点方框（常被看成按钮后多一块）
            self.action_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.action_btn.setFlat(True)
            self.action_btn.setAutoDefault(False)
            self.action_btn.setDefault(False)
            self.action_btn.setFixedHeight(SHELF_BADGE_H)
            self.action_btn.setAccessibleName(f"把《{book.title}》设为当前书")
            self.action_btn.setToolTip(f"把《{book.title}》设为当前书")
            # 完整三态已落在 fixtext.qss 的 #BtnSetCurrent（原内联收归）
            self.action_btn.clicked.connect(
                lambda _=False, bid=book.book_id: self.requestCurrent.emit(bid))
            sl.addWidget(self.action_btn, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.action_slot, 0, Qt.AlignmentFlag.AlignVCenter)

        self._paint()

    def is_current(self) -> bool:
        return self._current

    def _paint(self) -> None:
        """按当前态 / 导出态着色（对齐原型 .ws-row / .bs-dot）。"""
        self.dot.set_exported(bool(self.book.exported_at))
        self.name.ensurePolished()
        self.name._apply()
        tip = (
            f"《{self.book.title}》{self.book.suffix}\n"
            f"{self.book.fmt} · {shelf_data.human_size(self.book.size_bytes)} · "
            f"{shelf_data.human_imported(self.book)}"
        )
        self.name.setToolTip(tip)
        self.setToolTip(tip)

    def mousePressEvent(self, event):                # noqa: N802 - Qt 覆写
        if event.button() == Qt.MouseButton.LeftButton:
            self.requestCurrent.emit(self.book.book_id)
        super().mousePressEvent(event)


class ShelfPanel(QWidget):
    """导入页的书架：列工作区里的书 + 行内切换当前书。"""

    currentChanged = Signal(str)      # 用户把某本书设为当前（已落设置文件）

    def __init__(self, workspace_root: str | Path, parent=None):
        super().__init__(parent)
        self.workspace = Path(workspace_root)
        self._current_id = ""
        self.rows: list[ShelfRow] = []
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self.refresh()

    # ---- 数据 ---------------------------------------------------------
    def books(self) -> list[shelf_data.Book]:
        return shelf_data.list_books(self.workspace)

    def current_id(self) -> str:
        return self._current_id

    def current_book(self) -> shelf_data.Book | None:
        for b in self.books():
            if b.book_id == self._current_id:
                return b
        return None

    @staticmethod
    def _resolve(books: list[shelf_data.Book],
                 workspace: Path | None = None) -> str:
        cur = shelf_data.resolve_current(workspace or Path(), books)
        return cur.book_id if cur is not None else ""

    # ---- 渲染 ---------------------------------------------------------
    def refresh(self, books: list[shelf_data.Book] | None = None) -> None:
        items = self.books() if books is None else list(books)
        self._current_id = self._resolve(items, self.workspace)
        for row in self.rows:
            self._lay.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self.rows = []
        for i, book in enumerate(items):
            row = ShelfRow(book, current=(book.book_id == self._current_id),
                           separator=bool(i))
            row.requestCurrent.connect(self._on_row_request)
            self._lay.addWidget(row)
            self.rows.append(row)

    def set_current_book(self, book_id: str, *, persist: bool = False) -> None:
        """把某本设为当前（可选落设置文件），重排高亮但不发信号。"""
        if persist:
            shelf_data.set_current_book_id(book_id)
        self._current_id = str(book_id or "")
        self.refresh()

    def _on_row_request(self, book_id: str) -> None:
        """行内「设为当前」：落设置文件 → 重排高亮 → 通知外层（顶栏跟着换）。"""
        if not book_id or book_id == self._current_id:
            return
        shelf_data.set_current_book_id(book_id)
        self.refresh()
        self.currentChanged.emit(book_id)


class BookChip(QFrame):
    """顶栏常驻的「当前书」胶囊：只展示，点击跳到导入页书架去切换。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BookChip")
        self.setProperty("empty", "true")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setFixedHeight(CHIP_H)
        self.setMaximumWidth(CHIP_MAX_W)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("当前要校对的书，点击前往导入书籍切换")
        self._title = ""
        # M5-EX.7：无书/有书同一套玻璃胶囊（对齐原型 .book-chip，无半透明 wash）。
        # 渐变/圆角/描边统一由 fixtext.qss 的 #BookChip 提供（原内联收归，_chip_r 已按 BOOKCHIP_H 计算）。

        lay = QHBoxLayout(self)
        lay.setContentsMargins(px(sp("3")), 0, px(sp("3")), 0)
        lay.setSpacing(px(sp("2")))

        self.dot = QFrame()
        self.dot.setObjectName("BcDot")
        self.dot.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.dot.setFixedSize(DOT_SIZE, DOT_SIZE)
        lay.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self.name = ElidedLabel("未选择书")
        self.name.setObjectName("BcName")
        lay.addWidget(self.name, 1)

        self.go_label = QLabel("切换 ›")
        self.go_label.setObjectName("BcGo")
        lay.addWidget(self.go_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._apply_state()

    # ---- 内容 ---------------------------------------------------------
    @property
    def title(self) -> str:
        return self._title

    def set_book(self, title: str | None) -> None:
        """设置当前书名；None / 空串 = 还没有书（中性占位）。"""
        self._title = str(title or "").strip()
        self._apply_state()

    def _apply_state(self) -> None:
        has_book = bool(self._title)
        self.setProperty("empty", "false" if has_book else "true")
        muted = "false" if has_book else "true"
        self.name.setProperty("muted", muted)
        self.dot.setProperty("muted", muted)
        for w in (self, self.name, self.dot, self.go_label):
            repolish(w)
        # 无书只弱化文字/圆点；胶囊底仍与有书同色
        self.name.set_full_text(self._title or "未选择书")
        if has_book:
            tip = f"{self._title}\n点击前往「导入书籍」切换当前书"
        else:
            tip = "还没有导入的书\n点击前往「导入书籍」"
        self.setToolTip(tip)
        self.name.setToolTip(tip)
    def enterEvent(self, event):                     # noqa: N802 - Qt 覆写
        # 父 :hover 改子在 Qt 上不稳，用属性选择器刷「切换」主色
        self.setProperty("hover", "true")
        repolish(self)
        repolish(self.go_label)
        super().enterEvent(event)

    def leaveEvent(self, event):                     # noqa: N802 - Qt 覆写
        self.setProperty("hover", "false")
        repolish(self)
        repolish(self.go_label)
        super().leaveEvent(event)

    # ---- 交互 ---------------------------------------------------------
    def mousePressEvent(self, event):                # noqa: N802 - Qt 覆写
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):                  # noqa: N802 - Qt 覆写
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)
