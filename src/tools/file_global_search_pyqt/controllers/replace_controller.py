import regex
import html

from qtpy.QtCore import QObject, Signal
from qtpy.QtGui import QTextCursor
from qtpy.QtWidgets import QMessageBox, QToolTip

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.replace_service import ReplaceService
    from widgets.text_editor_widget import TextEditorWidget
    from widgets.replace_widget import ReplaceWidget
    from widgets.search_widget import SearchWidget
    from core.search_options import SearchOptions
    from models.search_model import SearchModel

import utils.util as util


class ReplaceController(QObject):
    replaceCompletedAndRequestNext = Signal()
    bulkReplaceCompleted = Signal()
    validReplaceOccurred = Signal(str)  # 进行了一次有效替换，发送替换文本，用于增加历史记录等

    def __init__(
        self,
        replace_service: "ReplaceService",
        text_editor_widget: "TextEditorWidget",
        replace_widget: "ReplaceWidget",
        search_widget: "SearchWidget",
        search_options: "SearchOptions",
        search_model: "SearchModel",
    ):
        super().__init__()
        self.replace_service = replace_service

        self.text_editor_widget = text_editor_widget
        self.text_edit = self.text_editor_widget.get_text_edit()
        self.replace_widget = replace_widget
        self.search_widget = search_widget

        self.search_options = search_options
        self.search_model = search_model

        self._toggle_replace_tip_suffix = False

    def toggle_replace_shortcuts(self):
        # 获取最新的状态
        is_enabled = self.replace_widget.get_replace_shortcuts_state()
        # 通知 TextEditorWidget 切换状态
        self.text_editor_widget.set_replace_shortcuts_enabled(is_enabled)

    def replace_and_find_next(self):
        search_term = self.search_widget.get_search_text()
        replace_text = self.replace_widget.get_replace_text()

        if search_term == replace_text:
            QMessageBox.information(self.replace_widget, "提示", "搜索和替换值相同，无需修改")
            return

        cursor = self.text_editor_widget.get_cursor()
        if cursor.hasSelection():
            self._perform_replace_and_find(cursor, search_term, replace_text)
            return

        # 若无选区，直接触发信号让导航模块跳下一个
        self.replaceCompletedAndRequestNext.emit()

    def _perform_replace_and_find(self, cursor: QTextCursor, search_term: str, replace_text: str):
        pattern_str = search_term if self.search_options.use_regex else regex.escape(search_term)
        flags = self.search_options.get_regex_flags()
        try:
            pattern = regex.compile(pattern_str, flags)
        except regex.error as e:
            QMessageBox.warning(self.replace_widget, "替换报错", f"无效的正则表达式：{str(e)}")
            return

        self._add_to_replace_history(replace_text)

        # 获取全文档文本，并重新搜索以获取带上下文的 match 对象
        selection_start = cursor.selectionStart()
        selection_end = cursor.selectionEnd()
        full_text = self.text_editor_widget.get_text()
        py_selection_start = util.qt_to_py_index(selection_start, full_text)

        # 从当前选区的起始位置开始在【整个文档】中搜索一次，避免受前后断言的影响导致无法替换
        match_obj = pattern.search(full_text, pos=py_selection_start)

        if match_obj and match_obj.start() == py_selection_start:
            result = self.replace_service.get_single_replace_result(
                match_obj, replace_text, self._get_replace_callback(replace_text)
            )

            if not result.success:
                QMessageBox.warning(self.replace_widget, "替换报错", result.error_msg)
                return

            cursor.setPosition(selection_start)
            cursor.setPosition(selection_end, QTextCursor.MoveMode.KeepAnchor)
            self.text_edit.insert_and_highlight_chars(cursor, result.new_text)

            # 直接跳到下一处匹配并选中
            self.replaceCompletedAndRequestNext.emit()
        else:
            # 如果选区不匹配，则正常查找下一个
            self.replaceCompletedAndRequestNext.emit()

    def show_replace_tool_tip(self, match_obj: regex.Match):
        replace_text = self.replace_widget.get_replace_text()

        result = self.replace_service.get_single_replace_result(
            match_obj, replace_text, self._get_replace_callback(replace_text)
        )

        if not result.success:
            return

        tip_text = result.new_text

        if len(tip_text) > 150:
            tip_text = "[...过长省略...] " + tip_text[-150:]

        # 检查是否有待显示的预览文本、有选区
        if tip_text and self.text_edit.textCursor().hasSelection():
            # 强制刷新：当两个相邻 match 的 tip_text 相同时，QToolTip 为了效率默认不会重复弹出提示
            # 这里 toggle 一个不可见后缀，使 tip_text 的内容每次都不同，以确保弹出提示
            if self._toggle_replace_tip_suffix:
                tip_text += "\u200b"
            self._toggle_replace_tip_suffix = not self._toggle_replace_tip_suffix

            # 为了实现宽度限制和自动换行，需要将 ToolTip 中的文本转为 HTML
            escaped_text = html.escape(tip_text).replace("\n", "<br>")
            rich_tip_text = (
                f"<div style='max-width: 50em; word-wrap: break-word; white-space: pre-wrap;'>{escaped_text}</div>"
            )

            cursor_rect = self.text_edit.cursorRect()
            tool_tip_pos = self.text_edit.viewport().mapToGlobal(cursor_rect.bottomRight())
            tool_tip_pos.setY(tool_tip_pos.y() - int(cursor_rect.height() * 0.7))

            QToolTip.hideText()  # 强制隐藏旧提示，确保刷新
            QToolTip.showText(tool_tip_pos, rich_tip_text, self.text_edit)

    def replace_in_selection(self):
        """仅替换当前选区内的所有匹配项"""
        cursor = self.text_editor_widget.get_cursor()
        if not cursor.hasSelection():
            self.replace_and_find_next()
            return

        selected_text = self.text_edit.get_normalized_selected_text(cursor)

        new_text = self._execute_bulk_replace(selected_text)

        if selected_text != new_text:
            self.text_edit.insert_and_highlight_chars(cursor, new_text, False)
            # 发射信号，让导航模块获取最新匹配计数
            self.bulkReplaceCompleted.emit()

    def replace_all(self):
        """替换文本框中的所有匹配项"""
        current_text = self.text_editor_widget.get_text()

        new_text = self._execute_bulk_replace(current_text)

        if current_text != new_text:
            old_line_number = self.text_edit.get_current_line_number()
            cursor = self.text_edit.textCursor()
            cursor.select(QTextCursor.Document)

            self.text_edit.insert_and_highlight_chars(cursor, new_text, False)

            # 设置光标焦点到结尾
            cursor.clearSelection()
            cursor.movePosition(QTextCursor.End)
            self.text_edit.setTextCursor(cursor)

            # 发射信号，让导航模块获取最新匹配计数
            self.bulkReplaceCompleted.emit()
            self.text_edit.set_current_line_number(old_line_number)

        self.text_edit.setFocus()

    def _execute_bulk_replace(self, source_text: str) -> str:
        """执行替换的核心逻辑，用于“全部替换”和“替换选区”"""
        search_term = self.search_widget.get_search_text()
        replace_text = self.replace_widget.get_replace_text()

        if search_term == replace_text:
            return source_text

        result = self.replace_service.perform_bulk_replace(
            source_text,
            search_term,
            replace_text,
            self.search_options.use_regex,
            self.search_options.get_regex_flags(),
            self._get_replace_callback(replace_text),
        )

        if not result.success:
            QMessageBox.warning(self.replace_widget, "替换报错", result.error_msg)
            return source_text

        self._add_to_replace_history(replace_text)

        return result.new_text

    def replace_by_list_index(self, index: int):
        """使用快捷键模拟鼠标点击，根据索引调用替换记录列表中不同的项"""
        replace_list = self.replace_widget.get_replace_history_list()

        if not replace_list or replace_list.count() <= index:
            return

        item = replace_list.item(index)
        if not item:
            return

        replace_list.setCurrentItem(item)
        replace_list.itemClicked.emit(item)

    def _add_to_replace_history(self, replace_text: str):
        condition = self.search_model.current_condition
        cond_ed_rep = condition.get("editorReplace", "") if condition else ""
        cond_rep = condition.get("replace", "") if condition else ""

        is_special = "\\" in replace_text or replace_text == "-"
        if self.search_options.add_to_history_list and (
            is_special or (replace_text != cond_ed_rep and replace_text != cond_rep)
        ):
            self.validReplaceOccurred.emit(replace_text)

    def _get_replace_callback(self, replace_text):
        condition = self.search_model.current_condition
        if (
            condition
            and "replaceCallback" in condition
            and replace_text != ""
            and replace_text == condition.get("replace", "")
        ):
            return condition["replaceCallback"]

        return None
