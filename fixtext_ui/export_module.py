"""
FixText V1 · 导出结果模块（M2-T2.7）
=====================================

把「导出结果」入口从占位页接成真功能：版式沿用 v4 的导出页壳（目标卡片 /
等级卡片 / 目录选择 / 报告卡），但逻辑全部换成真实链路——正文来自 M1 校正
产物或导入原文，EPUB 走 restore 引擎还原，每次导出自动附替换统计。

页面上只有四件事：
1. 选导出目标（纯文本 / 还原成电子书）；
2. 修正书名与作者（导入时自动提取过，这里可以改）；
3. 选导出目录；
4. 一键导出，然后看结果。

替换统计只落文件、不做界面呈现（排期 V1.1），所以结果卡只给文件名和路径。
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from fixtext_export import ExportOutcome, ExportSource, export_book, resolve_source
from fixtext_paths import default_export_dir
from fixtext_tokens import FONT_WEIGHT, c, fs
from fixtext_widgets import (
    Card, ConfirmDialog, Pill, RadioCard, EmptyState, hline, page_head_shell,
    enable_chrome, repolish,
)

try:
    import fixtext_error_center as error_center
except Exception:                                    # pragma: no cover
    error_center = None


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
# 后台执行
# ---------------------------------------------------------------------------

class ExportWorker(QObject):
    """在后台线程跑一次导出，用信号把结果送回界面线程。"""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            result = self._fn()
        except Exception as exc:
            # 没预期到的异常：归类 → 写诊断日志 → 人话错误卡（跨线程自动投递）。
            if error_center is not None:
                try:
                    error_center.report(exc, context="export")
                except Exception:
                    pass
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)


# ---------------------------------------------------------------------------
# 模块
# ---------------------------------------------------------------------------

class ExportModule(QWidget):

    #: 导出成功且导出状态已落盘（书的导出记录 + 运行摘要）后发出——
    #: 主窗口据此刷新书架「已导出」标识与历史条目状态（M4-EX.3b）。
    exportRecorded = Signal()
    #: 「查看替换报告」→ 打开替换报告页（载荷：替换统计文件路径）
    reportRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source: ExportSource | None = None
        self.outcome: ExportOutcome | None = None
        self.record: dict | None = None
        self.run: dict | None = None
        self.pipeline_root: str = ""
        self.target = "epub"
        # 记录「目标被强制成纯文本」的原因：还没有可还原的电子书来源。
        # 书源就绪后据此恢复默认的电子书导出；用户手动选过则不再自动改回。
        self._forced_txt = False
        self._default_out_dir = ""
        #: 元信息绑定的正文路径；换书 / 无书时重填，避免初始化后残留上一本书名
        self._meta_bound_path: str = ""
        self._running = False
        self._worker: ExportWorker | None = None
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_status)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        root.addWidget(self._header())

        # 无书空状态（原型 v3 §4）：还没有可导出的书时整页内容区换成
        # 这条引导；由真实状态触发（source 是否就绪）。
        self.empty_state = EmptyState(
            "📤", "还没有可导出的书",
            "请先导入并完成校正，才能导出干净文件。"
            "当前页面在有书状态下展示；无书时仅显示此引导。")
        root.addWidget(self.empty_state)

        # 常规内容区：有书才显示
        # M5-EX.4.1 / SYNC-1：主操作置顶 → 结果紧随 → 选项下沉（§9）
        self._content_w = QWidget()
        cl = QVBoxLayout(self._content_w)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(16)
        self._w_book = self._book_bar()
        self._w_actions = self._actions()
        self._w_result = self._result_card()
        self._w_target = self._target_card()
        self._w_meta = self._meta_card()
        self._w_dir = self._dir_card()
        self._w_status = self._status_card()
        cl.addWidget(self._w_book)
        cl.addWidget(self._w_actions)
        cl.addWidget(self._w_result)
        cl.addWidget(self._w_target)
        cl.addWidget(self._w_meta)
        cl.addWidget(self._w_dir)
        cl.addWidget(self._w_status)
        cl.addStretch(1)
        root.addWidget(self._content_w)

        self.refresh()

    # ------------------------------------------------------------------ 头部

    def _header(self) -> QWidget:
        shell, body = page_head_shell()
        hl = QHBoxLayout(body)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        col = QVBoxLayout()
        col.setSpacing(2)
        title = _label("导出结果", size="xl", color="neutral.900", weight="bold")
        title.setObjectName("PageTitle")
        sub = _label(
            "把校对好的书导出成可以直接用的文件：正文 + 两份替换统计（文本 / 表格）。",
            size="sm", color="neutral.600", wrap=True)
        sub.setObjectName("PageSub")
        col.addWidget(title)
        col.addWidget(sub)
        hl.addLayout(col, 1)
        return shell

    # -------------------------------------------------------------- 书源状态条

    def _book_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("BookBar")
        enable_chrome(bar)
        # 配色交给 fixtext.qss 的 QFrame#BookBar（原内联收归）

        hl = QHBoxLayout(bar)
        hl.setContentsMargins(18, 14, 18, 14)
        hl.setSpacing(14)

        ico = QLabel("📖")
        ico.setObjectName("BookBarIco")
        ico.setFixedSize(40, 40)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 图标方块配色交给 fixtext.qss 的 #BookBarIco（原内联收归）
        hl.addWidget(ico)

        col = QVBoxLayout()
        col.setSpacing(2)
        self.book_name_label = _label("尚未导入书籍", size="md", weight="bold")
        self.book_meta_label = _label(
            "先在「导入」页选择一本书，再回到这里导出", size="xs", color="neutral.500")
        col.addWidget(self.book_name_label)
        col.addWidget(self.book_meta_label)
        hl.addLayout(col, 1)

        self.book_pill = Pill("等待导入", "neutral")
        hl.addWidget(self.book_pill)
        return bar

    # ---------------------------------------------------------------- 目标卡片

    def _target_card(self) -> Card:
        card = Card("导出目标", "选一种就够，两种都会附上替换统计",
                    basis="§2.2 入口⑤ · 导出目标")
        card.body_l.addWidget(self._target_desc())
        card.body_l.addSpacing(12)

        self.txt_radio = RadioCard(
            "纯文本", "去掉内部标记的干净正文，用任何文本阅读器都能直接看", "txt")
        self.txt_radio.chosen.connect(self.set_target)
        card.body_l.addWidget(self.txt_radio)

        card.body_l.addSpacing(10)
        self.epub_radio = RadioCard(
            "还原成电子书", "用原书当模板还原，章节顺序与原书完全一致", "epub")
        self.epub_radio.chosen.connect(self.set_target)
        card.body_l.addWidget(self.epub_radio)
        return card

    def _target_desc(self) -> QLabel:
        self.target_hint = _label("", size="xs", color="neutral.500", wrap=True)
        return self.target_hint

    # ------------------------------------------------------------ 元信息卡片

    def _meta_card(self) -> Card:
        card = Card("书籍信息", "导入时自动提取过，这里可以改；导出以这里的值为准",
                    basis="§2.7.5 第 12 项 · 书名 / 作者可修正")

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 4, 0, 4)
        row1.addWidget(_label("书名", size="sm", weight="bold"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("这本书的名字")
        self.title_edit.textChanged.connect(lambda _v: self._sync_meta())
        row1.addWidget(self.title_edit, 1)
        card.body_l.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 4, 0, 4)
        row2.addWidget(_label("作者", size="sm", weight="bold"))
        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText("这本书的作者")
        self.author_edit.textChanged.connect(lambda _v: self._sync_meta())
        row2.addWidget(self.author_edit, 1)
        card.body_l.addLayout(row2)

        card.body_l.addSpacing(8)
        self.meta_hint = _label("", size="xs", color="neutral.500", wrap=True)
        card.body_l.addWidget(self.meta_hint)
        return card

    # -------------------------------------------------------------- 目录卡片

    def _dir_card(self) -> Card:
        card = Card("导出位置", "正文和两份统计都会放在这个目录里",
                    basis="§2.2 入口⑤ · 目标目录选择")

        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 4)
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("选择一个文件夹")
        self.dir_edit.textChanged.connect(lambda _v: self.refresh())
        row.addWidget(self.dir_edit, 1)

        pick = QPushButton("浏览…")
        pick.setObjectName("BtnOutline")
        pick.setCursor(Qt.CursorShape.PointingHandCursor)
        pick.clicked.connect(self._pick_dir)
        row.addWidget(pick)
        card.body_l.addLayout(row)

        card.body_l.addSpacing(8)
        self.dir_hint = _label("", size="xs", color="neutral.500", wrap=True)
        card.body_l.addWidget(self.dir_hint)
        return card

    # -------------------------------------------------------------- 状态卡片

    def _status_card(self) -> Card:
        card = Card("导出前检查")
        self.status_label = _label("", size="sm", color="neutral.600", wrap=True)
        card.body_l.addWidget(self.status_label)
        return card

    # ------------------------------------------------------------------ 动作

    def _actions(self) -> QFrame:
        # M5-EX.7 §10 Step4：导出主操作横幅，与校正 .hero / 检查 .chk-top 同规
        hero = QFrame()
        hero.setObjectName("Hero")
        enable_chrome(hero)
        # 渐变横幅交给 fixtext.qss 的 #Hero（原内联收归）
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(28, 26, 28, 26)
        hl.setSpacing(24)

        col = QVBoxLayout()
        col.setSpacing(6)
        h2 = QLabel("导出干净文件")
        h2.setProperty("role", "title")
        p = QLabel("导出干净文件 → 自动附替换报告 → 内部同步基准（保证下轮统计不重复）。")
        p.setWordWrap(True)
        col.addWidget(h2)
        col.addWidget(p)
        self.toast_label = QLabel("")
        self.toast_label.setWordWrap(True)
        self.toast_label.setProperty("role", "hint")
        col.addWidget(self.toast_label)
        hl.addLayout(col, 1)

        self.export_btn = QPushButton("📤 开始导出")
        self.export_btn.setObjectName("HeroBtn")
        self.export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_btn.setMinimumHeight(50)
        # 大按钮配色交给 fixtext.qss 的 #HeroBtn（原内联收归）
        self.export_btn.clicked.connect(self.export_now)
        hl.addWidget(self.export_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return hero

    # ---------------------------------------------------------------- 结果卡

    def _result_card(self) -> Card:
        card = Card("导出结果")
        self.result_box = QVBoxLayout()
        self.result_box.setContentsMargins(0, 0, 0, 0)
        self.result_box.setSpacing(6)
        self.result_placeholder = _label(
            "还没有导出过。选好目标和目录，点「开始导出」。",
            size="sm", color="neutral.500", wrap=True)
        self.result_box.addWidget(self.result_placeholder)
        card.body_l.addLayout(self.result_box)
        self.result_card = card
        return card

    # -------------------------------------------------------------- 外部接线

    def set_context(self, record: dict | None, run: dict | None = None,
                    pipeline_root: str = "") -> None:
        """由主窗口注入「当前书 + 最近一次校正」的真实信息。"""
        self.record = dict(record) if record else None
        self.run = dict(run) if run else None
        if pipeline_root:
            self.pipeline_root = pipeline_root
        self.source = resolve_source(self.record, self.run, self.pipeline_root)
        self.refresh()

    def set_source(self, source: ExportSource) -> None:
        """直接给一个导出源（测试与外部接线用）。"""
        self.source = source
        self.refresh()

    def set_target(self, fmt: str) -> None:
        # 用户手动选择：解除「因为没有电子书来源而强制纯文本」的标记
        self._forced_txt = False
        self.target = fmt
        self.refresh()

    def set_out_dir(self, path: str) -> None:
        self.dir_edit.setText(str(path))

    def set_meta(self, title: str, author: str = "") -> None:
        self.title_edit.setText(title or "")
        self.author_edit.setText(author or "")

    # ------------------------------------------------------------------ 刷新

    def refresh(self) -> None:
        src = self.source
        has_book = bool(src and src.text_path and Path(src.text_path).exists())

        # 无书空状态 / 常规内容区切换（真实状态触发）
        self._content_w.setVisible(has_book)
        self.empty_state.setVisible(not has_book)

        # 书源条
        if has_book:
            title = src.title or "未命名"
            self.book_name_label.setText(f"《{title}》")
            if src.source_kind == "epub":
                kind = "电子书"
            else:
                kind = "文本"
            if src.corrected:
                state = "已完成校正"
            else:
                state = "尚未校正"
            self.book_meta_label.setText(f"{kind} · {state}")
            self.book_pill.setText("可导出" if has_book else "等待导入")
            # 语义色 / 胶囊圆角交给 fixtext.qss 的 #Pill[kind="ok"]（原内联收归）
            self.book_pill.setProperty("kind", "ok")
            repolish(self.book_pill)
        else:
            self.book_name_label.setText("尚未导入书籍")
            self.book_meta_label.setText(
                "先在「导入」页选择一本书，再回到这里导出")
            self.book_pill.setText("等待导入")
            self.book_pill.setProperty("kind", "neutral")
            repolish(self.book_pill)

        # 目标：只有电子书来源才能还原
        can_epub = bool(has_book and src.can_restore_epub)
        if can_epub:
            if self._forced_txt:
                # 之前因为还没有书源而被强制成纯文本，现在恢复默认的电子书导出
                self.target = "epub"
                self._forced_txt = False
        else:
            self.target = "txt"
            self._forced_txt = True
        self.epub_radio.setEnabled(can_epub)
        self.epub_radio.set_selected(can_epub and self.target == "epub")
        self.txt_radio.set_selected(not (can_epub and self.target == "epub"))
        if can_epub:
            self.target_hint.setText(
                "这本书是从电子书导入的，可以还原成电子书，也可以导出纯文本。")
        else:
            self.target_hint.setText(
                "这本书不是从电子书导入的，导出为纯文本。")

        # 元信息：按「当前书」绑定。换书或清空时重填，避免初始化 / 向导换书后
        # 仍拿着上一本的书名去导出（M5-EX.6）。同一本书上不覆盖用户已改的值。
        if has_book:
            bound = str(Path(src.text_path).resolve()) if src.text_path else ""
            if bound != self._meta_bound_path:
                self._meta_bound_path = bound
                self.title_edit.setText(src.title or "")
                self.author_edit.setText(src.author or "")
            else:
                if not self.title_edit.text():
                    self.title_edit.setText(src.title or "")
                if not self.author_edit.text() and src.author:
                    self.author_edit.setText(src.author)
            if src.author:
                self.meta_hint.setText(
                    f"导入时从书里读到作者「{src.author}」，改了以后导出用你填的值。")
            else:
                self.meta_hint.setText(
                    "这本书的元信息里没有作者，可以自己补一个；导出时会写进文件。")
        else:
            self._meta_bound_path = ""
            self.title_edit.clear()
            self.author_edit.clear()
            self.meta_hint.setText("导入一本书后，这里会自动填上书名与作者。")

        # 目录：默认包根下「导出/」（M5-EX.2 / BUG-3）；用户自选仍优先。
        # 默认路径不写进输入框（零露出口径），只有用户自己选的才显示。
        if has_book:
            self._default_out_dir = str(default_export_dir())
        else:
            self._default_out_dir = ""

        # 导出前检查
        self._refresh_status(has_book, src)

    def _refresh_status(self, has_book: bool, src: ExportSource | None) -> None:
        lines: list[str] = []
        if not has_book or src is None:
            lines.append("· 还没有可导出的书，请先在「导入」页选一本书。")
            self.status_label.setText("\n".join(lines))
            self.export_btn.setEnabled(False)
            self.dir_hint.setText("选好目录后就能导出。")
            return

        if src.corrected:
            lines.append("· 这本书已经跑过校正，导出的是校正后的正文。")
        else:
            lines.append("· 这本书还没有跑过校正，导出的是导入时的原文（替换命中数为 0）。")
        if src.can_restore_epub:
            lines.append("· 可以还原成电子书：章节顺序与原书保持一致。")
        else:
            lines.append("· 只能导出纯文本。")
        self.status_label.setText("\n".join(lines))

        out_dir = self._resolve_out_dir()
        if self.dir_edit.text().strip():
            # 用户自己选的目录：只显示文件夹名，不透出绝对路径（零露出口径）
            self.dir_hint.setText(f"会导出到文件夹「{Path(out_dir).name}」")
        elif out_dir:
            self.dir_hint.setText(
                "没有另选目录时，默认导出到程序目录下的「导出」文件夹。")
        else:
            self.dir_hint.setText("选好目录后就能导出。")
        self.export_btn.setEnabled(True)

    def _resolve_out_dir(self) -> str:
        """导出目录：优先用户选的，否则包根「导出/」。"""
        return self.dir_edit.text().strip() or self._default_out_dir

    # ------------------------------------------------------------------ 导出

    def _export_targets(self, out_dir: str, fmt: str, title: str) -> list[Path]:
        """这次导出会落到磁盘上的文件（与 fixtext_export 的命名口径一致）。"""
        import fixtext_export as fx

        safe = fx._safe_name(title or "书籍")
        ext = "epub" if fmt == "epub" else "txt"
        return [Path(out_dir) / f"{safe}.{ext}",
                Path(out_dir) / f"{safe}替换统计.txt",
                Path(out_dir) / f"{safe}替换统计.csv"]

    def _confirm_overwrite(self, targets: list[Path]) -> bool:
        """目标文件已存在时要二次确认（M4-T4.4：覆盖导出不是静默动作）。"""
        existing = [p for p in targets if p.exists()]
        if not existing:
            return True
        names = "；".join(p.name for p in existing)
        dlg = ConfirmDialog(
            icon="⚠",
            title="导出目录里已有同名文件，要覆盖吗？",
            note=f"下列文件已经存在，继续导出会用新内容覆盖它们：{names}。"
                 f"覆盖后旧内容不可恢复；原书与你导入的文件不受影响。",
            note_kind="warn",
            confirm_text="覆盖导出",
            confirm_kind="danger",
            parent=self,
        )
        return dlg.exec() == QDialog.DialogCode.Accepted

    # ---- 向导之外的只读入口（M4-EX.2c） -------------------------------
    def is_busy(self) -> bool:
        return bool(self._running)

    def export_now(self) -> None:
        if self._running:
            return
        src = self.source
        if src is None or not src.text_path or not Path(src.text_path).exists():
            self._toast("请先在「导入」页选一本书")
            return
        out_dir = self._resolve_out_dir()
        if not out_dir:
            self._toast("请先选择导出目录")
            return
        fmt = self.target if (self.target == "epub" and src.can_restore_epub) else "txt"
        title = self.title_edit.text().strip() or src.title
        author = self.author_edit.text().strip()

        if not self._confirm_overwrite(self._export_targets(out_dir, fmt, title)):
            self._toast("已取消，没有覆盖任何文件")
            return

        self._running = True
        self.export_btn.setEnabled(False)
        self.status_label.setText("· 正在导出，请稍等…")

        worker = ExportWorker(
            lambda: export_book(src, out_dir, fmt=fmt, title=title, author=author))
        worker.succeeded.connect(self._on_succeeded)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        worker.start()

    def _on_succeeded(self, outcome: ExportOutcome) -> None:
        self._running = False
        self.outcome = outcome
        self.export_btn.setEnabled(True)
        self._render_result(outcome)
        self._record_export(outcome)
        self.refresh()
        self._toast(outcome.message)

    def _record_export(self, outcome: ExportOutcome) -> None:
        """导出成功的事实落盘（M4-EX.3b）：这本书的导出记录 + 那次运行的状态。

        书架「已导出」标识由书目录里的真实记录驱动，历史条目的导出状态由
        运行摘要驱动——这里就是导出页这条路的写入方（历史页的重新导出有
        自己的写点）。记录写不进去不影响导出结果本身，只不亮标识。
        """
        import time

        import fixtext_history as histdata
        import fixtext_shelf as shelf

        recorded = False
        if self.record:
            text_path = str(self.record.get("text_path") or "")
            book_dir = Path(text_path).resolve().parent if text_path else Path()
            if book_dir.name and (book_dir / shelf.IMPORT_RECORD).exists():
                shelf.write_export_record(
                    book_dir, fmt=outcome.fmt, path=outcome.main_file,
                    sha256=outcome.sha256, hits=outcome.hits)
                recorded = True
        run_dir = str((self.run or {}).get("workdir") or "")
        if run_dir and Path(run_dir).is_dir():
            histdata.write_run_meta(
                run_dir,
                exported_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                exported_sha256=str(outcome.sha256 or ""))
            recorded = True
        if recorded:
            self.exportRecorded.emit()

    def _on_failed(self, message: str) -> None:
        self._running = False
        self.export_btn.setEnabled(True)
        self.refresh()
        self._toast("这次导出没能完成，请看一下上面的提示")

    # ------------------------------------------------------------------ 结果

    def _render_result(self, outcome: ExportOutcome) -> None:
        while self.result_box.count():
            item = self.result_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        def add(text: str, *, size: str = "sm", color: str = "neutral.700",
                bold: bool = False) -> None:
            self.result_box.addWidget(_label(
                text, size=size, color=color,
                weight="bold" if bold else None, wrap=True))

        add("已导出", size="md", color="neutral.900", bold=True)
        add(f"正文文件：{Path(outcome.main_file).name}", color="neutral.800")
        add(f"替换统计（文本）：{Path(outcome.stats_text).name}")
        add(f"替换统计（表格）：{Path(outcome.stats_csv).name}")
        add(f"替换命中数：{outcome.hits}", color="neutral.800")
        add(f"涉及词库：{'；'.join(outcome.libs) if outcome.libs else '无'}")

        open_btn = QPushButton("📂 打开所在文件夹")
        open_btn.setObjectName("BtnOutline")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        folder = str(Path(outcome.main_file).resolve().parent)
        open_btn.clicked.connect(lambda _=False, p=folder: self._open_folder(p))
        self.result_box.addWidget(open_btn)

        # 「查看替换报告」→ 替换报告页（V1.1-E9）：直接带上这次导出附带的
        # 替换统计文件，报告页原样呈现，缺字段写明缺，不补数。
        stats_path = str(outcome.stats_csv or outcome.stats_text or "")
        if stats_path and Path(stats_path).exists():
            report_btn = QPushButton("📄 查看替换报告")
            report_btn.setObjectName("BtnOutline")
            report_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            report_btn.clicked.connect(
                lambda _=False, q=stats_path: self.reportRequested.emit(q))
            self.result_box.addWidget(report_btn)

        if outcome.fmt == "epub" and outcome.structure:
            st = outcome.structure
            add(f"电子书结构校验：{'通过' if st.get('ok') else '未通过'}", color="neutral.800")
            add(f"章节数：{st.get('spine_items')}（与原书一致："
                f"{'是' if st.get('spine_order_equal') else '否'}）")
            if outcome.sha_match is True:
                add("与引擎基线还原成品逐字节一致。", color="success")
            elif outcome.sha_match is False:
                add("校验值与引擎基线不同（本次修正过书名或作者，内容未变）。",
                    color="neutral.600")
        for note in outcome.notes:
            add(note, size="xs", color="neutral.500")

    # ------------------------------------------------------------------ 杂项

    def _pick_dir(self) -> None:
        current = (self.dir_edit.text().strip()
                   or self._default_out_dir
                   or str(default_export_dir()))
        path = QFileDialog.getExistingDirectory(self, "选择导出目录", current)
        if path:
            self.dir_edit.setText(path)

    @staticmethod
    def _open_folder(path: str) -> None:
        """在系统文件管理器中打开导出目录。"""
        p = Path(path)
        if not p.is_dir():
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.resolve())))

    def _sync_meta(self) -> None:
        self.refresh()

    def _toast(self, msg: str) -> None:
        self.toast_label.setText(msg)
        self._toast_timer.start(4000)

    def _hide_status(self) -> None:
        self.toast_label.setText("")
