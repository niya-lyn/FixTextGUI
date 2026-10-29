"""FixText V1 · 导入书籍模块（T2.2 · Qt 移植）

对照 `FixText_V1_导入书籍_原型.html` 与排期文档 §2.2 入口① / §2.7.3 实现。

界面结构（三步向导，TXT 走两步）：

    拖放区（全局拖放也落在这里）
      → ① 选择文件
      → ② 处理方式（仅 EPUB：直接处理 / 先转成 TXT）
      → ③ 章节预览（仅 EPUB：只读列表）
      → 导入中（步骤化进度 + 取消）
      → 完成（人话提示 + 导入记录明细）

设计约束（逐条对应验收）：

- 验收① 双通道：拖放（本页拖放区 + 全局窗口拖放）与「选择文件」按钮都可用，
  两条通道最终走同一个入口 `_take_file()`，行为不分叉。
- 验收② 零配置编码识别：用户不做任何选择；提示语全部来自 `messages`（人话），
  界面上不出现字符集名。
- 验收③ 无概念暴露：章节预览只给「第 N 章 · 标题 · 字数」，不出现
  spine / OPF / container.xml / manifest / NCX 等词（有 lint 测试盯着）。
- 验收④ 原文件不被改：导入在后台线程跑 `fixtext_import.import_book`，
  它先复制再处理，并把导入前后的 sha256 写进记录；界面上以「技术核对」折叠区呈现。

取消语义（说清楚，不留半成品）：取消请求在**阶段边界**生效
（读文件 / 识别 / 复制 / 合并 / 核对之间）。取消后删除本次的工作区目录，
工作区里只可能留下已完整完成的导入。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QProgressBar, QPushButton,
    QRadioButton, QVBoxLayout, QWidget,
)

from fixtext_tokens import FONT_MONO, c, fs, px, r, sp
from fixtext_widgets import Card, Pill, hline, EmptyState

import fixtext_import as fi
import fixtext_shelf as shelf_data
from fixtext_import import messages as M
from fixtext_shelf_ui import ShelfPanel

#: 人话错误体系（T2.4）。合并后各页错误出口统一走这里：
#: 已判定的人话错误仍用页内提示条（用户不需要点掉弹窗才能继续），
#: 只有「没预期到的异常」才经 error_center 归类→写日志→弹人话错误卡。
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
    preview_ready = Signal(object, str)   # (PreviewResult, 临时副本路径)
    failed = Signal(str, str)          # (人话消息, 细节)

    def __init__(self, path: str, workspace: Path, options, mode: str):
        super().__init__()
        self._path = path
        self._workspace = workspace
        self._options = options
        self._mode = mode
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
            if self._mode == "preview":
                # 预览用工作区里的临时副本，确保预览期间读的也不是原文件
                tmp_dir = self._workspace / "_preview"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                tmp = tmp_dir / Path(self._path).name
                self._tick("正在读这本书的章节", 20)
                fi.copy_verbatim(self._path, tmp)
                if self._cancelled:
                    raise _Cancelled()
                preview = fi.chapter_preview(tmp)
                self.preview_ready.emit(preview, str(tmp))
                return

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
        except Exception as exc:          # 兜底：任何异常都翻译成人话，不把堆栈丢给用户
            self._cleanup_partial()
            # 没预期到的异常：归类 → 写诊断日志 → 人话错误卡（跨线程自动投递到界面线程）。
            # 页内仍给一条提示，用户不点掉弹窗也能继续操作。
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

class StepDots(QWidget):
    """顶部步骤指示：编号圆点 + 步骤名，当前步主色，已完成打勾。

    用真实 QLabel 拼装而不是富文本：Qt 的 QLabel 对 HTML 的 background /
    border-radius 支持不稳定（会把圆点渲染成方块或吃掉间距）。
    """

    #: 最多支持的步骤数（TXT 两步 / EPUB 三步，按最多的建槽位）
    MAX_STEPS = 3

    def __init__(self, steps: list[str], parent=None):
        super().__init__(parent)
        self._dots: list[QLabel] = []
        self._names: list[QLabel] = []
        self._lines: list[QFrame] = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # 按最大步骤数建好槽位，之后只切显隐 —— 否则先按 TXT 建两个圆点，
        # EPUB 的第 3 步「章节预览」永远没有控件可画（LIFECYCLE BUG 已修）。
        for i in range(self.MAX_STEPS):
            dot = QLabel()
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setFixedSize(22, 22)
            self._dots.append(dot)
            lay.addWidget(dot)

            lab = QLabel("")
            self._names.append(lab)
            lay.addWidget(lab)

            line = QFrame()
            line.setFixedHeight(2)
            line.setMinimumWidth(28)
            self._lines.append(line)
            lay.addWidget(line, 1)
        lay.addStretch(1)
        self.set_steps(steps, 0)

    def set_steps(self, steps: list[str], current: int) -> None:
        n = len(steps)
        for i in range(len(self._dots)):
            visible = i < n
            self._dots[i].setVisible(visible)
            self._names[i].setVisible(visible)
            self._lines[i].setVisible(i < n - 1)
            if not visible:
                continue
            if i < current:
                text, fg, bg = "✓", c("success"), c("success.bg")
                name_color = c("neutral.500")
            elif i == current:
                text, fg, bg = str(i + 1), "#FFFFFF", c("primary.500")
                name_color = c("neutral.900")
            else:
                text, fg, bg = str(i + 1), c("neutral.500"), c("neutral.100")
                name_color = c("neutral.500")
            self._dots[i].setText(text)
            self._dots[i].setStyleSheet(
                f"background:{bg};color:{fg};border-radius:11px;"
                f"font-size:11px;font-weight:700"
            )
            self._names[i].setText(steps[i])
            self._names[i].setStyleSheet(
                f"color:{name_color};font-size:{fs('sm')};"
                f"font-weight:{'700' if i == current else '500'}"
            )
            if i < n - 1:
                self._lines[i].setStyleSheet(
                    f"background:{c('primary.300') if i < current else c('neutral.200')};"
                    "border:none"
                )


class DropZone(QFrame):
    """拖放区：拖入时高亮；点击任意处等同「选择文件」。"""

    fileDropped = Signal(str)
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
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
        bg = c("primary.50") if state == "hot" else c("neutral.50")
        self.setStyleSheet(
            f"#DropZone{{background:{bg};border:2px dashed {border};"
            f"border-radius:{r('lg')}}}"
            "#DropZone QLabel{border:none;background:transparent}"
        )

    # 拖放 ---------------------------------------------------------------
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


class ChoosePane(QWidget):
    """EPUB 处理方式（单选卡）：直接处理 / 先转成 TXT。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(int(sp("3").replace("px", "")))

        q = QLabel(M.epub_choice_title())
        q.setWordWrap(True)
        q.setStyleSheet(f"color:{c('neutral.800')};font-size:{fs('md')};font-weight:600")
        lay.addWidget(q)

        self.group = QButtonGroup(self)
        self._cards: list[QFrame] = []
        for idx, (title, desc) in enumerate((M.epub_choice_direct(), M.epub_choice_to_txt())):
            frame = QFrame()
            frame.setObjectName("ChoiceCard")
            fl = QHBoxLayout(frame)
            fl.setContentsMargins(14, 12, 14, 12)
            fl.setSpacing(10)
            rb = QRadioButton(title)
            rb.setStyleSheet(f"color:{c('neutral.800')};font-size:{fs('base')};font-weight:600")
            self.group.addButton(rb, idx)
            fl.addWidget(rb, 0, Qt.AlignmentFlag.AlignTop)
            d = QLabel(desc)
            d.setWordWrap(True)
            d.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('xs')}")
            fl.addWidget(d, 1)
            self._cards.append(frame)
            lay.addWidget(frame)
            if idx == 0:
                rb.setChecked(True)
            rb.toggled.connect(self._restyle)
        self._restyle()
        lay.addStretch(1)

    def _restyle(self) -> None:
        for i, frame in enumerate(self._cards):
            sel = self.group.checkedId() == i
            frame.setStyleSheet(
                f"QFrame#ChoiceCard{{background:{c('primary.50') if sel else c('neutral.0')};"
                f"border:1px solid {c('primary.300') if sel else c('neutral.200')};"
                f"border-radius:{r('md')}}}"
            )

    def mode(self) -> str:
        return "direct" if self.group.checkedId() == 0 else "text"


class ChapterPane(QWidget):
    """章节预览：只读章节清单（M4-EX.2c 起去掉原型里没有的反馈按钮）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(int(sp("3").replace("px", "")))

        head = QHBoxLayout()
        t = QLabel(M.epub_chapters_title())
        t.setStyleSheet(f"color:{c('neutral.800')};font-size:{fs('md')};font-weight:600")
        head.addWidget(t)
        self.count = Pill("—", "neutral")
        head.addWidget(self.count)
        head.addStretch(1)
        self.status = Pill("", "ok")
        head.addWidget(self.status)
        lay.addLayout(head)

        hint = QLabel(M.epub_chapters_hint())
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('xs')}")
        lay.addWidget(hint)

        self.list = QListWidget()
        self.list.setObjectName("ChapterList")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # v3 质感层：表格斑马纹（配合 QSS 的 alternate-background-color）
        self.list.setAlternatingRowColors(True)
        # 高度取「整行数 × 行高 + 边框」，避免最后一行被裁掉半截
        self.list.setMinimumHeight(7 * self.ROW_HEIGHT + 8)
        self.list.setMaximumHeight(9 * self.ROW_HEIGHT + 8)
        lay.addWidget(self.list)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('xs')}")
        lay.addWidget(self.note)

    #: 章节行高（px）——固定给值，不依赖 sizeHintForRow（空列表时返回 -1）
    ROW_HEIGHT = 30

    def load(self, preview) -> None:
        self.list.clear()
        self.count.setText(f"共 {len(preview.chapters)} 章")
        for ch in preview.chapters:
            item = QListWidgetItem(self._row(ch))
            item.setSizeHint(QSize(0, self.ROW_HEIGHT))
            self.list.addItem(item)
        self.status.setText(M.epub_order_ok() if preview.order_ok else M.epub_order_suspect())
        self.status.setStyleSheet(self._pill_style(
            "ok" if preview.order_ok else "warn"))
        # 没有目录信息时才补一句说明；有目录时上方已有提示，不重复
        self.note.setText("" if preview.has_toc else M.epub_no_toc())

    @staticmethod
    def _pill_style(kind: str) -> str:
        table = {
            "ok": ("success", "success.bg"),
            "warn": ("warning", "warning.bg"),
            "neutral": ("neutral.500", "neutral.100"),
        }
        fg, bg = table.get(kind, table["neutral"])
        return (
            f"color:{c(fg)};background:{c(bg)};border-radius:{r('full')};"
            f"padding:2px 9px;font-size:{fs('xs')};font-weight:700"
        )

    @staticmethod
    def _row(ch) -> str:
        # 封面 / 空白页没有正文，不该被叫成「第 N 章」——直接写它是什么。
        if ch.chars == 0:
            return ch.title
        return f"第 {ch.index} 章　{ch.title}"

    def scroll_to(self, index: int) -> None:
        self.list.scrollToItem(self.list.item(index))


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

        # 技术核对（默认折叠）：唯一出现哈希与识别结果的地方
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
            f"border-radius:{r('md')};padding:10px;font-family:{FONT_MONO};"
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
        self.detail.setText(
            "原文件导入前哈希  " + result.source_sha256_before + "\n"
            "原文件导入后哈希  " + result.source_sha256_after + "\n"
            "工作区副本哈希    " + result.workspace_copy_sha256 + "\n"
            f"对照结论：{'一致（原文件未被修改）' if same == '一致' else '不一致，请保留此记录反馈'}\n"
            f"识别结果：{result.encoding_label}（{result.encoding_confidence}）· "
            f"换行 {result.newline_kind} · 无法解释的字节 {result.replaced_chars}\n"
            f"导入方式：{'直接处理' if result.epub_mode == 'direct' else '先转成 TXT'}"
            f" · 复用已有副本：{'是' if result.reused else '否'}\n"
            # 只给子目录名，不给绝对路径：用户拿它核对是哪本书，
            # 打开目录交给上面的按钮（绝对路径属于内部信息，不进界面）
            f"工作区子目录：{Path(result.workspace_dir).name}"
        )


# ---------------------------------------------------------------------------
# 主模块
# ---------------------------------------------------------------------------

class ImportModule(QWidget):
    """「导入书籍」模块页。"""

    bookReady = Signal(str)      # 导入完成 → book.txt 绝对路径（供后续模块接力）
    currentBookChanged = Signal(str)   # 书架里切换了当前书 → 该书 book.txt 路径

    STEPS_TXT = ["选择文件", "导入"]
    STEPS_EPUB = ["选择文件", "处理方式", "章节预览"]

    def __init__(self, workspace_root: str | Path | None = None, parent=None):
        super().__init__(parent)
        self.workspace = Path(workspace_root or default_workspace())
        self.workspace.mkdir(parents=True, exist_ok=True)

        self._path: str | None = None
        self._kind: str | None = None
        self._preview = None
        self._preview_copy: str | None = None
        self._result = None
        self._thread: QThread | None = None
        self._worker: ImportWorker | None = None
        self._step = 0
        #: 最近一次导入失败 / 取消的人话原因（M4-EX.2c 向导要据此判断成败，
        #: 不能用提示条是否存在来判断——正常提示也会显示在同一个位置）
        self._fail_text = ""

        self._build()

    # ---- 构建 ---------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(int(sp("4").replace("px", "")))

        head = QWidget()
        head.setObjectName("PageHead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        t = QLabel("导入书籍")
        t.setFont(QFont("", int(fs("2xl").replace("px", "")), QFont.Weight.Bold))
        t.setStyleSheet(f"color:{c('neutral.900')}")
        hl.addWidget(t)
        sub = QLabel(
            "把 TXT 或 EPUB 拖进窗口即可开始。书会被复制到工作区处理，"
            "你电脑里原来的文件不会被改动。"
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('md')}")
        hl.addWidget(sub)
        root.addWidget(head)

        # ---- 内联提示条（错误 / 反馈，不用弹窗）----
        # 不用 QMessageBox：弹窗会阻塞整个窗口事件循环，用户必须点掉才能继续；
        # 内联提示始终可见、可自查，也不会打断拖放连续操作。
        self.notice = QLabel("")
        self.notice.setObjectName("NoticeBar")
        self.notice.setWordWrap(True)
        self.notice.setVisible(False)
        root.addWidget(self.notice)

        # ---- 拖放 + 选文件 ----
        self.drop_card = Card("从文件导入", "拖放或选择，两条路都一样")
        self.drop_zone = DropZone()
        self.drop_zone.fileDropped.connect(self._take_file)
        self.drop_zone.clicked.connect(self._choose_file)
        self.drop_card.body_l.addWidget(self.drop_zone)

        row = QHBoxLayout()
        row.addStretch(1)
        self.browse_btn = QPushButton("选择文件…")
        self.browse_btn.setObjectName("BtnPrimary")
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_btn.clicked.connect(self._choose_file)
        row.addWidget(self.browse_btn)
        self.drop_card.body_l.addSpacing(12)
        self.drop_card.body_l.addLayout(row)
        root.addWidget(self.drop_card)

        # ---- 向导 ----
        self.wizard = Card("导入向导", "EPUB 三步，TXT 两步")
        self.dots = StepDots(self.STEPS_TXT)
        self.wizard.body_l.addWidget(self.dots)
        self.wizard.body_l.addSpacing(12)

        # 用可见性切换而不是 QStackedWidget：stack 的高度按「最高的一页」算，
        # 章节列表那页比别的页高很多，会让其它页下方留一大片空白。
        # 这里用一个普通容器 + 垂直布局，同一时刻只显示一页（隐藏页不占高度）。
        self.panes = QWidget()
        self._panes_l = QVBoxLayout(self.panes)
        self._panes_l.setContentsMargins(0, 0, 0, 0)
        self._panes_l.setSpacing(0)
        self.choose_pane = ChoosePane()
        self.chapter_pane = ChapterPane()
        self.result_pane = ResultPane(on_open_folder=self._open_workspace)

        # 本次选中的文件摘要（第 1 步的内容）
        self.pick_pane = QWidget()
        pl = QVBoxLayout(self.pick_pane)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        self.pick_label = QLabel("还没有选择文件。")
        self.pick_label.setWordWrap(True)
        self.pick_label.setStyleSheet(f"color:{c('neutral.700')};font-size:{fs('sm')}")
        pl.addWidget(self.pick_label)
        self.pick_hint = QLabel("")
        self.pick_hint.setWordWrap(True)
        self.pick_hint.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('xs')}")
        pl.addWidget(self.pick_hint)
        pl.addStretch(1)

        self.progress_pane = QWidget()
        gl = QVBoxLayout(self.progress_pane)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(10)
        self.step_label = QLabel("准备中…")
        self.step_label.setStyleSheet(f"color:{c('neutral.800')};font-size:{fs('sm')}")
        gl.addWidget(self.step_label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        gl.addWidget(self.bar)
        self.cancel_btn = QPushButton("取消导入")
        self.cancel_btn.setObjectName("BtnOutline")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._cancel)
        gl.addStretch(1)
        crow = QHBoxLayout()
        crow.addStretch(1)
        crow.addWidget(self.cancel_btn)
        gl.addLayout(crow)

        # 顺序固定为 0..4；同一时刻只有一页可见，见 `_render_step`
        self._page_widgets = [
            self.pick_pane, self.choose_pane, self.chapter_pane,
            self.progress_pane, self.result_pane,
        ]
        for w in self._page_widgets:
            w.setVisible(False)
            self._panes_l.addWidget(w)
        self.wizard.body_l.addWidget(self.panes)
        self.wizard.body_l.addSpacing(12)

        foot = QHBoxLayout()
        self.back_btn = QPushButton("上一步")
        self.back_btn.setObjectName("BtnSecondary")
        self.back_btn.clicked.connect(self._back)
        self.next_btn = QPushButton("下一步")
        self.next_btn.setObjectName("BtnPrimary")
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.clicked.connect(self._next)
        self.cancel_step_btn = QPushButton("取消")
        self.cancel_step_btn.setObjectName("BtnGhost")
        self.cancel_step_btn.clicked.connect(self._reset)
        foot.addWidget(self.back_btn)
        foot.addWidget(self.cancel_step_btn)
        foot.addStretch(1)
        foot.addWidget(self.next_btn)
        self.foot_widget = QWidget()
        self.foot_widget.setLayout(foot)
        self.wizard.body_l.addWidget(self.foot_widget)
        root.addWidget(self.wizard)

        # ---- 安全说明（默认折叠）----
        safety = Card("导入安全说明", "你原来的文件不会被改动", collapsible=True, open_=False)
        body = QLabel(
            "· 书会被复制一份到 FixText 的工作区，所有处理都在这份副本上做，"
            "你原来的文件始终原样保留。\n"
            "· 导入前后会各记一次文件指纹，用来确认原文件一个字节都没变。\n"
            "· 书里的字符格式差异会自动处理，不需要你做任何选择；"
            "处理完成后会用一句普通话告诉你做了什么。\n"
            "· 电子书导入只显示章节标题与顺序，不涉及任何内部结构术语。"
        )
        body.setWordWrap(True)
        body.setStyleSheet(f"color:{c('neutral.700')};font-size:{fs('sm')}")
        safety.body_l.addWidget(body)
        root.addWidget(safety)

        # ---- 工作区书架（原型 v3 §6）----
        # 多书：这里列出工作区里真实的书，行内「设为当前」切换要校对的书。
        # 数据源就是工作区现有的副本（不新增导入副本机制），没有书时本卡收起、
        # 换成下面的统一空状态。
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

        # 无书空状态（原型 v3 §4，导入页口径）：工作区还没有书时，
        # 工作区卡换成这条引导；主按钮就是本页真实的选文件入口
        # （原型此位是「导入示例书」按钮，真实应用没有演示书，改接真实入口）。
        self.empty_state = EmptyState(
            "📥", "还没有导入的书",
            "本页默认即空状态：顶部拖放区 + 选择文件按钮就是导入入口。"
            "导入完成后，结果卡会替换此引导。",
            primary="📥 选择文件导入")
        self.empty_state.primaryClicked.connect(self._choose_file)
        root.addWidget(self.empty_state)

        root.addStretch(1)
        self._refresh_workspace()
        self._render_step()

    # ---- 步骤状态 ------------------------------------------------------
    def _steps(self) -> list[str]:
        return self.STEPS_EPUB if self._kind == "epub" else self.STEPS_TXT

    def _render_step(self) -> None:
        steps = self._steps()
        # current >= 步数 = 全部走完（完成页所有圆点都打勾）
        self.dots.set_steps(steps, min(self._step, len(steps)))

        pane = {
            0: 0, 1: (1 if self._kind == "epub" else 3), 2: 2, 3: 3, 4: 4,
        }.get(self._step, 0)
        # TXT 的第 1 步「导入」直接进入进度面板
        for i, w in enumerate(self._page_widgets):
            w.setVisible(i == pane)

        at_start = self._step == 0
        self.back_btn.setEnabled(self._step in (1, 2) and self._kind == "epub")
        self.cancel_step_btn.setVisible(self._step in (1, 2))
        self.foot_widget.setVisible(self._step in (0, 1, 2))

        if self._step == 0:
            self.next_btn.setText("下一步" if self._kind == "epub" else "开始导入")
            self.next_btn.setEnabled(bool(self._path))
        elif self._step == 1:
            self.next_btn.setText("看一下章节")
            self.next_btn.setEnabled(True)
        elif self._step == 2:
            self.next_btn.setText("开始导入")
            self.next_btn.setEnabled(True)
        elif self._step == 4:
            self.next_btn.setText("再导入一本")
            self.next_btn.setEnabled(True)

    # ---- 选文件 --------------------------------------------------------
    def _show_notice(self, text: str, kind: str = "warn") -> None:
        """在页面内显示一条人话提示（kind: warn | info | ok）。"""
        palette = {
            "warn": ("warning.bg", "warning", "neutral.200"),
            "info": ("primary.50", "primary.700", "primary.200"),
            "ok": ("success.bg", "success", "success.bg"),
        }
        bg, fg, border = palette.get(kind, palette["warn"])
        self.notice.setText(text)
        self.notice.setStyleSheet(
            f"background:{c(bg)};color:{c(fg)};border:1px solid {c(border)};"
            f"border-radius:{r('md')};padding:10px 12px;font-size:{fs('sm')}"
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
        """拖放与选择文件两条通道的唯一汇合点。"""
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
        self._preview = None
        self._result = None
        size_mb = Path(path).stat().st_size / (1024 * 1024)
        self.pick_label.setText(f"已选择：{Path(path).name}")
        self.pick_hint.setText(
            M.big_file_note(size_mb) if size_mb >= 20
            else ("这本是电子书，下一步选处理方式。" if kind == "epub"
                  else "这本可以直接导入，点「开始导入」即可。")
        )
        # EPUB 直接进向导第 2 步：不让用户误点「开始导入」跳过「直接处理 / 先转 TXT」
        self._step = 1 if kind == "epub" else 0
        self._render_step()

    # ---- 下一步 / 上一步 ----------------------------------------------
    def _next(self) -> None:
        if self._step == 0:
            if self._kind == "epub":
                self._step = 1
                self._render_step()
            else:
                self._start_import()
            return
        if self._step == 1 and self._kind == "epub":
            self._load_preview()
            return
        if self._step == 2:
            self._start_import()
            return
        if self._step == 4:
            self._reset()
            return

    def _back(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._render_step()

    def _load_preview(self) -> None:
        self._step = 3
        self._render_step()
        self.step_label.setText("正在读这本书的章节…")
        self.bar.setRange(0, 0)      # 不确定进度：显示滚动条
        self._start_worker("preview")

    def _start_import(self) -> None:
        self._step = 3
        self._render_step()
        self.step_label.setText("准备中…")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self._start_worker("import")

    def _start_worker(self, mode: str) -> None:
        if self._thread is not None:
            return
        options = fi.ImportOptions(epub_mode=self.choose_pane.mode())
        self._worker = ImportWorker(self._path, self.workspace, options, mode)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.preview_ready.connect(self._on_preview)
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

    @Slot(object, str)
    def _on_preview(self, preview, copy_path: str) -> None:
        self._stop_thread()
        self._preview = preview
        self._preview_copy = copy_path
        self.chapter_pane.load(preview)
        self._step = 2
        self._render_step()
        self.step_label.setText("")

    @Slot(object)
    def _on_finished(self, result) -> None:
        self._stop_thread()
        self._fail_text = ""
        self._result = result
        self.result_pane.load(result)
        self._step = 4
        self._render_step()
        self._cleanup_preview()
        self._refresh_workspace()
        self.bookReady.emit(result.text_path)

    @Slot(str, str)
    def _on_failed(self, message: str, detail: str) -> None:
        self._stop_thread()
        self._cleanup_preview()
        self._step = 0
        self._render_step()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.step_label.setText("")
        self._fail_text = str(message or "")
        if detail == "cancelled":
            self._show_notice(message, "info")
        else:
            # 失败原因 + 下一步建议是同一条提示，用户不需要点掉弹窗才能继续
            self._show_notice(message + " 你可以换一个文件再试，或者先确认这个文件能正常打开。")

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

    def _reset(self) -> None:
        self._cleanup_preview()
        self._path = None
        self._kind = None
        self._preview = None
        self._result = None
        self._step = 0
        self.pick_label.setText("还没有选择文件。")
        self.pick_hint.setText("")
        self.chapter_pane.list.clear()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.step_label.setText("")
        self._clear_notice()
        self._render_step()

    def _cleanup_preview(self) -> None:
        if self._preview_copy:
            try:
                Path(self._preview_copy).unlink(missing_ok=True)
                Path(self._preview_copy).parent.rmdir()
            except OSError:
                pass
            self._preview_copy = None

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
        """刷新书架：工作区里有书就展示列表，没有就换成空状态引导。

        数量与占用取自工作区真实目录（与 ``workspace_usage`` 同一判据），
        书架行本身由 ``ShelfPanel`` 按真实导入记录渲染。
        """
        books = self.shelf.books()
        n_books, size = fi.workspace_usage(self.workspace)
        # 空状态（原型 v3 §4）：无书时工作区卡换成统一空状态引导
        self.workspace_card.setVisible(bool(n_books))
        self.empty_state.setVisible(not n_books)
        if n_books:
            self.shelf.refresh(books)
            self.workspace_label.setText(
                shelf_data.shelf_caption(n_books, size)
                + " 在列表里点「设为当前」，切换要校对的书。")
        else:
            self.workspace_label.setText(
                "工作区还是空的，导入第一本书后就会出现在这里。")

    def _on_shelf_current_changed(self, book_id: str) -> None:
        """书架里换了当前书：告诉外层（顶栏书名跟着换，各页数据本卡不动）。"""
        book = shelf_data.find_book(self.workspace, book_id)
        if book is None:
            return
        self.currentBookChanged.emit(book.text_path)

    def current_book(self):
        """当前书（数据层对象）；没有书时 None。"""
        return self.shelf.current_book()

    # ---- 向导外的程序化入口（M4-EX.2c） --------------------------------
    # 向导只是导入流程的引导层：它需要「选好文件之后」继续推进同一台步骤机，
    # 所以这里把已有的内部步骤暴露成几个只读/只推进入口，**不新建流程**。
    def take_file(self, path: str) -> None:
        """与拖放 / 选择文件同一个汇合入口（向导用它把用户选的书交进来）。"""
        self._take_file(path)

    def step(self) -> int:
        return int(self._step)

    def is_busy(self) -> bool:
        return self._thread is not None

    def has_finished(self) -> bool:
        return self._step == 4 and self._result is not None

    def next_enabled(self) -> bool:
        """主按钮此刻能否点（界面上可见 + 可用；不因所在页面暂时不在前台而失效）。"""
        return bool(self.next_btn.isEnabled()
                    and self.next_btn.isVisibleTo(self))

    def click_next(self) -> None:
        """点一下本页自己的主按钮（向导代用户按「下一步 / 开始导入」）。"""
        if self.next_enabled():
            self._next()

    def result(self):
        return self._result

    def error_text(self) -> str:
        """最近一次导入失败 / 取消的人话原因（没失败时为空格串）。"""
        return str(self._fail_text or "")

    def refresh_shelf(self) -> None:
        """重扫工作区并重排书架（导入完成 / 外部改了当前书后调用）。"""
        self._refresh_workspace()

    def shutdown(self) -> None:
        """窗口关闭时调用：取消后台任务，避免线程未结束时退出。"""
        if self._worker is not None:
            self._worker.cancel()
        self._stop_thread()


# ---------------------------------------------------------------------------
# 全局拖放
# ---------------------------------------------------------------------------

def install_global_drop(window, module: ImportModule, goto_page=None) -> None:
    """让整个主窗口接受文件拖放，并自动切到「导入书籍」页。

    `goto_page` 为切页回调（通常是 MainWindow.go)；不传时只做导入不切页。
    """
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
    """包根（M4-T4.1b：统一解析，冻结后 __file__ 不再指源码树）。"""
    try:
        from fixtext_paths import pkg_root

        return pkg_root()
    except Exception:                                   # pragma: no cover
        return Path(__file__).resolve().parent.parent


def default_workspace() -> Path:
    """工作区位置：包根下 `workspace/`（M4-T4.4 统一用户区，绿色分发时可整体搬走）。

    原实现返回 fixtext_ui/workspace，会让「书籍导入副本」和「我的词库」
    落在两个不同的用户区目录里；统一到 <包根>/workspace。
    """
    return _pkg_root() / "workspace"
