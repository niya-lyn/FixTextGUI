"""
FixText V1 · 首次使用向导（T4.3 · P0 五项底线之一）
=================================================

纯流程壳：三步演示「导入 → 处理 → 导出」，附带示例书，可跳过、可重看。
本向导**不接入真实逻辑**（导入 / 一键校正 / 导出 的后端由对应模块负责），
只负责把工作流讲清楚、把示例书指出来、让用户第一次打开就知道怎么走。

设计约束（与全工程一致）：
- 只消费 `fixtext_tokens.py` 的令牌，不硬编码颜色 / 尺寸字面值。
- 内联 QSS 用精确 `#ObjectName` 选择器（避免裸 `QFrame{}` 误伤子 QLabel）。
- 条款号（§）不进向导常态文案（首-run 向导是「藏内部概念」最前线的页面）。
- 步骤指示条自含，不依赖 import_module.WizardSteps（保持新文件独立、零改动现有模块）。

触发 / 重看由 `main_window.py` 负责：
- 首启（QSettings 无 wizardSeen）→ 自动弹出；
- ☰ 菜单「新手向导（重新观看）」→ 随时再看。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)

from fixtext_tokens import c, sp, r, fs, FONT_WEIGHT
from fixtext_widgets import hline


# ---------------------------------------------------------------------------
# 静态内容（与导入 / 处理 / 导出 原型同源；示例书取自 import_module.SAMPLES）
# ---------------------------------------------------------------------------

SAMPLE = {
    "name": "示例书.epub",
    "size": "4.4 MB",
    "enc": "UTF-8",
    "encHint": "已是 UTF-8，无需转换",
}

STEPS = [
    ("📥", "导入", "把书放进 FixText"),
    ("⚡", "处理", "一键校正 + 检查问题"),
    ("📤", "导出", "导出干净电子书"),
]

STEP_BODY = [
    {
        "bullets": [
            "拖放或选择 TXT / EPUB；也可以直接用我们附带的示例书。",
            "编码自动识别并转为 UTF-8，全程人话提示，不弹命令行窗口。",
            "导入即复制到工作区，原文件保持只读——随时能回到这一刻。",
        ],
        "sample": f"已附带示例书：{SAMPLE['name']}（TXT 书也能导入，编码自动识别）",
    },
    {
        "bullets": [
            "一键校正：默认配置直接跑排版 + 替换 + 标点，可中途取消。",
            "检查问题：引号配对等逐处人工确认，想修哪里点哪里。",
            "词库管理：检索 / 查重 / 合并，所有改动可撤销、自动留快照。",
        ],
        "sample": f"示例书{SAMPLE['name']}会在这里被排版、标点规范化。",
    },
    {
        "bullets": [
            "导出干净 TXT，或把 EPUB 还原回去直接用阅读器打开。",
            "每次自动附替换报告（表格 / 文本），无差异则跳过并说明。",
            "任务自动记入历史记录，任一快照都能一键恢复现场。",
        ],
        "sample": f"处理完的{SAMPLE['name']}就能导出成干净的电子书了。",
    },
]


# ---------------------------------------------------------------------------
# 步骤指示条（自含，不依赖 import_module）
# ---------------------------------------------------------------------------

def _clear_layout(layout) -> None:
    """递归清空一个布局：控件解父子后 deleteLater，子布局同样递归。

    只按 `item.widget()` 清是不够的——`_render_step` 里的「步骤标题行」是
    `addLayout(hl)` 进去的**嵌套布局**，`item.widget()` 对它返回 None，
    于是旧标题的 `QLabel` 一路留着，翻页后新标题直接盖在旧标题上
    （实测截图里出现过「第 2 步 · 处理」和「第 1 步 · 导入」叠字）。
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
        spacer = item.spacerItem()
        if spacer is not None:
            del spacer


class _StepBar(QWidget):
    """水平步骤指示：已完成=绿、当前=主色、未到=中性，节点间连线同步着色。"""

    def __init__(self, icons, names, parent=None):
        super().__init__(parent)
        self._icons = icons
        self._names = names
        self._nodes = []
        self._lines = []
        self._built = False
        self.set_steps(0)

    def set_steps(self, current: int):
        if not self._built:
            self._build_once()
        for i, node in enumerate(self._nodes):
            done = i < current
            active = i == current
            self._style_node(node, done, active)
            if i < len(self._lines):
                self._lines[i].setStyleSheet(
                    f"background:{c('success') if done else c('neutral.200')};"
                    f"border:none")

    def _build_once(self):
        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        hl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        n = len(self._names)
        for i in range(n):
            node = QWidget()
            nl = QHBoxLayout(node)
            nl.setContentsMargins(0, 0, 0, 0)
            nl.setSpacing(8)
            nl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot = QLabel(self._icons[i])
            dot.setFixedSize(34, 34)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab = QLabel(self._names[i])
            nl.addWidget(dot)
            nl.addWidget(lab)
            node._dot = dot
            node._lab = lab
            self._nodes.append(node)
            hl.addWidget(node)
            if i < n - 1:
                line = QFrame()
                line.setFixedSize(44, 2)
                line.setStyleSheet(f"background:{c('neutral.200')};border:none")
                self._lines.append(line)
                hl.addWidget(line)
        self._built = True

    def _style_node(self, node, done: bool, active: bool):
        dot, lab = node._dot, node._lab
        if done:
            dot.setStyleSheet(
                f"background:{c('success')};color:#fff;border-radius:999px;"
                f"font-size:16px")
            lab.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('sm')}")
        elif active:
            dot.setStyleSheet(
                f"background:{c('primary.500')};color:#fff;border-radius:999px;"
                f"font-size:16px")
            lab.setStyleSheet(
                f"color:{c('primary.700')};font-weight:700;font-size:{fs('sm')}")
        else:
            dot.setStyleSheet(
                f"background:{c('neutral.100')};color:{c('neutral.500')};"
                f"border-radius:999px;font-size:16px")
            lab.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('sm')}")


# ---------------------------------------------------------------------------
# 向导对话框
# ---------------------------------------------------------------------------

class FirstRunWizard(QDialog):
    """首次使用向导：三步演示 + 示例书 + 跳过 / 重看。

    - 完成（「开始使用」accept）后由主窗口跳到「导入书籍」页；
    - 跳过 / 关闭（reject）后停留在首页，但同样标记为已看过。
    任何关闭方式都算「已看过」，重新观看走 ☰ 菜单。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新手向导 · FixText V1")
        self.setModal(True)
        self.setMinimumWidth(660)
        self.step = 0
        self._build()

    # ------------------------------------------------------------------ 构建
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._head())
        root.addWidget(self._body_panel())
        root.addWidget(self._foot())

    def _head(self) -> QWidget:
        head = QWidget()
        head.setObjectName("ModalHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(20, 18, 20, 18)
        ico = QLabel("👋")
        ico.setFixedSize(34, 34)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background:{c('primary.100')};color:{c('primary.700')};"
            f"border-radius:9px;font-size:18px")
        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel("欢迎使用 FixText V1")
        t.setStyleSheet(
            f"font-weight:700;font-size:{fs('lg')};color:{c('neutral.900')}")
        s = QLabel(
            f"用示例书 {SAMPLE['name']} 带你跑通 导入 → 处理 → 导出。"
            "约 30 秒，看完就能上手。")
        s.setWordWrap(True)
        s.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('sm')}")
        col.addWidget(t)
        col.addWidget(s)
        hl.addWidget(ico)
        hl.addLayout(col, 1)
        hl.addStretch(0)
        return head

    def _body_panel(self) -> QWidget:
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 18, 20, 18)
        bl.setSpacing(16)

        self.step_bar = _StepBar(
            [s[0] for s in STEPS], [s[1] for s in STEPS])
        bl.addWidget(self.step_bar)

        self.panel = QWidget()
        self.panel.setObjectName("WizardPanel")
        self.panel.setStyleSheet(
            f"QWidget#WizardPanel{{background:{c('neutral.0')};"
            f"border:1px solid {c('neutral.200')};border-radius:{r('lg')}}}"
        )
        self.panel_l = QVBoxLayout(self.panel)
        self.panel_l.setContentsMargins(24, 22, 24, 22)
        self.panel_l.setSpacing(0)
        bl.addWidget(self.panel, 1)

        self._render_step()
        return body

    def _render_step(self):
        # 清空面板（递归清，避免重渲染叠加）
        _clear_layout(self.panel_l)

        icon, name, tagline = STEPS[self.step]
        data = STEP_BODY[self.step]

        # 步骤标题行
        hl = QHBoxLayout()
        hl.setSpacing(12)
        ico = QLabel(icon)
        ico.setFixedSize(44, 44)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background:{c('primary.100')};color:{c('primary.700')};"
            f"border-radius:12px;font-size:22px")
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(f"第 {self.step + 1} 步 · {name}")
        t.setStyleSheet(
            f"font-weight:700;font-size:{fs('xl')};color:{c('neutral.900')}")
        sub = QLabel(tagline)
        sub.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('sm')}")
        col.addWidget(t)
        col.addWidget(sub)
        hl.addWidget(ico)
        hl.addLayout(col, 1)
        self.panel_l.addLayout(hl)

        self.panel_l.addSpacing(14)
        self.panel_l.addWidget(hline())

        # 要点列表
        for b in data["bullets"]:
            self.panel_l.addSpacing(10)
            self.panel_l.addWidget(self._bullet(b))

        # 示例书提示条
        self.panel_l.addSpacing(16)
        note = QLabel("📎 " + data["sample"])
        note.setWordWrap(True)
        note.setStyleSheet(
            f"background:{c('info.bg')};border:1px solid {c('info.border')};"
            f"color:{c('info')};border-radius:{r('md')};padding:10px 14px;"
            f"font-size:{fs('sm')}")
        self.panel_l.addWidget(note)

        self.panel_l.addStretch(1)

    def _bullet(self, text: str) -> QWidget:
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        dot = QLabel("●")
        dot.setFixedSize(16, 16)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setStyleSheet(f"color:{c('primary.500')};font-size:10px")
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet(
            f"color:{c('neutral.700')};font-size:{fs('sm')};line-height:1.6")
        hl.addWidget(dot)
        hl.addWidget(lab, 1)
        return w

    # ------------------------------------------------------------------ 底部
    def _foot(self) -> QWidget:
        foot = QWidget()
        foot.setObjectName("ModalFoot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(20, 14, 20, 14)

        skip = QPushButton("跳过")
        skip.setObjectName("BtnGhost")
        skip.setCursor(Qt.CursorShape.PointingHandCursor)
        skip.clicked.connect(self.reject)  # 跳过 = 不向导，标记已看过（主窗口处理）
        fl.addWidget(skip)

        fl.addStretch(1)

        self._prev = QPushButton("上一步")
        self._prev.setObjectName("BtnOutline")
        self._prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev.clicked.connect(self._go_prev)
        fl.addWidget(self._prev)

        self._next = QPushButton("下一步")
        self._next.setObjectName("BtnPrimary")
        self._next.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next.clicked.connect(self._go_next)
        fl.addWidget(self._next)

        self._sync_foot()
        return foot

    def _sync_foot(self):
        self._prev.setEnabled(self.step > 0)
        last = self.step >= len(STEPS) - 1
        self._next.setText("开始使用" if last else "下一步")

    # ------------------------------------------------------------------ 导航
    def _go_prev(self):
        if self.step > 0:
            self.step -= 1
            self._refresh()

    def _go_next(self):
        if self.step >= len(STEPS) - 1:
            self.accept()  # 完成 → 主窗口跳到导入页
            return
        self.step += 1
        self._refresh()

    def _refresh(self):
        self.step_bar.set_steps(self.step)
        self._render_step()
        self._sync_foot()

    # 供冒烟测试直接驱动（不依赖 exec 阻塞）
    def go_step(self, i: int):
        if 0 <= i < len(STEPS):
            self.step = i
            self._refresh()
