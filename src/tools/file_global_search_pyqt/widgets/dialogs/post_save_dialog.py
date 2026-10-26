from qtpy.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton


class PostSaveDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("保存提示")

        layout = QVBoxLayout(self)

        label = QLabel("修改已保存，可点击“比对检查”，确认本次操作的结果。\n或及时到 BC 中比较查看。")
        layout.addWidget(label)

        button_layout = QHBoxLayout()
        compare_button = QPushButton("比对检查")
        cancel_button = QPushButton("稍后比对")

        button_layout.addStretch()
        button_layout.addWidget(compare_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        compare_button.clicked.connect(self.accept)
        compare_button.setDefault(True)
        cancel_button.clicked.connect(self.reject)
