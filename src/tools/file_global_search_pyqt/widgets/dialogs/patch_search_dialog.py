from qtpy.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QFrame,
    QCheckBox,
    QSpinBox,
)
from qtpy.QtCore import Qt
from core.constants import PatchSearchAction


class PatchSearchDialog(QDialog):
    def __init__(self, parent=None, hide_old_content_checked=False, patch_merge_threshold=2):
        super().__init__(parent)

        self.setWindowTitle("差异比对")
        self.action = PatchSearchAction.NOT_PATCH_SEARCH
        self.hide_old_content = hide_old_content_checked
        self.merge_threshold = patch_merge_threshold
        self.clicked_button = None  # "search", "guidance", "cancel"
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        layout.addSpacing(10)

        layout.addWidget(
            QLabel(
                "此功能可以直观地查看当前文件与上一个版本的差异项。\n如果是第一次使用，建议点击“显示指引”查看详细说明。"
            )
        )

        layout.addSpacing(10)

        line = QFrame()
        line.setProperty("class", "separator_line")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        layout.addSpacing(10)

        self.radio_books_vs_bak = QRadioButton("方向：→ books（显示以 books 为主体的差异项）")
        self.radio_bak_vs_books = QRadioButton("方向：→ booksBak（显示以 booksBak 为主体的差异项）")
        self.radio_books_vs_bak.setChecked(True)
        layout.addWidget(self.radio_books_vs_bak)
        layout.addWidget(self.radio_bak_vs_books)

        layout.addSpacing(10)

        line = QFrame()
        line.setProperty("class", "separator_line")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        layout.addSpacing(10)

        self.checkbox_hide_content = QCheckBox("隐藏灰色背景的【旧内容】")
        self.checkbox_hide_content.setChecked(self.hide_old_content)
        layout.addWidget(self.checkbox_hide_content)

        layout.addWidget(QLabel("（如果勾选，则只显示黄色的【新内容】，鼠标悬停时可查看【旧内容】）"))

        layout.addSpacing(10)

        line = QFrame()
        line.setProperty("class", "separator_line")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        layout.addSpacing(10)

        threshold_layout = QHBoxLayout()
        threshold_label = QLabel("将差异处的前后 ")
        self.merge_threshold_spinbox = QSpinBox()
        self.merge_threshold_spinbox.setRange(0, 50)
        self.merge_threshold_spinbox.setAlignment(Qt.AlignRight | Qt.AlignTrailing | Qt.AlignVCenter)
        self.merge_threshold_spinbox.setValue(self.merge_threshold)
        threshold_layout.addWidget(threshold_label)
        threshold_layout.addWidget(self.merge_threshold_spinbox)
        threshold_layout.addWidget(QLabel(" 个字符视为同一差异块"))
        threshold_layout.addStretch()
        layout.addLayout(threshold_layout)
        layout.addWidget(QLabel("（值越小，差异块越零碎；值越大，差异块越大）"))

        layout.addSpacing(10)

        btn_layout = QHBoxLayout()
        search_btn = QPushButton("开始比对")
        guidance_btn = QPushButton("显示指引")
        cancel_btn = QPushButton("取消")

        search_btn.setDefault(True)

        search_btn.clicked.connect(self._on_search)
        guidance_btn.clicked.connect(self._on_guidance)
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(search_btn)
        btn_layout.addWidget(guidance_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _on_search(self):
        self.clicked_button = "search"
        self.action = (
            PatchSearchAction.BOOKS_VS_BAK if self.radio_books_vs_bak.isChecked() else PatchSearchAction.BAK_VS_BOOKS
        )
        self.hide_old_content = self.checkbox_hide_content.isChecked()
        self.merge_threshold = self.merge_threshold_spinbox.value()
        self.accept()

    def _on_guidance(self):
        self.clicked_button = "guidance"
        self.accept()
