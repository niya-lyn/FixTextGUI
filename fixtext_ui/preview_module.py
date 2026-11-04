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
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QFileDialog,
)

from fixtext_tokens import c, fs, r, FONT_WEIGHT, FONT_MONO
from fixtext_widgets import Modal, hline


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
    """一组（新增 / 冲突 / 格式不合格）：标题 + 条数 + 逐条清单。"""

    cancelRequested = Signal(int)      # 参数：原始行号

    def __init__(self, name: str, items: list, note: str, *, accent: str,
                 advice_of=None, parent=None):
        super().__init__(parent)
        self.name = name
        self.rows: list[dict] = []
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

    def fill(self, items: list) -> None:
        """按当前条目重画清单（取消 / 恢复后整组重建，不走逐行打补丁）。"""
        self.rows = []
        while self.box_l.count():
            item = self.box_l.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if not items:
            self.box_l.addWidget(_lab("（这一组没有条目）", size="xs",
                                     color="neutral.500"))
            return
        for it in items:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 6, 0, 6)
            rl.setSpacing(10)
            rl.addWidget(_lab(str(it.line_no), size="xs", color="neutral.500", mono=True))
            rl.addWidget(_lab(it.word or "—", size="xs", color="neutral.800",
                              mono=True, wrap=True), 2)
            rl.addWidget(_lab(it.value or "—", size="xs", color="neutral.800",
                              mono=True, wrap=True), 2)
            rl.addWidget(_lab(it.label(), size="xs", color="neutral.600", wrap=True), 4)
            btn = QPushButton("取消")
            btn.setObjectName("BtnGhost")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip("把这一条整条排除：取消后它不再出现在任何一组里")
            btn.clicked.connect(lambda _=False, n=it.line_no: self.cancelRequested.emit(n))
            rl.addWidget(btn)
            self.box_l.addWidget(row)
            self.box_l.addWidget(hline())
            self.rows.append(dict(line_no=it.line_no, word=it.word, value=it.value,
                                  label=it.label()))


class PreviewDialog(Modal):
    """导入预览弹窗：三组 + 取消 + 全部恢复 + 预演核对。"""

    def __init__(self, model, *, parent=None):
        super().__init__(icon="📥", title="导入预览（只看不动手）", parent=parent,
                         min_width=760)
        self.model = model
        self._sections: dict[str, GroupSection] = {}
        self._rehearsal = None
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
                               accent=accents[name])
            sec.cancelRequested.connect(self._on_cancel)
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

        self.fl.insertWidget(0, self.restore_btn)
        self.fl.insertWidget(1, self.rehearse_btn)
        self.add_foot("关闭", "ghost", self.reject)

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
        self.restore_btn.setEnabled(bool(n_cancel))
        self.rehearse_btn.setEnabled(self.model.total() > 0)
        return counts

    # ----- 动作 -----

    def _on_cancel(self, line_no: int) -> None:
        self.model.cancel(line_no)
        self.refresh()

    def restore_all(self) -> None:
        self.model.restore_all()
        self.refresh()

    def run_rehearsal(self) -> object:
        """预演核对：临时副本上真写一次，与预览数字并列展示。"""
        from fixtext_vocab_preview import messages as msg
        from fixtext_vocab_preview.rehearsal import rehearse

        snapshot = dict(self.model.counts())     # 用预览**当时**的数字对账
        result = rehearse(self.model, preview_snapshot=snapshot)
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
