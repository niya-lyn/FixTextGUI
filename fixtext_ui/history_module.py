"""
FixText V1 · 历史记录模块（Qt 移植）
====================================

对照 `FixText_V1_历史记录_原型.html` **1:1 移植**，保持核心价值：
任务列表（书名 / 时间 / 替换数 / 状态 / 操作）→ 快照与恢复说明 → 清理全部历史。

结构：无书源条（历史是全局视图）→ 任务列表表格（恢复 / 重新导出 / 删除）
      → 快照与恢复说明卡 → 清理全部历史（破坏性，二次确认）。

产品规则（与导出结果一致）：
- 单条删除与「恢复快照」均可撤销（Toast「撤销」按钮 + Ctrl+Z，撤销栈上限同一次会话）；
  清理全部历史为不可恢复操作，确认后会清空撤销栈。
- 单条删除与清理全部均须显式触发 + 二次确认。
- 基准同步失败不阻断主流程，仅在状态列留痕。
- 条款号一律收进「显示设计依据」，正文不露 §。

复用部件见 `fixtext_widgets.py`（Card / Pill / hline）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialog, QSizePolicy, QCheckBox,
)

from fixtext_tokens import c, fs, FONT_WEIGHT
from fixtext_widgets import Card, Pill, hline, ConfirmDialog


# ---------------------------------------------------------------------------
# 数据（与 HTML 原型同源）
# ---------------------------------------------------------------------------

TASKS = [
    dict(book="《星河彼端》", time="2026-10-26 17:42", hits=1284, status="ok"),
    dict(book="《旧巷杂记》", time="2026-10-25 09:10", hits=356, status="ok"),
    dict(book="《灯下漫笔》", time="2026-10-22 21:03", hits=87, status="syncfail"),
]

# 列表列宽比例（头行与数据行共用，保证对齐）。操作列右对齐。
COL_W = (3, 2, 1, 2, 4)


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

class HistoryModule(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.basis_labels = []
        self._undo_stack = []  # 恢复 / 单条删除可撤销；清理全部不可撤销
        self._active_idx = None  # 当前已恢复到工作区的快照（None=保持导入后状态）
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_status)
        # Ctrl+Z → 撤销（与词库一致；恢复 / 单条删除可撤销）
        QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self).activated.connect(self._undo)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        root.addWidget(self._header())
        root.addWidget(self._task_card())
        root.addWidget(self._snap_card())

        self.legend = _label(
            "勾选「显示设计依据」可看到每个 UI 元素对应的文档条款。清理历史是破坏性操作，"
            "必须显式触发 + 二次确认。",
            size="xs", color="neutral.500", wrap=True)
        root.addWidget(self.legend)

        self._build_status(root)

    # ------------------------------------------------------------------ 头部

    def _header(self) -> QWidget:
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(_label("历史记录", size="2xl", color="neutral.900",
                             weight="bold"))
        col.addWidget(_label(
            "每次校正的任务列表：书名、时间、替换数；可从任一快照完整恢复现场并重新导出。",
            size="md", color="neutral.600", wrap=True))
        hl.addLayout(col, 1)

        self.basis_cb = QCheckBox("显示设计依据")
        self.basis_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.basis_cb.toggled.connect(self._toggle_basis)
        hl.addWidget(self.basis_cb, 0, Qt.AlignmentFlag.AlignTop)
        return w

    # ------------------------------------------------------------ 任务列表

    def _task_card(self) -> Card:
        card = Card(
            "任务列表", "重启不丢 · 清理历史为显式操作且需二次确认",
            collapsible=True, open_=True,
            basis="§2.2 入口⑥ · 验收① 跨会话保留",
        )
        self.basis_labels.append(card.basis)

        self._table = QWidget()
        self._table_body = QVBoxLayout(self._table)
        self._table_body.setContentsMargins(0, 0, 0, 0)
        self._table_body.setSpacing(0)
        card.body_l.addWidget(self._table)

        self._render_tasks()

        # 脚注 + 清理全部历史
        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(0, 12, 0, 12)
        fl.setSpacing(12)
        fnote = _label(
            "历史记录跨会话保留；同步失败不阻断主流程，但在此留痕。",
            size="xs", color="neutral.500")
        fl.addWidget(fnote, 1)
        clear = QPushButton("清理全部历史")
        clear.setObjectName("BtnDanger")
        clear.setCursor(Qt.CursorShape.PointingHandCursor)
        clear.clicked.connect(self._confirm_clear)
        fl.addWidget(clear, 0, Qt.AlignmentFlag.AlignRight)
        card.body_l.addWidget(foot)
        return card

    def _render_tasks(self):
        # 清掉旧行（结果卡销毁后其 basis 不会进这张表，但为稳妥仍逐个摘除）
        while self._table_body.count():
            item = self._table_body.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        self._table_body.addWidget(self._header_row())
        self._table_body.addWidget(hline())

        if not TASKS:
            empty = _label("暂无历史记录", size="sm", color="neutral.500")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 28, 0, 28)
            self._table_body.addWidget(empty)
            return

        for i, t in enumerate(TASKS):
            self._table_body.addWidget(self._task_row(t, i))
            if i != len(TASKS) - 1:
                self._table_body.addWidget(hline())

    def _refresh_active(self):
        """刷新「当前工作区」提示，反映已恢复到哪个快照。"""
        if self._active_idx is not None and 0 <= self._active_idx < len(TASKS):
            t = TASKS[self._active_idx]
            self._active_hint.setText(
                f"当前工作区：{t['book']}（{t['time']}，替换 {t['hits']} 处）")
        else:
            self._active_hint.setText("当前工作区：未指定（保持「导入后」状态）")

    def _header_row(self) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 10, 0, 10)
        hl.setSpacing(12)
        for text, stretch in zip(("书名", "时间", "替换数", "状态"),
                                COL_W[:4]):
            hl.addWidget(self._th(text), stretch)
        op = self._th("操作")
        op.setAlignment(Qt.AlignmentFlag.AlignRight)
        hl.addWidget(op, COL_W[4])
        return row

    def _th(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(
            f"color:{c('neutral.600')};font-weight:{FONT_WEIGHT['semibold']};"
            f"font-size:{fs('xs')};background:transparent")
        return lab

    def _task_row(self, t: dict, idx: int) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 12, 0, 12)
        hl.setSpacing(12)

        book = _label(t["book"], size="sm", weight="bold", color="neutral.900")
        hl.addWidget(book, COL_W[0])

        time = _label(t["time"], size="sm", color="neutral.500")
        hl.addWidget(time, COL_W[1])

        hits = _label(f"{t['hits']} 处", size="sm", color="neutral.700")
        hl.addWidget(hits, COL_W[2])

        hl.addWidget(self._status_cell(t["status"]), COL_W[3])

        acts = QWidget()
        ahl = QHBoxLayout(acts)
        ahl.setContentsMargins(0, 0, 0, 0)
        ahl.setSpacing(8)
        ahl.addStretch(1)
        if idx == self._active_idx:
            ahl.addWidget(Pill("当前工作区", "ok"))
        restore = QPushButton("↺ 恢复")
        restore.setObjectName("BtnOutline")
        restore.setCursor(Qt.CursorShape.PointingHandCursor)
        restore.clicked.connect(lambda _c, i=idx: self._confirm_restore(i))
        reexport = QPushButton("📤 重新导出")
        reexport.setObjectName("BtnOutline")
        reexport.setCursor(Qt.CursorShape.PointingHandCursor)
        reexport.clicked.connect(lambda _c, i=idx: self._reexport(i))
        delete = QPushButton("删除")
        delete.setObjectName("BtnDanger")
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.clicked.connect(lambda _c, i=idx: self._confirm_delete(i))
        ahl.addWidget(restore)
        ahl.addWidget(reexport)
        ahl.addWidget(delete)
        hl.addWidget(acts, COL_W[4])
        return row

    def _status_cell(self, status: str) -> QWidget:
        if status == "ok":
            return Pill("正常", "ok")
        # 基准同步失败：警示徽标 + 留痕说明
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(Pill("基准同步失败", "warn"))
        note = _label("已在历史留痕，不影响本书", size="xs", color="neutral.500")
        v.addWidget(note)
        return box

    # ---------------------------------------------------------- 快照与恢复

    def _snap_card(self) -> Card:
        card = Card(
            "快照与恢复", "恢复到任意时间点",
            collapsible=True, open_=True,
            basis="§2.7.8 · 失败兜底留痕",
        )
        self.basis_labels.append(card.basis)

        bullets = [
            "每次处理前自动创建快照，任一快照可<b>完整恢复现场</b>并重新导出。",
            "基准同步失败<b>不阻断主流程</b>，仅在历史记录中留痕（状态列标记）。",
            "恢复与单条删除均可撤销；清理全部历史不可恢复（均需二次确认）。",
        ]
        for b in bullets:
            lab = QLabel(f"• {b}")
            lab.setTextFormat(Qt.TextFormat.RichText)
            lab.setWordWrap(True)
            lab.setStyleSheet(
                f"color:{c('neutral.600')};font-size:{fs('sm')};"
                f"background:transparent;line-height:1.7")
            card.body_l.addWidget(lab)
            card.body_l.addSpacing(8)
        self._active_hint = QLabel("当前工作区：未指定（保持「导入后」状态）")
        self._active_hint.setWordWrap(True)
        self._active_hint.setStyleSheet(
            f"color:{c('primary.700')};font-size:{fs('sm')};"
            f"background:transparent;margin-top:4px")
        card.body_l.addWidget(self._active_hint)
        return card

    # -------------------------------------------------------------- 操作链路

    def _confirm_restore(self, idx: int):
        t = TASKS[idx]
        dlg = ConfirmDialog(
            icon="↺",
            title="恢复到该快照？",
            note=f"将把 {t['book']} 恢复到 {t['time']} 的状态"
                 f"（替换 {t['hits']} 处时点）。当前未保存的改动会被覆盖。"
                 f"确认后可在 Toast 中撤销。",
            confirm_text="确认恢复",
            confirm_kind="primary",
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            prev_active = self._active_idx
            self._undo_stack.append(
                dict(type="restore", prev_active=prev_active, idx=idx))
            self._active_idx = idx
            self._render_tasks()
            self._refresh_active()
            self._toast(f"已恢复 {t['book']} 到 {t['time']} 的快照", with_undo=True)

    def _reexport(self, idx: int):
        self._toast(f"已从历史结果重新导出 {TASKS[idx]['book']}")

    def _confirm_delete(self, idx: int):
        t = TASKS[idx]
        dlg = ConfirmDialog(
            icon="🗑",
            title="删除这条历史？",
            note=f"删除该快照可通过「撤销」恢复（二次确认）。"
                 f"受影响：{t['book']} · {t['time']}。",
            note_kind="warn",
            confirm_text="确认删除",
            confirm_kind="danger",
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._undo_stack.append(dict(type="delete", item=dict(t), index=idx))
            # 维护激活态：删除项即当前工作区 → 清空；否则随列表前移
            if self._active_idx is not None:
                if self._active_idx == idx:
                    self._active_idx = None
                elif self._active_idx > idx:
                    self._active_idx -= 1
            TASKS.pop(idx)
            self._render_tasks()
            self._refresh_active()
            self._toast("已删除该条历史", with_undo=True)

    def _confirm_clear(self):
        dlg = ConfirmDialog(
            icon="🧹",
            title="清理全部历史？",
            note=f"将删除全部 {len(TASKS)} 条任务及其快照，且不可恢复。"
                 f"清理历史为显式操作，需二次确认。",
            note_kind="warn",
            confirm_text="确认清理全部",
            confirm_kind="danger",
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._undo_stack.clear()  # 清理全部不可撤销：清空撤销栈
            self._active_idx = None
            TASKS.clear()
            self._render_tasks()
            self._refresh_active()
            self._toast("已清理全部历史")

    # ------------------------------------------------------------------ 公共

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

    # ------------------------------------------------------------------ 撤销

    def _undo(self):
        """恢复 / 单条删除可撤销；清理全部已清空栈，不可撤销。"""
        self._hide_status()
        if not self._undo_stack:
            self._toast("没有可撤销的操作")
            return
        last = self._undo_stack.pop()
        if last["type"] == "delete":
            idx = min(last["index"], len(TASKS))
            TASKS.insert(idx, last["item"])
            self._render_tasks()
            self._refresh_active()
            self._toast("已撤销删除，该条历史已恢复")
        elif last["type"] == "restore":
            self._active_idx = last.get("prev_active")
            self._render_tasks()
            self._refresh_active()
            self._toast("已撤销恢复，回到恢复前状态")

    # ------------------------------------------------------------------ 公共

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
        self.status.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
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
