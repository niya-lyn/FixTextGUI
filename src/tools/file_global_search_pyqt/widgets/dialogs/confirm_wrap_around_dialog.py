from qtpy.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton

class ConfirmWrapAroundDialog(QDialog):
    def __init__(self, parent, forward: bool):
        super().__init__(parent)
        self.setWindowTitle("提示")

        msg = "已到结尾，是否从开头继续查找？" if forward else "已到开头，是否从结尾继续查找？"
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(msg))

        btn_layout = QHBoxLayout()
        yes_btn = QPushButton("是")
        no_btn = QPushButton("否")
        yes_btn.setDefault(True)

        yes_btn.clicked.connect(self.accept)
        no_btn.clicked.connect(self.reject)

        btn_layout.addWidget(yes_btn)
        btn_layout.addWidget(no_btn)
        layout.addLayout(btn_layout)
