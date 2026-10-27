"""
FixText V1 · 主窗口与六入口路由（M2-T2.5 四卡集成）
=====================================================

本文件是 M2 的**唯一**主程序外壳：T2.1 的顶栏 + 六入口左轨 + 内容区路由为基座，
把 T2.2 导入模块、T2.3 worker/进度/取消链路、T2.4 人话错误体系接在同一份
chrome 上。合并口径如下：

| 来源 | 在本文件里的落点 |
|---|---|
| T2.1 主窗口基座 | `MainWindow`：顶栏 / 左轨 / 内容区 / 路由 / 快捷键 / 面板保状态 |
| T2.2 导入模块 | `mount_import()` → `pages["import"]` 内嵌 `ImportModule` |
| T2.3 一键校正 | `mount_oneclick()` → `pages["oneclick"]` 内嵌 `OneClickModule`（真链路） |
| T2.3 检查问题 | `pages["check"]` → `CheckModule`（T2.3 修订版，修 `QFrame{}` 样式泄漏） |
| T2.4 错误中心 | 启动时 `init/install_app_hooks/set_dialog_host`；各页错误出口 `@guard`；
设置页「打开诊断日志目录」按钮 |

**已知集成偏差的修复**（本卡验收③）：
1. 常量统一：令牌唯一来源是 `fixtext_tokens.ENTRIES`；全包不再出现 `MODULES`，
   `host_window.py` 只剩转发，不存在两版常量并存导致的 ImportError。
2. 入口状态：导入 / 一键校正已接真链路，令牌里 `status="ready"`，
   左轨与首页概览都不再挂「建设中」徽标。
3. 封面页：EPUB 章节预览把零字首页标成「封面」（不是「第 1 章 未命名章节」）。

设计约束（沿用 T2.1 验收基线）：六入口常驻可达、路由不重建窗口、切走切回保状态、
界面零内部术语、令牌与设计地基一致。

运行：
    python main_app.py          （推荐入口，含错误中心接线）
或  python main_window.py       （仅窗口，错误中心用默认诊断目录）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QPushButton, QLabel, QStackedWidget, QFrame, QScrollArea,
    QMessageBox, QDialog, QSizePolicy,
)

from fixtext_tokens import (
    APP_TITLE, APP_NAME, ENTRIES, ENTRY_BY_KEY, HOME_KEY, RAIL_WIDTH,
    READY_KEYS, STATUS_TEXT, WINDOW_H, WINDOW_MIN_H, WINDOW_MIN_W, WINDOW_W,
    c, sp, r, fs, px, FONT_WEIGHT,
)
from fixtext_widgets import Card, Pill, hline
from check_module import CheckModule

HERE = os.path.dirname(os.path.abspath(__file__))
QSS_PATH = os.path.join(HERE, "fixtext.qss")
PKG_ROOT = Path(HERE).resolve().parent

#: 人话错误体系（T2.4）。缺包时降级：界面照常可用，只是没有错误卡与诊断日志。
try:
    import fixtext_error_center as error_center
except Exception:                                    # pragma: no cover
    error_center = None


# ---------------------------------------------------------------------------
# 左轨导航项
# ---------------------------------------------------------------------------

class RailItem(QPushButton):
    """左轨入口项：图标方块 + 名称 + （建设中）标记。

    active 属性驱动选中态（见 fixtext.qss 的 #RailItem[active="true"]）。
    用 QPushButton 承载，天然可 Tab 聚焦、可回车/空格触发，不是只能鼠标点的 QLabel。
    """

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self.key = entry["key"]
        self.setObjectName("RailItem")
        self.setProperty("active", "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(entry["label"])
        self.setMinimumHeight(40)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(10)

        self.ico = QLabel(entry["icon"])
        self.ico.setObjectName("RailIco")
        self.ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ico.setFixedSize(24, 24)
        row.addWidget(self.ico)

        self.text = QLabel(entry["label"])
        self.text.setObjectName("RailLabel")
        row.addWidget(self.text)

        self.tag = None
        if entry["status"] != "ready":
            self.tag = QLabel(STATUS_TEXT["building"])
            self.tag.setObjectName("RailTag")
            row.addStretch(1)
            row.addWidget(self.tag)
        else:
            row.addStretch(1)

        self._apply(False)

    def _apply(self, on: bool):
        """按选中态调整文字与图标配色（不依赖 QSS 祖先伪状态，跨平台稳定）。"""
        self.setProperty("active", "true" if on else "false")
        lab_color = c("primary.700") if on else c("neutral.600")
        self.text.setStyleSheet(
            f"color:{lab_color};font-size:{fs('base')};"
            f"font-weight:{FONT_WEIGHT['semibold'] if on else FONT_WEIGHT['medium']}"
        )
        self.ico.setStyleSheet(
            f"background:{c('neutral.0') if on else c('neutral.100')};"
            f"border-radius:7px;font-size:13px;color:{lab_color}"
        )
        self.style().unpolish(self)
        self.style().polish(self)

    def set_active(self, on: bool):
        self._apply(bool(on))


# ---------------------------------------------------------------------------
# 首页概览
# ---------------------------------------------------------------------------

class OverviewCard(QFrame):
    """首页概览的入口卡。点击发 entered(key)，由上层接线跳转（不耦合窗口）。"""

    entered = Signal(str)

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("OverviewCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.key = entry["key"]
        self.setAccessibleName(entry["label"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(10)
        ico = QLabel(entry["icon"])
        ico.setObjectName("OvfIco")
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setFixedSize(30, 30)
        top.addWidget(ico)

        title = QLabel(entry["label"])
        title.setStyleSheet(
            f"color:{c('neutral.900')};font-size:{fs('lg')};"
            f"font-weight:{FONT_WEIGHT['bold']}"
        )
        top.addWidget(title)
        top.addStretch(1)

        kind = "ok" if entry["status"] == "ready" else "warn"
        top.addWidget(Pill(STATUS_TEXT[entry["status"]], kind))
        layout.addLayout(top)

        desc = QLabel(entry["short"])
        desc.setWordWrap(True)
        desc.setMinimumHeight(40)
        desc.setStyleSheet(
            f"color:{c('neutral.600')};font-size:{fs('sm')}"
        )
        layout.addWidget(desc)

        hint = QLabel("点开看看 →")
        hint.setStyleSheet(
            f"color:{c('primary.600')};font-size:{fs('xs')};"
            f"font-weight:{FONT_WEIGHT['semibold']}"
        )
        layout.addWidget(hint)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.entered.emit(self.key)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.entered.emit(self.key)
            return
        super().keyPressEvent(event)


class HomeOverview(QWidget):
    """首页概览：六个入口的卡片网格，点卡片即进模块。"""

    def __init__(self, on_enter=None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(px(sp("4")))

        head = QWidget()
        head.setObjectName("PageHead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)

        title = QLabel("首页概览")
        title.setObjectName("PageTitle")
        hl.addWidget(title)

        sub = QLabel(
            "把书导入进来，然后一键校正；想逐处确认引号，就去「检查问题」。"
            "六个入口随时都在左边，点一下就能过去。"
        )
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        hl.addWidget(sub)
        layout.addWidget(head)

        grid = QGridLayout()
        grid.setSpacing(px(sp("4")))
        for i, entry in enumerate(ENTRIES):
            card = OverviewCard(entry)
            card.setMinimumHeight(132)
            if on_enter:
                card.entered.connect(on_enter)
            grid.addWidget(card, i // 3, i % 3)
        layout.addLayout(grid)

        foot = QLabel(
            "现在能直接用的入口标着「可用」，其余标着「建设中」——"
            "点进去会告诉你它做好之后能做什么，不会点了个寂寞。"
        )
        foot.setWordWrap(True)
        foot.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('xs')}")
        layout.addWidget(foot)
        layout.addStretch(1)


# ---------------------------------------------------------------------------
# 建设中占位页
# ---------------------------------------------------------------------------

class BuildingPage(QWidget):
    """未完成入口的占位页：人话说明它将来做什么 + 现在能先去哪。"""

    action_requested = Signal(str)

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.key = entry["key"]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(px(sp("4")))

        # 页头
        head = QWidget()
        head.setObjectName("PageHead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)

        trow = QHBoxLayout()
        trow.setSpacing(10)
        title = QLabel(entry["label"])
        title.setObjectName("PageTitle")
        trow.addWidget(title)
        trow.addWidget(Pill(STATUS_TEXT["building"], "warn"))
        trow.addStretch(1)
        hl.addLayout(trow)

        sub = QLabel(entry["short"])
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        hl.addWidget(sub)
        layout.addWidget(head)

        # 建设中说明
        note = Card("这个入口还在建设中")
        note.body_l.setSpacing(10)
        lead = QLabel(
            f"「{entry['label']}」的界面还没做完，所以现在点开还看不到可以操作的内容。"
            "它不是坏了，也不是点不动——等它做好，你在这里能做的事是："
        )
        lead.setWordWrap(True)
        lead.setStyleSheet(
            f"color:{c('neutral.700')};font-size:{fs('base')}"
        )
        note.body_l.addWidget(lead)

        for line in entry["what"]:
            item = QHBoxLayout()
            item.setSpacing(8)
            dot = QLabel("·")
            dot.setStyleSheet(
                f"color:{c('primary.500')};font-size:{fs('lg')};"
                f"font-weight:{FONT_WEIGHT['bold']}"
            )
            dot.setFixedWidth(10)
            item.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            lab = QLabel(line)
            lab.setWordWrap(True)
            lab.setStyleSheet(f"color:{c('neutral.700')};font-size:{fs('base')}")
            item.addWidget(lab, 1)
            note.body_l.addLayout(item)
        layout.addWidget(note)

        # 现在先去哪
        ready = [ENTRY_BY_KEY[k] for k in READY_KEYS]
        if ready:
            go_card = Card("现在可以先去这里")
            go_card.body_l.setSpacing(10)
            txt = QLabel(
                "在等这些入口做完的这段时间，点下面这个按钮就能先用起来："
                if len(ready) == 1 else
                "在等这些入口做完的这段时间，下面这些已经能用了："
            )
            txt.setWordWrap(True)
            txt.setStyleSheet(f"color:{c('neutral.700')};font-size:{fs('base')}")
            go_card.body_l.addWidget(txt)
            row = QHBoxLayout()
            row.setSpacing(10)
            for e in ready:
                btn = QPushButton(f"{e['icon']}  去用「{e['label']}」")
                btn.setObjectName("BtnPrimary")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(
                    lambda _=False, k=e["key"]: self.action_requested.emit(k)
                )
                row.addWidget(btn)
            row.addStretch(1)
            go_card.body_l.addLayout(row)
            layout.addWidget(go_card)

        layout.addStretch(1)


# ---------------------------------------------------------------------------
# 顶栏动作的小对话框（保证点了有反应，不留死按钮）
# ---------------------------------------------------------------------------

def _dialog(parent, title: str, lines: list[str]):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Information)
    head, *rest = lines
    box.setText(head)
    if rest:
        box.setInformativeText("\n".join(rest))
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.button(QMessageBox.StandardButton.Ok).setText("知道了")
    box.exec()


# ---------------------------------------------------------------------------
# 设置对话框（含「打开诊断日志目录」——T2.4 的 open_log_dir）
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    """设置面板（M2 阶段只做已落地的项：诊断日志目录）。

    没有可选项时装样子不如不装：这里只放真实可用的动作，并用一句话说明
    其余设置项为什么现在没有（由软件按默认方式处理，不影响正常使用）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setObjectName("SettingsDialog")
        self.setMinimumWidth(520)
        self._toast = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(px(sp("3")))

        title = QLabel("设置")
        title.setStyleSheet(
            f"color:{c('neutral.900')};font-size:{fs('lg')};"
            f"font-weight:{FONT_WEIGHT['bold']}"
        )
        root.addWidget(title)

        sub = QLabel(
            "现在能调的就下面这一项。校正用的词库、进度提示这些由软件按默认方式处理，"
            "不影响正常使用。"
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('sm')}")
        root.addWidget(sub)

        card = Card("诊断日志", "出问题时把这里的文件发给技术支持，能定位得更快")
        self.log_hint = QLabel(self._log_hint_text())
        self.log_hint.setWordWrap(True)
        self.log_hint.setStyleSheet(
            f"color:{c('neutral.700')};font-size:{fs('sm')}"
        )
        card.body_l.addWidget(self.log_hint)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.open_btn = QPushButton("打开诊断日志目录")
        self.open_btn.setObjectName("BtnOutline")
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.clicked.connect(self.open_log_dir)
        row.addWidget(self.open_btn)
        row.addStretch(1)
        card.body_l.addLayout(row)

        self.feedback = QLabel("")
        self.feedback.setWordWrap(True)
        self.feedback.setVisible(False)
        card.body_l.addWidget(self.feedback)
        root.addWidget(card)

        root.addStretch(1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("BtnSecondary")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        foot.addWidget(close_btn)
        root.addLayout(foot)

    # -- 日志目录状态 --------------------------------------------------
    def _log_hint_text(self) -> str:
        if error_center is None:
            return "诊断日志功能没有装好，这一项暂时用不了；不影响正常使用。"
        try:
            where = error_center.log_dir()
        except Exception:
            return "诊断日志目录还没准备好，第一次出错的时候会自动建好。"
        return f"诊断日志存在这台电脑的这个位置：{where}"

    def open_log_dir(self):
        """打开诊断日志目录（T2.4 qt_bridge.open_log_dir）。"""
        self.feedback.setVisible(False)
        if error_center is None:
            self._say("诊断日志功能没有装好，这一项暂时用不了。", "warn")
            return
        try:
            from fixtext_error_center.qt_bridge import open_log_dir
        except Exception:
            self._say("诊断日志功能没有装好，这一项暂时用不了。", "warn")
            return
        ok = False
        try:
            ok = bool(open_log_dir())
        except Exception:
            ok = False
        if ok:
            self._say("已经在文件管理器里打开诊断日志目录。", "ok")
        else:
            self._say(
                "没能自动打开文件夹。你可以照着上面那行位置自己找过去。", "warn")

    def _say(self, text: str, kind: str):
        palette = {
            "warn": ("warning.bg", "warning", "neutral.200"),
            "ok": ("success.bg", "success", "success.bg"),
        }
        bg, fg, border = palette.get(kind, palette["warn"])
        self.feedback.setText(text)
        self.feedback.setStyleSheet(
            f"background:{c(bg)};color:{c(fg)};border:1px solid {c(border)};"
            f"border-radius:{r('md')};padding:8px 10px;font-size:{fs('sm')}"
        )
        self.feedback.setVisible(True)


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):

    def __init__(self, workspace: str | os.PathLike | None = None):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(WINDOW_W, WINDOW_H)
        self.setMinimumSize(WINDOW_MIN_W, WINDOW_MIN_H)

        self.pages: dict[str, QWidget] = {}
        self.rail_items: dict[str, RailItem] = {}
        self.current_key = HOME_KEY
        self.workspace = Path(workspace) if workspace else None

        # 已挂载的真实模块（mount_* 之前为 None）
        self.import_module = None
        self.oneclick_module = None
        self.check_module = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_rail())
        body.addWidget(self._build_content(), 1)
        root.addLayout(body)

        # 三个真实模块挂进各自页面（T2.2 / T2.3 / T2.1-T2.3 检查页）
        self.mount_import(self.workspace)
        self.mount_oneclick()
        self._wire_book_ready()

        self._bind_shortcuts()
        self.go(HOME_KEY)

    # ------------------------------------------------------------------ 顶栏

    def _build_topbar(self) -> QWidget:
        top = QWidget()
        top.setObjectName("TopBar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 0, 12, 0)
        tl.setSpacing(8)

        self.brand = QPushButton(f"{APP_NAME}")
        self.brand.setObjectName("Brand")
        self.brand.setCursor(Qt.CursorShape.PointingHandCursor)
        self.brand.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.brand.setToolTip("回到首页概览")
        self.brand.clicked.connect(lambda: self.go(HOME_KEY))
        tl.addWidget(self.brand)

        self.where = QLabel("")
        self.where.setObjectName("TopWhere")
        tl.addWidget(self.where)

        tl.addStretch(1)
        for glyph, title, slot in (
            ("☰", "更多", self._act_more),
            ("?", "帮助", self._act_help),
            ("⚙", "设置", self._act_settings),
        ):
            act = QPushButton(glyph)
            act.setObjectName("TopAct")
            act.setCursor(Qt.CursorShape.PointingHandCursor)
            act.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            act.setToolTip(title)
            act.setAccessibleName(title)
            act.clicked.connect(lambda _=False, s=slot: s())
            tl.addWidget(act)
        return top

    # ------------------------------------------------------------------ 左轨

    def _build_rail(self) -> QWidget:
        rail = QWidget()
        rail.setObjectName("Rail")
        rail.setFixedWidth(RAIL_WIDTH)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(8, 12, 8, 12)
        rl.setSpacing(4)

        rtitle = QLabel("功能导航")
        rtitle.setObjectName("RailTitle")
        rl.addWidget(rtitle)

        for entry in ENTRIES:
            item = RailItem(entry)
            item.clicked.connect(lambda _=False, k=entry["key"]: self.go(k))
            self.rail_items[entry["key"]] = item
            rl.addWidget(item)
        rl.addStretch(1)

        tip = QLabel("六个入口随时可切，切走再回来，刚才的进度不会丢。")
        tip.setObjectName("RailTip")
        tip.setWordWrap(True)
        rl.addWidget(tip)
        return rail

    # ------------------------------------------------------------------ 内容区

    def _build_content(self) -> QWidget:
        self.stack = QStackedWidget()
        self.stack.setObjectName("Content")

        # 首页概览（内容区页，不占左轨配额）
        self.pages[HOME_KEY] = self._wrap(HomeOverview(on_enter=self.go))
        self.stack.addWidget(self.pages[HOME_KEY])

        # 六个入口：导入 / 一键校正 / 检查问题为真实模块，其余为建设中占位页。
        # 导入与一键校正页先放一个空控制器，由 mount_* 填真实模块——
        # 这样「页面实例只建一次」的约束在挂载前后都成立（不重建 stack 页）。
        for entry in ENTRIES:
            key = entry["key"]
            if key == "check":
                self.check_module = CheckModule()
                page = self.check_module
            elif key in ("import", "oneclick"):
                page = self._module_host()
            else:
                page = BuildingPage(entry)
                page.action_requested.connect(self.go)
            wrapped = self._wrap(page)
            self.pages[key] = wrapped
            self.stack.addWidget(wrapped)
        return self.stack

    @staticmethod
    def _module_host() -> QWidget:
        """真实模块的占位宿主：挂载时把真实模块塞进它的布局。"""
        holder = QWidget()
        holder.setObjectName("ModuleHost")
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(px(sp("4")))
        return holder

    def _content_slot(self, key: str) -> QWidget:
        """取某页内容区里的业务部件（滚动区内的第一层容器）。"""
        sa = self.pages[key]
        inner = sa.widget()
        return inner.layout().itemAt(0).widget()

    def wrap(self, widget: QWidget) -> QScrollArea:
        """内容装进滚动区：窗口变小时在内容区内部滚动，不裁切、不挤压。"""
        return self._wrap(widget)

    def _wrap(self, widget: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sa.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(20, 20, 20, 20)
        il.setSpacing(px(sp("4")))
        il.addWidget(widget)
        il.addStretch(1)
        sa.setWidget(inner)
        return sa

    # ------------------------------------------------------------------ 挂载

    def mount_import(self, workspace: str | os.PathLike | None = None):
        """把 T2.2 导入模块挂进「导入书籍」页（替换其占位宿主）。"""
        if self.import_module is not None:
            return self.import_module
        from import_module import ImportModule, install_global_drop

        root = Path(workspace) if workspace else PKG_ROOT / "workspace"
        module = ImportModule(root)
        host = self._content_slot("import")
        host.layout().addWidget(module)
        host.layout().addStretch(1)
        # 整个窗口接受拖放，拖进来自动切到导入页
        install_global_drop(self, module, goto_page=self.go)
        self.import_module = module
        return module

    def mount_oneclick(self):
        """把 T2.3 一键校正页（真链路 + 进度 + 取消）挂进「一键校正」页。"""
        if self.oneclick_module is not None:
            return self.oneclick_module
        from oneclick_module import OneClickModule

        module = OneClickModule()
        host = self._content_slot("oneclick")
        host.layout().addWidget(module)
        host.layout().addStretch(1)
        self.oneclick_module = module
        return module

    def _wire_book_ready(self):
        """导入完成 → 一键校正页就绪（同一本书直接往下走，不用再选一次）。"""
        if self.import_module is None or self.oneclick_module is None:
            return
        self.import_module.bookReady.connect(self._on_book_ready)

    def _on_book_ready(self, text_path: str):
        """导入完成的接力：把这本书的运行上下文交给一键校正页。

        只有 EPUB 且在「直接处理」路径下才有可还原的书；TXT / 先转 TXT 的
        EPUB 没有可还原的原书，这时不注入上下文，一键校正页会自己给出人话引导。
        """
        ctx = self.build_run_context(text_path)
        if ctx is None:
            return
        self.oneclick_module.set_run_context(ctx)

    def build_run_context(self, text_path: str) -> dict | None:
        """由导入结果推导一次校正所需的路径（真实文件，不做假运行）。"""
        try:
            book_dir = Path(text_path).resolve().parent
            record = book_dir / "import.json"
            import json
            meta = json.loads(record.read_text(encoding="utf-8"))
        except Exception:
            return None
        original = meta.get("original_copy_path") or ""
        # 只有 EPUB 原书才能走「校正后还原成 EPUB」的真链路
        if not original.lower().endswith(".epub") or not Path(original).exists():
            return None
        pipeline = PKG_ROOT / "pipeline"
        engine = (pipeline / "vendor" / "fixtext" / "engine" / "go_src" / "bin"
                  / "replace_by_go-linux-amd64")
        rules = PKG_ROOT / "data" / "rules"
        if not engine.exists() or not (rules / "before.json").exists():
            return None
        return dict(
            epub=str(Path(original)),
            pipeline_root=str(pipeline),
            rules_before=str(rules / "before.json"),
            rules_after=str(rules / "after.json"),
            engine_path=str(engine),
            runs_root=str(PKG_ROOT / "runs"),
            title=str(meta.get("title") or Path(original).stem),
        )

    # ------------------------------------------------------------------ 路由

    def go(self, key: str):
        """切换面板：只改 currentWidget，页面实例与其状态原样保留（不重建窗口）。"""
        if key not in self.pages:
            key = HOME_KEY
        self.stack.setCurrentWidget(self.pages[key])
        self.current_key = key
        for k, item in self.rail_items.items():
            item.set_active(k == key)
        self.where.setText(
            "首页概览" if key == HOME_KEY else
            f"{ENTRY_BY_KEY[key]['icon']}  {ENTRY_BY_KEY[key]['label']}"
        )
        self.brand.setProperty("home", "true" if key == HOME_KEY else "false")
        self.brand.style().unpolish(self.brand)
        self.brand.style().polish(self.brand)

    def page(self, key: str) -> QWidget:
        """取页面里承载的业务部件（供自检/外部接线用）。

        真实模块页返回模块本身（导入 / 一键校正 / 检查问题）；
        占位页返回占位部件。
        """
        if key == "import" and self.import_module is not None:
            return self.import_module
        if key == "oneclick" and self.oneclick_module is not None:
            return self.oneclick_module
        if key == "check" and self.check_module is not None:
            return self.check_module
        return self._content_slot(key)

    # ------------------------------------------------------------------ 顶栏动作

    def _act_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()

    def _act_help(self):
        _dialog(self, "帮助", [
            "三步就能走完一本书：",
            "1. 导入书籍：把 TXT 或 EPUB 拖进窗口。\n"
            "2. 一键校正：排版、词库替换、标点统一一次跑完。\n"
            "3. 导出结果：导出干净的 TXT，EPUB 进来的还原成 EPUB。\n\n"
            "想逐处确认引号，去「检查问题」；每一步的细节都写在对应页面里。",
        ])

    def _act_more(self):
        box = QMessageBox(self)
        box.setWindowTitle("更多")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("想去的页面：")
        box.setInformativeText("也可以直接点左边的六个入口。")
        home_btn = box.addButton("回到首页概览", QMessageBox.ButtonRole.ActionRole)
        about_btn = box.addButton("关于 FixText", QMessageBox.ButtonRole.ActionRole)
        box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is home_btn:
            self.go(HOME_KEY)
        elif box.clickedButton() is about_btn:
            _dialog(self, "关于", [
                f"{APP_NAME} · {APP_TITLE}",
                "一个面向写作者的文本校对工具：导入一本书，一键校正，"
                "逐处检查引号，导出干净文件。\n\n"
                "软件只读取你交给它的书，不会改动你的原文件。",
            ])

    # ------------------------------------------------------------------ 快捷键

    def _bind_shortcuts(self):
        """Ctrl+1~6 直达六个入口，Ctrl+H 回首页。"""
        ctx = Qt.ShortcutContext.WindowShortcut
        for i, entry in enumerate(ENTRIES, start=1):
            sc = QShortcut(QKeySequence(f"Ctrl+{i}"), self)
            sc.setContext(ctx)
            sc.activated.connect(lambda k=entry["key"]: self.go(k))
        sc = QShortcut(QKeySequence("Ctrl+H"), self)
        sc.setContext(ctx)
        sc.activated.connect(lambda: self.go(HOME_KEY))

    # ------------------------------------------------------------------ 收尾

    def closeEvent(self, event):
        if self.import_module is not None:
            try:
                self.import_module.shutdown()
            except Exception:
                pass
        super().closeEvent(event)


# ---------------------------------------------------------------------------

def load_qss(app: QApplication) -> bool:
    if not os.path.exists(QSS_PATH):
        return False
    with open(QSS_PATH, "r", encoding="utf-8") as f:
        app.setStyleSheet(f.read())
    return True


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    load_qss(app)

    # 错误中心：QApplication 之后、show 之前安装（T2.4 接法 1）
    if error_center is not None:
        try:
            error_center.init(str(PKG_ROOT / "logs"))
        except Exception:
            pass
        try:
            error_center.install_app_hooks()
        except Exception:
            pass

    win = MainWindow()
    if error_center is not None:
        try:
            error_center.set_dialog_host(win)
        except Exception:
            pass
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
