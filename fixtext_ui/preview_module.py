"""V1.1-D3 · 导入预览的三组呈现（只读，逐条可取消）。

排期 §9.5 交付物①：解析结果按「新增 N / 冲突 M / 格式不合格 K」三组呈现，
并逐条可取消；取消后该条不进任何一组。

几条刻意的取舍：

* **不新增左轨页**。左轨固定六项（E4 的用例钉着 `len(rail_items) == 6`），
  所以预览以**弹窗**形态挂在词库页工具条的「📥 导入预览」上，不占导航位。
* **只看不动手**。这里没有「确认导入」：写入与撤销是 D5、冲突处置是 D4，
  本卡越界做那些会把后面的卡架空。要落库时用词库页原有的新增 / 合并 / 删除，
  它们各自先预览、二次确认、可撤销。
* **数字可核对**。弹窗底部给一个「预演核对」按钮：它在词库文件的**临时副本**
  上跑一次真写入，把预览数字与实测数字并排列出来——用户不必相信这页的话，
  点一下就能自证。
* **数据只走 VocabStore**。界面层唯一词库入口就是它，不读也不写词库文件。

V1.1-D4 在这页上加了什么：

* **冲突组每行可处置**：改值（填新写法再重判）/ 跳过 / 设为禁用，三选一；
  状态就写在那一行上，随时可撤销，也能一次「全部撤销」。
* **确认执行前先看影响预览**：底部「确认执行」先弹二次确认，正文是
  「将写入 N 条：新增 X / 更新 Y / 禁用 Z / 跳过 S」——数字取自 `write_plan()`，
  与预演实测同一来源，用户点「预演核对」能自己验一遍。
  还有冲突没处置时**拦着不许确认**，否则那几条写不写说不清。
* **这一页仍然不落库**：确认后只把写好的清单交给下一步（D5 才真写）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QFileDialog,
)

from fixtext_tokens import c, fs, r, FONT_WEIGHT, FONT_MONO
from fixtext_widgets import ConfirmDialog, Modal, hline
from fixtext_vocab_preview import ACTION_DISABLE, ACTION_EDIT, ACTION_SKIP


def _lab(text: str, *, size: str = "sm", color: str = "neutral.800",
         weight: str | None = None, wrap: bool = False, mono: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(wrap)
    style = f"color:{c(color)};font-size:{fs(size)};background:transparent;"
    if weight:
        style += f"font-weight:{FONT_WEIGHT[weight]};"
    if mono:
        style += f"font-family:{FONT_MONO};"
    lab.setStyleSheet(style)
    return lab


class GroupSection(QWidget):
    """一组（新增 / 冲突 / 格式不合格）：标题 + 条数 + 逐条清单。

    ``actionable=True`` 时（D4 只给冲突组开）每一行多出三样东西：一个可直接
    输入新写法的框、三个处置按钮（改值 / 跳过 / 设为禁用）、以及处置状态文案。
    点按钮只发信号，真正的处置由 `PreviewModel` 算——界面不自己判轻重。
    """

    cancelRequested = Signal(int)              # 参数：原始行号
    actionRequested = Signal(int, str, str)    # (行号, 处置, 新值)

    def __init__(self, name: str, items: list, note: str, *, accent: str,
                 advice_of=None, actionable: bool = False, parent=None):
        super().__init__(parent)
        self.name = name
        self.rows: list[dict] = []
        self.actionable = actionable
        self.inputs: dict[int, object] = {}     # 行号 → 新值输入框（只有冲突组有）
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(6)

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        self.title_label = _lab(f"{name} {len(items)} 条", size="sm",
                                color=accent, weight="bold")
        hl.addWidget(self.title_label)
        hl.addStretch(1)
        vl.addWidget(head)

        if note:
            vl.addWidget(_lab(note, size="xs", color="neutral.500", wrap=True))

        self.box = QFrame()
        self.box.setObjectName("MiniTable")
        self.box_l = QVBoxLayout(self.box)
        self.box_l.setContentsMargins(12, 10, 12, 10)
        self.box_l.setSpacing(0)
        vl.addWidget(self.box)
        self.fill(items)

    def _clear(self) -> None:
        self.rows = []
        self.inputs = {}
        while self.box_l.count():
            item = self.box_l.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def fill(self, items: list) -> None:
        """按当前条目重画清单（取消 / 恢复 / 处置后整组重建，不走逐行打补丁）。"""
        self._clear()
        if not items:
            self.box_l.addWidget(_lab("（这一组没有条目）", size="xs",
                                     color="neutral.500"))
            return
        for it in items:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 6, 0, 6)
            rl.setSpacing(8)
            rl.addWidget(_lab(str(it.line_no), size="xs", color="neutral.500", mono=True))
            rl.addWidget(_lab(it.word or "—", size="xs", color="neutral.800",
                              mono=True, wrap=True), 2)
            if self.actionable:
                self._fill_actionable(it, rl)
            else:
                rl.addWidget(_lab(it.value or "—", size="xs", color="neutral.800",
                                  mono=True, wrap=True), 2)
                rl.addWidget(_lab(it.label(), size="xs", color="neutral.600", wrap=True), 4)
                btn = QPushButton("取消")
                btn.setObjectName("BtnGhost")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setToolTip("把这一条整条排除：取消后它不再出现在任何一组里")
                btn.clicked.connect(
                    lambda _=False, n=it.line_no: self.cancelRequested.emit(n))
                rl.addWidget(btn)
            self.box_l.addWidget(row)
            self.box_l.addWidget(hline())
            self.rows.append(dict(
                line_no=it.line_no, word=it.word, value=it.value,
                label=it.label(), state=it.action_note, action=it.action,
                effect=it.effect, effective_value=it.effective_value))

    def _fill_actionable(self, it, rl) -> None:
        """冲突行的处置控件：新值输入框 + 状态文案 + 三个处置按钮 + 撤销 + 取消。"""
        from PySide6.QtWidgets import QLineEdit

        inp = QLineEdit(it.effective_value)
        inp.setObjectName("D4ValueInput")
        inp.setMinimumWidth(100)
        inp.setMaximumWidth(160)
        inp.setToolTip("想写成什么样就填在这里，再点「改值」")
        rl.addWidget(inp, 2)
        self.inputs[it.line_no] = inp

        rl.addWidget(_lab(it.label(), size="xs", color="neutral.600", wrap=True), 3)
        rl.addWidget(self._state_label(it), 2)

        for text, action in (("改值", ACTION_EDIT), ("跳过", ACTION_SKIP),
                             ("设为禁用", ACTION_DISABLE)):
            rl.addWidget(self._action_button(it, text, action))

        undo = QPushButton("撤销")
        undo.setObjectName("BtnGhost")
        undo.setCursor(Qt.CursorShape.PointingHandCursor)
        undo.setEnabled(bool(it.action))
        undo.setToolTip("把这一条退回「还没处置」")
        undo.clicked.connect(
            lambda _=False, n=it.line_no: self.actionRequested.emit(n, "", ""))
        rl.addWidget(undo)

        cancel = QPushButton("取消")
        cancel.setObjectName("BtnGhost")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setToolTip("把这一条整条排除：取消后它不再出现在任何一组里")
        cancel.clicked.connect(
            lambda _=False, n=it.line_no: self.cancelRequested.emit(n))
        rl.addWidget(cancel)

    def _state_label(self, it) -> QLabel:
        """处置状态可见：这一条现在会被怎么处理，直接一行话说清。"""
        text = it.action_note or msg_note_pending()
        color = {"add": "success", "update": "success", "disabled": "warning",
                 "skipped": "neutral.500",
                 "pending": "warning"}.get(it.effect, "neutral.500")
        lab = _lab(text, size="xs", color=color, wrap=True)
        lab.setObjectName("D4StateLabel")
        return lab

    def _action_button(self, it, text: str, action: str) -> QPushButton:
        """一个处置按钮。当前已生效的那个处置按钮会高亮（处置状态的第一层可见性）。"""
        btn = QPushButton(text)
        btn.setObjectName("BtnGhost" if action != ACTION_DISABLE else "BtnOutline")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if it.action == action:
            btn.setStyleSheet(
                f"QPushButton{{border:1px solid {c('primary.600')};"
                f"color:{c('primary.700')};background:{c('primary.50')};}}")
        btn.setToolTip({"edit": "换一个正确写法，再按同一套查重重判",
                        "skip": "这一条这次不写入",
                        "disable": "照常写进词库，但按未启用状态写"}[action])

        def _go(_checked=False, n=it.line_no, a=action):
            # 改值要带上输入框里当前的新写法；其余两种没有新值
            value = self._edited_value(n) if a == ACTION_EDIT else ""
            self.actionRequested.emit(n, a, value)

        btn.clicked.connect(_go)
        return btn

    def _edited_value(self, line_no: int) -> str:
        inp = self.inputs.get(line_no)
        return inp.text().strip() if inp is not None else ""


def msg_note_pending() -> str:
    from fixtext_vocab_preview import messages as msg
    return msg.action_note_pending()


class PreviewDialog(Modal):
    """导入预览弹窗：三组 + 取消 + 全部恢复 + 预演核对。"""

    def __init__(self, model, *, parent=None):
        super().__init__(icon="📥", title="导入预览（只看不动手）", parent=parent,
                         min_width=760)
        self.model = model
        self._sections: dict[str, GroupSection] = {}
        self._rehearsal = None
        self.confirm_dialog = None          # 二次确认弹窗（界面测试要取它）
        self._confirmed = False             # 是否已点过「确认执行」
        self._confirmed_plan: dict = {}     # 被确认的那份影响预览数字
        self._write_list: list = []         # 交给 D5 的写入清单
        self._build_body()   # 不能叫 _build：Modal 基类占了这个名字

    # ----- 构建 -----

    def _build_body(self) -> None:
        from fixtext_vocab_preview import messages as msg
        from fixtext_vocab_preview.groups import GROUP_CONFLICT, GROUP_NEW, GROUP_REJECT

        self.summary_label = self.add_note(msg.preview_only(), "info")
        self.counts_label = _lab("", size="sm", color="neutral.900", weight="bold")
        self.add_widget(self.counts_label)
        self.batch_label = _lab("", size="xs", color="neutral.500", wrap=True)
        self.add_widget(self.batch_label)

        self._holder = QWidget()
        hv = QVBoxLayout(self._holder)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(14)
        accents = {GROUP_NEW: "success", GROUP_CONFLICT: "warning", GROUP_REJECT: "error"}
        for name in (GROUP_NEW, GROUP_CONFLICT, GROUP_REJECT):
            sec = GroupSection(name, [], msg.GROUP_NOTES.get(name, ""),
                               accent=accents[name],
                               actionable=(name == GROUP_CONFLICT))
            sec.cancelRequested.connect(self._on_cancel)
            sec.actionRequested.connect(self._on_action)
            self._sections[name] = sec
            hv.addWidget(sec)
        hv.addStretch(1)

        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.Shape.NoFrame)
        self.area.setMaximumHeight(420)
        self.area.setWidget(self._holder)
        self.add_widget(self.area)

        self.cancelled_label = _lab("", size="xs", color="neutral.500", wrap=True)
        self.add_widget(self.cancelled_label)

        # 处置提示（人话：三种处置各自是什么）+ 影响预览（数字随处置实时变）
        self.action_hint = _lab(msg.action_hint(), size="xs", color="neutral.500",
                                wrap=True)
        self.add_widget(self.action_hint)
        self.impact_label = _lab("", size="sm", color="neutral.900", weight="bold",
                                 wrap=True)
        self.add_widget(self.impact_label)
        self.pending_label = _lab("", size="xs", color="warning", wrap=True)
        self.add_widget(self.pending_label)
        # 页内提示条：无头环境不能用 QMessageBox（exec() 会卡住事件循环）
        self.tip_label = _lab("", size="xs", color="info", wrap=True)
        self.tip_label.setVisible(False)
        self.add_widget(self.tip_label)

        self.restore_btn = QPushButton("↺ 全部恢复")
        self.restore_btn.setObjectName("BtnOutline")
        self.restore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restore_btn.clicked.connect(self.restore_all)

        self.rehearse_btn = QPushButton("🧪 预演核对")
        self.rehearse_btn.setObjectName("BtnOutline")
        self.rehearse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rehearse_btn.setToolTip(
            "在词库文件的临时副本上做一次真写入，核对预览数字与实测条数是否一致"
            "（你的词库文件不会被改动）")
        self.rehearse_btn.clicked.connect(self.run_rehearsal)

        self.confirm_btn = QPushButton("确认执行")
        self.confirm_btn.setObjectName("BtnPrimary")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.setToolTip("先看影响预览再确认；确认后开始写入（写入在下一步做）")
        self.confirm_btn.clicked.connect(self.ask_confirm)

        self.fl.insertWidget(0, self.restore_btn)
        self.fl.insertWidget(1, self.rehearse_btn)
        self.add_foot("关闭", "ghost", self.reject)
        self.fl.addWidget(self.confirm_btn)

        self._rehearsal_box = QFrame()
        self._rehearsal_box.setVisible(False)
        self.body_l.addWidget(self._rehearsal_box)
        self.refresh()

    # ----- 视图刷新 -----

    def refresh(self) -> dict:
        """按模型当前状态重画三组（取消 / 恢复后都走这里）。"""
        from fixtext_vocab_preview import messages as msg
        from fixtext_vocab_preview.groups import GROUP_CONFLICT, GROUP_NEW, GROUP_REJECT

        groups = self.model.groups()
        counts = self.model.counts()
        for name, sec in self._sections.items():
            items = groups.get(name, [])
            sec.title_label.setText(msg.group_title(name, len(items)))
            sec.fill(items)                 # 取消后这一组的清单要跟着变

        self.counts_label.setText(msg.summary(counts[GROUP_NEW], counts[GROUP_CONFLICT],
                                             counts[GROUP_REJECT]))
        self.batch_label.setText(self.model.batch_note())

        n_cancel = len(self.model.cancelled_lines)
        if n_cancel:
            self.cancelled_label.setText(
                msg.cancelled(n_cancel) + " " + msg.empty_after_cancel_hint())
        else:
            self.cancelled_label.setText(msg.cancelled_hint())
        # 影响预览：数字与预演实测同一来源（`write_plan()`），处置一变它就变
        self.impact_label.setText(self.model.impact_text())
        pending = self.model.pending_items()
        if pending:
            self.pending_label.setText(msg.impact_blocked(len(pending)))
            self.pending_label.setVisible(True)
        else:
            self.pending_label.setVisible(False)

        n_done = len(self.model.dispositions)
        self.restore_btn.setEnabled(bool(n_cancel) or bool(n_done))
        self.restore_btn.setText(
            msg.action_restored(0).replace("已撤销 0 条处置，", "↺ 全部撤销")
            if (n_cancel or n_done) else "↺ 全部恢复")
        self.rehearse_btn.setEnabled(self.model.total() > 0)
        # 有冲突没处置时按钮仍可点（点了会给出人话解释），不让用户对着灰按钮猜原因
        self.confirm_btn.setEnabled(self.model.write_plan()["write"] > 0 or bool(pending))
        return counts

    # ----- 动作 -----

    def tip(self, text: str) -> None:
        """页内提示（不弹框）：一句话说清刚才发生了什么。"""
        self.tip_label.setText(text or "")
        self.tip_label.setVisible(bool(text))

    def _on_cancel(self, line_no: int) -> None:
        self.model.cancel(line_no)
        self.refresh()

    def _on_action(self, line_no: int, action: str, value: str) -> None:
        """把一次点击交给模型（处置的判定在模型里，界面只传意图）。"""
        try:
            self.model.set_action(line_no, action, value)
        except ValueError as exc:                 # 改值没填新写法这类
            self.tip(str(exc))
            return
        self.refresh()

    def restore_all(self) -> None:
        """一次撤销全部（逐条取消 + 全部处置），回到刚打开预览时的样子。"""
        self.model.restore_all_actions()
        self.refresh()

    def ask_confirm(self) -> object:
        """「确认执行」→ 先弹二次确认（影响预览），确认后才交出去。

        返回被确认的写入清单；没确认（还有冲突没处置、或用户取消）时返回 ``None``。
        本卡到此为止——真写入是 D5，这里只把清单准备好。
        """
        from fixtext_vocab_preview import messages as msg

        pending = self.model.pending_items()
        if pending:
            self.tip(msg.impact_blocked(len(pending)))
            return None

        plan = self.model.write_plan()
        dlg = ConfirmDialog(
            icon="✅", title=msg.confirm_title(),
            note=f"{self.model.impact_text()}\n\n{msg.impact_note()}\n{msg.confirm_note()}",
            parent=self)
        self.confirm_dialog = dlg              # 留给界面测试取用
        # 不用 exec()：无头环境会卡住事件循环；show() 后由信号接着走
        dlg.accepted.connect(lambda: self._on_confirmed(plan))
        dlg.show()
        return dlg

    def _on_confirmed(self, plan: dict) -> None:
        from fixtext_vocab_preview import messages as msg

        self._confirmed_plan = dict(plan)
        self._write_list = self.model.write_list()
        self._confirmed = True
        self.tip(msg.confirm_done(plan["write"]))

    def run_rehearsal(self) -> object:
        """预演核对：临时副本上真写一次，与预览数字并列展示。"""
        from fixtext_vocab_preview import messages as msg
        from fixtext_vocab_preview.rehearsal import rehearse

        # 不传 `preview_snapshot`：那份快照只有组别三项，"新增"会回落到组别数，
        # 而 D4 的处置会让条目换组（跳过 / 设为禁用都不算"新增"），两者口径不同。
        # 让 `rehearse` 直接取 `write_plan()`——影响预览与预演实测就必然同一来源。
        result = rehearse(self.model)
        self._rehearsal = result

        bl = self._rehearsal_box.layout()
        if bl is not None:
            while bl.count():
                item = bl.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
        else:
            bl = QVBoxLayout(self._rehearsal_box)
            bl.setContentsMargins(12, 10, 12, 10)
            bl.setSpacing(6)

        bl.addWidget(_lab(msg.rehearsal_title(), size="sm", color="neutral.900",
                          weight="bold"))
        bl.addWidget(_lab(msg.rehearsal_note(), size="xs", color="neutral.600", wrap=True))
        for name, preview, measured, verdict in result.diff_columns():
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 3, 0, 3)
            rl.setSpacing(10)
            rl.addWidget(_lab(name, size="xs", color="neutral.700"), 2)
            rl.addWidget(_lab(f"预览 {preview}", size="xs", color="neutral.600"), 2)
            rl.addWidget(_lab(f"实测 {measured}", size="xs", color="neutral.600"), 2)
            good = verdict.startswith("一致")
            rl.addWidget(_lab(verdict, size="xs",
                              color="success" if good else "error"), 3)
            bl.addWidget(row)
        self._rehearsal_box.setStyleSheet(
            f"QFrame{{background:{c('neutral.100')};border:1px solid {c('neutral.200')};"
            f"border-radius:{r('lg')};}}")
        self._rehearsal_box.setVisible(True)
        return result


# ---------------------------------------------------------------------------
# 页面上的入口
# ---------------------------------------------------------------------------

def open_preview(parent, store, *, path: str | None = None, text: str | None = None,
                 policy=None):
    """打开导入预览（挂在词库页工具条上）。

    传 `path` 走文件通道（D1 的 `parse_file`），传 `text` 走粘贴通道
    （`parse_text`）；两者都没有时先让用户挑一个文件。

    :return: `(dialog, model)` —— 关掉弹窗后仍可读模型做对账
    """
    from fixtext_vocab_import.parse import parse_file, parse_text
    from fixtext_vocab_preview.groups import preview_from_sheet

    if not path and not text:
        chosen, _ = QFileDialog.getOpenFileName(
            parent, "选择要预览的词条表", "", "表格或文本 (*.csv *.txt *.tsv);;所有文件 (*)")
        if not chosen:
            return None, None
        path = chosen

    sheet = parse_text(text) if text else parse_file(path)
    source = "" if text else str(path)
    model = preview_from_sheet(sheet, store, policy=policy, source_name=source)
    dlg = PreviewDialog(model, parent=parent)
    return dlg, model
