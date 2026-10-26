from qtpy.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QPushButton, QLabel
from qtpy.QtCore import Qt, Signal, QEvent
from qtpy.QtGui import QCursor


class FloatingTagEditor(QFrame):
    """自定义多行悬浮编辑框（支持长文本、自动换行、带确认按钮）"""

    editFinished = Signal(str)
    editCancelled = Signal()
    removeContent = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Widget)
        self._is_submitting = False

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # 1. 多行文本框和提示
        self.text_edit = QPlainTextEdit()
        self.text_edit.setStyleSheet('font-family: "Consolas-Slim", "FZYouSongJ GBK", "MiSans L3", "黑体"')

        self.hint_label = QLabel("提示：按 Shift+Enter 换行")
        self.hint_label.setStyleSheet("color: #888888; font-size: 11px;")

        # 2. 按钮布局
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)  # 缩小按钮之间的间距
        btn_layout.addStretch()  # 弹簧，把后面的控件顶到右边

        self.btn_confirm = QPushButton("采用")
        self.btn_remove = QPushButton("移除")
        self.btn_close = QPushButton("关闭")

        button_colors = {
            self.btn_confirm: "btn_confirm",
            self.btn_remove: "btn_remove",
            self.btn_close: "btn_close",
        }

        # 统一设置按钮样式，使其能在 200px 宽度内存放 3 个
        for btn, name in button_colors.items():
            btn.setObjectName(name)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn_layout.addWidget(btn)

        main_layout.addWidget(self.text_edit)
        main_layout.addWidget(self.hint_label)
        main_layout.addLayout(btn_layout)

        # 信号连接
        self.btn_confirm.clicked.connect(self._submit)
        self.btn_remove.clicked.connect(self._remove)
        self.btn_close.clicked.connect(self._cancel)

        # 监听输入框的按键和焦点事件
        self.text_edit.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event):
        if obj == self.text_edit:
            # 1. 拦截按键事件
            if event.type() == QEvent.KeyPress:
                if event.key() == Qt.Key_Escape:
                    self._cancel()
                    return True
                elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
                    # Shift + Enter 换行，纯 Enter 直接采用
                    if event.modifiers() & Qt.ShiftModifier:
                        return False  # 不拦截，让它正常换行
                    else:
                        self._submit()
                        return True  # 拦截回车，执行提交

            # 2. 拦截失去焦点事件（包含防误伤探测）
            elif event.type() == QEvent.FocusOut:
                # 因为换成了多行文本框，点击滚动条时也会触发失焦
                # 只要鼠标还在这个弹窗的物理范围内，一律不取消
                global_mouse_pos = QCursor.pos()
                local_mouse_pos = self.mapFromGlobal(global_mouse_pos)
                if self.rect().contains(local_mouse_pos):
                    return False

                self._cancel()

        return super().eventFilter(obj, event)

    def _submit(self):
        """确认采用"""
        if self.isVisible():
            self._is_submitting = True
            self.hide()
            self.editFinished.emit(self.text_edit.toPlainText())
            self._is_submitting = False

    def _remove(self):
        """整块移除"""
        if self.isVisible():
            self._is_submitting = True
            self.hide()
            self.removeContent.emit("", True)
            self._is_submitting = False

    def _cancel(self):
        """取消编辑"""
        if self.isVisible() and not self._is_submitting:
            self.hide()
            self.editCancelled.emit()

    # 代理方法替换为对应多行文本框的方法
    def setText(self, text):
        self.text_edit.setPlainText(text)

    def selectAll(self):
        self.text_edit.selectAll()

    def setFocus(self):
        self.text_edit.setFocus()
