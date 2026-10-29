"""
FixText V1 · 历史记录模块（Qt 移植 + 真实数据 + 快照恢复）
=======================================================

对照 `FixText_V1_历史记录_原型.html` **1:1 移植**，保持核心价值：
任务列表（书名 / 时间 / 替换数 / 状态 / 操作）→ 快照与恢复 → 清理全部历史。

数据来源（T2.10 接线）：一律来自**磁盘扫描** ``fixtext_history.scan_runs``，
重启后重扫即可恢复，没有任何内存态演示数据。没有运行记录时只显示空状态引导。

操作全部落到真实磁盘与真实执行层：
- 「恢复」→ 列出这次运行真实留下的阶段点，选一个就**把现场切到该点**
  （``fixtext_run_snapshot.restore_point``：产物逐字节复制成当前工作区），
  之后既可直接导出该点成品，也可从该点继续往后跑（管线断点续跑）；
- 「重新导出」→ ``fixtext_export.export_book`` 后台线程执行，产出真文件；
- 「从当前工作区继续」→ ``fixtext_run_snapshot.resume_from_point``，
  已完成的阶段按断点续跑规则跳过，不重跑；
- 「删除」→ 运行目录移入回收站（可撤销）；「清理全部历史」→ 不可撤销（二次确认）。

恢复只读原书、不动历史记录，全部影响收在 ``runs/_snapshots/`` 下，
因此「撤销」= 把当前工作区指针指回恢复前那个快照。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialog, QSizePolicy, QCheckBox, QRadioButton,
)

import fixtext_history as histdata
import fixtext_run_snapshot as snapshot
from fixtext_tokens import c, fs, FONT_WEIGHT
from fixtext_widgets import Card, Pill, hline, ConfirmDialog, Modal, EmptyState


# 列表列宽比例（头行与数据行共用，保证对齐）。操作列右对齐。
COL_W = (3, 2, 1, 2, 5)


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
# 时点选择弹窗（列真实存在的阶段点；不可用的置灰并写明原因）
# ---------------------------------------------------------------------------

class SnapshotDialog(Modal):
    """「恢复到哪个时点？」——把这次运行真实留下的阶段点列出来供选。

    ``points`` 来自 :func:`fixtext_run_snapshot.list_points`，``available`` 是
    机器判定（磁盘上有没有产物），不可用的选项**置灰**并写明原因。
    这个弹窗同时就是那次二次确认：确认按钮只在选了可用时点后启用，
    弹窗正文写明影响范围与可撤销。
    """

    def __init__(self, *, book: str, when: str, points: list[dict], parent=None):
        super().__init__(icon="↺", title="恢复到哪个时点？", parent=parent,
                         min_width=640)
        self.chosen = ""
        self._radios: dict[str, QRadioButton] = {}
        usable = [p for p in points if p.get("available")]
        total = len(points)

        self.add_note(
            f"{book}（{when}）在这次处理里留下了 {len(usable)} 个可恢复的时点。"
            f"恢复会把当前工作区切到选中的那一刻；之后没保存的改动会被覆盖，"
            f"历史记录与原书都不受影响，恢复本身可以在提示条上撤销。",
            "info")

        for p in points:
            self.add_widget(self._point_row(p))
            self.add_spacing(2)

        self.add_foot("取消", "ghost", self.reject)
        self.ok_btn = self.add_foot("确认恢复", "primary", self._take)
        self.ok_btn.setEnabled(False)
        #: 全部不可用时给一句人话说明（不假装可用）
        if not usable:
            self.add_note(
                f"这次运行（共 {total} 个时点）在磁盘上没有留下可恢复的结果，"
                f"只能重新导出它当时的成品。", "warn")

    def _point_row(self, p: dict) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        radio = QRadioButton(str(p.get("name") or ""))
        radio.setObjectName("SnapPoint")
        radio.setCursor(Qt.CursorShape.PointingHandCursor)
        available = bool(p.get("available"))
        radio.setEnabled(available)
        radio.setStyleSheet(
            f"QRadioButton{{color:{c('neutral.900' if available else 'neutral.400')};"
            f"font-size:{fs('sm')};font-weight:{FONT_WEIGHT['semibold']}}}")
        if available:
            radio.toggled.connect(self._on_toggle)
            self._radios[str(p.get("key"))] = radio
        hl.addWidget(radio, 0)

        col = QVBoxLayout()
        col.setSpacing(2)
        desc = _label(str(p.get("desc") or ""),
                      size="xs",
                      color="neutral.600" if available else "neutral.400")
        col.addWidget(desc)
        if not available:
            col.addWidget(_label(f"为什么不能选：{p.get('reason') or '没有留下结果'}",
                                 size="xs", color="warning"))
        hl.addLayout(col, 1)
        hl.addWidget(Pill("可用", "ok") if available else Pill("不可用", "neutral"), 0)
        return row

    def _on_toggle(self, checked: bool):
        if checked:
            self.ok_btn.setEnabled(True)

    def _take(self):
        pick = [k for k, r in self._radios.items() if r.isChecked()]
        if not pick:
            return
        self.chosen = pick[0]
        self.accept()


# ---------------------------------------------------------------------------
# 模块
# ---------------------------------------------------------------------------

class HistoryModule(QWidget):

    #: 重新导出的结果（给主窗口 / 自检用）：(run_dir, 成功?, 说明)
    exportFinished = Signal(object)
    #: 恢复的结果：(本次运行目录, 时点 key, 成功?)
    restoreFinished = Signal(object)
    #: 从当前工作区继续的结果：(退出码, 各阶段状态)
    resumeFinished = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.basis_labels = []
        self._undo_stack: list[dict] = []
        self._active_idx = None      # 当前工作区对应的条目下标
        self._current: dict | None = None   # 当前工作区指针（磁盘）
        self._last_restore: dict = {}       # 最近一次恢复的现场证据
        #: 真实数据：来自磁盘扫描（空 = 还没跑过校正）
        self.tasks: list[dict] = []
        self._runs_root: Path | None = None
        self._export_ctx: dict | None = None   # 导出 / 续跑要用：流水根 + 规则 + 引擎
        self._exporting = False
        self._resuming = False
        self._trash: list[Path] = []

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_status)
        # Ctrl+Z → 撤销（与词库一致；删除 / 恢复都可撤销）
        QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self).activated.connect(self._undo)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        root.addWidget(self._header())

        # 无任务空状态（原型 v3 §4）：还没有校正历史时整页内容区换成
        # 这条引导；由真实状态触发（磁盘扫描结果为空）。
        self.empty_state = EmptyState(
            "🕓", "还没有校正历史",
            "完成一次校正后，任务会自动出现在这里，可随时恢复任意时间点或重新导出。"
            "当前页面在有任务状态下展示；无任务时仅显示此引导。")
        root.addWidget(self.empty_state)

        self._task_w = self._task_card()
        self._snap_w = self._snap_card()
        root.addWidget(self._task_w)
        root.addWidget(self._snap_w)

        self.legend = _label(
            "清理历史是破坏性操作，必须显式触发 + 二次确认。",
            size="xs", color="neutral.500", wrap=True)
        root.addWidget(self.legend)

        self._build_status(root)

    # ------------------------------------------------------------------ 数据注入

    @property
    def row_count(self) -> int:
        return len(self.tasks)

    def set_runs_root(self, runs_root: str | Path | None) -> None:
        """指定运行目录根（历史就扫这里，快照也落在这里）。"""
        self._runs_root = Path(runs_root) if runs_root else None

    def set_export_ctx(self, ctx: dict | None) -> None:
        """注入导出 / 续跑所需上下文：流水根、导出目录、词库与引擎路径。"""
        self._export_ctx = ctx

    def refresh(self) -> None:
        """按磁盘重扫一遍历史（重启后、或校正完成后都走这里）。"""
        if self._runs_root is None:
            self.tasks = []
        else:
            self.tasks = histdata.scan_runs(self._runs_root)
        self._sync_current()
        self._render_tasks()
        self._refresh_active()

    def set_tasks(self, records: list[dict] | None) -> None:
        """直接注入一批历史记录（自检 / 外部接线用；数据仍是真实扫描结果）。"""
        self.tasks = list(records or [])
        self._sync_current()
        self._render_tasks()
        self._refresh_active()

    def add_task(self, record: dict) -> None:
        """新增一条历史（去重按运行目录），并把列表按时间重排。"""
        run_dir = str(record.get("run_dir") or "")
        self.tasks = [t for t in self.tasks if t.get("run_dir") != run_dir]
        self.tasks.append(dict(record))
        self.tasks.sort(key=lambda r: r.get("time_ts") or 0, reverse=True)
        self._sync_current()
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
            "每次校正的任务列表：书名、时间、替换数；可从任一快照完整恢复现场并重新导出。",
            size="md", color="neutral.600", wrap=True))
        hl.addLayout(col, 1)
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
            # 空状态（原型 v3 §4）：任务表与快照面板都收起，整页只留引导。
            # 构造期（_task_card 内部首渲染）时宿主还没赋值，用 getattr 兜过。
            task_w = getattr(self, "_task_w", None)
            snap_w = getattr(self, "_snap_w", None)
            es = getattr(self, "empty_state", None)
            if task_w is not None:
                task_w.setVisible(False)
            if snap_w is not None:
                snap_w.setVisible(False)
            if es is not None:
                es.setVisible(True)
            if hasattr(self, "clear_btn"):
                self.clear_btn.setEnabled(False)
            return
        if getattr(self, "_task_w", None) is not None:
            self._task_w.setVisible(True)
            self._snap_w.setVisible(True)
            self.empty_state.setVisible(False)
        if hasattr(self, "clear_btn"):
            self.clear_btn.setEnabled(True)

        for i, t in enumerate(self.tasks):
            self._table_body.addWidget(self._task_row(t, i))
            if i != len(self.tasks) - 1:
                self._table_body.addWidget(hline())

    def _sync_current(self) -> dict | None:
        """读磁盘上的「当前工作区」指针，并算出它对应列表里哪一条。

        指针是磁盘文件（``runs/_snapshots/current.json``），所以重启之后
        依然读得出「这本书现在停在哪个时点」。
        """
        cur = snapshot.current_state(self._runs_root) if self._runs_root else None
        self._current = cur
        rid = str((cur or {}).get("run_dir") or "")
        self._active_idx = None
        if rid:
            for i, t in enumerate(self.tasks):
                if str(t.get("run_dir") or "") == rid:
                    self._active_idx = i
                    break
        return cur

    def _refresh_active(self):
        """刷新「当前工作区」提示与续跑 / 导出的可用性（数据来自磁盘指针）。"""
        cur = self._sync_current()
        if hasattr(self, "_active_hint"):
            self._active_hint.setText(snapshot.current_summary_text(cur))
        ready = bool((cur or {}).get("working_text"))
        for name in ("continue_btn", "export_ws_btn"):
            btn = getattr(self, name, None)
            if btn is not None:
                btn.setEnabled(ready)
                btn.setToolTip("" if ready else "先在某条记录上选一个时点恢复，才有可用的工作区")

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
        restore = QPushButton("↺ 恢复")
        restore.setObjectName("BtnOutline")
        restore.setCursor(Qt.CursorShape.PointingHandCursor)
        restore.setToolTip("把这本书切回这次处理留下的某个时点（可撤销）")
        restore.clicked.connect(lambda _c, i=idx: self._open_snapshot_dialog(i))
        reexp = QPushButton("📤 重新导出")
        reexp.setObjectName("BtnOutline")
        reexp.setCursor(Qt.CursorShape.PointingHandCursor)
        reexp.setToolTip("用这次校正的成品重新导出一份文件")
        reexp.clicked.connect(lambda _c, i=idx: self._confirm_restore(i))
        delete = QPushButton("删除")
        delete.setObjectName("BtnDanger")
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.clicked.connect(lambda _c, i=idx: self._confirm_delete(i))
        ahl.addWidget(restore)
        ahl.addWidget(reexp)
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
            "快照与恢复", "恢复到任意时间点",
            collapsible=True, open_=True,
            basis="§2.2 入口⑥ · 验收② 任一快照可完整恢复现场",
        )
        self.basis_labels.append(card.basis)

        bullets = [
            "每次处理在每个阶段边界都会留下可恢复的现场，任一快照都能完整恢复并重新导出。",
            "恢复会覆盖当前工作区，需二次确认；恢复与单条删除都能撤销，清理全部历史不可恢复。",
            "基准同步失败不阻断主流程，仅在任务列表里留痕。",
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

        self._active_hint = QLabel(snapshot.current_summary_text(None))
        self._active_hint.setWordWrap(True)
        self._active_hint.setObjectName("ActiveHint")
        self._active_hint.setStyleSheet(
            f"color:{c('primary.700')};font-size:{fs('sm')};"
            f"background:transparent;margin-top:4px")
        card.body_l.addWidget(self._active_hint)

        acts = QWidget()
        al = QHBoxLayout(acts)
        al.setContentsMargins(0, 8, 0, 0)
        al.setSpacing(8)
        self.export_ws_btn = QPushButton("导出当前工作区的成品")
        self.export_ws_btn.setObjectName("BtnOutline")
        self.export_ws_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_ws_btn.clicked.connect(self._confirm_export_workspace)
        self.continue_btn = QPushButton("从当前工作区继续")
        self.continue_btn.setObjectName("BtnPrimary")
        self.continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.continue_btn.clicked.connect(self._confirm_continue)
        al.addStretch(1)
        al.addWidget(self.export_ws_btn)
        al.addWidget(self.continue_btn)
        card.body_l.addWidget(acts)

        self.export_ws_btn.setEnabled(False)
        self.continue_btn.setEnabled(False)
        self.export_ws_btn.setToolTip("先在某条记录上选一个时点恢复，才有可用的工作区")
        self.continue_btn.setToolTip("先在某条记录上选一个时点恢复，才有可用的工作区")
        return card

    # -------------------------------------------------------------- 快照恢复

    def _open_snapshot_dialog(self, idx: int):
        """列出该运行真实留下的阶段点，选一个就恢复（弹窗即二次确认）。"""
        if not (0 <= idx < len(self.tasks)):
            self._toast("这条记录已不在列表里")
            return
        t = self.tasks[idx]
        run_dir = str(t.get("run_dir") or "")
        if not run_dir or not Path(run_dir).is_dir():
            self._toast("这次运行的结果已经不在了，无法恢复")
            return
        points = snapshot.list_points(run_dir)
        if not points:
            self._toast("这次运行没有留下可恢复的时点")
            return
        dlg = SnapshotDialog(book=str(t.get("book") or ""),
                             when=str(t.get("time") or ""),
                             points=points, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.chosen:
            return
        self._apply_restore(idx, dlg.chosen, points)

    def _apply_restore(self, idx: int, point_key: str,
                       points: list[dict] | None = None):
        """真恢复：把该书当前状态切到该时点产物（逐字节复制 + sha 当场比对）。"""
        if not (0 <= idx < len(self.tasks)):
            return None
        if self._runs_root is None:
            self._toast("还没有可用的工作区目录")
            return None
        t = self.tasks[idx]
        run_dir = str(t.get("run_dir") or "")
        prev_active = self._active_idx
        res = snapshot.restore_point(run_dir, point_key, self._runs_root)
        self._last_restore = res.to_dict()
        if not res.ok:
            self._toast(res.message or "恢复没成功")
            self.restoreFinished.emit((run_dir, point_key, False))
            return res
        self._undo_stack.append(dict(type="restore", index=idx,
                                     prev_active=prev_active,
                                     snapshot=res.snapshot_dir,
                                     prev_snapshot=res.prev_snapshot,
                                     point=point_key))
        self._sync_current()
        self._render_tasks()
        self._refresh_active()
        pt = snapshot.POINT_BY_KEY.get(point_key, {})
        self._toast(f"已恢复到「{res.point_name or pt.get('name')}」时点，"
                    f"可从这里导出或继续", with_undo=True)
        self.restoreFinished.emit((run_dir, point_key, True))
        return res

    # -------------------------------------------------------------- 导出链路

    def _confirm_restore(self, idx: int):
        """用该次运行的产物重新导出（真实执行，产出真文件）。"""
        if not (0 <= idx < len(self.tasks)):
            self._toast("这条记录已不在列表里")
            return
        t = self.tasks[idx]
        hits = "—" if t.get("hits") is None else f"{t['hits']} 处"
        dlg = ConfirmDialog(
            icon="📤",
            title="用这次的结果重新导出一份？",
            note=f"将使用 {t['book']}（{t['time']}，替换 {hits}）那次校正的成品，"
                 f"重新导出一份放到导出目录。原书与本次校正结果都不改动。",
            confirm_text="重新导出",
            confirm_kind="primary",
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._run_export(t)

    def _run_export(self, t: dict, *, workspace: bool = False):
        """后台线程跑真实导出，界面线程收尾（不阻塞窗口）。"""
        if self._exporting:
            self._toast("上一次导出还没结束，稍等一下")
            return
        ctx = dict(self._export_ctx or {})
        run_dir = str(t.get("run_dir") or "")
        if not workspace:
            if not run_dir or not Path(run_dir).is_dir():
                self._toast("这次运行的产物已经不在了，无法重新导出")
                return
        elif not self._current:
            self._toast("还没有恢复过时点，当前工作区是空的")
            return
        self._exporting = True
        self._toast(f"正在导出 {t.get('book') or '这本书'}…")
        holder: dict = {}

        def work():
            try:
                if workspace:
                    holder["out"] = self._do_export_workspace(ctx)
                else:
                    holder["out"] = self._do_export(run_dir, ctx)
            except Exception as exc:  # noqa: BLE001 - 后台线程不外抛
                holder["err"] = exc
            finally:
                self._exporting = False

        threading.Thread(target=work, daemon=True).start()
        self._poll_export(t, holder)

    def _do_export(self, run_dir: str, ctx: dict) -> object:
        """真实导出：定位那次运行的正文，产出可交付文件。

        取源优先走「只凭运行目录重建」——这样**重启进程后**（导入记录已不在）
        重新导出照样能跑；只有在拿不到运行摘要时才退回导入记录那条老路。
        """
        import fixtext_export as fx

        pipeline_root = ctx.get("pipeline_root") or ""
        summary = fx.load_run_summary(run_dir)
        source = fx.resolve_source_from_run(run_dir, summary, pipeline_root)
        if not source.text_path:
            source = fx.resolve_source(ctx.get("import_record"), summary, pipeline_root)
        return self._export_with(source, ctx, run_dir,
                                 baseline=str((summary or {}).get("restored_sha256") or ""))

    def _do_export_workspace(self, ctx: dict) -> object:
        """从「当前工作区」（某个恢复点的现场）导出成品。"""
        cur = snapshot.current_state(self._runs_root) if self._runs_root else None
        if not cur:
            raise RuntimeError("还没有恢复过时点")
        source = snapshot.build_export_source(cur, ctx.get("pipeline_root"))
        summary = snapshot.load_run_summary(str(cur.get("run_dir") or ""))
        return self._export_with(source, ctx, str(cur.get("snapshot_dir") or ""),
                                 baseline=str((summary or {}).get("restored_sha256") or ""))

    @staticmethod
    def _export_with(source, ctx: dict, anchor: str, *, baseline: str = ""):
        import fixtext_export as fx

        fmt = "epub" if source.can_restore_epub else "txt"
        base = Path(ctx.get("out_dir") or (Path(anchor) / "exported"))
        out_dir = base / f"export_{time.strftime('%Y%m%d_%H%M%S')}"
        return fx.export_book(source, out_dir, fmt=fmt,
                              baseline_sha256=baseline or ctx.get("baseline_sha256") or "")

    def _poll_export(self, t: dict, holder: dict):
        """等后台导出结束（120ms 一轮，界面不被卡住）。"""
        if "out" not in holder and "err" not in holder:
            QTimer.singleShot(120, lambda: self._poll_export(t, holder))
            return
        if "err" in holder:
            self._toast(f"导出没成功：{holder['err']}")
            self.exportFinished.emit((t.get("run_dir"), False, str(holder["err"])))
            return
        out = holder["out"]
        name = Path(getattr(out, "main_file", "") or "").name
        sha = getattr(out, "sha256", "") or ""
        match = getattr(out, "sha_match", None)
        said = f"已导出 {name}"
        if sha:
            said += f"（校验值 {sha[:8]}…"
            said += "，与当时一致）" if match else "）"
        self._record_export_outcome(t, out)
        self._toast(said)
        self.exportFinished.emit((t.get("run_dir"), True, said))

    def _record_export_outcome(self, t: dict, out) -> None:
        """历史页重新导出成功 → 写这本书的导出记录与该次运行的导出状态。

        与导出页的写点是同一个数据源（书的 exports.json + 运行摘要），
        这样无论从哪一页导出，书架「已导出」标识和历史条目状态都点亮。
        """
        import fixtext_shelf as shelf

        run_dir = str(t.get("run_dir") or "")
        sha = str(getattr(out, "sha256", "") or "")
        main_file = str(getattr(out, "main_file", "") or "")
        fmt = str(getattr(out, "fmt", "") or "")
        hits = getattr(out, "hits", None)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        if run_dir and Path(run_dir).is_dir():
            histdata.write_run_meta(run_dir, exported_at=now, exported_sha256=sha)
        book_dir = str((self._export_ctx or {}).get("book_dir") or "")
        if book_dir and Path(book_dir).is_dir():
            shelf.write_export_record(
                book_dir, fmt=fmt, path=main_file, sha256=sha,
                hits=hits if isinstance(hits, int) else None)

    def _confirm_export_workspace(self):
        """导出「当前工作区」那一刻的成品（恢复完直接出文件，不用再跑一遍）。"""
        cur = snapshot.current_state(self._runs_root) if self._runs_root else None
        if not cur:
            self._toast("还没有恢复过时点，当前工作区是空的")
            return
        t = dict(book=cur.get("book") or "", run_dir=str(cur.get("run_dir") or ""))
        self._run_export(t, workspace=True)

    # ---------------------------------------------------------------- 续跑

    def _confirm_continue(self):
        """从当前工作区的时点继续往后跑（跳过已完成的阶段）。"""
        cur = snapshot.current_state(self._runs_root) if self._runs_root else None
        if not cur:
            self._toast("还没有恢复过时点，当前工作区是空的")
            return
        if self._resuming:
            self._toast("上一次继续还没结束，稍等一下")
            return
        ctx = dict(self._export_ctx or {})
        if not (ctx.get("rules_before") and ctx.get("rules_after")
                and ctx.get("engine_path")):
            self._toast("词库或处理组件不在原位，暂时不能继续")
            return
        dlg = ConfirmDialog(
            icon="⏭",
            title="从当前工作区往下继续？",
            note=f"将从 {cur.get('book') or '这本书'} 的「{cur.get('point_name') or '当前时点'}」"
                 f"接着往后做：这一步之前已经做完的部分会直接沿用（不重跑），"
                 f"只补做后面的步骤。原书只读，历史记录不受影响。",
            confirm_text="继续",
            confirm_kind="primary",
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._run_continue(cur, ctx)

    def _run_continue(self, cur: dict, ctx: dict):
        self._resuming = True
        self._toast("正在从当前工作区继续…")
        holder: dict = {}
        snap_dir = str(cur.get("snapshot_dir") or "")

        def work():
            try:
                holder["out"] = self._do_continue(snap_dir, ctx)
            except Exception as exc:  # noqa: BLE001
                holder["err"] = exc
            finally:
                self._resuming = False

        threading.Thread(target=work, daemon=True).start()
        self._poll_continue(holder)

    def _do_continue(self, snap_dir: str, ctx: dict) -> dict:
        """真跑：管线 resume（已完成阶段跳过），跑完把结果登记成当前工作区。"""
        cur = snapshot.current_state(self._runs_root) or {}
        meta = {}
        try:
            import json
            meta = json.loads((Path(snap_dir) / snapshot.META_FILE)
                              .read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        epub = str(cur.get("template_epub") or meta.get("template_epub") or "")
        if not epub or not Path(epub).is_file():
            epub = str(snapshot.load_run_summary(
                str(cur.get("run_dir") or "")).get("source_epub") or "")
        if not epub or not Path(epub).is_file():
            raise RuntimeError("找不到这本书的原书，无法继续")
        stamp = time.strftime("%Y%m%d_%H%M%S")
        work_dir = Path(self._runs_root) / snapshot.SNAPSHOT_DIRNAME / f"work-{stamp}"
        return snapshot.resume_from_point(
            snap_dir, self._runs_root,
            point=str(cur.get("point") or meta.get("point") or ""),
            epub=epub,
            rules_before=ctx.get("rules_before"),
            rules_after=ctx.get("rules_after"),
            engine_path=ctx.get("engine_path"),
            pipeline_root=ctx.get("pipeline_root"),
            work_dir=work_dir,
        )

    def _poll_continue(self, holder: dict):
        if "out" not in holder and "err" not in holder:
            QTimer.singleShot(200, lambda: self._poll_continue(holder))
            return
        if "err" in holder:
            self._toast(f"继续没成功：{holder['err']}")
            self.resumeFinished.emit((None, {}))
            return
        out = holder["out"]
        rep = out.get("report") or {}
        stages = {}
        for name, r in (rep.get("stages") or {}).items():
            stages[name] = dict(status=r.get("status"),
                                elapsed_s=r.get("elapsed_s"))
        code = out.get("exit_code")
        skipped = [k for k, v in stages.items() if v.get("status") == "skipped"]
        self._undo_stack.append(dict(type="restore", index=self._active_idx,
                                     prev_active=None,
                                     snapshot=str((out.get("adopted") or {}).get("snapshot_dir") or ""),
                                     prev_snapshot=str(
                                         (snapshot.current_state(self._runs_root) or {})
                                         .get("prev_snapshot") or ""),
                                     point=str(out.get("resume_from") or "")))
        self._sync_current()
        self._render_tasks()
        self._refresh_active()
        if code == 0:
            self._toast(f"已继续到最新成品（沿用了 {len(skipped)} 个已完成步骤）",
                        with_undo=True)
        else:
            self._toast(f"继续没跑完（退出码 {code}），可以先恢复回刚才的时点")
        self.resumeFinished.emit((code, stages))

    # ---------------------------------------------------------------- 删除

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
        self.tasks.pop(idx)
        self._sync_current()
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
            if self._runs_root is not None:
                histdata.clear_all(self._runs_root)
            self.tasks = []
            self._sync_current()
            self._render_tasks()
            self._refresh_active()
            self._toast("已清理全部历史")

    # ------------------------------------------------------------------ 公共

    # ------------------------------------------------------------------ 撤销

    def _undo(self):
        """删除可撤销（目录移回原位）；恢复可撤销（工作区指针回退）；其余不可撤销。"""
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
            self._sync_current()
            self._render_tasks()
            self._refresh_active()
            self._toast("已撤销删除，该条历史已恢复")
        elif last["type"] == "restore":
            prev_point = ""
            if self._runs_root is not None:
                after = snapshot.undo_restore(self._runs_root)
                prev_point = str((after or {}).get("point_name") or "")
            self._last_restore = {}
            self._sync_current()
            self._render_tasks()
            self._refresh_active()
            tail = f"（回到「{prev_point}」）" if prev_point else ""
            self._toast(f"已撤销恢复，回到恢复前状态{tail}")

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
        self._toast_timer.start(6000 if with_undo else 5200)

    def _hide_status(self):
        """提示条到点自动收起（不改动任何数据）。"""
        self.status_box.setVisible(False)
