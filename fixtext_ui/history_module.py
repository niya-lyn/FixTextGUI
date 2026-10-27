"""
FixText V1 · 历史记录模块（Qt 移植 + 真实数据）
================================================

对照 `FixText_V1_历史记录_原型.html` **1:1 移植**，保持核心价值：
任务列表（书名 / 时间 / 替换数 / 状态 / 操作）→ 快照与恢复说明 → 清理全部历史。

数据来源（T2.10 接线）：一律来自**磁盘扫描** ``fixtext_history.scan_runs``，
重启后重扫即可恢复，没有任何内存态演示数据。没有运行记录时只显示空状态引导。

操作全部落到真实磁盘与真实导出：
- 「重新导出该次结果」→ ``fixtext_export.export_book`` 后台线程执行，产出真文件
- 「删除」→ 运行目录移入回收站（可撤销，撤销 = 移回原位）
- 「清理全部历史」→ 真删所有运行目录，不可撤销（显式二次确认）

说明：条目上的按钮是「重新导出该次结果」而不是「恢复到当时」——把一本书切回
某次运行的中间状态需要重建整条会话上下文，本版本以「用该次产物重新导出」作为
等价的可交付结果，按钮文案与说明卡都按这个口径写，不留假动作。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialog, QSizePolicy, QCheckBox,
)

import fixtext_history as histdata
from fixtext_tokens import c, fs, FONT_WEIGHT
from fixtext_widgets import Card, Pill, hline, ConfirmDialog


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

    #: 重新导出的结果（给主窗口 / 自检用）：(run_dir, 成功?, 说明)
    exportFinished = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.basis_labels = []
        self._undo_stack: list[dict] = []
        self._active_idx = None      # 当前工作区对应的条目下标
        #: 真实数据：来自磁盘扫描（空 = 还没跑过校正）
        self.tasks: list[dict] = []
        self._runs_root: Path | None = None
        self._export_ctx: dict | None = None   # 导出要用：导入记录 + 流水根
        self._exporting = False
        self._trash: list[Path] = []

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_status)
        # Ctrl+Z → 撤销（与词库一致；删除可撤销）
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

    # ------------------------------------------------------------------ 数据注入

    @property
    def row_count(self) -> int:
        return len(self.tasks)

    def set_runs_root(self, runs_root: str | Path | None) -> None:
        """指定运行目录根（历史就扫这里）。"""
        self._runs_root = Path(runs_root) if runs_root else None

    def set_export_ctx(self, ctx: dict | None) -> None:
        """注入导出所需上下文（导入记录 + 流水根）：``export_book`` 靠它定位产物。"""
        self._export_ctx = ctx

    def refresh(self) -> None:
        """按磁盘重扫一遍历史（重启后、或校正完成后都走这里）。"""
        if self._runs_root is None:
            self.tasks = []
        else:
            self.tasks = histdata.scan_runs(self._runs_root)
        self._render_tasks()
        self._refresh_active()

    def set_tasks(self, records: list[dict] | None) -> None:
        """直接注入一批历史记录（自检 / 外部接线用；数据仍是真实扫描结果）。"""
        self.tasks = list(records or [])
        self._render_tasks()
        self._refresh_active()

    def add_task(self, record: dict) -> None:
        """新增一条历史（去重按运行目录），并把列表按时间重排。"""
        run_dir = str(record.get("run_dir") or "")
        self.tasks = [t for t in self.tasks if t.get("run_dir") != run_dir]
        self.tasks.append(dict(record))
        self.tasks.sort(key=lambda r: r.get("time_ts") or 0, reverse=True)
        self._render_tasks()
        self._refresh_active()

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
            "每次校正的任务列表：书名、时间、替换数；可从任一记录重新导出当时的成品。",
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
            "历史记录跨会话保留，来自本机的运行目录；删除后可在提示条上撤销。",
            size="xs", color="neutral.500")
        fl.addWidget(fnote, 1)
        self.clear_btn = QPushButton("清理全部历史")
        self.clear_btn.setObjectName("BtnDanger")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self._confirm_clear)
        fl.addWidget(self.clear_btn, 0, Qt.AlignmentFlag.AlignRight)
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

        if not self.tasks:
            empty = _label(
                "还没有校正记录。去「一键校正」跑一次，这里就会按时间留一条。",
                size="sm", color="neutral.500", wrap=True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 28, 0, 28)
            self._table_body.addWidget(empty)
            if hasattr(self, "clear_btn"):
                self.clear_btn.setEnabled(False)
            return
        if hasattr(self, "clear_btn"):
            self.clear_btn.setEnabled(True)

        for i, t in enumerate(self.tasks):
            self._table_body.addWidget(self._task_row(t, i))
            if i != len(self.tasks) - 1:
                self._table_body.addWidget(hline())

    def _refresh_active(self):
        """刷新「当前工作区」提示，反映已恢复到哪个快照。"""
        if self._active_idx is not None and 0 <= self._active_idx < len(self.tasks):
            t = self.tasks[self._active_idx]
            hits = "—" if t.get("hits") is None else f"{t['hits']} 处"
            self._active_hint.setText(
                f"当前工作区：{t['book']}（{t['time']}，替换 {hits}）")
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

        book = _label(t.get("book") or t.get("title") or "（未命名）",
                      size="sm", weight="bold", color="neutral.900")
        hl.addWidget(book, COL_W[0])

        time_txt = _label(t.get("time") or "—", size="sm", color="neutral.500")
        hl.addWidget(time_txt, COL_W[1])

        hits_v = t.get("hits")
        hits = _label("—" if hits_v is None else f"{hits_v} 处",
                      size="sm", color="neutral.700")
        hl.addWidget(hits, COL_W[2])

        hl.addWidget(self._status_cell(t), COL_W[3])

        acts = QWidget()
        ahl = QHBoxLayout(acts)
        ahl.setContentsMargins(0, 0, 0, 0)
        ahl.setSpacing(8)
        ahl.addStretch(1)
        if idx == self._active_idx:
            ahl.addWidget(Pill("当前工作区", "ok"))
        restore = QPushButton("↺ 重新导出该次结果")
        restore.setObjectName("BtnOutline")
        restore.setCursor(Qt.CursorShape.PointingHandCursor)
        restore.setToolTip("用这次校正的成品重新导出一份文件")
        restore.clicked.connect(lambda _c, i=idx: self._confirm_restore(i))
        delete = QPushButton("删除")
        delete.setObjectName("BtnDanger")
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.clicked.connect(lambda _c, i=idx: self._confirm_delete(i))
        ahl.addWidget(restore)
        ahl.addWidget(delete)
        hl.addWidget(acts, COL_W[4])
        return row

    def _status_cell(self, t: dict) -> QWidget:
        if t.get("status") != "syncfail":
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

    # ---------------------------------------------------------- 说明卡

    def _snap_card(self) -> Card:
        card = Card(
            "记录与重新导出", "每条记录都能再导出一份成品",
            collapsible=True, open_=True,
            basis="§2.7.8 · 失败兜底留痕",
        )
        self.basis_labels.append(card.basis)

        bullets = [
            "每条记录对应一次真实校正，产物就在本机运行目录里，重启后仍在。",
            "「重新导出该次结果」会用那次校正的成品再导出一份，校验值与当时一致。",
            "删除可撤销（运行目录先移入回收站）；清理全部历史不可恢复（均需二次确认）。",
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
        """用该次运行的产物重新导出（真实执行，产出真文件）。"""
        if not (0 <= idx < len(self.tasks)):
            self._toast("这条记录已不在列表里")
            return
        t = self.tasks[idx]
        hits = "—" if t.get("hits") is None else f"{t['hits']} 处"
        dlg = ConfirmDialog(
            icon="↺",
            title="用这次的结果重新导出一份？",
            note=f"将使用 {t['book']}（{t['time']}，替换 {hits}）那次校正的成品，"
                 f"重新导出一份放到导出目录。原书与本次校正结果都不改动。",
            confirm_text="重新导出",
            confirm_kind="primary",
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._active_idx = idx
        self._render_tasks()
        self._refresh_active()
        self._run_export(t)

    def _run_export(self, t: dict):
        """后台线程跑真实导出，界面线程收尾（不阻塞窗口）。"""
        if self._exporting:
            self._toast("上一次导出还没结束，稍等一下")
            return
        run_dir = str(t.get("run_dir") or "")
        if not run_dir or not Path(run_dir).is_dir():
            self._toast("这次运行的产物已经不在了，无法重新导出")
            return
        self._exporting = True
        self._toast(f"正在重新导出 {t['book']}…")
        ctx = dict(self._export_ctx or {})
        holder: dict = {}

        def work():
            try:
                holder["out"] = self._do_export(run_dir, ctx)
            except Exception as exc:  # noqa: BLE001 - 后台线程不外抛
                holder["err"] = exc
            finally:
                self._exporting = False

        threading.Thread(target=work, daemon=True).start()
        self._poll_export(t, holder)

    def _do_export(self, run_dir: str, ctx: dict) -> object:
        """真实导出：定位那次运行的正文，产出可交付文件。"""
        import fixtext_export as fx

        pipeline_root = ctx.get("pipeline_root") or ""
        summary = fx.load_run_summary(run_dir)
        source = fx.resolve_source(ctx.get("import_record"), summary, pipeline_root)
        fmt = "epub" if source.can_restore_epub else "txt"
        out_dir = Path(ctx.get("out_dir") or (Path(run_dir) / "reexport"))
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out_dir = out_dir / f"reexport_{stamp}"
        return fx.export_book(source, out_dir, fmt=fmt,
                              baseline_sha256=ctx.get("baseline_sha256") or "")

    def _poll_export(self, t: dict, holder: dict):
        """等后台导出结束（120ms 一轮，界面不被卡住）。"""
        if "out" not in holder and "err" not in holder:
            QTimer.singleShot(120, lambda: self._poll_export(t, holder))
            return
        if "err" in holder:
            self._toast(f"重新导出没成功：{holder['err']}")
            self.exportFinished.emit((t.get("run_dir"), False, str(holder["err"])))
            return
        out = holder["out"]
        name = Path(getattr(out, "main_file", "") or "").name
        sha = getattr(out, "sha256", "") or ""
        match = getattr(out, "sha_match", None)
        said = f"已重新导出 {name}"
        if sha:
            said += f"（校验值 {sha[:8]}…"
            said += "，与当时一致）" if match else "）"
        self._toast(said)
        self.exportFinished.emit((t.get("run_dir"), True, said))

    def _confirm_delete(self, idx: int):
        if not (0 <= idx < len(self.tasks)):
            return
        t = self.tasks[idx]
        dlg = ConfirmDialog(
            icon="🗑",
            title="删除这条历史？",
            note=f"删除后可在提示条上撤销。受影响：{t['book']} · {t['time']}。",
            note_kind="warn",
            confirm_text="确认删除",
            confirm_kind="danger",
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        run_dir = str(t.get("run_dir") or "")
        trash_dir = (self._runs_root / "_trash") if self._runs_root else None
        moved = histdata.delete_run(run_dir, trash_dir) if run_dir else None
        self._undo_stack.append(dict(type="delete", item=dict(t), index=idx,
                                     trash=str(moved or "")))
        if moved is not None:
            self._trash.append(moved)
        # 维护激活态：删除项即当前工作区 → 清空；否则随列表前移
        if self._active_idx is not None:
            if self._active_idx == idx:
                self._active_idx = None
            elif self._active_idx > idx:
                self._active_idx -= 1
        self.tasks.pop(idx)
        self._render_tasks()
        self._refresh_active()
        self._toast("已删除该条历史", with_undo=True)

    def _confirm_clear(self):
        n = len(self.tasks)
        dlg = ConfirmDialog(
            icon="🧹",
            title="清理全部历史？",
            note=f"将删除全部 {n} 条任务及其结果文件，且不可恢复。"
                 f"清理历史为显式操作，需二次确认。",
            note_kind="warn",
            confirm_text="确认清理全部",
            confirm_kind="danger",
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._undo_stack.clear()  # 清理全部不可撤销：清空撤销栈
            self._active_idx = None
            if self._runs_root is not None:
                histdata.clear_all(self._runs_root)
            self.tasks = []
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
        """删除可撤销（把运行目录移回原位）；清理全部已清空栈，不可撤销。"""
        self._hide_status()
        if not self._undo_stack:
            self._toast("没有可撤销的操作")
            return
        last = self._undo_stack.pop()
        if last["type"] == "delete":
            item = last["item"]
            restored = False
            if last.get("trash"):
                restored = histdata.restore_run(last["trash"], item["run_dir"])
                if restored and Path(last["trash"]) in self._trash:
                    self._trash.remove(Path(last["trash"]))
            idx = min(last["index"], len(self.tasks))
            if restored:
                self.tasks.insert(idx, item)
            else:
                self.refresh()      # 目录恢复失败就照磁盘事实重扫
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
        self._toast_timer.start(5000 if with_undo else 5200)

    def _hide_status(self):
        """提示条到点自动收起（不改动任何数据）。"""
        self.status_box.setVisible(False)
