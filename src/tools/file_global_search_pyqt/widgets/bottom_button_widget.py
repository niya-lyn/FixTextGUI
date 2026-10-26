import math

from qtpy.QtWidgets import QWidget, QPushButton, QButtonGroup, QLabel, QSpinBox
from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QIcon

from typing import Dict, Optional

from resources.ui_generated.ui_bottom_button_widget import Ui_BottomButtonWidget


class BottomButtonWidget(QWidget):

    pageChanged = Signal(int, int)  # (page_num, prev_page_num)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.ui = Ui_BottomButtonWidget()
        self.ui.setupUi(self)

        # 按钮组，用于处理点击事件
        self.pagination_button_group = QButtonGroup(self)
        self.pagination_button_group.setExclusive(True)
        self.pagination_button_group.buttonClicked.connect(self._on_page_button_clicked)

        # 内部状态变量
        self._total_items = 0
        self._items_per_page = 20
        self._current_page = 1
        self._total_pages = 0

        # 默认隐藏分页栏
        self.set_pagination_visible(False)

    def set_match_counter_label_text(self, cur, total):
        self.ui.match_counter_label.setText(f"匹配计数：{cur}/{total}")

    def set_match_counter_label_tool_tip(self, tip: str):
        self.ui.match_counter_label.setToolTip(tip)

    def reset_match_counter_label_text(self):
        self.ui.match_counter_label.setText("匹配计数：-/-")

    def set_calculating_counter_label_text(self):
        self.ui.match_counter_label.setText("匹配计数：计算中...")

    def set_editor_info_label_text(self, text: str, highlight: bool):
        self.ui.editor_info_label.setText(text)

        self.ui.editor_info_label.setProperty("highlight", highlight)
        self.ui.editor_info_label.style().unpolish(self.ui.editor_info_label)
        self.ui.editor_info_label.style().polish(self.ui.editor_info_label)

    def set_save_button_text(self, text: str, highlight: bool):
        self.ui.save_button.setText(text)

        self.ui.save_button.setProperty("highlight", highlight)
        self.ui.save_button.style().unpolish(self.ui.save_button)
        self.ui.save_button.style().polish(self.ui.save_button)

    def get_save_button(self) -> QPushButton:
        return self.ui.save_button

    def set_save_button_hint(self, unsaved=False):
        current_text = self.ui.save_button.text()
        if unsaved:
            if not current_text.startswith("* "):
                self.ui.save_button.setText(f"* {current_text}")
        else:
            if current_text.startswith("* "):
                self.ui.save_button.setText(current_text.lstrip("* "))

    def update_pagination_controls(self, total_items: int, items_per_page: int):
        """
        初始化分页控件，重置为第一页
        """
        # 暂停更新以防止闪烁
        self.setUpdatesEnabled(False)

        try:
            self._total_items = total_items
            self._items_per_page = items_per_page
            self._current_page = 1  # 重置时默认回第一页

            if total_items <= 0 or items_per_page <= 0 or total_items <= items_per_page:
                self._total_pages = 0
                self.set_pagination_visible(False)
                return

            self._total_pages = math.ceil(total_items / items_per_page)

            # 先渲染内容
            self._render_pagination()

            # 内容准备好后再显示
            self.set_pagination_visible(True)

        finally:
            # 恢复更新
            self.setUpdatesEnabled(True)

    def _render_pagination(self):
        """
        核心逻辑：根据当前页和总页数，重新生成布局中的按钮
        """
        layout = self.ui.pagination_layout

        # 1. 清除现有控件
        buttons = self.pagination_button_group.buttons()
        for btn in buttons:
            self.pagination_button_group.removeButton(btn)

        while layout.count() > 0:
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.deleteLater()

        # 2. 添加上一页/下一页控件
        self._add_prev_next_page_buttons(layout)

        # 3. 计算需要显示的页码列表
        page_nums_to_show = set()
        page_nums_to_show.add(1)
        page_nums_to_show.add(self._total_pages)

        siblings = 2
        for i in range(self._current_page - siblings, self._current_page + siblings + 1):
            if 1 <= i <= self._total_pages:
                page_nums_to_show.add(i)

        sorted_pages = sorted(list(page_nums_to_show))

        # 4. 生成分页按钮和省略号
        layout.addWidget(QLabel("分页："))
        prev_page = 0
        for page_num in sorted_pages:
            if prev_page > 0 and page_num - prev_page > 1:
                dots_label = QLabel("...")
                dots_label.setObjectName("dots_label")
                layout.addWidget(dots_label)

            btn = self._create_page_button(page_num)
            layout.addWidget(btn)
            self.pagination_button_group.addButton(btn, page_num)

            prev_page = page_num

        # 5. 添加跳转控件
        self._add_jump_controls(layout)

        # 在末尾添加弹簧，将所有控件顶到左边
        layout.addStretch()

    def _add_prev_next_page_buttons(self, layout):
        layout.addSpacing(5)

        # “上一页”按钮
        prev_btn = QPushButton("上一页")
        prev_btn.setFixedSize(60, 22)
        prev_btn.setEnabled(self._current_page > 1)
        prev_btn.clicked.connect(lambda: self.switch_to_page(self._current_page - 1))
        layout.addWidget(prev_btn)

        # “下一页”按钮
        next_btn = QPushButton("下一页")
        next_btn.setFixedSize(60, 22)
        next_btn.setEnabled(self._current_page < self._total_pages)
        next_btn.clicked.connect(lambda: self.switch_to_page(self._current_page + 1))
        layout.addWidget(next_btn)

        sep = QLabel(" | ")
        sep.setObjectName("prev_next_separator")
        layout.addWidget(sep)

    def _create_page_button(self, page_num):
        """创建一个标准的分页按钮"""
        info = self.get_page_info(page_num)

        btn = QPushButton(str(page_num))
        btn.setToolTip(f"显示第 {info['start_index']} 到 {info['end_index']} 项")
        btn.setFixedSize(40, 22)
        btn.setCheckable(True)

        if page_num == self._current_page:
            btn.setChecked(True)
            btn.setEnabled(False)

        return btn

    def _add_jump_controls(self, layout):
        """添加跳转输入框和确定按钮"""
        sep = QLabel("|")
        sep.setObjectName("jump_separator")
        layout.addWidget(sep)

        layout.addWidget(QLabel("跳转："))

        self.jump_spinbox = QSpinBox()
        self.jump_spinbox.setFixedSize(60, 22)
        self.jump_spinbox.setRange(1, self._total_pages)
        self.jump_spinbox.setValue(self._current_page)
        self.jump_spinbox.setAlignment(Qt.AlignRight)

        # 连接回车键
        self.jump_spinbox.lineEdit().returnPressed.connect(self._on_jump_clicked)

        layout.addWidget(self.jump_spinbox)

        # GO 按钮
        go_btn = QPushButton("Go")
        go_btn.setFixedSize(30, 22)
        go_btn.clicked.connect(self._on_jump_clicked)
        layout.addWidget(go_btn)

    def _on_page_button_clicked(self, btn):
        page_num = self.pagination_button_group.id(btn)
        self.switch_to_page(page_num)

    def _on_jump_clicked(self):
        """处理跳转按钮点击"""
        # SpinBox 自动处理了非数字输入，直接取值即可
        page_num = self.jump_spinbox.value()

        if 1 <= page_num <= self._total_pages:
            self.switch_to_page(page_num)
        else:
            # 理论上 SpinBox 的 Range 会限制住，但为了保险重置一下
            self.jump_spinbox.setValue(self._current_page)

    def switch_to_page(self, page_num: int, emit_changed_signal: bool = True):
        if self._current_page == page_num:
            return

        prev_page_num = self._current_page
        self._current_page = page_num

        # 暂停更新防止切换时的闪烁
        self.setUpdatesEnabled(False)
        try:
            self._render_pagination()
        finally:
            self.setUpdatesEnabled(True)

        if emit_changed_signal:
            self.pageChanged.emit(page_num, prev_page_num)

    def get_page_info(self, page_num: int) -> Optional[Dict]:
        if self._items_per_page <= 0:
            return None

        start_index = (page_num - 1) * self._items_per_page + 1
        end_index = min(page_num * self._items_per_page, self._total_items)

        return {"page_num": page_num, "start_index": start_index, "end_index": end_index}

    def set_pagination_visible(self, visible: bool):
        """统一设置分页控件的可见性"""
        if visible:
            self.ui.pagination_scroll_area.setMinimumSize(0, 45)
            self.ui.pagination_scroll_area.setMaximumSize(16777215, 45)
        else:
            self.ui.pagination_scroll_area.setFixedSize(0, 0)

        self.ui.pagination_scroll_area.setVisible(visible)

    def update_theme_style(self, qss_string: str, theme_name: str):
        """统一暴露的主题更新接口"""
        self.setStyleSheet(qss_string)

        self.ui.go_to_prev_pos_button.setIcon(QIcon(f":/{theme_name}/icons/left.png"))
        self.ui.go_to_next_pos_button.setIcon(QIcon(f":/{theme_name}/icons/right.png"))
        self.ui.go_to_line_button.setIcon(QIcon(f":/{theme_name}/icons/updown.png"))
        self.ui.go_to_top_button.setIcon(QIcon(f":/{theme_name}/icons/to-top.png"))
