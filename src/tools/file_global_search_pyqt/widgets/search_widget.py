from qtpy.QtWidgets import QWidget
from qtpy.QtCore import QSize
from qtpy.QtGui import QIcon

from resources.ui_generated.ui_search_widget import Ui_SearchWidget

from widgets.pinyin_completer import PinyinCompleter


class SearchWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.ui = Ui_SearchWidget()
        self.ui.setupUi(self)

        self.ui.reload_search_button.setIconSize(QSize(18, 18))

        self.ui.desc_combo_box.currentIndexChanged.connect(self.set_selection_label)
        self.ui.prev_search_button.clicked.connect(self.select_prev_search)
        self.ui.next_search_button.clicked.connect(self.select_next_search)

    def get_search_text(self) -> str:
        return self.ui.search_input.toPlainText()

    def set_search_text(self, text: str) -> None:
        if self.get_search_text() != text:
            self.ui.search_input.setPlainText(text)

    def get_desc_text(self) -> str:
        return self.ui.desc_combo_box.currentText()

    def set_desc_text(self, desc: str) -> None:
        self.ui.desc_combo_box.setCurrentText(desc)

    def set_desc_index(self, index: int) -> None:
        self.ui.desc_combo_box.setCurrentIndex(index)

    def set_selection_label(self):
        current_index = self.ui.desc_combo_box.currentIndex()
        total_count = self.ui.desc_combo_box.count()
        label_text = f"{current_index + 1}/{total_count}"
        self.ui.current_selection_label.setText(label_text)

    def set_search_conditions(self, conditions) -> None:
        """
        接收一个条件列表，并用它来填充描述下拉框及其自动完成器
        """
        # 1. 从条件数据中提取描述列表
        desc_list = [condition["desc"] for condition in conditions]

        # 2. 更新 ComboBox 的内容
        self.ui.desc_combo_box.clear()
        self.ui.desc_combo_box.addItems(desc_list)

        # 3. 更新 Completer 的模型
        self.ui.desc_combo_box.setCompleter(PinyinCompleter(desc_list, self))

    def select_prev_search(self):
        self.ui.desc_combo_box.select_prev_item()

    def select_next_search(self):
        self.ui.desc_combo_box.select_next_item()

    def get_search_button_text(self) -> str:
        return self.ui.search_button.text()

    def set_search_button_text(self, text: str) -> None:
        self.ui.search_button.setText(text)

    def get_search_button_style(self) -> None:
        return self.ui.search_button.styleSheet()

    def set_search_button_style(self, style: str) -> None:
        self.ui.search_button.setStyleSheet(style)

    def scroll_search_input_to_top(self) -> None:
        self.ui.search_input.verticalScrollBar().setValue(0)

    def update_theme_style(self, qss_string: str, theme_name: str):
        self.setStyleSheet(qss_string)

        self.ui.reload_search_button.setIcon(QIcon(f":/{theme_name}/icons/refresh.png"))
