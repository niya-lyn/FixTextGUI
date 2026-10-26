from qtpy.QtWidgets import QWidget
from qtpy.QtGui import QTextCursor, QIcon
from qtpy.QtCore import QSize

from resources.ui_generated.ui_text_editor_widget import Ui_TextEditorWidget
from widgets.custom.custom_plain_text_edit import CustomPlainTextEdit
from widgets.custom.custom_highlighter import CustomHighlighter

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.context_menu import ContextMenu


class TextEditorWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.ui = Ui_TextEditorWidget()
        self.ui.setupUi(self)

        self._is_smart_scroll_enabled = True

        self._is_normal_search_result = False

        self.set_icons()

        self._setup_smart_scroll_button()

        self.highlighter = self.get_highlighter()

    def set_icons(self, theme: str = "light"):
        self.enabled_icon = QIcon(f":/{theme}/icons/enabled.png")
        self.disabled_icon = QIcon(f":/{theme}/icons/disabled.png")

        self._update_smart_scroll_button_style(self.ui.smart_scroll_button.isChecked())

    def set_replace_shortcuts_enabled(self, enabled: bool):
        self.ui.text_edit.replace_shortcuts_enabled = enabled

    def set_context_menu(self, menu: "ContextMenu"):
        self.ui.text_edit.set_custom_menu(menu)

    def get_text(self) -> str:
        """无行首标记 [行号：xxx]，只获取编辑器现有的文本内容"""
        return self.ui.text_edit.toPlainText()

    def get_raw_text(self) -> str:
        """会根据已有行号信息，恢复行首标记 [行号：xxx] 或 [匹配：xxx]"""
        return self.ui.text_edit.get_raw_text()

    def load_raw_text(self, text: str) -> None:
        """载入编辑器时，会把 [行号：xxx] 或 [匹配：xxx] 的行号提取到行号区域，然后移除这些标记"""
        self.ui.text_edit.load_raw_text(text)

    def get_cursor(self) -> QTextCursor:
        return self.ui.text_edit.textCursor()

    def set_cursor(self, cursor: QTextCursor) -> None:
        self.ui.text_edit.setTextCursor(cursor)

    def get_text_edit(self) -> CustomPlainTextEdit:
        return self.ui.text_edit

    def get_highlighter(self) -> CustomHighlighter:
        return self.ui.text_edit.get_highlighter()

    def set_focus(self):
        self.ui.text_edit.setFocus()

    def reset_highlighter(self, editor_highlight_rules: str):
        old_line_number = self.ui.text_edit.get_current_line_number()
        original_text = self.get_raw_text()
        self.load_raw_text("")
        self.highlighter.clear_rules()
        self.highlighter.setup_highlighter(editor_highlight_rules)
        self.ui.text_edit.set_current_line_number(old_line_number)
        self.load_raw_text(original_text)

    def handle_major_content_change(self):
        """
        当文档内容发生变化时（如加载新文件、搜索替换等），清空所有跳转位置的记录
        """
        self.ui.text_edit.clear_cursor_history()

    def _setup_smart_scroll_button(self):
        self.ui.smart_scroll_button.setIconSize(QSize(15, 15))

        self.ui.smart_scroll_button.toggled.connect(self._update_smart_scroll_button_style)

        self._update_smart_scroll_button_style(self.ui.smart_scroll_button.isChecked())

    def _update_smart_scroll_button_style(self, checked: bool):
        button = self.ui.smart_scroll_button
        button.setChecked(checked)
        if checked:
            button.setIcon(self.enabled_icon)
            button.setToolTip("智能滚动已开启。在匹配项之间跳转时，会自动判断是否需要进行滚动")
            self._is_smart_scroll_enabled = True
        else:
            button.setIcon(self.disabled_icon)
            button.setToolTip("智能滚动已关闭。在匹配项之间跳转时，始终将匹配项置于视窗的中间")
            self._is_smart_scroll_enabled = False

    def is_smart_scroll_enabled(self) -> bool:
        return self._is_smart_scroll_enabled

    def is_normal_search_result(self) -> bool:
        return self._is_normal_search_result

    def set_normal_search_result(self, result_text: str):
        # 只有存在这个边界行，才是一个正常的搜索结果
        self._is_normal_search_result = "※※※（下文省略）※※※" in result_text

    def is_content_modified(self) -> bool:
        return self.ui.text_edit.document().isModified()

    def set_content_modified(self, state=True):
        return self.ui.text_edit.document().setModified(state)

    def reset_editor_color(self):
        self.ui.text_edit.reset_editor_color()

    def reload_text(self):
        original_text = self.get_raw_text()
        self.reset_editor_color()
        self.load_raw_text(original_text)

    def toggle_line_num(self):
        self.ui.text_edit.toggle_line_num()

    def update_theme_style(self, qss_string: str, theme_name: str, function_colors: dict):
        self.setStyleSheet(qss_string)

        # 更新自己的内部小图标
        self.set_icons(theme_name)

        # 安全获取颜色，并设置给底层的编辑器控件
        self.get_text_edit().update_colors(function_colors)
