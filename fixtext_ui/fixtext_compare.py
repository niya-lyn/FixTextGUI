"""
FixText V1.1-E2 · 左右对比视图（只读）
========================================

排期 V1.1 §10.3 的两件交付物都在这个文件里：

1. **左右对比界面**——左边「改前」、右边「改后」逐条并列，改动的字用底色标出来；
2. **从差异项跳转到书籍位置**——任一条差异项都能算出它在书里的精确位置
   （第几章、该章第几行、行内第几个字），并把那一段原文原样摆出来给人核对。

三条纪律（E2 卡片自带的边界，不许越过）：

- **差异数据只用 E1 的结构**：``fixtext_diff_view`` 的 ``DiffItem`` /
  ``SideRef`` / ``DiffReport``。本模块不另造一套差异，也不再算一遍差异。
- **只读**：本模块没有任何写回原文的入口，正文只读不写；界面上的正文预览
  用的是只读控件，用户在这里改一个字都改不动。
- **不碰装载层**：``vocab_bridge.compose()`` / ``bags.write_round_rules()``
  一个字都没动，派生规则文件只读。

大书不卡死靠三件事（实测数字见交付说明）：

- 差异项清单放在 model 里，表格**只画看得见的行**——开一万条差异项也不建控件；
- 差异项本身在**后台线程**算，界面线程只收结果，���头一直可点；
- 行内文字**按需现算**（带上限的缓存），打开时不预渲染任何一格。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QSplitter, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QTableView, QVBoxLayout, QWidget,
)

from fixtext_diff_view import (
    ATTR_NO_RULES, ATTR_UNVERIFIED, ATTR_VERIFIED, ATTR_VERIFIED_SET,
    KIND_DELETE, KIND_INSERT, KIND_MULTI_LINE, KIND_REPLACE,
    DiffItem, DiffReport, build_diff_for_run,
)
from fixtext_tokens import FONT_WEIGHT, c, fs, px, r, sp
from fixtext_widgets import (
    Card, EmptyState, Pill, PrimaryButton, enable_chrome, hline, page_head_shell,
)

#: 差异项类型 → 人话
KIND_LABEL = {
    KIND_REPLACE: "替换",
    KIND_INSERT: "新增",
    KIND_DELETE: "删除",
    KIND_MULTI_LINE: "跨行",
}

#: 规则归属 → 人话
ATTR_LABEL = {
    ATTR_VERIFIED: "已核对",
    ATTR_VERIFIED_SET: "组合规则",
    ATTR_UNVERIFIED: "没核对上",
    ATTR_NO_RULES: "无规则记录",
}

#: 行内文字缓存上限（条）。超了按「先入先出」淘汰，避免大书把内存吃满。
TEXT_CACHE_LIMIT = 4000


# ---------------------------------------------------------------------------
# 位置
# ---------------------------------------------------------------------------

@dataclass
class BookPosition:
    """一条差异项在书里的位置（**只读描述**，不带任何写回能力）。

    :param chapter_index: 第几章（0 基，与 ``DiffItem.before.chapter_index`` 同口径）
    :param chapter_title: 章节标题
    :param before_line:   改前那一侧的行号（1 基）
    :param before_char_start / before_char_end: 改前行内字符区间（0 基闭开）
    :param after_line:    改后那一侧的行号（1 基）
    """

    chapter_index: int = -1
    chapter_title: str = ""
    before_line: int = 0
    before_char_start: int = -1
    before_char_end: int = -1
    after_line: int = 0

    @property
    def located(self) -> bool:
        """定位得到章 + 行。"""
        return self.chapter_index >= 0 and self.before_line > 0

    @property
    def exact(self) -> bool:
        """定位得到行内字符区间。"""
        return self.located and self.before_char_start >= 0

    def describe(self) -> str:
        """一句人话位置：第几章 · 第几行 · 第几个字。"""
        if not self.located:
            return "位置未知"
        bits = []
        if self.chapter_index >= 0:
            head = f"第 {self.chapter_index + 1} 章"
            if self.chapter_title:
                head += f"《{self.chapter_title}》"
            bits.append(head)
        bits.append(f"第 {self.before_line} 行")
        if self.before_char_start >= 0 and self.before_char_end > self.before_char_start:
            bits.append(f"第 {self.before_char_start + 1}–{self.before_char_end} 字")
        if self.after_line and self.after_line != self.before_line:
            bits.append(f"改后在第 {self.after_line} 行")
        return " · ".join(bits)


def locate_item(item: DiffItem) -> BookPosition:
    """差异项 → 书里位置。

    直接读 E1 给的 ``SideRef``，不重新推算——E1 已经把章 / 行 / 行内区间算准了，
    这里只负责把它翻译成人话。
    """
    ref = item.before
    return BookPosition(
        chapter_index=ref.chapter_index,
        chapter_title=ref.chapter_title,
        before_line=ref.line,
        before_char_start=ref.char_start,
        before_char_end=ref.char_end,
        after_line=item.after_ref.line,
    )


# ---------------------------------------------------------------------------
# 模型：只画看得见的行
# ---------------------------------------------------------------------------

class _DiffModelBase(QAbstractTableModel):
    """差异项清单的公共部分：数据放在 model 里，界面按需取。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[DiffItem] = []

    def set_items(self, items: list[DiffItem]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def item_at(self, row: int) -> DiffItem | None:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def items(self) -> list[DiffItem]:
        return list(self._items)


class CompareModel(_DiffModelBase):
    """左右两列：改前 / 改后。

    单元格文字**按需现算**并放进有上限的缓存：打开时一格都不渲染，
    滚动到哪里算到哪里，所以差异项多少都不影响打开速度。
    """

    ITEM_ROLE = Qt.ItemDataRole.UserRole + 1
    SPANS_ROLE = Qt.ItemDataRole.UserRole + 2

    COL_BEFORE = 0
    COL_AFTER = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache: dict[int, tuple[str, list]] = {}

    def set_items(self, items: list[DiffItem]) -> None:
        self._cache.clear()
        super().set_items(items)

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 2

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return "改前" if section == self.COL_BEFORE else "改后"

    def _cell(self, row: int, column: int) -> tuple[str, list]:
        hit = self._cache.get(row)
        if hit is None:
            item = self._items[row]
            text = item.before_text if column == self.COL_BEFORE else item.after_text
            spans = list(item.char_spans) if column == self.COL_BEFORE else \
                _after_spans(item)
            hit = (text, spans)
            if len(self._cache) >= TEXT_CACHE_LIMIT:
                # 先入先出淘汰一批，别让大书把内存吃满
                for k in list(self._cache.keys())[:TEXT_CACHE_LIMIT // 4]:
                    self._cache.pop(k, None)
            self._cache[row] = hit
        return hit

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        item = self.item_at(row)
        if item is None:
            return None
        if role == self.ITEM_ROLE:
            return item
        if role == self.SPANS_ROLE:
            return self._cell(row, col)[1]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._cell(row, col)[0]
        if role == Qt.ItemDataRole.ToolTipRole:
            return _tooltip_of(item)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        return None


class IndexModel(_DiffModelBase):
    """差异项索引：位置 / 类型 / 摘要。点一条即跳到对应的那条差异。"""

    COL_POS = 0
    COL_KIND = 1
    COL_SUM = 2

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 3

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return ("位置", "类型", "改动摘要")[section]

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.item_at(index.row())
        if item is None:
            return None
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == self.COL_POS:
                pos = locate_item(item)
                if pos.chapter_index >= 0:
                    return f"{pos.chapter_index + 1}章·{pos.before_line}行"
                return f"{pos.before_line}行" if pos.before_line else "—"
            if col == self.COL_KIND:
                return KIND_LABEL.get(item.kind, item.kind)
            return _summary_of(item)
        if role == Qt.ItemDataRole.ToolTipRole:
            return _tooltip_of(item)
        return None


# ---------------------------------------------------------------------------
# 高亮：把改动的字标出来
# ---------------------------------------------------------------------------

def _after_spans(item: DiffItem) -> list[tuple[int, int]]:
    """改后一侧要高亮的那几段。

    **不另算一遍差异**：只用 E1 已经给出的规则归属——改后那几个词就是规则的
    新写法，把它们在新文里的位置圈出来即可。归属没核对上时不标——
    宁可空着，也不画一个可能错的圈。
    """
    if not item.after_text:
        return []
    words: list[str] = []
    if item.rule_after:
        words.append(item.rule_after)
    for pair in item.rule_set or ():
        if len(pair) >= 2 and pair[1]:
            words.append(pair[1])
    spans: list[tuple[int, int]] = []
    for word in words:
        if not word:
            continue
        start = 0
        while True:
            at = item.after_text.find(word, start)
            if at < 0:
                break
            spans.append((at, at + len(word)))
            start = at + len(word)
    spans.sort()
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


class SpanDelegate(QStyledItemDelegate):
    """把改动的那几个字画成高亮底色，其余照常。"""

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget is not None else None
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        text = index.data(Qt.ItemDataRole.DisplayRole)
        if not isinstance(text, str) or not text:
            return
        spans = index.data(CompareModel.SPANS_ROLE) or []
        rect = option.rect.adjusted(8, 2, -8, -2)
        painter.save()
        painter.setFont(option.font)
        fm = QFontMetrics(option.font)
        painter.setPen(QColor(c("neutral.800")))
        base = rect.top() + max(0, (rect.height() - fm.height()) // 2) + fm.ascent()
        if not spans:
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                             text)
            painter.restore()
            return
        highlight = QColor(c("warning.bg"))
        x = rect.left()
        pos = 0
        for s, e in spans:
            if s > pos:
                seg = text[pos:s]
                painter.drawText(x, base, seg)
                x += fm.horizontalAdvance(seg)
            seg = text[s:e]
            width = fm.horizontalAdvance(seg)
            painter.fillRect(x, rect.top(), width, rect.height(), highlight)
            painter.drawText(x, base, seg)
            x += width
            pos = e
        if pos < len(text):
            seg = text[pos:]
            painter.drawText(x, base, seg)
        painter.restore()


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _summary_of(item: DiffItem) -> str:
    """索引表里那一句摘要。"""
    before = (item.before_snippet or item.before_text or "").strip()
    after = (item.after_snippet or item.after_text or "").strip()
    if len(before) > 18:
        before = before[:18] + "…"
    if len(after) > 18:
        after = after[:18] + "…"
    if item.kind == KIND_INSERT:
        return f"＋ {after}"
    if item.kind == KIND_DELETE:
        return f"－ {before}"
    return f"{before} → {after}"


def _tooltip_of(item: DiffItem) -> str:
    """悬停提示：位置 + 归属 + 原文/新文。"""
    pos = locate_item(item)
    attr = ATTR_LABEL.get(item.attribution, item.attribution)
    rule = ""
    if item.rule_before:
        rule = f"\n规则：{item.rule_before} → {item.rule_after}"
    elif item.rule_set:
        rule = "\n规则：" + "、".join(f"{b}→{a}" for b, a in item.rule_set)
    return (f"{pos.describe()}\n类型：{KIND_LABEL.get(item.kind, item.kind)}"
            f"\n归属：{attr}{rule}\n改前：{item.before_text}\n改后：{item.after_text}")


class _LineCursor:
    """按行号取正文里的一行——只读，不缓存整本书。

    大书整本读进内存不现实，这里边用边扫；顺序翻页时是 O(1) 均摊。
    """

    def __init__(self) -> None:
        self._path = ""
        self._next_line = 1
        self._fh = None

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None

    def line(self, path: str, lineno: int) -> str:
        if not path or lineno <= 0:
            return ""
        if path != self._path:
            self.close()
            self._path = path
            self._next_line = 1
            self._fh = open(path, "r", encoding="utf-8", errors="surrogateescape")
        if lineno < self._next_line:          # 往回翻：重扫
            self.close()
            self._fh = open(path, "r", encoding="utf-8", errors="surrogateescape")
            self._next_line = 1
        assert self._fh is not None
        for no, raw in enumerate(self._fh, start=self._next_line):
            if no == lineno:
                self._next_line = no + 1
                return raw.rstrip("\n")
        self._next_line = no + 1
        return ""


# ---------------------------------------------------------------------------
# 后台加载
# ---------------------------------------------------------------------------

class _Loader(QObject):
    """后台线程算差异，结果用信号送回界面线程。"""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, run_dir: str, parent=None):
        super().__init__(parent)
        self._run_dir = run_dir
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        t0 = time.perf_counter()
        try:
            _ensure_pipeline()
            report = build_diff_for_run(self._run_dir)
        except Exception as exc:
            self.failed.emit(f"{exc}")
            return
        self.succeeded.emit((report, time.perf_counter() - t0))


def _ensure_pipeline() -> None:
    """把引擎包挂到 sys.path（差异计算要用到排版与词库那几段）。"""
    try:
        from fixtext_export import ensure_vendor

        ensure_vendor(None)
    except Exception:                                    # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------

class CompareModule(QWidget):
    """左右对比页（只读）。

    打开方式有两种：

    - ``open_run(run_dir)``：从一次校正的运行目录打开（后台算，界面不卡）；
    - ``set_report(report)``：直接给一份差异清单（自检与验收用）。
    """

    #: 打开过程有进展时发这个信号（已完成的差异项数 / 总数未知时给 -1）
    loadingChanged = Signal(bool)
    #: 打开完成时发（报告 + 耗时秒）
    opened = Signal(object, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._report: DiffReport | None = None
        self._items: list[DiffItem] = []
        self._cur = -1
        self._loader: _Loader | None = None
        self._cursor = _LineCursor()
        self._metrics: dict = {}
        self._kind_filter = "全部"
        self._chapter_filter = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(px(sp("4")))

        shell, head = page_head_shell()
        title = QLabel("前后对比")
        title.setStyleSheet(
            f"color:{c('neutral.900')};font-size:{fs('2xl')};"
            f"font-weight:{FONT_WEIGHT['semibold']}"
        )
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(title)
        hl.addStretch(1)
        self._head_note = QLabel("左边是改前，右边是改后；只读，不会动你的原文。")
        self._head_note.setStyleSheet(
            f"color:{c('neutral.500')};font-size:{fs('sm')};background:transparent")
        hl.addWidget(self._head_note)
        root.addWidget(shell)

        # -- 来源摘要 ------------------------------------------------------
        src = Card("对比来源", "本次比的是哪一次校正")
        self._src_line = _muted("")
        src.body_l.addWidget(self._src_line)
        self._src_pills = QHBoxLayout()
        self._src_pills.setSpacing(px(sp("2")))
        src.body_l.addLayout(self._src_pills)
        root.addWidget(src)

        # -- 定位条 --------------------------------------------------------
        loc = Card("定位", "选中任一条差异，这里报出它在书里的位置")
        self._loc_line = _muted("还没打开对比内容。")
        self._loc_line.setWordWrap(True)
        loc.body_l.addWidget(self._loc_line)

        nav = QHBoxLayout()
        nav.setSpacing(px(sp("2")))
        self._prev_btn = QPushButton("◀ 上一处")
        self._next_btn = QPushButton("下一处 ▶")
        for btn in (self._prev_btn, self._next_btn):
            btn.setObjectName("BtnOutline")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev_btn.clicked.connect(lambda: self.step(-1))
        self._next_btn.clicked.connect(lambda: self.step(1))
        nav.addWidget(self._prev_btn)
        nav.addWidget(self._next_btn)
        self._counter = _muted("第 — / — 条")
        nav.addWidget(self._counter)
        nav.addStretch(1)
        self._copy_btn = QPushButton("复制位置")
        self._copy_btn.setObjectName("BtnOutline")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.clicked.connect(self.copy_position)
        nav.addWidget(self._copy_btn)
        loc.body_l.addLayout(nav)

        filters = QHBoxLayout()
        filters.setSpacing(px(sp("2")))
        filters.addWidget(_muted("只看"))
        self._kind_box = QComboBox()
        self._kind_box.addItems(["全部"] + [KIND_LABEL[k] for k in
                                           (KIND_REPLACE, KIND_INSERT,
                                            KIND_DELETE, KIND_MULTI_LINE)])
        self._kind_box.currentTextChanged.connect(self._on_filter)
        filters.addWidget(self._kind_box)
        filters.addWidget(_muted("章节"))
        self._chapter_box = QComboBox()
        self._chapter_box.currentIndexChanged.connect(self._on_filter)
        filters.addWidget(self._chapter_box)
        filters.addStretch(1)
        loc.body_l.addLayout(filters)
        root.addWidget(loc)

        # -- 左右对比 ------------------------------------------------------
        cmp_card = Card("左右对比", "点左边任一条，右边跳到那一条")
        self._split = QSplitter(Qt.Orientation.Horizontal)
        self._split.setChildrenCollapsible(False)
        self._split.setHandleWidth(px(sp("2")))

        self._index_view = _table()
        self._index_model = IndexModel(self)
        self._index_view.setModel(self._index_model)
        self._index_view.setColumnWidth(IndexModel.COL_POS, 84)
        self._index_view.setColumnWidth(IndexModel.COL_KIND, 52)

        self._compare_view = _table()
        self._compare_model = CompareModel(self)
        self._compare_view.setModel(self._compare_model)
        self._compare_view.setItemDelegate(SpanDelegate(self._compare_view))
        self._compare_view.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._compare_view.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)

        self._split.addWidget(self._index_view)
        self._split.addWidget(self._compare_view)
        self._split.setStretchFactor(0, 0)
        self._split.setStretchFactor(1, 1)
        self._split.setSizes([300, 720])
        cmp_card.body_l.addWidget(self._split)
        root.addWidget(cmp_card)
        self._cmp_card = cmp_card

        # -- 原文预览（只读） ----------------------------------------------
        prev = Card("这一处原文", "只读，用来核对位置对不对")
        self._preview = QLabel("")
        self._preview.setWordWrap(True)
        self._preview.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self._preview.setStyleSheet(
            f"color:{c('neutral.800')};font-size:{fs('sm')};line-height:150%;"
            f"background:{c('neutral.50')};border:1px solid {c('neutral.200')};"
            f"border-radius:{r('md')};padding:{sp('3')}"
        )
        prev.body_l.addWidget(self._preview)
        root.addWidget(prev)

        # -- 空状态 --------------------------------------------------------
        self._empty = EmptyState(
            "🔍", "还没有可对比的内容",
            "先在「一键校正」里跑一次，再回到这里看前后对比。",
            primary=None, secondary=None,
        )
        root.addWidget(self._empty)
        self._empty.setVisible(False)

        self._index_view.selectionModel().currentRowChanged.connect(self._on_index_row)
        self._compare_view.selectionModel().currentRowChanged.connect(self._on_row)
        self._set_ready(False)

    # -- 只读访问口（验收与外部接线用） -----------------------------------

    @property
    def compare_model(self) -> CompareModel:
        """左右对比表格的数据模型（只读视图的载体）。"""
        return self._compare_model

    @property
    def index_model(self) -> IndexModel:
        """差异项清单的数据模型。"""
        return self._index_model

    # -- 打开 ---------------------------------------------------------------

    def open_run(self, run_dir: str) -> None:
        """打开一次校正的运行目录（后台算，界面不卡）。"""
        self._metrics = {}
        self._set_ready(False)
        self._empty.setVisible(False)
        self._src_line.setText("正在读取这一次校正的内容…")
        self._loader = _Loader(str(run_dir), self)
        self._loader.succeeded.connect(self._on_loaded)
        self._loader.failed.connect(self._on_failed)
        self.loadingChanged.emit(True)
        self._loader.start()

    def set_report(self, report: DiffReport, *, label: str = "") -> None:
        """直接给一份差异清单（自检 / 验收用）。"""
        self._apply_report(report, load_s=0.0, label=label)

    # -- 结果回调 -----------------------------------------------------------

    def _on_loaded(self, payload) -> None:
        report, load_s = payload
        self._apply_report(report, load_s=load_s)

    def _on_failed(self, message: str) -> None:
        self.loadingChanged.emit(False)
        self._src_line.setText("这次的内容读不出来，换一次校正记录再试。")
        self._loc_line.setText(f"没能打开：{message}")

    def _apply_report(self, report: DiffReport, *, load_s: float,
                      label: str = "") -> None:
        t0 = time.perf_counter()
        self._report = report
        self._items = list(report.items)
        self._cur = -1

        self._chapter_box.blockSignals(True)
        self._chapter_box.clear()
        self._chapter_box.addItem("全部", -1)
        seen: dict[int, str] = {}
        for item in self._items:
            idx = item.before.chapter_index
            if idx < 0 or idx in seen:
                continue
            seen[idx] = item.before.chapter_title or ""
        for idx in sorted(seen):
            self._chapter_box.addItem(
                f"第 {idx + 1} 章" + (f"《{seen[idx]}》" if seen[idx] else ""), idx)
        self._chapter_box.blockSignals(False)

        self._apply_filter()
        ready_s = time.perf_counter() - t0
        self._metrics = {
            "load_s": load_s,
            "ready_s": load_s + ready_s,
            "items": len(self._items),
            "chapters": len(report.chapters),
            "unverified": report.unverified_count,
        }
        self._render_summary(report, load_s)
        self._set_ready(True)
        self.loadingChanged.emit(False)
        self.opened.emit(report, float(load_s))

    def _render_summary(self, report: DiffReport, load_s: float) -> None:
        bits = [f"差异 {report.item_count} 条", f"章节 {len(report.chapters)} 章"]
        if report.hits_verified:
            bits.append(f"改动 {report.hits} 处")
        if report.unverified_count:
            bits.append(f"没核对上 {report.unverified_count} 条")
        self._src_line.setText("　".join(bits))
        while self._src_pills.count():
            w = self._src_pills.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for text, kind in (("只读", "info"),
                           (f"打开耗时 {load_s:.2f} 秒", "neutral"),
                           (f"显示 {len(self._items)} 条", "neutral")):
            pill = Pill(text, kind)
            self._src_pills.addWidget(pill)
            self._src_pills.addStretch(1)

    def _set_ready(self, ready: bool) -> None:
        self._split.setVisible(ready)
        self._empty.setVisible(not ready)
        for btn in (self._prev_btn, self._next_btn, self._copy_btn):
            btn.setEnabled(ready)

    # -- 筛选 ---------------------------------------------------------------

    def _on_filter(self, *_args) -> None:
        self._apply_filter()

    def _apply_filter(self) -> None:
        kind_text = self._kind_box.currentText() if hasattr(self, "_kind_box") else "全部"
        chapter = self._chapter_box.currentData() if hasattr(self, "_chapter_box") else -1
        if chapter is None:
            chapter = -1
        kind_map = {v: k for k, v in KIND_LABEL.items()}
        kind = kind_map.get(kind_text, "")
        out = []
        for item in self._items:
            if kind and item.kind != kind:
                continue
            if chapter is not None and chapter >= 0 and item.before.chapter_index != chapter:
                continue
            out.append(item)
        self._index_model.set_items(out)
        self._compare_model.set_items(out)
        self._cur = -1
        self._update_counter()
        self._loc_line.setText(
            f"当前显示 {len(out)} 条差异。点左边任一条，右边跳到那一条并报出位置。"
            if out else "当前筛选下没有差异。")

    # -- 选中与跳转 ---------------------------------------------------------

    def _on_index_row(self, current, _previous) -> None:
        row = current.row()
        if row < 0:
            return
        self._select(row, from_index=True)

    def _on_row(self, current, _previous) -> None:
        row = current.row()
        if row < 0:
            return
        self._select(row, from_index=False)

    def _select(self, row: int, *, from_index: bool) -> None:
        if row == self._cur:
            return
        self._cur = row
        if from_index:
            self._compare_view.selectRow(row)
        else:
            self._index_view.selectRow(row)
        item = self._compare_model.item_at(row)
        if item is None:
            return
        pos = locate_item(item)
        self._loc_line.setText(
            f"第 {row + 1} / {self._compare_model.rowCount()} 条　"
            f"{pos.describe()}　"
            f"类型：{KIND_LABEL.get(item.kind, item.kind)}　"
            f"归属：{ATTR_LABEL.get(item.attribution, item.attribution)}"
        )
        self._update_counter()
        self._render_preview(item, pos)

    def _update_counter(self) -> None:
        total = self._compare_model.rowCount()
        if self._cur < 0 or total == 0:
            self._counter.setText("第 — / — 条")
        else:
            self._counter.setText(f"第 {self._cur + 1} / {total} 条")

    def step(self, delta: int) -> None:
        """上一处 / 下一处。"""
        total = self._compare_model.rowCount()
        if total == 0:
            return
        row = self._cur
        row = (row + delta) % total if row >= 0 else (0 if delta > 0 else total - 1)
        self._index_view.selectRow(row)
        self._index_view.scrollTo(self._index_model.index(row, 0))
        self._compare_view.selectRow(row)
        self._compare_view.scrollTo(self._compare_model.index(row, 0))

    def current_item(self) -> DiffItem | None:
        """当前选中的差异项（自检 / 验收用）。"""
        if self._cur < 0:
            return None
        return self._compare_model.item_at(self._cur)

    def current_position(self) -> BookPosition | None:
        """当前选中的差异项在书里的位置。"""
        item = self.current_item()
        return locate_item(item) if item is not None else None

    def copy_position(self) -> None:
        """把当前位置抄到剪贴板。"""
        pos = self.current_position()
        if pos is None:
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(pos.describe())

    # -- 原文预览（只读） ---------------------------------------------------

    def _render_preview(self, item: DiffItem, pos: BookPosition) -> None:
        """把这一处在书里的原文原样摆出来（只读）。"""
        path = self._report.before_path if self._report else ""
        line_text = self._cursor.line(path, pos.before_line)
        if not line_text:
            self._preview.setText(
                f"{pos.describe()}\n（这一行没取到原文）")
            return
        start = pos.before_char_start
        end = pos.before_char_end
        if start >= 0 and end > start and end <= len(line_text):
            head = line_text[:start]
            mid = line_text[start:end]
            tail = line_text[end:]
            self._preview.setText(
                f"{pos.describe()}\n"
                f"……{head}【{mid}】{tail}……")
        else:
            self._preview.setText(f"{pos.describe()}\n{line_text}")

    # -- 收尾 ---------------------------------------------------------------

    def shutdown(self) -> None:
        self._cursor.close()

    def metrics(self) -> dict:
        """本次打开的耗时与规模（验收记录用）。"""
        return dict(self._metrics)


# ---------------------------------------------------------------------------
# 小组件
# ---------------------------------------------------------------------------

def _muted(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(
        f"color:{c('neutral.600')};font-size:{fs('sm')};background:transparent")
    return lab


def _table() -> QTableView:
    view = QTableView()
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setAlternatingRowColors(False)
    view.setWordWrap(False)
    view.setShowGrid(False)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(28)
    view.setStyleSheet(
        f"QTableView{{background:{c('neutral.0')};border:1px solid {c('neutral.200')};"
        f"border-radius:{r('md')};font-size:{fs('sm')};color:{c('neutral.800')}}}"
        f"QTableView::item{{padding:4px 6px;}}"
        f"QHeaderView::section{{background:{c('neutral.100')};color:{c('neutral.600')};"
        f"font-size:{fs('xs')};border:none;border-bottom:1px solid {c('neutral.200')};}}"
    )
    return view
