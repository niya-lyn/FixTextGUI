"""
FixText V1 · 导入书籍模块（Qt 移植）
=====================================

对照 `FixText_V1_导入书籍_原型.html` **1:1 移植**，保持核心价值：
**导入即复制、原文件只读 + 编码零配置自动转 UTF-8**，全程人话提示、不暴露内部概念。

结构：拖放 / 文件选择双通道 → 3 步（EPUB）/ 2 步（TXT）向导 → 导入安全说明
      → 进度（可取消、不留半成品、自动快照）→ 结果卡（编码 / 大小 / 章节 + 后续动作）。

用到的复用部件见 `fixtext_widgets.py`（Card / hline / px）。
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QFileDialog, QDialog, QCheckBox, QSizePolicy,
)

from fixtext_tokens import c, sp, r, fs, FONT_WEIGHT
from fixtext_widgets import Card, hline, px, RadioCard, ProgressDialog


# ---------------------------------------------------------------------------
# 数据（与 HTML 原型同源）
# ---------------------------------------------------------------------------

SAMPLES = {
    "epub": {"name": "《星河彼端》.epub", "size": "18.4 MB", "enc": "UTF-8",
             "encHint": "已是 UTF-8，无需转换", "kind": "epub"},
    "txt":  {"name": "《旧巷杂记》.txt", "size": "2.1 MB", "enc": "GBK",
             "encHint": "检测到 GBK，已自动转为 UTF-8", "kind": "txt"},
}

CHAPS = [
    "第一章 坠落之始", "第二章 无名信笺", "第三章 旧港夜雨",
    "第四章 星图残页", "第五章 归途", "第六章 彼端",
]


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _clear(layout):
    """清空一个布局并销毁其中的控件（含嵌套布局）。

    必须先 setParent(None) 再 deleteLater：deleteLater 是延迟删除，若只调用它，
    旧控件在下一次事件循环前仍可见并停留在旧位置，重渲染时会与新内容叠加。
    """
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
            continue
        sub = item.layout()
        if sub is not None:
            _clear(sub)
            sub.deleteLater()


# ---------------------------------------------------------------------------
# 拖放 / 选择双通道
# ---------------------------------------------------------------------------

class DropZone(QFrame):
    """拖放区：点击选择文件；拖入释放接收路径；两个示例书按钮。"""

    browse_requested = Signal()
    drop_received = Signal(str)
    sample_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._base = (
            f"QFrame#DropZone{{background:{c('neutral.0')};"
            f"border:2px dashed {c('neutral.300')};border-radius:{r('lg')};"
            f"padding:{sp('8')} {sp('6')}}}"
        )
        self._hover = (
            f"QFrame#DropZone{{background:{c('primary.50')};"
            f"border:2px dashed {c('primary.500')};border-radius:{r('lg')};"
            f"padding:{sp('8')} {sp('6')}}}"
        )
        self.setStyleSheet(self._base)
        self._build()

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 24, 20, 24)
        v.setSpacing(8)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)

        ico = QLabel("📥")
        ico.setStyleSheet("font-size:34px")
        t = QLabel("把书拖到这里，或点击选择文件")
        t.setStyleSheet(f"font-weight:700;font-size:{fs('md')};color:{c('neutral.800')}")
        d = QLabel("支持 TXT / EPUB · 导入后自动复制到工作区，原文件不会被修改")
        d.setStyleSheet(f"font-size:{fs('xs')};color:{c('neutral.500')}")

        s = QHBoxLayout()
        s.setSpacing(10)
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b1 = QPushButton("示例：《星河彼端》.epub")
        b1.setObjectName("BtnOutline")
        b1.setCursor(Qt.CursorShape.PointingHandCursor)
        b1.clicked.connect(lambda: self.sample_requested.emit("epub"))
        b2 = QPushButton("示例：《旧巷杂记》.txt")
        b2.setObjectName("BtnOutline")
        b2.setCursor(Qt.CursorShape.PointingHandCursor)
        b2.clicked.connect(lambda: self.sample_requested.emit("txt"))
        s.addWidget(b1)
        s.addWidget(b2)

        v.addWidget(ico)
        v.addWidget(t)
        v.addWidget(d)
        v.addLayout(s)

    def mousePressEvent(self, event):
        # 点在示例按钮上时不触发浏览
        w = self.childAt(event.pos())
        if isinstance(w, QPushButton):
            return
        self.browse_requested.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(self._hover)
        else:
            event.ignore()

    def dragLeaveEvent(self, _event):
        self.setStyleSheet(self._base)

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.setStyleSheet(self._base)
            self.drop_received.emit(urls[0].toLocalFile())
        event.acceptProposedAction()


# ---------------------------------------------------------------------------
# 向导步骤指示条
# ---------------------------------------------------------------------------

class WizardSteps(QWidget):
    """水平步骤指示：已完成=绿、当前=主色、未到=中性。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hl = QHBoxLayout(self)
        self._hl.setContentsMargins(0, 0, 0, 0)
        self._hl.setSpacing(0)
        self._hl.setAlignment(Qt.AlignmentFlag.AlignLeft)

    def set_steps(self, names, current):
        _clear(self._hl)
        n = len(names)
        for i, name in enumerate(names):
            done = i < current
            active = i == current
            w = QWidget()
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(7)
            hl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            dot = QLabel("✓" if done else str(i + 1))
            dot.setFixedSize(22, 22)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if done:
                dot.setStyleSheet(
                    f"background:{c('success')};color:#fff;border-radius:999px;"
                    f"font-size:11px;font-weight:700")
            elif active:
                dot.setStyleSheet(
                    f"background:{c('primary.500')};color:#fff;border-radius:999px;"
                    f"font-size:11px;font-weight:700")
            else:
                dot.setStyleSheet(
                    f"background:{c('neutral.100')};color:{c('neutral.500')};"
                    f"border-radius:999px;font-size:11px;font-weight:700")

            lab = QLabel(name)
            if active:
                lab.setStyleSheet(
                    f"color:{c('primary.700')};font-weight:700;font-size:{fs('sm')}")
            elif done:
                lab.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('sm')}")
            else:
                lab.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('sm')}")

            hl.addWidget(dot)
            hl.addWidget(lab)
            self._hl.addWidget(w)

            if i < n - 1:
                line = QFrame()
                line.setFixedSize(40, 2)
                line.setStyleSheet(
                    f"background:{'success' and c('success') if done else c('neutral.100')};"
                    f"border:none")
                self._hl.addWidget(line)


# ---------------------------------------------------------------------------
# 导入进度 Modal（可取消、不留半成品、自动快照）
# ---------------------------------------------------------------------------

class ImportProgressDialog(ProgressDialog):
    """导入进度弹窗：只是把通用 ProgressDialog 配上导入语义的标题与说明。"""

    def __init__(self, name: str, steps: list, on_finish, parent=None):
        super().__init__(
            icon="\U0001F4E5",
            title=f"正在导入 {name}",
            note="原文件保持只读，导入的是复制到工作区的副本。",
            steps=steps,
            on_finish=on_finish,
            finish_text="导入完成",
            parent=parent,
        )


# ---------------------------------------------------------------------------
# 模块
# ---------------------------------------------------------------------------

class ImportModule(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cur = None
        self.wstep = 0
        self.imp_mode = "direct"
        self.basis_labels = []
        self._result_basis = None

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_status)

        self._build()

    # ------------------------------------------------------------------ 构建

    def _btn(self, text: str, obj: str = "BtnOutline", slot=None) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(obj)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        if slot is not None:
            b.clicked.connect(slot)
        return b

    def _card(self, *args, **kwargs) -> Card:
        card = Card(*args, **kwargs)
        if card.basis is not None:
            self.basis_labels.append(card.basis)
        return card

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(px(sp("4")))

        root.addWidget(self._head())
        root.addWidget(self._drop_card())
        root.addWidget(self._wizard_card())
        root.addWidget(self._safety_card())
        root.addWidget(self._result_slot())
        root.addWidget(self._legend())
        root.addWidget(self._status_label())

    def _head(self) -> QWidget:
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel("导入书籍")
        title.setStyleSheet(
            f"color:{c('neutral.900')};font-size:{fs('2xl')};"
            f"font-weight:{FONT_WEIGHT['bold']}")
        sub = QLabel(
            "拖放或选择 TXT / EPUB；自动识别编码并转为 UTF-8，导入即复制到工作区，"
            "不触碰原文件。"
        )
        sub.setStyleSheet(f"color:{c('neutral.600')};font-size:{fs('md')}")
        col.addWidget(title)
        col.addWidget(sub)
        hl.addLayout(col, 1)

        self.basis_cb = QCheckBox("显示设计依据")
        self.basis_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.basis_cb.toggled.connect(self._toggle_basis)
        hl.addWidget(self.basis_cb, 0, Qt.AlignmentFlag.AlignTop)
        return w

    def _drop_card(self) -> Card:
        card = self._card(
            "拖放或选择文件", "导入后自动复制到工作区，原文件不会被修改",
            basis="§2.2 入口① · 验收① 双通道",
        )
        dz = DropZone()
        dz.browse_requested.connect(self._browse)
        dz.drop_received.connect(self._on_drop)
        dz.sample_requested.connect(self.pick_file)
        card.body_l.addWidget(dz)
        return card

    def _wizard_card(self) -> Card:
        card = self._card(
            "导入向导", "EPUB 走 3 步（含章节预览）；TXT 走 2 步",
            collapsible=True, open_=True, basis="§2.7.3 · 3 步向导",
        )
        card.body_l.setSpacing(px(sp("3")))  # 步骤条与正文之间留出间距
        self.wiz_steps = WizardSteps()
        card.body_l.addWidget(self.wiz_steps)

        self.wiz_body_w = QWidget()
        self.wiz_body = QVBoxLayout(self.wiz_body_w)
        self.wiz_body.setContentsMargins(0, 0, 0, 0)
        self.wiz_body.setSpacing(10)
        card.body_l.addWidget(self.wiz_body_w)

        card.setVisible(False)  # 选定文件前隐藏（与原型 display:none 一致）
        self.wizard_card = card
        return card

    def _safety_card(self) -> Card:
        card = self._card(
            "导入安全说明", collapsible=True, open_=True,
            basis="§2.4.3 底线① · 只读保护 + 人话提示",
        )
        ul = QLabel(
            "• 导入即把书<b>复制</b>到内部工作区，绝不直接修改你原来的文件"
            "（验收①「原文件字节不被修改」）。<br>"
            "• 编码自动识别（UTF-8 / GBK / GB18030），转换时以人话提示，"
            "<b>不出现任何命令行窗口</b>。<br>"
            "• EPUB 导入不暴露 spine / OPF 等内部概念。"
        )
        ul.setWordWrap(True)
        ul.setStyleSheet(
            f"color:{c('neutral.700')};font-size:{fs('sm')};line-height:1.9")
        card.body_l.addWidget(ul)
        return card

    def _result_slot(self) -> QWidget:
        self.result_slot_w = QWidget()
        self.result_slot_l = QVBoxLayout(self.result_slot_w)
        self.result_slot_l.setContentsMargins(0, 0, 0, 0)
        self.result_slot_l.setSpacing(0)
        return self.result_slot_w

    def _legend(self) -> QLabel:
        lab = QLabel(
            "勾选「显示设计依据」可看到每个 UI 元素对应的文档条款，"
            "证明不是把命令面板直接包装成产品。"
        )
        lab.setWordWrap(True)
        lab.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('xs')}")
        return lab

    def _status_label(self) -> QLabel:
        self.status = QLabel("")
        self.status.setVisible(False)
        self.status.setWordWrap(True)
        # 给一个合理下限，避免短消息被挤成两行
        self.status.setMinimumWidth(240)
        self.status.setStyleSheet(
            f"background:{c('neutral.800')};color:#FFFFFF;"
            f"border-radius:{r('md')};padding:10px 16px;font-size:{fs('sm')}")
        self.status.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed,
        )
        return self.status

    # ------------------------------------------------------------------ 交互

    def _toggle_basis(self, on: bool):
        alive = []
        for b in self.basis_labels:
            try:
                b.setVisible(bool(on))
                alive.append(b)
            except RuntimeError:
                # 底层 C++ 对象已随结果卡销毁，丢弃这个悬空引用
                pass
        self.basis_labels = alive

    def toast(self, msg: str):
        self.status.setText(msg)
        self.status.setVisible(True)
        self._toast_timer.start(2600)

    def _hide_status(self):
        self.status.setVisible(False)

    # ---- 选书 ----

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择文件", "", "TXT / EPUB (*.txt *.epub)")
        if path:
            self._start_with(self._make_cur_from_path(path))

    def _on_drop(self, path: str):
        self._start_with(self._make_cur_from_path(path))

    def _make_cur_from_path(self, path: str) -> dict:
        name = os.path.basename(path)
        try:
            size = f"{os.path.getsize(path) / 1024 / 1024:.1f} MB"
        except OSError:
            size = "—"
        kind = "epub" if name.lower().endswith(".epub") else "txt"
        return {"name": name, "size": size, "enc": "自动识别",
                "encHint": "将自动识别编码并转 UTF-8", "kind": kind}

    def pick_file(self, kind: str):
        """示例书按钮 / 拖放 / 浏览 的统一入口。"""
        self.cur = dict(SAMPLES[kind])
        self.wstep = 0
        self.imp_mode = "direct"
        self.wizard_card.setVisible(True)
        self._render_wiz()
        self.toast(f"已选择 {self.cur['name']}")

    def _start_with(self, cur: dict):
        self.cur = cur
        self.wstep = 0
        self.imp_mode = "direct"
        self.wizard_card.setVisible(True)
        self._render_wiz()
        self.toast(f"已选择 {self.cur['name']}")

    # ---- 向导 ----

    def _wiz_steps(self) -> list:
        if not self.cur:
            return []
        return (["选择文件", "EPUB 导入方式", "预览章节列表"]
                if self.cur["kind"] == "epub"
                else ["选择文件", "确认导入"])

    def _render_wiz(self):
        if not self.cur:
            return
        names = self._wiz_steps()
        self.wiz_steps.set_steps(names, self.wstep)
        _clear(self.wiz_body)

        last = self.wstep == len(names) - 1

        if self.wstep == 0:
            self.wiz_body.addWidget(self._info_line("文件", self.cur["name"]))
            self.wiz_body.addWidget(self._info_line("大小", self.cur["size"]))
            self.wiz_body.addWidget(
                self._info_line("编码", f"{self.cur['enc']} · {self.cur['encHint']}"))
            self.wiz_body.addWidget(self._hint(
                "编码与换行符转换在导入时自动执行，不作为可选项。"))
            self.wiz_body.addWidget(self._basis(
                "§2.7.1 第 1 项 · 导入时机自动处理"))

        elif self.cur["kind"] == "epub" and self.wstep == 1:
            opt = QLabel("EPUB 导入方式")
            opt.setStyleSheet(
                f"font-weight:700;font-size:{fs('sm')};color:{c('neutral.800')}")
            self.wiz_body.addWidget(opt)
            rrow = QHBoxLayout()
            rrow.setSpacing(px(sp("3")))
            r1 = RadioCard("直接处理 EPUB", "内部先合并为工作文本，导出时还原", "direct")
            r2 = RadioCard("先转成 TXT", "得到同名 TXT 再处理", "totxt")
            r1.chosen.connect(lambda m="direct": self._set_mode(m, [r1, r2]))
            r2.chosen.connect(lambda m="totxt": self._set_mode(m, [r1, r2]))
            self._set_mode(self.imp_mode, [r1, r2])
            rrow.addWidget(r1, 1)
            rrow.addWidget(r2, 1)
            self.wiz_body.addLayout(rrow)
            self.wiz_body.addWidget(self._basis(
                "原 5 号 bat 的参数空间以选项形式露在向导里，不设独立入口 · §2.7.3"))

        elif self.cur["kind"] == "epub" and self.wstep == 2:
            self.wiz_body.addWidget(
                self._info_line("章节顺序", "严格按原书顺序合并"))
            cl = QVBoxLayout()
            cl.setSpacing(6)
            for i, ch in enumerate(CHAPS):
                cl.addWidget(self._chapter_row(i, ch))
            self.wiz_body.addLayout(cl)
            order_row = QHBoxLayout()
            order_row.addWidget(self._btn(
                "顺序有问题，反馈一下", "BtnOutline", self._order_issue))
            order_row.addStretch(1)
            self.wiz_body.addLayout(order_row)
            self.wiz_body.addWidget(self._hint(
                "合并时按原书顺序插入章节边界标记，导出时据此还原。"))
            self.wiz_body.addWidget(self._basis(
                "章节顺序异常由 ChapterAnalyzer 提示 · §2.7.3"))

        else:  # TXT 末步
            self.wiz_body.addWidget(self._info_line("文件", self.cur["name"]))
            self.wiz_body.addWidget(
                self._info_line("编码", f"{self.cur['enc']} → 已转为 UTF-8"))
            self.wiz_body.addWidget(self._hint(
                "TXT 无章节结构，跳过章节预览，可直接导入。"))

        # 导航
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 14, 0, 0)
        nav.setSpacing(10)
        nav.addWidget(QLabel(f"第 {self.wstep + 1} / {len(names)} 步"))
        nav.addStretch(1)
        prev = self._btn("上一步", "BtnOutline", self._prev_wiz)
        prev.setEnabled(self.wstep > 0)
        nxt = self._btn(
            "开始导入" if last else "下一步",
            "BtnPrimary" if last else "BtnOutline",
            self._next_wiz)
        nav.addWidget(prev)
        nav.addWidget(nxt)
        self.wiz_body.addLayout(nav)

    def _set_mode(self, m: str, cards):
        self.imp_mode = m
        for card in cards:
            card.set_selected(card.value == m)

    def _info_line(self, label: str, value: str) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        l = QLabel(label)
        l.setStyleSheet(
            f"font-weight:700;min-width:64px;color:{c('neutral.700')};"
            f"font-size:{fs('sm')}")
        v = QLabel(value)
        v.setStyleSheet(f"color:{c('neutral.800')};font-size:{fs('sm')}")
        row.addWidget(l)
        row.addWidget(v, 1)
        return w

    def _hint(self, text: str) -> QLabel:
        h = QLabel(text)
        h.setWordWrap(True)
        h.setStyleSheet(
            f"font-size:{fs('xs')};color:{c('neutral.500')};margin-top:6px")
        return h

    def _basis(self, text: str) -> QLabel:
        """设计依据（条款号 / 内部组件名）：默认隐藏，随「显示设计依据」出现。

        内部概念不进常态文案——这是「藏内部概念」原则在向导内的落地。
        """
        b = QLabel(f"设计依据 · {text}")
        b.setWordWrap(True)
        b.setStyleSheet(
            f"font-size:{fs('xs')};color:{c('neutral.500')};margin-top:6px")
        b.setVisible(self.basis_cb.isChecked())
        self.basis_labels.append(b)
        return b

    def _chapter_row(self, i: int, title: str) -> QFrame:
        row = QFrame()
        row.setObjectName("ChapterRow")
        row.setStyleSheet(
            f"QFrame#ChapterRow{{background:{c('neutral.50')};border:1px solid "
            f"{c('neutral.100')};border-radius:{r('md')}}}")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(10, 8, 10, 8)
        hl.setSpacing(10)
        no = QLabel(str(i + 1))
        no.setFixedSize(22, 22)
        no.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no.setStyleSheet(
            f"background:{c('neutral.100')};color:{c('neutral.500')};"
            f"border-radius:6px;font-size:11px;font-weight:700")
        t = QLabel(title)
        t.setStyleSheet(f"color:{c('neutral.800')};font-size:{fs('sm')}")
        hl.addWidget(no)
        hl.addWidget(t)
        return row

    def _prev_wiz(self):
        if self.wstep > 0:
            self.wstep -= 1
            self._render_wiz()

    def _next_wiz(self):
        names = self._wiz_steps()
        if self.wstep >= len(names) - 1:
            self.do_import()
            return
        self.wstep += 1
        self._render_wiz()

    def _order_issue(self):
        self.toast("已记录：章节顺序存疑，导入后可在「检查问题」复核")

    # ---- 执行导入 ----

    def do_import(self):
        if not self.cur:
            return
        is_e = self.cur["kind"] == "epub"
        steps = [
            {"name": "复制到工作区", "desc": "原文件保持只读，不做任何修改", "dur": 800},
            {"name": "编码与换行转换", "desc": self.cur["encHint"], "dur": 900},
        ]
        if is_e:
            steps.append({
                "name": "EPUB 文本合并",
                "desc": "直接处理" if self.imp_mode == "direct" else "先转成同名 TXT",
                "dur": 1500,
            })
        steps.append({
            "name": "创建初始快照",
            "desc": "导入后即可随时恢复到此状态",
            "dur": 600,
        })

        dlg = ImportProgressDialog(
            self.cur["name"], steps, on_finish=self._on_import_done, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.toast("导入完成，已自动创建快照")
        else:
            self.toast("已取消导入，未留下任何半成品文件")

    def _on_import_done(self):
        # 上一张结果卡即将销毁 → 先摘掉它的 basis 悬空引用
        if self._result_basis is not None:
            try:
                if self._result_basis in self.basis_labels:
                    self.basis_labels.remove(self._result_basis)
            except Exception:
                pass
            self._result_basis = None
        _clear(self.result_slot_l)
        is_e = self.cur["kind"] == "epub"
        card = self._card(basis="§2.2 入口① · 验收② 编码零配置")
        self._result_basis = card.basis

        hl = QHBoxLayout()
        hl.setSpacing(12)
        ico = QLabel("✓")
        ico.setFixedSize(34, 34)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background:{c('success')};color:#fff;border-radius:10px;font-size:18px")
        col = QVBoxLayout()
        col.setSpacing(2)
        name_l = QLabel(f"{self.cur['name']} 已导入工作区")
        name_l.setStyleSheet(f"font-weight:700;font-size:{fs('md')};color:{c('neutral.900')}")
        meta_l = QLabel(
            f"原文件未被修改 · 已创建初始快照"
            f"{' · 已按章节顺序合并' if is_e else ''}")
        meta_l.setStyleSheet(f"font-size:{fs('xs')};color:{c('neutral.500')}")
        col.addWidget(name_l)
        col.addWidget(meta_l)
        hl.addWidget(ico)
        hl.addLayout(col, 1)
        card.body_l.addLayout(hl)

        kv = QHBoxLayout()
        kv.setContentsMargins(0, 14, 0, 4)
        kv.setSpacing(px(sp("8")))
        kv.addWidget(self._kv("编码", f"{self.cur['enc']} → UTF-8"))
        kv.addWidget(self._kv("大小", self.cur["size"]))
        kv.addWidget(self._kv("章节", f"{len(CHAPS)} 章" if is_e else "—"))
        kv.addStretch(1)
        card.body_l.addLayout(kv)

        acts = QHBoxLayout()
        acts.setContentsMargins(0, 6, 0, 0)
        acts.setSpacing(10)
        acts.addWidget(self._btn(
            "⚡ 去一键校正", "BtnPrimary",
            lambda: self.toast("原型示意：下一步进入「一键校正」")))
        acts.addWidget(self._btn(
            "🔍 先检查问题", "BtnOutline",
            lambda: self.toast("原型示意：进入「检查问题」")))
        acts.addWidget(self._btn(
            "↺ 恢复到导入时", "BtnOutline",
            lambda: self.toast("已恢复到刚导入的状态（快照）")))
        acts.addStretch(1)
        card.body_l.addLayout(acts)

        self.result_slot_l.addWidget(card)

    def _kv(self, k: str, v: str) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        kl = QLabel(k)
        kl.setStyleSheet(f"font-size:{fs('xs')};color:{c('neutral.500')}")
        vl = QLabel(v)
        vl.setStyleSheet(
            f"font-weight:700;font-size:{fs('md')};color:{c('primary.700')}")
        col.addWidget(kl)
        col.addWidget(vl)
        # 两行标签叠放，必须声明最小高度：否则空间吃紧时上下行会压在一起
        w.setMinimumHeight(40)
        return w
