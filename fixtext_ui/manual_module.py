"""V1.1-E4 · 手动逐批替换页（索引 / 范围选择 + 逐批执行 / 跳过 / 撤销）
==========================================================================

本页是排期文档 §10.5 交付物①的界面载体，内容区的**平级路由页**
（与前后对比页同一种接法：左轨六入口配额不变，由检查页的入口卡进入）。

页面上的四件事，对应四条判据：

1. **索引 / 范围选择**：规则清单按原表顺序列出（序号 + 规则 + 命中数），
   可以按序号区间挑、也可以只挑有命中的，或者在清单里逐条勾选；
2. **「执行 / 跳过」交互**：选好之后切成分批清单，每一批单独
   「预览 → 确认执行」或「跳过」；跳过的批可以「放回待执行」（磁盘没动过）；
3. **每批替换前的备份**：执行某批之前，正文整份字节进既有还原点仓库，
   页面上「备份」区随时能看到这一批的备份点与是否已撤回；
4. **每批可单独撤销**：任意已执行的批都能单独撤，不要求是最后一批。

所有写盘动作都只在 :class:`fixtext_batch_confirm.BatchSession` 里发生，
本模块只负责「用户在哪一步点了什么」以及把结果说成人话。确认对话框是
真正的关口：取消 = 一个字节都不写。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QSpinBox, QTableView, QVBoxLayout, QWidget,
)

import fixtext_batch_confirm as bc
from fixtext_manual_search import ORDER_FILE, ORDER_LABELS, RuleSet, load_rules
from fixtext_tokens import c, fs, sp, r, FONT_WEIGHT
from fixtext_widgets import Card, EmptyState, hline, page_head_shell, px, ConfirmDialog

# ---------------------------------------------------------------------------
# 状态 → 人话
# ---------------------------------------------------------------------------

STATE_LABEL = {
    bc.ST_PENDING: "待执行",
    bc.ST_PREVIEWED: "已预览",
    bc.ST_EXECUTED: "已执行",
    bc.ST_SKIPPED: "已跳过",
}

STATE_KIND = {
    bc.ST_PENDING: "neutral",
    bc.ST_PREVIEWED: "warn",
    bc.ST_EXECUTED: "ok",
    bc.ST_SKIPPED: "info",
}


def _muted(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(
        f"color:{c('neutral.600')};font-size:{fs('sm')};background:transparent")
    return lab


def _table() -> QTableView:
    view = QTableView()
    view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
    view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
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
# 规则清单模型（带勾选）
# ---------------------------------------------------------------------------

class RulePickModel(QAbstractTableModel):
    """规则清单：序号 / 规则 / 命中数 / 说明。勾选即「选中要处理」。"""

    COLS = ("序号", "规则", "命中", "说明")
    COL_INDEX, COL_MARK, COL_HITS, COL_NOTE = range(4)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules: list[Any] = []
        self._hits: dict[int, int] = {}
        self._picked: set[int] = set()

    # -- 数据装载 ---------------------------------------------------------

    def set_rules(self, rules: list[Any], hits: dict[int, int] | None = None) -> None:
        self.beginResetModel()
        self._rules = list(rules)
        self._hits = dict(hits or {})
        self.endResetModel()

    def set_hits(self, hits: dict[int, int]) -> None:
        self._hits = dict(hits)
        if self._rules:
            self.dataChanged.emit(
                self.index(0, self.COL_HITS),
                self.index(len(self._rules) - 1, self.COL_HITS),
            )

    def set_picked(self, indices) -> None:
        self._picked = set(int(i) for i in indices)
        if self._rules:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self._rules) - 1, self.columnCount() - 1))

    def picked(self) -> list[int]:
        return sorted(self._picked)

    def rule_at(self, row: int):
        return self._rules[row] if 0 <= row < len(self._rules) else None

    def row_of_index(self, rule_index: int) -> int:
        for r, rule in enumerate(self._rules):
            if rule.index == int(rule_index):
                return r
        return -1

    # -- QAbstractTableModel ---------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rules)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLS[section]
        return None

    def flags(self, index: QModelIndex):
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    def _note(self, rule) -> str:
        """规则说明了：只给「改前 → 改后」的形状，不外露规则源码。

        规则表里的 note 字段带有来源网址与工程字眼，直接搬上界面会露出内部
        细节；这里只按规则标识的形态给出人话（``{改前->改后}`` 形式）。
        """
        mark = str(rule.mark or "")
        if mark.startswith("{") and "->" in mark:
            body = mark.strip("{}")
            before, after = body.split("->", 1)
            return f"把「{before.strip()}」改成「{after.strip()}」"
        body = mark.strip("{}").strip()
        if body:
            # 少数规则（标点类）没有「改前->改后」的形状，规则标识本身就是人话，
            # 原样给出即可；仍然不搬 rules.json 的 note（那里带来源网址）。
            return f"按「{body}」这条规则处理"
        return "按这条规则处理"

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rules)):
            return None
        rule = self._rules[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.CheckStateRole and col == 0:
            return (Qt.CheckState.Checked if rule.index in self._picked
                    else Qt.CheckState.Unchecked)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            if col == 0:
                return str(rule.index)
            if col == 1:
                return str(rule.mark)
            if col == 2:
                return str(self._hits.get(rule.index, 0))
            return self._note(rule)
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (0, 2):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.CheckStateRole or index.column() != 0:
            return False
        rule = self._rules[index.row()]
        if Qt.CheckState(value) == Qt.CheckState.Checked:
            self._picked.add(rule.index)
        else:
            self._picked.discard(rule.index)
        self.dataChanged.emit(index, index)
        return True


# ---------------------------------------------------------------------------
# 批次清单模型
# ---------------------------------------------------------------------------

class BatchModel(QAbstractTableModel):
    COLS = ("批次", "规则序号", "条数", "命中", "状态")
    COL_BATCH, COL_RANGE, COL_COUNT, COL_HITS, COL_STATE = range(5)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._batches: list[Any] = []

    def set_batches(self, batches: list[Any]) -> None:
        self.beginResetModel()
        self._batches = list(batches)
        self.endResetModel()

    def refresh(self) -> None:
        if not self._batches:
            self.beginResetModel()
            self.endResetModel()
            return
        self.dataChanged.emit(self.index(0, 0),
                              self.index(len(self._batches) - 1, self.columnCount() - 1))

    def batch_at(self, row: int):
        return self._batches[row] if 0 <= row < len(self._batches) else None

    def row_of(self, batch_id: int) -> int:
        for r, b in enumerate(self._batches):
            if b.batch_id == int(batch_id):
                return r
        return -1

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._batches)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._batches)):
            return None
        b = self._batches[index.row()]
        col = index.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            if col == self.COL_BATCH:
                return f"第 {b.batch_id} 批"
            if col == self.COL_RANGE:
                if len(b.rules) == 1:
                    return str(b.first_index)
                return f"{b.first_index}–{b.last_index}"
            if col == self.COL_COUNT:
                return str(len(b.rules))
            if col == self.COL_HITS:
                return str(b.hits)
            return STATE_LABEL.get(b.state, b.state)
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (
                self.COL_RANGE, self.COL_COUNT, self.COL_HITS):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------

class ManualModule(QWidget):
    """手动逐批替换页（只读展示 + 逐批确认落盘）。"""

    #: 需要用户确认时发（预览对象 + 标题），接线方弹确认框
    confirmRequested = Signal(object)
    #: 有「书没就绪 / 规则没装上」等需要引导的情况
    gotoImport = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.session: bc.BatchSession | None = None
        self.ruleset: RuleSet | None = None
        self._text_path = ""
        self._book_name = ""
        self._text = ""
        self._confirm_hook = None       # 测试可替换的确认函数
        self._last_message = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(px(sp("4")))

        root.addWidget(self._head())
        self._body = QWidget()
        bl = QVBoxLayout(self._body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(px(sp("4")))
        bl.addWidget(self._scope_card())
        bl.addWidget(self._rules_card())
        bl.addWidget(self._plan_card())
        bl.addWidget(self._batches_card())
        bl.addWidget(self._backups_card())
        root.addWidget(self._body)

        self.empty_state = EmptyState(
            "🧾", "还没有可逐批处理的书",
            "先导入一本书（或在校正完之后回到这里），再按规则挑一批一批处理。"
            "每一批动手前都会自动留一份原样，并再问你一次。",
            primary="📥 去导入第一本书", secondary="🧭 打开新手向导",
        )
        root.addWidget(self.empty_state)
        root.addWidget(self._status_label())

        self._set_book_ready(False)
        self._load_rules()

    # -- 构建 ---------------------------------------------------------------

    def _head(self) -> QWidget:
        shell, body = page_head_shell()
        hl = QHBoxLayout(body)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)
        col = QVBoxLayout()
        title = QLabel("手动逐批替换")
        title.setObjectName("PageTitle")
        title.setStyleSheet(
            f"color:{c('neutral.900')};font-size:{fs('2xl')};"
            f"font-weight:{FONT_WEIGHT['semibold']}")
        sub = QLabel("挑规则、按批走：每一批都先预览、再确认、先备份后才动手。")
        sub.setObjectName("PageSub")
        sub.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('sm')}")
        col.addWidget(title)
        col.addWidget(sub)
        hl.addLayout(col)
        hl.addStretch(1)
        self.book_label = _muted("还没有选书")
        hl.addWidget(self.book_label)
        return shell

    def _scope_card(self) -> Card:
        card = Card("范围与选择", "按序号挑，或者只挑有命中的")
        row = QHBoxLayout()
        row.setSpacing(px(sp("2")))
        self.scan_btn = QPushButton("① 扫描这本书")
        self.scan_btn.setObjectName("BtnPrimary")
        self.scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_btn.clicked.connect(self.scan_book)
        row.addWidget(self.scan_btn)

        row.addWidget(_muted("序号"))
        self.range_from = QSpinBox()
        self.range_from.setRange(0, 0)
        self.range_from.setFixedWidth(80)
        row.addWidget(self.range_from)
        row.addWidget(_muted("到"))
        self.range_to = QSpinBox()
        self.range_to.setRange(0, 0)
        self.range_to.setFixedWidth(80)
        row.addWidget(self.range_to)
        self.range_btn = QPushButton("按范围选中")
        self.range_btn.setObjectName("BtnOutline")
        self.range_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.range_btn.clicked.connect(self.pick_range)
        row.addWidget(self.range_btn)

        self.nonzero_btn = QPushButton("只选有命中的")
        self.nonzero_btn.setObjectName("BtnOutline")
        self.nonzero_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nonzero_btn.clicked.connect(self.pick_nonzero)
        row.addWidget(self.nonzero_btn)

        self.clear_btn = QPushButton("清空选择")
        self.clear_btn.setObjectName("BtnGhost")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear_pick)
        row.addWidget(self.clear_btn)
        row.addStretch(1)
        card.body_l.addLayout(row)

        card.body_l.addSpacing(12)
        self.scope_note = _muted("还没扫描。先点「扫描这本书」才知道哪些规则在这本书上有命中。")
        self.scope_note.setWordWrap(True)
        card.body_l.addWidget(self.scope_note)
        return card

    def _rules_card(self) -> Card:
        card = Card("规则清单", "勾选的就是这一轮要处理的", collapsible=True, open_=True)
        self.rule_model = RulePickModel(self)
        self.rule_view = _table()
        self.rule_view.setModel(self.rule_model)
        self.rule_view.setMinimumHeight(240)
        self.rule_view.horizontalHeader().setSectionResizeMode(
            RulePickModel.COL_MARK, QHeaderView.ResizeMode.Stretch)
        self.rule_view.horizontalHeader().setSectionResizeMode(
            RulePickModel.COL_NOTE, QHeaderView.ResizeMode.Stretch)
        self.rule_view.setColumnWidth(RulePickModel.COL_INDEX, 60)
        self.rule_view.setColumnWidth(RulePickModel.COL_HITS, 60)
        self.rule_view.model().dataChanged.connect(lambda *_: self._sync_scope_note())
        card.body_l.addWidget(self.rule_view)
        return card

    def _plan_card(self) -> Card:
        card = Card("分批", "一批一批来，批越小越好核对")
        row = QHBoxLayout()
        row.setSpacing(px(sp("2")))
        row.addWidget(_muted("每批放"))
        self.chunk_box = QSpinBox()
        self.chunk_box.setRange(1, 50)
        self.chunk_box.setValue(1)
        self.chunk_box.setFixedWidth(72)
        row.addWidget(self.chunk_box)
        row.addWidget(_muted("条规则"))
        self.plan_btn = QPushButton("生成分批")
        self.plan_btn.setObjectName("BtnOutline")
        self.plan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.plan_btn.clicked.connect(self.make_plan)
        row.addWidget(self.plan_btn)
        row.addStretch(1)
        card.body_l.addLayout(row)
        card.body_l.addSpacing(10)
        self.plan_note = _muted("还没生成分批。选好规则后点「生成分批」。")
        self.plan_note.setWordWrap(True)
        card.body_l.addWidget(self.plan_note)
        return card

    def _batches_card(self) -> Card:
        card = Card("逐批处理", "预览 → 确认 → 才写回；随时可以跳过或单独撤销")
        self.batch_model = BatchModel(self)
        self.batch_view = _table()
        self.batch_view.setModel(self.batch_model)
        self.batch_view.setMinimumHeight(200)
        self.batch_view.horizontalHeader().setSectionResizeMode(
            BatchModel.COL_STATE, QHeaderView.ResizeMode.Stretch)
        for col, w in ((BatchModel.COL_BATCH, 90), (BatchModel.COL_RANGE, 110),
                       (BatchModel.COL_COUNT, 60), (BatchModel.COL_HITS, 60)):
            self.batch_view.setColumnWidth(col, w)
        card.body_l.addWidget(self.batch_view)

        card.body_l.addSpacing(12)
        acts = QHBoxLayout()
        acts.setSpacing(px(sp("2")))
        self.preview_btn = QPushButton("预览选中批次")
        self.preview_btn.setObjectName("BtnOutline")
        self.preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_btn.clicked.connect(self.preview_selected)
        acts.addWidget(self.preview_btn)

        self.exec_btn = QPushButton("确认执行这一批")
        self.exec_btn.setObjectName("BtnPrimary")
        self.exec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.exec_btn.clicked.connect(self.execute_selected)
        acts.addWidget(self.exec_btn)

        self.skip_btn = QPushButton("跳过这批")
        self.skip_btn.setObjectName("BtnOutline")
        self.skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip_btn.clicked.connect(self.skip_selected)
        acts.addWidget(self.skip_btn)

        self.resume_btn = QPushButton("放回待执行")
        self.resume_btn.setObjectName("BtnGhost")
        self.resume_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.resume_btn.clicked.connect(self.resume_selected)
        acts.addWidget(self.resume_btn)

        self.undo_btn = QPushButton("↺ 撤销这一批")
        self.undo_btn.setObjectName("BtnOutline")
        self.undo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.undo_btn.clicked.connect(self.undo_selected)
        acts.addWidget(self.undo_btn)
        acts.addStretch(1)
        card.body_l.addLayout(acts)

        card.body_l.addSpacing(10)
        self.preview_note = _muted("选中一批，先「预览」，看清会改哪几处再决定。")
        self.preview_note.setWordWrap(True)
        card.body_l.addWidget(self.preview_note)
        return card

    def _backups_card(self) -> Card:
        card = Card("每批的备份", "动手之前自动留的原样，撤回后可核对", collapsible=True, open_=True)
        self.backup_note = _muted("还没有备份。第一批确认执行时会自动留下。")
        self.backup_note.setWordWrap(True)
        card.body_l.addWidget(self.backup_note)
        card.body_l.addWidget(hline())
        card.body_l.addSpacing(8)
        self.backup_list = QLabel("")
        self.backup_list.setWordWrap(True)
        self.backup_list.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.backup_list.setStyleSheet(
            f"color:{c('neutral.700')};font-size:{fs('sm')};background:transparent")
        card.body_l.addWidget(self.backup_list)
        return card

    def _status_label(self) -> QLabel:
        self.status = QLabel("")
        self.status.setVisible(False)
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"background:{c('neutral.800')};color:{c('neutral.0')};"
            f"border-radius:8px;padding:{sp('3')} {sp('4')};font-size:{fs('sm')}")
        return self.status

    # -- 规则集 -------------------------------------------------------------

    def _load_rules(self, path: str | Path | None = None) -> None:
        try:
            self.ruleset = load_rules(path)
            self.ruleset.warmup()
        except Exception as exc:                        # noqa: BLE001
            self.ruleset = None
            self.toast(f"规则没装上：{type(exc).__name__}")
            return
        self.rule_model.set_rules(self.ruleset.rules)
        n = len(self.ruleset)
        self.range_from.setRange(0, max(0, n - 1))
        self.range_to.setRange(0, max(0, n - 1))
        self.range_to.setValue(max(0, n - 1))

    @property
    def rule_count(self) -> int:
        return len(self.ruleset) if self.ruleset is not None else 0

    # -- 书 -----------------------------------------------------------------

    def set_book(self, text_path: str, book_name: str = "") -> None:
        """挂当前书；换书会丢掉上一本的会话（不跨书串扰）。"""
        self._text_path = str(text_path or "")
        self._book_name = book_name or (
            Path(self._text_path).parent.name if self._text_path else "")
        self._text = ""
        self.session = None
        if self._text_path:
            try:
                self._text = Path(self._text_path).read_text(encoding="utf-8")
            except Exception as exc:                    # noqa: BLE001
                self._text = ""
                self.toast(f"读不到这本书的正文：{type(exc).__name__}")
        self.rule_model.set_hits({})
        self.batch_model.set_batches([])
        self._refresh_backups()
        self.book_label.setText(
            f"当前书：{self._book_name}" if self._book_name else "还没有选书")
        self._set_book_ready(bool(self._text))
        if self._text:
            self.scan_book(silent=True)

    def _set_book_ready(self, ready: bool) -> None:
        self.empty_state.setVisible(not ready)
        self._body.setVisible(ready)

    # -- 扫描 / 选择 --------------------------------------------------------

    def scan_book(self, silent: bool = False) -> None:
        if not self._text:
            self.toast("先导入并选一本书")
            return
        if self.ruleset is None:
            self.toast("规则没装上，先检查安装包是否完整")
            return
        self.session = bc.BatchSession(
            self.ruleset, self._text,
            target_path=self._text_path,
            label=self._book_name or "当前书",
        )
        res = self.session.scan()
        hits = {h.rule.index: h.count for h in res.hits}
        self.rule_model.set_hits(hits)
        self.rule_model.set_picked([])
        self.batch_model.set_batches([])
        self.plan_note.setText("还没生成分批。选好规则后点「生成分批」。")
        self._refresh_backups()
        if not silent:
            self.toast(f"扫描完成：{len(self.ruleset)} 条规则里 "
                       f"{len(res.nonzero)} 条有命中，共 {res.total} 处")
        self._sync_scope_note()

    def pick_range(self) -> None:
        if self.session is None:
            self.toast("先扫描这本书")
            return
        idx = self.session.select_range(self.range_from.value(), self.range_to.value())
        self.rule_model.set_picked(idx)
        self.batch_model.set_batches([])
        self._sync_scope_note()

    def pick_nonzero(self) -> None:
        if self.session is None:
            self.toast("先扫描这本书")
            return
        idx = self.session.select_all_hits()
        self.rule_model.set_picked(idx)
        self.batch_model.set_batches([])
        self._sync_scope_note()

    def clear_pick(self) -> None:
        if self.session is None:
            return
        self.session.clear_selection()
        self.rule_model.set_picked([])
        self.batch_model.set_batches([])
        self._sync_scope_note()

    def _sync_scope_note(self) -> None:
        if self.session is None:
            return
        picked = self.rule_model.picked()
        self.session.selected = picked
        total = sum(self.session.hits_of(i) for i in picked)
        self.scope_note.setText(
            f"已选 {len(picked)} 条规则，这些规则在本书上共 {total} 处命中。")

    # -- 分批 ---------------------------------------------------------------

    def make_plan(self) -> None:
        if self.session is None:
            self.toast("先扫描这本书")
            return
        picked = self.rule_model.picked()
        if not picked:
            self.toast("还没选规则")
            return
        self.session.selected = picked
        batches = self.session.plan(self.chunk_box.value())
        self.batch_model.set_batches(batches)
        self.plan_note.setText(
            f"已切成 {len(batches)} 批，每批最多 {self.session.chunk} 条规则；"
            "选中一批再点预览。")
        self.preview_note.setText("选中一批，先「预览」，看清会改哪几处再决定。")

    def _selected_batch_id(self) -> int:
        rows = self.batch_view.selectionModel().selectedRows()
        if not rows:
            raise bc.BatchError("先在下面批次清单里选一批")
        b = self.batch_model.batch_at(rows[0].row())
        if b is None:
            raise bc.BatchError("先在下面批次清单里选一批")
        return b.batch_id

    def selected_batch_id(self) -> int | None:
        try:
            return self._selected_batch_id()
        except bc.BatchError:
            return None

    # -- 预览 / 执行 / 跳过 / 撤销 -------------------------------------------

    def _confirm(self, title: str, note: str, confirm_text: str = "确认执行",
                 *, kind: str = "warn") -> bool:
        """确认关口：默认弹 :class:`ConfirmDialog`；测试可换钩子。

        取消 = 返回 False，调用方必须**一个字节都不写**。
        """
        if self._confirm_hook is not None:
            return bool(self._confirm_hook(title, note))
        box = ConfirmDialog(icon="⚠️", title=title, note=note,
                            note_kind=kind, confirm_text=confirm_text,
                            confirm_kind="primary", parent=self)
        return box.exec() == ConfirmDialog.DialogCode.Accepted

    def preview_selected(self) -> None:
        if self.session is None:
            self.toast("先扫描这本书")
            return
        try:
            bid = self._selected_batch_id()
            pv = self.session.preview(bid)
        except bc.BatchError as exc:
            self.toast(str(exc))
            return
        self.batch_model.refresh()
        self._last_preview = pv
        lines = [f"第 {bid} 批：会改 {pv.hits} 处。"]
        for before, after in pv.samples[:2]:
            b = before.replace("\n", " ").strip()
            a = after.replace("\n", " ").strip()
            lines.append(f"例如「{b[:28]}…」→「{a[:28]}…」")
        self.preview_note.setText("\n".join(lines))
        self.toast(f"第 {bid} 批已预览：{pv.hits} 处待改，确认后才会写回")

    def execute_selected(self) -> None:
        if self.session is None:
            self.toast("先扫描这本书")
            return
        try:
            bid = self._selected_batch_id()
        except bc.BatchError as exc:
            self.toast(str(exc))
            return
        pv = getattr(self, "_last_preview", None)
        if pv is None or pv.batch_id != bid or self.session._previews.get(bid) is None:
            self.toast("这一批还没预览，先点「预览选中批次」")
            return
        note = (f"第 {bid} 批会改 {pv.hits} 处，写完就落盘。\n"
                f"动手之前会自动把整份原文留成备份（可在「每批的备份」里看到），"
                f"之后这一批也能单独撤销。")
        if not self._confirm(f"确认执行第 {bid} 批？", note):
            self.toast("已取消，没有写入任何内容")
            return
        try:
            rec = self.session.execute(bid, pv.token)
        except bc.BatchError as exc:
            self.toast(str(exc))
            self.batch_model.refresh()
            return
        self._last_preview = None
        self.batch_model.refresh()
        self._refresh_backups()
        self.preview_note.setText(
            f"第 {bid} 批已写回：{rec['hits']} 处。需要反悔就点「撤销这一批」。")
        self.toast(f"第 {bid} 批已写回 {rec['hits']} 处（备份已留）")

    def skip_selected(self) -> None:
        if self.session is None:
            self.toast("先扫描这本书")
            return
        try:
            bid = self._selected_batch_id()
            b = self.session.skip(bid, "用户跳过")
        except bc.BatchError as exc:
            self.toast(str(exc))
            return
        self.batch_model.refresh()
        self.preview_note.setText(
            f"第 {bid} 批已跳过，书里一个字节都没改；想回来就点「放回待执行」。")
        self.toast(f"第 {bid} 批已跳过（未写入）")

    def resume_selected(self) -> None:
        if self.session is None:
            return
        try:
            bid = self._selected_batch_id()
            self.session.resume_skip(bid)
        except bc.BatchError as exc:
            self.toast(str(exc))
            return
        self.batch_model.refresh()
        self.toast(f"第 {bid} 批已放回待执行")

    def undo_selected(self) -> None:
        if self.session is None:
            return
        try:
            bid = self._selected_batch_id()
            token = self.session.prepare_undo(bid)
        except bc.BatchError as exc:
            self.toast(str(exc))
            return
        note = (f"撤销第 {bid} 批：把这一批的改动从当前正文里摘掉，"
                f"其它已执行的批保持不动。撤销同样会写回，之前的备份仍在。")
        if not self._confirm(f"确认撤销第 {bid} 批？", note,
                             confirm_text="确认撤销", kind="warn"):
            self.toast("已取消撤销，正文没动")
            return
        try:
            rec = self.session.undo(bid, token)
        except bc.BatchError as exc:
            self.toast(str(exc))
            self.batch_model.refresh()
            return
        self.batch_model.refresh()
        self._refresh_backups()
        extra = "（已与该批备份逐字节核对一致）" if rec.get("backup_exact") and not rec.get("mismatch") else ""
        if rec.get("mismatch"):
            extra = f"（注意：{rec['mismatch']}）"
        self.preview_note.setText(f"第 {bid} 批已撤销{extra}。")
        self.toast(f"第 {bid} 批已撤销{extra}")

    # -- 备份显示 -----------------------------------------------------------

    def _refresh_backups(self) -> None:
        if self.session is None:
            self.backup_note.setText("还没有备份。第一批确认执行时会自动留下。")
            self.backup_list.setText("")
            return
        rows = self.session.backups()
        if not rows:
            self.backup_note.setText("还没有备份。第一批确认执行时会自动留下。")
            self.backup_list.setText("")
            return
        self.backup_note.setText(
            f"共 {len(rows)} 个备份点（每批动手前一份、每次撤销一份），"
            "标「已撤回」的是当时那一步已经被退回去。")
        lines = []
        for row in rows[:12]:
            mark = "已撤回" if row["undone"] else "在位"
            kind = "撤销" if row["act"] == "batch_undo" else "执行"
            lines.append(f"· {row['time']}  {kind}前留档  {mark}")
        self.backup_list.setText("\n".join(lines))

    # -- 文案输出 -----------------------------------------------------------

    def toast(self, msg: str) -> None:
        self._last_message = str(msg)
        self.status.setText(msg)
        self.status.setVisible(True)
        QTimer.singleShot(4000, lambda: self.status.setVisible(False))

    def last_message(self) -> str:
        return self._last_message

    def shutdown(self) -> None:
        pass
