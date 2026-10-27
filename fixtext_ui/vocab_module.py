"""
FixText V1 · 词库管理模块（Qt 移植）
====================================

对照更新后的 `FixText_V1_词库管理_原型.html` **1:1 移植**。

结构（页头 → 本书专有词库横幅 → 左侧词库分级 + 右侧工作区）：
- 页头：标题 / 副标题 / 「显示设计依据」开关 / 分级切换（全部·自定义·内置）
- 本书专有词库横幅（2.4.2）：发现专有词条 → 查看并加入 / 稍后
- 左侧词库分级（底线③ 文件不暴露 · 友好名）：我的词库（可编辑）+ 3 内置（只读）
- 右侧工作区：
  · 工具条（§2.4.1 五操作）：新增 / 检索 / 查重 / 合并 / 删除选中 / 展开核对 / 选择计数
  · 词条表格（底线③ 结构化表格 · 不露内部文件格式）：选择 / 原词 / 替换为 / 类型 / 来源 / 命中书籍 / 操作
  · 历史与快照面板（底线② 自动快照 · 可恢复，默认隐藏）

产品规则（逐条对应原型标注）：
- 五操作（§2.4.1）：新增 / 检索 / 查重 / 删除 / 合并；写入与批量动作先预览再二次确认（底线④）。
- 文件不暴露（底线③）：用友好名，结果以结构化表格呈现，不露内部文件格式。
- 自动快照（底线②）：每次变更前自动快照，可恢复到任一时间点；恢复默认词库仅重置内置、保留自定义（底线⑤）。
- 撤销（底线①）：所有写动作可撤销，toast 内「撤销」入口 + Ctrl+Z。
- 条款号一律收进「显示设计依据」，正文不露 §。
"""

from __future__ import annotations

import copy

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialog,
    QLineEdit, QComboBox, QCheckBox, QScrollArea, QFrame,
    QSizePolicy, QApplication,
)

from fixtext_tokens import c, fs, r, sp, FONT_WEIGHT, FONT_MONO
from fixtext_widgets import Card, Pill, hline, ConfirmDialog, Modal


# ---------------------------------------------------------------------------
# 数据（与 HTML 原型同源）
# ---------------------------------------------------------------------------

ENTRY_TYPES = ["错词校正", "角色名", "专有名词", "其他"]

DICT_NAMES = {
    "custom": "我的词库",
    "b1": "常规校正词库",
    "b2": "标点规范词库",
    "b3": "繁简转换词库",
}

DICT_ORDER = ["custom", "b1", "b2", "b3"]


def _seed_builtin() -> list:
    """内置词库出厂种子（只读，可被「恢复默认词库」重置）。"""
    return [
        dict(id=11, word="好象", value="好像", type="错词校正", pinyin="", dict="b1", tier="builtin", books=[]),
        dict(id=12, word="做为一个", value="作为一个", type="错词校正", pinyin="", dict="b1", tier="builtin", books=[]),
        dict(id=13, word="他门", value="他们", type="错词校正", pinyin="", dict="b1", tier="builtin", books=[]),
        dict(id=14, word="在次", value="再次", type="错词校正", pinyin="", dict="b1", tier="builtin", books=[]),
        dict(id=21, word="“", value="“", type="其他", pinyin="", dict="b2", tier="builtin", books=[]),
        dict(id=22, word="''", value="“”,", type="其他", pinyin="", dict="b2", tier="builtin", books=[]),
        dict(id=31, word="網", value="网", type="其他", pinyin="", dict="b3", tier="builtin", books=[]),
        dict(id=32, word="國", value="国", type="其他", pinyin="", dict="b3", tier="builtin", books=[]),
        dict(id=33, word="對", value="对", type="其他", pinyin="", dict="b3", tier="builtin", books=[]),
    ]


def _seed_custom() -> list:
    return [
        dict(id=1, word="星河彼端", value="星河彼岸", type="专有名词", pinyin="", dict="custom", tier="custom", books=["《星河彼端》"]),
        dict(id=2, word="绯红之翼", value="绯红之翌", type="专有名词", pinyin="", dict="custom", tier="custom", books=["《绯红之翼》", "《黎明誓约》"]),
        dict(id=3, word="萧衍", value="萧彦", type="角色名", pinyin="xiāo yàn", dict="custom", tier="custom", books=["《九域志》"]),
        dict(id=4, word="地煞", value="第煞", type="错词校正", pinyin="", dict="custom", tier="custom", books=[]),
        dict(id=5, word="玄机阁", value="悬机阁", type="专有名词", pinyin="", dict="custom", tier="custom", books=["《玄机阁秘录》"]),
    ]


# 本书专有词条（2.4.2）：校正完成后发现的待加入条目
BOOK_WORDS = [
    dict(word="星陨大陆", value="星陨大陆", note="本书专有地名"),
    dict(word="墨羽", value="墨羽", note="角色名"),
    dict(word="九转玄功", value="九转玄功", note="功法名"),
]


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

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
        btn.setStyleSheet(
            f"QPushButton#{kind}{{background:transparent;border:none;"
            f"color:{c('neutral.300')};font-weight:600;font-size:{fs('xs')};"
            f"padding:4px 6px;border-radius:6px}}")
    return btn


def _mini_table(headers: list, rows: list, *, mono_cols: set | None = None) -> QWidget:
    """只读小表格（删除预览 / 查重 / 展开核对共用）。"""
    mono_cols = mono_cols or set()
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    head = QWidget()
    hl = QHBoxLayout(head)
    hl.setContentsMargins(0, 0, 0, 0)
    for h in headers:
        lab = _label(h, size="xs", color="neutral.600", weight="semibold")
        hl.addWidget(lab, 1)
    v.addWidget(head)
    v.addWidget(hline("neutral.200"))
    for row in rows:
        rw = QWidget()
        rl = QHBoxLayout(rw)
        rl.setContentsMargins(0, 6, 0, 6)
        for i, cell in enumerate(row):
            mono = i in mono_cols
            lab = _label(str(cell), size="xs", color="neutral.800", mono=mono)
            rl.addWidget(lab, 1)
        v.addWidget(rw)
    return w


# 词条表格列宽比例（头行与数据行共用，保证对齐）
# 选择(固定) / 原词 / 替换为 / 类型 / 来源 / 命中书籍 / 操作(固定)
COL_CHECK_W = 34
COL_ACT_W = 128


# ---------------------------------------------------------------------------
# 模块
# ---------------------------------------------------------------------------

class VocabModule(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        # ---- 状态（与 HTML 原型同源）----
        self.entries = _seed_custom() + _seed_builtin()
        self.tier = "all"          # all / custom / builtin
        self.dict_ = "custom"      # custom / b1 / b2 / b3
        self.search = ""
        self._selected: set = set()
        self._snapshots: list = []
        self._undo_stack: list = []
        self._seq = 100
        self._pending_add: dict | None = None
        self._merge_sel: list | None = None
        self._book_sel: list | None = None

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
            "勾选「显示设计依据」可看到每个 UI 元素对应的文档条款。新增 / 查重 / 删除 / 合并"
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
        self._snap_toggle.clicked.connect(lambda: self._snap_card.setVisible(not self._snap_card.isVisible()))
        right.addWidget(self._snap_toggle)

        hl.addLayout(right)
        self._set_tier_active("all")
        return w

    def _set_tier_active(self, t: str):
        for key, b in self._tier_btns.items():
            on = (key == t)
            # Qt 的样式表没有 cursor / box-shadow 这两个属性（写了会刷
            # "Unknown property" 警告且不生效），选中态改用描边表达层级；
            # 手型光标在构造按钮时已用 setCursor 设好。
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
        txt.addWidget(_label("《星河彼端》校正完成，发现 3 条本书专有词条", size="base", weight="bold", color="neutral.900"))
        txt.addWidget(_label("是否把它们加入你的自定义词库？加入后，下次校正同类错误将自动生效。", size="sm", color="neutral.500"))
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
        return self._banner_w

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
        for d in DICT_ORDER:
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
        col.addWidget(_label(DICT_NAMES[d], size="sm", weight="bold", color="neutral.800"))
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

    def _set_dict_active(self, d: str):
        for key, item in self._dict_items.items():
            on = (key == d)
            item.setStyleSheet(
                f"QWidget#DictItem{{border:1px solid {c('primary.500') if on else c('neutral.200')};"
                f"border-radius:{r('md')};background:{c('primary.50') if on else c('neutral.0')}}}")
            item._meta.setText(
                f"{sum(1 for e in self.entries if e['dict']==key)} 条 · {'可编辑' if key=='custom' else '只读'}")

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

        chk = QCheckBox()
        chk.setChecked(e["id"] in self._selected)
        chk.stateChanged.connect(lambda s, i=e["id"]: self._toggle_row(i, s))
        hl.addWidget(chk, 0)

        word = _label(e["word"], size="sm", weight="bold", color="neutral.900", mono=True)
        hl.addWidget(word, 3)
        val = _label(e["value"], size="sm", color="primary.700", mono=True)
        hl.addWidget(val, 3)
        typ = _label(e.get("type", "—"), size="sm", color="neutral.600")
        hl.addWidget(typ, 2)

        is_builtin = e["tier"] == "builtin"
        chip = Pill("自定义" if not is_builtin else "内置", "ok" if not is_builtin else "info")
        hl.addWidget(chip, 2)

        books = ("📖 " + "、".join(e["books"])) if e["books"] else "—"
        bk = _label(books, size="xs", color="neutral.600")
        bk.setWordWrap(True)
        hl.addWidget(bk, 3)

        acts = QWidget()
        al = QHBoxLayout(acts)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        al.addStretch(1)
        edit = _link_btn("编辑", enabled=not is_builtin)
        if not is_builtin:
            edit.clicked.connect(lambda _c, i=e["id"]: self.open_edit(i))
        al.addWidget(edit)
        if not is_builtin:
            dele = _link_btn("删除", danger=True)
            dele.clicked.connect(lambda _c, i=e["id"]: self._confirm_delete([i]))
            al.addWidget(dele)
        else:
            al.addWidget(_label("只读", size="xs", color="neutral.400"))
        hl.addWidget(acts, 0)
        acts.setFixedWidth(COL_ACT_W)
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

    def _render_all(self):
        self._render_entries()
        self._set_dict_active(self.dict_)
        self._render_snaps()
        self._update_sel_state()

    def get_filtered(self) -> list:
        lst = self.entries[:]
        if self.dict_ != "all":
            lst = [e for e in lst if e["dict"] == self.dict_]
        elif self.tier == "custom":
            lst = [e for e in lst if e["tier"] == "custom"]
        elif self.tier == "builtin":
            lst = [e for e in lst if e["tier"] == "builtin"]
        q = self.search.strip().lower()
        if q:
            lst = [e for e in lst if q in e["word"].lower() or q in e["value"].lower()]
        return lst

    def _render_entries(self):
        while self._table_body.count():
            item = self._table_body.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        self._table_body.addWidget(self._entry_header())
        self._table_body.addWidget(hline())

        lst = self.get_filtered()
        if not lst:
            empty = _label("没有匹配的词条", size="sm", color="neutral.500")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 28, 0, 28)
            self._table_body.addWidget(empty)
            return
        for i, e in enumerate(lst):
            self._table_body.addWidget(self._entry_row(e))
            if i != len(lst) - 1:
                self._table_body.addWidget(hline())

    def _render_snaps(self):
        while self._snap_list.count():
            item = self._snap_list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        if not self._snapshots:
            empty = _label("暂无快照（任何变更都会自动创建）", size="xs", color="neutral.500")
            empty.setContentsMargins(0, 4, 0, 4)
            self._snap_list.addWidget(empty)
            return
        for i, s in enumerate(self._snapshots):
            item = QWidget()
            hl = QHBoxLayout(item)
            hl.setContentsMargins(0, 10, 0, 10)
            hl.setSpacing(10)
            dot = QLabel()
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(
                f"background:{c('success') if i==0 else c('neutral.200')};"
                f"border-radius:999px")
            if i == 0:
                dot.setStyleSheet(
                    f"background:{c('success')};border-radius:999px;"
                    f"border:3px solid {c('success.bg')}")
            hl.addWidget(dot)
            hl.addWidget(_label(s["label"], size="sm", color="neutral.800"))
            hl.addStretch(1)
            time = _label(s["time"] + (" · 当前" if i == 0 else ""), size="xs", color="neutral.500")
            hl.addWidget(time)
            if i > 0:
                b = _link_btn("恢复到此")
                b.clicked.connect(lambda _c, sid=s["id"]: self.restore_snap(sid))
                hl.addWidget(b)
            self._snap_list.addWidget(item)

    def _update_sel_state(self):
        sel = list(self._selected)
        valid = [i for i in sel if self._by_id(i) and self._by_id(i)["tier"] == "custom"]
        self._sel_count.setText(
            f"已选 {len(self._selected)} 条（可删 {len(valid)}）" if self._selected else "未选择")
        self._del_btn.setEnabled(len(valid) > 0)
        self._merge_btn.setEnabled(len(valid) >= 2)

    # ------------------------------------------------------------------ 选择

    def _by_id(self, i):
        return next((e for e in self.entries if e["id"] == i), None)

    def _toggle_row(self, i: int, state: int):
        if state:
            self._selected.add(i)
        else:
            self._selected.discard(i)
        self._update_sel_state()

    def _toggle_all(self, state: int):
        for e in self.get_filtered():
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
        else:
            self.dict_ = "all"
        self._set_dict_active(self.dict_)
        self._set_tier_active(t)
        self._render_entries()

    def select_dict(self, d: str):
        self.dict_ = d
        if d not in ("custom", "all"):
            self.tier = "all"
            self._set_tier_active("all")
        self._set_dict_active(d)
        self._render_entries()

    def _on_search(self, text: str):
        self.search = text
        self._render_entries()

    # ------------------------------------------------------------------ 快照 / 撤销

    def _now(self) -> str:
        import datetime
        d = datetime.datetime.now()
        return f"{d.hour:02d}:{d.minute:02d}:{d.second:02d}"

    def _snap(self, label: str):
        self._seq += 1
        self._snapshots.insert(0, dict(
            id=self._seq, time=self._now(), label=label,
            data=copy.deepcopy(self.entries)))
        if len(self._snapshots) > 12:
            self._snapshots.pop()
        self._render_snaps()

    def _push_undo(self, before):
        self._undo_stack.append(dict(before=copy.deepcopy(before)))

    def _undo(self):
        self._hide_status()
        if not self._undo_stack:
            self._toast("没有可撤销的操作")
            return
        last = self._undo_stack.pop()
        self.entries = copy.deepcopy(last["before"])
        self._selected = {i for i in self._selected if self._by_id(i)}
        self._snap("撤销上一步")
        self._render_all()
        self._toast("已撤销上一步操作")

    def restore_snap(self, sid: int):
        s = next((x for x in self._snapshots if x["id"] == sid), None)
        if not s:
            return
        self._push_undo(self.entries)
        self.entries = copy.deepcopy(s["data"])
        self._selected = {i for i in self._selected if self._by_id(i)}
        self._snap(f"恢复到 {s['time']}")
        self._render_all()
        self._toast("已恢复到所选时间点")

    # ------------------------------------------------------------------ 新增词条

    def open_add(self):
        if self.dict_ != "custom":
            self.select_dict("custom")
        modal = Modal(icon="＋", title="新增词条", parent=self)
        modal.add_note(
            "写入「我的词库」（自定义分级）；加入前自动查重；操作可撤销（同五条安全底线）。", "info")
        word = QLineEdit(); word.setPlaceholderText("例如：萧衍")
        val = QLineEdit(); val.setPlaceholderText("例如：萧彦")
        typ = QComboBox()
        typ.addItems(ENTRY_TYPES)
        py = QLineEdit(); py.setPlaceholderText("例如：xiāo yàn")
        modal.add_widget(self._field("原词（词 / 角色名）", word))
        modal.add_widget(self._field("替换为", val))
        modal.add_widget(self._field("类型", typ))
        modal.add_widget(self._field("注音（可选）", py))
        modal.add_foot("取消", "ghost", modal.reject)
        modal.add_foot("预览并查重", "primary",
                       lambda: self.preview_add(modal, word.text(), val.text(), typ.currentText(), py.text()))
        modal.show()

    def preview_add(self, parent_modal, word: str, value: str, typ: str, pinyin: str):
        word = (word or "").strip()
        value = (value or "").strip()
        pinyin = (pinyin or "").strip()
        if not word:
            self._toast("请填写原词"); return
        if not value:
            self._toast("请填写替换为"); return
        if word == value:
            self._toast("原词与替换值相同，无需新增"); return
        f = dict(word=word, value=value, type=typ, pinyin=pinyin)
        self._pending_add = f
        same_word = [e for e in self.entries if e["word"] == word]
        same_val = [e for e in self.entries if e["value"] == value and e["word"] != word]
        m = Modal(icon="✍", title="写入词库（二次确认）", parent=self)
        m.add_note("底线④：批量 / 写动作先预览再执行；新增可撤销。", "warn")
        rows = [(e["word"], e["value"], DICT_NAMES[e["dict"]], "内置" if e["tier"] == "builtin" else "自定义")
                for e in (same_word + same_val)]
        m.add_widget(_mini_table(["冲突", "原词", "替换为", "所在"], rows, mono_cols={1, 2}))
        if rows:
            m.add_note("加入前查重：发现冲突，请确认是否仍要写入「我的词库」。", "warn")
        else:
            m.add_note("查重通过：未发现同词 / 同值冲突。", "info")
        m.add_widget(_label(
            f"本次将写入 1 条到自定义词库；与内置词库分开管理（底线⑤）。", size="xs", color="neutral.500"))
        m.add_foot("返回修改", "ghost", parent_modal.show)
        m.add_foot("确认写入", "primary", lambda: self.confirm_add(m))
        m.show()

    def confirm_add(self, modal: Modal):
        f = self._pending_add
        if not f:
            self._toast("没有待写入的词条"); return
        before = copy.deepcopy(self.entries)
        nid = (max(e["id"] for e in self.entries) if self.entries else 0) + 1
        self.entries.append(dict(
            id=nid, word=f["word"], value=f["value"], type=f["type"],
            pinyin=f.get("pinyin", "") or "", dict="custom", tier="custom", books=[]))
        self._push_undo(before)
        self._snap(f"新增「{f['word']}」")
        self._pending_add = None
        self.dict_ = "custom"; self.tier = "custom"
        self._set_dict_active("custom"); self._set_tier_active("custom")
        modal.accept()
        self._render_all()
        self._toast(f"已新增「{f['word']}」到我的词库", with_undo=True)

    # ------------------------------------------------------------------ 编辑

    def open_edit(self, i: int):
        e = self._by_id(i)
        if not e or e["tier"] == "builtin":
            return
        modal = Modal(icon="✎", title="编辑词条", parent=self)
        word = QLineEdit(e["word"])
        val = QLineEdit(e["value"])
        typ = QComboBox(); typ.addItems(ENTRY_TYPES); typ.setCurrentText(e.get("type", "错词校正"))
        py = QLineEdit(e.get("pinyin", ""))
        modal.add_widget(self._field("原词", word))
        modal.add_widget(self._field("替换为", val))
        modal.add_widget(self._field("类型", typ))
        modal.add_widget(self._field("注音（可选）", py))
        modal.add_note("修改后自动快照，可撤销（底线①②）。", "info")
        modal.add_foot("取消", "ghost", modal.reject)
        modal.add_foot("保存", "primary",
                       lambda: self.save_edit(i, word.text(), val.text(), typ.currentText(), py.text(), modal))
        modal.show()

    def save_edit(self, i: int, word: str, value: str, typ: str, pinyin: str, modal: Modal):
        before = copy.deepcopy(self.entries)
        e = self._by_id(i)
        if not e:
            return
        e["word"] = (word or "").strip() or e["word"]
        e["value"] = (value or "").strip() or e["value"]
        e["type"] = typ or e.get("type", "错词校正")
        e["pinyin"] = (pinyin or "").strip()
        self._push_undo(before)
        self._snap(f"编辑「{e['word']}」")
        modal.accept()
        self._render_all()
        self._toast("已保存修改", with_undo=True)

    # ------------------------------------------------------------------ 查重

    def open_dup(self):
        groups = self._compute_dups()
        if not groups:
            self._toast("未发现重复词条"); return
        m = Modal(icon="🔁", title="查重结果（先预览，确认后处理）", parent=self)
        m.add_note("底线④：查重结果先给预览清单，确认后才执行；处理动作可撤销。", "warn")
        for g in groups:
            box = QFrame()
            box.setObjectName("DupGroup")
            box.setStyleSheet(
                f"QFrame#DupGroup{{border:1px solid {c('neutral.200')};border-radius:10px;"
                f"background:{c('neutral.50')};padding:12px 14px;margin-top:6px}}")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(8)
            bl.addWidget(_label(f"{g['type']}：{g['key']}", size="sm", color="warning", weight="bold"))
            bl.addWidget(_mini_table(["原词", "替换为", "来源"],
                                     [(e["word"], e["value"], DICT_NAMES[e["dict"]]) for e in g["items"]],
                                     mono_cols={0, 1}))
            m.add_widget(box)
        m.add_widget(_label("建议合并同词不同值冲突，或保留其一。可撤销，请放心处理。",
                            size="sm", color="neutral.500"))
        m.add_foot("暂时不处理", "ghost", m.reject)
        m.add_foot("我知道了", "primary", m.accept)
        m.show()

    def _compute_dups(self) -> list:
        lst = [e for e in self.entries if e["tier"] == "custom"]
        by_word, by_val, groups = {}, {}, []
        for e in lst:
            by_word.setdefault(e["word"], []).append(e)
            by_val.setdefault(e["value"], []).append(e)
        for w, arr in by_word.items():
            if len(arr) > 1:
                groups.append(dict(type="同词不同值", key=w, items=arr))
        for v, arr in by_val.items():
            if len(arr) > 1:
                groups.append(dict(type="同值不同词", key=v, items=arr))
        return groups

    # ------------------------------------------------------------------ 合并

    def open_merge(self):
        sel = [i for i in self._selected if self._by_id(i) and self._by_id(i)["tier"] == "custom"]
        if len(sel) < 2:
            self._toast("请至少选择 2 条自定义词条进行合并"); return
        self._merge_sel = sel
        items = [self._by_id(i) for i in sel]
        m = Modal(icon="➕", title="合并词条（先预览清单）", parent=self)
        m.add_note("底线④：合并前给预览清单（改哪些、删哪些、留哪个）；合并可撤销。", "warn")
        target = QComboBox()
        target.addItems([f"{e['word']} → {e['value']}" for e in items])
        m.add_widget(self._field("合并为「原词」（保留其一作为主词，其余并入其替换值）", target))
        m.add_widget(_mini_table(["处理", "原词", "替换为"],
                                 [("并入", e["word"], e["value"]) for e in items], mono_cols={1, 2}))
        m.add_widget(_label("合并后需「写入词库」二次确认（展示将写入条数）。", size="xs", color="neutral.500"))
        m.add_foot("取消", "ghost", m.reject)
        m.add_foot("预览写入", "primary", lambda: self.do_merge(m, target.currentText().split(" → ")[0]))
        m.show()

    def do_merge(self, parent_modal, target_word: str):
        sel = self._merge_sel or []
        items = [self._by_id(i) for i in sel if self._by_id(i)]
        if not items:
            return
        before = copy.deepcopy(self.entries)
        self.entries = [e for e in self.entries if not (e["id"] in sel and e["word"] != target_word)]
        removed = len([e for e in items if e["word"] != target_word])
        self._push_undo(before)
        self._selected = {i for i in self._selected if self._by_id(i)}
        self._snap(f"合并为「{target_word}」")
        m = Modal(icon="✍", title="写入词库（二次确认）", parent=self)
        m.add_note(
            f"将把合并结果写入「我的词库」，主词保留「{target_word}」，移除 {removed} 条重复词条。", "info")
        m.add_widget(_label(f"本次将写入 1 条主词、移除 {removed} 条（合并动作可撤销）。", size="sm", color="neutral.700"))
        m.add_foot("取消", "ghost", m.reject)
        m.add_foot("确认写入", "primary", lambda: (m.accept(), self._after_merge()))
        parent_modal.accept()
        m.show()

    def _after_merge(self):
        self._merge_sel = None
        self._render_all()
        self._toast("已写入词库，合并完成", with_undo=True)

    # ------------------------------------------------------------------ 展开核对

    def open_expand(self):
        scope = self.entries if (self.dict_ in ("custom", "all")) else \
            [e for e in self.entries if e["dict"] == self.dict_]
        lst = sorted(scope, key=lambda e: e["word"])
        m = Modal(icon="📋", title="展开核对（只读）", parent=self, min_width=620)
        m.add_note("结果以结构化表格呈现，不展示内部文件内容 / 行号（底线③）。", "info")
        m.add_widget(_mini_table(["#", "原词", "替换为", "来源"],
                                 [(i + 1, e["word"], e["value"], DICT_NAMES[e["dict"]])
                                  for i, e in enumerate(lst)], mono_cols={1, 2}))
        m.add_foot("关闭", "primary", m.accept)
        m.show()

    # ------------------------------------------------------------------ 删除（底线①④）

    def _on_delete_selected(self):
        targets = [i for i in self._selected if self._by_id(i) and self._by_id(i)["tier"] == "custom"]
        if not targets:
            self._toast("没有可删除的自定义词条"); return
        self._confirm_delete(targets)

    def _confirm_delete(self, ids: list):
        targets = [self._by_id(i) for i in ids if self._by_id(i) and self._by_id(i)["tier"] == "custom"]
        if not targets:
            self._toast("没有可删除的自定义词条"); return
        book_map = {}
        for e in targets:
            for b in e["books"]:
                book_map[b] = book_map.get(b, 0) + 1
        book_lines = "；".join(f"{b}：涉及 {n} 条" for b, n in book_map.items()) or \
            "无（这些词条尚未在任何校正中命中）"
        m = Modal(icon="🗑", title="删除确认（批量先预览）", parent=self)
        m.add_note("底线④：批量删除必须先给预览清单，确认后执行；底线①：误删可撤销。", "warn")
        m.add_widget(_label(f"即将删除 {len(targets)} 条自定义词条，删除后可通过「撤销」恢复。", size="sm", color="neutral.800"))
        m.add_widget(_label("影响范围（命中过哪些书）：", size="sm", weight="semibold", color="neutral.700"))
        m.add_note(book_lines, "info")
        m.add_widget(_mini_table(["原词", "替换为"], [(e["word"], e["value"]) for e in targets], mono_cols={0, 1}))
        m.add_foot("取消", "ghost", m.reject)
        m.add_foot(f"确认删除 {len(targets)} 条", "danger",
                   lambda: (m.accept(), self.do_delete(ids)))
        m.show()

    def do_delete(self, ids: list):
        before = copy.deepcopy(self.entries)
        self.entries = [e for e in self.entries if e["id"] not in ids]
        self._selected = {i for i in self._selected if self._by_id(i)}
        self._push_undo(before)
        self._snap(f"删除 {len(ids)} 条")
        self._render_all()
        self._toast(f"已删除 {len(ids)} 条自定义词条", with_undo=True)

    # ------------------------------------------------------------------ 本书专有词（2.4.2）

    def open_book_words(self):
        m = Modal(icon="✨", title="本书专有词条（加入预览）", parent=self)
        m.add_note("加入前有预览，可逐条或整组确认；加入后下次校正自动生效。", "info")
        checks = []
        rows = QVBoxLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(4)
        for i, w in enumerate(BOOK_WORDS):
            rw = QWidget()
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(10)
            cb = QCheckBox(); cb.setChecked(True); checks.append(cb)
            rl.addWidget(cb)
            rl.addWidget(_label(w["word"], size="sm", weight="bold", color="neutral.900", mono=True), 0)
            rl.addWidget(_label(w["note"], size="xs", color="neutral.500"), 1)
            rows.addWidget(rw)
        self._book_checks = checks
        rows_box = QWidget()
        rows_box.setLayout(rows)
        m.add_widget(rows_box)
        m.add_foot("取消", "ghost", m.reject)
        m.add_foot("加入选中词条到「我的词库」", "primary",
                   lambda: self.add_book_words(m))
        m.show()

    def add_book_words(self, modal: Modal):
        before = copy.deepcopy(self.entries)
        added = []
        nid = (max(e["id"] for e in self.entries) if self.entries else 0)
        for i, cb in enumerate(self._book_checks or []):
            if cb.isChecked():
                w = BOOK_WORDS[i]
                if not any(e["word"] == w["word"] and e["dict"] == "custom" for e in self.entries):
                    nid += 1
                    self.entries.append(dict(
                        id=nid, word=w["word"], value=w["value"], type="专有名词",
                        pinyin="", dict="custom", tier="custom", books=["《星河彼端》"]))
                    added.append(w["word"])
        self._push_undo(before)
        self._snap(f"加入 {len(added)} 条专有词")
        self.hide_banner()
        modal.accept()
        self._render_all()
        self._toast(f"已加入 {len(added)} 条专有词条到「我的词库」", with_undo=True)

    # ------------------------------------------------------------------ 恢复默认（底线⑤）

    def restore_default(self):
        d = ConfirmDialog(
            icon="↺", title="恢复默认词库",
            note="底线⑤：恢复默认词库只重置内置词库，不影响你的自定义词条。",
            confirm_text="确认恢复", confirm_kind="primary", parent=self)
        if d.exec() == QDialog.DialogCode.Accepted:
            before = copy.deepcopy(self.entries)
            custom = [e for e in self.entries if e["tier"] == "custom"]
            self.entries = custom + _seed_builtin()
            self._push_undo(before)
            self._snap("恢复默认词库")
            self._render_all()
            self._toast("已恢复默认词库（自定义词条保留）", with_undo=True)

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
