import regex
from qtpy.QtCore import QObject, Signal
from qtpy.QtGui import QTextCursor
from qtpy.QtWidgets import QMessageBox, QInputDialog, QDialog

from typing import Optional, TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from services.navigation_service import NavigationService
    from widgets.text_editor_widget import TextEditorWidget
    from widgets.bottom_button_widget import BottomButtonWidget
    from widgets.search_widget import SearchWidget
    from core.search_options import SearchOptions
    from models.search_model import SearchModel

from core.data_classes import SearchResult
from widgets.dialogs.confirm_wrap_around_dialog import ConfirmWrapAroundDialog
import utils.util as util


class NavigationController(QObject):
    navigatedToMatch = Signal(object)  # (regex.Match) 供 ReplaceController 弹 Tooltip 用

    def __init__(
        self,
        navigation_service: "NavigationService",
        search_model: "SearchModel",
        text_editor_widget: "TextEditorWidget",
        search_widget: "SearchWidget",
        bottom_button_widget: "BottomButtonWidget",
        search_options: "SearchOptions",
        check_search_text_changed_callback: Callable[[], bool],
    ):
        super().__init__()

        self.navigation_service = navigation_service
        self.search_model = search_model
        self.text_editor_widget = text_editor_widget
        self.search_widget = search_widget
        self.bottom_button_widget = bottom_button_widget
        self.search_options = search_options
        self.check_search_text_changed_callback = check_search_text_changed_callback

    def invalidate_cache(self):
        had_counter_task = self.navigation_service.invalidate_cache()
        if had_counter_task:
            self.bottom_button_widget.reset_match_counter_label_text()

    # ==================== 公开的导航 API ====================
    def go_to_prev_match(self):
        self._navigate_to_match(forward=False, is_interactive=True)

    def go_to_next_match(self):
        self._navigate_to_match(forward=True, is_interactive=True)

    def get_prev_match_obj(self) -> Optional[regex.Match]:
        """静默查询，用于更新计数或获取上一个目标"""
        return self._navigate_to_match(forward=False, is_interactive=False)

    def get_next_match_obj(self) -> Optional[regex.Match]:
        """静默查询，用于更新计数或获取下一个目标"""
        return self._navigate_to_match(forward=True, is_interactive=False)

    # ==================== 核心逻辑 ====================
    def _navigate_to_match(self, forward: bool, is_interactive: bool) -> Optional[regex.Match]:
        """
        核心的导航和搜索方法，使用用户输入的搜索词进行搜索，区分交互与静默模式
        """
        pattern_str = self.search_widget.get_search_text()
        if not pattern_str:
            return None

        pattern = self.navigation_service.compile_pattern(
            pattern_str, self.search_options.use_regex, self.search_options.get_regex_flags()
        )

        if not pattern:
            if is_interactive:
                # parent 替换为 self.text_editor_widget
                QMessageBox.warning(self.text_editor_widget, "错误", "正则表达式无效")
            return None

        # 执行核心搜索并返回 SearchResult 数据类
        search_result = self._perform_search(pattern, forward, is_interactive)

        # 检查搜索是否被用户取消
        if search_result is None:
            return None  # 立即中止

        match_obj = search_result.found_match
        all_matches = search_result.all_matches

        # 非交互模式（静默查询）：仅更新计数器并返回
        # 如果无缓存则暂时不显示匹配计数
        if not is_interactive:
            if match_obj:
                self._update_counter(match_obj, all_matches)
            return match_obj

        # 交互模式：需要高亮、滚动、并发射信号
        if match_obj:
            self._show_match_in_editor(match_obj)
            self._update_counter(match_obj, all_matches)
            self.navigatedToMatch.emit(match_obj)
        else:
            self.bottom_button_widget.reset_match_counter_label_text()

        return match_obj

    def _perform_search(self, pattern: regex.Pattern, forward: bool, is_interactive: bool) -> Optional[SearchResult]:
        full_text = self.text_editor_widget.get_text()
        cursor = self.text_editor_widget.get_cursor()
        search_pos = util.qt_to_py_index(cursor.selectionEnd() if forward else cursor.selectionStart(), full_text)

        # 1. 尝试查找
        match_obj, all_matches = self.navigation_service.find_match(pattern, full_text, search_pos, forward)

        # 2. 如果缓存失效，启动后台计数
        if match_obj and not all_matches and self.search_options.enable_match_count:
            self.bottom_button_widget.set_calculating_counter_label_text()
            self.navigation_service.start_background_counting(pattern, full_text, self._on_counting_finished)

        # 3. 处理回绕
        if not match_obj:
            should_wrap = False
            if is_interactive:
                dialog = ConfirmWrapAroundDialog(self.text_editor_widget, forward)
                if dialog.exec_() == QDialog.Accepted:
                    should_wrap = True
                else:
                    return None  # 终止流程
            else:
                should_wrap = True  # 静默模式下自动回绕

            if should_wrap:
                wrap_pos = 0 if forward else len(full_text)
                match_obj, all_matches = self.navigation_service.find_match(pattern, full_text, wrap_pos, forward)

                # 回绕后也需要检查是否需要启动计数
                if match_obj and not all_matches and self.search_options.enable_match_count:
                    self.bottom_button_widget.set_calculating_counter_label_text()
                    self.navigation_service.start_background_counting(pattern, full_text, self._on_counting_finished)

        return SearchResult(found_match=match_obj, all_matches=all_matches)

    # ==================== UI 展现与回调 ====================
    def _show_match_in_editor(self, match_obj):
        """高亮并滚动到匹配项"""
        # 1. 移动光标并选中匹配项
        text_edit = self.text_editor_widget.get_text_edit()
        full_text = text_edit.toPlainText()

        qt_start = util.py_to_qt_index(match_obj.start(), full_text)
        qt_end = util.py_to_qt_index(match_obj.end(), full_text)

        cursor = text_edit.textCursor()
        cursor.setPosition(qt_start)
        cursor.setPosition(qt_end, QTextCursor.MoveMode.KeepAnchor)
        text_edit.setTextCursor(cursor)

        # 2. 滚动逻辑
        if self.text_editor_widget.is_smart_scroll_enabled():
            text_edit.smart_scroll()
        else:
            # 如果关闭了智能定位，则始终将匹配项置于可视窗口的垂直中部
            text_edit.centerCursor()

    def _update_counter(self, match_obj, all_matches):
        if not all_matches:
            return

        try:
            index = all_matches.index(match_obj) + 1
            total = len(all_matches)
            self.bottom_button_widget.set_match_counter_label_text(index, total)
        except ValueError:
            self.bottom_button_widget.reset_match_counter_label_text()

    def _on_counting_finished(self, all_matches):
        if not all_matches:
            return

        cursor = self.text_editor_widget.get_cursor()
        full_text = self.text_editor_widget.get_text()
        current_pos = util.qt_to_py_index(cursor.selectionStart(), full_text)

        current_match = None
        if current_pos == 0:
            # 设置新搜索结果时，光标位置为 0，直接找第一个匹配
            current_match = all_matches[0]
        else:
            # 寻找光标位置之后（或恰好在光标上）的第一个匹配项
            for m in all_matches:
                if m.start() >= current_pos:
                    current_match = m
                    break

            # 如果光标位置大于所有匹配项的起始位置，则将当前匹配项设置为最后一个
            # 例如在末尾进行“替换选中”或“替换全部”，就会出现这种情况
            if not current_match:
                current_match = all_matches[-1]

        if current_match:
            self._update_counter(current_match, all_matches)
        else:
            self.bottom_button_widget.reset_match_counter_label_text()

    # ==================== Editor Undo/Redo 联动 ====================
    def on_editor_undo(self, has_undo_steps: bool):
        text_edit = self.text_editor_widget.get_text_edit()
        if not has_undo_steps:
            # 如果没有可撤销的操作，则不执行任何导航相关的逻辑
            text_edit.setFocus()
            return

        prev_match_obj = self.get_prev_match_obj()
        if prev_match_obj is not None:
            full_text = text_edit.toPlainText()
            py_prev_match_end_pos = prev_match_obj.end()
            cursor = text_edit.textCursor()
            py_cursor_pos = util.qt_to_py_index(cursor.position(), full_text)

            if py_prev_match_end_pos == py_cursor_pos:
                # 当撤销后光标位置刚好在前一个匹配末尾时
                # 直接选中前一个匹配，以便替换
                qt_start = util.py_to_qt_index(prev_match_obj.start(), full_text)
                qt_end = util.py_to_qt_index(py_prev_match_end_pos, full_text)
                cursor.setPosition(qt_start, QTextCursor.MoveAnchor)
                cursor.setPosition(qt_end, QTextCursor.MoveMode.KeepAnchor)
                text_edit.setTextCursor(cursor)
                text_edit.ensureCursorVisible()

                # 发射信号通知 ReplaceController 去弹 ToolTip
                self.navigatedToMatch.emit(prev_match_obj)

        text_edit.setFocus()

    def on_editor_redo(self, has_redo_steps: bool):
        text_edit = self.text_editor_widget.get_text_edit()
        if not has_redo_steps:
            # 如果没有可重做的操作，则不执行任何导航相关的逻辑
            text_edit.setFocus()
            return

        self.get_prev_match_obj()  # 静默刷新一下状态
        text_edit.setFocus()

    # ==================== 行号跳转与记录 ====================
    def open_go_to_line_dialog(self):
        matched_lines = self.search_model.get_matched_line_numbers()
        if not matched_lines:
            QMessageBox.warning(self.text_editor_widget, "提示", "没有可用的匹配行号")
            return

        line_num, ok = QInputDialog.getInt(self.text_editor_widget, "跳转到行", "请输入行号：", minValue=1)
        if ok:
            if line_num in matched_lines:
                # 找到完全匹配的行号，直接跳转
                self.go_to_line(line_num)
            else:
                # 没有完全匹配，找到最近的匹配行号并跳转
                closest_line = self._get_closest_line_number(line_num, matched_lines)
                self.go_to_line(closest_line)

    def _get_closest_line_number(self, line_number, matched_line_numbers):
        return min(
            matched_line_numbers,
            key=lambda x: abs(x - line_number),
        )

    def go_to_line(self, line_number: int):
        target_line_str = str(line_number).strip()
        text_edit = self.text_editor_widget.get_text_edit()
        document = text_edit.document()

        block = document.firstBlock()
        while block.isValid():
            if text_edit.get_line_num_from_block(block) == target_line_str:
                cursor = QTextCursor(block)
                text_edit.setTextCursor(cursor)
                text_edit.centerCursor()
                text_edit.setFocus()
                return True
            block = block.next()

        return False

    def go_to_prev_pos(self):
        self.text_editor_widget.get_text_edit().navigate_back()

    def go_to_next_pos(self):
        self.text_editor_widget.get_text_edit().navigate_forward()

    def go_to_top(self):
        cursor = self.text_editor_widget.get_cursor()
        cursor.movePosition(QTextCursor.Start)
        self.text_editor_widget.set_cursor(cursor)
        self.text_editor_widget.get_text_edit().setFocus()

    def on_raw_text_loaded(self, old_line_number: str):
        if not self.search_model.get_matched_line_numbers():
            return

        if self.check_search_text_changed_callback():
            # 搜索词发生变更时，不跳转到原行数的位置
            return

        if old_line_number.isdigit():
            old_line_num_int = int(old_line_number)
            matched_line_numbers = self.search_model.get_matched_line_numbers()
            if old_line_num_int in matched_line_numbers:
                # 找到完全匹配的行号，直接跳转
                self.go_to_line(old_line_num_int)
            else:
                # 找到最近的行号
                closest_line_str = self._get_closest_line_number(old_line_num_int, matched_line_numbers)

                # 检查差值是否在 10 以内，如果是则跳转
                if abs(int(closest_line_str) - old_line_num_int) <= 10:
                    self.go_to_line(closest_line_str)
