"""V1.1-E9 · 替换报告页（内容区的平级路由页）
=================================================

落点（为什么不新造导航入口）
--------------------------
左轨六入口配额固定（导入 / 一键校正 / 检查问题 / 词库管理 / 导出结果 / 历史记录）。
替换报告是导出的产物、也是校正结果的复核材料，按既有范式做成**内容区的平级
路由页**（与前后对比页、重复段落清单页同一接法）：入口有三处——导出结果页的
结果卡、一键校正页的「查看替换报告」、前后对比页的「看完整报告」，页面本身
不进左轨。

本页只做「呈现」，不做解析
------------------------
报告怎么读、字段怎么容错、各口径怎么对账，全部属于 E8 数据层
（``fixtext_report``）与装配层（``fixtext_report_present``）。本页只把装配好的
:class:`~fixtext_report_present.ReportView` 摆到界面上：

* 数字一律原样取自报告，报告没写的显示「报告里没有写」，**绝不拿 0 顶替**；
* 命中数合计与明细合计对不上时**两个数都摆出来**，并写明差多少；
* 报告没有按词库拆分命中数时，只列各词库的规则条数，并明说「不按比例摊派」
  ——这是数据层的诚实缺口，呈现层不许补一个看起来合理的数字。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import fixtext_report_present as rp
from fixtext_tokens import FONT_MONO, FONT_WEIGHT, c, fs, r, sp
from fixtext_widgets import Card, EmptyState, Pill, hline, page_head_shell, px


def _muted(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(
        f"color:{c('neutral.600')};font-size:{fs('sm')};background:transparent")
    return lab


def _hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(
        f"color:{c('neutral.500')};font-size:{fs('xs')};background:transparent")
    return lab


def _stat_tile(value: str, label: str, note: str = "") -> QFrame:
    """一格概况数字（原型 .stat）。

    数值为「报告里没有写」时不放大字号——避免缺失被读成一个具体数。
    """
    box = QFrame()
    box.setObjectName("Stat")
    v = QVBoxLayout(box)
    v.setContentsMargins(14, 12, 14, 12)
    v.setSpacing(2)
    missing = value == rp.MISSING
    num = QLabel(value)
    num.setAlignment(Qt.AlignmentFlag.AlignCenter)
    num.setWordWrap(True)
    num.setStyleSheet(
        f"color:{c('neutral.500') if missing else c('primary.700')};"
        f"font-size:{fs('sm') if missing else fs('xl')};"
        f"font-weight:{FONT_WEIGHT['medium'] if missing else FONT_WEIGHT['bold']};"
        f"background:transparent")
    lab = QLabel(label)
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lab.setStyleSheet(
        f"color:{c('neutral.600')};font-size:{fs('xs')};background:transparent")
    v.addWidget(num)
    v.addWidget(lab)
    if note:
        n = QLabel(note)
        n.setAlignment(Qt.AlignmentFlag.AlignCenter)
        n.setWordWrap(True)
        n.setStyleSheet(
            f"color:{c('neutral.500')};font-size:{fs('xs')};background:transparent")
        v.addWidget(n)
    return box


def _diff_block(rows: list) -> QFrame:
    """改动对照块（原型 .diff）：改前红字删除线 / 改后绿字。"""
    box = QFrame()
    box.setObjectName("Diff")
    v = QVBoxLayout(box)
    v.setContentsMargins(14, 12, 14, 12)
    v.setSpacing(4)
    for row in rows:
        pri = QLabel(f"原：{row.before}")
        pri.setWordWrap(True)
        pri.setStyleSheet(
            f"color:{c('error')};text-decoration:line-through;"
            f"font-family:{FONT_MONO};font-size:{fs('xs')};background:transparent")
        cur = QLabel(f"改：{row.after}")
        cur.setWordWrap(True)
        cur.setStyleSheet(
            f"color:{c('success')};font-family:{FONT_MONO};"
            f"font-size:{fs('xs')};background:transparent")
        v.addWidget(pri)
        v.addWidget(cur)
    return box


def _table(headers: list[str], widths: list[int]) -> QTableWidget:
    tb = QTableWidget(0, len(headers))
    tb.setHorizontalHeaderLabels(headers)
    tb.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tb.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    tb.setShowGrid(False)
    tb.verticalHeader().setVisible(False)
    tb.verticalHeader().setDefaultSectionSize(28)
    tb.setAlternatingRowColors(False)
    hh = tb.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    for i, w in enumerate(widths):
        hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
        tb.setColumnWidth(i, w)
        if w <= 0:
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
    tb.setStyleSheet(
        f"QTableWidget{{background:{c('neutral.0')};"
        f"border:1px solid {c('neutral.200')};border-radius:{r('md')};"
        f"font-size:{fs('sm')};color:{c('neutral.800')};}}"
        f"QTableWidget::item{{padding:4px 6px;}}"
        f"QHeaderView::section{{background:{c('neutral.100')};"
        f"color:{c('neutral.600')};font-size:{fs('xs')};border:none;"
        f"border-bottom:1px solid {c('neutral.200')};padding:6px;}}"
    )
    return tb


class ReportModule(QWidget):
    """替换报告页（只读呈现 + 跳转到相关页面）。"""

    #: 报告装好后发（载荷：ReportView，供自检 / 外部统计）
    loaded = Signal(object)
    #: 需要回到导出页时发
    gotoExport = Signal()
    #: 需要回到导入页时发（还没有书）
    gotoImport = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = rp.empty_view("这本书还没有导出过报告")
        self.book_name = ""
        self.run_dir = ""
        self._keyword = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(px(sp("4")))

        root.addWidget(self._head())

        self._body = QWidget()
        bl = QVBoxLayout(self._body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(px(sp("4")))
        bl.addWidget(self._card_overview())
        bl.addWidget(self._card_rows())
        bl.addWidget(self._card_libraries())
        bl.addWidget(self._card_issues())
        root.addWidget(self._body)

        self.empty_state = EmptyState(
            "📄", "还没有可看的替换报告",
            "报告在导出时自动生成。先跑一次校正、再导出结果，这里就会出现本次替换的完整清单。",
            primary="📤 去导出结果", secondary=None)
        self.empty_state.primaryClicked.connect(lambda: self.gotoExport.emit())
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
        title = QLabel("替换报告")
        title.setObjectName("PageTitle")
        title.setStyleSheet(
            f"color:{c('neutral.900')};font-size:{fs('2xl')};"
            f"font-weight:{FONT_WEIGHT['semibold']}")
        sub = QLabel("这次校正到底改了哪些地方：命中多少处、按词条列出的每一条改动，都在这里。")
        sub.setObjectName("PageSub")
        sub.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('sm')}")
        col.addWidget(title)
        col.addWidget(sub)
        hl.addLayout(col)
        hl.addStretch(1)
        self.book_label = _muted("还没有选书")
        hl.addWidget(self.book_label)
        return shell

    def _card_overview(self) -> Card:
        card = Card("报告概况", "数字原样取自报告，报告没写的会写明没写")
        v = card.body_l
        self.kpi_row = QHBoxLayout()
        self.kpi_row.setSpacing(px(sp("2")))
        v.addLayout(self.kpi_row)
        self.meta_label = _hint("")
        v.addWidget(self.meta_label)
        self.consistency = _muted("")
        self.consistency.setObjectName("ConsistencyNote")
        v.addWidget(self.consistency)
        rd = QHBoxLayout()
        rd.setSpacing(10)
        self.diff_holder = QVBoxLayout()
        self.diff_holder.setSpacing(4)
        rd.addLayout(self.diff_holder, 1)
        v.addLayout(rd)
        return card

    def _card_rows(self) -> Card:
        card = Card("逐条改动", "按替换次数从多到少排列")
        v = card.body_l
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("FmtCombo")
        self.search_edit.setPlaceholderText("搜改前或改后的字词…")
        self.search_edit.setFixedWidth(280)
        self.search_edit.textChanged.connect(self._on_search)
        bar.addWidget(self.search_edit)
        self.search_pill = _hint("")
        bar.addWidget(self.search_pill)
        bar.addStretch(1)
        v.addLayout(bar)
        self.rows_table = _table(["改前", "改后", "替换次数", "占全部命中"], [-1, -1, 110, 120])
        self.rows_table.setMinimumHeight(320)
        v.addWidget(self.rows_table)
        self.rows_note = _hint("")
        v.addWidget(self.rows_note)
        return card

    def _card_libraries(self) -> Card:
        card = Card("涉及哪些词库", "命中的规则来自哪几套词库")
        v = card.body_l
        self.lib_table = _table(["词库", "说明", "应用规则", "去重规则", "提取词条"],
                                [-1, -1, 110, 110, 110])
        self.lib_table.setMinimumHeight(140)
        v.addWidget(self.lib_table)
        self.lib_note = _hint("")
        v.addWidget(self.lib_note)
        return card

    def _card_issues(self) -> Card:
        card = Card("读取提示", "报告里有哪些地方需要你知道")
        self.issues_card = card
        v = card.body_l
        self.issues_box = QVBoxLayout()
        self.issues_box.setSpacing(6)
        v.addLayout(self.issues_box)
        return card

    # -- 取值 ---------------------------------------------------------------

    def _set_ready(self, ready: bool) -> None:
        self._body.setVisible(bool(ready))
        self.empty_state.setVisible(not ready)

    def set_context(self, *, book_name: str = "", run_dir: str = "") -> None:
        """记下当前书与运行目录（改书后重新装报告用）。"""
        self.book_name = book_name or ""
        self.run_dir = run_dir or ""
        self.book_label.setText(f"《{self.book_name}》" if self.book_name else "还没有选书")

    def show_view(self, view) -> None:
        """把一个装配好的报告视图摆到界面上。"""
        self.view = view
        if view.run_dir and not self.run_dir:
            self.run_dir = view.run_dir
        ok = view.ok_to_show
        self._set_ready(ok)
        if not ok:
            self.empty_state.findChild(QLabel, "es-t")
            self._fill_empty(view)
            self.status.setText(view.empty_desc or view.empty_title)
            self.loaded.emit(view)
            return
        self._fill_overview(view)
        self._fill_rows(view)
        self._fill_libraries(view)
        self._fill_issues(view)
        self.status.setText(view.summary_line())
        self.loaded.emit(view)

    def load_file(self, path: str | Path) -> None:
        self.show_view(rp.load_report_file(path, run_dir=self.run_dir))

    def load_for_book(self, book_name: str = "", *, run_dir: str = "") -> None:
        """按书名找最近一份报告并呈现（找不到落在空态，不报假数）。"""
        title = book_name or self.book_name
        if run_dir:
            self.run_dir = run_dir
        if not title:
            self.show_view(rp.empty_view("还没有选书"))
            return
        self.show_view(rp.latest_report_view(title, run_dir=self.run_dir))

    # -- 填充 ---------------------------------------------------------------

    def _fill_empty(self, view) -> None:
        """空态文案按状态换（未校正 / 没有报告 / 读不出来各有各的说法）。

        EmptyState 的标题 / 描述标签是匿名控件（构建顺序固定：图标环 → 标题 →
        描述 → 按钮行），这里按顺序取用，不靠 objectName。
        """
        labels = self.empty_state.findChildren(QLabel)
        skipped_icon = False
        targets = []
        for lab in labels:
            if not skipped_icon and lab.objectName() == "EsIco":
                skipped_icon = True   # 图标是第一个 QLabel，跳过
                continue
            targets.append(lab)
        if len(targets) >= 2:
            targets[0].setText(view.empty_title or rp.STATE_TITLES.get(view.state, ""))
            targets[1].setText(view.empty_desc or "")

    def _clear(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            sub = item.layout()
            if sub is not None:
                self._clear(sub)

    def _fill_overview(self, view) -> None:
        self._clear(self.kpi_row)
        for kpi in view.kpis:
            self.kpi_row.addWidget(_stat_tile(kpi.value, kpi.label, kpi.note), 1)

        bits = []
        if view.generated_at:
            bits.append(f"生成于 {view.generated_at}")
        if view.fmt_label:
            bits.append(f"报告以{view.fmt_label}留存")
        if view.title and view.title != self.book_name:
            bits.append(f"报告书名《{view.title}》")
        if view.author:
            bits.append(f"作者 {view.author}")
        self.meta_label.setText(" · ".join(bits))

        note = view.consistency_note
        self.consistency.setText(note)
        self.consistency.setVisible(bool(note))
        bad = view.hits_consistent is False
        self.consistency.setStyleSheet(
            f"color:{c('warning') if bad else c('neutral.600')};"
            f"font-size:{fs('sm')};background:transparent")

        self._clear(self.diff_holder)
        if view.top_rows:
            self.diff_holder.addWidget(_diff_block(view.top_rows[:3]))
            cap = _hint(f"上面先看改动最多的 3 条；完整 {view.detail_rows} 条在下面的清单里。")
            self.diff_holder.addWidget(cap)
        elif view.state == rp.STATE_UNCORRECTED:
            self.diff_holder.addWidget(_hint(
                "这次导出前没有跑过校正，所以报告里没有改动可列——上面的 0 是报告本身写的 0，"
                "不是读取失败。先跑一次校正，再导出就会有一份有内容的报告。"))
        else:
            self.diff_holder.addWidget(_hint("这份报告没有明细条目。"))

    def _match_rows(self, view):
        kw = self._keyword.strip()
        if not kw:
            return view.rows
        return [r0 for r0 in view.rows
                if kw in r0.before or kw in r0.after]

    def _fill_rows(self, view) -> None:
        rows = self._match_rows(view)
        tb = self.rows_table
        tb.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for col, text, align in (
                    (0, row.before, Qt.AlignmentFlag.AlignLeft),
                    (1, row.after, Qt.AlignmentFlag.AlignLeft),
                    (2, str(row.count), Qt.AlignmentFlag.AlignRight),
                    (3, row.share_text, Qt.AlignmentFlag.AlignRight)):
                item = QTableWidgetItem(text)
                item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                tb.setItem(i, col, item)

        total = view.detail_rows
        if self._keyword.strip():
            self.search_pill.setText(f"搜到 {len(rows)} / {total} 条")
            self.search_pill.setVisible(True)
        else:
            self.search_pill.setText("")
            self.search_pill.setVisible(False)

        if view.rows:
            self.rows_note.setText(
                f"共 {total} 条明细，各条次数合计 {view.detail_total} 次。"
                + ("" if not self._keyword.strip() else "（当前是搜索后的结果）"))
        else:
            self.rows_note.setText("这份报告没有明细条目。")
        self.rows_note.setVisible(True)

    def _fill_libraries(self, view) -> None:
        libs = view.libraries
        tb = self.lib_table
        tb.setRowCount(len(libs))
        for i, lib in enumerate(libs):
            texts = (lib.name, lib.detail,
                     "—" if lib.applied_rules is None else str(lib.applied_rules),
                     "—" if lib.unique_rules is None else str(lib.unique_rules),
                     "—" if lib.extracted_entries is None else str(lib.extracted_entries))
            for col, text in enumerate(texts):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                tb.setItem(i, col, item)
        tb.setVisible(bool(libs))
        self.lib_note.setText(view.library_hits_note or (
            "报告没有分列各词库各命中多少次，所以这里只给规则条数。"
            if libs else "这份报告没有列词库。"))
        self.lib_note.setVisible(True)

    def _fill_issues(self, view) -> None:
        self._clear(self.issues_box)
        items = view.issues
        self.issues_card.setVisible(bool(items) or bool(view.notes))
        for issue in items:
            row = QHBoxLayout()
            row.setSpacing(8)
            kind = "warn" if issue.is_warning else "info"
            row.addWidget(Pill("需要留意" if issue.is_warning else "说明", kind),
                          0, Qt.AlignmentFlag.AlignTop)
            text = _muted(issue.text)
            if issue.line_no:
                text.setText(f"（第 {issue.line_no} 行）{issue.text}")
            row.addWidget(text, 1)
            self.issues_box.addLayout(row)
        for note in view.notes:
            if not str(note).strip():
                continue
            lab = _muted(str(note))
            self.issues_box.addWidget(lab)

    # -- 事件 ---------------------------------------------------------------

    def _on_search(self, text: str) -> None:
        self._keyword = text or ""
        if self.view.ok_to_show:
            self._fill_rows(self.view)
