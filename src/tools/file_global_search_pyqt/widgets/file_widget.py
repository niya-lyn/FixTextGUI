import os
from typing import Optional

from qtpy.QtWidgets import QWidget
from qtpy.QtCore import Signal

from resources.ui_generated.ui_file_widget import Ui_FileWidget
from core.env_config import env_config
from widgets.custom.custom_combo_box import CustomComboBox


class FileWidget(QWidget):
    # 1. 定义模块内部业务信号
    fileSelected = Signal(str)
    fileDropped = Signal(str)
    refreshRequested = Signal()  # 请求刷新文件列表

    # 2. 定义跨模块业务信号
    lineNumToggleRequested = Signal()  # 请求切换行号
    patchSearchRequested = Signal()  # 请求执行 patch 搜索

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.ui = Ui_FileWidget()
        self.ui.setupUi(self)

        self.file_dir = env_config.file_dir
        self.is_html_file = False

        self._setup_internal_connections()

    def _setup_internal_connections(self):
        # 内部 UI 组件动作 ---> 转化为对外暴露的语义化信号
        self.ui.file_combo_box.currentTextChanged.connect(lambda text: self.fileSelected.emit(text))
        self.ui.refresh_file_list_button.clicked.connect(self.refreshRequested.emit)
        self.ui.ln_switch.clicked.connect(self.lineNumToggleRequested.emit)
        self.ui.patch_search_button.clicked.connect(self.patchSearchRequested.emit)

    def get_file_combo_box(self) -> CustomComboBox:
        return self.ui.file_combo_box

    def set_file_list(self, file_list: list):
        self.ui.file_combo_box.clear()
        if file_list:
            self.ui.file_combo_box.addItems(file_list)

    def set_current_file(self, filename: str):
        self.ui.file_combo_box.setCurrentText(filename)

    def get_current_file(self) -> str:
        return self.ui.file_combo_box.currentText()

    def get_file_path(self) -> str:
        return os.path.join(self.file_dir, self.get_current_file())

    def get_backup_file_path(self) -> str:
        backup_dir = os.path.join(os.path.dirname(self.file_dir), "booksBak")
        os.makedirs(backup_dir, exist_ok=True)

        return os.path.join(backup_dir, self.get_current_file())

    def set_char_count_label(self, char_count_str: str):
        self.ui.char_count_label.setText(char_count_str)

    def update_theme_style(self, qss_string: str, theme_name: str):
        self.setStyleSheet(qss_string)

        # FileWidget 有个文字标签需要根据主题变化
        if theme_name == "light":
            self.ui.theme_switch.setText("深色")
        else:
            self.ui.theme_switch.setText("浅色")
