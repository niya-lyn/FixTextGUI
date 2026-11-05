"""新手向导（M4-EX.2c · 任务式，替代原只读演示向导）
==================================================

向导不再是「看三条要点」，而是**带着用户真实走完一本书的三步**：

  第 1 步 · 导入   用户点「选择我的书…」→ 系统文件选择对话框 → 真实导入
                   （复用导入模块的文件汇合入口，与拖放同一条路）
  第 2 步 · 一键校正 真实跑六阶段校正（自带可视化进度弹窗，可取消且二次确认）
  第 3 步 · 导出   真实导出干净文件 + 替换统计，历史记录留一条

每一步完成后，向导里显示的是**这一步的真实结果**（书名 / 字数 / 编码 /
命中数 / 成品文件名），不是固定文案——所以「向导走完」等于「书真的处理好了」。

交互（对齐合并版原型 v3 · M5-EX.5）：
- 首启自动弹出（主窗口触发）、可跳过、可返回上一步；
- 按钮左右分栏：左侧「上一步 / 跳过」，右侧主操作；
- 点「上一步」后，当前页主按钮变为「下一步」，一键回到刚才离开的那一步（不重跑）；
- ☰「重新观看」始终从第 1 步开始；
- 校正取消二次确认（原型 `#corrConfirm`，层级高于校正进度弹窗）。

层级（原型附「层级速查」z-index 表，Qt 侧用窗口栈等效表达）：
  主界面 1–10 → 向导 45/46（模态窗，一定在主界面之上）
  → 通用弹窗 50 → 校正取消确认 56（进度弹窗内的遮罩层，一定在弹窗内容之上）
  → Toast 60 → ☰ 菜单 70（菜单是顶层弹出，盖住向导）

设计约束（与全工程一致）：
- 只消费 `fixtext_tokens.py` 的令牌，不硬编码颜色 / 尺寸字面量。
- 内联 QSS 用精确 `#ObjectName` 选择器（避免裸 `QFrame{}` 误伤子 QLabel）。
- 条款号（§）与内部术语不进向导文案。

只让用户选**自己的书**：原型里的演示样书不作为功能实现。
测试用的公版样本只是验收输入，不是产品功能。
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from fixtext_tokens import c, sp, r, fs
from fixtext_widgets import enable_chrome, hline, PrimaryButton, repolish


# ---------------------------------------------------------------------------
# 三步定义（与原型 ONB_STEPS 同源）
# ---------------------------------------------------------------------------

STEPS = [
    ("📥", "导入书籍"),
    ("⚡", "一键校正"),
    ("📤", "导出结果"),
]

FILE_FILTER = "书籍文件 (*.txt *.epub)"


def _clear_layout(layout) -> None:
    """递归清空布局：控件解父子后 deleteLater，子布局同样递归。

    只按 ``item.widget()`` 清不够——标题行是 ``addLayout`` 塞进去的嵌套布局，
    ``item.widget()`` 对它返回 None，旧标题会一路留着叠在下一页上（真实缺陷）。
    """
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
            continue
        child = item.layout()
        if child is not None:
            _clear_layout(child)
            child.deleteLater()
            continue
        spacer = item.spacerItem()
        if spacer is not None:
            del spacer


class _StepBars(QWidget):
    """三步进度条（原型 `.onb-steps`：每步一根细条，已完成 100%、当前 50%）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bars: list[QProgressBar] = []
        self._labels: list[QLabel] = []
        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        for ico, name in STEPS:
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(6)
            bar = QProgressBar()
            bar.setObjectName("OnbBar")
            bar.setProperty("state", "todo")
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            bl.addWidget(bar)
            lab = QLabel(f"{ico} {name}")
            lab.setObjectName("OnbLabel")
            lab.setProperty("state", "todo")
            bl.addWidget(lab)
            self._bars.append(bar)
            self._labels.append(lab)
            hl.addWidget(box, 1)

    def set_step(self, current: int) -> None:
        for i, (bar, lab) in enumerate(zip(self._bars, self._labels)):
            if i < current:
                state, value = "done", 100
            elif i == current:
                state, value = "active", 50
            else:
                state, value = "todo", 0
            bar.setValue(value)
            # 进度条 / 文字三态配色与圆角统一由 QSS 属性选择器承接
            bar.setProperty("state", state)
            lab.setProperty("state", state)
            repolish(bar)
            repolish(lab)

    #: 测试用：读回每根条的百分比
    def values(self) -> list[int]:
        return [b.value() for b in self._bars]


# ---------------------------------------------------------------------------
# 向导
# ---------------------------------------------------------------------------

class FirstRunWizard(QDialog):
    """任务式新手向导：真实引导用户走完 导入 → 校正 → 导出。

    主窗口负责弹出 / 记住「已看过」/ ☰ 重开；本类只负责把三步做实。
    完成（accept）后由主窗口跳到「历史记录」页（与原型 finishWizard 一致）。
    """

    exported = Signal(str)     # 导出成品文件的绝对路径（供验收与接线）

    def __init__(self, import_module=None, oneclick_module=None,
                 export_module=None, parent=None, has_current_book=False):
        super().__init__(parent)
        self.setWindowTitle("新手向导 · FixTextGUI")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.import_module = import_module
        self.oneclick_module = oneclick_module
        self.export_module = export_module
        # M5-EX.5：重看 / 首启一律从第 1 步开始。has_current_book 仅保留兼容形参，
        # 不再跳过导入（旧 M4-EX.2c-S5 行为已撤销）。
        self.has_current_book = bool(has_current_book)

        self.step = 0
        self._import_result = None
        self._correction = None
        self._export = None
        self._export_path = ""
        self._busy = False
        self._error = ""
        # 点「上一步」时记下离开的步号；返回页用「下一步」跳回，不重跑业务。
        self._back_from_step: int | None = None
        # 忙碌态延迟渲染：短操作不整页重绘，避免进度条/提示块一闪而过。
        self._busy_ui_timer = QTimer(self)
        self._busy_ui_timer.setSingleShot(True)
        self._busy_ui_timer.setInterval(180)
        self._busy_ui_timer.timeout.connect(self._render_if_still_busy)

        self._build()
        self._render()
    # ---------------------------------------------------------------- 构建
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._head())

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 16, 20, 12)
        bl.setSpacing(12)
        self.bars = _StepBars()
        bl.addWidget(self.bars)
        self.panel = QWidget()
        self.panel.setObjectName("WizardPanel")
        enable_chrome(self.panel)
        # 配色交给 fixtext.qss 的 #WizardPanel（原内联收归）
        self.panel_l = QVBoxLayout(self.panel)
        self.panel_l.setContentsMargins(20, 18, 20, 18)
        self.panel_l.setSpacing(10)
        bl.addWidget(self.panel)
        root.addWidget(body)

        root.addWidget(self._foot())

    def _head(self) -> QWidget:
        head = QWidget()
        head.setObjectName("ModalHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(20, 16, 20, 16)
        hl.setSpacing(12)
        ico = QLabel("🧭")
        ico.setFixedSize(40, 40)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background:{c('primary.100')};color:{c('primary.700')};"
            f"border-radius:{r('lg')};font-size:{fs('xl')}")
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel("新手向导")
        t.setStyleSheet(
            f"font-weight:700;font-size:{fs('lg')};color:{c('neutral.900')}")
        s = QLabel("三步走完一本书的校准")
        s.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('xs')}")
        col.addWidget(t)
        col.addWidget(s)
        hl.addWidget(ico)
        hl.addLayout(col, 1)
        close = QPushButton("×")
        close.setObjectName("ModalClose")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setFixedSize(30, 30)
        close.setToolTip("关掉向导（随时可从右上角菜单重新打开）")
        close.clicked.connect(self._skip_wizard)
        hl.addWidget(close)
        return head

    def _foot(self) -> QWidget:
        foot = QWidget()
        foot.setObjectName("ModalFoot")
        self.foot_l = QHBoxLayout(foot)
        self.foot_l.setContentsMargins(20, 12, 20, 14)
        self.foot_l.setSpacing(10)
        self.foot_widget = foot
        return foot

    # ---------------------------------------------------------------- 渲染
    def _render(self) -> None:
        self.bars.set_step(self.step)
        _clear_layout(self.panel_l)

        title, desc, ico = self._copy()
        hl = QHBoxLayout()
        hl.setSpacing(12)
        ic = QLabel(ico)
        ic.setFixedSize(44, 44)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setStyleSheet(
            f"background:{c('primary.100')};color:{c('primary.700')};"
            f"border-radius:{r('lg')};font-size:{fs('xl')}")
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title)
        t.setWordWrap(True)
        t.setStyleSheet(
            f"font-weight:700;font-size:{fs('md')};color:{c('neutral.900')}")
        col.addWidget(t)
        hl.addWidget(ic)
        hl.addLayout(col, 1)
        self.panel_l.addLayout(hl)

        p = QLabel(desc)
        p.setWordWrap(True)
        p.setStyleSheet(
            f"color:{c('neutral.700')};font-size:{fs('sm')};line-height:1.7")
        self.panel_l.addWidget(p)
        self.panel_l.addWidget(hline())
        self.panel_l.addWidget(self._result_block())
        if self._busy:
            self.progress = QProgressBar()
            self.progress.setObjectName("OnbProgress")
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setTextVisible(False)
            self.progress.setFixedHeight(8)
            # 配色交给 fixtext.qss 的 #OnbProgress（原内联收归）
            self.panel_l.addWidget(self.progress)
        self._render_actions()
        self.adjustSize()

    def _copy(self) -> tuple[str, str, str]:
        if self.step == 0:
            return ("第 1 步 · 导入一本书",
                    "先把要校正的书导入工作区。原文件只读保护，FixTextGUI 会在"
                    "工作区里留下一份副本和初始快照，随时能回到这一刻。",
                    "📥")
        if self.step == 1:
            return ("第 2 步 · 一键校正",
                    "用默认配置跑完「备份 → 排版 → 词库替换 → 校验」，进度条里"
                    "每一步都看得到；中途想停可以取消，取消不会留下半成品。",
                    "⚡")
        if self.step == 2:
            return ("第 3 步 · 导出结果",
                    "导出干净文件，自动附一份替换报告，并在历史记录里留一条任务，"
                    "以后随时能恢复或重新导出。",
                    "📤")
        return ("一本书的校准已完成！",
                "导入、校正、导出三步都真实完成了，结果分别落在「导入书籍 / "
                "一键校正 / 导出结果」三页，历史记录也多了一条任务。需要细修"
                "引号时，可随时进入「检查问题」逐处处理。",
                "🎉")

    # ---- 各步的真实结果 ------------------------------------------------
    def _result_block(self) -> QWidget:
        """这一步做完之后的真实结果（没做完就只有一句当步提示）。"""
        rows: list[str] = []
        if self.step == 0 and self._import_result is not None:
            res = self._import_result
            rows = [
                f"书名：{getattr(res, 'title', '')}",
                f"字数：{getattr(res, 'text_chars', 0)} 字"
                f"（{getattr(res, 'chapters', 0)} 个章节）",
                f"编码：{getattr(res, 'encoding_label', '')}",
                "原文件没有被改动（已核对过指纹）"
                if getattr(res, "source_unchanged", True) else "原文件指纹有变化，请核对",
            ]
        elif self.step == 1 and self._correction is not None:
            summ = self._correction or {}
            libs = summ.get("libs") or []
            rows = [
                f"替换命中：{summ.get('hits', 0)} 处",
                f"涉及词库：{'；'.join(libs) if libs else '无'}",
                f"耗时：{summ.get('elapsed_s', 0)} 秒",
                "引号类问题已同步到「检查问题」页，可逐处处理",
            ]
        elif self.step == 2 and self._export is not None:
            out = self._export
            rows = [
                f"成品文件：{Path(out.main_file).name}",
                f"替换命中：{out.hits} 处",
                f"替换统计：{Path(out.stats_text).name} / {Path(out.stats_csv).name}",
                f"保存位置：{Path(out.main_file).parent}",
            ]
        elif self.step == 3 and self._export is not None:
            out = self._export
            rows = [
                f"成品文件：{Path(out.main_file).name}（{out.fmt.upper()}）",
                f"替换命中：{out.hits} 处",
                f"保存位置：{Path(out.main_file).parent}",
            ]

        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)

        if self._error:
            err = QLabel("⚠️ " + self._error)
            err.setWordWrap(True)
            err.setStyleSheet(
                f"background:{c('warning.bg')};border:1px solid {c('warning.border')};"
                f"color:{c('warning')};border-radius:{r('md')};padding:{sp('3')} {sp('4')};"
                f"font-size:{fs('sm')}")
            bl.addWidget(err)

        if rows:
            ttl = QLabel("✓ 这一步已完成")
            ttl.setStyleSheet(
                f"color:{c('success')};font-size:{fs('sm')};font-weight:700")
            bl.addWidget(ttl)
            for txt in rows:
                lab = QLabel(txt)
                lab.setWordWrap(True)
                lab.setStyleSheet(
                    f"color:{c('neutral.700')};font-size:{fs('sm')}")
                bl.addWidget(lab)
        elif not self._error and not self._busy:
            hint = QLabel(self._pending_hint())
            hint.setWordWrap(True)
            hint.setStyleSheet(
                f"background:{c('info.bg')};border:1px solid {c('info.border')};"
                f"color:{c('info')};border-radius:{r('md')};padding:{sp('3')} {sp('4')};"
                f"font-size:{fs('sm')}")
            bl.addWidget(hint)
        return box

    def _pending_hint(self) -> str:
        return {
            0: "点右下角「选择我的书」，从你自己的电脑里挑一本 TXT 或 EPUB。",
            1: "准备好后点右下角「开始校正」，全程有进度，随时能取消。",
            2: "点右下角「导出并生成历史」，成品会存到这本书所在文件夹的"
               "「导出结果」里。",
            3: "点下面「完成」回到历史记录，随时能回来查看这次的结果。",
        }[self.step]

    # ---- 按钮区（左：返回 / 跳过；右：主操作） -------------------------
    def _render_actions(self) -> None:
        _clear_layout(self.foot_l)
        left = QWidget()
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)

        self._prev = QPushButton("上一步")
        self._prev.setObjectName("BtnGhost")
        self._prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev.clicked.connect(self._go_prev)
        self._prev.setVisible(0 < self.step < 3 and not self._busy)
        ll.addWidget(self._prev)

        self._skip = QPushButton("跳过")
        self._skip.setObjectName("BtnGhost")
        self._skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip.clicked.connect(self._skip_wizard)
        self._skip.setVisible(self.step < 3 and not self._busy)
        ll.addWidget(self._skip)

        self.foot_l.addWidget(left)
        self.foot_l.addStretch(1)

        # 从后面退回来时：保留原主操作作次按钮，主按钮改「下一步」回到离开页
        if self._can_resume_next() and not self._busy:
            redo = QPushButton(self._action_text())
            redo.setObjectName("BtnGhost")
            redo.setCursor(Qt.CursorShape.PointingHandCursor)
            redo.clicked.connect(self._run_step_action)
            self.foot_l.addWidget(redo)

        self._primary = PrimaryButton(self._primary_text())
        self._primary.setCursor(Qt.CursorShape.PointingHandCursor)
        self._primary.clicked.connect(self._go_next)
        self._primary.setEnabled(not self._busy)
        self.foot_l.addWidget(self._primary)

    def _can_resume_next(self) -> bool:
        return (
            self._back_from_step is not None
            and self.step < self._back_from_step
            and self.step < 3
        )

    def _action_text(self) -> str:
        """当前步的真实业务按钮文案（与「下一步」恢复导航区分）。"""
        return {
            0: "📥 选择我的书…",
            1: "⚡ 开始校正",
            2: "📤 导出并生成历史",
            3: "完成",
        }[self.step]

    def _primary_text(self) -> str:
        if self._busy:
            return {0: "正在导入…", 1: "正在校正…", 2: "正在导出…"}.get(
                self.step, "请稍候…")
        if self._can_resume_next():
            return "下一步"
        return self._action_text()

    # ---------------------------------------------------------------- 导航
    def _go_prev(self) -> None:
        if self.step > 0 and not self._busy:
            self._back_from_step = self.step
            self.step -= 1
            self._error = ""
            self._render()

    def _go_next(self) -> None:
        if self._busy:
            return
        if self.step >= 3:
            self.accept()
            return
        if self._can_resume_next():
            target = self._back_from_step
            self._back_from_step = None
            self.step = int(target)
            self._error = ""
            self._render()
            return
        self._run_step_action()

    def _run_step_action(self) -> None:
        """跑当前步真实业务（导入 / 校正 / 导出）；会清掉「下一步」恢复态。"""
        if self._busy:
            return
        self._back_from_step = None
        self._error = ""
        if self.step == 0:
            self._do_import()
        elif self.step == 1:
            self._do_correct()
        elif self.step == 2:
            self._do_export()

    def _skip_wizard(self) -> None:
        """跳过 / 关闭：不完成任何一步，主窗口只记「已看过」。"""
        if self._busy:
            return
        self.reject()

    def skip(self) -> None:
        """测试与主窗口用的显式跳过。"""
        self._skip_wizard()

    def go_step(self, i: int) -> None:
        """直接定位到某一步（重看时不会重跑已完成的步骤）。"""
        if 0 <= i <= 3 and not self._busy:
            self.step = i
            self._render()

    # ---------------------------------------------------------------- 业务
    def _set_busy(self, busy: bool) -> None:
        """忙碌开关。

        短操作若立刻整页 ``_render``，进度条与提示块会一闪而过（观感像弹窗闪一下）。
        进入忙碌时先只锁主按钮；超过约 180ms 仍在忙才整页画出进度条。
        结束忙碌时取消延迟并交给调用方做最终 ``_render``（避免连闪两次）。
        """
        self._busy = busy
        if busy:
            if hasattr(self, "_primary") and self._primary is not None:
                self._primary.setEnabled(False)
                self._primary.setText(self._primary_text())
            if hasattr(self, "_prev") and self._prev is not None:
                self._prev.setVisible(False)
            if hasattr(self, "_skip") and self._skip is not None:
                self._skip.setVisible(False)
            self._busy_ui_timer.start()
        else:
            self._busy_ui_timer.stop()

    def _render_if_still_busy(self) -> None:
        if self._busy:
            self._render()

    def _do_import(self) -> None:
        """真实导入：文件选择对话框 → 导入模块同一汇合入口 → 等它跑完。"""
        if self.import_module is None:
            self._error = "导入功能没准备好，请重开窗口再试。"
            self._render()
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择要导入的书", "", FILE_FILTER)
        if not path:
            return                      # 用户在对话框里取消了：留在第 1 步
        mod = self.import_module
        self._set_busy(True)
        # M5-EX.3：take_file 即开跑，无需再代点「下一步 / 处理方式」
        mod.take_file(path)
        ok = self._pump(lambda: mod.has_finished() or mod.error_text(),
                        timeout_s=600)
        self._set_busy(False)
        if not ok or mod.error_text() or mod.result() is None:
            self._error = mod.error_text() or "这本书没能导入，换一个文件再试。"
            self._render()
            return
        self._import_result = mod.result()
        self.step = 1
        self._render()

    def _do_correct(self) -> None:
        if self.oneclick_module is None:
            self._error = "校正功能没准备好，请重开窗口再试。"
            self._render()
            return
        self._set_busy(True)
        self.oneclick_module.do_correction(confirm_cancel=True)
        self._set_busy(False)
        outcome = getattr(self.oneclick_module, "_outcome", None)
        summary = getattr(self.oneclick_module, "_summary", None)
        if outcome != "ok" or summary is None:
            self._error = ("已取消校正，本次没有留下半成品；随时可以再点一次开始。"
                           if outcome == "cancelled" else
                           "这次校正没跑完，可以再点一次开始校正。")
            self._render()
            return
        self._correction = summary
        self.step = 2
        self._render()

    def _do_export(self) -> None:
        if self.export_module is None:
            self._error = "导出功能没准备好，请重开窗口再试。"
            self._render()
            return
        mod = self.export_module
        self._set_busy(True)
        mod.export_now()
        ok = self._pump(lambda: not mod.is_busy() and mod.outcome is not None,
                        timeout_s=300)
        self._set_busy(False)
        outcome = mod.outcome
        if not ok or outcome is None or not outcome.ok:
            self._error = "这次导出没能完成，可以回到「导出结果」页看看提示。"
            self._render()
            return
        self._export = outcome
        self._export_path = str(outcome.main_file or "")
        self.step = 3
        self._render()
        self.exported.emit(self._export_path)

    # ---------------------------------------------------------------- 等待
    def _pump(self, cond, *, timeout_s: float, on_tick=None) -> bool:
        """在自己的事件循环里等一个条件成立（不阻塞界面的 sleep 忙等）。

        模态窗里也要能推进：外部（用户点击 / 验收脚本）仍在同一事件循环，
        所以这里只排队事件、每 50ms 查一次条件，超时就返回 False。
        """
        loop = QEventLoop()
        ok = {"v": False}
        timer = QTimer()
        timer.setInterval(50)

        def tick():
            if on_tick is not None:
                on_tick()
            self._sync_progress()
            if cond():
                ok["v"] = True
                loop.quit()

        timer.timeout.connect(tick)
        timer.start()
        guard = QTimer()
        guard.setSingleShot(True)
        guard.timeout.connect(loop.quit)
        guard.start(int(max(1.0, timeout_s) * 1000))
        loop.exec()
        timer.stop()
        guard.stop()
        return ok["v"]

    def _sync_progress(self) -> None:
        bar = getattr(self, "progress", None)
        if bar is None:
            return
        mod = self.import_module
        if self.step == 0 and mod is not None:
            src = getattr(mod, "bar", None)
            if src is not None and src.maximum() > 0:
                bar.setValue(int(src.value()))


# ---------------------------------------------------------------------------
# 便利入口（主窗口 / 测试共用）
# ---------------------------------------------------------------------------

def opens_on_first_run() -> bool:
    """是否还需要自动弹向导（第一次打开程序）。"""
    from fixtext_settings import AppSettings
    return AppSettings().value("wizardSeen", "0") != "1"


def mark_seen() -> None:
    from fixtext_settings import AppSettings
    s = AppSettings()
    s.setValue("wizardSeen", "1")
    s.sync()


__all__ = ["FirstRunWizard", "STEPS", "mark_seen", "opens_on_first_run"]
