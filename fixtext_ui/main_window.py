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
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QPushButton, QLabel, QStackedWidget, QFrame, QScrollArea,
    QMessageBox, QDialog, QMenu, QSizePolicy,
)

from fixtext_tokens import (
    APP_TITLE, APP_NAME, ENTRIES, ENTRY_BY_KEY, HOME_KEY, RAIL_WIDTH,
    READY_KEYS, SETTINGS_KEY, STATUS_TEXT, WINDOW_H, WINDOW_MIN_H,
    WINDOW_MIN_W, WINDOW_W, CONTENT_MAX_W,
    c, sp, r, fs, px, FONT_WEIGHT,
)
import fixtext_settings as app_settings
from fixtext_widgets import (
    Card, Modal, Pill, Switch, cascade_in, enable_chrome, hline, page_head_shell, PrimaryButton,
)
from fixtext_shelf import resolve_current as resolve_current_book
from fixtext_shelf import list_books as list_shelf_books
from fixtext_shelf import set_current_book_id
from fixtext_shelf_ui import BookChip
from first_run_wizard import FirstRunWizard, mark_seen, opens_on_first_run
from check_module import CheckModule
from export_module import ExportModule
from history_module import HistoryModule
from settings_module import SettingsModule
from vocab_module import VocabModule

HERE = os.path.dirname(os.path.abspath(__file__))
QSS_PATH = os.path.join(HERE, "fixtext.qss")
# 包根统一由 fixtext_paths 解析（M4-T4.1b）：打包后 fixtext_ui 被平铺进程序
# 内部目录，靠 __file__ 往上数一层会指错，词库 / 引擎 / 用户区就全找不到。
try:
    from fixtext_paths import pkg_root as _pkg_root

    PKG_ROOT = _pkg_root()
except Exception:                    # pragma: no cover - 包根模块缺失时退化
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
        """按选中态切换 active 属性，配色完全交给 fixtext.qss 的
        #RailItem / #RailItem[active="true"] 及其 #RailLabel/#RailIco 子选择器
        统一接管（单源、便于排查）。"""
        self.setProperty("active", "true" if on else "false")
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
        enable_chrome(self)  # 外框圆角（对齐原型 .card）
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

        head, body = page_head_shell()
        hl = QVBoxLayout(body)
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
# 建设中占位页（六入口已全部接真模块；仅令牌新增未知入口时回退使用）
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
        head, body = page_head_shell()
        hl = QVBoxLayout(body)
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
                btn = PrimaryButton(f"{e['icon']}  去用「{e['label']}」")
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


# --------------------------------------------------------------------
# 主窗口
# --------------------------------------------------------------------

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
        self.vocab_module = None
        self.history_module = None
        self.export_module = None
        self.settings_module = None
        self._content_inners: list = []
        #: 当前书（导入记录）：M4-EX.3a 起由用户在书架上的选择驱动，
        #: 不再等于「最近导入的那本」；启动时按设置恢复，没有设置才用最近导入。
        self._import_record: dict | None = None
        #: 当前书对应的正文路径（供后续模块接力 / 恢复运行上下文）
        self._current_text_path: str = ""

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
        self._wire_export_record()
        # M4-EX.3a：启动即按持久化的选择恢复「当前书」（重启保持）；
        # 恢复过程里会顺带按当前书重挂载各数据页（3b）
        self._restore_current_book()

        self._bind_shortcuts()
        self.go(HOME_KEY)


        # 首次使用向导（T2.8 并入）：首启自动弹出一次，之后不再自动弹
        QTimer.singleShot(0, self._maybe_first_run)

    # ------------------------------------------------------------------ 首次向导

    def _maybe_first_run(self) -> None:
        """首启（设置里没有 wizardSeen）→ 自动弹向导；之后不再自动弹。"""
        # 与 first_run_wizard.mark_seen / opens_on_first_run 同一写路径（P2-6）
        if not opens_on_first_run():
            return
        self._open_wizard()

    def _wire_empty_state(self, module, *, primary_to_import: bool = True) -> None:
        """空状态双按钮接线（原型 v3 §4 统一口径）。

        主按钮「去导入第一本书」→ 跳导入页；导入页自己的空状态主按钮
        就是选文件入口（模块内已接 ``_choose_file``），不再跳转。
        次按钮「打开新手向导」→ 弹新手向导。
        """
        es = getattr(module, "empty_state", None)
        if es is None:
            return
        if primary_to_import:
            es.primaryClicked.connect(lambda: self.go("import"))
        es.secondaryClicked.connect(self._open_wizard)

    def _open_wizard(self) -> None:
        """弹出任务式新手向导（首启触发，或 ☰ 菜单里重新观看）。

        M4-EX.2c：向导不再是只读演示，它带着用户真实走完 导入 → 校正 → 导出，
        所以要把三个模块的实例交给它（向导只调用既有流程，不新建业务）。
        完成（accept）后跳到「历史记录」页（与原型 finishWizard 一致）。
        """
        w = FirstRunWizard(
            import_module=self.import_module,
            oneclick_module=self.oneclick_module,
            export_module=self.export_module,
            parent=self,
            # M5-EX.5：☰ 重新观看 / 空状态入口一律从第 1 步开始
            has_current_book=False,
        )
        accepted = w.exec() == QDialog.DialogCode.Accepted
        # 任何关闭方式都算已看过（跳过 / 关闭 / 完成一致），先记再看跳转
        mark_seen()
        if accepted:
            self.go("history")  # 完成 → 看这次留下的历史记录

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

        # M4-EX.3a：当前书常驻显示。只展示，不在这里切换——
        # 点击跳到「导入书籍」页的书架去选（用户约束：其它页只展示不提供切换）。
        # 没书时给中性占位文案「未选择书」，点击行为一致。
        self.book_chip = BookChip()
        self.book_chip.setAccessibleName("当前要校对的书，点击前往导入书籍切换")
        self.book_chip.clicked.connect(lambda: self.go("import"))
        tl.addWidget(self.book_chip, 0, Qt.AlignmentFlag.AlignVCenter)

        tl.addStretch(1)
        # M4-EX.4d：三颗顶栏按钮**必须直连槽函数**。
        # 之前用 `lambda _=False, s=slot: s()` 中转，Qt 的 clicked 在
        # 中转 lambda 里就把发送者丢了，槽里 `self.sender()` 恒为 None，
        # 菜单锚点只能回退主窗口 → 弹在窗口左下角。直连之后
        # sender() 才是那颗按钮，弹层才能贴着按钮展开。
        self._top_acts: dict[str, QPushButton] = {}
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
            self._top_acts[title] = act
            act.clicked.connect(slot)
            tl.addWidget(act)
        return top

    # ------------------------------------------------------------- 弹层定位

    def _popup_anchor(self, title: str) -> QWidget:
        """顶栏弹层的锚点控件：优先 sender（真实点击），回退同名按钮。

        两个来源都要有：真实点击走 sender()；测试 / 脚本直接调
        `_act_more()` 时 sender() 是 None，回退到那颗按钮，
        这样两种入口都不会再退化成"锚到主窗口"。
        """
        btn = self.sender()
        if isinstance(btn, QWidget):
            return btn
        return self._top_acts.get(title) or self

    def _global_of(self, point: QPoint) -> QPoint:
        return self.mapToGlobal(point)

    def _popup_target(self, anchor: QWidget, popup_w: int, popup_h: int) -> QPoint:
        """弹层该出现在哪：默认贴锚点左下角生长，只在越界时向内收。

        收也要收得有章法——横向越出窗口右边缘时，改成"弹层右边缘对齐
        按钮右边缘"，弹层始终挨着那颗按钮，不会被推成离按钮很远的样子；
        纵向放不下时才整体上提。两者都再兜一次窗口边界。
        """
        a_left = anchor.mapToGlobal(QPoint(0, anchor.height())).x()
        a_right = anchor.mapToGlobal(QPoint(anchor.width(), anchor.height())).x()
        gy = anchor.mapToGlobal(QPoint(0, anchor.height())).y()

        left = self._global_of(QPoint(0, 0)).x()
        right = self._global_of(QPoint(self.width(), 0)).x()
        top = self._global_of(QPoint(0, 0)).y()
        bottom = self._global_of(QPoint(0, self.height())).y()

        gx = a_left
        if popup_w > 0 and gx + popup_w > right:
            # 横向放不下：右边缘对齐按钮右边缘（比推回窗口左边更贴按钮）
            gx = a_right - popup_w
        if popup_w > 0:
            gx = max(min(gx, right - popup_w), left)
        if popup_h > 0:
            gy = min(gy, bottom - popup_h)
        return QPoint(gx, max(gy, top))

    def _show_modal_under(self, m: Modal, title: str) -> int:
        """模态框贴着顶栏按钮展开（不再是屏幕左上角 / 窗口左下角）。"""
        anchor = self._popup_anchor(title)
        m.adjustSize()          # 先定尺寸，否则 width()/height() 还是 0
        m.move(self._popup_target(anchor, m.width(), m.height()))
        return m.exec()

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

        # 六个入口均为真实模块（词库 / 历史 / 导出已非占位页）。
        # 导入与一键校正页先放宿主，由 mount_* 填入——「页面实例只建一次」。
        for entry in ENTRIES:
            key = entry["key"]
            if key == "check":
                self.check_module = CheckModule()
                page = self.check_module
            elif key == "vocab":
                self.vocab_module = VocabModule()
                page = self.vocab_module
            elif key == "history":
                self.history_module = HistoryModule()
                page = self.history_module
            elif key == "export":
                self.export_module = ExportModule()
                page = self.export_module
            elif key in ("import", "oneclick"):
                page = self._module_host()
            else:
                # 防御性回退：令牌若新增未知入口，仍给建设中页而非崩
                page = BuildingPage(entry)
                page.action_requested.connect(self.go)
            if key in ("check", "history", "export"):
                self._wire_empty_state(page)
            wrapped = self._wrap(page)
            self.pages[key] = wrapped
            self.stack.addWidget(wrapped)
        # 设置页（M4-EX.2a）：不在左轨六入口里，由顶栏 ⚙ 进入的平级路由页
        self.settings_module = SettingsModule()
        self.settings_module.vocab_dir_changed.connect(self.reload_vocab_store)
        self.settings_module.engine_changed.connect(self._on_engine_changed)
        self.settings_module.factory_reset_requested.connect(self._on_factory_reset)
        self.pages[SETTINGS_KEY] = self._wrap(self.settings_module)
        self.stack.addWidget(self.pages[SETTINGS_KEY])

        # 检查页「＋词库」走词库页同一个写入口（T3.1 五操作同一入口）：
        # 加入天然可撤销、天然查重，不另起一套写盘路径。
        if self.check_module is not None and self.vocab_module is not None:
            self.check_module.set_vocab_store(self.vocab_module.store)
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
        if not hasattr(self, "_content_inners"):
            self._content_inners = []
        self._content_inners.append((sa, inner))
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
        # 空状态次按钮（打开新手向导）；主按钮已由模块内接 _choose_file
        self._wire_empty_state(module, primary_to_import=False)
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
        # 校正完成 → 导出页拿到可导出的产物；「去导出」→ 真的跳到导出页
        module.correctionDone.connect(self._on_correction_done)
        module.gotoExport.connect(lambda: self.go("export"))
        module.gotoCheck.connect(self._go_check)
        # 本书专有词条（真实抽出）→ 词库管理页确认后加入
        module.bookWordsReady.connect(self._on_book_words_ready)
        self._wire_empty_state(module)
        return module

    def _on_book_words_ready(self, words, book_title: str):
        """把本次运行真实抽出的本书专有词条交给词库页（页面自己再逐条查重）。"""
        if self.vocab_module is None:
            return
        self.vocab_module.set_book_words(list(words or []), str(book_title or ""))
        self.go("vocab")

    def _wire_book_ready(self):
        """导入完成 → 一键校正页就绪（同一本书直接往下走，不用再选一次）。"""
        if self.import_module is None or self.oneclick_module is None:
            return
        self.import_module.bookReady.connect(self._on_book_ready)
        # 书架里换当前书（M4-EX.3a 引入；3b 起四页数据跟着换书）
        self.import_module.currentBookChanged.connect(self._on_current_book_changed)

    def _wire_export_record(self):
        """导出成功（无论从哪一页）→ 书架「已导出」与历史状态按真实记录刷新。"""
        if self.export_module is not None:
            self.export_module.exportRecorded.connect(self._on_export_recorded)
        if self.history_module is not None:
            self.history_module.exportFinished.connect(
                lambda _payload: self._on_export_recorded())

    def _on_export_recorded(self):
        """导出状态落盘后：重扫书架与历史（都由磁盘上的真实记录驱动）。"""
        if self.import_module is not None:
            self.import_module.refresh_shelf()
        if self.history_module is not None:
            self.history_module.refresh()

    def _restore_current_book(self) -> None:
        """启动时恢复当前书：设置里记的那本 → 否则最近导入的那本 → 否则没有。"""
        books = list_shelf_books(self._workspace_root())
        current = resolve_current_book(self._workspace_root(), books)
        if current is None:
            self._apply_current_book(None, "")
        else:
            self._apply_current_book(current.record, current.text_path)
        # 启动即按当前书把各数据页挂载到位（3b：历史 / 检查 / 导出从一开始就按书）
        self._reload_book_pages()

    def _workspace_root(self) -> Path:
        """工作区根目录（与导入模块同一口径）。"""
        if self.import_module is not None:
            return Path(self.import_module.workspace)
        return Path(self.workspace) if self.workspace else PKG_ROOT / "workspace"

    def _apply_current_book(self, record: dict | None, text_path: str) -> None:
        """把「当前书」落到窗口状态：顶栏书名 + 导出/历史/校正用的记录与路径。"""
        self._import_record = record
        self._current_text_path = str(text_path or "")
        title = str((record or {}).get("title") or "")
        self.book_chip.set_book(title or None)

    def _on_current_book_changed(self, text_path: str):
        """书架里换了当前书（M4-EX.3b）：四页数据即时跟着换。

        换书不只换顶栏——一键校正的运行上下文、历史页的记录、检查页的
        问题列表、导出页的最近产物全部按新书重挂载；新书没有记录时各页
        走自己的空状态，**不会**把上一本书的数据留在页面上。
        """
        record = self._read_import_record(text_path) if text_path else None
        self._apply_current_book(record, text_path)
        self._reload_book_pages()

    def _on_book_ready(self, text_path: str):
        """导入完成的接力：这本书即成为当前书，并把运行上下文交给一键校正页。

        只有 EPUB 且在「直接处理」路径下才有可还原的书；TXT / 先转 TXT 的
        EPUB 没有可还原的原书，这时不注入上下文，一键校正页会自己给出人话引导。
        """
        record = self._read_import_record(text_path)
        # 新导入的书自动设为当前（否则多书之后「导入完直接用」的动线会断）
        book_id = Path(text_path).resolve().parent.name if text_path else ""
        if book_id:
            set_current_book_id(book_id)
        self._apply_current_book(record, text_path)
        # 书架重排：这一行现在应显示「当前」，其它行回到「设为当前」
        if self.import_module is not None:
            self.import_module.refresh_shelf()
        self._reload_book_pages()

    @staticmethod
    def _read_import_record(text_path: str) -> dict | None:
        """读导入记录（导出页要靠它判断这本书能不能还原成电子书）。"""
        try:
            import json
            record = Path(text_path).resolve().parent / "import.json"
            return json.loads(record.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _sync_export(self, run: dict | None) -> None:
        """把「当前书 + 最近一次校正」同步给导出页。"""
        if self.export_module is None:
            return
        self.export_module.set_context(
            self._import_record, run, str(PKG_ROOT / "pipeline"))

    def _on_correction_done(self, summary: dict) -> None:
        """校正完成 → 导出页拿到产物，检查页挂当前正文并自扫，历史页记一条。

        M4-EX.6-R3：把替换后正文（含可选自动修引号）写回当前书 ``book.txt``，
        检查页立刻自扫，关=全量 / 开=剩余 M 处，无需再点「开始检查」。
        """
        self._sync_book_text_from_run(summary)
        # 工作区正文/账本已更新 → 刷新一键校正上下文，下次校正吃新副本
        if self.oneclick_module is not None and self._current_text_path:
            ctx = self.build_run_context(self._current_text_path)
            self.oneclick_module.set_run_context(ctx)
        self._sync_export(summary)
        self._sync_check(summary, auto_scan=True)
        self._sync_history(summary)

    def _go_check(self) -> None:
        """「去检查页」：切页；若尚在待检查态则补扫一次。"""
        self.go("check")
        cm = self.check_module
        if cm is None or not cm.has_book:
            return
        from check_module import PHASE_READY, PHASE_RUNNING
        if cm.phase == PHASE_READY:
            cm.start_check()
        elif cm.phase == PHASE_RUNNING:
            pass

    def _sync_book_text_from_run(self, summary: dict | None) -> None:
        """把本次校正后正文（及 EPUB 账本）写回工作区副本。

        ``book.txt`` ← replace/quote 后正文；EPUB 还要把与正文同 nonce 的
        ``*.bundle.json`` 写到书目录并更新 ``import.json``，否则下一轮无法
        用工作正文还原工作 EPUB，导出也会对不上账本。
        """
        path = str(getattr(self, "_current_text_path", "") or "")
        if not path:
            return
        book_path = Path(path)
        arts = (summary or {}).get("artifacts") or {}
        # quote 写回的是 replace_after；checked_file 与之同路径，优先 after_text
        after = str(arts.get("after_text") or arts.get("checked_file") or "")
        if not after or not Path(after).is_file():
            return
        try:
            text = Path(after).read_text(encoding="utf-8")
            book_path.write_text(text, encoding="utf-8", newline="\n")
        except Exception:
            return

        ledger_src = str(arts.get("ledger") or "")
        if not ledger_src or not Path(ledger_src).is_file():
            return
        book_dir = book_path.parent
        ledger_dst = book_dir / "book.bundle.json"
        try:
            import shutil
            shutil.copy2(ledger_src, ledger_dst)
        except Exception:
            return
        # 刷新 import.json 里的账本指针，供导出 / 下一轮校正使用
        record_path = book_dir / "import.json"
        if not record_path.is_file():
            return
        try:
            import json
            meta = json.loads(record_path.read_text(encoding="utf-8"))
            meta["ledger_path"] = str(ledger_dst)
            meta["text_path"] = str(book_path)
            record_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            self._import_record = meta
        except Exception:
            pass

    # --------------------------------------------------- 检查页 / 历史页 接线（T2.10）

    def _sync_check(self, run: dict | None = None, *, auto_scan: bool = False) -> None:
        """M4-EX.6-R2：检查页挂当前书正文，自扫不读校正报告。

        ``auto_scan=True``（校正完成）：挂载后立即扫描，结果进检查页。
        """
        if self.check_module is None:
            return
        path = str(getattr(self, "_current_text_path", "") or "")
        if not path:
            self.check_module.set_book("", "")
            return
        rec = self._import_record or {}
        title = str(rec.get("title") or Path(path).parent.name)
        ext = str(rec.get("source_suffix") or "txt")
        self.check_module.set_book(
            path, title, book_ext=ext,
            rules_dir=self._workspace_root())
        if auto_scan:
            self.check_module.start_check()

    def _load_history(self) -> None:
        """历史页接上**当前书**的运行目录（M4-EX.3b：runs 按书隔离）。"""
        runs_root = self._book_runs_root()
        if self.history_module is None:
            return
        self.history_module.set_runs_root(
            str(runs_root if runs_root is not None else PKG_ROOT / "runs"))
        self.history_module.refresh()

    @staticmethod
    def _pick_engine() -> Path | None:
        """取本平台的替换引擎（全窗口唯一入口，勿在别处再写文件名）。

        Windows 上必须拿 ``.exe``；照旧写死 Linux 文件名会让
        ``exists()`` 照样为真（那个文件真在包里），一路放行到执行时
        才炸 ``WinError 193``。所以这里统一走 engine_selector 的平台判断。
        """
        import sys as _sys

        pipeline_root = str(PKG_ROOT / "pipeline")
        if pipeline_root not in _sys.path:
            _sys.path.insert(0, pipeline_root)
        from fixtext_pipeline.engine_selector import select_engine

        return select_engine(PKG_ROOT / "pipeline" / "vendor" / "fixtext"
                             / "engine" / "go_src" / "bin")

    def _book_runs_root(self) -> Path | None:
        """当前书专属的运行目录（runs/<书 id>）；没有当前书时为 None。"""
        if not self._current_text_path:
            return None
        book_id = Path(self._current_text_path).resolve().parent.name
        return (PKG_ROOT / "runs" / book_id) if book_id else None

    def _latest_run_summary(self, runs_root: Path | None) -> dict | None:
        """当前书最近一次校正的运行摘要（没有记录就是 None，不编数据）。"""
        if runs_root is None or not runs_root.is_dir():
            return None
        import fixtext_history as histdata
        import fixtext_export as fx

        for rec in histdata.scan_runs(runs_root):
            summary = fx.load_run_summary(rec["run_dir"])
            if summary:
                summary.setdefault("workdir", rec["run_dir"])
                return summary
        return None

    def _reload_book_pages(self) -> None:
        """当前书一变，四个数据页全部按这本书重挂载（M4-EX.3b 切换即时刷新）。

        一键校正拿到新书的运行上下文（下次校正作用于新书）；历史页扫这本书
        自己的运行目录；检查页与导出页挂这本书最近一次校正的结果。没有当前
        书或这本书还没有记录时，各页走自己的空状态——切换后页面上不允许
        留着另一本书的数据。
        """
        runs_root = self._book_runs_root()
        latest = self._latest_run_summary(runs_root)
        if self.oneclick_module is not None:
            ctx = (self.build_run_context(self._current_text_path)
                   if self._current_text_path else None)
            self.oneclick_module.set_run_context(ctx)
        self._load_history()
        self._sync_check(latest)
        self._sync_export(latest)
        self._refresh_export_ctx(latest)

    def _refresh_export_ctx(self, run: dict | None) -> None:
        """把「重新导出 / 快照恢复 / 从时点继续」要用的上下文交给历史页。

        不只是导出：恢复后要继续跑后面的阶段，就得有词库与处理组件的位置，
        所以这里一并把它们的真实路径注入（缺任何一项，继续按钮会自己说不行）。
        """
        if self.history_module is None:
            return
        pipeline_root = str(PKG_ROOT / "pipeline")
        rules = PKG_ROOT / "data" / "rules"
        engine = self._pick_engine()
        # 这本书的目录（M4-EX.3b）：历史页重新导出成功后，导出记录写到这里
        book_dir = ""
        if self._import_record:
            bd = Path(str(self._import_record.get("text_path") or "")).resolve().parent
            if bd.name and (bd / "import.json").exists():
                book_dir = str(bd)
        self.history_module.set_export_ctx({
            "import_record": self._import_record,
            "pipeline_root": pipeline_root,
            "out_dir": str(self.export_out_dir()),
            "baseline_sha256": str((run or {}).get("restored_sha256") or ""),
            "rules_before": str(rules / "before.json"),
            "rules_after": str(rules / "after.json"),
            "engine_path": str(engine or ""),
            "book_dir": book_dir,
        })

    def export_out_dir(self) -> Path:
        """导出目录：跟导出页同一口径（导入文件夹旁边的「导出结果」）。

        没有导入记录时退回工作区下的同名文件夹——真实可写目录，
        不写进任何界面文案，也不在界面里显示绝对路径。
        """
        original = str((self._import_record or {}).get("original_copy_path") or "")
        if original:
            return Path(original).resolve().parent / "导出结果"
        base = self.workspace or (PKG_ROOT / "workspace")
        return Path(base) / "导出结果"

    def _sync_history(self, run: dict | None) -> None:
        """校正完成 → 把本次记录写进运行摘要并让历史页重扫（重启也在）。"""
        if self.history_module is None:
            return
        import fixtext_history as histdata

        run_dir = str((run or {}).get("workdir") or "")
        if run_dir:
            hits = (run or {}).get("hits")
            if hits is None:
                # 老摘要可能没写命中数：按本次产物现算，算不出就留空（不编数字）
                import fixtext_worker as worker

                art = (run or {}).get("artifacts") or {}
                hits = worker._count_replaced(
                    Path(art["before_text"]) if art.get("before_text") else None,
                    Path(art["after_text"]) if art.get("after_text") else None,
                )
            histdata.write_run_meta(
                run_dir,
                title=str((run or {}).get("title") or (run or {}).get("book") or ""),
                book=str((run or {}).get("book") or ""),
                author=str((run or {}).get("author") or ""),
                hits=hits,
                quote_errors=(run or {}).get("quote_errors"),
                chapters=(run or {}).get("chapters"),
                restored_sha256=str((run or {}).get("restored_sha256") or ""),
                source_epub=str((run or {}).get("source_epub") or ""),
            )
        self._refresh_export_ctx(run)
        self.history_module.refresh()

    def build_run_context(self, text_path: str) -> dict | None:
        """由导入结果推导一次校正所需的路径（真实文件，不做假运行）。

        校正输入**一律**是工作区 ``book.txt``（导入时已从原件合并/转写；
        一键校正与检查页的修改也写回这里）。原件副本只读保留：EPUB 仅作
        导出还原模板（``template_epub``），校正过程不再碰 EPUB 格式。

        TXT：``plain_book`` 包成单章电子书后走 merge。
        EPUB：跳过 merge，用 ``book.txt``+账本直接进排版/替换；导出时再还原 EPUB。
        """
        try:
            book_dir = Path(text_path).resolve().parent
            record = book_dir / "import.json"
            import json
            meta = json.loads(record.read_text(encoding="utf-8"))
        except Exception:
            return None
        original = meta.get("original_copy_path") or ""
        if not original or not Path(original).exists():
            return None
        working = Path(text_path)
        if not working.is_file():
            return None

        pipeline = PKG_ROOT / "pipeline"
        engine = self._pick_engine()
        rules = PKG_ROOT / "data" / "rules"
        # M4-T4.2：不再要求 Go 引擎存在才建运行上下文——引擎被删 / 被杀软
        # 隔离时，一键校正会走降级确认（Python 引擎不需要 Go 二进制）；
        # 这里只挡词库缺失（两个引擎都绕不开词库）。
        # M4-T4.1c：引擎路径按平台取（engine_selector），取不到时留空串，
        # 由 oneclick 的 go_engine_status 判为不可用后走降级确认。
        if not (rules / "before.json").exists():
            return None

        title = str(meta.get("title") or Path(original).stem)
        # 用户区（自定义词库 / 派生规则 / 还原点）统一在包根 workspace/ 下，
        # 显式注入，避免替换阶段按别的推算规则找第二份自定义词库。
        vocab_dir = PKG_ROOT / "workspace" / "vocab"
        ctx = dict(
            pipeline_root=str(pipeline),
            rules_before=str(rules / "before.json"),
            rules_after=str(rules / "after.json"),
            engine_path=str(engine),
            # M4-EX.3b：运行目录按书隔离（runs/<书 id>）——历史、快照、
            # 「当前工作区」指针全部跟着 runs_root 走，一处注入即全书隔离。
            runs_root=str(PKG_ROOT / "runs" / book_dir.name),
            workspace=str(PKG_ROOT / "workspace"),
            title=title,
            author=str(meta.get("author") or ""),
            suffix=Path(original).suffix.lower(),
            custom_vocab_path=str(vocab_dir / "custom_vocab.json"),
            derived_rules_dir=str(vocab_dir / "derived_rules"),
            # 工作副本：TXT / EPUB 校正都吃它
            plain_source=str(working),
        )
        if original.lower().endswith(".epub"):
            ctx["template_epub"] = str(Path(original))
            ledger = str(meta.get("ledger_path") or "")
            if not ledger or not Path(ledger).is_file():
                cand = book_dir / "book.bundle.json"
                ledger = str(cand) if cand.is_file() else ""
            if ledger:
                ctx["ledger_path"] = ledger
        return ctx

    # ------------------------------------------------------------------ 路由

    def go(self, key: str):
        """切换面板：只改 currentWidget，页面实例与其状态原样保留（不重建窗口）。"""
        if key not in self.pages:
            key = HOME_KEY
        self.stack.setCurrentWidget(self.pages[key])
        self.current_key = key
        for k, item in self.rail_items.items():
            item.set_active(k == key)
        if key == HOME_KEY:
            self.where.setText("首页概览")
        elif key == SETTINGS_KEY:
            self.where.setText("⚙  设置")
        else:
            self.where.setText(
                f"{ENTRY_BY_KEY[key]['icon']}  {ENTRY_BY_KEY[key]['label']}"
            )
        # v3 质感层：切页时页内卡片级联淡入（等效原型 cardIn）
        if key != getattr(self, "_cascade_last_key", None):
            target = self.page(key)
            if target is not None:
                cards = [w for w in target.findChildren(Card)
                         if w.isVisible() and w.graphicsEffect() is None]
                cascade_in(cards)
        self._cascade_last_key = key
        self.brand.setProperty("home", "true" if key == HOME_KEY else "false")
        self.brand.style().unpolish(self.brand)
        self.brand.style().polish(self.brand)

    def page(self, key: str) -> QWidget:
        """取页面里承载的业务部件（供自检/外部接线用）。

        六入口与设置页均返回真实模块；未知键才回落到内容槽宿主。
        """
        if key == "import" and self.import_module is not None:
            return self.import_module
        if key == "oneclick" and self.oneclick_module is not None:
            return self.oneclick_module
        if key == "check" and self.check_module is not None:
            return self.check_module
        if key == "vocab" and self.vocab_module is not None:
            return self.vocab_module
        if key == "history" and self.history_module is not None:
            return self.history_module
        if key == "export" and self.export_module is not None:
            return self.export_module
        if key == SETTINGS_KEY and self.settings_module is not None:
            return self.settings_module
        return self._content_slot(key)

    # ------------------------------------------------------------------ 顶栏动作

    def _act_settings(self):
        """设置：跳到设置路由页（M4-EX.2a 起不再弹对话框）。"""
        self.go(SETTINGS_KEY)

    def _act_help(self):
        """帮助：六个入口各自负责什么（等权，没有先后）。"""
        m = Modal(icon="?", title="帮助")
        m.add_note("FixTextGUI 把电子书校对收敛成六个入口，点左边导航或首页卡片就能进去；"
                   "六者等权，没有先后顺序。", "info")
        for entry in ENTRIES:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            name = QLabel(f"{entry['icon']}  {entry['label']}")
            name.setStyleSheet(f"font-size:{fs('md')};color:{c('neutral.800')}")
            rl.addWidget(name)
            rl.addStretch(1)
            desc = QLabel(entry["short"])
            desc.setWordWrap(True)
            desc.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('sm')}")
            rl.addWidget(desc, 2)
            m.add_widget(row)
        m.add_foot("关闭", kind="ghost")
        self._show_modal_under(m, "帮助")

    def _act_more(self):
        """菜单：新手向导 / 重新生成样式表 / 关于。"""
        menu = QMenu(self)
        a_wizard = menu.addAction("新手向导（重新观看）")
        a_wizard.triggered.connect(self._open_wizard)
        menu.addSeparator()
        a_regen = menu.addAction("重新生成样式表")
        a_regen.triggered.connect(self._regen_qss)
        menu.addSeparator()
        a_about = menu.addAction("关于 FixTextGUI")
        a_about.triggered.connect(self._about)
        # M4-EX.4d：锚点必须是触发那颗按钮本身。这里不再依赖 sender() 是否
        # 有效，锚点解析统一收在 _popup_anchor（真实点击取 sender，脚本直调
        # 回退到同名按钮）；尺寸用 sizeHint，菜单此刻还没 show 起来。
        anchor = self._popup_anchor("更多")
        menu.exec(self._popup_target(anchor, menu.sizeHint().width(),
                                     menu.sizeHint().height()))

    def _regen_qss(self):
        """按设计令牌重新生成界面样式表。

        打包后（M4-T4.1b）不能再起子进程跑 ``build_qss.py``——``sys.executable``
        是程序本身，会再拉起一个主窗口。冻结态改为进程内调用生成函数，
        写出的是同一份样式表（两者共用 fixtext_tokens 令牌）。
        """
        try:
            if getattr(sys, "frozen", False):
                import build_qss as _bq

                Path(QSS_PATH).write_text(_bq.build(), encoding="utf-8")
            else:
                script = os.path.join(HERE, "build_qss.py")
                subprocess.run([sys.executable, script], check=True, timeout=30,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            self._flash("✓", "样式表已重新生成",
                        "已按设计令牌重写界面样式，重新打开窗口即可看到。", "info")
        except Exception as e:  # noqa: BLE001
            self._flash("!", "样式表生成失败", f"这次没能生成：{e}", "warn")

    def _about(self):
        self._flash("ℹ", "关于 FixTextGUI",
                    "FixTextGUI · 面向写作者的电子书排版校正工具。\n"
                    "六个入口：导入书籍、一键校正、检查问题、词库管理、导出结果、历史记录。\n"
                    "软件只读取你交给它的书，不会改动你的原文件。", "info")

    def _flash(self, icon: str, title: str, msg: str, kind: str = "info"):
        """轻量结果提示（重新生成 / 打开目录 / 关于 的反馈）。

        M4-EX.4d：这些提示都由 ☰ 菜单项触发，sender() 是 QAction 不是按钮，
        所以锚点回退到「更多」按钮，弹层贴在 ☰ 下方而不是屏幕左上角。
        """
        m = Modal(icon=icon, title=title, min_width=460)
        m.add_note(msg, kind)
        m.add_foot("知道了", kind="ghost")
        self._show_modal_under(m, "更多")

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

    # ------------------------------------------------------------------ 大屏收束

    def resizeEvent(self, event):
        """v3 质感层：窗口比内容收束宽（1280）更宽时，内容区居中收束。

        原型用 CSS ``.main { max-width:1280px; margin:0 auto }``；Qt 侧在
        每页滚动区的内容容器上动态加左右留白，宽度不够时回落正常留白（20px）。
        """
        super().resizeEvent(event)
        # viewport 的宽度要等本轮布局走完才更新，延迟一拍再收束
        QTimer.singleShot(0, self._apply_content_max_width)

    def _apply_content_max_width(self):
        base = px(sp("5"))                     # 常态内容留白 20px
        for sa, inner in self._content_inners:
            vw = sa.viewport().width()
            if vw <= 0:
                continue
            m = max(base, (vw - CONTENT_MAX_W) // 2)
            lay = inner.layout()
            lay.setContentsMargins(m, base, m, base)

    # ------------------------------------------------------------------ 词库重载

    def reload_vocab_store(self):
        """设置里改了自定义词库存储位置后：按新位置重建词库数据入口。

        只换 UI 层的数据入口对象（VocabStore 以显式路径重建），
        词库读写逻辑本身不动。检查页共享的词库引用一并更新。
        """
        if self.vocab_module is None:
            return
        try:
            self.vocab_module.reload_store()
        except Exception:                              # noqa: BLE001
            pass
        if self.check_module is not None:
            self.check_module.set_vocab_store(self.vocab_module.store)

    def _on_engine_changed(self, value: str):
        """替换引擎切换（M4-EX.2a 只保存选择；执行逻辑在 M4-T4.2 接线）。"""
        self._last_engine = value

    def _on_factory_reset(self) -> None:
        """设置页「初始化」：清全部运行产物并刷新界面（M5-EX.6）。"""
        from fixtext_factory_reset import reset_all_products

        done = reset_all_products(
            workspace=self._workspace_root(),
            pkg_root=PKG_ROOT,
        )
        # 内存态回到无书
        try:
            from fixtext_shelf import clear_current_book_id
            clear_current_book_id()
        except Exception:  # noqa: BLE001
            pass
        self._apply_current_book(None, "")
        if self.import_module is not None:
            try:
                # 书架 + 「本次导入」结果卡一并清掉（只 refresh_shelf 会留下结果区）
                self.import_module.reset_session()
            except Exception:  # noqa: BLE001
                pass
        if self.oneclick_module is not None:
            try:
                self.oneclick_module.set_run_context(None)
            except Exception:  # noqa: BLE001
                pass
        self._reload_book_pages()
        self.reload_vocab_store()
        if self.settings_module is not None:
            self.settings_module._sync_from_settings()
            self.settings_module._apply_log_backend()
            self.settings_module._say(
                "已初始化为刚装好时的状态。已清理：" + "；".join(done),
                "ok",
            )
        self.go("import")
        # 设置已清空 → 视为从未看过向导，与首启一致再弹一次
        QTimer.singleShot(0, self._maybe_first_run)

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
