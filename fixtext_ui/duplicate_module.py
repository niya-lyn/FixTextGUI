"""V1.1-E7 · 重复段落清单页（内容区的平级路由页）
=================================================

落点（为什么不新造导航入口）
--------------------------
左轨六入口配额是固定的（导入 / 一键校正 / 检查问题 / 词库管理 / 导出结果 /
历史记录），重复段落检测在排期里是「检查问题」的补充能力，所以本页按既有
范式做成**内容区的平级路由页**（与前后对比页、逐批手动处理页、设置页同一
种接法）：入口是检查页「批量操作」卡上的一行，页面本身不进左轨。

页面上的两件事，对应两条判据
----------------------------
1. **清单可定位**：清单按组列出（组号 ``E-x`` / ``S-x`` 由检测报告给出，稳定
   可复现），选中任意一组即报出四套口径（段序号 / 章节 / 行区间 / 字符偏移），
   点「跳到正文」把只读正文预览的光标落在该段的行区间上并高亮——这是页内
   真实发生的跳转，同时向外发 :attr:`jumpRequested` 供外部接线。
2. **处置只有两态**：标记 / 忽略，外加清回未处置与撤销。页面**没有**删除按钮，
   也没有任何改书稿的路径——处置只写这本书自己的处置记录
   （``fixtext_duplicate_marks``），正文一个字节都不碰。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout,
    QHeaderView, QLabel, QPlainTextEdit, QPushButton, QSpinBox, QTableView,
    QTextEdit, QVBoxLayout, QWidget,
)

import fixtext_duplicate_list as dl
import fixtext_duplicate_marks as dm
from fixtext_tokens import FONT_WEIGHT, c, fs, r, sp
from fixtext_widgets import Card, EmptyState, Pill, hline, page_head_shell, px

#: 正文预览上下各带几行上下文
CONTEXT_LINES = 6

#: 默认检测口径（与 E6 的引擎默认值一致）
DEFAULT_THRESHOLD = 0.85
DEFAULT_MIN_CHARS = 20


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
    view.setWordWrap(False)
    view.setShowGrid(False)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(28)
    view.setStyleSheet(
        f"QTableView{{background:{c('neutral.0')};border:1px solid {c('neutral.200')};"
        f"border-radius:{r('md')};"
        f"font-size:{fs('sm')};color:{c('neutral.800')}}}"
        f"QTableView::item{{padding:4px 6px;}}"
        f"QHeaderView::section{{background:{c('neutral.100')};color:{c('neutral.600')};"
        f"font-size:{fs('xs')};border:none;border-bottom:1px solid {c('neutral.200')};}}"
    )
    return view


# ---------------------------------------------------------------------------
# 清单模型
# ---------------------------------------------------------------------------

class DuplicateListModel(QAbstractTableModel):
    """清单表：组号 / 类型 / 处数 / 首次位置 / 处置。

    只读模型——处置不走表格编辑，走页面上的按钮（一次点一组的动作要能被
    测试逐条核对，编辑单元格反而是隐患）。
    """

    COLS = ("组号", "类型", "处数", "首次出现的位置", "处置")
    COL_ID, COL_KIND, COL_COUNT, COL_POS, COL_STATE = range(5)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._list: dl.DuplicateList = dl.DuplicateList()
        #: 组号 → 处置记录（界面判「正文已改动」用）
        self._records: dict[str, dict] = {}

    # -- 装载 -------------------------------------------------------------

    def set_list(self, view: dl.DuplicateList,
                 records: dict[str, dict] | None = None) -> None:
        self.beginResetModel()
        self._list = view
        self._records = dict(records or {})
        self.endResetModel()

    def set_records(self, records: dict[str, dict] | None) -> None:
        self._records = dict(records or {})
        if self._list.items:
            self.dataChanged.emit(
                self.index(0, self.COL_STATE),
                self.index(len(self._list.items) - 1, self.COL_STATE))

    def duplicate_list(self) -> dl.DuplicateList:
        return self._list

    def item_at(self, row: int) -> dl.DuplicateItem | None:
        return self._list.item_at(row)

    def row_of(self, group_id: str) -> int:
        return self._list.row_of(group_id)

    def state_text(self, group_id: str, item: dl.DuplicateItem | None = None) -> str:
        """处置列的文案：状态 + 正文改动提示（签名对不上时如实说）。"""
        state = self._list.state_of(group_id)
        rec = self._records.get(group_id) or {}
        note = ""
        if state and rec.get("signature") and item is not None:
            want = dm.signature_of((s.index, s.text) for s in item.slots)
            if rec.get("signature") != want:
                note = "（正文已改动，这条处置不再生效）"
        return (dm.STATE_NAMES.get(state, "未处置") + note) if state else "未处置"

    # -- Qt 模型接口 -------------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._list.items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.COLS):
            return self.COLS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.item_at(index.row())
        if item is None:
            return None
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == self.COL_ID:
                return item.group_id
            if col == self.COL_KIND:
                return item.kind_name
            if col == self.COL_COUNT:
                return f"{item.occurrences} 段"
            if col == self.COL_POS:
                return item.position_text()
            if col == self.COL_STATE:
                return self.state_text(item.group_id, item)
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (self.COL_ID,
                                                                self.COL_COUNT):
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == self.COL_POS:
                return item.summary_text()
            if col == self.COL_STATE:
                return self.state_text(item.group_id, item)
            return None
        return None


# ---------------------------------------------------------------------------
# 检测（后台线程，界面不卡）
# ---------------------------------------------------------------------------

class _Scanner(threading.Thread):
    """在后台跑一次检测；结果经页面回调送回（不直接碰控件）。"""

    def __init__(self, text: str, threshold: float, min_chars: int, on_done) -> None:
        super().__init__(daemon=True)
        self._text = text
        self._threshold = threshold
        self._min_chars = min_chars
        self._on_done = on_done
        self.cancelled = False

    def run(self) -> None:
        try:
            from fixtext_duplicates import DetectOptions, detect_text

            report = detect_text(
                self._text,
                DetectOptions(threshold=float(self._threshold),
                              min_chars=int(self._min_chars)))
            payload = report.payload()
        except Exception as exc:                        # noqa: BLE001
            payload = None
            error = f"{type(exc).__name__}：{exc}"
        else:
            error = ""
        if self.cancelled:
            return
        self._on_done(payload, error)


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------

class DuplicateModule(QWidget):
    """重复段落清单页（只读定位 + 标记 / 忽略 + 撤销）。"""

    #: 跳到正文时发（载荷：组号 / 组内第几处 / 四套位置口径）
    jumpRequested = Signal(object)
    #: 处置状态变化后发（载荷：``{"group_id", "state", "changed"}``）
    marksChanged = Signal(object)
    #: 清单装好后发（载荷：清单视图，供自检 / 外部统计）
    loaded = Signal(object)
    #: 需要回到导入页时发（没有书可用）
    gotoImport = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text_path = ""
        self._book_name = ""
        self._text = ""
        self._lines: list[str] = []
        self.marks: dm.DuplicateMarks | None = None
        self.book_id = ""
        self._list: dl.DuplicateList = dl.DuplicateList()
        self._cur = -1
        self._member = 0
        self._scanner: _Scanner | None = None
        self._last_jump: dict[str, Any] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(px(sp("4")))

        root.addWidget(self._head())
        self._body = QWidget()
        bl = QVBoxLayout(self._body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(px(sp("4")))
        bl.addWidget(self._overview_card())
        bl.addWidget(self._list_card())
        bl.addWidget(self._locate_card())
        bl.addWidget(self._preview_card())
        bl.addWidget(self._marks_card())
        root.addWidget(self._body)

        self.empty_state = EmptyState(
            "🧩", "还没有可看重复段落的书",
            "先导入一本书，之后这里会按组列出重复段落，每一组都能跳到正文对应位置。",
            primary="📥 去导入第一本书", secondary=None)
        self.empty_state.primaryClicked.connect(lambda: self.gotoImport.emit())
        root.addWidget(self.empty_state)

        self.status = _muted("还没有选书。")
        root.addWidget(self.status)

        self._set_ready(False)

    # -- 构建 ---------------------------------------------------------------

    def _head(self) -> QWidget:
        shell, body = page_head_shell()
        hl = QHBoxLayout(body)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)
        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel("重复段落清单")
        title.setObjectName("PageTitle")
        title.setStyleSheet(
            f"color:{c('neutral.900')};font-size:{fs('2xl')};"
            f"font-weight:{FONT_WEIGHT['semibold']}")
        sub = QLabel("按组列出重复段落，逐组跳到正文核对；可以标记或忽略，不会动到正文。")
        sub.setObjectName("PageSub")
        sub.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('sm')}")
        col.addWidget(title)
        col.addWidget(sub)
        hl.addLayout(col)
        hl.addStretch(1)
        self.book_label = _muted("还没有选书")
        hl.addWidget(self.book_label)
        return shell

    def _overview_card(self) -> Card:
        card = Card("清单概况", "这一本书、这一次检测的范围")
        row = QHBoxLayout()
        row.setSpacing(px(sp("2")))
        self.scan_btn = QPushButton("① 扫描这本书")
        self.scan_btn.setObjectName("BtnPrimary")
        self.scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_btn.clicked.connect(lambda: self.scan())
        row.addWidget(self.scan_btn)

        row.addWidget(_muted("相似度阈值"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.30, 1.00)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setValue(DEFAULT_THRESHOLD)
        self.threshold_spin.setFixedWidth(80)
        row.addWidget(self.threshold_spin)

        row.addWidget(_muted("最短字数"))
        self.minchars_spin = QSpinBox()
        self.minchars_spin.setRange(2, 400)
        self.minchars_spin.setValue(DEFAULT_MIN_CHARS)
        self.minchars_spin.setFixedWidth(80)
        row.addWidget(self.minchars_spin)

        row.addWidget(_muted("排序"))
        self.order_box = QComboBox()
        for key, name in (("count", "按出现次数"),
                          ("position", "按书中位置"),
                          ("similarity", "按相似度")):
            self.order_box.addItem(name, key)
        self.order_box.setFixedWidth(120)
        self.order_box.currentIndexChanged.connect(lambda _i: self._refilter())
        row.addWidget(self.order_box)

        row.addWidget(_muted("只看"))
        self.filter_box = QComboBox()
        self.filter_box.addItem("全部", dl.FILTER_ALL)
        self.filter_box.addItem("完全重复", dl.FILTER_EXACT)
        self.filter_box.addItem("相似重复", dl.FILTER_SIMILAR)
        self.filter_box.setFixedWidth(110)
        self.filter_box.currentIndexChanged.connect(lambda _i: self._refilter())
        row.addWidget(self.filter_box)
        card.body_l.addLayout(row)

        card.body_l.addWidget(hline())

        pills = QHBoxLayout()
        pills.setSpacing(px(sp("2")))
        self.pill_groups = Pill("0 组", "info")
        self.pill_exact = Pill("完全重复 0 组", "warn")
        self.pill_similar = Pill("相似重复 0 组", "neutral")
        self.pill_handled = Pill("已处置 0 组", "ok")
        for pill in (self.pill_groups, self.pill_exact, self.pill_similar,
                     self.pill_handled):
            pills.addWidget(pill)
        pills.addStretch(1)
        self.only_open = QCheckBox("只看未处置")
        self.only_open.setStyleSheet(
            f"color:{c('neutral.600')};font-size:{fs('sm')}")
        self.only_open.toggled.connect(lambda _v: self._refilter())
        pills.addWidget(self.only_open)
        card.body_l.addLayout(pills)

        self.overview = _muted("还没有扫描。")
        self.overview.setWordWrap(True)
        card.body_l.addWidget(self.overview)
        return card

    def _list_card(self) -> Card:
        card = Card("重复清单", "点任意一组，下面报出它的位置")
        nav = QHBoxLayout()
        nav.setSpacing(px(sp("2")))
        self.prev_btn = QPushButton("◀ 上一组")
        self.next_btn = QPushButton("下一组 ▶")
        for btn in (self.prev_btn, self.next_btn):
            btn.setObjectName("BtnOutline")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn.clicked.connect(lambda: self.step(1))
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        self.counter = _muted("第 — / — 组")
        nav.addWidget(self.counter)
        nav.addStretch(1)
        card.body_l.addLayout(nav)

        self.view = _table()
        self.model = DuplicateListModel(self.view)
        self.view.setModel(self.model)
        head = self.view.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.view.setMinimumHeight(240)
        self.view.selectionModel().currentRowChanged.connect(self._on_row)
        card.body_l.addWidget(self.view)
        return card

    def _locate_card(self) -> Card:
        card = Card("定位", "四套口径同时给出：段序号 / 章节 / 行区间 / 字符偏移")
        self.loc_group = _muted("还没有选中任何一组。")
        self.loc_group.setWordWrap(True)
        card.body_l.addWidget(self.loc_group)

        self.loc_index = _muted("")
        self.loc_chapter = _muted("")
        self.loc_line = _muted("")
        self.loc_char = _muted("")
        for lab in (self.loc_index, self.loc_chapter, self.loc_line, self.loc_char):
            lab.setWordWrap(True)
            card.body_l.addWidget(lab)

        card.body_l.addWidget(hline())

        row = QHBoxLayout()
        row.setSpacing(px(sp("2")))
        row.addWidget(_muted("组内第"))
        self.member_from = QSpinBox()
        self.member_from.setRange(1, 1)
        self.member_from.setFixedWidth(70)
        self.member_from.valueChanged.connect(self._on_member_pick)
        row.addWidget(self.member_from)
        self.member_total = _muted("/ 1 处")
        row.addWidget(self.member_total)

        self.jump_btn = QPushButton("跳到正文")
        self.jump_btn.setObjectName("BtnPrimary")
        self.jump_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.jump_btn.clicked.connect(lambda: self.jump())
        row.addWidget(self.jump_btn)

        self.member_prev = QPushButton("◀ 上一处")
        self.member_prev.setObjectName("BtnOutline")
        self.member_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.member_prev.clicked.connect(lambda: self.step_member(-1))
        row.addWidget(self.member_prev)

        self.member_next = QPushButton("下一处 ▶")
        self.member_next.setObjectName("BtnOutline")
        self.member_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.member_next.clicked.connect(lambda: self.step_member(1))
        row.addWidget(self.member_next)
        row.addStretch(1)
        self.copy_btn = QPushButton("复制位置")
        self.copy_btn.setObjectName("BtnOutline")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.clicked.connect(self.copy_position)
        row.addWidget(self.copy_btn)
        card.body_l.addLayout(row)

        self.members_note = _muted("")
        self.members_note.setWordWrap(True)
        card.body_l.addWidget(self.members_note)
        return card

    def _preview_card(self) -> Card:
        card = Card("正文位置", "只读；跳转会落在这几行上，正文不会被改动")
        self.preview_note = _muted("选中一组后，这里显示它在正文里的样子。")
        self.preview_note.setWordWrap(True)
        card.body_l.addWidget(self.preview_note)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(200)
        self.preview.setStyleSheet(
            f"QPlainTextEdit{{background:{c('neutral.50')};"
            f"border:1px solid {c('neutral.200')};border-radius:{r('md')};"
            f"font-size:{fs('sm')};color:{c('neutral.700')};padding:8px;}}")
        card.body_l.addWidget(self.preview)
        return card

    def _marks_card(self) -> Card:
        card = Card("处置", "只有「标记 / 忽略」两态，没有删除；随时可以撤销")
        row = QHBoxLayout()
        row.setSpacing(px(sp("2")))
        self.mark_btn = QPushButton("标记这一组")
        self.mark_btn.setObjectName("BtnOutline")
        self.mark_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mark_btn.clicked.connect(lambda: self.set_state(dm.ST_MARKED))
        row.addWidget(self.mark_btn)

        self.ignore_btn = QPushButton("忽略这一组")
        self.ignore_btn.setObjectName("BtnOutline")
        self.ignore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ignore_btn.clicked.connect(lambda: self.set_state(dm.ST_IGNORED))
        row.addWidget(self.ignore_btn)

        self.clear_btn = QPushButton("清回未处置")
        self.clear_btn.setObjectName("BtnGhost")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(lambda: self.set_state(dm.ST_NONE))
        row.addWidget(self.clear_btn)

        self.undo_btn = QPushButton("撤销上次处置")
        self.undo_btn.setObjectName("BtnOutline")
        self.undo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.undo_btn.clicked.connect(self.undo_last)
        row.addWidget(self.undo_btn)
        row.addStretch(1)
        card.body_l.addLayout(row)

        self.marks_note = _muted(
            "处置随这本书保存：写在这本书自己的记录里，换一本书不会串味；"
            "书稿本身不会被改动一个字节。")
        self.marks_note.setWordWrap(True)
        card.body_l.addWidget(self.marks_note)

        self.marks_status = _muted("这本书还没有处置过任何一组。")
        self.marks_status.setWordWrap(True)
        card.body_l.addWidget(self.marks_status)
        return card

    # -- 挂书 ---------------------------------------------------------------

    def set_book(self, text_path: str, book_name: str = "") -> None:
        """挂当前书：清掉上一本的清单与处置绑定（不跨书串扰）。"""
        self._cancel_scan()
        self._text_path = str(text_path or "")
        self._book_name = book_name or (
            Path(self._text_path).parent.name if self._text_path else "")
        self._text = ""
        self._lines = []
        self.marks = None
        self.book_id = ""
        self._set_list(dl.DuplicateList())
        if self._text_path:
            try:
                self._text = Path(self._text_path).read_text(encoding="utf-8")
                self._lines = self._text.splitlines()
            except Exception as exc:                    # noqa: BLE001
                self._text = ""
                self._lines = []
                self._say(f"读不到这本书的正文：{type(exc).__name__}")
        if self._text:
            self.book_id = dm.book_id_of_text_path(self._text_path)
            if self.book_id:
                self.marks = dm.DuplicateMarks(
                    store_dir=Path(self._text_path).resolve().parent / dm.BACKUP_DIRNAME)
                self.marks.bind(self._text_path)
        self.book_label.setText(
            f"当前书：{self._book_name}" if self._book_name else "还没有选书")
        self._set_ready(bool(self._text))
        if self._text:
            self.scan()
        else:
            self._say("还没有选书。" if not self._text_path else "这本书的正文读不出来。")

    def set_payload(self, payload: dict[str, Any]) -> None:
        """直接给一份检测结果视图（自检 / 验收 / 离线复现用，不再跑一次检测）。"""
        self._set_payload(payload, "")

    # -- 检测 ---------------------------------------------------------------

    def _cancel_scan(self) -> None:
        if self._scanner is not None:
            self._scanner.cancelled = True
            self._scanner = None

    def scan(self, *, silent: bool = False) -> None:
        """按当前阈值扫一遍这本书（后台跑，界面不卡）。"""
        if not self._text:
            self._say("这本书的正文读不出来，先重新导入一次。")
            return
        threshold = float(self.threshold_spin.value())
        min_chars = int(self.minchars_spin.value())
        self._cancel_scan()
        self.scan_btn.setEnabled(False)
        if not silent:
            self._say(f"正在扫描（相似度阈值 {threshold:.2f}，最短 {min_chars} 字）…")
        self._scanner = _Scanner(self._text, threshold, min_chars,
                                 lambda p, e: self._on_scanned(p, e))
        self._scanner.start()

    def _on_scanned(self, payload: dict[str, Any] | None, error: str) -> None:
        self._scanner = None
        self.scan_btn.setEnabled(True)
        if payload is None:
            self._say(f"这次扫描没能完成：{error}")
            return
        self._set_payload(payload, error)

    def _set_payload(self, payload: dict[str, Any], error: str) -> None:
        records = {}
        if self.marks is not None:
            records = self.marks.records(payload.get("threshold") or 0.0,
                                         payload.get("min_chars") or 0)
        self._records = records
        self._payload = payload
        self._refilter(payload=payload, records=records)
        if error:
            self._say(f"这次扫描没能完成：{error}")

    # -- 清单装配 -----------------------------------------------------------

    def _order_key(self) -> str:
        data = self.order_box.currentData()
        return str(data or "count")

    def _filter_key(self) -> str:
        return str(self.filter_box.currentData() or dl.FILTER_ALL)

    def _refilter(self, *, payload: dict[str, Any] | None = None,
                  records: dict[str, dict] | None = None) -> None:
        """按当前排序 / 筛选重建清单（处置状态只作筛选与展示）。"""
        payload = payload if payload is not None else getattr(self, "_payload", None)
        records = records if records is not None else getattr(self, "_records", {})
        if not isinstance(payload, dict):
            return
        show = "open" if self.only_open.isChecked() else "all"
        states = {gid: str(rec.get("state") or "") for gid, rec in (records or {}).items()}
        keep_id = self.current_item().group_id if self.current_item() else ""
        view = dl.build_list(payload, order=self._order_key(),
                             kind=self._filter_key(), show=show, marks=states)
        self._set_list(view, records, keep_id)

    def _set_list(self, view: dl.DuplicateList, records: dict[str, dict] | None = None,
                  keep_id: str = "") -> None:
        self._list = view
        self.model.set_list(view, records)
        self._update_overview()
        self._refresh_marks_status()
        row = view.row_of(keep_id) if keep_id else -1
        if row < 0 and view.items:
            row = 0
        if row >= 0:
            self.view.selectRow(row)
            self._select(row)
        else:
            self._cur = -1
            self._member = 0
            self._clear_locate()
        self.loaded.emit(view)

    def _update_overview(self) -> None:
        counts = self._list.counts()
        self.pill_groups.setText(f"{counts['groups']} 组")
        self.pill_exact.setText(f"完全重复 {counts['exact_groups']} 组")
        self.pill_similar.setText(f"相似重复 {counts['similar_groups']} 组")
        self.pill_handled.setText(f"已处置 {counts['handled']} 组")
        self.overview.setText(self._list.overview_text())

    def _refresh_marks_status(self) -> None:
        if self.marks is None:
            self.marks_status.setText(
                "这本书所在目录名不适合作为处置的作用域，先不记处置（其它功能不受影响）。"
                if self._text_path and not self.book_id
                else "还没有选书。")
            self.undo_btn.setEnabled(False)
            return
        payload = getattr(self, "_payload", None) or {}
        threshold = payload.get("threshold") or 0.0
        min_chars = payload.get("min_chars") or 0
        counts = self.marks.counts(threshold, min_chars)
        if counts["total"]:
            self.marks_status.setText(
                f"这一轮已处置 {counts['total']} 组：标记 {counts['marked']} 组、"
                f"忽略 {counts['ignored']} 组。")
        else:
            self.marks_status.setText("这本书这一轮还没有处置过任何一组。")
        self.undo_btn.setEnabled(self.marks.can_undo())

    # -- 选中 / 定位 ---------------------------------------------------------

    def current_item(self) -> dl.DuplicateItem | None:
        return self._list.item_at(self._cur)

    def _on_row(self, current, _previous) -> None:
        if current.isValid():
            self._select(current.row())

    def _select(self, row: int) -> None:
        item = self._list.item_at(row)
        if item is None:
            return
        self._cur = row
        self._member = 0
        self.member_from.blockSignals(True)
        self.member_from.setRange(1, max(1, len(item.slots)))
        self.member_from.setValue(1)
        self.member_from.blockSignals(False)
        self.member_total.setText(f"/ {max(1, len(item.slots))} 处")
        self._render_locate()
        self._render_preview()
        self.counter.setText(f"第 {row + 1} / {self._list.counts()['groups']} 组")

    def _clear_locate(self) -> None:
        self.loc_group.setText("还没有选中任何一组。")
        for lab in (self.loc_index, self.loc_chapter, self.loc_line, self.loc_char):
            lab.setText("")
        self.members_note.setText("")
        self.member_total.setText("/ 1 处")
        self.counter.setText("第 — / — 组")
        self.preview.setPlainText("")
        self.preview.setExtraSelections([])
        self.preview_note.setText("选中一组后，这里显示它在正文里的样子。")

    def _render_locate(self) -> None:
        item = self.current_item()
        if item is None or not item.slots:
            self._clear_locate()
            return
        slot = item.slots[min(self._member, len(item.slots) - 1)]
        texts = slot.texts()
        self.loc_group.setText(
            f"{item.group_id}　{item.summary_text()}　"
            f"相似度 {item.similarity_text()}　共 {item.pair_count} 对")
        self.loc_index.setText(f"段序号：{texts['index']}")
        self.loc_chapter.setText(f"章节：{texts['chapter']}")
        self.loc_line.setText(f"行区间：{texts['line']}（第 {slot.line_start} 行到第 "
                              f"{slot.line_end} 行，闭区间）")
        self.loc_char.setText(f"字符偏移：{texts['char']}（左闭右开，指向含标签原文）")
        self.members_note.setText(
            "组内各处的位置：" + "；".join(
                f"{i}）{s.location_text()}" for i, s in enumerate(item.slots, 1)))

    def _on_member_pick(self, value: int) -> None:
        item = self.current_item()
        if item is None:
            return
        self._member = max(0, int(value) - 1)
        self._render_locate()
        self._render_preview()

    def step_member(self, delta: int) -> None:
        item = self.current_item()
        if item is None or not item.slots:
            return
        total = len(item.slots)
        self._member = (self._member + delta) % total
        self.member_from.blockSignals(True)
        self.member_from.setValue(self._member + 1)
        self.member_from.blockSignals(False)
        self._render_locate()
        self._render_preview()

    def step(self, delta: int) -> None:
        total = self._list.counts()["groups"]
        if total == 0:
            return
        row = self._cur
        row = (row + delta) % total if row >= 0 else (0 if delta > 0 else total - 1)
        self.view.selectRow(row)
        self.view.scrollTo(self.model.index(row, 0))

    # -- 正文预览与跳转 -------------------------------------------------------

    def _render_preview(self) -> None:
        """把这一处附近的行摆出来，并把光标落在它的行区间上（真实跳转）。"""
        item = self.current_item()
        if item is None or not item.slots or not self._lines:
            self.preview.setPlainText("")
            self.preview.setExtraSelections([])
            return
        slot = item.slots[min(self._member, len(item.slots) - 1)]
        lo = max(1, slot.line_start)
        hi = max(lo, slot.line_end)
        total = len(self._lines)
        if lo > total:
            self.preview_note.setText(
                f"这一处标在第 {lo} 行，可这本书现在只有 {total} 行——正文改过之后行号会对不上。")
            self.preview.setPlainText("")
            self.preview.setExtraSelections([])
            return
        hi = min(hi, total)
        first = max(1, lo - CONTEXT_LINES)
        last = min(total, hi + CONTEXT_LINES)
        blocks: list[str] = []
        sel_from = sel_to = -1
        for n in range(first, last + 1):
            prefix = f"L{n}   "
            if n == lo:
                sel_from = sum(len(b) + 1 for b in blocks) + len(prefix)
            blocks.append(prefix + self._lines[n - 1])
            if n == hi:
                sel_to = sum(len(b) + 1 for b in blocks) - 1
        self.preview.setPlainText("\n".join(blocks))
        if sel_from >= 0 and sel_to > sel_from:
            sel = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            fmt.setBackground(QBrush(QColor(c("warning.bg"))))
            fmt.setFontWeight(QFont.Weight.Bold)
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SingleUnderline)
            fmt.setUnderlineColor(QColor(c("warning")))
            sel.format = fmt
            cur = QTextCursor(self.preview.document())
            cur.setPosition(sel_from)
            cur.setPosition(sel_to, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cur
            self.preview.setExtraSelections([sel])
            self.preview.setTextCursor(cur)
            self.preview.ensureCursorVisible()
        self.preview_note.setText(
            f"第 {slot.line_start}–{slot.line_end} 行（{slot.chapter_text()}；"
            f"光标已落在这一段的开头，高亮是这一段的正文）")

    def jump(self) -> dict[str, Any] | None:
        """跳到正文：把预览光标落到该段并高亮，同时发出跳转信号。"""
        item = self.current_item()
        if item is None or not item.slots:
            self._say("先在清单里选一组，再跳到正文。")
            return None
        self._render_preview()
        slot = item.slots[min(self._member, len(item.slots) - 1)]
        payload = dict(group_id=item.group_id, member=self._member,
                       total=len(item.slots), target=slot.target(),
                       location=slot.location_text())
        self._last_jump = payload
        self.jumpRequested.emit(payload)
        self._say(f"已跳到 {item.group_id} 的第 {self._member + 1} 处："
                  f"{slot.location_text()}")
        return payload

    def last_jump(self) -> dict[str, Any]:
        """最近一次跳转的载荷（自检 / 验收用）。"""
        return dict(self._last_jump)

    def copy_position(self) -> None:
        item = self.current_item()
        if item is None or not item.slots:
            return
        slot = item.slots[min(self._member, len(item.slots) - 1)]
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(slot.location_text())

    # -- 处置 ---------------------------------------------------------------

    def set_state(self, state: str, *, group_id: str | None = None) -> dict:
        """对当前（或指定）一组做标记 / 忽略 / 清回未处置。

        只写处置记录；书稿与正文一字不动。处置后清单就地刷新（保留当前选中）。
        """
        item = self.current_item() if group_id is None else self._item_of(group_id or "")
        if item is None:
            self._say("先在清单里选一组，再做处置。")
            return dict(changed=False)
        if self.marks is None:
            self._say("这本书不能记处置（书所在目录名不合规），其它功能不受影响。")
            return dict(changed=False)
        payload = getattr(self, "_payload", None) or {}
        threshold = float(payload.get("threshold") or 0.0)
        min_chars = int(payload.get("min_chars") or 0)
        try:
            res = self.marks.set_state(
                item.group_id, state, threshold=threshold, min_chars=min_chars,
                signature=dm.signature_of((s.index, s.text) for s in item.slots),
                occurrences=item.occurrences,
                paragraphs=[s.index for s in item.slots])
        except Exception as exc:                        # noqa: BLE001
            self._say(f"这一组没能记下来：{type(exc).__name__}")
            return dict(changed=False)
        self._after_marks(res, item.group_id, state)
        return res

    def _item_of(self, group_id: str) -> dl.DuplicateItem | None:
        for it in self._list.items:
            if it.group_id == group_id:
                return it
        return None

    def _after_marks(self, res: dict, group_id: str, state: str) -> None:
        if res.get("changed"):
            name = dm.STATE_NAMES.get(state, "未处置")
            self._say(f"{group_id} 已处置为「{name}」。")
        else:
            self._say(f"{group_id} 已经是这个状态，没有重复写盘。")
        self._refilter()
        self.marksChanged.emit(dict(group_id=group_id, state=state,
                                    changed=bool(res.get("changed"))))
        self._refresh_marks_status()

    def undo_last(self) -> dict | None:
        """撤销最近一次处置（处置记录逐字节回到处置前）。"""
        if self.marks is None:
            self._say("这本书没有可撤销的处置记录。")
            return None
        res = self.marks.undo_last()
        if res is None:
            self._say("没有可撤销的处置记录。")
            self._refresh_marks_status()
            return None
        keep_id = self.current_item().group_id if self.current_item() else ""
        self._records = (self.marks.records(
            (getattr(self, "_payload", {}) or {}).get("threshold") or 0.0,
            (getattr(self, "_payload", {}) or {}).get("min_chars") or 0))
        self._refilter(records=self._records)
        if keep_id:
            row = self._list.row_of(keep_id)
            if row >= 0:
                self.view.selectRow(row)
        self._say(f"已撤销「{res['label']}」；处置记录"
                  + ("逐字节回到处置前的状态。" if res.get("identical")
                     else "已回写，但内容与处置前不一致，请检查。"))
        self.marksChanged.emit(dict(group_id="", state="", changed=True,
                                    undone=res["point_id"]))
        self._refresh_marks_status()
        return res

    # -- 状态 ---------------------------------------------------------------

    def _set_ready(self, ready: bool) -> None:
        self._body.setVisible(bool(ready))
        self.empty_state.setVisible(not ready)
        for btn in (self.prev_btn, self.next_btn):
            btn.setEnabled(bool(ready))

    def _say(self, text: str) -> None:
        self.status.setText(text)

    def metrics(self) -> dict:
        """本次清单的规模（验收记录用）。"""
        return dict(groups=self._list.counts()["groups"],
                    paragraphs=self._list.counts()["paragraphs"],
                    handled=self._list.counts()["handled"],
                    threshold=self._list.threshold,
                    min_chars=self._list.min_chars)

    def shutdown(self) -> None:
        self._cancel_scan()


__all__ = ["DuplicateModule", "DuplicateListModel", "CONTEXT_LINES",
           "DEFAULT_THRESHOLD", "DEFAULT_MIN_CHARS"]
