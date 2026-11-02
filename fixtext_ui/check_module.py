"""
FixText V1 · 检查问题模块（M4-EX.6-R2）
=====================================

对照合并版原型 §8 四态状态机重建：
空态（无书）→ 待检查 → 检查中（可取消）→ 结果态（含 0 检出「检查通过」）。

一态一键：开始检查 / 取消 / 重新检查（已删「只统计不修复」「结束检查」）。
自扫当前书正文（不读校正报告）；7 条规则接 R1 引擎配置接口并持久化。
逐处修复写回书的当前文本；「按已启用规则修复全部」预览→确认→可撤销。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer, QThread, QSize
from PySide6.QtGui import (
    QFont, QColor, QBrush, QTextCursor, QTextCharFormat, QShortcut, QKeySequence,
    QIcon,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QScrollArea, QFrame, QMessageBox, QCheckBox, QSizePolicy, QProgressBar,
)

import fixtext_check as checkdata
from fixtext_tokens import c, sp
from icons import icon, has_icon, pixmap
from fixtext_widgets import (
    Card, Switch, Pill, FieldRow, EmptyState, hline, px, page_head_shell, PrimaryButton,
    enable_chrome, make_label,
)

# ---------------------------------------------------------------------------
# 状态机 / 规则 UI
# ---------------------------------------------------------------------------

PHASE_EMPTY = "empty"
PHASE_READY = "ready"
PHASE_RUNNING = "running"
PHASE_RESULT = "result"

CHECKS = [
    ("缺左引号 / 缺右引号", "配对栈中发现未闭合或多余", ("缺左引号", "缺右引号")),
    ("引号交叉错乱",       "双套内又出现独立双引号",    ("引号交叉错乱",)),
    ("空引号",             "成对出现但内容为空",        ("空引号",)),
    ("跨行未闭合",         "向下最多探测 100 行",       ("多层嵌套未闭合",)),
    ("英文撇号误报过滤",   "前后为字母的撇号不计错",    ("其他引号问题",)),
]

#: 与 R1 RULE_IDS / 原型面板对齐（#6 名「补右引号」）
RULE_UI: tuple[tuple[str, str, str], ...] = (
    ("nested_doubles", "双套双引号改单引号", "外层双引号内再出现双引号时，把内层改为单引号"),
    ("reverted_quotations", "写反引号反转", "左右引号写反时调换"),
    ("repeated_quotations", "连续同向引号归一", "连续两个左 / 右引号收回一个"),
    ("sole_right_double", "句尾孤立右双引号移除", "句末无配对的右双引号删除"),
    ("sole_right_single", "句尾孤立右单引号移除", "句末无配对的右单引号删除"),
    ("missing_left_double", "补左引号", "缺左引号处补入"),
    ("missing_right_double", "补右引号", "在段落末尾补上缺失的右引号"),
)

PAGE_SIZE = 40


def _vendor_path() -> Path:
    try:
        from fixtext_paths import pkg_root
        return pkg_root() / "pipeline" / "vendor"
    except Exception:  # pragma: no cover
        return Path(__file__).resolve().parent.parent / "pipeline" / "vendor"


def _load_engine():
    v = _vendor_path()
    if str(v) not in sys.path:
        sys.path.insert(0, str(v))
    from fixtext_quotation.fixer import QuotationFixer, fix_text
    from fixtext_quotation.rules import (
        QuotationFixRules, load_fix_rules, save_fix_rules, default_rules_path,
    )
    return QuotationFixer, fix_text, QuotationFixRules, load_fix_rules, save_fix_rules, default_rules_path


# ---------------------------------------------------------------------------
# 问题清单行
# ---------------------------------------------------------------------------

class ProblemRow(QFrame):
    clicked = Signal(int)
    addRequested = Signal(int)

    def __init__(self, idx: int, p: dict, selected: bool, parent=None):
        super().__init__(parent)
        self.idx = idx
        state = p.get("state")
        self.setObjectName("ProblemRow")
        # 选中态底色/边框交给 fixtext.qss 的 #ProblemRow[selected="true"]
        self.setProperty("selected", "true" if selected else "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        hl = QHBoxLayout(self)
        hl.setContentsMargins(10, 9, 10, 9)
        hl.setSpacing(10)

        no = make_label(
            f"L{p['line']}", size="xs", color="neutral.500", weight="bold", mono=True)
        hl.addWidget(no)

        tone = "neutral.400" if state else "neutral.800"
        t = make_label(p["type"], size="sm", color=tone, weight="semibold")
        hl.addWidget(t)

        ctx = make_label(
            p["pre"] + p["hl"] + p["post"], size="xs", color="neutral.500", mono=True)
        ctx.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        hl.addWidget(ctx, 1)

        if state == "fixed":
            badge = Pill("已修复", "ok")
        elif state == "skip":
            badge = Pill("已跳过", "neutral")
        else:
            badge = Pill("待确认", "warn")
        hl.addWidget(badge)

        self.add_btn = QPushButton("词库")
        self.add_btn.setObjectName("LinkBtn")
        self.add_btn.setIcon(icon("plus", c("primary.600"), 14))
        self.add_btn.setIconSize(QSize(14, 14))
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setToolTip("把这一处的写法加入「我的词库」，下次校正自动纠正")
        self.add_btn.setAccessibleName("加入词库")
        self.add_btn.clicked.connect(
            lambda _=False, i=idx: self.addRequested.emit(i))
        hl.addWidget(self.add_btn)

    def mousePressEvent(self, event):
        self.clicked.emit(self.idx)
        super().mousePressEvent(event)


class _ScanWorker(QThread):
    """后台扫描当前书文本。"""

    finished_ok = Signal(object)
    finished_err = Signal(str)

    def __init__(self, text: str, book: str, path: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._book = book
        self._path = path
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            report = checkdata.scan_text(
                self._text, book=self._book, source_path=self._path)
            if self._cancel:
                return
            self.finished_ok.emit(report)
        except Exception as exc:  # noqa: BLE001
            if not self._cancel:
                self.finished_err.emit(str(exc))


# ---------------------------------------------------------------------------
# 模块
# ---------------------------------------------------------------------------

class CheckModule(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.phase = PHASE_EMPTY
        self.report: dict | None = None
        self.probs: list[dict] = []
        self.cur = 0
        self._page = 0
        self.ins_buf = ""
        self.undo: list = []
        self.basis_labels: list = []
        self._marks: dict[str, str] = {}
        self._run_dir: str = ""
        self.vocab_store = None
        self.last_add_point: int = 0

        self._text_path: str = ""
        self._book_name: str = ""
        self._book_ext: str = "txt"
        self._book_text: str = ""
        self._rules_path: Path | None = None
        self._worker: _ScanWorker | None = None
        self._text_undo_stack: list[str] = []  # 整书正文撤销（写回用）

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_status)

        self._build()
        self._load_rules_into_ui()
        self.set_book("", "")
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

        self.empty_state = EmptyState(
            "search", "还没有可检查的书",
            "请先导入一本书，之后才能逐处检查标点与引号问题。"
            "当前页面在有书状态下展示；无书时仅显示此引导。")
        root.addWidget(self.empty_state)

        self._content_w = QWidget()
        cl = QVBoxLayout(self._content_w)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(px(sp("4")))
        cl.addWidget(self._bookbar())
        cl.addWidget(self._top_bar())
        self.pass_banner = QLabel("检查通过，未发现引号问题")
        self.pass_banner.setObjectName("PassBanner")
        self.pass_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pass_banner.setVisible(False)
        cl.addWidget(self.pass_banner)
        self._result_w = QWidget()
        rl = QVBoxLayout(self._result_w)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(px(sp("4")))
        rl.addLayout(self._columns())
        rl.addWidget(self._action_bar())
        rl.addWidget(self._rules_card())
        rl.addWidget(self._batch_card())
        rl.addWidget(self._checks_card())
        cl.addWidget(self._result_w)
        root.addWidget(self._content_w)

        root.addWidget(self._legend())
        root.addWidget(self._status_label())
        self._apply_phase()

    def _head(self) -> QWidget:
        shell, body = page_head_shell()
        hl = QHBoxLayout(body)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)
        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel("检查问题")
        title.setObjectName("PageTitle")
        sub = QLabel(
            "引号配对检查 + 逐处交互修复。检查结果可定位、可单独处理、可撤销。")
        sub.setObjectName("PageSub")
        col.addWidget(title)
        col.addWidget(sub)
        hl.addLayout(col, 1)
        return shell

    def _card(self, *args, **kwargs) -> Card:
        card = Card(*args, **kwargs)
        if card.basis is not None:
            self.basis_labels.append(card.basis)
        return card

    def _bookbar(self) -> Card:
        card = self._card(basis="§2.2 入口③ · 逐处人工确认")
        hl = QHBoxLayout()
        hl.setSpacing(14)
        ico = QLabel()
        ico.setObjectName("MarkIco")
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setFixedSize(40, 40)
        ico.setPixmap(pixmap("book", 28, c("neutral.600")))
        hl.addWidget(ico)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.book_name = make_label("", size="md", color="neutral.900", weight="bold")
        self.book_meta = make_label("", size="xs", color="neutral.500")
        col.addWidget(self.book_name)
        col.addWidget(self.book_meta)
        hl.addLayout(col)
        hl.addStretch(1)
        hl.addWidget(Pill("编辑器可改文并保存回写", "info"))
        card.body_l.addLayout(hl)
        return card

    def _top_bar(self) -> QFrame:
        """待检查 / 运行 / 结果：一态一键主按钮（原型 .chk-top 渐变横幅）。"""
        # M5-EX.7 §10 Step4：与校正/导出 .hero 同规 padding/gap/大按钮
        bar = QFrame()
        bar.setObjectName("ChkTop")
        enable_chrome(bar)
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(28, 26, 28, 26)
        hl.setSpacing(24)

        self._ready_text = QWidget()
        self._ready_text.setObjectName("ChkReady")
        rt = QVBoxLayout(self._ready_text)
        rt.setContentsMargins(0, 0, 0, 0)
        rt.setSpacing(6)
        t1 = QLabel("检查引号问题")
        t1.setProperty("role", "title")
        t2 = QLabel("扫描当前书的引号配对，逐处确认修复；可定位、可单独处理、可撤销。")
        t2.setWordWrap(True)
        rt.addWidget(t1)
        rt.addWidget(t2)
        hl.addWidget(self._ready_text, 1)

        self.stats = QLabel("")
        self.stats.setProperty("role", "stats")
        hl.addWidget(self.stats, 1)

        self._run_box = QWidget()
        self._run_box.setObjectName("ChkRun")
        rb = QVBoxLayout(self._run_box)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.setSpacing(4)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # busy
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.run_tip = QLabel("正在扫描引号配对…")
        self.run_tip.setProperty("role", "hint")
        rb.addWidget(self.progress)
        rb.addWidget(self.run_tip)
        hl.addWidget(self._run_box, 1)

        self.main_btn = QPushButton("开始检查")
        self.main_btn.setObjectName("HeroBtn")
        self.main_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main_btn.setMinimumHeight(50)
        self.main_btn.setIcon(icon("search", c("neutral.700"), 18))
        self.main_btn.setIconSize(QSize(18, 18))
        # 大按钮配色交给 fixtext.qss 的 #HeroBtn（原内联收归）
        self.main_btn.clicked.connect(self.on_main)
        hl.addWidget(self.main_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return bar

    def _columns(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(px(sp("4")))

        left = QVBoxLayout()
        left.setSpacing(px(sp("4")))
        probs_card = self._card(
            "问题清单", "点击任一问题，右侧定位", collapsible=True, open_=True,
            basis="§2.7.4 · 问题清单 · 点击定位")
        self.probs_title = probs_card
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFixedHeight(300)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setObjectName("ProbScroll")
        holder = QWidget()
        holder.setObjectName("ProbScrollInner")
        self.prob_box = QVBoxLayout(holder)
        self.prob_box.setContentsMargins(0, 0, 0, 0)
        self.prob_box.setSpacing(6)
        sc.setWidget(holder)
        probs_card.body_l.addWidget(sc)
        probs_card.body_l.addLayout(self._pager())
        left.addWidget(probs_card)
        left.addStretch(1)

        right = QVBoxLayout()
        right.setSpacing(px(sp("4")))
        ed = self._card(
            "正文（当前问题上下文）", "可直接改文，保存后自动跳下一处",
            collapsible=True, open_=True,
            basis="§2.7.4 · 右栏编辑器 · 保存并下一处")
        ed.body_l.setSpacing(10)
        self.editor = QTextEdit()
        self.editor.setObjectName("CheckEditor")
        self.editor.setMinimumHeight(150)
        ed.body_l.addWidget(self.editor)
        self.advice = make_label("", size="sm", color="neutral.600", wrap=True)
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
        self.page_label = make_label("", size="xs", color="neutral.500")
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
        lab = make_label(text, size="sm", color="neutral.800", weight="bold")
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
        hl.addWidget(self._btn("撤销上一步", "BtnOutline", self.undo_last))
        card.body_l.addLayout(hl)
        return card

    def _rules_card(self) -> Card:
        card = self._card(
            "自动修复规则", "7 条，逐条可开关", collapsible=True, open_=False,
            basis="§2.7.4 · 7 条规则逐条可开关")
        self.rule_switches: dict[str, Switch] = {}
        for i, (rid, name, desc) in enumerate(RULE_UI):
            if i:
                card.body_l.addWidget(hline())
            sw = Switch(True)
            sw.toggled.connect(lambda _on, r=rid: self._on_rule_toggled(r))
            self.rule_switches[rid] = sw
            card.body_l.addWidget(FieldRow(i + 1, name, desc, control=sw))
        card.body_l.addWidget(hline())
        foot = QHBoxLayout()
        tip = make_label("7 条规则逐条可开关，配置按用户持久化。", size="xs", color="neutral.500")
        foot.addWidget(tip)
        foot.addStretch(1)
        foot.addWidget(self._btn("保存配置", "BtnGhost", self.save_rules_config))
        card.body_l.addLayout(foot)
        return card

    def _batch_card(self) -> Card:
        card = self._card(
            "批量操作", "执行前预览影响条数", collapsible=True, open_=True,
            basis="§2.7.4 · 批量操作二次确认 + 预览")
        card.body_l.addWidget(FieldRow(
            None, "最外层单引号批量改双引号", "把最外层的 ‘…’ 统一改为 “…”",
            control=self._btn("执行", "BtnOutline", self.batch_op),
            name_width=190))
        card.body_l.addWidget(hline())
        card.body_l.addWidget(FieldRow(
            None, "按已启用规则修复全部",
            "用当前已开启的规则批量修复全部问题（可撤销）",
            control=self._btn("执行", "BtnOutline", self.batch_fix_all),
            name_width=190))
        return card

    def _checks_card(self) -> Card:
        """检查项说明卡置底（原型参考区）。"""
        checks = self._card(
            "检查项（自动执行）", collapsible=True, open_=True,
            basis="§2.7.4 · 检查项自动执行无开关")
        self._check_rows: list[FieldRow] = []
        for i, (name, desc, _kinds) in enumerate(CHECKS):
            if i:
                checks.body_l.addWidget(hline())
            fr = FieldRow(i + 1, name, desc, chip="—")
            checks.body_l.addWidget(fr)
            self._check_rows.append(fr)
        return checks

    def _legend(self) -> QLabel:
        return make_label(
            "「逐处人工确认」是这个模块的核心价值，不能只做「一键修复全部」。",
            size="xs", color="neutral.500", wrap=True)

    def _status_label(self) -> QLabel:
        self.status = QLabel("")
        self.status.setObjectName("CheckToast")
        self.status.setVisible(False)
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        return self.status

    # ------------------------------------------------------------------ 书 / 相位

    @property
    def has_book(self) -> bool:
        return bool(self._text_path)

    @property
    def has_data(self) -> bool:
        """有可逐处处理的条目（结果态或兼容 set_report 注入）。"""
        if not self.probs:
            return False
        if self.phase == PHASE_RESULT:
            return True
        return bool(self.report and self.report.get("ok"))

    @property
    def is_pass(self) -> bool:
        return (
            self.phase == PHASE_RESULT
            and bool(self.report and self.report.get("ok"))
            and not self.probs
        )

    def set_rules_path(self, path: str | Path | None) -> None:
        """用户区规则文件；``None`` 时用 workspace 默认。"""
        self._rules_path = Path(path) if path else None
        self._load_rules_into_ui()

    def set_book(
        self,
        text_path: str,
        book_name: str = "",
        *,
        book_ext: str = "txt",
        rules_dir: str | Path | None = None,
    ) -> None:
        """挂当前书。无路径 → 空态；有路径 → 待检查（清掉上一轮结果）。"""
        self._cancel_worker()
        self._text_path = str(text_path or "")
        self._book_name = book_name or (
            Path(self._text_path).parent.name if self._text_path else "")
        self._book_ext = (book_ext or "txt").lstrip(".")
        if rules_dir is not None:
            _, _, _, _, _, default_rules_path = _load_engine()
            self._rules_path = default_rules_path(rules_dir)
        self.report = None
        self.probs = []
        self.cur = 0
        self._page = 0
        self.undo = []
        self._text_undo_stack = []
        self.ins_buf = ""
        self._book_text = ""
        if self._text_path:
            try:
                self._book_text = Path(self._text_path).read_text(encoding="utf-8")
            except Exception:
                self._book_text = ""
            self.phase = PHASE_READY
        else:
            self.phase = PHASE_EMPTY
        self._load_rules_into_ui()
        self._apply_phase()
        self.render()

    def set_report(self, report: dict | None) -> None:
        """兼容旧注入：直接进入结果态（测试 / 过渡）。"""
        self._cancel_worker()
        if not report or not report.get("ok"):
            if self.has_book:
                self.phase = PHASE_READY
                self.report = None
                self.probs = []
            else:
                self.phase = PHASE_EMPTY
                self.report = None
                self.probs = []
            self._apply_phase()
            self.render()
            return
        self.report = report
        self._run_dir = str(report.get("run_dir") or "")
        cf = str(report.get("checked_file") or "")
        if cf and not self._text_path:
            self._text_path = cf
            try:
                self._book_text = Path(cf).read_text(encoding="utf-8")
            except Exception:
                pass
        if report.get("book"):
            self._book_name = str(report["book"])
        self.probs = [dict(it) for it in report.get("items") or []]
        self._page = 0
        self.cur = 0
        self.undo = []
        self.ins_buf = ""
        self.set_marks(self._marks)
        self.phase = PHASE_RESULT
        self._apply_phase()
        self.render()

    def set_marks(self, marks: dict[str, str] | None = None) -> None:
        self._marks = dict(marks or {})
        for it in self.probs:
            state = self._marks.get(checkdata.mark_key(it))
            it["state"] = state if state in ("fixed", "skip") else None

    def set_empty(self, reason: str = "") -> None:
        self.set_book("", "")
        self._empty_reason = reason

    def _apply_phase(self) -> None:
        is_empty = self.phase == PHASE_EMPTY or not self.has_book
        self.empty_state.setVisible(is_empty)
        self._content_w.setVisible(not is_empty)
        if is_empty:
            return

        running = self.phase == PHASE_RUNNING
        ready = self.phase == PHASE_READY
        result = self.phase == PHASE_RESULT

        self._ready_text.setVisible(ready)
        self._run_box.setVisible(running)
        self.stats.setVisible(result)
        self.pass_banner.setVisible(self.is_pass)
        # 有问题时才显示清单/编辑器等；通过态只留横幅 + 顶栏
        show_work = result and not self.is_pass
        self._result_w.setVisible(show_work)

        if ready:
            self.main_btn.setText("开始检查")
            self.main_btn.setIcon(icon("search", c("neutral.700"), 18))
        elif running:
            self.main_btn.setText("取消")
            self.main_btn.setIcon(QIcon())
        else:
            self.main_btn.setText("重新检查")
            self.main_btn.setIcon(QIcon())
        # 始终 HeroBtn（渐变横幅上的白底大按钮）
        self.main_btn.setObjectName("HeroBtn")
        self.main_btn.style().unpolish(self.main_btn)
        self.main_btn.style().polish(self.main_btn)

        name = self._book_name or "当前书"
        self.book_name.setText(f"《{name}》.{self._book_ext}")
        if ready:
            self.book_meta.setText("待检查")
        elif running:
            self.book_meta.setText("检查中…")
        elif self.is_pass:
            self.book_meta.setText("检查通过")
        else:
            self.book_meta.setText(f"共 {len(self.probs)} 处待确认")

    # ------------------------------------------------------------------ 规则

    def _rules_file(self) -> Path:
        _, _, _, _, _, default_rules_path = _load_engine()
        if self._rules_path is not None:
            return self._rules_path
        try:
            from fixtext_paths import pkg_root
            return default_rules_path(pkg_root() / "workspace")
        except Exception:
            return default_rules_path(Path("workspace"))

    def _load_rules_into_ui(self) -> None:
        _, _, _, load_fix_rules, _, _ = _load_engine()
        rules = load_fix_rules(self._rules_file())
        for rid, sw in self.rule_switches.items():
            sw.blockSignals(True)
            sw.setChecked(bool(getattr(rules, rid, True)))
            sw.blockSignals(False)

    def current_rules(self):
        _, _, QuotationFixRules, _, _, _ = _load_engine()
        d = {rid: sw.isChecked() for rid, sw in self.rule_switches.items()}
        return QuotationFixRules.from_mapping(d)

    def _on_rule_toggled(self, _rid: str) -> None:
        # 即时持久化，避免只点开关却忘了「保存配置」
        self.save_rules_config(silent=True)
        self._refresh_advice_for_rules()

    def save_rules_config(self, silent: bool = False) -> None:
        _, _, _, _, save_fix_rules, _ = _load_engine()
        save_fix_rules(self.current_rules(), self._rules_file())
        if not silent:
            self.toast("规则配置已保存")

    def _refresh_advice_for_rules(self) -> None:
        """关闭的规则：对应条目去掉自动改法建议（不参与修复建议）。"""
        enabled = set(self.current_rules().enabled_ids())
        for p in self.probs:
            rid = p.get("rule_id")
            if rid and rid not in enabled:
                p["_advice_blocked"] = True
            else:
                p.pop("_advice_blocked", None)
        if self.phase == PHASE_RESULT and self.probs:
            self._render_editor()

    def rule_allows_item(self, p: dict) -> bool:
        rid = p.get("rule_id")
        if not rid:
            return True  # 无映射规则的人工项仍可手动处理
        return bool(getattr(self.current_rules(), rid, False))

    # ------------------------------------------------------------------ 扫描

    def on_main(self) -> None:
        if self.phase == PHASE_RUNNING:
            self.cancel_check()
        else:
            self.start_check()

    def start_check(self, *, sync: bool = False) -> None:
        """开始 / 重新检查。``sync=True`` 供单测同步跑完。"""
        if not self.has_book:
            self.toast("请先导入一本书")
            return
        if self.phase == PHASE_RUNNING and not sync:
            return
        try:
            self._book_text = Path(self._text_path).read_text(encoding="utf-8")
        except Exception as exc:
            self.toast(f"读不到当前书正文：{exc}")
            return

        self.phase = PHASE_RUNNING
        self._apply_phase()
        self.run_tip.setText("正在扫描引号配对…")

        if sync:
            report = checkdata.scan_text(
                self._book_text, book=self._book_name,
                source_path=self._text_path)
            self._on_scan_ok(report)
            return

        self._cancel_worker()
        self._worker = _ScanWorker(
            self._book_text, self._book_name, self._text_path, self)
        self._worker.finished_ok.connect(self._on_scan_ok)
        self._worker.finished_err.connect(self._on_scan_err)
        self._worker.start()

    def cancel_check(self) -> None:
        self._cancel_worker()
        self.phase = PHASE_READY
        self.report = None
        self.probs = []
        self._apply_phase()
        self.render()
        self.toast("已取消检查")

    def _cancel_worker(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(800)
            self._worker = None

    def _on_scan_ok(self, report: object) -> None:
        self._worker = None
        if not isinstance(report, dict):
            self._on_scan_err("扫描结果异常")
            return
        self.report = report
        self.probs = [dict(it) for it in report.get("items") or []]
        self.cur = 0
        self._page = 0
        self.undo = []
        self.ins_buf = ""
        self._refresh_advice_for_rules()
        self.phase = PHASE_RESULT
        self._apply_phase()
        self.render()
        n = len(self.probs)
        if n == 0:
            self.toast("检查通过，未发现引号问题")
        else:
            self.toast(f"检查完成，共 {n} 处待确认")

    def _on_scan_err(self, msg: str) -> None:
        self._worker = None
        self.phase = PHASE_READY
        self._apply_phase()
        self.toast(f"检查失败：{msg}")

    # ------------------------------------------------------------------ 写回

    def _write_book_text(self, text: str) -> bool:
        if not self._text_path:
            return False
        try:
            Path(self._text_path).write_text(text, encoding="utf-8", newline="\n")
            self._book_text = text
            return True
        except Exception as exc:
            self.toast(f"写回失败：{exc}")
            return False

    def _push_text_undo(self) -> None:
        self._text_undo_stack.append(self._book_text)

    def _replace_line_in_book(self, line_no: int, new_line_body: str) -> str | None:
        """替换 1-based 行内容（保留原行尾换行形态），返回新全文。"""
        return self._replace_lines_in_book({line_no: new_line_body})

    def _replace_lines_in_book(self, updates: dict[int, str]) -> str | None:
        """按 1-based 行号批量替换（保留原行尾 \\r 形态），返回新全文。"""
        raw = self._book_text
        parts = raw.split("\n")
        for line_no, new_line_body in updates.items():
            idx = int(line_no) - 1
            if idx < 0 or idx >= len(parts):
                return None
            body = str(new_line_body).replace("\r", "").replace("\n", "")
            had_cr = "\r" in (parts[idx] if idx < len(parts) else "")
            parts[idx] = body + ("\r" if had_cr else "")
        return "\n".join(parts)

    # ------------------------------------------------------------------ 渲染

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

    def toast(self, msg: str):
        self.status.setText(msg)
        self.status.setVisible(True)
        self._toast_timer.start(2600)

    def _hide_status(self):
        self.status.setVisible(False)

    def render(self):
        self._apply_phase()
        if self.phase != PHASE_RESULT or self.is_pass:
            return
        self._follow_cursor()
        self._render_checks()
        self._render_probs()
        self._render_editor()
        self._render_stats()

    def _follow_cursor(self):
        if not self.probs:
            return
        page = self.cur // PAGE_SIZE
        if page != self._page:
            self._page = page

    @property
    def pages(self) -> int:
        return max(1, math.ceil(len(self.probs) / PAGE_SIZE)) if self.probs else 1

    def _render_checks(self):
        for i, (_name, _desc, kinds) in enumerate(CHECKS):
            n = sum(1 for p in self.probs if p.get("type") in kinds)
            chip = f"{n} 处" if self.probs else "—"
            if i < len(self._check_rows):
                self._check_rows[i].set_chip(chip)

    def _render_stats(self):
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
        if not self.probs:
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

    def _update_pager(self):
        total = self.pages
        if not self.probs:
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
        if not self.probs:
            return
        target = self._page + delta
        if target < 0 or target >= self.pages:
            return
        self._page = target
        self._render_probs()

    def _render_editor(self):
        if not self.probs:
            self.editor.setPlainText("")
            self.advice.setText("")
            return
        self.editor.setReadOnly(False)
        p = self.probs[self.cur]
        prefix = f"L{p['line']}   "
        # M5-EX.2 / BUG-5：前段 / 问题段 / 后段，空行分隔
        before = str(p.get("seg_before") or "")
        problem = str(p.get("seg_problem") or (p.get("pre", "") + p.get("hl", "") + p.get("post", "")))
        after = str(p.get("seg_after") or "")
        body = f"{before}\n\n{problem}\n\n{after}"
        self.editor.setPlainText(prefix + body + self.ins_buf)
        advice = p.get("advice") or ""
        if p.get("_advice_blocked"):
            advice = "对应自动修复规则已关闭，可手动改文或开启规则后再修。"
        self.advice.setText(advice)
        length = len(p.get("hl") or "")
        if length:
            # 高亮落在问题段内的 hl；问题段起点 = 前缀 + 前段 + 空行
            start = len(prefix) + len(before) + 2 + len(str(p.get("pre") or ""))
            sel = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            bg = c("success.bg") if p.get("state") == "fixed" else c("warning.bg")
            fmt.setBackground(QBrush(QColor(bg)))
            fmt.setFontWeight(QFont.Weight.Bold)
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SingleUnderline)
            fmt.setUnderlineColor(
                QColor(c("success") if p.get("state") == "fixed" else c("warning")))
            sel.format = fmt
            cur = self.editor.textCursor()
            cur.setPosition(start)
            cur.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cur
            self.editor.setExtraSelections([sel])
        else:
            self.editor.setExtraSelections([])

    # ------------------------------------------------------------------ 词库（保留）

    def set_vocab_store(self, store) -> None:
        self.vocab_store = store

    def problem_candidate(self, i: int) -> dict:
        p = self.probs[i]
        hl = str(p.get("hl") or "").strip()
        fixed = checkdata.apply_action(p).strip()
        pre = str(p.get("pre") or "").rstrip()
        post = str(p.get("post") or "").lstrip()
        word, value, scope = hl, fixed, "单处"
        if self.vocab_word_blocker(hl):
            if pre:
                word, value = pre + hl, pre + fixed
                scope = "整句"
            elif post:
                word, value = hl + post, fixed + post
                scope = "整句"
        return dict(
            word=word, value=(value or word),
            type=("缺字漏字" if (p.get("action") or {}).get("mode") in
                  ("prepend", "append") else "错词校正"),
            count=1, scope=scope,
            blocked=self.vocab_word_blocker(word),
            note=f"检查页第 {p.get('line')} 行 · {p.get('type') or ''}".strip(" ·"),
        )

    @staticmethod
    def vocab_word_blocker(word: str) -> str:
        w = str(word or "").strip()
        if not w:
            return "这一处没有可加入词库的写法"
        if len(w) < 2:
            return ("这一处只有一个标点、前后也没有上下文，收进词库会让全书同类"
                    "标点一起变；请用行内修复逐处处理，或到「词库管理」手动新增")
        if not any(ch.isalnum() for ch in w):
            return ("这一处全是标点，收进词库会让全书同类标点一起变；"
                    "请用行内修复逐处处理，或到「词库管理」手动新增")
        return ""

    def add_problem_to_vocab(self, i: int) -> dict | None:
        if not self._guard() or not (0 <= i < len(self.probs)):
            return None
        if self.vocab_store is None:
            self.toast("词库暂不可用，请到「词库管理」页手动新增这一条")
            return None
        cand = self.problem_candidate(i)
        if cand.get("blocked"):
            self.toast(cand["blocked"])
            return None
        if cand["word"] == cand["value"]:
            self.toast("这一处还没有可靠的自动改法，暂不建议加入词库")
            return None
        box = QMessageBox(self)
        box.setWindowTitle("加入词库预览")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("把这一处写法加入「我的词库」？")
        box.setInformativeText(
            f"词条：{cand['word']}\n替换值：{cand['value']}\n"
            f"类型：{cand['type']}\n生效范围：{cand.get('scope') or '单处'}\n\n"
            "加入后下次校正同类写法自动生效，加入动作可以撤销。")
        box.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok)
        box.button(QMessageBox.StandardButton.Cancel).setText("取消")
        box.button(QMessageBox.StandardButton.Ok).setText("确认加入")
        if box.exec() != QMessageBox.StandardButton.Ok:
            return None
        try:
            res = self.vocab_store.add_book_words(
                [cand], self._book_name or "")
        except Exception as exc:
            self.toast(f"没有加入：{exc}")
            return None
        added = int(res.get("added") or 0)
        self.last_add_point = int(res.get("point_id") or 0)
        if added:
            self.toast(f"已加入「{cand['word']}」到「我的词库」，可撤销")
        else:
            self.toast("没有加入：词库规则跳过或已存在")
        return res

    # ------------------------------------------------------------------ 交互

    def _guard(self) -> bool:
        if not self.probs:
            self.toast("请先完成一次检查" if self.has_book else self._empty_text())
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
        p = self.probs[self.cur]
        self.undo.append({
            "i": self.cur, "pre": p["pre"], "hl": p["hl"],
            "post": p["post"], "state": p.get("state"),
        })

    def _set_state(self, state: str | None):
        self.probs[self.cur]["state"] = state
        if self._run_dir:
            key = checkdata.mark_key(self.probs[self.cur])
            if state:
                self._marks[key] = state
            else:
                self._marks.pop(key, None)
            checkdata.save_marks(self._run_dir, self._marks)

    def fix_here(self):
        """逐处修复：按已启用规则改行并写回当前书文本。"""
        if not self._guard():
            return
        p = self.probs[self.cur]
        if p.get("rule_id") and not self.rule_allows_item(p):
            self.toast("对应自动修复规则已关闭，请开启后再修或手动改文")
            return

        line_no = int(p["line"])
        # 取原行
        parts = self._book_text.split("\n")
        if line_no < 1 or line_no > len(parts):
            self.toast("定位不到这一行")
            return
        old_line = parts[line_no - 1]
        # 优先用 R1 引擎对该行跑启用规则；否则用条目 action
        _, _, _, _, _, _ = _load_engine()
        from fixtext_quotation.fixer import apply_rules_to_error_lines

        line_text = old_line if old_line.endswith("\n") else old_line + "\n"
        # 构造仅含该行的迷你文本以触发规则（报错行集合）
        mini = line_text
        fixed_mini, actions = apply_rules_to_error_lines(
            mini, self.current_rules(), {1}, round_index=1)
        new_body = fixed_mini.rstrip("\n").replace("\r", "")
        used_engine = bool(actions) and fixed_mini != mini

        if not used_engine:
            action = p.get("action")
            if not action:
                self.toast("这处没有可靠的自动改法，需要人工判断后再改")
                return
            # 在 hl 位置套用 action（基于上下文片段）
            fixed_hl = checkdata.apply_action(p)
            # 尝试在整行中替换 hl 一次
            if p["hl"] and p["hl"] in old_line.replace("\r", ""):
                new_body = old_line.replace("\r", "").replace(p["hl"], fixed_hl, 1)
            else:
                new_body = p["pre"] + fixed_hl + p["post"]

        self._push_undo()
        self.undo[-1]["wrote"] = True
        self._push_text_undo()
        new_text = self._replace_line_in_book(line_no, new_body)
        if new_text is None or not self._write_book_text(new_text):
            self.undo.pop()
            if self._text_undo_stack:
                self._text_undo_stack.pop()
            return

        p["hl"] = checkdata.apply_action(p) if p.get("action") else p["hl"]
        if used_engine:
            p["hl"] = new_body[:40]
            p["pre"] = ""
            p["post"] = ""
        self._set_state("fixed")
        line = p["line"]
        self.render()
        self.next_issue()
        self.toast(f"已修复并写回 L{line}")

    def skip_here(self):
        if not self._guard():
            return
        self._push_undo()
        self._set_state("skip")
        self.render()
        self.next_issue()
        self.toast("已跳过，记入跳过清单")

    def save_and_next(self):
        """把编辑器三段正文写回前/问题/后行，再跳下一处。"""
        if not self._guard():
            return
        p = self.probs[self.cur]
        raw = self.editor.toPlainText()
        body = raw
        if body.startswith(f"L{p['line']}"):
            body = body.split("   ", 1)[-1] if "   " in body else body
        # 去掉插入缓冲残留（界面追加的临时内容）
        if self.ins_buf and body.endswith(self.ins_buf):
            body = body[: -len(self.ins_buf)]
        parts = body.split("\n\n", 2)
        while len(parts) < 3:
            parts.append("")
        seg_before, seg_problem, seg_after = parts[0], parts[1], parts[2]
        line_no = int(p["line"])
        updates: dict[int, str] = {line_no: seg_problem}
        if p.get("has_before"):
            updates[line_no - 1] = seg_before
        if p.get("has_after"):
            updates[line_no + 1] = seg_after
        self._push_undo()
        self.undo[-1]["wrote"] = True
        self._push_text_undo()
        new_text = self._replace_lines_in_book(updates)
        if new_text is None or not self._write_book_text(new_text):
            self.undo.pop()
            if self._text_undo_stack:
                self._text_undo_stack.pop()
            return
        p["seg_before"] = seg_before
        p["seg_problem"] = seg_problem
        p["seg_after"] = seg_after
        self._set_state("fixed")
        self.render()
        self.next_issue()
        self.toast("已保存回写，自动跳到下一处")

    def undo_last(self):
        if self.phase != PHASE_RESULT:
            self.toast("没有可撤销的操作")
            return
        # 优先整书正文撤销（写回类操作）
        if self._text_undo_stack and (not self.undo or self.undo[-1].get("text_batch")
                                      or self.undo[-1].get("wrote")):
            pass
        if not self.undo and not self._text_undo_stack:
            self.toast("没有可撤销的操作")
            return

        if self.undo and self.undo[-1].get("text_batch"):
            a = self.undo.pop()
            prev = a.get("prev_text", "")
            if prev and self._write_book_text(prev):
                self.toast("已撤销批量修复，正在重新检查…")
                self.start_check(sync=True)
            return

        if self._text_undo_stack and self.undo and self.undo[-1].get("wrote", True):
            # 逐处写回：恢复正文 + 条目状态
            a = self.undo.pop()
            prev = self._text_undo_stack.pop()
            self._write_book_text(prev)
            if 0 <= a["i"] < len(self.probs):
                p = self.probs[a["i"]]
                p["pre"] = a["pre"]
                p["hl"] = a["hl"]
                p["post"] = a["post"]
                p["state"] = a["state"]
                self.cur = a["i"]
            self.render()
            self.toast("已撤销上一步（正文已恢复）")
            return

        if not self.undo:
            if self._text_undo_stack:
                prev = self._text_undo_stack.pop()
                self._write_book_text(prev)
                self.toast("已撤销正文修改")
            return

        a = self.undo.pop()
        if a.get("batch"):
            for it in a["items"]:
                p = self.probs[it["i"]]
                p["pre"] = it["pre"]
                p["hl"] = it["hl"]
                p["post"] = it["post"]
            self.cur = a["items"][0]["i"]
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
        self.ins_buf = ""
        self.render()
        self.toast("已撤销上一步")

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

    # ------------------------------------------------------------------ 批量

    def _affected_single(self):
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
            "原：‘这里的引号是外层的’\n改：“这里的引号是外层的”")
        box.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok)
        box.button(QMessageBox.StandardButton.Cancel).setText("取消")
        box.button(QMessageBox.StandardButton.Ok).setText("确认执行")
        if box.exec() != QMessageBox.StandardButton.Ok:
            return
        items = [{
            "i": i, "pre": p["pre"], "hl": p["hl"],
            "post": p["post"], "state": p.get("state"),
        } for i, p in affected]
        for _i, p in affected:
            p["pre"] = self._apply_outer_single(p["pre"])
            p["hl"] = self._apply_outer_single(p["hl"])
            p["post"] = self._apply_outer_single(p["post"])
        self.undo.append({"batch": True, "items": items})
        self.render()
        self.toast(f"已批量修改 {len(affected)} 处（可撤销）")

    def batch_fix_all(self):
        """按已启用规则修复全部（预览条数 → 二次确认 → 写回 → 可撤销）。"""
        if self.phase != PHASE_RESULT:
            self.toast("请先完成一次检查")
            return
        rules = self.current_rules()
        on_n = len(rules.enabled_ids())
        if on_n == 0:
            self.toast("当前没有启用的规则")
            return

        # 预览：只统计 rule_id 落在启用集内、且尚未处理的条目
        enabled = set(rules.enabled_ids())
        candidates = [
            p for p in self.probs
            if not p.get("state")
            and (not p.get("rule_id") or p.get("rule_id") in enabled)
        ]
        # 引擎级预览：跑一遍看 actions
        _, fix_text, *_rest = _load_engine()
        preview = fix_text(self._book_text, rules, max_rounds=8)
        n_actions = len(preview.actions)
        n = max(len(candidates), n_actions)

        box = QMessageBox(self)
        box.setWindowTitle("按已启用规则修复全部")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"将用当前已启用的 {on_n} 条规则批量修复。")
        box.setInformativeText(
            f"预览影响约 <b>{n}</b> 处（引擎动作 {n_actions} 步）。"
            "执行后写回当前书正文，可撤销。")
        box.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok)
        box.button(QMessageBox.StandardButton.Cancel).setText("取消")
        box.button(QMessageBox.StandardButton.Ok).setText("确认执行")
        if box.exec() != QMessageBox.StandardButton.Ok:
            return

        prev = self._book_text
        if not self._write_book_text(preview.text):
            return
        self.undo.append({"text_batch": True, "prev_text": prev})
        self.toast(f"已按已启用规则修复（{n_actions} 步），正在重新检查…")
        self.start_check(sync=True)

    def _empty_text(self) -> str:
        return "还没有可检查的书。请先到「导入书籍」导入一本，再回来检查。"
