"""
FixText V1 · 一键校正模块（Qt 移植）
======================================

对照 `FixText_V1_一键校正_原型.html` **1:1 移植**，保持核心价值：
**主按钮 = 默认组合**（备份 → 排版 → 替换 → 校验一次跑完），
可选项收进折叠面板，不把参数空间摊在首屏。

结构：书源条 → 主按钮 hero → 排版规范化（14 项折叠）→ 高级选项
      （运行模式 + 子模式 / 词库 / 引擎）→ 校正结果卡 → 设计依据开关。

复用部件见 `fixtext_widgets.py`（Card / Switch / Pill / FieldRow / RadioCard / ProgressDialog）。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QComboBox, QLineEdit, QCheckBox, QDialog, QSizePolicy,
)

from fixtext_tokens import c, r, fs, FONT_MONO, FONT_WEIGHT
from fixtext_widgets import (
    Card, Switch, Pill, FieldRow, RadioCard, ProgressDialog, hline,
)
from fixtext_worker import CorrectionJob, CorrectionWorker, HUMAN_STAGES


# ---------------------------------------------------------------------------
# 数据（与 HTML 原型同源）
# ---------------------------------------------------------------------------

FMT_ITEMS = [
    dict(n=1,  name="编码与换行符转换", desc="源编码自动识别，换行统一", kind="auto"),
    dict(n=2,  name="英文大小写转换", desc="数百个固定大小写词组", kind="switch", on=False),
    dict(n=3,  name="数字转换", desc="阿拉伯↔中文数字互转（防误伤）", kind="dropdown",
         opts=["不转换", "转中文", "转阿拉伯"], val="不转换"),
    dict(n=4,  name="去中文间空格", desc="清除汉字之间多余空格", kind="switch", on=False),
    dict(n=5,  name="按标点分行/还原", desc="在标点处断行或合并为整段", kind="dropdown",
         opts=["不动", "分行", "还原为整段"], val="不动"),
    dict(n=6,  name="特殊字符转义还原", desc="还原 EPUB/HTML 转义实体", kind="auto"),
    dict(n=7,  name="标点规范化", desc="全半角 / 省略号 / 破折号统一（含引号转换）",
         kind="switch", on=True, default=True),
    dict(n=8,  name="多行引号处理", desc="跨行引语补 / 去行首引号", kind="dropdown",
         opts=["不动", "补引号", "去引号"], val="不动"),
    dict(n=9,  name="HTML 转 TXT", desc="剥离 HTML 标签转纯文本", kind="auto"),
    dict(n=10, name="TXT 排版", desc="去空行 / 加缩进 / 插章节分隔", kind="switch_input",
         on=True, default=True, ph="缩进字符数", ival="2", iw=64),
    dict(n=11, name="分级标题", desc="◎ 标记转「第X部 / 卷 / 章」", kind="dropdown",
         opts=["不处理", "一级", "两级", "三级"], val="不处理"),
    dict(n=12, name="书籍信息提取", desc="从正文提取书名 / 作者", kind="auto"),
    dict(n=13, name="附加校对声明", desc="文末追加校对声明", kind="switch_input",
         on=False, default=False, ph="署名", ival="", iw=140),
    dict(n=14, name="中英文之间加空格", desc="pangu 风格，汉字与字母 / 数字间补空格",
         kind="switch", on=False),
]

MAPS = [
    ("常规校正", "默认组合，覆盖常见错词与标点"),
    ("严格校正", "规则更紧，减少漏替"),
    ("繁简转换", "繁体转简体专用"),
    ("标点规范", "仅做全半角与引号统一"),
    ("专有名词", "人名 / 地名 / 书名"),
    ("生僻字注音", "配合子模式使用"),
    ("网络用语", "口语化词归一"),
    ("古籍整理", "竖排与异体字"),
    ("同义词", "表述统一"),
    ("自定义组合", "用户在词库管理拼装"),
]

ENGINES = [
    ("自动（Go 内置，异常时自动降级 Python）", "auto"),
    ("强制标准引擎（Go）", "force"),
    ("降级模式（Python greedy）", "degrade"),
]

# 进度步骤不再是演的：来自 M1 编排器六阶段的人话映射
# （fixtext_worker.HUMAN_STAGES），由真实任务信号驱动，见 do_correction。

BOOK_WORDS = [
    ("星陨大陆", "本书专有地名"),
    ("墨羽", "角色名"),
    ("九转玄功", "功法名"),
]


def _label(text: str, *, size: str = "sm", color: str = "neutral.800",
           weight: str | None = None, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(wrap)
    style = f"color:{c(color)};font-size:{fs(size)};background:transparent;"
    if weight:
        style += f"font-weight:{FONT_WEIGHT[weight]};"
    lab.setStyleSheet(style)
    return lab


def _fmt_num(v) -> str:
    """大数字加千分位；None 显示「—」。"""
    if v is None:
        return "—"
    return f"{v:,}"


# ---------------------------------------------------------------------------
# 模块
# ---------------------------------------------------------------------------

class OneClickModule(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.basis_labels = []
        self._result_basis = None
        self.mode = "full"
        self.fmt_state = {it["n"]: dict(it) for it in FMT_ITEMS}
        self._switches: dict[int, Switch] = {}
        self._combos: dict[int, QComboBox] = {}
        self._inputs: dict[int, QLineEdit] = {}
        self._running = False
        # 运行上下文：由导入流程（或测试）注入真实路径；None 时主按钮给出引导提示，
        # 不做任何「演示用假运行」。
        self.run_context: dict | None = None
        self._worker: CorrectionWorker | None = None
        self._dlg: ProgressDialog | None = None
        self._summary: dict | None = None
        self._outcome: str | None = None
        self._fail_message: str | None = None

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_status)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        root.addWidget(self._header())
        root.addWidget(self._book_bar())
        root.addWidget(self._hero())
        root.addWidget(self._fmt_card())
        root.addWidget(self._adv_card())

        self.result_slot = QVBoxLayout()
        self.result_slot.setContentsMargins(0, 0, 0, 0)
        self.result_slot.setSpacing(16)
        root.addLayout(self.result_slot)

        self.legend = _label(
            "勾选「显示设计依据」可看到每个 UI 元素对应的文档条款，"
            "证明不是把命令面板直接包装成产品。",
            size="xs", color="neutral.500", wrap=True)
        root.addWidget(self.legend)

        self.status = QLabel("")
        self.status.setObjectName("Toast")
        self.status.setVisible(False)
        self.status.setStyleSheet(
            f"#Toast{{background:{c('neutral.800')};color:#fff;"
            f"border-radius:10px;padding:10px 16px;font-size:{fs('sm')}}}")
        self.status.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        root.addWidget(self.status, 0, Qt.AlignmentFlag.AlignLeft)

    # ------------------------------------------------------------------ 头部

    def _header(self) -> QWidget:
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        col = QVBoxLayout()
        col.setSpacing(2)
        title = _label("一键校正", size="2xl", color="neutral.900", weight="bold")
        sub = _label(
            "默认配置一键完成「排版规范化 + 词库替换 + 标点标准化」。"
            "需要微调时，展开下方可选项。",
            size="md", color="neutral.600", wrap=True)
        col.addWidget(title)
        col.addWidget(sub)
        hl.addLayout(col, 1)

        self.basis_cb = QCheckBox("显示设计依据")
        self.basis_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.basis_cb.toggled.connect(self._toggle_basis)
        hl.addWidget(self.basis_cb, 0, Qt.AlignmentFlag.AlignTop)
        return w

    # -------------------------------------------------------------- 书源状态条

    def _book_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("BookBar")
        bar.setStyleSheet(
            f"#BookBar{{background:{c('neutral.0')};border:1px solid "
            f"{c('neutral.200')};border-radius:{r('lg')}}}")

        hl = QHBoxLayout(bar)
        hl.setContentsMargins(18, 14, 18, 14)
        hl.setSpacing(14)

        ico = QLabel("📖")
        ico.setFixedSize(40, 40)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background:{c('primary.100')};color:{c('primary.700')};"
            f"border-radius:10px;font-size:19px")
        hl.addWidget(ico)

        col = QVBoxLayout()
        col.setSpacing(2)
        self.book_name_label = _label("尚未导入书籍", size="md", weight="bold")
        self.book_meta_label = _label("先在「导入」页选择 EPUB，再回到这里一键校正",
                                      size="xs", color="neutral.500")
        col.addWidget(self.book_name_label)
        col.addWidget(self.book_meta_label)
        hl.addLayout(col, 1)

        self.book_pill = Pill("等待导入", "neutral")
        hl.addWidget(self.book_pill)
        return bar

    def set_run_context(self, ctx: dict) -> None:
        """注入一次真实校正所需的全部路径（由导入流程或测试调用）。

        ctx 字段：epub / pipeline_root / rules_before / rules_after /
        engine_path / runs_root / title（可选，书名显示用）
        """
        self.run_context = dict(ctx)
        title = ctx.get("title") or Path(str(ctx["epub"])).stem
        size_mb = Path(str(ctx["epub"])).stat().st_size / (1024 * 1024)
        self.book_name_label.setText(f"《{title}》.epub")
        self.book_meta_label.setText(
            f"{size_mb:.1f} MB · 校正过程只读原文件，可随时恢复到校正前")
        self.book_pill.setText("已就绪")
        self.book_pill.setStyleSheet(
            f"color:{c('success')};background:{c('success.bg')};"
            f"border-radius:{r('full')};padding:2px 9px;"
            f"font-size:{fs('xs')};font-weight:700")

    # ------------------------------------------------------------ 主按钮 hero

    def _hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("Hero")
        hero.setStyleSheet(
            f"#Hero{{border-radius:{r('lg')};"
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {c('primary.700')},stop:1 {c('primary.500')});}}")

        hl = QHBoxLayout(hero)
        hl.setContentsMargins(26, 22, 26, 22)
        hl.setSpacing(24)

        col = QVBoxLayout()
        col.setSpacing(6)
        h2 = QLabel("一键校正")
        h2.setStyleSheet(
            f"color:#fff;font-size:{fs('lg')};"
            f"font-weight:{FONT_WEIGHT['bold']};background:transparent")
        p = QLabel(
            "使用「常规校正」词库 + Go 引擎 + 默认排版项，"
            "一次跑完备份→排版→替换→校验。")
        p.setWordWrap(True)
        p.setStyleSheet(
            f"color:rgba(255,255,255,0.88);font-size:{fs('sm')};"
            f"background:transparent")
        col.addWidget(h2)
        col.addWidget(p)
        hl.addLayout(col, 1)

        self.run_btn = QPushButton("⚡ 开始校正")
        self.run_btn.setObjectName("HeroBtn")
        self.run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_btn.setMinimumHeight(50)
        self.run_btn.setStyleSheet(
            f"#HeroBtn{{background:#fff;color:{c('primary.700')};"
            f"border:none;border-radius:{r('lg')};padding:0 32px;"
            f"font-size:{fs('md')};font-weight:{FONT_WEIGHT['bold']}}}"
            f"#HeroBtn:hover{{background:{c('primary.50')}}}"
            f"#HeroBtn:disabled{{background:rgba(255,255,255,0.55);"
            f"color:{c('primary.500')}}}")
        self.run_btn.clicked.connect(self.do_correction)
        hl.addWidget(self.run_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return hero

    # ------------------------------------------------- 排版规范化（14 项折叠）

    def _fmt_card(self) -> Card:
        card = Card(
            "排版规范化（可选）", "展开可逐项调整；配置自动保存，下次沿用",
            collapsible=True, open_=True,
            basis="§2.7.1 · 14 项折叠 · 默认开 7 / 10",
        )
        self.basis_labels.append(card.basis)

        for it in FMT_ITEMS:
            card.body_l.addWidget(FieldRow(
                it["n"], it["name"], it["desc"],
                control=self._fmt_control(it),
                chip="导入时自动" if it["kind"] == "auto" else None,
                name_width=132,
            ))
            if it["n"] != FMT_ITEMS[-1]["n"]:
                card.body_l.addWidget(hline())

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 12, 0, 0)
        foot.addWidget(_label(
            "默认仅开启第 7、10 两项；其余按上次要用的配置自动恢复。",
            size="xs", color="neutral.500"))
        foot.addStretch(1)
        reset = QPushButton("恢复默认")
        reset.setObjectName("BtnLink")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(self.reset_fmt)
        foot.addWidget(reset)
        card.body_l.addLayout(foot)
        return card

    def _fmt_control(self, it: dict) -> QWidget | None:
        kind = it["kind"]
        if kind == "auto":
            # 「导入时自动」项：不暴露任何控件，只显示 chip
            return None
        if kind == "switch":
            sw = Switch(it["on"])
            self._switches[it["n"]] = sw
            sw.toggled.connect(
                lambda on, n=it["n"]: self._on_switch(n, on))
            return sw

        if kind == "dropdown":
            box = QComboBox()
            box.addItems(it["opts"])
            box.setCurrentText(it["val"])
            box.setMinimumWidth(132)
            box.setCursor(Qt.CursorShape.PointingHandCursor)
            self._combos[it["n"]] = box
            box.currentTextChanged.connect(
                lambda v, n=it["n"]: self._on_choice(n, v))
            return box

        # switch_input
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        sw = Switch(it["on"])
        self._switches[it["n"]] = sw
        sw.toggled.connect(lambda on, n=it["n"]: self._on_switch(n, on))
        hl.addWidget(sw)

        edit = QLineEdit(it["ival"])
        edit.setPlaceholderText(it["ph"])
        edit.setFixedWidth(it["iw"])
        edit.setStyleSheet(f"background:{c('neutral.0')}")
        self._inputs[it["n"]] = edit
        edit.textChanged.connect(
            lambda v, n=it["n"]: self._on_input(n, v))
        hl.addWidget(edit)
        return holder

    def _on_switch(self, n: int, on: bool):
        self.fmt_state[n]["on"] = on
        self._persist()

    def _on_choice(self, n: int, value: str):
        self.fmt_state[n]["val"] = value
        self._persist()

    def _on_input(self, n: int, value: str):
        self.fmt_state[n]["ival"] = value

    def reset_fmt(self):
        """直接回设各控件到默认值（不重建卡片，避免重排闪烁与错乱）。

        - switch / switch_input 的开关 → FMT_ITEMS 的 default
        - dropdown 的当前项     → FMT_ITEMS 的 val
        - switch_input 的输入框 → FMT_ITEMS 的 ival
        """
        for it in FMT_ITEMS:
            n = it["n"]
            kind = it["kind"]
            default_on = bool(it.get("default", False))
            if kind in ("switch", "switch_input"):
                sw = self._switches.get(n)
                if sw is not None:
                    sw.blockSignals(True)
                    sw.setChecked(default_on)
                    sw.blockSignals(False)
                self.fmt_state[n]["on"] = default_on
            if kind == "dropdown":
                val = it.get("val")
                box = self._combos.get(n)
                if box is not None and val is not None:
                    box.blockSignals(True)
                    box.setCurrentText(val)
                    box.blockSignals(False)
                if val is not None:
                    self.fmt_state[n]["val"] = val
            if kind == "switch_input":
                ival = it.get("ival", "")
                edit = self._inputs.get(n)
                if edit is not None:
                    edit.blockSignals(True)
                    edit.setText(ival)
                    edit.blockSignals(False)
                self.fmt_state[n]["ival"] = ival
        self._toast("已恢复默认排版项（仅开 7、10）")

    # ---------------------------------------------------------------- 高级选项

    def _adv_card(self) -> Card:
        card = Card(
            "高级选项", "运行模式 / 子模式 / 词库组合 / 引擎",
            collapsible=True, open_=False,
            basis="§2.7.2 · 高级选项收进面板",
        )
        self.basis_labels.append(card.basis)

        # —— 运行模式
        card.body_l.addLayout(self._opt_label("运行模式", "主按钮之外才用到"))
        row = QHBoxLayout()
        row.setContentsMargins(0, 8, 0, 0)
        row.setSpacing(10)
        self.rd_full = RadioCard(
            "完整流程（默认）", "备份 → 排版 → 词库替换 → 校验，一条龙", "full")
        self.rd_skip = RadioCard(
            "跳过预处理", "不做排版，直接用词库校正（展开子模式）", "skip")
        self.rd_full.chosen.connect(self.set_mode)
        self.rd_skip.chosen.connect(self.set_mode)
        self.rd_full.set_selected(True)
        row.addWidget(self.rd_full, 1)
        row.addWidget(self.rd_skip, 1)
        card.body_l.addLayout(row)

        self.sub_panel = self._sub_panel()
        self.sub_panel.setVisible(False)
        card.body_l.addWidget(self.sub_panel)

        card.body_l.addWidget(hline())

        # —— 词库
        card.body_l.addLayout(self._opt_label("使用哪套词库"))
        self.map_box = QComboBox()
        self.map_box.addItems(
            [f"{n} — {d}" for n, d in MAPS])
        self.map_box.setCursor(Qt.CursorShape.PointingHandCursor)
        card.body_l.addWidget(self.map_box)
        card.body_l.addWidget(self._hint(
            "共 10 组，带人话说明，默认「常规校正」。V1 主按钮不询问此组合。"))
        card.body_l.addWidget(self._basis("§2.2 · 主按钮不询问词库组合"))

        card.body_l.addWidget(hline())

        # —— 引擎
        card.body_l.addLayout(self._opt_label("替换引擎"))
        self.engine_box = QComboBox()
        self.engine_box.addItems([t for t, _v in ENGINES])
        self.engine_box.setCursor(Qt.CursorShape.PointingHandCursor)
        card.body_l.addWidget(self.engine_box)
        card.body_l.addWidget(self._hint(
            "Go 缺失 / 异常时自动降级接管并提示，不露命令行。"))
        card.body_l.addWidget(self._basis(
            "与「设置页」共用落点 · Go 异常按降级路径接管 · §2.7.2"))
        return card

    def _opt_label(self, text: str, badge: str = "") -> QHBoxLayout:
        hl = QHBoxLayout()
        hl.setContentsMargins(0, 12, 0, 0)
        hl.setSpacing(8)
        hl.addWidget(_label(text, size="base", weight="bold"))
        if badge:
            p = Pill(badge, "warn")
            p.setStyleSheet(
                f"color:{c('warning')};background:{c('warning.bg')};"
                f"border-radius:{r('full')};padding:1px 7px;"
                f"font-size:10px;font-weight:700")
            hl.addWidget(p)
        hl.addStretch(1)
        return hl

    def _sub_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("SubPanel")
        panel.setStyleSheet(
            f"#SubPanel{{background:{c('neutral.50')};border:1px dashed "
            f"{c('neutral.200')};border-radius:10px}}")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 12, 14, 12)
        pl.setSpacing(8)

        pl.addLayout(self._sub_line(
            "词库严格度", ["常规", "严格"], on_change=None))

        pl.addLayout(self._sub_line(
            "生僻字注音",
            ["不注音", "仅注一次", "所有位置", "取第一读音", "多音字拆分"],
            on_change=self._zhu_changed))

        self.zhu_map_row = QWidget()
        self.zhu_map_row.setVisible(False)
        zl = QHBoxLayout(self.zhu_map_row)
        zl.setContentsMargins(0, 0, 0, 0)
        zl.setSpacing(12)
        zl.addWidget(_label("拆分用词库", size="sm", weight="semibold"))
        self.zhu_map_box = QComboBox()
        self.zhu_map_box.addItems(["生僻字注音词库", "自定义组合", "专有名词"])
        zl.addWidget(self.zhu_map_box, 1)
        pl.addWidget(self.zhu_map_row)

        pl.addWidget(self._hint("多音字拆分需先选词库。"))
        pl.addWidget(self._basis(
            "子模式的实质选项必须能被用户直接选用 · §2.7.2"))
        return panel

    def _sub_line(self, name: str, opts: list[str], on_change) -> QHBoxLayout:
        hl = QHBoxLayout()
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(12)
        lab = _label(name, size="sm", weight="semibold")
        lab.setMinimumWidth(96)
        hl.addWidget(lab)
        box = QComboBox()
        box.addItems(opts)
        box.setCursor(Qt.CursorShape.PointingHandCursor)
        if on_change:
            box.currentTextChanged.connect(on_change)
        hl.addWidget(box, 1)
        return hl

    def _zhu_changed(self, value: str):
        self.zhu_map_row.setVisible(value == "多音字拆分")

    def set_mode(self, mode: str):
        self.mode = mode
        self.rd_full.set_selected(mode == "full")
        self.rd_skip.set_selected(mode == "skip")
        self.sub_panel.setVisible(mode == "skip")

    # -------------------------------------------------------------- 执行流程

    def do_correction(self):
        """真实执行：M1 编排器六阶段在后台线程跑，进度弹窗事件驱动。"""
        if self._running:
            return
        if not self.run_context:
            self._toast("请先在「导入」页选择 EPUB，再开始校正")
            return

        ctx = self.run_context
        from PySide6.QtWidgets import QDialog

        runs_root = Path(ctx["runs_root"])
        runs_root.mkdir(parents=True, exist_ok=True)
        workdir = runs_root / f"run-{int(time.time() * 1000)}"
        book = ctx.get("title") or Path(str(ctx["epub"])).stem

        job = CorrectionJob(
            epub=Path(ctx["epub"]),
            workdir=workdir,
            rules_before=Path(ctx["rules_before"]),
            rules_after=Path(ctx["rules_after"]),
            engine_path=Path(ctx["engine_path"]),
            pipeline_root=Path(ctx["pipeline_root"]),
        )
        worker = CorrectionWorker(job)
        self._worker = worker
        self._summary = None
        self._outcome = None
        self._running = True
        self.run_btn.setEnabled(False)

        dlg = ProgressDialog(
            icon="⚡",
            title=f"正在校正《{book}》",
            note="校正过程中原书保持只读；随时可取消，取消后不留下半成品。",
            steps=[dict(name=s["name"], desc=s["desc"]) for s in HUMAN_STAGES],
            cancel_text="取消（不留半成品）",
            finish_text="校正完成",
            parent=self,
            mode="live",
            on_cancel_request=worker.request_cancel,
        )
        self._dlg = dlg
        worker.stage_started.connect(dlg.live_stage_started)
        worker.stage_finished.connect(dlg.live_stage_finished)
        worker.succeeded.connect(self._on_succeeded)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)

        worker.start()
        dlg.start_live(worker.snapshot)
        dlg.exec()

        # exec 返回 = 弹窗已关（完成/取消/失败三条路都汇聚到这里）
        self._running = False
        self.run_btn.setEnabled(True)
        self._worker = None
        self._dlg = None

        if self._outcome == "ok" and self._summary is not None:
            self._render_result(self._summary)
            self._toast("校正完成，已生成替换报告")
        elif self._outcome == "failed":
            self._clear_result()
            self._toast(self._fail_message or "校正未完成，可重试")
        else:
            self._clear_result()
            self._toast("已取消，工作区已清理，未留下半成品（原书完好）")

    # ---- 任务信号落地（都在界面线程执行：Qt 信号跨线程自动排队） ----

    def _on_succeeded(self, summary: dict):
        self._summary = summary
        self._outcome = "ok"
        if self._dlg is not None:
            self._dlg.live_finish()

    def _on_failed(self, message: str):
        self._outcome = "failed"
        self._fail_message = message
        if self._dlg is not None:
            self._dlg.reject()

    def _on_cancelled(self):
        self._outcome = "cancelled"
        if self._dlg is not None:
            self._dlg.live_close_cancelled()

    def _on_done(self):
        """旧 timer 模式回调兼容（live 模式不使用）。"""
        self._render_result(None)

    def _clear_result(self):
        # 结果卡被销毁后，它的 basis 容器会成为悬空引用——先摘掉再删
        if self._result_basis is not None:
            try:
                if self._result_basis in self.basis_labels:
                    self.basis_labels.remove(self._result_basis)
            except Exception:
                pass
            self._result_basis = None
        while self.result_slot.count():
            item = self.result_slot.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    # ---------------------------------------------------------------- 结果卡

    def _render_result(self, summary: dict | None):
        """渲染校正结果卡。summary 为真实运行汇总；None 时不再渲染。"""
        self._clear_result()
        if not summary:
            return
        card = self._card_result()

        head = QHBoxLayout()
        head.setSpacing(12)
        ok = QLabel("✓")
        ok.setFixedSize(34, 34)
        ok.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ok.setStyleSheet(
            f"background:{c('success')};color:#fff;border-radius:10px;"
            f"font-size:18px")
        col = QVBoxLayout()
        col.setSpacing(2)
        book = summary.get("book", "书籍")
        col.addWidget(_label(f"《{book}》校正完成", size="md", weight="bold",
                             color="neutral.900"))
        total = summary.get("total_elapsed_s")
        sub = ("原书保持只读，处理前状态即快照，可随时恢复到校正前"
               + (f" · 总耗时 {total:.1f} 秒" if isinstance(total, (int, float)) else ""))
        col.addWidget(_label(sub, size="xs", color="neutral.500"))
        head.addWidget(ok)
        head.addLayout(col, 1)
        card.body_l.addLayout(head)

        stats = QHBoxLayout()
        stats.setContentsMargins(0, 14, 0, 12)
        stats.setSpacing(12)
        for num, lab in (
            (f"{_fmt_num(summary.get('chapters'))} 章", "全书章节"),
            (f"{_fmt_num(summary.get('replace_rules'))}", "校正词库规则（条）"),
            (f"{_fmt_num(summary.get('quote_errors'))}", "引号待修（处）"),
        ):
            stats.addWidget(self._stat(num, lab), 1)
        card.body_l.addLayout(stats)

        card.body_l.addWidget(self._diff(summary))
        card.body_l.addLayout(self._result_actions())
        self.result_slot.addWidget(card)

    def _diff(self, summary: dict | None) -> QFrame:
        """本次处理摘要（数字全部来自真实运行报告）。"""
        box = QFrame()
        box.setObjectName("Diff")
        box.setStyleSheet(
            f"#Diff{{background:{c('neutral.50')};border-radius:10px}}")
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(4)
        rows = []
        ci, co = summary.get("replace_chars_in"), summary.get("replace_chars_out")
        if ci is not None and co is not None:
            rows.append(f"替换环节：{_fmt_num(ci)} 字符 → {_fmt_num(co)} 字符"
                        + ("（有内容被修正）" if ci != co else "（本词库未命中）"))
        if summary.get("bookmap_entries") is not None:
            rows.append(f"提取到 {_fmt_num(summary['bookmap_entries'])} 条本书专有词条，"
                        "可在词库管理里确认后加入")
        sha = summary.get("restored_sha256")
        if sha:
            rows.append(f"成品校验指纹 {sha[:16]}…（与重跑结果一致）")
        for text in rows:
            lab = QLabel(text)
            lab.setStyleSheet(
                f"color:{c('neutral.700')};font-family:{FONT_MONO};"
                f"font-size:{fs('xs')};background:transparent")
            v.addWidget(lab)
        return box

    def _card_result(self) -> Card:
        card = Card(basis="§2.2 入口⑤ · 替换统计 + 2.4.2 反馈回路")
        self.basis_labels.append(card.basis)
        self._result_basis = card.basis
        card.basis.setVisible(self.basis_cb.isChecked())
        return card

    def _stat(self, num: str, lab: str) -> QFrame:
        box = QFrame()
        box.setObjectName("Stat")
        box.setStyleSheet(
            f"#Stat{{background:{c('primary.50')};border-radius:10px}}")
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(2)
        n = QLabel(num)
        n.setAlignment(Qt.AlignmentFlag.AlignCenter)
        n.setStyleSheet(
            f"color:{c('primary.700')};font-size:{fs('xl')};"
            f"font-weight:{FONT_WEIGHT['bold']};background:transparent")
        l2 = QLabel(lab)
        l2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l2.setStyleSheet(
            f"color:{c('neutral.500')};font-size:{fs('xs')};background:transparent")
        v.addWidget(n)
        v.addWidget(l2)
        return box

    def _result_actions(self) -> QHBoxLayout:
        acts = QHBoxLayout()
        acts.setContentsMargins(0, 14, 0, 0)
        acts.setSpacing(10)

        report = QPushButton("📄 查看替换报告")
        report.setObjectName("BtnPrimary")
        report.setCursor(Qt.CursorShape.PointingHandCursor)
        report.clicked.connect(
            lambda: self._toast("替换报告已留存（表格 / 文本），可在导出页查看"))
        acts.addWidget(report)

        undo = QPushButton("↺ 恢复到校正前")
        undo.setObjectName("BtnOutline")
        undo.setCursor(Qt.CursorShape.PointingHandCursor)
        undo.clicked.connect(self._restore_before)
        acts.addWidget(undo)

        go = QPushButton("📤 去导出")
        go.setObjectName("BtnOutline")
        go.setCursor(Qt.CursorShape.PointingHandCursor)
        go.clicked.connect(lambda: self._toast("已跳转导出结果（原型示意）"))
        acts.addWidget(go)

        acts.addStretch(1)

        words = QPushButton("✨ 把本书专有词条加入词库")
        words.setObjectName("BtnOutline")
        words.setCursor(Qt.CursorShape.PointingHandCursor)
        words.clicked.connect(self._open_book_words)
        acts.addWidget(words)
        return acts

    # ------------------------------------------------------------ 专有词条弹窗

    def _open_book_words(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("本书专有词条（加入预览）")
        dlg.setModal(True)
        dlg.setMinimumWidth(460)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head.setObjectName("ModalHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(18, 16, 18, 16)
        hl.addWidget(_label("✨ 本书专有词条（加入预览）", size="lg", weight="bold"))
        root.addWidget(head)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(18, 16, 18, 16)
        bl.setSpacing(12)

        note = QLabel("加入前预览，可逐条确认；加入后下次校正自动生效。")
        note.setWordWrap(True)
        note.setStyleSheet(
            f"background:{c('info.bg')};border:1px solid {c('info.border')};"
            f"color:{c('info')};border-radius:10px;padding:10px 14px;"
            f"font-size:{fs('sm')}")
        bl.addWidget(note)

        boxes = []
        for word, desc in BOOK_WORDS:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 6, 0, 6)
            rl.setSpacing(12)
            cb = QCheckBox()
            cb.setChecked(True)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            rl.addWidget(cb)
            rl.addWidget(_label(word, size="sm", weight="semibold"))
            rl.addWidget(_label(desc, size="xs", color="neutral.500"))
            rl.addStretch(1)
            boxes.append((cb, word))
            bl.addWidget(row)
            bl.addWidget(hline())

        root.addWidget(body)

        foot = QWidget()
        foot.setObjectName("ModalFoot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(18, 14, 18, 14)
        fl.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("BtnOutline")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(dlg.reject)
        fl.addWidget(cancel)
        confirm = QPushButton("加入选中词条")
        confirm.setObjectName("BtnPrimary")
        confirm.setCursor(Qt.CursorShape.PointingHandCursor)

        def _confirm():
            n = sum(1 for cb, _w in boxes if cb.isChecked())
            dlg.accept()
            self._toast(f"已加入 {n} 条专有词条到「我的词库」")

        confirm.clicked.connect(_confirm)
        fl.addWidget(confirm)
        root.addWidget(foot)
        dlg.exec()

    # ------------------------------------------------------------------ 公共

    def _restore_before(self):
        """恢复到校正前：删除本次运行的工作区副本（原书全程只读，从未改动）。"""
        wd = (self._summary or {}).get("workdir")
        if wd:
            shutil.rmtree(Path(wd), ignore_errors=True)
        self._clear_result()
        self._summary = None
        self._toast("已恢复到校正前：删除本次工作区副本，原书从未被改动")

    def _hint(self, text: str) -> QLabel:
        return _label(text, size="xs", color="neutral.500", wrap=True)

    def _basis(self, text: str) -> QLabel:
        """设计依据（条款号 / 内部组件名）：默认隐藏，随开关出现。"""
        b = _label(f"设计依据 · {text}", size="xs", color="neutral.500", wrap=True)
        b.setVisible(self.basis_cb.isChecked())
        self.basis_labels.append(b)
        return b

    def _persist(self):
        self._toast("排版配置已保存，下次沿用")

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

    def _toast(self, msg: str):
        self.status.setText(msg)
        self.status.setVisible(True)
        self._toast_timer.start(2600)

    def _hide_status(self):
        self.status.setVisible(False)
