import re

from qtpy.QtWidgets import QWidget, QPushButton
from qtpy.QtCore import Qt, QSize, QPoint
from qtpy.QtGui import QIcon

from resources.ui_generated.ui_replace_widget import Ui_ReplaceWidget

from widgets.custom.draggable_history_list_widget import DraggableHistoryListWidget


class ReplaceWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.ui = Ui_ReplaceWidget()
        self.ui.setupUi(self)

        self.ui.history_button.setIconSize(QSize(18, 18))

        # 设置弹出窗口标志，以确保面板能正确显示
        self.ui.history_panel.setWindowTitle("历史记录面板")
        self.ui.history_panel.setWindowFlags(Qt.Tool)

        self.ui.history_button.clicked.connect(self.toggle_history_panel)

    def get_replace_text(self) -> str:
        # 兼容 Perl 风格的 $1, $2... 分组写法
        return re.sub(r'\$(\d+)', r'\\\1', self.ui.replace_input.text())

    def set_replace_text(self, text: str) -> None:
        self.ui.replace_input.setText(text)

    def get_history_button(self) -> QPushButton:
        return self.ui.history_button

    def get_history_panel(self) -> QWidget:
        return self.ui.history_panel

    def get_search_history_list(self) -> DraggableHistoryListWidget:
        return self.ui.search_history_list

    def get_replace_history_list(self) -> DraggableHistoryListWidget:
        return self.ui.replace_history_list

    def get_replace_shortcuts_state(self) -> bool:
        return self.ui.replace_shortcuts_checkbox.isChecked()

    def toggle_history_panel(self):
        panel = self.ui.history_panel
        panel.setVisible(not panel.isVisible())
        return

    def get_history_panel_state(self):
        panel = self.ui.history_panel
        return (panel.frameGeometry().topLeft(), panel.size())

    def set_history_panel_state(self, pos: QPoint = None, size: QSize = None):
        """恢复历史面板位置和尺寸"""
        if pos:
            self.ui.history_panel.move(pos)

        if size:
            self.ui.history_panel.resize(size)

    def update_theme_style(self, qss_string: str, theme_name: str):
        self.setStyleSheet(qss_string)

        self.ui.history_button.setIcon(QIcon(f":/{theme_name}/icons/history.png"))
