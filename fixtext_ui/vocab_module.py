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

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialog,
    QLineEdit, QComboBox, QCheckBox, QFrame, QSizePolicy, QScrollArea,
)

import fixtext_settings as app_settings
from fixtext_tokens import c, fs, r, FONT_WEIGHT, FONT_MONO, ICON_GLYPH_SIZE
from fixtext_widgets import Card, Pill, hline, ConfirmDialog, Modal, page_head_shell, PrimaryButton

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
        # 存储位置由设置页决定（未配置时 None = 包内默认树）
        self.store = VocabStore(custom_path=app_settings.vocab_custom_file())

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

        self._build_status(root)

        self._snap_card.setVisible(False)
        self._render_all()

    # ------------------------------------------------------------------ 头部

    def _header(self) -> QWidget:
        shell, body = page_head_shell()
        hl = QHBoxLayout(body)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        col = QVBoxLayout()
        col.setSpacing(2)
        title = _label("词库管理", size="2xl", color="neutral.900", weight="bold")
        title.setObjectName("PageTitle")
        sub = _label(
            "新增、检索、查重、合并、删除词条，并安全维护你的校正词库。",
            size="md", color="neutral.600", wrap=True)
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
        # QLabel 背景必须 WA_StyledBackground；内联与 QSS 双保险（防「重新生成」漏项）
        safe.setStyleSheet(
            f"QLabel#SafeBadge{{color:{c('success')};background:{c('success.bg')};"
            f"border:1px solid {c('success.border')};border-radius:{r('full')};"
            f"padding:6px 12px;font-size:{fs('xs')};font-weight:700}}")
        right.addWidget(safe)

        self.hist_btn = self._head_icon_btn("🕑", "历史与快照",
                                            lambda: self._snap_card.setVisible(
                                                not self._snap_card.isVisible()))
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
        self._snap_card = self._snap_card()
        col.addWidget(self._snap_card, 0)
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

        bar = QWidget()
        bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)

        add = PrimaryButton("＋ 新增词条")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(self.open_add)
        bl.addWidget(add)

        self._search = QLineEdit()
        self._search.setObjectName("Search")
        self._search.setPlaceholderText("检索词或替换值…（双向）")
        self._search.setMinimumWidth(200)
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
        # 列表区吃竖直剩余空间；空态也不反向撑工具条
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        self._table = QWidget()
        self._table.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
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
        """「历史与快照」面板（对齐原型 ``#historyPanel`` 的面板头）。

        面板头左边是标题、右边是「恢复默认词库」按钮（原型同一位置、同一文案）；
        面板体分两段：上面是时间线（``renderSnaps`` 的 1:1 移植），下面是
        操作历史（每次变更的时间点 + 摘要）。两段都只显示人话，不出现路径。
        """
        card = Card(basis="底线② 自动快照 · 可恢复")
        self.basis_labels.append(card.basis)
        card.body_l.setSpacing(10)

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        hl.addWidget(_label("历史与快照", size="base", color="neutral.800", weight="semibold"))
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
        wrap = QWidget()
        wrap.setLayout(self._snap_list)
        card.body_l.addWidget(wrap)

        # ---- 操作历史 ----
        op_head = QHBoxLayout()
        op_head.setContentsMargins(0, 8, 0, 0)
        op_head.setSpacing(8)
        op_head.addWidget(_label("操作历史", size="sm", color="neutral.800", weight="semibold"))
        self._op_summary = _label("", size="xs", color="neutral.500")
        op_head.addWidget(self._op_summary)
        op_head.addStretch(1)
        self._op_toggle = _link_btn("展开全部")
        self._op_toggle.clicked.connect(self._toggle_ops)
        op_head.addWidget(self._op_toggle)
        body_w = QWidget()
        body_w.setLayout(op_head)
        card.body_l.addWidget(body_w)

        self._ops_expanded = False
        self._op_list = QVBoxLayout()
        self._op_list.setSpacing(0)
        ops_wrap = QWidget()
        ops_wrap.setLayout(self._op_list)
        card.body_l.addWidget(ops_wrap)
        return card

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

    @staticmethod
    def _clear_layout(lay: QVBoxLayout):
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _render_snaps(self):
        """时间线：1:1 移植原型 ``renderSnaps()``。

        原型语义逐条对齐：
        * 最新一个在前，圆点高亮 + 时间后面带「· 当前」，且不显示「恢复到此」；
        * 其余每个时间点都带「恢复到此」链接；
        * 一条记录都没有时，给空状态说明（不写任何内部概念）。
        """
        self._clear_layout(self._snap_list)
        records = self.store.timeline(limit=12)
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
            return

        for i, rec in enumerate(records):
            cur = bool(rec.get("is_current"))
            item = QWidget()
            item.setObjectName("SnapItem")
            # 分隔线交给 fixtext.qss 的 #SnapItem（原内联收归）
            hl = QHBoxLayout(item)
            hl.setContentsMargins(2, 10, 2, 10)
            hl.setSpacing(10)
            dot = QLabel()
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(
                f"background:{c('success') if cur else c('neutral.200')};"
                + (f"border:3px solid {c('success.bg')};" if cur else "")
                + "border-radius:999px")
            hl.addWidget(dot)
            hl.addWidget(_label(rec["label"], size="sm", weight="semibold",
                                color="neutral.800"), 0)
            hl.addStretch(1)
            txt = rec.get("time", "")
            hl.addWidget(_label(f"{txt} · 当前" if cur else txt, size="xs",
                                color="neutral.500"))
            if not cur:
                b = _link_btn("恢复到此")
                b.setToolTip(f"回到 {rec.get('time', '')} 这一刻的词库内容")
                b.clicked.connect(lambda _c, pid=int(rec["id"]): self.restore_point(pid))
                hl.addWidget(b)
            self._snap_list.addWidget(item)

    def _toggle_ops(self):
        self._ops_expanded = not self._ops_expanded
        self._op_toggle.setText("收起" if self._ops_expanded else "展开全部")
        self._render_ops()

    def _render_ops(self):
        """操作历史：每次变更的时间点 + 摘要，与时间点恢复联动。

        「联动」体现在每行右侧的「回到这里」——点了就是「恢复到该行那次变更
        完成后的状态」，与时间线上同名时间点是同一个动作、同一份数据。
        """
        self._clear_layout(self._op_list)
        total = self.store.op_count()
        limit = 30 if self._ops_expanded else 6
        rows = self.store.ops(limit=limit)
        self._op_toggle.setVisible(total > 6)
        self._op_toggle.setText("收起" if self._ops_expanded else "展开全部")
        self._op_summary.setText(f"共 {_fmt_num(total)} 次变更" if total else "")
        if not rows:
            lab = _label("还没有操作记录。每次改动都会记下时间与内容，可随时回到某个时间点。",
                         size="xs", color="neutral.500", wrap=True)
            lab.setContentsMargins(0, 6, 0, 2)
            self._op_list.addWidget(lab)
            return

        current_pid = self.store.current_point_id()

        for op in rows:
            item = QWidget()
            hl = QHBoxLayout(item)
            hl.setContentsMargins(0, 8, 0, 8)
            hl.setSpacing(10)
            hl.addWidget(_label(op.get("time", ""), size="xs", color="neutral.500"))
            pill = QLabel(op.get("act_name", "变更"))
            pill.setStyleSheet(
                f"background:{c('neutral.100')};color:{c('neutral.700')};"
                f"border-radius:6px;padding:2px 8px;font-size:{fs('xs')}")
            hl.addWidget(pill)
            hl.addWidget(_label(op.get("summary", ""), size="sm", color="neutral.800"), 0)
            hl.addStretch(1)
            pid = int(op.get("point_id") or 0)
            if pid and pid != current_pid:
                b = _link_btn("回到这里")
                b.setToolTip(f"把词库恢复到 {op.get('time', '')} 这次变更之后")
                b.clicked.connect(lambda _c, p=pid: self.restore_point(p))
                hl.addWidget(b)
            elif pid and pid == current_pid:
                hl.addWidget(_label("当前", size="xs", color="success"))
            self._op_list.addWidget(item)

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

        holder = QWidget()
        hv = QVBoxLayout(holder)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(8)
        for gi, g in enumerate(groups, start=1):
            box = QFrame()
            box.setObjectName("DupGroup")
            box.setStyleSheet(
                f"QFrame#DupGroup{{border:1px solid {c('neutral.200')};border-radius:10px;"
                f"background:{c('neutral.50')};padding:12px 14px;margin-top:6px}}")
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
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(2, 0, 2, 4)
        hl.setSpacing(10)
        for txt, stretch in (("加入", 0), ("词条", 3), ("类型", 1),
                             ("替换值", 3), ("出现次数", 1)):
            hl.addWidget(_label(txt, size="xs", color="neutral.600",
                                weight="semibold"), stretch)
        rows.addWidget(head)
        rows.addWidget(hline())
        for i, w in enumerate(self._book_words):
            rw = QWidget()
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(2, 5, 2, 5)
            rl.setSpacing(10)
            cb = QCheckBox()
            cb.setChecked(True)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            cb.toggled.connect(self._book_sync_pick_label)
            checks.append(cb)
            rl.addWidget(cb, 0)
            rl.addWidget(_label(w.get("word") or "", size="xs",
                                color="neutral.900", weight="bold", mono=True), 3)
            rl.addWidget(_label(w.get("type") or "专有名词", size="xs",
                                color="neutral.600"), 1)
            rl.addWidget(_label(w.get("value") or w.get("word") or "", size="xs",
                                color="neutral.700", mono=True), 3)
            rl.addWidget(_label(f"{int(w.get('count') or 1)} 次", size="xs",
                                color="neutral.500", mono=True), 1)
            rows.addWidget(rw)
            if i != len(self._book_words) - 1:
                rows.addWidget(hline())
        rows_box = QWidget()
        rows_box.setLayout(rows)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setMinimumHeight(320)
        area.setMaximumHeight(420)
        area.setWidget(rows_box)
        area.setStyleSheet(
            f"QScrollArea{{border:1px solid {c('neutral.200')};"
            f"border-radius:10px;background:{c('neutral.0')}}}")
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

    def _build_status(self, root: QVBoxLayout):
        self.status_box = QWidget()
        sl = QHBoxLayout(self.status_box)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(12)
        self.status = QLabel("")
        self.status.setObjectName("Toast")
        self.status.setStyleSheet(
            f"#Toast{{background:{c('neutral.800')};color:{c('on.fill')};"
            f"border-radius:10px;padding:10px 16px;font-size:{fs('sm')}}}")
        self.status.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.undo_btn = QPushButton("撤销")
        self.undo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.undo_btn.setStyleSheet(
            f"QPushButton{{background:{c('primary.500')};color:{c('on.fill')};border:none;"
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
