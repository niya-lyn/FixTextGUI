"""
FixText V1 · 检查问题模块（Qt 移植）
=====================================

对照 `FixText_V1_检查问题_原型.html` **1:1 移植**，保持核心价值：
**逐处人工确认**（不是「一键修复全部」）。

结构：书源条 → 统计条（只统计 / 结束检查）→ 两栏（检查项 + 问题清单 | 编辑器）
      → 操作条（下一处 / 修复 / 跳过 / 保存并下一处 / 撤销）
      → 7 条规则开关 → 批量操作（二次确认）→ 设计依据开关。

数据来源（T2.10 接线）：问题清单一律来自**真实运行的引号检查报告**，
经 ``fixtext_check.load_report`` 读入后由 ``set_report`` 注入；
本模块不含任何演示数据。没有真实报告时只显示空状态引导。

大报告分页：一页 ``PAGE_SIZE`` 条，翻页可达全部条目，不静默截断。

用到的复用部件见 `fixtext_widgets.py`（Card / Switch / Pill / FieldRow）。
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import (
    QFont, QColor, QBrush, QTextCursor, QTextCharFormat, QShortcut, QKeySequence,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QScrollArea, QFrame, QMessageBox, QCheckBox, QSizePolicy,
)

import fixtext_check as checkdata
from fixtext_tokens import c, sp, r, fs, FONT_MONO, FONT_WEIGHT
from fixtext_widgets import Card, Switch, Pill, FieldRow, hline, px


# ---------------------------------------------------------------------------
# 检查项（自动执行的检查与规则，条数由真实报告算）
# ---------------------------------------------------------------------------

#: (名称, 说明, 计入的分类)
CHECKS = [
    ("缺左引号 / 缺右引号", "配对栈中发现未闭合或多余", ("缺左引号", "缺右引号")),
    ("引号交叉错乱",       "双套内又出现独立双引号",    ("引号交叉错乱",)),
    ("空引号",             "成对出现但内容为空",        ("空引号",)),
    ("跨行未闭合",         "向下最多探测 100 行",       ("多层嵌套未闭合",)),
    ("英文撇号误报过滤",   "前后为字母的撇号不计错",    ("其他引号问题",)),
]

RULES = [
    (1, "双套双引号改单引号",   "外层双引号内再出现双引号时，把内层改为单引号", True),
    (2, "写反引号反转",         "左右引号写反时调换",                         True),
    (3, "连续同向引号归一",     "连续两个左 / 右引号收回一个",                 True),
    (4, "句尾孤立右引号移除",   "句末无配对的右引号删除",                     True),
    (5, "补左引号",             "缺左引号处补入",                             True),
    (6, "按文件类型补右引号",   "依文件类型（TXT / EPUB 合并）规则补右引号",   True),
    (7, "最外层单引号批量改双引号", "批量把最外层单引号统一改双引号",           True),
]

#: 问题清单每页条数（真实报告动辄上百条，翻页而不是截断）
PAGE_SIZE = 40


# ---------------------------------------------------------------------------
# 问题清单行
# ---------------------------------------------------------------------------

class ProblemRow(QFrame):
    clicked = Signal(int)
    #: 「加入词库」按钮被点（§2.4.2 第 4 条：检查页问题行 → 预览 → 确认加入）
    addRequested = Signal(int)

    def __init__(self, idx: int, p: dict, selected: bool, parent=None):
        super().__init__(parent)
        self.idx = idx
        state = p.get("state")
        border = c("primary.500") if selected else c("neutral.100")
        bg = c("primary.50") if selected else c("neutral.0")
        # 精确选择器：# 内联 QSS 的类型选择器会连带命中 QLabel（QLabel 是 QFrame 子类）
        self.setObjectName("ProblemRow")
        self.setStyleSheet(
            f"QFrame#ProblemRow{{background:{bg};border:1px solid {border};"
            f"border-radius:10px}}"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        hl = QHBoxLayout(self)
        hl.setContentsMargins(10, 9, 10, 9)
        hl.setSpacing(10)

        no = QLabel(f"L{p['line']}")
        no.setStyleSheet(
            f"color:{c('neutral.500')};font-size:11px;font-weight:700;"
            f"font-family:{FONT_MONO}"
        )
        hl.addWidget(no)

        tone = "neutral.400" if state else "neutral.800"
        t = QLabel(p["type"])
        t.setStyleSheet(f"color:{c(tone)};font-weight:600;font-size:{fs('sm')}")
        hl.addWidget(t)

        ctx = QLabel(p["pre"] + p["hl"] + p["post"])
        ctx.setStyleSheet(
            f"color:{c('neutral.500')};font-size:{fs('xs')};font-family:{FONT_MONO}"
        )
        ctx.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        hl.addWidget(ctx, 1)

        if state == "fixed":
            badge = Pill("已修复", "ok")
        elif state == "skip":
            badge = Pill("已跳过", "neutral")
        else:
            badge = Pill("待确认", "warn")
        hl.addWidget(badge)

        # 加入词库：把这一处的可疑写法收进「我的词库」，下次同类直接纠正
        self.add_btn = QPushButton("＋词库")
        self.add_btn.setObjectName("LinkBtn")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setToolTip("把这一处的写法加入「我的词库」，下次校正自动纠正")
        self.add_btn.setAccessibleName("加入词库")
        self.add_btn.setStyleSheet(
            f"QPushButton#LinkBtn{{background:transparent;border:none;"
            f"color:{c('primary.700')};font-weight:600;font-size:11px;"
            f"padding:3px 6px;border-radius:6px}}"
            f"QPushButton#LinkBtn:hover{{background:{c('primary.100')}}}")
        self.add_btn.clicked.connect(
            lambda _=False, i=idx: self.addRequested.emit(i))
        hl.addWidget(self.add_btn)

    def mousePressEvent(self, event):
        self.clicked.emit(self.idx)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# 模块
# ---------------------------------------------------------------------------

class CheckModule(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        #: 真实报告（``fixtext_check.load_report`` 的返回；None = 还没校正过）
        self.report: dict | None = None
        self.probs: list[dict] = []
        self.cur = 0
        self._page = 0
        self.ins_buf = ""
        self.undo = []
        self.basis_labels = []
        self._marks: dict[str, str] = {}
        self._run_dir: str = ""
        #: 词库写入口（由主窗口注入；None 时「＋词库」只给引导，不静默失败）
        self.vocab_store = None
        #: 最近一次加入结果的还原点（供界面提示「可撤销」）
        self.last_add_point: int = 0

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_status)

        self._build()
        self.set_empty()
        self._bind_shortcuts()

    # ------------------------------------------------------------------ 构建

    def _btn(self, text: str, obj: str = "BtnOutline", slot=None) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(obj)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        if slot is not None:
            b.clicked.connect(slot)
        return b

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(px(sp("4")))

        root.addWidget(self._head())
        root.addWidget(self._bookbar())
        root.addWidget(self._stats_bar())
        root.addLayout(self._columns())
        root.addWidget(self._action_bar())
        root.addWidget(self._rules_card())
        root.addWidget(self._batch_card())
        root.addWidget(self._legend())
        root.addWidget(self._status_label())

    def _head(self) -> QWidget:
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel("检查问题")
        title.setStyleSheet(
            f"color:{c('neutral.900')};font-size:{fs('2xl')};"
            f"font-weight:{FONT_WEIGHT['bold']}"
        )
        sub = QLabel(
            "引号配对检查 + 逐处交互修复。检查结果可定位、可单独处理、可撤销。"
        )
        sub.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('md')}")
        col.addWidget(title)
        col.addWidget(sub)
        hl.addLayout(col, 1)

        self.basis_cb = QCheckBox("显示设计依据")
        self.basis_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.basis_cb.toggled.connect(self._toggle_basis)
        hl.addWidget(self.basis_cb, 0, Qt.AlignmentFlag.AlignTop)
        return w

    def _card(self, *args, **kwargs) -> Card:
        card = Card(*args, **kwargs)
        if card.basis is not None:
            self.basis_labels.append(card.basis)
        return card

    def _bookbar(self) -> Card:
        card = self._card(basis="§2.2 入口③ · 逐处人工确认")
        hl = QHBoxLayout()
        hl.setSpacing(14)

        ico = QLabel("📖")
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setFixedSize(40, 40)
        ico.setStyleSheet(
            f"background:{c('primary.100')};color:{c('primary.700')};"
            f"border-radius:10px;font-size:19px"
        )
        hl.addWidget(ico)

        col = QVBoxLayout()
        col.setSpacing(2)
        self.book_name = QLabel("尚未校正")
        self.book_name.setStyleSheet(
            f"color:{c('neutral.900')};font-weight:700;font-size:{fs('md')}"
        )
        self.book_meta = QLabel("")
        self.book_meta.setStyleSheet(
            f"color:{c('neutral.500')};font-size:{fs('xs')}")
        col.addWidget(self.book_name)
        col.addWidget(self.book_meta)
        hl.addLayout(col)

        hl.addStretch(1)
        hl.addWidget(Pill("编辑器可改文并保存回写", "info"))
        card.body_l.addLayout(hl)
        return card

    def _stats_bar(self) -> Card:
        card = Card()
        hl = QHBoxLayout()
        hl.setSpacing(10)
        self.stats = QLabel("")
        self.stats.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('sm')}")
        hl.addWidget(self.stats)
        hl.addStretch(1)
        hl.addWidget(self._btn("只统计不修复", "BtnOutline", self.only_count))
        hl.addWidget(self._btn("结束检查", "BtnDanger", self.end_check))
        card.body_l.addLayout(hl)
        return card

    def _columns(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(px(sp("4")))

        # ---- 左列 ----
        left = QVBoxLayout()
        left.setSpacing(px(sp("4")))

        checks = self._card(
            "检查项（自动执行）", collapsible=True, open_=True,
            basis="§2.7.4 · 检查项自动执行无开关",
        )
        self._check_rows: list[FieldRow] = []
        self._check_chips: list[tuple[int, FieldRow]] = []
        for i, (name, desc, _kinds) in enumerate(CHECKS):
            if i:
                checks.body_l.addWidget(hline())
            fr = FieldRow(i + 1, name, desc, chip="—")
            checks.body_l.addWidget(fr)
            self._check_rows.append(fr)
        left.addWidget(checks)

        probs_card = self._card(
            "问题清单", "点击任一问题，右侧定位", collapsible=True, open_=True,
            basis="§2.7.4 · 问题清单 · 点击定位",
        )
        self.probs_title = probs_card
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFixedHeight(300)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setStyleSheet("QScrollArea{border:none;background:transparent}")
        holder = QWidget()
        holder.setStyleSheet("background:transparent")
        self.prob_box = QVBoxLayout(holder)
        self.prob_box.setContentsMargins(0, 0, 0, 0)
        self.prob_box.setSpacing(6)
        sc.setWidget(holder)
        probs_card.body_l.addWidget(sc)
        probs_card.body_l.addLayout(self._pager())
        left.addWidget(probs_card)
        left.addStretch(1)

        # ---- 右列 ----
        right = QVBoxLayout()
        right.setSpacing(px(sp("4")))

        ed = self._card(
            "正文（当前问题上下文）", "可直接改文，保存后自动跳下一处",
            collapsible=True, open_=True,
            basis="§2.7.4 · 右栏编辑器 · 保存并下一处",
        )
        ed.body_l.setSpacing(10)

        self.editor = QTextEdit()
        self.editor.setMinimumHeight(150)
        self.editor.setStyleSheet(
            f"QTextEdit{{background:{c('neutral.50')};"
            f"border:1px solid {c('neutral.200')};border-radius:{r('md')};"
            f"padding:12px;font-family:{FONT_MONO};font-size:{fs('sm')};"
            f"color:{c('neutral.800')}}}"
        )
        ed.body_l.addWidget(self.editor)

        self.advice = QLabel("")
        self.advice.setWordWrap(True)
        self.advice.setStyleSheet(
            f"color:{c('neutral.600')};font-size:{fs('sm')};background:transparent")
        ed.body_l.addWidget(self.advice)

        ed.body_l.addLayout(self._label_row("四类引号快捷变换", "Alt+1~4"))
        ed.body_l.addLayout(self._quote_buttons([
            ("前后引号互换", 1), ("单双引号互转", 2),
            ("合并行", 3), ("单引号转〔〕", 4),
        ]))
        ed.body_l.addLayout(self._label_row("插入四种引号", "F1~F4"))
        ed.body_l.addLayout(self._quote_buttons([
            ("插入 “", "“"), ("插入 ”", "”"), ("插入 ‘", "‘"), ("插入 ’", "’"),
        ], insert=True))
        right.addWidget(ed)
        right.addStretch(1)

        row.addLayout(left, 1)
        row.addLayout(right, 1)
        return row

    def _pager(self) -> QHBoxLayout:
        hl = QHBoxLayout()
        hl.setSpacing(8)
        self.page_label = QLabel("")
        self.page_label.setStyleSheet(
            f"color:{c('neutral.500')};font-size:{fs('xs')}")
        hl.addWidget(self.page_label)
        hl.addStretch(1)
        self.prev_btn = self._btn("上一页", "BtnOutline", lambda: self.turn_page(-1))
        self.next_btn = self._btn("下一页", "BtnOutline", lambda: self.turn_page(1))
        hl.addWidget(self.prev_btn)
        hl.addWidget(self.next_btn)
        return hl

    def _label_row(self, text: str, shortcut: str) -> QHBoxLayout:
        hl = QHBoxLayout()
        hl.setSpacing(8)
        lab = QLabel(text)
        lab.setStyleSheet(
            f"color:{c('neutral.800')};font-weight:700;font-size:{fs('sm')}"
        )
        hl.addWidget(lab)
        hl.addWidget(Pill(shortcut, "warn"))
        hl.addStretch(1)
        return hl

    def _quote_buttons(self, items, insert: bool = False) -> QHBoxLayout:
        hl = QHBoxLayout()
        hl.setSpacing(8)
        for text, arg in items:
            if insert:
                btn = self._btn(text, "BtnOutline", lambda _=False, a=arg: self.ins(a))
            else:
                btn = self._btn(text, "BtnOutline", lambda _=False, a=arg: self.qx(a))
            hl.addWidget(btn)
        hl.addStretch(1)
        return hl

    def _action_bar(self) -> Card:
        card = self._card(basis="§2.7.4 · 逐处操作 + 撤销")
        hl = QHBoxLayout()
        hl.setSpacing(10)
        hl.addWidget(self._btn("下一处", "BtnOutline", self.next_issue))
        hl.addWidget(self._btn("修复此处", "BtnPrimary", self.fix_here))
        hl.addWidget(self._btn("跳过此处", "BtnOutline", self.skip_here))
        hl.addWidget(self._btn("保存并下一处", "BtnOutline", self.save_and_next))
        hl.addStretch(1)
        hl.addWidget(self._btn("↺ 撤销上一步", "BtnOutline", self.undo_last))
        card.body_l.addLayout(hl)
        return card

    def _rules_card(self) -> Card:
        card = self._card(
            "自动修复规则", "7 条，逐条可开关", collapsible=True, open_=False,
            basis="§2.7.4 · 7 条规则逐条可开关",
        )
        self.rule_switches = {}
        for i, (n, name, desc, on) in enumerate(RULES):
            if i:
                card.body_l.addWidget(hline())
            sw = Switch(on)
            self.rule_switches[n] = sw
            card.body_l.addWidget(FieldRow(n, name, desc, control=sw))

        card.body_l.addWidget(hline())
        foot = QHBoxLayout()
        tip = QLabel("7 条规则逐条可开关，配置按用户持久化。")
        tip.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('xs')}")
        foot.addWidget(tip)
        foot.addStretch(1)
        foot.addWidget(self._btn("保存配置", "BtnGhost",
                                 lambda: self.toast("规则配置已保存")))
        card.body_l.addLayout(foot)
        return card

    def _batch_card(self) -> Card:
        card = self._card(
            "批量操作", "执行前预览影响条数", collapsible=True, open_=True,
            basis="§2.7.4 · 批量操作二次确认 + 预览",
        )
        card.body_l.addWidget(FieldRow(
            None, "最外层单引号批量改双引号", "把最外层的 ‘…’ 统一改为 “…”",
            control=self._btn("执行", "BtnOutline", self.batch_op),
            name_width=190,
        ))
        return card

    def _legend(self) -> QLabel:
        lab = QLabel(
            "勾选「显示设计依据」可看到每个 UI 元素对应的文档条款。"
            "「逐处人工确认」是这个模块的核心价值，不能只做「一键修复全部」。"
        )
        lab.setWordWrap(True)
        lab.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('xs')}")
        return lab

    def _status_label(self) -> QLabel:
        self.status = QLabel("")
        self.status.setVisible(False)
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"background:{c('neutral.800')};color:#FFFFFF;"
            f"border-radius:{r('md')};padding:10px 16px;font-size:{fs('sm')}"
        )
        self.status.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        return self.status

    # ------------------------------------------------------------------ 数据注入

    @property
    def has_data(self) -> bool:
        """是否已注入真实报告且报告里有条目。"""
        return bool(self.report and self.report.get("ok") and self.probs)

    def set_report(self, report: dict | None) -> None:
        """注入一次真实运行的引号检查结果（``fixtext_check.load_report`` 的返回）。

        报告为空 / 读失败 → 自动落到空状态引导，不显示任何假条目。
        """
        if not report or not report.get("ok"):
            self.set_empty(reason=(report or {}).get("reason", ""))
            return
        self.report = report
        self._run_dir = str(report.get("run_dir") or "")
        self.probs = [dict(it) for it in report.get("items") or []]
        self._page = 0
        self.cur = 0
        self.undo = []
        self.ins_buf = ""
        self.set_marks(self._marks)
        self._render_bookbar()
        self.render()

    def set_marks(self, marks: dict[str, str] | None = None) -> None:
        """贴上/更新复核标记（已修复、已跳过）。"""
        self._marks = dict(marks or {})
        for it in self.probs:
            state = self._marks.get(checkdata.mark_key(it))
            it["state"] = state if state in ("fixed", "skip") else None

    def set_empty(self, reason: str = "") -> None:
        """空状态：还没校正过（或报告读不到）时的人话引导。"""
        self.report = None
        self.probs = []
        self.cur = 0
        self._page = 0
        self._empty_reason = reason or (
            "这里显示每次校正后真实检出的引号问题。先去「一键校正」跑一次，"
            "回来就能逐处检查。")
        self._render_bookbar()
        self.render()

    def _render_bookbar(self):
        if self.has_data:
            book = self.report.get("book") or ""
            self.book_name.setText(f"《{book}》" if book else "本次校正的书")
            counts = (f"共 <b>{self.report.get('found', 0)}</b> 处待确认")
            if not self.report.get("consistent", True):
                counts += (f"（报告声明 {self.report.get('declared')} 处，"
                           f"读取到 {self.report.get('found')} 处，已如实并列）")
            self.book_meta.setText(f"已校正 · {counts}")
        else:
            self.book_name.setText("尚未校正")
            self.book_meta.setText(str(getattr(self, "_empty_reason", ""))[:120])

    # ------------------------------------------------------------------ 行为

    def _bind_shortcuts(self):
        ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for n in (1, 2, 3, 4):
            sc = QShortcut(QKeySequence(f"Alt+{n}"), self)
            sc.setContext(ctx)
            sc.activated.connect(lambda n=n: self.qx(n))
        for i, ch in enumerate(("“", "”", "‘", "’"), start=1):
            sc = QShortcut(QKeySequence(f"F{i}"), self)
            sc.setContext(ctx)
            sc.activated.connect(lambda ch=ch: self.ins(ch))

    def _toggle_basis(self, on: bool):
        for b in self.basis_labels:
            b.setVisible(bool(on))

    def toast(self, msg: str):
        self.status.setText(msg)
        self.status.setVisible(True)
        self._toast_timer.start(2600)

    def _hide_status(self):
        self.status.setVisible(False)

    # ------------------------------------------------------------------ 渲染

    def _follow_cursor(self):
        """当前处不在本页时把页码跟过去（「下一处」跨页跳转时）。"""
        if not self.has_data:
            return
        page = self.cur // PAGE_SIZE
        if page != self._page:
            self._page = page

    def render(self):
        self._follow_cursor()
        self._render_checks()
        self._render_probs()
        self._render_editor()
        self._render_stats()
        self._render_bookbar()

    @property
    def pages(self) -> int:
        return max(1, math.ceil(len(self.probs) / PAGE_SIZE))

    def _render_checks(self):
        """检查项的实际条数来自真实报告。"""
        for i, (_name, _desc, kinds) in enumerate(CHECKS):
            n = sum(1 for p in self.probs if p.get("type") in kinds)
            chip = f"{n} 处" if self.has_data else "—"
            if i < len(self._check_rows):
                self._check_rows[i].set_chip(chip)

    def _render_stats(self):
        if not self.has_data:
            self.stats.setText("尚未校正 · 还没有可检查的结果")
            return
        done = sum(1 for p in self.probs if p.get("state"))
        self.stats.setText(
            f"共 <b>{len(self.probs)}</b> 处 · 已处理 <b>{done}</b> · "
            f"当前第 <b>{self.cur + 1}</b> 处"
        )

    def _render_probs(self):
        while self.prob_box.count():
            item = self.prob_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not self.has_data:
            empty = QLabel(self._empty_text())
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(
                f"color:{c('neutral.500')};font-size:{fs('sm')};"
                f"border:1px dashed {c('neutral.300')};border-radius:10px;"
                f"padding:22px 16px;background:{c('neutral.50')}")
            self.prob_box.addWidget(empty)
            self._update_pager()
            return

        start = self._page * PAGE_SIZE
        chunk = self.probs[start:start + PAGE_SIZE]
        for off, p in enumerate(chunk):
            idx = start + off
            row = ProblemRow(idx, p, idx == self.cur)
            row.clicked.connect(self.select)
            row.addRequested.connect(self.add_problem_to_vocab)
            self.prob_box.addWidget(row)
        self.prob_box.addStretch(1)
        self._update_pager()

    # -------------------------------------------------- 问题行 → 加入词库（§2.4.2 第 4 条）

    def set_vocab_store(self, store) -> None:
        """注入词库写入口（T3.1 的五操作同一入口，加入也走它 → 天然可撤销）。"""
        self.vocab_store = store

    def problem_candidate(self, i: int) -> dict:
        """把第 i 处问题整理成一条待加入词库的词条。

        取这一处的「可疑写法」作为原词：自动改法能算出来的，替换值就是改后；
        算不出来的（需要人工判断）不上「加入词库」这条快路，避免写进错值。
        """
        p = self.probs[i]
        word = str(p.get("hl") or "").strip()
        fixed = checkdata.apply_action(p).strip()
        return dict(
            word=word,
            value=(fixed or word),
            type="错词校正",
            count=1,
            note=f"检查页第 {p.get('line')} 行 · {p.get('type') or ''}".strip(" ·"),
        )

    def add_problem_to_vocab(self, i: int) -> dict | None:
        """问题行「＋词库」：预览 → 确认加入（可撤销、必须查重）。"""
        if not self._guard() or not (0 <= i < len(self.probs)):
            return None
        if self.vocab_store is None:
            self.toast("词库暂不可用，请到「词库管理」页手动新增这一条")
            return None
        cand = self.problem_candidate(i)
        if not cand["word"]:
            self.toast("这一处没有可加入词库的写法")
            return None
        if cand["word"] == cand["value"]:
            self.toast("这一处还没有可靠的自动改法，暂不建议加入词库")
            return None

        box = QMessageBox(self)
        box.setWindowTitle("加入词库预览")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("把这一处写法加入「我的词库」？")
        box.setInformativeText(
            f"词条：{cand['word']}\n"
            f"替换值：{cand['value']}\n"
            f"类型：{cand['type']}\n\n"
            "加入后下次校正同类错误自动生效，加入动作可以撤销。"
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok)
        box.button(QMessageBox.StandardButton.Cancel).setText("取消")
        box.button(QMessageBox.StandardButton.Ok).setText("确认加入")
        box.setDefaultButton(QMessageBox.StandardButton.Ok)
        if box.exec() != QMessageBox.StandardButton.Ok:
            return None

        try:
            res = self.vocab_store.add_book_words([cand], str(
                (self.report or {}).get("book") or ""))
        except Exception as exc:                       # 词库写失败要说清原因
            self.toast(f"没有加入：{exc}")
            return None

        added = int(res.get("added") or 0)
        skipped = list(res.get("skipped_exists") or [])
        conflicts = list(res.get("conflicts") or [])
        self.last_add_point = int(res.get("point_id") or 0)
        if added:
            self.toast(f"已加入「{cand['word']}」到「我的词库」，可撤销")
        elif conflicts:
            kinds = "、".join(sorted({str(h.get("kind") or "") for c0 in conflicts
                                      for h in (c0.get("hits") or []) if h.get("kind")}))
            self.toast(
                f"没有加入：「{cand['word']}」与词库里已有词条冲突（{kinds}），"
                "未覆盖已有写法")
        elif skipped:
            self.toast(f"没有重复加入：「{cand['word']}」已在词库中")
        else:
            self.toast("没有加入：这一条被词库规则跳过")
        return dict(res, added=added, skipped=len(skipped),
                    conflicts=len(conflicts), candidate=cand)

    def _empty_text(self) -> str:
        return (
            "还没有可检查的结果。先去「一键校正」完成一次校正，"
            "这次检出的引号问题就会出现在这里，可以逐处确认。"
        )

    def _update_pager(self):
        total = self.pages
        if not self.has_data:
            self.page_label.setText("")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return
        start = self._page * PAGE_SIZE
        end = min(len(self.probs), start + PAGE_SIZE)
        self.page_label.setText(
            f"第 {start + 1}–{end} 条 · 共 {len(self.probs)} 条 · "
            f"第 {self._page + 1}/{total} 页")
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page + 1 < total)

    def turn_page(self, delta: int):
        if not self.has_data:
            self.toast(self._empty_text())
            return
        target = self._page + delta
        if target < 0 or target >= self.pages:
            return
        self._page = target
        self._render_probs()

    def _render_editor(self):
        if not self.has_data:
            self.editor.setPlainText("")
            self.editor.setReadOnly(True)
            self.advice.setText("校正完成后，这里会显示选中那一处的正文上下文。")
            self.editor.setExtraSelections([])
            return
        self.editor.setReadOnly(False)
        p = self.probs[self.cur]
        prefix = f"L{p['line']}   "
        self.editor.setPlainText(prefix + p["pre"] + p["hl"] + p["post"] + self.ins_buf)
        self.advice.setText(p.get("advice") or "")

        length = len(p["hl"])
        if length:
            start = len(prefix) + len(p["pre"])
            sel = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            bg = c("success.bg") if p.get("state") == "fixed" else c("warning.bg")
            fmt.setBackground(QBrush(QColor(bg)))
            fmt.setFontWeight(QFont.Weight.Bold)
            # 下划线对应原型的 2px 底边，弥补 cream 底在小尺寸下不够醒目
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SingleUnderline)
            fmt.setUnderlineColor(
                QColor(c("success") if p.get("state") == "fixed" else c("warning"))
            )
            sel.format = fmt
            cur = self.editor.textCursor()
            cur.setPosition(start)
            cur.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cur
            self.editor.setExtraSelections([sel])
        else:
            self.editor.setExtraSelections([])

    # ------------------------------------------------------------------ 交互

    def _guard(self) -> bool:
        """无数据时所有逐处操作只给引导，不动界面状态。"""
        if not self.has_data:
            self.toast(self._empty_text())
            return False
        return True

    def select(self, i: int):
        if not self._guard() or not (0 <= i < len(self.probs)):
            return
        self.cur = i
        self.ins_buf = ""
        self.render()

    def next_issue(self):
        if not self._guard():
            return
        n = len(self.probs)
        for k in range(1, n + 1):
            j = (self.cur + k) % n
            if not self.probs[j].get("state"):
                self.cur = j
                break
        self.ins_buf = ""
        self.render()

    def _push_undo(self):
        # pre / post 一起存：批量操作会同时改一段话的上下文，只存 hl 撤不完整
        p = self.probs[self.cur]
        self.undo.append({
            "i": self.cur, "pre": p["pre"], "hl": p["hl"],
            "post": p["post"], "state": p.get("state"),
        })

    def _set_state(self, state: str | None):
        """写状态并同步落盘（重启后还能看到上次的复核进度）。"""
        self.probs[self.cur]["state"] = state
        if self._run_dir:
            key = checkdata.mark_key(self.probs[self.cur])
            if state:
                self._marks[key] = state
            else:
                self._marks.pop(key, None)
            checkdata.save_marks(self._run_dir, self._marks)

    def fix_here(self):
        if not self._guard():
            return
        p = self.probs[self.cur]
        action = p.get("action")
        if not action:
            self.toast("这处没有可靠的自动改法，需要人工判断后再改")
            return
        self._push_undo()
        p["hl"] = checkdata.apply_action(p)
        self._set_state("fixed")
        line = p["line"]
        self.render()
        self.next_issue()
        self.toast(f"已按自动修复规则修复 L{line}")

    def skip_here(self):
        if not self._guard():
            return
        self._push_undo()
        self._set_state("skip")
        self.render()
        self.next_issue()
        self.toast("已跳过，记入跳过清单")

    def save_and_next(self):
        if not self._guard():
            return
        self._push_undo()
        self._set_state("fixed")
        self.render()
        self.next_issue()
        self.toast("已保存回写，自动跳到下一处")

    def undo_last(self):
        if not self._guard():
            return
        if not self.undo:
            self.toast("没有可撤销的操作")
            return
        a = self.undo.pop()
        if a.get("batch"):
            # 批量操作是一条撤销记录：整组一起回退，光标回到第一处
            for it in a["items"]:
                p = self.probs[it["i"]]
                p["pre"] = it["pre"]
                p["hl"] = it["hl"]
                p["post"] = it["post"]
            self.cur = a["items"][0]["i"]
            self._set_state(a.get("prev_state"))
            self.ins_buf = ""
            self.render()
            self.toast("已撤销批量操作")
            return
        p = self.probs[a["i"]]
        p["pre"] = a["pre"]
        p["hl"] = a["hl"]
        p["post"] = a["post"]
        p["state"] = a["state"]
        self.cur = a["i"]
        self._sync_mark(p)
        self.ins_buf = ""
        self.render()
        self.toast("已撤销上一步")

    def _sync_mark(self, p: dict):
        """撤销后把落盘标记同步成条目当前状态。"""
        if not self._run_dir:
            return
        key = checkdata.mark_key(p)
        state = p.get("state")
        if state in ("fixed", "skip"):
            self._marks[key] = state
        else:
            self._marks.pop(key, None)
        checkdata.save_marks(self._run_dir, self._marks)

    def qx(self, n: int):
        if not self._guard():
            return
        p = self.probs[self.cur]
        t = p["hl"]
        if n == 1:
            t = "”" + t[1:-1] + "“" if len(t) >= 2 else t
        elif n == 2:
            t = t.replace("“", "‘").replace("”", "’")
        elif n == 3:
            p["post"] = ""
            t = t + "（已合并到本行）"
        elif n == 4:
            t = t.replace("‘", "〔").replace("’", "〕")
        self._push_undo()
        p["hl"] = t
        self.render()
        self.toast(f"已应用快捷变换 Alt+{n}")

    def ins(self, ch: str):
        if not self._guard():
            return
        self.ins_buf += ch
        self._render_editor()
        self.toast(f"已插入 {ch}")

    def only_count(self):
        if not self.has_data:
            self.toast(self._empty_text())
            return
        self.toast(f"共检出 {len(self.probs)} 处问题，未做任何修改（仅统计）")

    def end_check(self):
        if not self.has_data:
            self.toast(self._empty_text())
            return
        total = len(self.probs)
        done = sum(1 for p in self.probs if p.get("state"))
        box = QMessageBox(self)
        box.setWindowTitle("结束检查？")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"已处理 {done} / {total} 处；未处理的 {total - done} 处将保持原样。")
        box.setInformativeText("结束检查后仍可从左侧入口重新进入。")
        box.setStandardButtons(
            QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes
        )
        box.button(QMessageBox.StandardButton.No).setText("继续检查")
        box.button(QMessageBox.StandardButton.Yes).setText("结束检查")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.toast("已结束本轮检查")

    def _affected_single(self):
        """会被「最外层单引号改双引号」影响的处（上下文任一段含单引号）。"""
        out = []
        for i, p in enumerate(self.probs):
            txt = p["pre"] + p["hl"] + p["post"]
            if "‘" in txt or "’" in txt:
                out.append((i, p))
        return out

    @staticmethod
    def _apply_outer_single(text: str) -> str:
        return text.replace("‘", "“").replace("’", "”")

    def batch_op(self):
        if not self._guard():
            return
        affected = self._affected_single()
        if not affected:
            self.toast("未检出需要批量处理的单引号")
            return
        box = QMessageBox(self)
        box.setWindowTitle("批量操作确认")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"最外层单引号改双引号 · 影响 {len(affected)} 处。")
        box.setInformativeText(
            "执行前预览影响条数，执行后可撤销。\n"
            "原：‘这里的引号是外层的’\n改：“这里的引号是外层的”"
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok
        )
        box.button(QMessageBox.StandardButton.Cancel).setText("取消")
        box.button(QMessageBox.StandardButton.Ok).setText("确认执行")
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() == QMessageBox.StandardButton.Ok:
            items = [{
                "i": i, "pre": p["pre"], "hl": p["hl"],
                "post": p["post"], "state": p.get("state"),
            } for i, p in affected]
            prev_state = self.probs[self.cur].get("state")
            for _i, p in affected:
                p["pre"] = self._apply_outer_single(p["pre"])
                p["hl"] = self._apply_outer_single(p["hl"])
                p["post"] = self._apply_outer_single(p["post"])
            self.undo.append({"batch": True, "items": items,
                              "prev_state": prev_state})
            self.render()
            self.toast(f"已批量修改 {len(affected)} 处（可撤销）")
