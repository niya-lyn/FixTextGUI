"""
FixText V1 · 检查问题模块（Qt 移植）
=====================================

对照 `FixText_V1_检查问题_原型.html` **1:1 移植**，保持核心价值：
**逐处人工确认**（不是「一键修复全部」）。

结构：书源条 → 统计条（只统计 / 结束检查）→ 两栏（检查项 + 问题清单 | 编辑器）
      → 操作条（下一处 / 修复 / 跳过 / 保存并下一处 / 撤销）
      → 7 条规则开关 → 批量操作（二次确认）→ 设计依据开关。

用到的复用部件见 `fixtext_widgets.py`（Card / Switch / Pill / FieldRow）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import (
    QFont, QColor, QBrush, QTextCursor, QTextCharFormat, QShortcut, QKeySequence,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QScrollArea, QFrame, QMessageBox, QCheckBox, QSizePolicy,
)

from fixtext_tokens import c, sp, r, fs, FONT_MONO, FONT_WEIGHT
from fixtext_widgets import Card, Switch, Pill, FieldRow, hline, px


# ---------------------------------------------------------------------------
# 数据（与 HTML 原型同源）
# ---------------------------------------------------------------------------

PROBS = [
    dict(line=128,  type="缺右引号",     pre="他说道：", hl="“今天天气不错，我们出去走走…", post="",
         fix="“今天天气不错，我们出去走走…”"),
    dict(line=214,  type="引号交叉错乱", pre="他摇头：", hl="“我见过「那种人」的做法”", post="",
         fix="“我见过『那种人』的做法”"),
    dict(line=377,  type="空引号",       pre="她愣了一下：", hl="“”", post="",
         fix=""),
    dict(line=502,  type="跨行未闭合",   pre="", hl="“这句话从这里开始，", post="（下一行继续）",
         fix="“这句话从这里开始，”"),
    dict(line=640,  type="缺左引号",     pre="", hl="明天再告诉你”", post="",
         fix="“明天再告诉你”"),
    dict(line=811,  type="写反引号",     pre="", hl="”这样写反了“", post="",
         fix="“这样写反了”"),
    dict(line=1024, type="连续同向引号", pre="", hl="““这样连着两个左引号”", post="",
         fix="“这样连着两个左引号”"),
    dict(line=1288, type="最外层单引号", pre="她低声说：", hl="‘那是我们之间的秘密’", post="",
         fix="“那是我们之间的秘密”"),
]

CHECKS = [
    ("缺左引号 / 缺右引号", "配对栈中发现未闭合或多余", "2 处"),
    ("引号交叉错乱",         "双套内又出现独立双引号",   "1 处"),
    ("空引号",               "成对出现但内容为空",       "1 处"),
    ("跨行未闭合",           "向下最多探测 100 行",      "1 处"),
    ("英文撇号误报过滤",     "前后为字母的撇号不计错",   "内部"),
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


# ---------------------------------------------------------------------------
# 问题清单行
# ---------------------------------------------------------------------------

class ProblemRow(QFrame):
    clicked = Signal(int)

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

    def mousePressEvent(self, event):
        self.clicked.emit(self.idx)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# 模块
# ---------------------------------------------------------------------------

class CheckModule(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.probs = [dict(p) for p in PROBS]
        self.cur = 0
        self.ins_buf = ""
        self.undo = []
        self.basis_labels = []

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_status)

        self._build()
        self.render()
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
        name = QLabel("《星河彼端》")
        name.setStyleSheet(
            f"color:{c('neutral.900')};font-weight:700;font-size:{fs('md')}"
        )
        meta = QLabel(f"已校正 · 共 <b>{len(self.probs)}</b> 处待确认")
        meta.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('xs')}")
        col.addWidget(name)
        col.addWidget(meta)
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
        for i, (name, desc, chip) in enumerate(CHECKS):
            if i:
                checks.body_l.addWidget(hline())
            checks.body_l.addWidget(FieldRow(i + 1, name, desc, chip=chip))
        left.addWidget(checks)

        probs_card = self._card(
            "问题清单", "点击任一问题，右侧定位", collapsible=True, open_=True,
            basis="§2.7.4 · 问题清单 · 点击定位",
        )
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

    def render(self):
        self._render_probs()
        self._render_editor()
        self._render_stats()

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
        for i, p in enumerate(self.probs):
            row = ProblemRow(i, p, i == self.cur)
            row.clicked.connect(self.select)
            self.prob_box.addWidget(row)
        self.prob_box.addStretch(1)

    def _render_editor(self):
        p = self.probs[self.cur]
        prefix = f"L{p['line']}   "
        self.editor.setPlainText(prefix + p["pre"] + p["hl"] + p["post"] + self.ins_buf)

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

    def select(self, i: int):
        self.cur = i
        self.ins_buf = ""
        self.render()

    def next_issue(self):
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

    def fix_here(self):
        p = self.probs[self.cur]
        self._push_undo()
        p["hl"] = p["fix"]
        p["state"] = "fixed"
        line = p["line"]
        self.render()
        self.next_issue()
        self.toast(f"已按自动修复规则修复 L{line}")

    def skip_here(self):
        self._push_undo()
        self.probs[self.cur]["state"] = "skip"
        self.render()
        self.next_issue()
        self.toast("已跳过，记入跳过清单")

    def save_and_next(self):
        self._push_undo()
        self.probs[self.cur]["state"] = "fixed"
        self.render()
        self.next_issue()
        self.toast("已保存回写，自动跳到下一处")

    def undo_last(self):
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
                p["state"] = it["state"]
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
        self.ins_buf += ch
        self._render_editor()
        self.toast(f"已插入 {ch}")

    def only_count(self):
        self.toast(f"共检出 {len(self.probs)} 处问题，未做任何修改（仅统计）")

    def end_check(self):
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
        affected = self._affected_single()
        if not affected:
            self.toast("未检出需要批量处理的单引号")
            return
        box = QMessageBox(self)
        box.setWindowTitle("批量操作确认")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"最外层单引号改双引号 · 影响 {len(affected)} 处。")
        box.setWindowTitle("批量操作确认")
        box.setIcon(QMessageBox.Icon.Warning)
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
            for _i, p in affected:
                p["pre"] = self._apply_outer_single(p["pre"])
                p["hl"] = self._apply_outer_single(p["hl"])
                p["post"] = self._apply_outer_single(p["post"])
            self.undo.append({"batch": True, "items": items})
            self.render()
            self.toast(f"已批量修改 {len(affected)} 处（可撤销）")
