"""FixText V1 · 导入书籍模块（T2.2 · M5-EX.3 去向导）

界面结构（无分步向导；M5-EX.4.1 布局）：

    拖放区 / 选择文件（全局拖放也落在这里）
      → 导入中 / 完成（进度 + 结果）
      → 工作区书架（无书时弱提示，无独立空状态）
      → 导入安全说明（参考区置底）

设计约束（逐条对应验收）：

- 验收① 双通道：拖放与「选择文件」都走 ``_take_file()``。
- 验收② 零配置编码识别：用户不做任何选择；提示语来自 ``messages``。
- 验收③ 无概念暴露：界面不出现 spine / OPF 等词。
- 验收④ 原文件不被改：后台 ``import_book`` 先复制再处理，记录双哈希。
- M5-EX.3：EPUB 一律可逆合并；导出页再选 TXT / 还原 EPUB。无「处理方式」
  /「章节预览」步骤。

取消在阶段边界生效；取消后清半成品。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from fixtext_tokens import FONT_MONO, c, fs, px, r, sp
from fixtext_widgets import Card, Pill, enable_chrome, hline, page_head_shell, PrimaryButton

import fixtext_import as fi
import fixtext_shelf as shelf_data
from fixtext_shelf_ui import ShelfPanel

try:
    import fixtext_error_center as error_center
except Exception:                                    # pragma: no cover
    error_center = None


# ---------------------------------------------------------------------------
# 后台导入线程
# ---------------------------------------------------------------------------

class ImportWorker(QObject):
    """在后台线程执行导入；进度按阶段回报，取消在阶段边界生效。"""

    progress = Signal(str, int)
    finished = Signal(object)          # ImportResult
    failed = Signal(str, str)          # (人话消息, 细节)

    def __init__(self, path: str, workspace: Path, options):
        super().__init__()
        self._path = path
        self._workspace = workspace
        self._options = options
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _tick(self, step: str, pct: int) -> None:
        if self._cancelled:
            raise _Cancelled()
        self.progress.emit(step, pct)

    @Slot()
    def run(self) -> None:
        try:
            result = fi.import_book(
                self._path, self._workspace, self._options, progress=self._tick
            )
            self.finished.emit(result)
        except _Cancelled:
            self._cleanup_partial()
            self.failed.emit("已取消导入。工作区里没有留下任何未完成的文件。", "cancelled")
        except fi.EpubImportError as exc:
            self._cleanup_partial()
            self.failed.emit(str(exc), "epub")
        except fi.ImportError_ as exc:
            self._cleanup_partial()
            self.failed.emit(str(exc), "import")
        except Exception as exc:          # 兜底：人话，不把堆栈丢给用户
            self._cleanup_partial()
            if error_center is not None:
                try:
                    error_center.report(exc, context="import")
                except Exception:
                    pass
            self.failed.emit(
                "这次导入没能完成。你的原文件没有被改动，可以重新导入一次。",
                f"{type(exc).__name__}: {exc}",
            )

    def _cleanup_partial(self) -> None:
        """取消 / 失败时清掉本次可能产生的半成品目录。"""
        try:
            for d in self._workspace.glob("_preview"):
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


class _Cancelled(Exception):
    pass


# ---------------------------------------------------------------------------
# 小部件
# ---------------------------------------------------------------------------

class DropZone(QFrame):
    """拖放区：拖入时高亮；点击任意处等同「选择文件」。"""

    fileDropped = Signal(str)
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        enable_chrome(self)  # 虚线外框圆角（对齐原型 .drop）
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(150)
        self._hot = False
        self._apply_style("normal")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("📥")
        icon.setFont(QFont("", 30))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(icon)

        self.title = QLabel("把书拖到这里，或点击选择文件")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet(
            f"color:{c('neutral.800')};font-size:{fs('md')};font-weight:600"
        )
        lay.addWidget(self.title)

        self.sub = QLabel("支持 TXT / EPUB · 导入后自动复制到工作区，原文件不会改动")
        self.sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('xs')}")
        lay.addWidget(self.sub)

    def _apply_style(self, state: str) -> None:
        border = c("primary.500") if state == "hot" else c("neutral.300")
        bg = c("primary.50") if state == "hot" else c("neutral.0")
        self.setStyleSheet(
            f"#DropZone{{background:{bg};border:2px dashed {border};"
            f"border-radius:{r('lg')}}}"
            "#DropZone QLabel{border:none;background:transparent}"
        )

    def dragEnterEvent(self, event):
        if self._first_local_file(event.mimeData()):
            event.acceptProposedAction()
            self._hot = True
            self._apply_style("hot")
        else:
            event.ignore()

    def dragLeaveEvent(self, _event):
        self._hot = False
        self._apply_style("normal")

    def dropEvent(self, event):
        path = self._first_local_file(event.mimeData())
        self._hot = False
        self._apply_style("normal")
        if path:
            event.acceptProposedAction()
            self.fileDropped.emit(path)
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    @staticmethod
    def _first_local_file(mime) -> str | None:
        if not mime.hasUrls():
            return None
        urls = [u for u in mime.urls() if u.isLocalFile()]
        if not urls:
            return None
        return urls[0].toLocalFile()


class ResultPane(QWidget):
    """导入完成：人话提示 + 关键事实 + 可展开的技术核对。"""

    def __init__(self, on_open_folder=None, parent=None):
        super().__init__(parent)
        self._on_open_folder = on_open_folder
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(int(sp("3").replace("px", "")))

        head = QHBoxLayout()
        self.title = QLabel("导入完成")
        self.title.setWordWrap(True)
        self.title.setStyleSheet(
            f"color:{c('neutral.900')};font-size:{fs('lg')};font-weight:700"
        )
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(Pill("已完成", "ok"))
        lay.addLayout(head)

        self.facts = QLabel("")
        self.facts.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('sm')}")
        lay.addWidget(self.facts)

        lay.addWidget(hline("neutral.100"))
        self.notes_box = QVBoxLayout()
        self.notes_box.setSpacing(4)
        lay.addLayout(self.notes_box)

        self.detail_toggle = QPushButton("查看导入记录（技术核对）")
        self.detail_toggle.setObjectName("BtnGhost")
        self.detail_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.detail_toggle.setCheckable(True)
        self.detail_toggle.clicked.connect(self._toggle_detail)
        lay.addWidget(self.detail_toggle)

        self.detail = QLabel("")
        self.detail.setVisible(False)
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail.setStyleSheet(
            f"color:{c('neutral.600')};background:{c('neutral.50')};"
            f"border-radius:{r('md')};padding:{sp('3')};font-family:{FONT_MONO};"
            f"font-size:{fs('xs')}"
        )
        lay.addWidget(self.detail)

        foot = QHBoxLayout()
        foot.addStretch(1)
        if on_open_folder:
            self.open_btn = QPushButton("打开工作区")
            self.open_btn.setObjectName("BtnOutline")
            self.open_btn.clicked.connect(on_open_folder)
            foot.addWidget(self.open_btn)
        lay.addLayout(foot)

    def _toggle_detail(self) -> None:
        self.detail.setVisible(self.detail_toggle.isChecked())

    def load(self, result) -> None:
        self.title.setText(result.title)
        unit = "章" if result.chapters > 1 else "篇"
        self.facts.setText(
            f"共 {result.chapters} {unit} · 正文约 {result.text_chars:,} 字 · "
            f"导入耗时 {result.elapsed_ms / 1000:.1f} 秒"
        )
        while self.notes_box.count():
            item = self.notes_box.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for note in result.human_notes:
            row = QHBoxLayout()
            dot = QLabel("·")
            dot.setStyleSheet(f"color:{c('primary.500')};font-weight:700")
            lab = QLabel(note)
            lab.setWordWrap(True)
            lab.setStyleSheet(f"color:{c('neutral.700')};font-size:{fs('sm')}")
            row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(lab, 1)
            box = QWidget()
            box.setLayout(row)
            self.notes_box.addWidget(box)

        same = "一致" if result.source_sha256_before == result.source_sha256_after else "不一致"
        mode_label = (
            "可逆合并（可还原 EPUB）" if result.epub_mode == "direct" else "纯文本"
        )
        self.detail.setText(
            "原文件导入前哈希  " + result.source_sha256_before + "\n"
            "原文件导入后哈希  " + result.source_sha256_after + "\n"
            "工作区副本哈希    " + result.workspace_copy_sha256 + "\n"
            f"对照结论：{'一致（原文件未被修改）' if same == '一致' else '不一致，请保留此记录反馈'}\n"
            f"识别结果：{result.encoding_label}（{result.encoding_confidence}）· "
            f"换行 {result.newline_kind} · 无法解释的字节 {result.replaced_chars}\n"
            f"导入方式：{mode_label}"
            f" · 复用已有副本：{'是' if result.reused else '否'}\n"
            f"工作区子目录：{Path(result.workspace_dir).name}"
        )


# ---------------------------------------------------------------------------
# 主模块
# ---------------------------------------------------------------------------

class ImportModule(QWidget):
    """「导入书籍」模块页（M5-EX.3：无导入向导）。"""

    bookReady = Signal(str)      # 导入完成 → book.txt 绝对路径
    currentBookChanged = Signal(str)

    #: 状态：idle / running / done（给首启与自检用）
    STATE_IDLE = 0
    STATE_RUNNING = 3
    STATE_DONE = 4

    def __init__(self, workspace_root: str | Path | None = None, parent=None):
        super().__init__(parent)
        self.workspace = Path(workspace_root or default_workspace())
        self.workspace.mkdir(parents=True, exist_ok=True)

        self._path: str | None = None
        self._kind: str | None = None
        self._result = None
        self._thread: QThread | None = None
        self._worker: ImportWorker | None = None
        self._step = self.STATE_IDLE
        self._fail_text = ""

        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(int(sp("4").replace("px", "")))

        head, body = page_head_shell()
        hl = QVBoxLayout(body)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)
        t = QLabel("导入书籍")
        t.setObjectName("PageTitle")
        hl.addWidget(t)
        sub = QLabel(
            "把 TXT 或 EPUB 拖进窗口即可开始。书会被复制到工作区处理，"
            "你电脑里原来的文件不会被改动。"
        )
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        hl.addWidget(sub)
        root.addWidget(head)

        self.notice = QLabel("")
        self.notice.setObjectName("NoticeBar")
        self.notice.setWordWrap(True)
        self.notice.setVisible(False)
        root.addWidget(self.notice)

        self.drop_card = Card("从文件导入", "拖放或选择，两条路都一样")
        self.drop_zone = DropZone()
        self.drop_zone.fileDropped.connect(self._take_file)
        self.drop_zone.clicked.connect(self._choose_file)
        self.drop_card.body_l.addWidget(self.drop_zone)

        row = QHBoxLayout()
        row.addStretch(1)
        self.browse_btn = PrimaryButton("选择文件…")
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_btn.clicked.connect(self._choose_file)
        row.addWidget(self.browse_btn)
        self.drop_card.body_l.addSpacing(12)
        self.drop_card.body_l.addLayout(row)
        root.addWidget(self.drop_card)

        # ---- 导入进度 / 结果（无向导步骤）----
        self.status_card = Card("本次导入", "")
        self.progress_pane = QWidget()
        gl = QVBoxLayout(self.progress_pane)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(10)
        self.file_label = QLabel("")
        self.file_label.setWordWrap(True)
        self.file_label.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('xs')}")
        gl.addWidget(self.file_label)
        self.step_label = QLabel("准备中…")
        self.step_label.setStyleSheet(f"color:{c('neutral.800')};font-size:{fs('sm')}")
        gl.addWidget(self.step_label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        gl.addWidget(self.bar)
        crow = QHBoxLayout()
        crow.addStretch(1)
        self.cancel_btn = QPushButton("取消导入")
        self.cancel_btn.setObjectName("BtnOutline")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._cancel)
        crow.addWidget(self.cancel_btn)
        gl.addLayout(crow)

        self.result_pane = ResultPane(on_open_folder=self._open_workspace)
        self.status_card.body_l.addWidget(self.progress_pane)
        self.status_card.body_l.addWidget(self.result_pane)
        self.progress_pane.setVisible(False)
        self.result_pane.setVisible(False)
        self.status_card.setVisible(False)
        root.addWidget(self.status_card)

        # M5-EX.4.1 / SYNC-3：无独立 EmptyState；无书时书架卡仍显示弱提示
        self.workspace_card = Card("工作区书架", "")
        self.workspace_label = QLabel("")
        self.workspace_label.setWordWrap(True)
        self.workspace_label.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('sm')}")
        self.workspace_card.body_l.addWidget(self.workspace_label)
        self.workspace_card.body_l.addSpacing(px(sp("3")))
        self.shelf = ShelfPanel(self.workspace)
        self.shelf.currentChanged.connect(self._on_shelf_current_changed)
        self.workspace_card.body_l.addWidget(self.shelf)
        self.workspace_card.body_l.addSpacing(px(sp("3")))
        wrow = QHBoxLayout()
        wrow.addStretch(1)
        open_ws = QPushButton("打开工作区")
        open_ws.setObjectName("BtnOutline")
        open_ws.clicked.connect(self._open_workspace)
        wrow.addWidget(open_ws)
        self.workspace_card.body_l.addLayout(wrow)
        root.addWidget(self.workspace_card)

        # M5-EX.4.1 / SYNC-2：安全说明置底参考区（书架之后）
        self.safety_card = Card(
            "导入安全说明", "你原来的文件不会被改动",
            collapsible=True, open_=False)
        body = QLabel(
            "· 书会被复制一份到 FixTextGUI 的工作区，所有处理都在这份副本上做，"
            "你原来的文件始终原样保留。\n"
            "· 导入前后会各记一次文件指纹，用来确认原文件一个字节都没变。\n"
            "· 书里的字符格式差异会自动处理，不需要你做任何选择；"
            "处理完成后会用一句普通话告诉你做了什么。\n"
            "· 电子书按可还原方式导入，导出页再选择 TXT 或还原为 EPUB。"
        )
        body.setWordWrap(True)
        body.setStyleSheet(f"color:{c('neutral.700')};font-size:{fs('sm')}")
        self.safety_card.body_l.addWidget(body)
        root.addWidget(self.safety_card)

        root.addStretch(1)
        self._refresh_workspace()

    # ---- 选文件 --------------------------------------------------------
    def _show_notice(self, text: str, kind: str = "warn") -> None:
        palette = {
            "warn": ("warning.bg", "warning", "neutral.200"),
            "info": ("primary.50", "primary.700", "primary.200"),
            "ok": ("success.bg", "success", "success.bg"),
        }
        bg, fg, border = palette.get(kind, palette["warn"])
        self.notice.setText(text)
        self.notice.setStyleSheet(
            f"background:{c(bg)};color:{c(fg)};border:1px solid {c(border)};"
            f"border-radius:{r('md')};padding:{sp('3')} {sp('3')};font-size:{fs('sm')}"
        )
        self.notice.setVisible(True)

    def _clear_notice(self) -> None:
        self.notice.setVisible(False)
        self.notice.setText("")

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择要导入的书", "", "书籍文件 (*.txt *.epub)"
        )
        if path:
            self._take_file(path)

    def _take_file(self, path: str) -> None:
        """拖放与选择文件两条通道的唯一汇合点；选完即开始导入。"""
        try:
            kind = fi.detect_kind(path)
        except fi.ImportError_ as exc:
            self._show_notice(str(exc))
            return
        except OSError:
            self._show_notice("找不到这个文件，请重新选一次。")
            return

        if self._thread is not None:
            self._show_notice("上一本书还在导入，完成后再选下一本。", "info")
            return

        self._clear_notice()
        self._fail_text = ""
        self._path = path
        self._kind = kind
        self._result = None
        self._start_import()

    def _start_import(self) -> None:
        self._step = self.STATE_RUNNING
        self.status_card.setVisible(True)
        self.file_label.setText(Path(self._path).name if self._path else "")
        self.progress_pane.setVisible(True)
        self.result_pane.setVisible(False)
        self.step_label.setText("准备中…")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self._start_worker()

    def _start_worker(self) -> None:
        if self._thread is not None:
            return
        # M5-EX.3：固定可逆；importer 侧也会忽略非 direct
        options = fi.ImportOptions(epub_mode="direct")
        self._worker = ImportWorker(self._path, self.workspace, options)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()
        self.cancel_btn.setEnabled(True)

    @Slot(str, int)
    def _on_progress(self, step: str, pct: int) -> None:
        self.step_label.setText(step)
        if self.bar.maximum() == 0:
            self.bar.setRange(0, 100)
        self.bar.setValue(max(0, min(100, pct)))

    @Slot(object)
    def _on_finished(self, result) -> None:
        self._stop_thread()
        self._fail_text = ""
        self._result = result
        self.result_pane.load(result)
        self.progress_pane.setVisible(False)
        self.result_pane.setVisible(True)
        self.status_card.setVisible(True)
        self._step = self.STATE_DONE
        self._refresh_workspace()
        self.bookReady.emit(result.text_path)

    @Slot(str, str)
    def _on_failed(self, message: str, detail: str) -> None:
        self._stop_thread()
        self._step = self.STATE_IDLE
        self.progress_pane.setVisible(False)
        self.result_pane.setVisible(False)
        self.status_card.setVisible(False)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.step_label.setText("")
        self._fail_text = str(message or "")
        if detail == "cancelled":
            self._show_notice(message, "info")
        else:
            self._show_notice(
                message + " 你可以换一个文件再试，或者先确认这个文件能正常打开。"
            )

    def _stop_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
            self._thread = None
        self._worker = None
        self.cancel_btn.setEnabled(True)

    def _cancel(self) -> None:
        if self._worker is not None:
            self.cancel_btn.setEnabled(False)
            self.step_label.setText("正在取消…")
            self._worker.cancel()

    def _open_workspace(self) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(self.workspace))          # noqa: S606
            elif sys.platform == "darwin":
                os.system(f'open "{self.workspace}"')      # noqa: S605
            else:
                os.system(f'xdg-open "{self.workspace}"')  # noqa: S605
        except OSError:
            self._show_notice("打不开文件夹。工作区在程序目录下的 workspace 里。", "info")

    def _refresh_workspace(self) -> None:
        books = self.shelf.books()
        n_books, size = fi.workspace_usage(self.workspace)
        # 书架卡始终可见：无书时弱提示，有书时列清单（不再整页 EmptyState）
        self.workspace_card.setVisible(True)
        self.shelf.refresh(books)
        if n_books:
            self.workspace_label.setText(
                shelf_data.shelf_caption(n_books, size)
                + " 在列表里点「设为当前」，切换要校对的书。")
        else:
            self.workspace_label.setText(
                "工作区还是空的。用上面的拖放区或「选择文件」导入第一本，"
                "导入完成后会出现在这里。")

    def _on_shelf_current_changed(self, book_id: str) -> None:
        book = shelf_data.find_book(self.workspace, book_id)
        if book is None:
            return
        self.currentBookChanged.emit(book.text_path)

    def current_book(self):
        return self.shelf.current_book()

    # ---- 向导 / 自检程序化入口 -----------------------------------------
    def take_file(self, path: str) -> None:
        """与拖放 / 选择文件同一个汇合入口（选完即开跑）。"""
        self._take_file(path)

    def step(self) -> int:
        return int(self._step)

    def is_busy(self) -> bool:
        return self._thread is not None

    def has_finished(self) -> bool:
        return self._step == self.STATE_DONE and self._result is not None

    def next_enabled(self) -> bool:
        """兼容旧调用：无下一步按钮，恒为 False。"""
        return False

    def click_next(self) -> None:
        """兼容旧调用：无向导步骤，空操作（导入由 take_file 直接启动）。"""
        return

    def result(self):
        return self._result

    def error_text(self) -> str:
        return str(self._fail_text or "")

    def refresh_shelf(self) -> None:
        self._refresh_workspace()

    def reset_session(self) -> None:
        """清掉本次导入结果区，回到无书空态（M5-EX.6 初始化用）。

        只动本页内存与可见控件；磁盘清理由 ``fixtext_factory_reset`` 负责。
        """
        if self._worker is not None:
            try:
                self._worker.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._stop_thread()
        self._step = self.STATE_IDLE
        self._path = ""
        self._kind = ""
        self._result = None
        self._fail_text = ""
        self._clear_notice()
        self.file_label.setText("")
        self.step_label.setText("")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.progress_pane.setVisible(False)
        self.result_pane.setVisible(False)
        self.status_card.setVisible(False)
        self.cancel_btn.setEnabled(True)
        self._refresh_workspace()

    def shutdown(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        self._stop_thread()


# ---------------------------------------------------------------------------
# 全局拖放
# ---------------------------------------------------------------------------

def install_global_drop(window, module: ImportModule, goto_page=None) -> None:
    """让整个主窗口接受文件拖放，并自动切到「导入书籍」页。"""
    window.setAcceptDrops(True)
    zone_filter = getattr(window, "_fixtext_drop_filter", None)
    if zone_filter is not None:
        window.removeEventFilter(zone_filter)

    original_drag_enter = getattr(window, "dragEnterEvent", None)
    original_drop = getattr(window, "dropEvent", None)

    def drag_enter(event):
        path = DropZone._first_local_file(event.mimeData())
        if path and fi.detect_kind_safe(path):
            event.acceptProposedAction()
            if callable(goto_page):
                goto_page("import")
            return
        if original_drag_enter:
            original_drag_enter(event)

    def drop(event):
        path = DropZone._first_local_file(event.mimeData())
        if path:
            event.acceptProposedAction()
            if callable(goto_page):
                goto_page("import")
            module._take_file(path)
            return
        if original_drop:
            original_drop(event)

    window.dragEnterEvent = drag_enter
    window.dropEvent = drop


def _pkg_root() -> Path:
    try:
        from fixtext_paths import pkg_root

        return pkg_root()
    except Exception:                                   # pragma: no cover
        return Path(__file__).resolve().parent.parent


def default_workspace() -> Path:
    """工作区位置：包根下 `workspace/`。"""
    return _pkg_root() / "workspace"
