"""
FixText V1 · 词库管理模块（Qt 移植 · M3-T3.1 接真实词库）
=========================================================

对照 `FixText_V1_词库管理_原型.html` **1:1 移植**，控件语义与文案逐条对齐。

结构（页头 → 本书专有词库横幅 → 左侧词库分级 + 右侧工作区）：
- 页头：标题 / 副标题 / 「显示设计依据」开关 / 分级切换（全部·自定义·内置）
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

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialog,
    QLineEdit, QComboBox, QCheckBox, QFrame, QSizePolicy,
)

from fixtext_tokens import c, fs, r, FONT_WEIGHT, FONT_MONO
from fixtext_widgets import Card, Pill, hline, ConfirmDialog, Modal

from fixtext_vocab import (
    ENTRY_TYPES, TIER_NAMES, TIER_ORDER, VocabDataError, VocabStore,
)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 词库表格每页条数（内置词库 30 万条，翻页而不是截断）
PAGE_SIZE = 40

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
           mono: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(wrap)
    style = f"color:{c(color)};font-size:{fs(size)};background:transparent;"
    if weight:
        style += f"font-weight:{FONT_WEIGHT[weight]};"
    if mono:
        style += f"font-family:{FONT_MONO};"
    lab.setStyleSheet(style)
    return lab


def _link_btn(text: str, *, danger: bool = False, enabled: bool = True) -> QPushButton:
    """行内文字按钮（编辑 / 删除）：透明底、主色或危险色、hover 反白。"""
    btn = QPushButton(text)
    kind = "LinkBtnDel" if danger else "LinkBtn"
    btn.setObjectName(kind)
    fg = c("error") if danger else c("primary.700")
    hover_bg = c("error.bg") if danger else c("primary.100")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton#{kind}{{background:transparent;border:none;color:{fg};"
        f"font-weight:600;font-size:{fs('xs')};padding:4px 6px;border-radius:6px}}"
        f"QPushButton#{kind}:hover{{background:{hover_bg}}}")
    if not enabled:
        btn.setEnabled(False)
    return btn


def _mini_table(headers: list, rows: list, *, mono_cols: set | None = None) -> QWidget:
    """弹窗里的小表格（纯 QWidget 拼，样式沿用卡片感）。"""
    mono_cols = mono_cols or set()
    box = QFrame()
    box.setObjectName("MiniTable")
    box.setStyleSheet(
        f"QFrame#MiniTable{{border:1px solid {c('neutral.200')};"
        f"border-radius:10px;background:{c('neutral.0')}}}")
    vl = QVBoxLayout(box)
    vl.setContentsMargins(12, 10, 12, 10)
    vl.setSpacing(0)

    head = QWidget()
    hl = QHBoxLayout(head)
    hl.setContentsMargins(0, 0, 0, 6)
    hl.setSpacing(10)
    for h in headers:
        hl.addWidget(_label(h, size="xs", color="neutral.600", weight="semibold"), 1)
    vl.addWidget(head)
    vl.addWidget(hline())

    if not rows:
        vl.addWidget(_label("（无）", size="xs", color="neutral.500"))
        return box

    for i, row in enumerate(rows):
        rw = QWidget()
        rl = QHBoxLayout(rw)
        rl.setContentsMargins(0, 7, 0, 7)
        rl.setSpacing(10)
        for j, cell in enumerate(row):
            rl.addWidget(_label(str(cell), size="xs", color="neutral.800",
                                mono=(j in mono_cols), wrap=True), 1)
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
        self.store = VocabStore()

        # ---- 状态 ----
        self.tier = "all"          # all / custom / builtin
        self.dict_ = "custom"      # custom / all / b1 / b2 / b3
        self.search = ""
        self._page = 0
        self._hit_total = 0
        self._page_rows: list = []
        self._selected: set = set()
        self._pending_add: dict | None = None
        self._merge_sel: list | None = None
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
        root.addWidget(self._banner())
        root.addWidget(self._layout_grid())

        self.legend = _label(
            "勾选「显示设计依据」可看到每个界面元素对应的文档条款。新增 / 查重 / 删除 / 合并"
            "与本书专有词均受五条安全底线约束。",
            size="xs", color="neutral.500", wrap=True)
        root.addWidget(self.legend)

        self._build_status(root)

        self._snap_card.setVisible(False)
        self._render_all()

    # ------------------------------------------------------------------ 头部

    def _header(self) -> QWidget:
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(_label("词库管理", size="2xl", color="neutral.900", weight="bold"))
        col.addWidget(_label(
            "新增、检索、查重、合并、删除词条，并安全维护你的校正词库。",
            size="md", color="neutral.600", wrap=True))
        hl.addLayout(col, 1)

        right = QHBoxLayout()
        right.setSpacing(14)
        right.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.basis_cb = QCheckBox("显示设计依据")
        self.basis_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.basis_cb.toggled.connect(self._toggle_basis)
        right.addWidget(self.basis_cb)

        self._tier_btns = {}
        seg = QWidget()
        seg.setObjectName("TierTabs")
        seg.setStyleSheet(
            f"QWidget#TierTabs{{background:{c('neutral.100')};border-radius:{r('full')};padding:3px}}")
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

        self._snap_toggle = QPushButton("🕑 快照")
        self._snap_toggle.setObjectName("BtnOutline")
        self._snap_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._snap_toggle.clicked.connect(
            lambda: self._snap_card.setVisible(not self._snap_card.isVisible()))
        right.addWidget(self._snap_toggle)

        hl.addLayout(right)
        self._set_tier_active("all")
        return w

    def _set_tier_active(self, t: str):
        for key, b in self._tier_btns.items():
            on = (key == t)
            # Qt 样式表没有 cursor / box-shadow：选中态改用描边表达层级
            b.setStyleSheet(
                f"QPushButton#TierTab{{border-radius:{r('full')};padding:6px 15px;"
                f"font-weight:600;font-size:{fs('sm')};"
                f"background:{'#fff' if on else 'transparent'};"
                f"color:{c('primary.700') if on else c('neutral.600')};"
                + (f"border:1px solid {c('neutral.200')};" if on else "border:none;")
                + "}"
                f"QPushButton#TierTab:hover{{background:{'#fff' if on else c('neutral.50')}}}")

    # -------------------------------------------------- 本书专有词库横幅（2.4.2）

    def _banner(self) -> QWidget:
        self._banner_w = QWidget()
        self._banner_w.setObjectName("Banner")
        self._banner_w.setStyleSheet(
            f"QWidget#Banner{{background:{c('primary.50')};border:1px solid {c('primary.100')};"
            f"border-radius:{r('lg')};padding:14px 18px}}")
        hl = QHBoxLayout(self._banner_w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(14)
        ico = QLabel("✨")
        ico.setFixedSize(38, 38)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background:{c('primary.500')};color:#fff;border-radius:10px;font-size:18px")
        hl.addWidget(ico)
        txt = QVBoxLayout()
        txt.setSpacing(2)
        self._banner_title = _label("", size="base", weight="bold", color="neutral.900")
        txt.addWidget(self._banner_title)
        txt.addWidget(_label("是否把它们加入你的自定义词库？加入后，下次校正同类错误将自动生效。",
                             size="sm", color="neutral.500"))
        hl.addLayout(txt, 1)
        add = QPushButton("查看并加入")
        add.setObjectName("BtnPrimary")
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
        ico = QLabel("✎" if d == "custom" else ("📕" if d == "b1" else "📗" if d == "b2" else "📘"))
        ico.setFixedSize(22, 22)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background:{c('success.bg') if d=='custom' else c('info.bg')};"
            f"border-radius:6px;font-size:12px")
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
            f"color:{'transparent' if d=='custom' else c('neutral.500')};font-size:12px")
        hl.addWidget(lock)
        item.mousePressEvent = lambda e, d=d: self.select_dict(d)
        return item

    def counts(self) -> dict:
        return self.store.counts()

    def _set_dict_active(self, d: str):
        counts = self.counts()
        for key, item in self._dict_items.items():
            on = (key == d)
            item.setStyleSheet(
                f"QWidget#DictItem{{border:1px solid {c('primary.500') if on else c('neutral.200')};"
                f"border-radius:{r('md')};background:{c('primary.50') if on else c('neutral.0')}}}")
            item._meta.setText(
                f"{_fmt_num(counts.get(key, 0))} 条 · {'可编辑' if key=='custom' else '只读'}")

    # ----- 右侧工作区 -----

    def _workspace(self) -> QWidget:
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(16)
        col.addWidget(self._toolbar())
        col.addWidget(self._table_card())
        self._snap_card = self._snap_card()
        col.addWidget(self._snap_card)
        w = QWidget()
        w.setLayout(col)
        return w

    # ----- 工具条（§2.4.1 五操作）-----

    def _toolbar(self) -> Card:
        card = Card(basis="§2.4.1 五操作 · 新增为 V1 补入")
        self.basis_labels.append(card.basis)
        card.body_l.setSpacing(10)

        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)

        add = QPushButton("＋ 新增词条")
        add.setObjectName("BtnPrimary")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(self.open_add)
        bl.addWidget(add)

        self._search = QLineEdit()
        self._search.setPlaceholderText("检索词或替换值…（双向）")
        self._search.setMinimumWidth(200)
        self._search.setStyleSheet(
            f"QLineEdit{{background:{c('neutral.50')};border:1px solid {c('neutral.200')};"
            f"border-radius:{r('md')};padding:8px 12px;font-size:{fs('base')};color:{c('neutral.800')}}}"
            f"QLineEdit:focus{{border-color:{c('primary.500')};border-width:2px}}")
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

        self._sel_count = _label("未选择", size="xs", color="neutral.500")
        bl.addWidget(self._sel_count)
        card.body_l.addWidget(bar)

        self._hint = _label("", size="xs", color="neutral.500", wrap=True)
        self._hint.setVisible(False)
        card.body_l.addWidget(self._hint)
        return card

    # ----- 词条表格（底线③ 结构化表格 · 不露内部文件格式）-----

    def _table_card(self) -> Card:
        card = Card(basis="底线③ 结构化表格 · 不露内部文件格式")
        self.basis_labels.append(card.basis)
        card.body_l.setSpacing(0)

        self._table = QWidget()
        self._table_body = QVBoxLayout(self._table)
        self._table_body.setContentsMargins(0, 0, 0, 0)
        self._table_body.setSpacing(0)
        card.body_l.addWidget(self._table)

        self._render_entries()
        return card

    def _entry_header(self) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 10, 0, 10)
        hl.setSpacing(12)
        self._chk_all = QCheckBox()
        self._chk_all.stateChanged.connect(self._toggle_all)
        hl.addWidget(self._chk_all, 0)
        hl.addSpacing(COL_CHECK_W - 34)
        for text, stretch in (("原词", 3), ("替换为", 3), ("类型", 2), ("来源", 2), ("命中书籍", 3)):
            lab = _label(text, size="xs", color="neutral.600", weight="semibold")
            hl.addWidget(lab, stretch)
        act = _label("操作", size="xs", color="neutral.600", weight="semibold")
        act.setAlignment(Qt.AlignmentFlag.AlignRight)
        hl.addWidget(act, 0)
        return row

    def _entry_row(self, e: dict) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 12, 0, 12)
        hl.setSpacing(12)

        is_builtin = e.get("tier") == "builtin"
        chk = QCheckBox()
        chk.setChecked(e["id"] in self._selected)
        chk.setEnabled(not is_builtin)          # 内置只读，不给勾选框假希望
        chk.stateChanged.connect(lambda s, i=e["id"]: self._toggle_row(i, s))
        hl.addWidget(chk, 0)

        word_col = QVBoxLayout()
        word_col.setSpacing(1)
        word_col.addWidget(_label(e["word"], size="sm", weight="bold",
                                   color="neutral.900", mono=True))
        if e.get("pinyin"):
            word_col.addWidget(_label(f"/{e['pinyin']}", size="xs",
                                      color="neutral.500", mono=True))
        wbox = QWidget()
        wbox.setLayout(word_col)
        hl.addWidget(wbox, 3)

        hl.addWidget(_label(e["value"], size="sm", color="primary.700", mono=True), 3)
        hl.addWidget(_label(e.get("type") or "—", size="sm", color="neutral.600"), 2)

        hl.addWidget(Pill("自定义" if not is_builtin else "内置",
                          "ok" if not is_builtin else "info"), 2)

        books = ("📖 " + "、".join(e["books"])) if e.get("books") else "—"
        bk = _label(books, size="xs", color="neutral.600")
        bk.setWordWrap(True)
        hl.addWidget(bk, 3)

        acts = QWidget()
        al = QHBoxLayout(acts)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        al.addStretch(1)
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
        row = QWidget()
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

    # ----- 历史与快照（底线② 自动快照 · 可恢复）-----

    def _snap_card(self) -> Card:
        card = Card("历史与快照", basis="底线② 自动快照 · 可恢复")
        self.basis_labels.append(card.basis)
        card.body_l.setSpacing(10)

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        hl.addStretch(1)
        restore = QPushButton("↺ 恢复默认词库（保留自定义）")
        restore.setObjectName("BtnGhost")
        restore.setCursor(Qt.CursorShape.PointingHandCursor)
        restore.clicked.connect(self.restore_default)
        hl.addWidget(restore)
        card.body_l.addWidget(head)

        self._snap_list = QVBoxLayout()
        wrap = QWidget()
        wrap.setLayout(self._snap_list)
        card.body_l.addWidget(wrap)
        return card

    # ------------------------------------------------------------------ 渲染

    def _scope(self) -> str:
        """当前选择折算成数据层的检索范围。"""
        if self.dict_ == "custom":
            return "custom"
        if self.dict_ in ("b1", "b2", "b3"):
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
        while self._table_body.count():
            item = self._table_body.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

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

        self._table_body.addWidget(self._entry_header())
        self._table_body.addWidget(hline())

        if not rows:
            self._table_body.addWidget(self._empty_state())
            return

        for i, e in enumerate(rows):
            self._table_body.addWidget(self._entry_row(e))
            if i != len(rows) - 1:
                self._table_body.addWidget(hline())
        self._table_body.addWidget(hline())
        self._table_body.addWidget(self._pager())
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

    def _render_snaps(self):
        while self._snap_list.count():
            item = self._snap_list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        records = self.store.history()
        if not records:
            empty = _label("暂无变更记录（新增 / 编辑 / 删除 / 合并都会自动留一份）",
                           size="xs", color="neutral.500")
            empty.setContentsMargins(0, 4, 0, 4)
            self._snap_list.addWidget(empty)
            return
        for i, s in enumerate(records):
            item = QWidget()
            hl = QHBoxLayout(item)
            hl.setContentsMargins(0, 10, 0, 10)
            hl.setSpacing(10)
            dot = QLabel()
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(
                f"background:{c('success') if i == 0 else c('neutral.200')};"
                + ("border:3px solid %s;" % c("success.bg") if i == 0 else "")
                + "border-radius:999px")
            hl.addWidget(dot)
            hl.addWidget(_label(s["label"], size="sm", color="neutral.800"))
            hl.addStretch(1)
            hl.addWidget(_label(s.get("time", ""), size="xs", color="neutral.500"))
            b = _link_btn("恢复到此")
            b.clicked.connect(lambda _c, idx=i: self.restore_snap(idx))
            hl.addWidget(b)
            self._snap_list.addWidget(item)

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

    def _toggle_row(self, i: int, state: int):
        if state:
            self._selected.add(i)
        else:
            self._selected.discard(i)
        self._update_sel_state()

    def _toggle_all(self, state: int):
        for e in self._page_rows:
            if not self._is_custom(e["id"]):
                continue
            if state:
                self._selected.add(e["id"])
            else:
                self._selected.discard(e["id"])
        self._render_entries()
        self._update_sel_state()

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
        self._toast("已撤销上一步操作", with_undo=False)

    def restore_snap(self, idx: int):
        """按「历史与快照」里的真实记录把自定义词库原字节回写。"""
        rec = self.store.undo_to(idx)
        if not rec:
            self._toast("这份记录已无法恢复")
            return
        self._selected = {i for i in self._selected if self._by_id(i)}
        self._render_all()
        self._toast("已恢复到所选记录", with_undo=False)

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
        groups = self.store.dup_groups()
        if not groups:
            self._toast("未发现重复词条")
            return groups
        m = Modal(icon="🔁", title="查重结果（先预览，确认后处理）", parent=self)
        m.add_note("底线④：查重结果先给预览清单，确认后才执行；处理动作可撤销。", "warn")
        for g in groups[:20]:
            box = QFrame()
            box.setObjectName("DupGroup")
            box.setStyleSheet(
                f"QFrame#DupGroup{{border:1px solid {c('neutral.200')};border-radius:10px;"
                f"background:{c('neutral.50')};padding:12px 14px;margin-top:6px}}")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(8)
            bl.addWidget(_label(f"{g['kind']}：{g['key']}", size="sm",
                                color="warning", weight="bold"))
            bl.addWidget(_mini_table(
                ["原词", "替换为", "来源"],
                [(row["word"], row["value"], TIER_NAMES[row["dict"]]) for row in g["items"]],
                mono_cols={0, 1}))
            m.add_widget(box)
        if len(groups) > 20:
            m.add_note(f"重复分组较多，这里只列出前 20 组（共 {len(groups)} 组）。", "info")
        m.add_widget(_label("建议合并同词不同值冲突，或保留其一。可撤销，请放心处理。",
                            size="sm", color="neutral.500"))
        m.add_foot("暂时不处理", "ghost", m.reject)
        m.add_foot("我知道了", "primary", m.accept)
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
        if not self._book_words:
            self._toast("还没有可加入的本书专有词条")
            return
        m = Modal(icon="✨", title="本书专有词条（加入预览）", parent=self)
        m.add_note("加入前有预览，可逐条或整组确认；加入后下次校正自动生效。", "info")
        checks = []
        rows = QVBoxLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(4)
        for w in self._book_words:
            rw = QWidget()
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(10)
            cb = QCheckBox()
            cb.setChecked(True)
            checks.append(cb)
            rl.addWidget(cb)
            rl.addWidget(_label(w["word"], size="sm", weight="bold",
                                color="neutral.900", mono=True), 0)
            rl.addWidget(_label(w.get("note") or "", size="xs",
                                color="neutral.500"), 1)
            rows.addWidget(rw)
        self._book_checks = checks
        rows_box = QWidget()
        rows_box.setLayout(rows)
        m.add_widget(rows_box)
        m.add_foot("取消", "ghost", m.reject)
        m.add_foot("加入选中词条到「我的词库」", "primary",
                   lambda: self.add_book_words(m))
        m.show()

    def add_book_words(self, modal: Modal) -> int:
        added = 0
        for i, cb in enumerate(self._book_checks or []):
            if not cb.isChecked():
                continue
            w = self._book_words[i]
            word = w["word"]
            value = w.get("value") or word
            if self.store.conflicts_for_add(word, value):
                continue           # 已在词库里就不再重复写入
            try:
                self.store.add_entry(word=word, value=value, typ="专有名词",
                                     book=self._book_title)
            except VocabDataError:
                continue
            added += 1
        self.hide_banner()
        modal.accept()
        self._render_all()
        self._toast(f"已加入 {added} 条专有词条到「我的词库」", with_undo=added > 0)
        return added

    # ------------------------------------------------------------------ 恢复默认（底线⑤）

    def restore_default(self):
        """只重置内置词库；自定义词条原样保留（内置本来只读，这里做完整性自检 + 说明）。"""
        d = ConfirmDialog(
            icon="↺", title="恢复默认词库",
            note="底线⑤：恢复默认词库只重置内置词库，不影响你的自定义词条。",
            confirm_text="确认恢复", confirm_kind="primary", parent=self)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        ok, detail = self.store.builtin.self_check() if hasattr(
            self.store.builtin, "self_check") else (self.store.builtin.available, "")
        self._render_all()
        if ok:
            self._toast(f"内置词库已校验完整，自定义词条保留（{_fmt_num(len(self.store.custom))} 条）")
        else:
            self._toast(f"内置词库不完整：{detail}")

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

    def _toggle_basis(self, on: bool):
        alive = []
        for b in self.basis_labels:
            try:
                b.setVisible(bool(on))
                alive.append(b)
            except RuntimeError:
                pass
        self.basis_labels = alive

    def _build_status(self, root: QVBoxLayout):
        self.status_box = QWidget()
        sl = QHBoxLayout(self.status_box)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(12)
        self.status = QLabel("")
        self.status.setObjectName("Toast")
        self.status.setStyleSheet(
            f"#Toast{{background:{c('neutral.800')};color:#fff;"
            f"border-radius:10px;padding:10px 16px;font-size:{fs('sm')}}}")
        self.status.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.undo_btn = QPushButton("撤销")
        self.undo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.undo_btn.setStyleSheet(
            f"QPushButton{{background:{c('primary.500')};color:#fff;border:none;"
            f"padding:6px 12px;border-radius:7px;font-weight:700;font-size:{fs('sm')}}}"
            f"QPushButton:hover{{background:{c('primary.600')}}}")
        self.undo_btn.clicked.connect(self._undo)
        sl.addWidget(self.status)
        sl.addWidget(self.undo_btn)
        self.status_box.setVisible(False)
        root.addWidget(self.status_box, 0, Qt.AlignmentFlag.AlignLeft)

    def _toast(self, msg: str, with_undo: bool = False):
        self.status.setText(msg)
        self.undo_btn.setVisible(with_undo)
        self.status_box.setVisible(True)
        self._toast_timer.start(5000 if with_undo else 2600)

    def _hide_status(self):
        self.status_box.setVisible(False)
