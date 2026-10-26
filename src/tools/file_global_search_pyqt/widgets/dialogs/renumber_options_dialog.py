from qtpy.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QFrame,
    QButtonGroup,
)


class RenumberOptionsDialog(QDialog):
    def __init__(self, parent=None, show_sub=False, show_vol=False, show_range=False):
        super().__init__(parent)
        self.setWindowTitle("章节重排选项")
        self.setMinimumWidth(620)
        self.results = {"group_sub": False, "reset_vol": False, "keep_range": False}
        self._setup_ui(show_sub, show_vol, show_range)

    def _setup_ui(self, show_sub, show_vol, show_range):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>请选择重排逻辑（默认选项已预选）：</b>"))
        layout.addSpacing(10)

        if show_sub:
            layout.addWidget(self._create_separator())
            layout.addSpacing(10)
            layout.addWidget(QLabel("检测到（上）（下）、（一）（二）等【子分节后缀】："))
            self.radio_sub_inc = QRadioButton(
                "【递增】所有章节号依次递增（例：第1章 陨落的天才（上） → 第2章 陨落的天才（下））"
            )
            self.radio_sub_keep = QRadioButton(
                "【保留】主章节号保持不变（例：第1章 陨落的天才（上） → 第1章 陨落的天才（下））"
            )
            self.radio_sub_inc.setChecked(True)  # 默认递增
            bg = QButtonGroup(self)
            bg.addButton(self.radio_sub_inc)
            bg.addButton(self.radio_sub_keep)
            layout.addWidget(self.radio_sub_inc)
            layout.addWidget(self.radio_sub_keep)
            layout.addSpacing(10)

        if show_vol:
            layout.addWidget(self._create_separator())
            layout.addSpacing(10)
            layout.addWidget(QLabel("检测到包含【跨越多卷】的章节："))
            self.radio_vol_cont = QRadioButton(
                "【连续】所有章节全局连续（例：第一卷末【第100章】 → 第二卷首按顺序改为【第101章】）"
            )
            self.radio_vol_reset = QRadioButton(
                "【重置】新卷开始时重置序号（例：第一卷末【第100章】 → 第二卷首重置为【第1章】）"
            )
            self.radio_vol_cont.setChecked(True)  # 默认连续
            bg = QButtonGroup(self)
            bg.addButton(self.radio_vol_cont)
            bg.addButton(self.radio_vol_reset)
            layout.addWidget(self.radio_vol_cont)
            layout.addWidget(self.radio_vol_reset)
            reset_warning_label = QLabel(
                "（如果【重置】，【第一行】不要从【章节行】开始，可以直接全选，或从【匹配项】那行开始）"
            )
            reset_warning_label.setStyleSheet("color: red;")
            layout.addWidget(reset_warning_label)
            layout.addSpacing(10)

        if show_range:
            layout.addWidget(self._create_separator())
            layout.addSpacing(10)
            layout.addWidget(QLabel("检测到包含【有范围】的章节序号（如 1-2）："))
            self.radio_range_merge = QRadioButton("【合并】将范围强制规范化为单数字（例：第1-2章 → 第一章）")
            self.radio_range_keep = QRadioButton("【保留】保持原有的范围形式（例：第1-2章 → 第一-二章）")
            self.radio_range_merge.setChecked(True)  # 默认合并
            bg = QButtonGroup(self)
            bg.addButton(self.radio_range_merge)
            bg.addButton(self.radio_range_keep)
            layout.addWidget(self.radio_range_merge)
            layout.addWidget(self.radio_range_keep)
            layout.addSpacing(10)

        layout.addWidget(self._create_separator())
        layout.addSpacing(10)
        layout.addStretch()
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("确认重排")
        cancel_btn = QPushButton("取消")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _create_separator(self):
        line = QFrame()
        line.setProperty("class", "separator_line")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def _on_accept(self):
        if hasattr(self, "radio_sub_keep"):
            self.results["group_sub"] = self.radio_sub_keep.isChecked()
        if hasattr(self, "radio_vol_reset"):
            self.results["reset_vol"] = self.radio_vol_reset.isChecked()
        if hasattr(self, "radio_range_keep"):
            self.results["keep_range"] = self.radio_range_keep.isChecked()
        self.accept()
