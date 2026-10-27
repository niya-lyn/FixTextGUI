"""
FixText V1 · 主窗口与六入口路由（M2-T2.1）
============================================

在已验收的 Qt 骨架上收敛出的**统一主界面框架**：
顶栏 + 左侧常驻 6 入口导航轨 + 内容区（QStackedWidget 面板路由）。

设计要点（对照《FixText 第一版功能范围与开发排期》§4.4 T2.1 / §2.2）：

- **左侧六入口常驻**：导入书籍 / 一键校正 / 检查问题 / 词库管理 / 导出结果 / 历史记录。
  六入口等权、任何页面都可见、点一下即切模块，chrome（顶栏+轨）不变。
- **首页概览**是内容区里的一页（点顶栏品牌回首页），不占左轨配额。
- **面板路由不重建窗口**：每个页面只构造一次并常驻 QStackedWidget，
  切走再切回状态原样保留（检查问题里已修复的条目切回后仍是已修复）。
- **状态清晰**：当前入口有选中态（主色浅底 + 左侧强调条 + 图标反白），
  未完成入口在轨上带「建设中」标记，页面内也有建设中说明；
  顶栏始终显示「当前位置」，任何时候都知道自己在哪。
- **零露出**：界面字符串不出现 books / booksBak / spine / OPF / 内部文件名等概念，
  统一用「你的原文件」「软件自己复制的一份」这类人话。

运行：
    python main_window.py
依赖：pip install PySide6（`fixtext.qss` 需与本包同目录，由 build_qss.py 生成）。
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, Signal, QSize
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
# 主窗口
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(WINDOW_W, WINDOW_H)
        self.setMinimumSize(WINDOW_MIN_W, WINDOW_MIN_H)

        self.pages: dict[str, QWidget] = {}
        self.rail_items: dict[str, RailItem] = {}
        self.current_key = HOME_KEY

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
        def wrap(widget: QWidget) -> QScrollArea:
            """内容装进滚动区：窗口变小时在内容区内部滚动，不裁切、不挤压。"""
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

        self.stack = QStackedWidget()
        self.stack.setObjectName("Content")

        # 首页概览（内容区页，不占左轨配额）
        self.pages[HOME_KEY] = wrap(HomeOverview(on_enter=self.go))
        self.stack.addWidget(self.pages[HOME_KEY])

        # 六个入口：检查问题为已移植真实模块，其余为建设中占位页
        for entry in ENTRIES:
            if entry["key"] == "check":
                page = CheckModule()
            else:
                page = BuildingPage(entry)
                page.action_requested.connect(self.go)
            wrapped = wrap(page)
            self.pages[entry["key"]] = wrapped
            self.stack.addWidget(wrapped)
        return self.stack

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
        """取面板里承载的业务部件（供自检/外部接线用）。"""
        sa = self.pages[key]
        inner = sa.widget()
        layout = inner.layout()
        return layout.itemAt(0).widget()

    # ------------------------------------------------------------------ 顶栏动作

    def _act_settings(self):
        _dialog(self, "设置", [
            "设置面板还在建设中。",
            "做好之后可以在这里选替换用的引擎、调进度提示、打开诊断日志——"
            "现在这些都由软件自己按默认方式处理，不影响正常使用。",
        ])

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
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
