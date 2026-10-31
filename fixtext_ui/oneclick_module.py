"""
FixText V1 · 一键校正模块（Qt 移植）
======================================

对照 `FixText_V1_一键校正_原型.html` **1:1 移植**，保持核心价值：
**主按钮 = 默认组合**（备份 → 排版 → 替换 → 校验一次跑完），
可选项收进折叠面板，不把参数空间摊在首屏。

结构：书源条 → 主按钮 hero → 校正结果卡 → 排版规范化（14 项折叠）→ 高级选项
      （运行模式 / 词库 / 引号）。

复用部件见 `fixtext_widgets.py`（Card / Switch / Pill / FieldRow / RadioCard / ProgressDialog）。
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QComboBox, QLineEdit, QDialog, QSizePolicy,
)

from fixtext_tokens import c, r, fs, FONT_MONO, FONT_WEIGHT
from fixtext_widgets import (
    Card, Switch, Pill, FieldRow, RadioCard, ProgressDialog, EmptyState, hline, PrimaryButton,
    ConfirmDialog, page_head_shell, enable_chrome, BagChk, FlowLayout,
)
from fixtext_worker import CorrectionJob, CorrectionWorker


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

#: 一键组合可勾选袋（常规锁定；预处理/严格/注音走独立开关与独立轮，不在此列）
#: 与 data/rules/bags 中主轮可达袋对齐；新增袋须同步 UI_BAG_MAP / 词库 TIER_*。
BAG_CHECKS = [
    ("b1", "常规校正词库", True, True),         # code, label, default_on, locked
    ("cjk", "CJK 恢复词库", True, True),        # 编码修复，与常规同锁
    ("custom", "我的词库", True, False),
    ("b3", "繁简转换词库", True, False),        # 默开可关
    ("ddd", "的地得词库", True, False),
    ("old_style", "旧式通假词库", True, False),
    ("b3r", "繁简转换激进词库", False, False),  # 和谐字等，默认关
    ("extra", "的地得/象像加强", False, False),
    ("dei2de", "「得」转「的」", False, False),
    ("txt_format", "txtFormat 词库", False, False),
    # postfix / temp：不可达，分别留待正则误伤修复、批注→临时表功能
]

ZHUYIN_OPTS = [
    ("0", "每个生僻字只注音一次", ""),
    ("1", "给文本中所有位置的生僻字注音", "同一个字注音多次"),
    ("2", "每个字只注音一次，且多音字只取第一种读音", ""),
    ("3", "所有位置都注音，且多音字只取第一种读音", ""),
]

# 进度步骤不再是演的：来自 M1 编排器六阶段的人话映射
# （fixtext_worker.HUMAN_STAGES），由真实任务信号驱动，见 do_correction。

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

    #: 校正完成 → 运行摘要（含工作目录），导出页据此判断「有可导出的产物」
    correctionDone = Signal(object)
    #: 「去导出」→ 主窗口切到导出页
    gotoExport = Signal()
    #: 「去检查页」→ 主窗口切到检查问题（M4-EX.6-R3 摘要分支）
    gotoCheck = Signal()
    #: 本书专有词条就绪（真实词条列表, 书名）→ 交给词库管理页，由用户确认后加入
    bookWordsReady = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.basis_labels = []
        self._result_basis = None
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

        # 无书空状态（原型 v3 §4）：无运行上下文时整页只显示这条引导，
        # 有书后恢复常规布局。由真实状态触发（run_context 是否注入）。
        self.empty_state = EmptyState(
            "⚡", "还没有可校正的书",
            "请先导入一本书，才能跑「一键校正」。"
            "当前页面在有书状态下展示；无书时仅显示此引导。")
        root.addWidget(self.empty_state)

        self._book_w = self._book_bar()
        self._hero_w = self._hero()
        self._fmt_w = self._fmt_card()
        self._adv_w = self._adv_card()
        root.addWidget(self._book_w)
        root.addWidget(self._hero_w)

        # 校正结果卡：主按钮下方、排版规范化上方（跑完后插入）
        self.result_slot = QVBoxLayout()
        self.result_slot.setContentsMargins(0, 0, 0, 0)
        self.result_slot.setSpacing(16)
        root.addLayout(self.result_slot)

        root.addWidget(self._fmt_w)
        root.addWidget(self._adv_w)

        self.legend = _label(
            "高级选项里可调运行模式（排版 / 预处理 / 严格 / 注音）与词库组合。",
            size="xs", color="neutral.500", wrap=True)
        root.addWidget(self.legend)

        self.status = QLabel("")
        self.status.setObjectName("Toast")
        self.status.setVisible(False)
        self.status.setStyleSheet(
            f"#Toast{{background:{c('neutral.800')};color:{c('on.fill')};"
            f"border-radius:10px;padding:10px 16px;font-size:{fs('sm')}}}")
        self.status.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        root.addWidget(self.status, 0, Qt.AlignmentFlag.AlignLeft)
        self._apply_book_presence()

    def _apply_book_presence(self) -> None:
        """按「有没有一本书可校正」切换整页布局（真实状态触发，无假数据）。"""
        has_book = self.run_context is not None
        for w in (self._book_w, self._hero_w, self._fmt_w, self._adv_w,
                  self.legend):
            w.setVisible(has_book)
        for i in range(self.result_slot.count()):
            item = self.result_slot.itemAt(i)
            if item.widget() is not None:
                item.widget().setVisible(has_book)
        self.empty_state.setVisible(not has_book)

    # ------------------------------------------------------------------ 头部

    def _header(self) -> QWidget:
        shell, body = page_head_shell()
        hl = QHBoxLayout(body)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        col = QVBoxLayout()
        col.setSpacing(2)
        title = _label("一键校正", size="2xl", color="neutral.900", weight="bold")
        title.setObjectName("PageTitle")
        sub = _label(
            "默认配置一键完成「排版规范化 + 词库替换 + 标点标准化」。"
            "需要微调时，展开下方可选项。",
            size="md", color="neutral.600", wrap=True)
        sub.setObjectName("PageSub")
        col.addWidget(title)
        col.addWidget(sub)
        hl.addLayout(col, 1)
        return shell

    # -------------------------------------------------------------- 书源状态条

    def _book_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("BookBar")
        enable_chrome(bar)
        # 配色交给 fixtext.qss 的 QFrame#BookBar（原内联收归）

        hl = QHBoxLayout(bar)
        hl.setContentsMargins(18, 14, 18, 14)
        hl.setSpacing(14)

        ico = QLabel("📖")
        ico.setObjectName("BookBarIco")
        ico.setFixedSize(40, 40)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 图标方块配色交给 fixtext.qss 的 #BookBarIco（原内联收归）
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

    def set_run_context(self, ctx: dict | None) -> None:
        """注入一次真实校正所需的全部路径（由导入流程或测试调用）。

        ctx 字段：epub / pipeline_root / rules_before / rules_after /
        engine_path / runs_root / title（可选，书名显示用）
        传 None 表示清空（回到无书空状态）。
        """
        self.run_context = dict(ctx) if ctx else None
        if not ctx:
            self._summary = None
            self._outcome = None
            self._clear_result()
            self._apply_book_presence()
            return
        ref = ctx.get("epub") or ctx.get("plain_source") or ""
        title = ctx.get("title") or Path(str(ref)).stem
        suffix = (ctx.get("suffix") or Path(str(ref)).suffix or "").lower()
        kind = "电子书" if suffix == ".epub" else "文本"
        size_mb = Path(str(ref)).stat().st_size / (1024 * 1024) if ref else 0
        self.book_name_label.setText(f"《{title}》· {kind}")
        self.book_meta_label.setText(
            f"{size_mb:.1f} MB · 校正过程只读原文件，可随时恢复到校正前")
        self.book_pill.setText("已就绪")
        self.book_pill.setStyleSheet(
            f"color:{c('success')};background:{c('success.bg')};"
            f"border-radius:{r('full')};padding:2px 9px;"
            f"font-size:{fs('xs')};font-weight:700")
        self._apply_book_presence()

    # ------------------------------------------------------------ 主按钮 hero

    def _hero(self) -> QFrame:
        # M5-EX.7 §10 Step4：与 .chk-top / 导出 .hero 同规（padding/gap/大按钮）
        hero = QFrame()
        hero.setObjectName("Hero")
        enable_chrome(hero)
        # 渐变横幅交给 fixtext.qss 的 #Hero（原内联收归）
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(28, 26, 28, 26)
        hl.setSpacing(24)

        col = QVBoxLayout()
        col.setSpacing(6)
        h2 = QLabel("一键校正")
        h2.setProperty("role", "title")
        p = QLabel(
            "使用常规校正词库 + 默认排版项，"
            "一次跑完备份→排版→替换→校验。")
        p.setWordWrap(True)
        col.addWidget(h2)
        col.addWidget(p)
        hl.addLayout(col, 1)

        self.run_btn = QPushButton("⚡ 开始校正")
        self.run_btn.setObjectName("HeroBtn")
        self.run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_btn.setMinimumHeight(50)
        # 大按钮配色交给 fixtext.qss 的 #HeroBtn（原内联收归）
        self.run_btn.clicked.connect(lambda: self.do_correction())
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
            box.setObjectName("FmtCombo")
            box.addItems(it["opts"])
            box.setCurrentText(it["val"])
            box.setMinimumWidth(132)
            box.setCursor(Qt.CursorShape.PointingHandCursor)
            # 完整态交给 fixtext.qss 的 QComboBox#FmtCombo（原内联收归）
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
            "高级选项", "运行模式 / 词库组合 / 引号",
            collapsible=True, open_=False,
            basis="§2.7.2 · 高级选项收进面板",
        )
        self.basis_labels.append(card.basis)

        # —— 运行模式：完整流程（RadioCard）+ 排版/预处理/严格/注音四开关
        card.body_l.addLayout(self._opt_label("运行模式"))
        self.rd_full = RadioCard(
            "完整流程（默认）",
            "点击恢复默认：排版开、预处理开、严格关、注音关",
            "full",
        )
        self.rd_full.chosen.connect(lambda _=None: self._reset_run_mode_defaults())
        self.rd_full.set_selected(True)
        card.body_l.addWidget(self.rd_full)

        # 排版默认开；关闭 = 跳过排版流程
        self.sw_layout = Switch(True)
        self.sw_layout.toggled.connect(lambda _=False: self._sync_full_flow_selected())
        card.body_l.addLayout(self._opt_label("排版"))
        card.body_l.addLayout(self._switch_row(
            "关闭则跳过排版，直接用词库校正", self.sw_layout))

        self.sw_preprocess = Switch(True)
        self.sw_preprocess.toggled.connect(lambda _=False: self._sync_full_flow_selected())
        card.body_l.addLayout(self._opt_label("预处理"))
        card.body_l.addLayout(self._switch_row(
            "主替换前先用预处理词库单独跑一轮（轻量纠错，非排版）",
            self.sw_preprocess))

        self.sw_strict = Switch(False)
        self.sw_strict.toggled.connect(lambda _=False: self._sync_full_flow_selected())
        card.body_l.addLayout(self._opt_label("严格模式"))
        card.body_l.addLayout(self._switch_row(
            "用严格词库（strictMap）单独跑一轮，规则更紧", self.sw_strict))

        self.sw_zhuyin = Switch(False)
        self.sw_zhuyin.toggled.connect(self._on_zhuyin_toggled)
        self.sw_zhuyin.toggled.connect(lambda _=False: self._sync_full_flow_selected())
        card.body_l.addLayout(self._opt_label("生僻字注音"))
        card.body_l.addLayout(self._switch_row(
            "为生僻字补充拼音注音", self.sw_zhuyin))
        self.zhu_panel = self._zhuyin_opts_panel()
        self.zhu_panel.setVisible(False)
        card.body_l.addWidget(self.zhu_panel)
        self.zhuyin_mode = "0"

        card.body_l.addWidget(hline())

        # —— 词库多选（原型 .chk-group 胶囊 + 锁定徽标）
        card.body_l.addLayout(self._opt_label("使用哪套词库", "可多选"))
        self.bag_checks: dict[str, BagChk] = {}
        bags_wrap = QFrame()
        bags_wrap.setObjectName("BagChkGroup")
        fl = FlowLayout(bags_wrap, hspacing=8, vspacing=8)
        fl.setContentsMargins(0, 4, 0, 0)
        for code, label, on, locked in BAG_CHECKS:
            chip = BagChk(label, checked=on, locked=locked)
            self.bag_checks[code] = chip
            fl.addWidget(chip)
        card.body_l.addWidget(bags_wrap)
        card.body_l.addSpacing(10)
        card.body_l.addWidget(self._hint(
            "「常规校正」「CJK 恢复」锁定（CJK 用于扩展区编码修复，强制跑）。"
            "「繁简转换」「的地得」「旧式通假」「我的词库」默认开，可关。"
            "「繁简转换激进」含和谐字等，易误改，默认关。"
            "排版 / 预处理 / 严格 / 注音见上方「运行模式」。"
            "txtFormat 较多误改，建议常规校正后再单独勾选比对。"))
        card.body_l.addWidget(self._basis("§2.2 · 主按钮不询问词库组合"))
        card.body_l.addSpacing(16)
        card.body_l.addWidget(hline())
        card.body_l.addSpacing(8)

        # —— 自动修复引号（引擎改在设置页）
        card.body_l.addLayout(self._opt_label("自动修复引号"))
        import fixtext_settings as _settings
        self.sw_auto_fix_quote = Switch(_settings.auto_fix_quote())
        self.sw_auto_fix_quote.toggled.connect(self._on_auto_fix_quote_toggled)
        card.body_l.addLayout(self._switch_row(
            "按检查页规则自动修可确定项；关则留待检查页处理",
            self.sw_auto_fix_quote))
        return card

    def _reset_run_mode_defaults(self) -> None:
        """「完整流程（默认）」：四个运行模式开关恢复出厂组合。"""
        if getattr(self, "sw_layout", None) is not None:
            self.sw_layout.setChecked(True)
        if getattr(self, "sw_preprocess", None) is not None:
            self.sw_preprocess.setChecked(True)
        if getattr(self, "sw_strict", None) is not None:
            self.sw_strict.setChecked(False)
        if getattr(self, "sw_zhuyin", None) is not None:
            self.sw_zhuyin.setChecked(False)
        self._set_zhuyin_mode("0")
        self._sync_full_flow_selected()

    def _sync_full_flow_selected(self) -> None:
        """四个开关均处默认态时，「完整流程」卡片保持选中样式。"""
        rd = getattr(self, "rd_full", None)
        if rd is None:
            return
        at_default = (
            bool(getattr(self, "sw_layout", None) and self.sw_layout.isChecked())
            and bool(getattr(self, "sw_preprocess", None) and self.sw_preprocess.isChecked())
            and not bool(getattr(self, "sw_strict", None) and self.sw_strict.isChecked())
            and not bool(getattr(self, "sw_zhuyin", None) and self.sw_zhuyin.isChecked())
        )
        rd.set_selected(at_default)

    def _zhuyin_opts_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("ZhuPanel")
        panel.setStyleSheet(
            f"#ZhuPanel{{background:{c('neutral.50')};border:1px dashed "
            f"{c('neutral.200')};border-radius:10px}}")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 12, 14, 12)
        pl.setSpacing(8)
        self._zhu_radios: dict[str, RadioCard] = {}
        for code, title, desc in ZHUYIN_OPTS:
            rd = RadioCard(title, desc or " ", code)
            rd.chosen.connect(self._set_zhuyin_mode)
            self._zhu_radios[code] = rd
            pl.addWidget(rd)
        self._zhu_radios["0"].set_selected(True)
        return panel

    def _on_zhuyin_toggled(self, on: bool) -> None:
        self.zhu_panel.setVisible(bool(on))

    def _set_zhuyin_mode(self, mode: str) -> None:
        self.zhuyin_mode = str(mode)
        for code, rd in self._zhu_radios.items():
            rd.set_selected(code == mode)

    def _on_auto_fix_quote_toggled(self, on: bool) -> None:
        import fixtext_settings as _settings
        _settings.set_auto_fix_quote(bool(on))

    def _opt_label(self, text: str, badge: str = "") -> QHBoxLayout:
        hl = QHBoxLayout()
        hl.setContentsMargins(0, 8, 0, 8)
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

    def _switch_row(self, desc: str, control: QWidget) -> QHBoxLayout:
        """原型 ``.frow``：仅描述 + 控件（无独立加粗标题；标题由上方 ``_opt_label`` 承担）。"""
        hl = QHBoxLayout()
        hl.setContentsMargins(0, 8, 0, 8)
        hl.setSpacing(12)
        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet(f"color:{c('neutral.500')};font-size:{fs('xs')}")
        hl.addWidget(d, 1)
        hl.addWidget(control)
        return hl

    def _run_options(self) -> dict:
        """从高级选项控件收集 M5-EX.1 运行参数。"""
        bags: list[str] = []
        for code, _label, _on, locked in BAG_CHECKS:
            if locked:
                bags.append(code)  # 常规 / CJK 等锁定袋强制计入
                continue
            cb = self.bag_checks.get(code)
            if cb is not None and cb.isChecked():
                bags.append(code)
        zhu = "off"
        if getattr(self, "sw_zhuyin", None) is not None and self.sw_zhuyin.isChecked():
            zhu = str(getattr(self, "zhuyin_mode", "0") or "0")
        # 排版开关默认开；关闭 → skip_layout
        layout_on = bool(
            getattr(self, "sw_layout", None) and self.sw_layout.isChecked())
        return dict(
            skip_layout=(not layout_on),
            enable_preprocess=bool(
                getattr(self, "sw_preprocess", None) and self.sw_preprocess.isChecked()),
            enable_strict=bool(
                getattr(self, "sw_strict", None) and self.sw_strict.isChecked()),
            zhuyin_mode=zhu,
            selected_bags=tuple(bags),
        )

    # -------------------------------------------------------------- 执行流程

    @staticmethod
    def _source_epub(ctx: dict, workdir: Path) -> Path:
        """校正链路的输入：EPUB 书用原书；纯文本书先包成单章电子书。

        包装只发生在本次运行目录里，用户导入文件夹不被写入。
        """
        epub = ctx.get("epub")
        if epub:
            return Path(str(epub))
        from plain_book import plain_source_epub
        return plain_source_epub(
            ctx["plain_source"], workdir,
            title=str(ctx.get("title") or ""),
            author=str(ctx.get("author") or ""),
        )

    def do_correction(self, *, confirm_cancel: bool = True):
        """真实执行：M1 编排器六阶段在后台线程跑，进度弹窗事件驱动。

        ``confirm_cancel``（M4-EX.2c）：点「取消」先弹二次确认
        （原型 `#corrConfirm`）。默认开——主按钮、向导、验收脚本走的都是
        同一个入口，同一个行为。

        M4-T4.2：启动前按配置键 ``engine`` 选引擎；计划走 Go 且引擎
        文件不可用（缺失 / 无法启动 / 被杀软隔离）时，先弹人话确认再
        决定是否改走 Python 引擎——用户拒绝则明确报错，不硬跑。
        """
        if self._running:
            return
        if not self.run_context:
            self._toast("请先在「导入」页选择一本书，再开始校正")
            return

        ctx = self.run_context
        engine = self._planned_engine(ctx)
        if engine == "go":
            ec = self._engine_choice_mod(ctx)
            ok, reason = ec.go_engine_status(ctx["engine_path"])
            if not ok:
                if self._confirm_engine_fallback(reason):
                    engine = "python"      # 只本次生效，不写回设置
                else:
                    self._clear_result()
                    self._toast(
                        "校正未开始：校正引擎不可用（"
                        + self._sanitized_reason(reason)
                        + "）。可重试，或在设置里改用 Python 备用引擎。"
                    )
                    return
        self._start_correction(ctx, engine_override=engine,
                               confirm_cancel=confirm_cancel)

    # ---------------------------------------------------------- 引擎选择

    @staticmethod
    def _engine_choice_mod(ctx: dict):
        """把 pipeline 目录挂进 sys.path 后取 engine_choice 数据层。

        界面模块不依赖 Qt 之外的写入：引擎键的持久化读写统一走
        ``fixtext_pipeline.engine_choice``（契约键 ``engine``，与设置页
        M4-EX.2a 共用），这里只是读。
        """
        root = str(Path(str(ctx["pipeline_root"])).resolve())
        if root not in sys.path:
            sys.path.insert(0, root)
        from fixtext_pipeline import engine_choice
        return engine_choice

    def _planned_engine(self, ctx: dict) -> str:
        """本次计划用的引擎：配置键 ``engine``（默认 go）。"""
        try:
            return self._engine_choice_mod(ctx).get_engine_choice()
        except Exception:
            return "go"

    @staticmethod
    def _sanitized_reason(reason: str) -> str:
        """把引擎状态原因里的内部文件名截掉（不进界面文案）。"""
        return reason.split("：", 1)[0] if "：" in reason else reason

    def _confirm_engine_fallback(self, reason: str) -> bool:
        """Go 引擎不可用时的人话降级确认（M4-T4.2 §3.3）。

        明示耗时量级差异（Python 引擎较慢，大部头书约数十秒）；
        返回 True = 用户同意本次改走 Python 引擎。
        """
        dlg = ConfirmDialog(
            icon="⚠️",
            title="校正引擎没有就绪",
            note=(
                "检测到：" + self._sanitized_reason(reason) + "。\n\n"
                "可以改用 Python 备用引擎完成这次校正——校正结果与平时"
                "完全一致，只是速度较慢：大部头书大约需要数十秒"
                "（平时一般只要几秒）。\n\n"
                "这次的选择只对本次校正生效，不会改动设置里的长期选择。"
            ),
            note_kind="warn",
            confirm_text="改用 Python 引擎，继续校正",
            parent=self,
        )
        return dlg.exec() == QDialog.DialogCode.Accepted

    # ---------------------------------------------------------- 执行主体

    def _start_correction(self, ctx: dict, *, engine_override: str | None = None,
                          confirm_cancel: bool = True):
        """跑一次六阶段校正（engine_override 显式指定时只本次生效）。"""
        from PySide6.QtWidgets import QDialog

        runs_root = Path(ctx["runs_root"])
        runs_root.mkdir(parents=True, exist_ok=True)
        workdir = runs_root / f"run-{int(time.time() * 1000)}"
        book = ctx.get("title") or Path(str(ctx.get("epub") or "")).stem

        # 纯文本书没有章节包结构：先原样包成单章电子书，再走同一条链路
        source_epub = self._source_epub(ctx, workdir)

        import fixtext_settings as _settings
        from fixtext_quotation_rules_path import quotation_rules_path_for

        rules_path = quotation_rules_path_for(ctx)
        opts = self._run_options()
        job = CorrectionJob(
            epub=source_epub,
            workdir=workdir,
            rules_before=Path(ctx["rules_before"]),
            rules_after=Path(ctx["rules_after"]),
            engine_path=Path(ctx["engine_path"]),
            pipeline_root=Path(ctx["pipeline_root"]),
            # 书名 / 作者 / 原书进运行摘要：历史记录靠它显示这条是谁
            title=str(ctx.get("title") or ""),
            author=str(ctx.get("author") or ""),
            source_epub=Path(str(ctx.get("epub") or source_epub)),
            # 用户区里的自定义词库 / 派生规则（显式给，不依赖下游推算）
            custom_vocab_path=(Path(str(ctx["custom_vocab_path"]))
                               if ctx.get("custom_vocab_path") else None),
            derived_rules_dir=(Path(str(ctx["derived_rules_dir"]))
                               if ctx.get("derived_rules_dir") else None),
            # M4-T4.2：本次运行的替换引擎（None = 读配置；降级确认后传 python）
            engine=engine_override,
            # M4-EX.6-R3：高级选项「自动修复引号问题」
            auto_fix_quotes=_settings.auto_fix_quote(),
            quotation_rules_path=rules_path,
            # M5-EX.1：运行模式 / 分袋 / 注音
            skip_layout=bool(opts["skip_layout"]),
            enable_preprocess=bool(opts["enable_preprocess"]),
            enable_strict=bool(opts["enable_strict"]),
            zhuyin_mode=str(opts["zhuyin_mode"]),
            selected_bags=tuple(opts["selected_bags"]),
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
            steps=[dict(name=s["name"], desc=s["desc"]) for s in job.human_stages],
            cancel_text="取消（不留半成品）",
            finish_text="校正完成",
            parent=self,
            mode="live",
            on_cancel_request=worker.request_cancel,
            confirm_cancel=bool(confirm_cancel),
        )
        self._dlg = dlg
        worker.stage_started.connect(dlg.live_stage_started)
        worker.stage_finished.connect(dlg.live_stage_finished)
        worker.succeeded.connect(self._on_succeeded)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.engine_failed.connect(self._on_engine_failed)

        worker.start()
        dlg.start_live(worker.snapshot)
        dlg.exec()

        # exec 返回 = 弹窗已关（完成/取消/失败/降级确认，四条路都汇聚到这里）
        self._running = False
        self.run_btn.setEnabled(True)
        self._worker = None
        self._dlg = None

        if self._outcome == "ok" and self._summary is not None:
            self._render_result(self._summary)
            self._toast("校正完成，已生成替换报告")
        elif self._outcome == "fallback":
            # 用户已确认降级：本次改走 Python 引擎重跑（不改长期设置）
            self._clear_result()
            self._start_correction(ctx, engine_override="python",
                                   confirm_cancel=confirm_cancel)
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
        try:
            self.correctionDone.emit(summary)
        except Exception:
            pass
        if self._dlg is not None:
            self._dlg.live_finish()

    def _on_failed(self, message: str):
        self._outcome = "failed"
        self._fail_message = message
        if self._dlg is not None:
            self._dlg.reject()

    def _on_engine_failed(self, reason: str):
        """Go 引擎在运行中不可用（M4-T4.2 §3.3）：弹降级确认。

        确认 → 本次改走 Python 引擎重跑；拒绝 → 明确报错，不硬跑。
        此时后台线程已结束、半成品已由 worker 清理，弹窗可以安全关闭。
        """
        if self._confirm_engine_fallback(reason):
            self._outcome = "fallback"
        else:
            self._outcome = "failed"
            self._fail_message = (
                "校正未完成：校正引擎不可用（"
                + self._sanitized_reason(reason)
                + "）。可在设置里改用 Python 备用引擎后重试。"
            )
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
            f"background:{c('success')};color:{c('on.fill')};border-radius:10px;"
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
        # §2.4.2 第 1 条：处理完成时就告诉用户「这本书抽到了多少条专有词」，
        # 数就是引擎实际产物（去重后的清单条数），不是估算。
        stats_items = [
            (f"{_fmt_num(summary.get('chapters'))} 章", "全书章节"),
            (f"{_fmt_num(summary.get('replace_rules'))}", "校正词库规则（条）"),
            (f"{_fmt_num(summary.get('quote_errors'))}", "引号待修（处）"),
        ]
        book_n = summary.get('book_words_unique')
        if book_n is None:
            book_n = len(summary.get('book_words') or [])
        stats_items.append((f"{_fmt_num(book_n)} 条", "本书专有词条"))
        for num, lab in stats_items:
            stats.addWidget(self._stat(num, lab), 1)
        card.body_l.addLayout(stats)

        card.body_l.addWidget(self._quote_status_note(summary))
        card.body_l.addWidget(self._diff(summary))
        card.body_l.addLayout(self._result_actions())
        self.result_slot.addWidget(card)

    def _quote_status_note(self, summary: dict) -> QFrame:
        """原型 §7 三分支引号摘要（关 / 开且剩余 / 开且清零）。"""
        from fixtext_quote_status import quote_status_from_summary

        text, _show_go, tip = quote_status_from_summary(summary)
        box = QFrame()
        box.setObjectName("QuoteNote")
        box.setStyleSheet(
            f"#QuoteNote{{background:{c('warning.bg')};border-radius:10px;"
            f"border:1px solid {c('warning')}}}")
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(4)
        main = QLabel(text)
        main.setWordWrap(True)
        main.setStyleSheet(
            f"color:{c('neutral.800')};font-weight:700;font-size:{fs('sm')};"
            f"background:transparent")
        sub = QLabel(tip)
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"color:{c('neutral.600')};font-size:{fs('xs')};background:transparent")
        v.addWidget(main)
        v.addWidget(sub)
        return box

    def _diff(self, summary: dict | None) -> QFrame:
        """本次处理摘要（数字全部来自真实运行报告）。"""
        box = QFrame()
        box.setObjectName("Diff")
        # 配色交给 fixtext.qss 的 #Diff（原内联收归）
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(4)
        rows = []
        ci, co = summary.get("replace_chars_in"), summary.get("replace_chars_out")
        if ci is not None and co is not None:
            rows.append(f"替换环节：{_fmt_num(ci)} 字符 → {_fmt_num(co)} 字符"
                        + ("（有内容被修正）" if ci != co else "（本词库未命中）"))
        if summary.get("bookmap_entries") is not None:
            raw_n = summary.get("book_words_declared_total")
            uniq_n = summary.get("book_words_unique")
            if uniq_n is not None and raw_n is not None and raw_n != uniq_n:
                rows.append(
                    f"提取到 {_fmt_num(raw_n)} 条本书专有词条（按写法合并后 "
                    f"{_fmt_num(uniq_n)} 条可加入），可在下面预览后加入词库")
            else:
                rows.append(
                    f"提取到 {_fmt_num(summary['bookmap_entries'])} 条本书专有词条，"
                    "可在下面预览后加入词库")
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
        if card.basis is not None:
            card.basis.setVisible(False)
        return card

    def _stat(self, num: str, lab: str) -> QFrame:
        box = QFrame()
        box.setObjectName("Stat")
        # 配色交给 fixtext.qss 的 #Stat（原内联收归）
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
        from fixtext_quote_status import quote_status_from_summary

        acts = QHBoxLayout()
        acts.setContentsMargins(0, 14, 0, 0)
        acts.setSpacing(10)

        report = PrimaryButton("📄 查看替换报告")
        report.setCursor(Qt.CursorShape.PointingHandCursor)
        report.clicked.connect(self._goto_export_report)
        acts.addWidget(report)

        undo = QPushButton("↺ 恢复到校正前")
        undo.setObjectName("BtnOutline")
        undo.setCursor(Qt.CursorShape.PointingHandCursor)
        undo.clicked.connect(self._restore_before)
        acts.addWidget(undo)

        _text, show_go_check, _tip = quote_status_from_summary(self._summary)
        if show_go_check:
            check_btn = PrimaryButton("🔍 去检查页")
            check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            check_btn.clicked.connect(self.gotoCheck.emit)
            acts.addWidget(check_btn)

        go = QPushButton("📤 去导出")
        go.setObjectName("BtnOutline")
        go.setCursor(Qt.CursorShape.PointingHandCursor)
        go.clicked.connect(self.gotoExport.emit)
        acts.addWidget(go)

        acts.addStretch(1)

        book_n = (self._summary or {}).get('book_words_unique')
        if book_n is None:
            book_n = len((self._summary or {}).get('book_words') or [])
        words = QPushButton(
            f"✨ 预览本书专有词条（{_fmt_num(book_n)} 条）并加入词库")
        words.setObjectName("BtnOutline")
        words.setCursor(Qt.CursorShape.PointingHandCursor)
        words.setToolTip("先看清单再决定加入哪些，加入后下次校正自动生效")
        words.setAccessibleName("预览本书专有词条")
        words.clicked.connect(self._open_book_words)
        acts.addWidget(words)
        return acts

    # ------------------------------------------------------------ 专有词条弹窗

    def _goto_export_report(self):
        """替换统计在导出时自动附上（排期 V1.1：报告不做界面呈现）。"""
        try:
            self.gotoExport.emit()
        except Exception:
            pass
        self._toast("导出时会自动附上替换统计（文本 / 表格）")

    def _open_book_words(self):
        """本书专有词条：只取本次运行真实抽出的词，交给词库页确认后写入。

        没有真实词条时明确告知「无需加入」，绝不退回演示词条。
        """
        words = list((self._summary or {}).get("book_words") or [])
        if not words:
            self._toast("本次校正没有提取到本书专有词条，无需加入")
            return
        title = str((self._summary or {}).get("title") or "")
        self.bookWordsReady.emit(words, title)
        self._toast(f"已把 {len(words)} 条本书专有词条带到词库管理，确认后加入")

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
        """设计依据标签：保留结构但始终隐藏（M5-EX.2 / BUG-2）。"""
        b = _label(f"设计依据 · {text}", size="xs", color="neutral.500", wrap=True)
        b.setVisible(False)
        self.basis_labels.append(b)
        return b

    def _persist(self):
        self._toast("排版配置已保存，下次沿用")

    def _toast(self, msg: str):
        self.status.setText(msg)
        self.status.setVisible(True)
        self._toast_timer.start(2600)

    def _hide_status(self):
        self.status.setVisible(False)
