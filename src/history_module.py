"""
FixText V1 · 历史记录模块（Qt 移植）
====================================

对照 `FixText_V1_历史记录_原型.html` **1:1 移植**，保持核心价值：
任务列表（书名 / 时间 / 替换数 / 状态 / 操作）→ 快照与恢复说明 → 清理全部历史。

结构：无书源条（历史是全局视图）→ 任务列表表格（恢复 / 重新导出 / 删除）
      → 快照与恢复说明卡 → 清理全部历史（破坏性，二次确认）。

产品规则（与导出结果一致）：
- 单条删除可撤销、清理全部不可恢复；两者均须显式触发 + 二次确认。
- 基准同步失败不阻断主流程，仅在状态列留痕。
- 条款号一律收进「显示设计依据」，正文不露 §。

复用部件见 `fixtext_widgets.py`（Card / Pill / hline）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialog, QSizePolicy, QCheckBox,
)

from fixtext_tokens import c, fs, FONT_WEIGHT
from fixtext_widgets import Card, Pill, hline


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
# 通用确认弹窗（二次确认统一入口）
# ---------------------------------------------------------------------------

class ConfirmDialog(QDialog):
    """带「取消 / 确认」的操作确认弹窗，用于恢复 / 删除 / 清理全部历史。

    note_kind="warn" 用琥珀底（破坏性操作），否则用信息底。
    confirm_kind="danger" 用危险按钮（红边），否则用主色按钮。
    """

    def __init__(self, *, icon: str, title: str, note: str,
                 note_kind: str = "info", confirm_text: str = "确认",
                 confirm_kind: str = "primary", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(480)
        self._build(icon, title, note, note_kind, confirm_text, confirm_kind)

    def _build(self, icon, title, note, note_kind, confirm_text, confirm_kind):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head.setObjectName("ModalHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(18, 16, 18, 16)
        ico = QLabel(icon)
        ico.setFixedSize(30, 30)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background:{c('primary.100')};color:{c('primary.700')};"
            f"border-radius:8px;font-size:16px")
        htitle = QLabel(title)
        htitle.setStyleSheet(
            f"font-weight:700;font-size:{fs('lg')};color:{c('neutral.900')}")
        hl.addWidget(ico)
        hl.addWidget(htitle)
        root.addWidget(head)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(18, 16, 18, 16)
        bl.setSpacing(12)
        nl = QLabel(note)
        nl.setWordWrap(True)
        if note_kind == "warn":
            nl.setStyleSheet(
                f"background:{c('warning.bg')};border:1px solid {c('warning.border')};"
                f"color:{c('warning')};border-radius:10px;padding:10px 14px;"
                f"font-size:{fs('sm')}")
        else:
            nl.setStyleSheet(
                f"background:{c('info.bg')};border:1px solid {c('info.border')};"
                f"color:{c('info')};border-radius:10px;padding:10px 14px;"
                f"font-size:{fs('sm')}")
        bl.addWidget(nl)
        root.addWidget(body)

        foot = QWidget()
        foot.setObjectName("ModalFoot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(18, 14, 18, 14)
        fl.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("BtnGhost")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        fl.addWidget(cancel)
        confirm = QPushButton(confirm_text)
        confirm.setObjectName(
            "BtnPrimary" if confirm_kind == "primary" else "BtnDanger")
        confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm.clicked.connect(self.accept)
        fl.addWidget(confirm)
        root.addWidget(foot)


# ---------------------------------------------------------------------------
# 模块
# ---------------------------------------------------------------------------

class HistoryModule(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.basis_labels = []
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_status)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        root.addWidget(self._header())
        root.addWidget(self._task_card())
        root.addWidget(self._snap_card())

        self.legend = _label(
            "勾选「显示设计依据」可看到每个 UI 元素对应的文档条款。清理历史是破坏性操作，"
            "必须显式触发 + 二次确认（§2.2 入口⑥ 验收③）。",
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
            "恢复与单条删除均可撤销；清理全部历史不可恢复（均需二次确认）（2.4.3 底线）。",
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
        return card

    # -------------------------------------------------------------- 操作链路

    def _confirm_restore(self, idx: int):
        t = TASKS[idx]
        dlg = ConfirmDialog(
            icon="↺",
            title="恢复到该快照？",
            note=f"将把 {t['book']} 恢复到 {t['time']} 的状态"
                 f"（替换 {t['hits']} 处时点）。当前未保存的改动会被覆盖。",
            confirm_text="确认恢复",
            confirm_kind="primary",
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._toast(f"已恢复 {t['book']} 到 {t['time']} 的快照")

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
            TASKS.pop(idx)
            self._render_tasks()
            self._toast("已删除该条历史")

    def _confirm_clear(self):
        dlg = ConfirmDialog(
            icon="🧹",
            title="清理全部历史？",
            note=f"将删除全部 {len(TASKS)} 条任务及其快照，且不可恢复。"
                 f"清理历史为显式操作，需二次确认（§2.2 入口⑥ 验收③）。",
            note_kind="warn",
            confirm_text="确认清理全部",
            confirm_kind="danger",
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            TASKS.clear()
            self._render_tasks()
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

    def _toast(self, msg: str):
        self.status.setText(msg)
        self.status.setVisible(True)
        self._toast_timer.start(2600)

    def _hide_status(self):
        self.status.setVisible(False)
