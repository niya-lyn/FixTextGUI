from qtpy.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox


class BackupConfirmDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("备份确认")

        layout = QVBoxLayout(self)
        message = (
            "是否覆盖 booksBak 中的上一版本文件？\n\n"
            "如果覆盖，则在“比对”时只能看到本次操作的修改结果。\n"
            "如不覆盖，则仍能看到上一次操作所做的修改。"
        )
        layout.addWidget(QLabel(message))

        button_layout = QHBoxLayout()
        self.yes_button = QPushButton("覆盖")
        self.no_button = QPushButton("不覆盖")
        self.cancel_button = QPushButton("取消")

        button_layout.addStretch()
        button_layout.addWidget(self.yes_button)
        button_layout.addWidget(self.no_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.yes_button.setDefault(True)

        self.yes_button.clicked.connect(lambda: self.done(QMessageBox.Yes))
        self.no_button.clicked.connect(lambda: self.done(QMessageBox.No))
        self.cancel_button.clicked.connect(lambda: self.done(QMessageBox.Cancel))

    def reject(self):
        """
        重写 reject 方法，当用户按下 ESC 键时，此方法被调用
        让它的行为和点击“取消”按钮完全一致
        """
        self.done(QMessageBox.Cancel)
