"""
FixText V1 · 导出结果模块（Qt 移植）
======================================

对照 `FixText_V1_导出结果_原型.html` **1:1 移植**，保持核心价值：
导出干净文件 → 自动附替换报告 → 内部同步基准（保证下轮统计不重复）。

结构：书源条 → 导出目标（TXT / EPUB 单选）→ 章节标题分级
      → 导出目录 → 替换报告（KV + diff + 无差异演示）→ 导出 hero → 结果卡。

设计依据：「显示设计依据」开关覆盖全部 7 个原型标注点，其中书源条与
      hero 不是 Card，单独挂同款 basis 标签在卡片外（其余 5 个随 Card 内置）。
条款号一律收进「显示设计依据」，正文不露 §。
复用部件见 `fixtext_widgets.py`（Card / Pill / RadioCard / ProgressDialog）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QComboBox, QCheckBox, QDialog, QSizePolicy, QFileDialog,
)

from fixtext_tokens import c, r, fs, FONT_MONO, FONT_WEIGHT
from fixtext_widgets import Card, Pill, RadioCard, ProgressDialog, hline


# ---------------------------------------------------------------------------
# 数据（与 HTML 原型同源）
# ---------------------------------------------------------------------------

BOOK = "《星河彼端》"
SOURCE = "EPUB"
HITS = 1284
LIB_COUNT = 3
DEFAULT_DIR = r"D:\FixText\导出\星河彼端"
REPORT_NAME = "替换报告_20261026.csv"

LEVELS = ["不处理", "一级", "两级", "三级"]


def _label(text: str, *, size: str = "sm", color: str = "neutral.800",
           weight: str | None = None, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(wrap)
    style = f"color:{c(color)};font-size:{fs(size)};background:transparent;"
    if weight:
        style += f"font-weight:{FONT_WEIGHT[weight]};"
    lab.setStyleSheet(style)
    return lab


# ---------------------------------------------------------------------------
# 模块
# ---------------------------------------------------------------------------

class ExportModule(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.basis_labels = []
        self.target = "epub"
        self.no_diff = False
        self.exp_dir = DEFAULT_DIR
        self._running = False
        self._result_basis = None

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_status)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        root.addWidget(self._header())  # 创建 self.basis_cb

        # 书源条 / hero 不是 Card，没有内置 basis——单独挂同款标签，保证
        # 「显示设计依据」开关能覆盖原型里这 2 个标注点（共 7 个）。
        self.book_bar_basis = self._basis_chip(
            "§2.2 入口⑤ · 验收③ 自动附统计")
        self.book_bar_basis.setVisible(self.basis_cb.isChecked())
        self.basis_labels.append(self.book_bar_basis)
        root.addWidget(self.book_bar_basis)
        root.addWidget(self._book_bar())

        root.addWidget(self._target_card())
        root.addWidget(self._level_card())
        root.addWidget(self._dir_card())
        root.addWidget(self._report_card())

        self.hero_basis = self._basis_chip(
            "§2.2 入口⑤ · 导出 + 报告 + 基准同步")
        self.hero_basis.setVisible(self.basis_cb.isChecked())
        self.basis_labels.append(self.hero_basis)
        root.addWidget(self.hero_basis)
        root.addWidget(self._hero())

        self.result_slot = QVBoxLayout()
        self.result_slot.setContentsMargins(0, 0, 0, 0)
        self.result_slot.setSpacing(16)
        root.addLayout(self.result_slot)

        self.legend = _label(
            "勾选「显示设计依据」可看到每个 UI 元素对应的文档条款。"
            "替换报告的 GUI 对比视图属 V1.1，V1 只做文件留存 + 提示位置。",
            size="xs", color="neutral.500", wrap=True)
        root.addWidget(self.legend)

        self.status = QLabel("")
        self.status.setObjectName("Toast")
        self.status.setVisible(False)
        self.status.setStyleSheet(
            f"#Toast{{background:{c('neutral.800')};color:#fff;"
            f"border-radius:10px;padding:10px 16px;font-size:{fs('sm')}}}")
        self.status.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        root.addWidget(self.status, 0, Qt.AlignmentFlag.AlignLeft)

    # ------------------------------------------------------------------ 头部

    def _header(self) -> QWidget:
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(_label("导出结果", size="2xl", color="neutral.900",
                             weight="bold"))
        col.addWidget(_label(
            "导出干净 TXT；EPUB 来源自动拆分还原为 EPUB。"
            "每次导出自动附替换统计（报告以文件留存）。",
            size="md", color="neutral.600", wrap=True))
        hl.addLayout(col, 1)

        self.basis_cb = QCheckBox("显示设计依据")
        self.basis_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.basis_cb.toggled.connect(self._toggle_basis)
        hl.addWidget(self.basis_cb, 0, Qt.AlignmentFlag.AlignTop)
        return w

    # -------------------------------------------------------------- 书源状态条

    def _book_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("BookBar")
        bar.setStyleSheet(
            f"#BookBar{{background:{c('neutral.0')};border:1px solid "
            f"{c('neutral.200')};border-radius:{r('lg')}}}")

        hl = QHBoxLayout(bar)
        hl.setContentsMargins(18, 14, 18, 14)
        hl.setSpacing(14)

        ico = QLabel("📖")
        ico.setFixedSize(40, 40)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background:{c('primary.100')};color:{c('primary.700')};"
            f"border-radius:10px;font-size:19px")
        hl.addWidget(ico)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(_label(BOOK, size="md", weight="bold"))
        col.addWidget(_label(
            f"来源 {SOURCE} · 已校正 · 替换命中 {HITS} 处",
            size="xs", color="neutral.500"))
        hl.addLayout(col, 1)

        hl.addWidget(Pill("就绪", "ok"))
        return bar

    # ------------------------------------------------------------ 导出目标

    def _target_card(self) -> Card:
        card = Card(
            "导出目标", "来源为 EPUB 时才出现「还原为 EPUB」",
            collapsible=True, open_=True,
            basis="§2.2 入口⑤ · 验收② EPUB 还原",
        )
        self.basis_labels.append(card.basis)

        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(10)
        self.rd_txt = RadioCard("导出干净 TXT", "得到整理好的纯文本", "txt")
        self.rd_epub = RadioCard(
            "还原为 EPUB", "按章节边界标记还原，可直接用阅读器打开", "epub")
        self.rd_txt.chosen.connect(self.set_target)
        self.rd_epub.chosen.connect(self.set_target)
        self.rd_epub.set_selected(True)
        row.addWidget(self.rd_txt, 1)
        row.addWidget(self.rd_epub, 1)
        card.body_l.addLayout(row)
        return card

    def set_target(self, t: str):
        self.target = t
        self.rd_txt.set_selected(t == "txt")
        self.rd_epub.set_selected(t == "epub")
        self._toast(f"导出目标：{'干净 TXT' if t == 'txt' else '还原 EPUB'}")

    # ------------------------------------------------------------ 章节标题分级

    def _level_card(self) -> Card:
        card = Card(
            "章节标题分级", "导入时自动判断，此处可修正",
            collapsible=True, open_=True,
            basis="§2.7.1 第 11 项 · 结果在导出页可修正",
        )
        self.basis_labels.append(card.basis)

        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(12)
        lab = _label("分级方式", size="sm", weight="semibold")
        lab.setMinimumWidth(96)
        row.addWidget(lab)
        self.level_box = QComboBox()
        self.level_box.addItems(LEVELS)
        self.level_box.setCurrentText("一级")
        self.level_box.setCursor(Qt.CursorShape.PointingHandCursor)
        self.level_box.setMinimumWidth(150)
        self.level_box.currentTextChanged.connect(
            lambda v: self._toast(f"章节分级已设为：{v}"))
        row.addWidget(self.level_box)
        row.addStretch(1)
        card.body_l.addLayout(row)

        card.body_l.addWidget(self._hint(
            "导入时自动识别 ◎ 标记并转「第X部 / 卷 / 章」，结果在导出页可修正。"))
        return card

    # ------------------------------------------------------------ 导出目录

    def _dir_card(self) -> Card:
        card = Card(
            "导出到", "",
            collapsible=True, open_=True,
            basis="§2.7.7 · 报告落在导出目录旁",
        )
        self.basis_labels.append(card.basis)

        self.dir_row = QFrame()
        self.dir_row.setObjectName("PathRow")
        self.dir_row.setStyleSheet(
            f"#PathRow{{background:{c('neutral.50')};border:1px dashed "
            f"{c('neutral.200')};border-radius:10px}}")
        hl = QHBoxLayout(self.dir_row)
        hl.setContentsMargins(12, 10, 12, 10)
        hl.setSpacing(10)
        self.dir_label = QLabel(self.exp_dir + "\\")
        self.dir_label.setStyleSheet(
            f"font-family:{FONT_MONO};font-size:{fs('sm')};"
            f"color:{c('neutral.600')};background:transparent")
        self.dir_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        hl.addWidget(self.dir_label, 1)
        browse = QPushButton("浏览…")
        browse.setObjectName("BtnOutline")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._pick_dir)
        hl.addWidget(browse)
        card.body_l.addWidget(self.dir_row)
        return card

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择导出目录", self.exp_dir)
        if d:
            self.exp_dir = d
            self.dir_label.setText(d + "\\")
            self._toast("导出目录已更新")

    # ------------------------------------------------------------ 替换报告

    def _report_card(self) -> Card:
        card = Card(
            "替换报告（自动附）", "以 CSV / 文本留存，不做 GUI 对比视图",
            collapsible=True, open_=True,
            basis="§2.7.7 · 报告文件留存（GUI 呈现属 V1.1）",
        )
        self.basis_labels.append(card.basis)

        kv = QHBoxLayout()
        kv.setContentsMargins(0, 2, 0, 12)
        kv.setSpacing(28)
        kv.addWidget(self._kv("替换命中", str(HITS)))
        kv.addWidget(self._kv("涉及词库", f"{LIB_COUNT} 套"))
        kv.addWidget(self._kv("报告格式", "CSV / 文本"))
        kv.addStretch(1)
        card.body_l.addLayout(kv)

        card.body_l.addWidget(self._diff())

        card.body_l.addWidget(self._hint(
            "报告以上次校正备份为基准反推本轮实际替换；导出时自动生成，"
            "无独立按钮。若未跑过校正则无差异，自动跳过并说明。"))

        demo_row = QHBoxLayout()
        demo_row.setContentsMargins(0, 10, 0, 0)
        self.no_diff_btn = QPushButton("演示：未跑过校正（无差异）")
        self.no_diff_btn.setObjectName("BtnOutline")
        self.no_diff_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.no_diff_btn.clicked.connect(self._toggle_no_diff)
        demo_row.addWidget(self.no_diff_btn)
        demo_row.addStretch(1)
        card.body_l.addLayout(demo_row)
        return card

    def _toggle_no_diff(self):
        self.no_diff = not self.no_diff
        if self.no_diff:
            self.no_diff_btn.setText("演示：恢复正常（有差异）")
            self._toast("已切换为「未跑过校正」：导出时将跳过报告并说明")
        else:
            self.no_diff_btn.setText("演示：未跑过校正（无差异）")
            self._toast("已切换回正常状态：导出时附替换报告")

    def _kv(self, k: str, v: str) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        kl = QLabel(k)
        kl.setStyleSheet(f"font-size:{fs('xs')};color:{c('neutral.500')};"
                         f"background:transparent")
        vl = QLabel(v)
        vl.setStyleSheet(
            f"font-weight:700;font-size:{fs('md')};color:{c('primary.700')};"
            f"background:transparent")
        col.addWidget(kl)
        col.addWidget(vl)
        w.setMinimumHeight(kl.sizeHint().height() + vl.sizeHint().height() + 2)
        return w

    def _diff(self) -> QFrame:
        box = QFrame()
        box.setObjectName("Diff")
        box.setStyleSheet(
            f"#Diff{{background:{c('neutral.50')};border-radius:10px}}")
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(4)
        del_ = (f"<span style='color:{c('error')};"
                f"text-decoration:line-through'>")
        add = f"<span style='color:{c('success')}'>"
        for html in (
            f"原：他{del_}好象</span>在{del_}在次</span>见面。",
            f"改：他{add}好像</span>在{add}再次</span>见面。",
        ):
            lab = QLabel(html)
            lab.setTextFormat(Qt.TextFormat.RichText)
            lab.setStyleSheet(
                f"color:{c('neutral.700')};font-family:{FONT_MONO};"
                f"font-size:{fs('xs')};background:transparent")
            v.addWidget(lab)
        return box

    # ------------------------------------------------------------ 导出 hero

    def _hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("Hero")
        hero.setStyleSheet(
            f"#Hero{{border-radius:{r('lg')};"
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {c('primary.700')},stop:1 {c('primary.500')});}}")

        hl = QHBoxLayout(hero)
        hl.setContentsMargins(26, 22, 26, 22)
        hl.setSpacing(24)

        col = QVBoxLayout()
        col.setSpacing(6)
        h2 = QLabel(f"导出{BOOK}")
        h2.setStyleSheet(
            f"color:#fff;font-size:{fs('lg')};"
            f"font-weight:{FONT_WEIGHT['bold']};background:transparent")
        p = QLabel(
            "导出干净文件 → 自动附替换报告 → 内部同步基准"
            "（保证下轮统计不重复）。")
        p.setWordWrap(True)
        p.setStyleSheet(
            f"color:rgba(255,255,255,0.88);font-size:{fs('sm')};"
            f"background:transparent")
        col.addWidget(h2)
        col.addWidget(p)
        hl.addLayout(col, 1)

        self.exp_btn = QPushButton("📤 开始导出")
        self.exp_btn.setObjectName("HeroBtn")
        self.exp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.exp_btn.setMinimumHeight(50)
        self.exp_btn.setStyleSheet(
            f"#HeroBtn{{background:#fff;color:{c('primary.700')};"
            f"border:none;border-radius:{r('lg')};padding:0 32px;"
            f"font-size:{fs('md')};font-weight:{FONT_WEIGHT['bold']}}}"
            f"#HeroBtn:hover{{background:{c('primary.50')}}}"
            f"#HeroBtn:disabled{{background:rgba(255,255,255,0.55);"
            f"color:{c('primary.500')}}}")
        self.exp_btn.clicked.connect(self.do_export)
        hl.addWidget(self.exp_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return hero

    # -------------------------------------------------------------- 执行流程

    def do_export(self):
        if self._running:
            return
        target = self.target
        no_diff = self.no_diff
        target_name = f"{BOOK}.epub" if target == "epub" else f"{BOOK}.txt"

        steps = [dict(name="准备导出目录", desc=self.exp_dir, dur=700)]
        if target == "epub":
            steps.append(dict(
                name="EPUB 拆分还原",
                desc="按章节边界标记还原，保证章节顺序不乱", dur=1600))
        else:
            steps.append(dict(
                name="生成干净 TXT",
                desc="按当前章节分级输出纯文本", dur=1200))
        if no_diff:
            steps.append(dict(
                name="生成替换报告",
                desc="未检出差异，跳过并说明", dur=700))
        else:
            steps.append(dict(
                name="生成替换报告",
                desc="以上次校正备份为基准反推本轮替换", dur=1200))
            steps.append(dict(
                name="同步校正备份",
                desc="内部机制，保证下轮报告不重复统计", dur=600))

        self._running = True
        self.exp_btn.setEnabled(False)
        dlg = ProgressDialog(
            icon="📤",
            title=f"正在导出 {target_name}",
            note="",
            steps=steps,
            on_finish=lambda: self._render_result(target_name, no_diff),
            cancel_text="取消",
            finish_text="导出完成",
            parent=self,
        )
        dlg.start()  # 启动步骤推进（QTimer 链），否则进度条不前进、弹窗卡死
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        self._running = False
        self.exp_btn.setEnabled(True)
        if accepted:
            self._toast(
                "导出完成" + ("（未检出差异，已跳过报告）"
                              if no_diff else "，替换报告已留存"))
        else:
            self._clear_result()
            self._toast("已取消导出")

    def _clear_result(self):
        # 结果卡被销毁后，它的 basis 容器会成为悬空引用——先摘掉再删
        if self._result_basis is not None:
            try:
                if self._result_basis in self.basis_labels:
                    self.basis_labels.remove(self._result_basis)
            except Exception:
                pass
            self._result_basis = None
        while self.result_slot.count():
            item = self.result_slot.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    # ---------------------------------------------------------------- 结果卡

    def _render_result(self, target_name: str, no_diff: bool):
        self._clear_result()

        card = Card(basis="§2.2 入口⑤ · 验收①②③")
        self.basis_labels.append(card.basis)
        self._result_basis = card.basis
        card.basis.setVisible(self.basis_cb.isChecked())

        head = QHBoxLayout()
        head.setSpacing(12)
        ok = QLabel("✓")
        ok.setFixedSize(34, 34)
        ok.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ok.setStyleSheet(
            f"background:{c('success')};color:#fff;border-radius:10px;"
            f"font-size:18px")
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(_label(f"{target_name} 已导出", size="md",
                             weight="bold", color="neutral.900"))
        col.addWidget(_label("可直接导入主流阅读器打开",
                             size="xs", color="neutral.500"))
        head.addWidget(ok)
        head.addLayout(col, 1)
        card.body_l.addLayout(head)

        out_path = f"{self.exp_dir}\\{target_name}"
        card.body_l.addWidget(self._path_row(
            out_path, "打开目录",
            lambda: self._toast("原型示意：打开导出目录")))

        if no_diff:
            warn = QLabel(
                "未检出与基准的差异，本次已跳过替换报告生成。")
            warn.setWordWrap(True)
            warn.setStyleSheet(
                f"background:{c('warning.bg')};border:1px solid "
                f"{c('warning.border')};color:{c('warning')};"
                f"border-radius:10px;padding:10px 14px;font-size:{fs('sm')};"
                f"margin-top:10px")
            card.body_l.addWidget(warn)
        else:
            report_path = f"{self.exp_dir}\\{REPORT_NAME}"
            card.body_l.addWidget(self._with_top_margin(self._path_row(
                report_path, "打开报告",
                lambda: self._toast("原型示意：打开替换报告"))))

        card.body_l.addLayout(self._result_actions())
        self.result_slot.addWidget(card)

    def _with_top_margin(self, w: QWidget) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 10, 0, 0)
        v.addWidget(w)
        return box

    def _path_row(self, text: str, btn_text: str, on_click) -> QFrame:
        box = QFrame()
        box.setObjectName("PathRow")
        box.setStyleSheet(
            f"#PathRow{{background:{c('neutral.50')};border:1px dashed "
            f"{c('neutral.200')};border-radius:10px}}")
        hl = QHBoxLayout(box)
        hl.setContentsMargins(12, 10, 12, 10)
        hl.setSpacing(10)
        lab = QLabel(text)
        lab.setStyleSheet(
            f"font-family:{FONT_MONO};font-size:{fs('sm')};"
            f"color:{c('neutral.600')};background:transparent")
        lab.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        hl.addWidget(lab, 1)
        b = QPushButton(btn_text)
        b.setObjectName("BtnOutline")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(on_click)
        hl.addWidget(b)
        return box

    def _result_actions(self) -> QHBoxLayout:
        acts = QHBoxLayout()
        acts.setContentsMargins(0, 14, 0, 0)
        acts.setSpacing(10)

        hist = QPushButton("🕓 查看历史记录")
        hist.setObjectName("BtnPrimary")
        hist.setCursor(Qt.CursorShape.PointingHandCursor)
        hist.clicked.connect(
            lambda: self._toast("原型示意：本次任务已记入「历史记录」"))
        acts.addWidget(hist)

        again = QPushButton("⚡ 再校正一轮")
        again.setObjectName("BtnOutline")
        again.setCursor(Qt.CursorShape.PointingHandCursor)
        again.clicked.connect(
            lambda: self._toast("原型示意：回到「一键校正」再跑一轮"))
        acts.addWidget(again)

        acts.addStretch(1)
        return acts

    # ------------------------------------------------------------------ 公共

    def _basis_chip(self, text: str) -> QWidget:
        """与 `Card.basis` 同款的设计依据标签（容器可整体显隐）。

        书源条 / hero 不是 Card，没有内置 basis，这里单独挂一个，保证
        「显示设计依据」开关能覆盖全部 7 个原型标注点。
        """
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        lab = QLabel(text if text.lstrip().startswith("§") else f"§ {text}")
        lab.setStyleSheet(
            f"color:{c('primary.700')};background:{c('primary.50')};"
            f"border-radius:{r('full')};padding:2px 9px;"
            f"font-size:{fs('xs')};font-weight:700")
        lab.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        bl.addWidget(lab)
        bl.addSpacing(12)
        box.setVisible(False)
        return box

    def _hint(self, text: str) -> QLabel:
        h = _label(text, size="xs", color="neutral.500", wrap=True)
        h.setContentsMargins(0, 6, 0, 0)
        return h

    def _toggle_basis(self, on: bool):
        alive = []
        for b in self.basis_labels:
            try:
                b.setVisible(bool(on))
                alive.append(b)
            except RuntimeError:
                # 底层 C++ 对象已随结果卡销毁，丢弃这个悬空引用
                pass
        self.basis_labels = alive

    def _toast(self, msg: str):
        self.status.setText(msg)
        self.status.setVisible(True)
        self._toast_timer.start(2600)

    def _hide_status(self):
        self.status.setVisible(False)
