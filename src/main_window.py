"""
FixText V1 · 主窗口骨架（PySide6 收敛版）
========================================

把 6 份 HTML 原型各自重复的 chrome（顶栏 / 左轨 / 视图切换）收敛为**单一**
MainWindow + QStackedWidget。这是「Qt 交付阶段」的第一步（见决策文档待办）。

- 共享样式来自 `fixtext.qss`（由 `build_qss.py` 从 `fixtext_tokens.py` 生成）。
- 导航模型：左侧常驻 6 入口轨 + 内容区；「首页概览」降级为内容区首页。
- 默认进入首页概览；点击左轨入口或首页卡片切到对应模块，chrome 不变。
- 已移植真实模块页：导入书籍、检查问题、一键校正、导出结果、历史记录；
  词库管理仍为占位页（含范围说明 + HTML 原型指向 + 设计依据），内容逐步移植，架构已贯通。
  注：词库管理模块待移植时须先补「新增词条」功能规划，再动手（原排期漏项）。

运行：
    python main_window.py
（依赖：pip install PySide6；共享样式 fixtext.qss 需与本文件同目录）
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QPushButton, QLabel, QStackedWidget, QFrame, QScrollArea, QGroupBox,
)

from fixtext_tokens import MODULES, MODULE_PROTO, c, sp, r, fs
from check_module import CheckModule
from import_module import ImportModule
from oneclick_module import OneClickModule
from export_module import ExportModule
from history_module import HistoryModule

HERE = os.path.dirname(os.path.abspath(__file__))
QSS_PATH = os.path.join(HERE, "fixtext.qss")

# 首页概览卡片用的短描述（与薄地基「主窗口框架」6 卡一致）
MODULE_SHORT = {
    "import":  "拖放或选择 TXT / EPUB，自动识别编码并转 UTF-8",
    "oneclick": "默认配置执行排版 + 替换 + 标点，可取消",
    "check":   "引号配对检查与逐处交互修复",
    "vocab":   "检索 / 查重 / 删除 / 合并 + 安全底线",
    "export":  "导出干净 TXT / EPUB，附替换报告",
    "history": "任务列表、快照恢复、重新导出",
}

# 模块键 → 说明（占位页副标题 + 设计依据，内容后续从 HTML 原型移植）
MODULE_DESC = {
    "import":  ("拖放 / 文件选择双通道；编码识别到人话；3 步导入向导；"
                "导入安全（复制到工作区、不改原文件、字节对照校验）；进度+可取消+自动快照。",
                "文档 §2.7.3 / §2.2（导入书籍）：编码自动转 UTF-8、EPUB 导入方式、章节预览只读、"
                "安全基线（不改原文件 + 字节校验）。"),
    "oneclick":("默认配置执行 排版+替换+标点；可取消；展开「排版规范化（可选）」与「高级选项」。"
                "低分辨率下内容内部滚动，不裁切。",
                "文档 §2.7.1 / §2.7.2 / §2.2（一键校正）：默认即跑、可中途取消、处理前自动快照、"
                "排版 14 项与高级选项。"),
    "check":   ("只统计不修复 / 结束检查（二次确认）；自动检查清单 + 问题清单（点击定位）；"
                "右栏编辑器（保存并下一处）；操作条（下一处/修复/跳过/撤销）；7 条规则开关；批量操作。",
                "文档 §2.7.4 / §2.2（检查问题）：逐处人工确认、引号配对检查、"
                "批量操作二次确认 + 预览影响条数。"),
    "vocab":   ("检索 / 查重 / 删除 / 合并 + 5 条安全底线；首屏一级入口，视觉权重与其他 5 个并列。",
                "文档 §2.4（词库管理提拔为首屏一级）/ §2.2 入口④（检索、查重、删除、合并、安全底线）。"),
    "export":  ("导出目标（干净 TXT / EPUB 还原）；章节分级修正；自动附替换报告（CSV/文本，无差异则跳过）；"
                "报告统计只读展示；进度 + 完成提示。报告 GUI 对比视图属 V1.1。",
                "文档 §2.7.7 / §2.2（导出结果）：报告文件留存（非 GUI 对比）、"
                "无差异则跳过并说明、章节标题分级修正。"),
    "history": ("任务列表（书名/时间/替换数）；快照恢复（任一快照完整恢复现场）；重新导出；"
                "单条删除可撤销、清理全部不可恢复（均二次确认）；跨会话保留；基准同步失败留痕。",
                "文档 §2.7.8 / §2.2（历史记录）：快照恢复、重新导出、"
                "显式删除 + 二次确认、同步失败状态标记。"),
}


class RailItem(QPushButton):
    """左轨导航项。active 属性驱动高亮（见 fixtext.qss 的 #RailItem[active]）。"""

    def __init__(self, key: str, icon: str, label: str):
        super().__init__(f"{icon}  {label}")
        self.key = key
        self.setObjectName("RailItem")
        self.setProperty("active", "false")
        self.setMinimumHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_active(self, on: bool):
        self.setProperty("active", "true" if on else "false")
        # 属性变更后刷新样式（QSS 选择器依赖属性）
        self.style().unpolish(self)
        self.style().polish(self)


class OverviewCard(QFrame):
    """首页概览的 6 入口卡片。点击时发出 entered(key)，由上层接线跳转。"""

    entered = Signal(str)

    def __init__(self, key: str, icon: str, label: str, desc: str):
        super().__init__()
        self.setObjectName("Card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.key = key

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(6)

        top = QHBoxLayout()
        ico = QLabel(icon)
        ico.setFont(QFont("", 22))
        title = QLabel(label)
        title.setFont(QFont("", int(fs("lg").replace("px", "")), QFont.Weight.Bold))
        title.setStyleSheet(f"color:{c('neutral.900')}")
        top.addWidget(ico)
        top.addWidget(title)
        top.addStretch(1)
        layout.addLayout(top)

        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('sm')}")
        layout.addWidget(d)

    def mousePressEvent(self, event):
        self.entered.emit(self.key)
        super().mousePressEvent(event)


class ModulePlaceholder(QWidget):
    """模块占位页：展示标题、范围说明、对应的 HTML 原型文件名、设计依据。"""

    def __init__(self, key: str, label: str):
        super().__init__()
        self.key = key
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(int(sp("4").replace("px", "")))

        # 页头
        head = QWidget()
        head.setObjectName("PageHead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        title = QLabel(label)
        title.setFont(QFont("", int(fs("2xl").replace("px", "")), QFont.Weight.Bold))
        hl.addWidget(title)
        desc, basis = MODULE_DESC.get(key, ("（待移植）", "（待补充）"))
        sub = QLabel("该模块完整交互原型已存在于下方 HTML 文件；此处为 Qt 收敛骨架，内容将逐步移植。")
        sub.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('md')}")
        hl.addWidget(sub)
        layout.addWidget(head)

        # 说明卡片
        card = QFrame()
        card.setObjectName("Card")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.setSpacing(8)

        scope = QLabel("范围说明")
        scope.setFont(QFont("", int(fs("lg").replace("px", "")), QFont.Weight.DemiBold))
        scope.setStyleSheet(f"color:{c('neutral.800')}")
        cl.addWidget(scope)
        ds = QLabel(desc)
        ds.setWordWrap(True)
        ds.setStyleSheet(f"color:{c('neutral.700')}")
        cl.addWidget(ds)

        proto = QLabel(f"完整交互原型：<b>{MODULE_PROTO.get(key, '—')}</b>")
        proto.setStyleSheet(f"color:{c('primary.600')}")
        cl.addWidget(proto)
        layout.addWidget(card)

        # 设计依据折叠
        gb = QGroupBox("显示设计依据")
        gl = QVBoxLayout(gb)
        gl.setContentsMargins(12, 18, 12, 12)
        b = QLabel(basis)
        b.setWordWrap(True)
        b.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('sm')}")
        gl.addWidget(b)
        layout.addWidget(gb)

        layout.addStretch(1)


class HomeOverview(QWidget):
    """首页概览：6 入口卡片网格，点击进入模块。"""

    def __init__(self, on_enter=None):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(int(sp("4").replace("px", "")))

        head = QWidget()
        head.setObjectName("PageHead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        t = QLabel("首页概览")
        t.setFont(QFont("", int(fs("2xl").replace("px", "")), QFont.Weight.Bold))
        t.setStyleSheet(f"color:{c('neutral.900')}")
        s = QLabel("把书拖进来，或选一个入口开始。六个入口等权，词库管理为首屏一级。")
        s.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('md')}")
        hl.addWidget(t)
        hl.addWidget(s)
        layout.addWidget(head)

        grid = QGridLayout()
        grid.setSpacing(int(sp("4").replace("px", "")))
        modules = [m for m in MODULES if m[0] != "home"]
        positions = [(i // 3, i % 3) for i in range(len(modules))]
        for (key, icon, label), (row, col) in zip(modules, positions):
            desc = MODULE_SHORT.get(key, "")
            card = OverviewCard(key, icon, label, desc)
            if on_enter:
                card.entered.connect(on_enter)
            grid.addWidget(card, row, col)
        layout.addLayout(grid)
        layout.addStretch(1)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FixText V1")
        self.resize(1180, 760)

        # 中央部件
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 顶栏 ----
        top = QWidget()
        top.setObjectName("TopBar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 0, 12, 0)
        brand = QPushButton("F  FixText")
        brand.setObjectName("Brand")
        brand.setCursor(Qt.CursorShape.PointingHandCursor)
        brand.clicked.connect(lambda: self.go("home"))
        tl.addWidget(brand)
        tl.addStretch(1)
        for glyph in ("⚙", "?", "☰"):
            act = QPushButton(glyph)
            act.setObjectName("TopAct")
            act.setCursor(Qt.CursorShape.PointingHandCursor)
            act.clicked.connect(lambda _checked, g=glyph: self._top_action(g))
            tl.addWidget(act)
        root.addWidget(top)

        # ---- 左轨 + 内容 ----
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        rail = QWidget()
        rail.setObjectName("Rail")
        rail.setFixedWidth(212)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(8, 12, 8, 12)
        rl.setSpacing(2)
        rtitle = QLabel("功能导航")
        rtitle.setObjectName("RailTitle")
        rl.addWidget(rtitle)
        self.rail_items = {}
        for key, icon, label in MODULES:
            item = RailItem(key, icon, label)
            item.clicked.connect(lambda _checked, k=key: self.go(k))
            self.rail_items[key] = item
            rl.addWidget(item)
        rl.addStretch(1)
        body.addWidget(rail)

        # ---- 堆叠内容 ----
        self.stack = QStackedWidget()
        self.stack.setObjectName("Content")
        self.pages = {}
        self.pages["home"] = self._wrap(HomeOverview(on_enter=lambda k: self.go(k)))
        for key, _icon, label in MODULES:
            if key == "home":
                continue
            # 已移植真实模块页：检查问题 / 导入书籍 / 一键校正 / 导出结果 / 历史记录；
            # 词库管理仍为占位页（待补「新增词条」规划后移植）。
            if key == "check":
                page = CheckModule()
            elif key == "import":
                page = ImportModule()
            elif key == "oneclick":
                page = OneClickModule()
            elif key == "export":
                page = ExportModule()
            elif key == "history":
                page = HistoryModule()
            else:
                page = ModulePlaceholder(key, label)
            self.pages[key] = self._wrap(page)
            self.stack.addWidget(self.pages[key])
        self.stack.addWidget(self.pages["home"])
        body.addWidget(self.stack, 1)

        root.addLayout(body)

        # 默认进入首页概览
        self.go("home")

    def _wrap(self, widget: QWidget) -> QScrollArea:
        """把页面装进滚动区（低分辨率下内容内部滚动，对应 HTML 的 min-height:0 修复）。"""
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        # 内容为流式宽度（标签换行 + 卡片网格），不需要横向滚动
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(20, 20, 20, 20)
        il.setSpacing(16)
        il.addWidget(widget)
        il.addStretch(1)
        sa.setWidget(inner)
        return sa

    def go(self, key: str):
        """切换到指定模块页，并更新左轨高亮。"""
        if key not in self.pages:
            key = "home"
        self.stack.setCurrentWidget(self.pages[key])
        for k, item in self.rail_items.items():
            item.set_active(k == key)

    def _top_action(self, glyph: str):
        """顶栏动作（设置 ⚙ / 帮助 ? / 菜单 ☰）占位。

        骨架阶段仅占位，真实行为后续接入：
          设置 → 配置面板；帮助 → 帮助文档；菜单 → 模块切换 / 关于。
        """
        # TODO: 接入各动作的真实行为
        pass


def main():
    app = QApplication(sys.argv)
    if os.path.exists(QSS_PATH):
        with open(QSS_PATH, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
