"""设置页（M4-EX.2a 结构层）：从顶栏弹窗升为平级路由页。

对齐合并版原型 v3 的「设置视图」：页头（标题 + 副标题）
+ 四张卡片——

1. 词库与数据      自定义词库存储位置（选择目录 / 恢复默认位置）
2. 诊断与日志      日志目录（选择目录 / 打开日志目录）+ 出错时自动保留现场
3. 通用            安全保护（只读原文件，始终开启）
4. 替换引擎        Go（默认）/ Python 二选一，读写配置键 ``engine``
                   （与 M4-T4.2 引擎双轨的对接契约：go | python，默认 go）

所有设置项真实生效：

* 词库存储位置 —— 写入设置后发 ``vocab_dir_changed``，主窗口重载词库数据入口，
  之后新增的词条就落在新位置（工作副本与还原点随同一棵子树走）；
* 日志目录 —— 变更后立即对错误中心重新初始化，后续诊断记录落新目录；
* 开关与引擎选择 —— 落在用户区设置文件里，重启后保留。

页面不在左侧六入口里（左轨保持六项），由顶栏 ⚙ 进入。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

import fixtext_settings as settings
from fixtext_tokens import c, sp, r, fs, FONT_WEIGHT, FONT_MONO
from fixtext_widgets import Card, FieldRow, Switch, RadioCard, hline

try:
    import fixtext_error_center as error_center
except Exception:                                  # noqa: BLE001 - 可选组件
    error_center = None


def _label(text: str, *, size: str = "sm", color: str = "neutral.600",
            weight: str = "regular", wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(wrap)
    lab.setStyleSheet(
        f"color:{c(color)};font-size:{fs(size)};font-weight:{FONT_WEIGHT[weight]}")
    return lab


def _pathbox() -> tuple[QFrame, QLabel]:
    """原型 pathrow 的 Qt 等效：浅底虚线框 + 等宽字体路径。"""
    box = QFrame()
    box.setObjectName("PathRow")
    lay = QHBoxLayout(box)
    lay.setContentsMargins(12, 9, 12, 9)
    lay.setSpacing(10)
    lab = QLabel("")
    lab.setWordWrap(True)
    lab.setStyleSheet(
        f"color:{c('neutral.600')};font-size:{fs('sm')};"
        f"font-family:'{FONT_MONO}'")
    lab.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    lay.addWidget(lab, 1)
    return box, lab


def _btn(text: str, obj: str, slot) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(obj)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.clicked.connect(slot)
    return b


class SettingsModule(QWidget):
    """设置路由页（key = "settings"，由顶栏 ⚙ 进入）。"""

    #: 自定义词库存储位置变了（主窗口重载词库数据入口）
    vocab_dir_changed = Signal()
    #: 替换引擎选择变了（执行逻辑在 M4-T4.2，此处只负责选择与保存）
    engine_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._syncing = False
        self.cards: list[Card] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(px(sp("4")))

        root.addWidget(self._header())

        root.addWidget(self._card_vocab())
        root.addWidget(self._card_log())
        root.addWidget(self._card_general())
        root.addWidget(self._card_engine())

        self.legend = _label(
            "这里的每一项改动都会立即保存，重启后仍然生效。",
            size="xs", color="neutral.500", wrap=True)
        root.addWidget(self.legend)

        self._build_status(root)
        self._sync_from_settings()

    # ------------------------------------------------------------------ 页头

    def _header(self) -> QWidget:
        """页头：标题 + 副标题。"""
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(_label("设置", size="2xl", color="neutral.900", weight="bold"))
        col.addWidget(_label(
            "词库存放位置、诊断日志、安全保护与替换引擎，都集中在这里。",
            size="md", color="neutral.600", wrap=True))
        hl.addLayout(col, 1)

        # 质感层：页头底部分隔线（原型 page-head 的 border-bottom）
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        wl.addWidget(w)
        wl.addWidget(hline())
        return wrap

    # ------------------------------------------------------------------ 卡片一

    def _card_vocab(self) -> Card:
        card = Card("词库与数据", "指定词库存放位置")
        self.cards.append(card)

        self.vocab_path = _pathbox()
        self.vocab_path_btns = QWidget()
        vbl = QHBoxLayout(self.vocab_path_btns)
        vbl.setContentsMargins(0, 0, 0, 0)
        vbl.setSpacing(8)
        self.vocab_choose_btn = _btn("选择目录", "BtnSecondary", self._choose_vocab_dir)
        self.vocab_reset_btn = _btn("恢复默认位置", "BtnGhost", self._reset_vocab_dir)
        self.vocab_reset_btn.setVisible(False)
        vbl.addWidget(self.vocab_choose_btn)
        vbl.addWidget(self.vocab_reset_btn)

        row1 = FieldRow(
            None, "自定义词库存储位置",
            "我的词库与还原点都存在这里；可以改到任意目录（比如同步盘），"
            "改完立即生效。",
            control=self.vocab_path_btns)
        card.body_l.addWidget(self._with_path(row1, self.vocab_path[0]))

        row2 = FieldRow(
            None, "内置词库",
            "随软件一起发布，只读；恢复默认只重置内置词库，不影响上面的存放位置。")
        card.body_l.addWidget(row2)
        return card

    def _with_path(self, row: FieldRow, pathbox: QFrame) -> QWidget:
        """一行 = 字段行（上） + 路径展示框（下），中间留一点呼吸。"""
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        bl.addWidget(row)
        bl.addWidget(pathbox)
        return box

    # ------------------------------------------------------------------ 卡片二

    def _card_log(self) -> Card:
        card = Card("诊断与日志", "日志存放位置与一键打开")
        self.cards.append(card)

        self.log_path = _pathbox()
        self.log_path_btns = QWidget()
        lbl = QHBoxLayout(self.log_path_btns)
        lbl.setContentsMargins(0, 0, 0, 0)
        lbl.setSpacing(8)
        self.log_choose_btn = _btn("选择目录", "BtnSecondary", self._choose_log_dir)
        self.log_reset_btn = _btn("恢复默认位置", "BtnGhost", self._reset_log_dir)
        self.log_reset_btn.setVisible(False)
        self.log_open_btn = _btn("打开日志目录", "BtnOutline", self._open_log_dir)
        lbl.addWidget(self.log_choose_btn)
        lbl.addWidget(self.log_reset_btn)
        lbl.addWidget(self.log_open_btn)

        row1 = FieldRow(
            None, "诊断日志目录",
            "处理失败时的原始记录都落在这个目录；换一个位置后，新的记录就写过去。",
            control=self.log_path_btns)
        card.body_l.addWidget(self._with_path(row1, self.log_path[0]))

        row2 = FieldRow(
            None, "出错时自动保留现场",
            "任何处理失败都在日志里留一条记录，不打断正在做的事。",
            control=self._switch_slot("diag"))
        card.body_l.addWidget(row2)
        return card

    # ------------------------------------------------------------------ 卡片三

    def _card_general(self) -> Card:
        card = Card("通用", "安全保护")
        self.cards.append(card)

        safe = Switch(checked=True)
        safe.setEnabled(False)          # 始终开启，不给「关掉」的假选项
        row1 = FieldRow(
            None, "安全保护（只读原文件）",
            "始终开启：任何导入都先复制一份副本，你的原文件从头到尾只读。",
            control=safe)
        card.body_l.addWidget(row1)
        return card

    # ------------------------------------------------------------------ 卡片四

    def _card_engine(self) -> Card:
        card = Card("替换引擎", "选择替换阶段的执行引擎")
        self.cards.append(card)

        intro = _label(
            "两种引擎做同一件事，选中的那种会在下一次校正开始时使用；"
            "选择会保存，重启后仍然生效。",
            size="xs", color="neutral.500", wrap=True)
        card.body_l.addWidget(intro)
        card.body_l.addSpacing(8)

        self.engine_cards: dict[str, RadioCard] = {}
        grid = QWidget()
        gl = QHBoxLayout(grid)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(12)
        for value, title, desc in (
            ("go", "Go 引擎（默认）",
             "软件自带的替换引擎，装好就能用，不需要额外安装任何东西。"),
            ("python", "Python 引擎",
             "改用 Python 版替换引擎执行替换阶段，便于对照排查。"),
        ):
            rc = RadioCard(title, desc, value)
            rc.chosen.connect(self._on_engine)
            self.engine_cards[value] = rc
            gl.addWidget(rc, 1)
        card.body_l.addWidget(grid)
        return card

    # ------------------------------------------------------------------ 开关槽

    def _switch_slot(self, which: str) -> QWidget:
        """开关 + 保存引用。"""
        if which == "diag":
            self.diag_sw = Switch(checked=settings.diag_enabled())
            self.diag_sw.toggled.connect(self._on_diag)
            return self.diag_sw
        raise ValueError(which)

    # ------------------------------------------------------------------ 状态

    def _build_status(self, root: QVBoxLayout) -> None:
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        root.addWidget(self.status)

    def _say(self, text: str, kind: str = "ok") -> None:
        palette = {
            "ok":   ("success.bg", "success", "success.border"),
            "warn": ("warning.bg", "warning", "warning.border"),
            "info": ("info.bg", "info", "info.border"),
        }
        bg, fg, border = palette.get(kind, palette["info"])
        self.status.setText(text)
        self.status.setStyleSheet(
            f"background:{c(bg)};color:{c(fg)};border:1px solid {c(border)};"
            f"border-radius:{r('md')};padding:8px 10px;font-size:{fs('sm')}")
        self.status.setVisible(True)

    # ------------------------------------------------------------------ 动作

    def _choose_vocab_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "选择自定义词库存储位置", str(settings.vocab_dir() or ""))
        if not d:
            return
        settings.set_vocab_dir(d)
        self.vocab_dir_changed.emit()
        self._sync_vocab()
        self._say(f"自定义词库存储位置已改为：{d}", "ok")

    def _reset_vocab_dir(self) -> None:
        settings.set_vocab_dir(None)
        self.vocab_dir_changed.emit()
        self._sync_vocab()
        self._say("自定义词库存储位置已恢复为软件默认位置。", "ok")

    def _choose_log_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "选择诊断日志目录", str(settings.log_dir() or ""))
        if not d:
            return
        settings.set_log_dir(d)
        self._apply_log_backend()
        self._sync_log()
        self._say(f"诊断日志目录已改为：{d}，之后的记录会写在那里。", "ok")

    def _reset_log_dir(self) -> None:
        settings.set_log_dir(None)
        self._apply_log_backend()
        self._sync_log()
        self._say("诊断日志目录已恢复为软件默认位置。", "ok")

    def _apply_log_backend(self) -> None:
        """把日志目录 / 留痕开关应用到错误中心（立即生效）。"""
        if error_center is None:
            return
        try:
            d = settings.log_dir()
            if d is not None:
                error_center.init(str(d), enabled=settings.diag_enabled())
            else:
                error_center.init(enabled=settings.diag_enabled())
        except Exception:                              # noqa: BLE001
            pass

    def _open_log_dir(self) -> None:
        """打开诊断日志目录（T2.4 qt_bridge.open_log_dir）。"""
        if error_center is None:
            self._say("诊断日志功能没有装好，这一项暂时用不了。", "warn")
            return
        try:
            from fixtext_error_center.qt_bridge import open_log_dir
        except Exception:                              # noqa: BLE001
            self._say("诊断日志功能没有装好，这一项暂时用不了。", "warn")
            return
        try:
            ok = bool(open_log_dir())
        except Exception:                              # noqa: BLE001
            ok = False
        if ok:
            self._say("已经在文件管理器里打开诊断日志目录。", "ok")
        else:
            self._say("没能自动打开文件夹。你可以照着上面那行位置自己找过去。", "warn")

    def _on_diag(self, on: bool) -> None:
        settings.set_diag_enabled(on)
        self._apply_log_backend()
        self._say("出错时自动保留现场：已开启。" if on else "出错时自动保留现场：已关闭。",
                  "ok" if on else "warn")

    def _on_engine(self, value: str) -> None:
        settings.set_engine(value)
        self._sync_engine()
        name = "Go 引擎" if value == "go" else "Python 引擎"
        self._say(f"替换引擎已切换为 {name}，下一次校正开始时使用。", "ok")
        self.engine_changed.emit(value)

    # ------------------------------------------------------------------ 同步

    def _sync_from_settings(self) -> None:
        self._sync_vocab()
        self._sync_log()
        if self.diag_sw.isChecked() != settings.diag_enabled():
            self.diag_sw.setChecked(settings.diag_enabled())
        self._sync_engine()

    def _sync_vocab(self) -> None:
        d = settings.vocab_dir()
        self.vocab_path[1].setText(
            str(d) if d is not None else "使用软件自带的默认位置")
        self.vocab_reset_btn.setVisible(d is not None)

    def _sync_log(self) -> None:
        d = settings.log_dir()
        if d is not None:
            self.log_path[1].setText(str(d))
        elif error_center is not None:
            try:
                self.log_path[1].setText(error_center.log_dir())
            except Exception:                          # noqa: BLE001
                self.log_path[1].setText("第一次出错时会自动建好")
        else:
            self.log_path[1].setText("第一次出错时会自动建好")
        self.log_reset_btn.setVisible(d is not None)

    def _sync_engine(self) -> None:
        cur = settings.engine()
        for v, rc in self.engine_cards.items():
            rc.set_selected(v == cur)


def px(value: str) -> int:
    return int(str(value).replace("px", ""))
