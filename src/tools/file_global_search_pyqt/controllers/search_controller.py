import time, importlib, sys, os
import regex
import logging

from qtpy.QtCore import QObject, QTimer, Signal
from qtpy.QtWidgets import QMessageBox, QDialog, QApplication

from typing import TYPE_CHECKING, Dict, Optional, List, Tuple, Callable

if TYPE_CHECKING:
    from models.search_model import SearchModel
    from services.search_service import SearchService
    from core.search_options import SearchOptions
    from widgets.search_widget import SearchWidget
    from widgets.file_widget import FileWidget
    from widgets.text_editor_widget import TextEditorWidget
    from widgets.bottom_button_widget import BottomButtonWidget
    from widgets.context_lines_widget import ContextLinesWidget
    from widgets.replace_widget import ReplaceWidget

from core.constants import PatchSearchAction
from config import HIGHLIGHT_TEXT_LEN_LIMIT, SEARCH_RESULT_CHAR_THRESHOLD, SEARCH_RESULT_PAGE_SIZE
from widgets.dialogs.search_edit_dialog import SearchEditDialog
from widgets.dialogs.patch_search_dialog import PatchSearchDialog  # 独立出来的差异比对弹窗
import utils.util as util


class SearchController(QObject):
    searchCompletedGoToNextMatch = Signal()  # go_to_next_match
    searchCompletedGetNextMatch = Signal()  # get_next_match_obj
    searchStateResetRequested = Signal()  # 触发导航清理缓存
    validSearchOccurred = Signal(str)  # 触发历史记录写入

    _PATCH_SEARCH_PATTERN_STR = r"<［[adn]:[^］]*?］>"
    _LINE_NUM_STRIP_PATTERN = regex.compile(r"^\[(行号|匹配)：\d+\]", regex.M)

    def __init__(
        self,
        search_model: "SearchModel",
        search_service: "SearchService",
        search_options: "SearchOptions",
        search_widget: "SearchWidget",
        file_widget: "FileWidget",
        text_editor_widget: "TextEditorWidget",
        bottom_button_widget: "BottomButtonWidget",
        context_lines_widget: "ContextLinesWidget",
        replace_widget: "ReplaceWidget",
        check_save_callback: Callable[[], bool],
        get_function_color_callback: Callable[[str], Tuple[str, str]],
        get_highlight_rules_callback: Callable[[str], str],
    ):
        super().__init__()

        # 核心服务与模型
        self.search_model = search_model
        self.search_service = search_service
        self.search_options = search_options

        # UI 组件 (依赖注入)
        self.search_widget = search_widget
        self.file_widget = file_widget
        self.text_editor_widget = text_editor_widget
        self.bottom_button_widget = bottom_button_widget
        self.context_lines_widget = context_lines_widget
        self.replace_widget = replace_widget
        self.document = self.text_editor_widget.get_text_edit().document()

        # 回调函数 (外部状态)
        self._check_save_callback = check_save_callback
        self._get_color_callback = get_function_color_callback
        self._get_highlight_rules_callback = get_highlight_rules_callback

        # 内部状态
        self.searching = False
        self.search_start_time = 0
        self.search_task = None
        self.current_search_text = ""
        self.is_search_text_changed = False
        self.hide_old_tag_content = False
        self.patch_merge_threshold = 2

        self.main_search_highlight_rule = ""
        self.cur_search_highlight_rule = ""
        self.highlight_text_len_limit = HIGHLIGHT_TEXT_LEN_LIMIT

        self.original_search_button_text = self.search_widget.get_search_button_text()
        self.original_search_button_style = self.search_widget.get_search_button_style()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_searching_time_display)

        # 初始化 UI，载入规则
        self.context_lines_widget.set_page_size(SEARCH_RESULT_PAGE_SIZE)
        self.on_reload_search()

    # =========================================================
    # 第一模块：上下文行数 (Context Lines) 和搜索条件选择
    # =========================================================
    def on_user_prev_lines_changed(self, value: int):
        """当用户手动改变“上文行数”时触发"""
        if not self.search_model.is_prev_lines_from_config:
            # user_prev_lines 只在使用未配置 prevLines 值的规则时记录并生效
            self.search_model.user_prev_lines = value
        self.search_model.prev_lines = value
        self._reset_editor_fields_on_context_change()

    def on_user_next_lines_changed(self, value: int):
        """当用户手动改变“下文行数”时触发"""
        if not self.search_model.is_next_lines_from_config:
            # user_next_lines 只在使用未配置 nextLines 值的规则时记录并生效
            self.search_model.user_next_lines = value
        self.search_model.next_lines = value
        self._reset_editor_fields_on_context_change()

    def on_condition_selected(self, index: int):
        if index == -1:
            return

        try:
            condition = self.search_model.search_condition_mapping[index]
            self._apply_condition(condition)
            self._update_ui_from_condition(condition)
        except IndexError:
            logging.error(f"Error: Condition index {index} is out of range.")

    def _apply_condition(self, condition: Dict):
        """应用一个新的搜索条件"""
        self.search_model.current_condition = condition
        self.search_options.reset_to_defaults()
        self.search_options.set_enable_match_count(not condition.get("skipMatchCount", False))
        if condition.get("isChapterSearch", False) is True:
            self.search_options.set_show_chapter_title(True)
        self._update_context_lines()

    def _update_context_lines(self):
        """根据当前规则和用户设置，更新实际用于搜索的上下文行数值"""
        cond = self.search_model.current_condition
        if not cond:
            return

        # 检查规则中是否定义了 prevLines
        if "prevLines" in cond:
            self.search_model.is_prev_lines_from_config = True
            self.search_model.prev_lines = cond["prevLines"]
        else:
            # 配置中没有上下文字段，则用用户手动调整的值
            self.search_model.is_prev_lines_from_config = False
            self.search_model.prev_lines = self.search_model.user_prev_lines

        # 检查规则中是否定义了 nextLines
        if "nextLines" in cond:
            self.search_model.is_next_lines_from_config = True
            self.search_model.next_lines = cond["nextLines"]
        else:
            self.search_model.is_next_lines_from_config = False
            self.search_model.next_lines = self.search_model.user_next_lines

        self._reset_editor_fields_on_context_change()

    def _reset_editor_fields_on_context_change(self):
        """
        上下文行数变动时，调整 editorSearch 和 editorReplace，还原为 original 的值
        因为 original 的值不涉及 (行号|匹配) 和换行符之类的信息，在设置高亮时更为准确
        """
        # 和 editorSearch 相等时才重置（搜索后输入框的值被设置为 editorSearch）
        current_search = self.search_widget.get_search_text()
        editor_search = self.search_model.current_condition.get("editorSearch")
        original_search = self.search_model.current_condition.get("search")
        if editor_search and original_search and current_search == editor_search:
            self.search_widget.set_search_text(original_search)

        # 对 editorReplace 做同样的处理
        current_replace = self.replace_widget.get_replace_text()
        editor_replace = self.search_model.current_condition.get("editorReplace")
        original_replace = self.search_model.current_condition.get("replace")
        if editor_replace and original_replace and current_replace == editor_replace:
            self.replace_widget.set_replace_text(original_replace)

    def _update_ui_from_condition(self, condition: Dict):
        """根据新的条件更新 UI 界面"""
        self.search_widget.set_search_text(condition.get("search", ""))
        self.replace_widget.set_replace_text(condition.get("replace", ""))

        # 更新上下文行数 UI，优先使用规则配置，否则使用用户上次设置的值
        self.context_lines_widget.set_prev_lines(condition.get("prevLines", self.search_model.user_prev_lines))
        self.context_lines_widget.set_next_lines(condition.get("nextLines", self.search_model.user_next_lines))

        # 设置上下文行数类型提示
        if self.search_model.is_next_lines_from_config or self.search_model.is_prev_lines_from_config:
            self.context_lines_widget.set_context_line_type_hint("（规则预设）")
        else:
            self.context_lines_widget.set_context_line_type_hint("（用户调整）")

        # 将搜索输入框的滚动条移动到顶部
        QTimer.singleShot(0, lambda: self.search_widget.scroll_search_input_to_top())

    # =========================================================
    # 第二模块：动态高亮与 Editor 联动
    # =========================================================
    def change_cur_search_highlight_rule(self):
        text_len = len(self.text_editor_widget.get_text())
        if (
            # 文本过大时不高亮
            text_len > self.highlight_text_len_limit
            # 在比对视图中不二次高亮
            or self.search_model.is_patch_search() != PatchSearchAction.NOT_PATCH_SEARCH
        ):
            return

        # 暂时阻止 text_edit 发出任何信号，避免触发 textChanged
        text_edit = self.text_editor_widget.get_text_edit()
        text_edit.blockSignals(True)

        try:
            # 实时更改高亮规则
            search_text = self.search_widget.get_search_text()
            highlighter = self.text_editor_widget.get_highlighter()

            if (
                search_text != self.cur_search_highlight_rule
                and self.cur_search_highlight_rule != self.main_search_highlight_rule
            ):
                # 避免将黄色背景的主搜索高亮清除掉
                highlighter.remove_highlight_rule(self.cur_search_highlight_rule, False)

            if search_text not in (self.main_search_highlight_rule, self.cur_search_highlight_rule):
                # 保证上色的操作不被事件循环中的其他事件干扰
                QTimer.singleShot(0, lambda: self._add_cur_search_highlight_rule(search_text))
                self.cur_search_highlight_rule = search_text
        finally:
            # 恢复信号的发送
            text_edit.blockSignals(False)

    def _add_main_search_highlight_rule(self, search_text: str):
        """为搜索文本添加高亮规则"""
        if not search_text:
            return

        bg, fg = self._get_color_callback("main_search_color")
        self.text_editor_widget.get_highlighter().add_highlight_rule(
            # QSyntaxHighlighter 需要使用 PCRE 的 Unicode 写法才能正常高亮
            [util.change_unicode_to_pcre_format(search_text)],
            options=self.search_options.get_qt_regex_flags(),
            background=bg,
            color=fg,
        )

    def _add_cur_search_highlight_rule(self, search_text: str):
        if self.main_search_highlight_rule == search_text or not search_text:
            return

        bg, fg = self._get_color_callback("cur_search_color")

        self.text_editor_widget.get_highlighter().add_highlight_rule(
            [util.change_unicode_to_pcre_format(search_text)],
            options=self.search_options.get_qt_regex_flags(),
            background=bg,
            color=fg,
        )

    # =========================================================
    # 第三模块：复杂弹窗与交互 (Dialogs)
    # =========================================================
    def open_search_edit_dialog(self, _=None):
        """打开搜索编辑对话框"""
        # 好像 mousePressEvent 中肯定会传一个 event 进来，这里忽略掉
        dialog = SearchEditDialog(
            search_text=self.search_widget.get_search_text(),
            search_options=self.search_options,
            search_condition=self.search_model.current_condition,
            replace_text=self.replace_widget.get_replace_text(),
            regex_highlight_rules=self._get_highlight_rules_callback("regex_highlight_rules.json"),
            markdown_style=self._get_highlight_rules_callback("markdown.qss"),
            parent=self.search_widget,
        )
        result = dialog.exec_()
        if result == QDialog.Rejected:
            return

        # 从对话框获取更新后的值
        new_search_text = dialog.get_search_text()
        use_regex, use_dotall, case_sensitive, enable_match_count, add_to_history, show_chapter, max_match_lines = (
            dialog.get_options()
        )

        # 更新 UI 和搜索选项
        self.search_widget.set_search_text(new_search_text)
        self.search_options.set_use_regex(use_regex)
        self.search_options.set_use_dotall(use_dotall)
        self.search_options.set_case_sensitive(case_sensitive)
        self.search_options.set_enable_match_count(enable_match_count)
        self.search_options.set_add_to_history_list(add_to_history)
        self.search_options.set_show_chapter_title(show_chapter)
        self.search_options.set_max_match_lines(max_match_lines)
        self.replace_widget.set_replace_text(dialog.get_replace_text())

        # 根据对话框的关闭方式执行相应操作
        if result == SearchEditDialog.SearchInFile:
            self.perform_search()
        elif result == SearchEditDialog.SearchInEditor:
            # 添加搜索记录
            self._add_to_search_history_list(new_search_text)
            # 跳转到第一个匹配
            self.searchCompletedGoToNextMatch.emit()  # 触发导航
            # 实时更改高亮
            self.change_cur_search_highlight_rule()
        elif result == SearchEditDialog.SetConditionOnly:
            # 仅改变条件，只添加历史记录，不执行搜索
            self._add_to_search_history_list(new_search_text)
            # 实时更改高亮
            self.change_cur_search_highlight_rule()

    def perform_patch_search(self):
        """比对视图入口"""
        dialog = PatchSearchDialog(self.search_widget, self.hide_old_tag_content, self.patch_merge_threshold)
        dialog.exec_()

        self.hide_old_tag_content = dialog.hide_old_content
        self.patch_merge_threshold = dialog.merge_threshold
        if dialog.clicked_button == "search":
            self.perform_search(is_patch_search=dialog.action)
        elif dialog.clicked_button == "guidance":
            if self._check_save_callback():
                return

            rules = self._get_highlight_rules_callback("editor_highlight_rules.json")
            self.text_editor_widget.reset_highlighter(rules)

            guidance_text = self.search_service.get_compare_guidance_md()
            self.text_editor_widget.load_raw_text(guidance_text)

    # =========================================================
    # 第四模块：搜索核心引擎 (_perform_search)
    # =========================================================
    def toggle_search(self):
        if self.searching:
            self._stop_search()
        else:
            self.perform_search()

    def perform_search(self, is_patch_search=PatchSearchAction.NOT_PATCH_SEARCH):
        """执行文件搜索的核心逻辑"""
        if self._check_save_callback():
            return

        if self.searching:
            return

        old_is_patch_search = self.search_model.is_patch_search()
        self.search_model.set_patch_search(is_patch_search)

        if (
            is_patch_search == PatchSearchAction.NOT_PATCH_SEARCH
            and old_is_patch_search == PatchSearchAction.BAK_VS_BOOKS
        ):
            reply = QMessageBox.warning(
                self.search_widget,
                "提示",
                "不支持直接搜索 booksBak 中的文件，\n即将转为搜索 books 中的文件。\n\n是否继续？",
                QMessageBox.Ok | QMessageBox.Cancel,
            )
            if reply == QMessageBox.Cancel:
                return

        # 检测是否在“比对视图”和“普通搜索”之间切换
        patch_search_actions = (PatchSearchAction.BOOKS_VS_BAK, PatchSearchAction.BAK_VS_BOOKS)
        patch_search_mode_changed = old_is_patch_search != is_patch_search and not (
            old_is_patch_search in patch_search_actions and is_patch_search in patch_search_actions
        )

        # 如果不是比对视图模式，且搜索条件为差异项搜索的默认值，还原为当前规则的 search 字段
        if (
            is_patch_search == PatchSearchAction.NOT_PATCH_SEARCH
            and self.search_widget.get_search_text() == self._PATCH_SEARCH_PATTERN_STR
        ):
            self.search_widget.set_search_text(self.search_model.current_condition.get("search", ""))
            self.replace_widget.set_replace_text(self.search_model.current_condition.get("replace", ""))

        search_term = self.search_widget.get_search_text()
        self.is_search_text_changed = (
            patch_search_mode_changed  # 在“比对视图”和“普通搜索”之间切换时，也视作搜索词发生了变更
            or (
                is_patch_search == PatchSearchAction.NOT_PATCH_SEARCH
                and self.current_search_text
                and self.current_search_text != search_term
            )
        )
        self.current_search_text = search_term

        if not search_term:
            self._process_error_result("【搜索内容为空，无法搜索】")
            return

        editor_search = self.search_model.current_condition.get("editorSearch")
        if editor_search and search_term == editor_search:
            # 未修改 editorSearch 条件时，还原为 search，高亮更准确
            search_term = self.search_model.current_condition["search"]
            self._reset_editor_fields_on_context_change()

        file_path = self.file_widget.get_file_path()
        if not os.path.isfile(file_path):
            self._process_error_result("【books 文件夹中无匹配的 txt 文件，无法搜索】")
            return

        # 在比对视图中强制至少显示一行上下文，避免在替换时因缺少上下文而出错
        if is_patch_search != PatchSearchAction.NOT_PATCH_SEARCH:
            force_lines = max(self.context_lines_widget.get_next_lines(), 1)
            self.context_lines_widget.set_prev_lines(force_lines)
            self.context_lines_widget.set_next_lines(force_lines)
            self.search_model.prev_lines = force_lines
            self.search_model.next_lines = force_lines

        # 重置 UI 状态
        self._reset_ui_before_search()

        # 添加历史记录
        self._add_to_search_history_list(search_term)

        # 创建搜索任务
        search_term = self.search_service.revise_condition_before_search(search_term, self.file_widget.is_html_file)
        self.search_task = self.search_service.start_search_task(
            file_path,
            search_term,
            self.search_model.current_condition,
            self.search_model.prev_lines,
            self.search_model.next_lines,
            self.search_options,
            is_patch_search,
            self.patch_merge_threshold,
        )
        self.search_task.signals.formattingResult.connect(self._show_formatting_result_message)
        self.search_task.signals.searchFinished.connect(self._process_success_result)
        self.search_task.signals.searchError.connect(self._process_error_result)

    def _reset_ui_before_search(self):
        # 设置搜索状态为开始，记录开始时间
        self.text_editor_widget.reset_editor_color()
        self.text_editor_widget.load_raw_text("【搜索中：（已执行 0 秒），如耗时过长，可停止当前搜索】")
        self.searching = True
        self.search_start_time = time.time()
        self.timer.start(1000)

        # 修改按钮为“停止”状态
        self.search_widget.set_search_button_text("停止")
        self.search_widget.set_search_button_style("color: white; background-color: #D9534F;")

        # 当无上下文时不改变匹配行的字符颜色
        highlighter = self.text_editor_widget.get_highlighter()
        highlighter.set_has_context_lines(self.search_model.prev_lines != 0 or self.search_model.next_lines != 0)

        # 重置高亮规则
        self.text_editor_widget.reset_highlighter(self._get_highlight_rules_callback("editor_highlight_rules.json"))

        # 隐藏差异项中的灰色【旧内容】
        self._hide_old_tag_content()

    def _hide_old_tag_content(self):
        if self.search_model.is_patch_search() != PatchSearchAction.NOT_PATCH_SEARCH:
            pattern = "(?<=<［)o:.*?(?=］>)"
            highlighter = self.text_editor_widget.get_highlighter()

            if self.hide_old_tag_content:
                highlighter.remove_highlight_rule(pattern, False)
                highlighter.add_highlight_rule(
                    [pattern], rehighlight=True, color="transparent", **{"font-size": 1, "letter-spacing": -1}
                )
            else:
                highlighter.remove_highlight_rule(pattern)

    def _update_searching_time_display(self):
        if self.search_start_time:
            elapsed = int(time.time() - self.search_start_time)
            self.text_editor_widget.load_raw_text(f"【搜索中：（已执行 {elapsed} 秒），如耗时过长，可停止当前搜索】")
            QApplication.processEvents()

    def _stop_search(self):
        """停止当前的搜索任务"""
        if self.search_task and hasattr(self.search_task, "stop"):
            self.search_task.stop()
        self.search_task = None

        self.searching = False
        self.timer.stop()
        self._process_error_result("【搜索已手动停止】")

    # =========================================================
    # 第五模块：搜索结果处理与分页
    # =========================================================
    def _show_formatting_result_message(self, match_positions_count: int):
        # 此处也要终止计时，避免在整理较长的结果时，因耗时过长还反复出现计时信息
        self.timer.stop()
        self.text_editor_widget.load_raw_text(f"【共 {match_positions_count} 处匹配，正在准备显示结果，不可中断】")

    def _process_success_result(
        self, result_text: str, match_blocks_count: int, matches_count: int, all_matched_line_numbers: List
    ):
        # 检查结果长度
        cur_page_size = self.context_lines_widget.get_page_size()

        if not self._check_result_size_and_prompt(result_text, match_blocks_count, cur_page_size):
            self._process_error_result("【操作已取消：搜索结果过长，可尝试调整分页尺寸和上下文行数，再重试搜索】")
            return

        # 构建 Header
        if self.search_start_time:
            elapsed_time = int(time.time() - self.search_start_time)
            if self.search_model.is_patch_search() == PatchSearchAction.BOOKS_VS_BAK:
                header = f"【搜索耗时 {elapsed_time} 秒，共有 {match_blocks_count} 个以 books 为主体的差异项】"
                result_text = result_text.replace(f"匹配内容【共有 N 处匹配】", header)
            elif self.search_model.is_patch_search() == PatchSearchAction.BAK_VS_BOOKS:
                header = f"【搜索耗时 {elapsed_time} 秒，共有 {match_blocks_count} 个以 booksBak 为主体的差异项】"
                result_text = result_text.replace(f"匹配内容【共有 N 处匹配】", header)
            else:
                header = f"【搜索耗时 {elapsed_time} 秒，共有 {match_blocks_count} 个匹配项，{matches_count} 处匹配】"
                result_text = result_text.replace(f"匹配内容【共有 N 处匹配】", header)
            self.bottom_button_widget.set_match_counter_label_tool_tip(header)

        # 回调修改 (非差异视图)
        search_callback = self.search_model.current_condition.get("searchCallback")
        if (
            self.search_model.is_patch_search() == PatchSearchAction.NOT_PATCH_SEARCH
            and search_callback
            and callable(search_callback)
        ):
            result_text = search_callback(result_text, self.file_widget.get_file_path())

        self.search_model.set_initial_search_result(result_text)
        display_text = result_text

        # 判断是否需要分页显示
        if match_blocks_count > cur_page_size:
            QMessageBox.information(
                self.search_widget,
                "分页提示",
                f"当前共有 {match_blocks_count} 个匹配项，超过单页可显示数量：{cur_page_size}，"
                "将分页进行显示。\n\n请注意下方的页码按钮，按页分批处理结果。",
            )
            self.search_model.set_has_pagination(True)
            self.bottom_button_widget.update_pagination_controls(match_blocks_count, cur_page_size)

            # 根据编辑器记录的 old_line_number 动态计算目标页码，自动跳转到重新搜索之前的进度位置
            target_page = 1
            if not self.is_search_text_changed:
                old_line_number_str = self.text_editor_widget.get_text_edit().get_current_line_number()
                old_line_number = (
                    int(old_line_number_str) if old_line_number_str and old_line_number_str.isdigit() else -1
                )
                page_line_ranges = self.search_service.get_page_line_ranges(
                    display_text, match_blocks_count, cur_page_size
                )

                for i, (s_line, e_line) in enumerate(page_line_ranges):
                    if s_line <= old_line_number <= e_line:
                        target_page = i + 1
                        break

            display_text = self._load_page_text(target_page)
            if target_page != 1:
                # 仅改变页码的 UI 展示，不发射 pageChanged 信号，避免重复触发 load_raw_text
                self.bottom_button_widget.switch_to_page(target_page, False)
        else:
            self.search_model.set_has_pagination(False)
            self.bottom_button_widget.set_pagination_visible(False)

        # 给当前规则的匹配加上黄色背景高亮
        search_text = self.search_widget.get_search_text()
        if (
            # 避免在显示差异时所有类型的标签都变成黄色背景
            self.search_model.is_patch_search() == PatchSearchAction.NOT_PATCH_SEARCH
            and search_text != self._PATCH_SEARCH_PATTERN_STR
        ):
            self._add_main_search_highlight_rule(search_text)
            self.main_search_highlight_rule = search_text

        self._finalize_search_operation(display_text)
        self._update_editor_condition()

        # 在比对视图中更换为检索差异项的专用正则
        if self.search_model.is_patch_search() != PatchSearchAction.NOT_PATCH_SEARCH:
            self.search_widget.set_search_text(self._PATCH_SEARCH_PATTERN_STR)
            self.replace_widget.set_replace_text("")

        self.search_model.set_matched_line_numbers(all_matched_line_numbers)

        # 获取一下匹配计数
        # 使用 singleShot 是因为在 CustomPlainTextEdit.load_raw_text() 设置高亮时，
        # 可能会在当前事件循环中重复触发 textChanged，导致 NavigationCounterTask 被取消
        QTimer.singleShot(0, lambda: self.searchCompletedGetNextMatch.emit())

    def _check_result_size_and_prompt(self, result_text: str, match_blocks_count: int, cur_page_size: int) -> bool:
        """检查单页结果的字符数，如果过长则提示用户"""
        if match_blocks_count > 0:
            text_to_check = self._LINE_NUM_STRIP_PATTERN.sub("", result_text)  # 已有单独行号区域，不再需要统计行号字数
            num_to_check = min(cur_page_size, match_blocks_count)

            # 找到第一个匹配块的起始位置
            start_pos = self.search_service.find_match_offset(text_to_check, 1, 0)
            if start_pos == -1:
                return True  # 没有找到匹配项，直接继续

            # 找到第 num_to_check + 1 个匹配块的起始位置
            # 这标志着前 num_to_check 个块的结束
            end_pos = -1
            if (num_to_check + 1) <= match_blocks_count:
                # 从第一个匹配项之后开始搜索，以提高效率
                end_pos = self.search_service.find_match_offset(text_to_check, num_to_check + 1, start_pos)

            char_count = 0
            if end_pos != -1:
                # 如果找到了第 n+1 项，计算从第 1 项到它的长度
                char_count = end_pos - start_pos
            else:
                # 如果没有第 n+1 项，说明后面没有更多匹配块了，计算到文本末尾
                char_count = len(text_to_check) - start_pos

            if char_count > SEARCH_RESULT_CHAR_THRESHOLD:
                reply = QMessageBox.warning(
                    self.search_widget,
                    "结果可能过长",
                    f"单页共有【{num_to_check}】个匹配项，"
                    f"约有【{char_count / 10000:.1f} 万】个字符（含匹配项、分隔行标记等），\n"
                    f"继续加载可能会导致程序卡住一段时间。\n\n您确定要继续吗？\n\n"
                    f"100 万到 200 万字左右一般可以直接显示，问题不大。\n"
                    f"如果实在过长，可以选择不继续加载，\n"
                    "调整【分页尺寸】和【上下文行数】后，再重试搜索。",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    return False  # 用户选择不继续

        return True  # 继续处理

    def _load_page_text(self, page_num: int) -> str:
        page_info = self.bottom_button_widget.get_page_info(page_num)
        if not page_info:
            return ""

        start_idx = page_info.get("start_index")
        end_idx = page_info.get("end_index")

        initial = self.search_model.get_initial_search_result()
        start_pos = self.search_service.find_match_offset(initial, start_idx)
        # 查找下一页的第一项作为当前页的结束点
        # 如果是最后一页，end_index + 1 将找不到，find 返回 -1
        end_pos = self.search_service.find_match_offset(initial, end_idx + 1, start_pos)

        if start_pos == -1:
            return ""
        if end_pos != -1:
            return initial[start_pos:end_pos].rstrip("\n") + "\n"

        # 最后一页，截取到最后
        return initial[start_pos:]

    def _process_error_result(self, error_message: str):
        self.search_model.set_matched_line_numbers([])
        self.text_editor_widget.get_highlighter().remove_highlight_rule(self.cur_search_highlight_rule)
        self.search_model.set_initial_search_result(error_message)
        self.search_model.set_has_pagination(False)
        self._finalize_search_operation(error_message)

    def _finalize_search_operation(self, display_text: str):
        """处理搜索操作结束后的通用逻辑，包括将文本设置到编辑器、设置 modified 标记等"""
        self.searching = False
        self.timer.stop()

        # 重置按钮样式和计数器
        self.search_widget.set_search_button_text(self.original_search_button_text)
        self.search_widget.set_search_button_style(self.original_search_button_style)
        self.bottom_button_widget.reset_match_counter_label_text()

        # 将搜索结果设置到编辑器，并进行记录
        self.text_editor_widget.load_raw_text(display_text)
        self.text_editor_widget.handle_major_content_change()
        self.text_editor_widget.set_normal_search_result(display_text)

        # 设置当前结果字数，移除所有不计入统计的标记和元信息
        patch_action = self.search_model.is_patch_search()
        info, hl = self.search_service.calculate_char_count_info(
            display_text, self.file_widget.get_file_path(), patch_action
        )
        self.bottom_button_widget.set_editor_info_label_text(info, hl)

        # 判断当前是否为 patch 差异比对视图，更改保存按钮提示文字
        text, hl = self.search_service.save_button_text(patch_action)
        self.bottom_button_widget.set_save_button_text(text, hl)

        # 判断当前是否为 patch 差异比对视图，显示或隐藏编辑器侧边栏还原差异项按钮
        if patch_action != PatchSearchAction.NOT_PATCH_SEARCH:
            self.text_editor_widget.ui.revert_diff_button.setVisible(True)
        else:
            self.text_editor_widget.ui.revert_diff_button.setVisible(False)

        # 清空扩展历史栈
        self.search_model.clear_extension_stacks()
        self.document.clearUndoRedoStacks()
        self.text_editor_widget.set_content_modified(False)
        self.bottom_button_widget.set_save_button_hint(False)

    def _update_editor_condition(self):
        """根据 editorSearch 和 editorReplace 的设置，改变搜索框和替换框的值"""
        current_condition = self.search_model.current_condition
        if not current_condition:
            return

        # 仅当搜索框内容与规则的 'search' 字段相同时，或强制设置时，才更新
        # 这防止了用户自定义的搜索条件被意外覆盖
        is_search_unmodified = self.search_widget.get_search_text() == current_condition.get("search")
        # 硬回车那一条特殊处理，需要强制设置 editorSearch 以支持多行替换
        force_set = current_condition.get("forceSetEditorSearch", False)

        if is_search_unmodified or force_set:
            # 设置了 editorSearch 时，将输入框设置为 editorSearch 的值
            editor_search = current_condition.get("editorSearch", "")
            if editor_search:
                self.search_widget.set_search_text(editor_search)

            # 设置了 editorReplace 时，将输入框设置为 editorReplace 的值
            editor_replace = current_condition.get("editorReplace", "")
            if editor_replace:
                self.replace_widget.set_replace_text(editor_replace)

    # =========================================================
    # 第六模块：分页动作与撤销重做
    # =========================================================
    def on_page_changed(
        self, page_num: int, prev_page_num: int, is_initiating_pagination: bool = False
    ) -> Optional[str]:
        if self._check_save_callback():
            # 用户点击了取消，恢复分页按钮的 UI，跳回原来的分页
            self.bottom_button_widget.switch_to_page(prev_page_num, False)
            return

        display_text = self._load_page_text(page_num)
        if not display_text:
            QMessageBox.warning(self.search_widget, "分页错误", f"找不到页码 {page_num} 的分页信息。\n请重新搜索。")
            return

        if not is_initiating_pagination:
            self.text_editor_widget.reset_editor_color()
            self.text_editor_widget.load_raw_text(display_text)

            info, hl = self.search_service.calculate_char_count_info(
                display_text, self.file_widget.get_file_path(), self.search_model.is_patch_search()
            )
            self.bottom_button_widget.set_editor_info_label_text(info, hl)

            self.search_model.clear_extension_stacks()
            self.document.clearUndoRedoStacks()
            self.text_editor_widget.set_content_modified(False)

            # 获取计数，navigation_controller
            QTimer.singleShot(0, lambda: self.searchCompletedGetNextMatch.emit())

        return display_text

    def update_search_result_on_extend(self, old_text: str, new_text: str):
        # 在旧文本中同步移除进度信息
        initial = self.search_model.get_initial_search_result()
        self.search_model.set_initial_search_result(initial.replace(old_text, new_text))

        # 获取当前的 Undo 栈深度
        # 注意：因为扩展操作刚刚完成（insertText 已执行），现在的 depth 就是包含该操作后的深度
        cur_depth = self.document.availableUndoSteps()

        # 记录：(旧文本, 新文本, 对应的栈深度)
        self.search_model.extension_history.append((old_text, new_text, cur_depth))

        # 更新安全撤销拦截标记
        self.search_model.last_extension_depth = cur_depth
        self.search_model.has_saved_after_extension = False

        # 清空重做栈（因为有了新操作，之前的重做路径失效）
        self.search_model.extension_redo_stack.clear()

    def update_search_result_by_page(self):
        current_text = self.text_editor_widget.get_raw_text()

        # 1. 获取当前编辑内容的匹配项序号范围
        matches = list(regex.finditer(r"【匹配项：(\d+)/\d+】", current_text))
        if not matches:
            QMessageBox.warning(self.search_widget, "更新错误", "当前文本中找不到任何“匹配项”，无法确定更新范围。")
            return

        first_item_num = int(matches[0].group(1))
        last_item_num = int(matches[-1].group(1))

        # 2. 在原始结果中定位替换区间
        initial = self.search_model.get_initial_search_result()
        new_initial = self.search_service.splice_page_result(initial, current_text, first_item_num, last_item_num)

        if not new_initial:
            QMessageBox.warning(
                self.search_widget,
                "更新错误",
                f"无法在原始搜索结果中定位起始项 {first_item_num}。\n"
                f"原始结果可能已过期，建议去 BC 检查修改结果，并重新搜索。",
            )
            return

        self.search_model.set_initial_search_result(new_initial)

    def on_editor_undo(self, _: bool):
        """
        当编辑器执行撤销时触发
        """
        if not self.search_model.extension_history:
            return

        # 获取当前（撤销动作发生后）的栈深度
        current_depth = self.document.availableUndoSteps()

        # 如果已经保存过，且当前撤销尝试越过（小于）扩展时的深度
        if self.search_model.has_saved_after_extension and self.search_model.last_extension_depth is not None:
            if current_depth < self.search_model.last_extension_depth:
                # 1. 强行重做，恢复内容
                self.text_editor_widget.get_text_edit().redo()

                # 2. 弹出警告
                QMessageBox.warning(
                    self.text_editor_widget,
                    "撤销受阻",
                    "由于您在【扩展上下文】后已经【执行过保存】，\n"
                    "为了防止实际文件内容与编辑器视图不一致，\n"
                    "不支持撤销到扩展操作之前。\n\n"
                    "如需恢复，请尝试重新搜索或手动修改。",
                )
                return

        old_text, new_text, recorded_depth = self.search_model.extension_history[-1]

        # 如果 当前深度 < 记录深度，说明刚才那个撤销动作把“扩展操作”给撤没了
        if current_depth < recorded_depth:
            # 回滚 initial_search_result
            initial = self.search_model.get_initial_search_result()
            self.search_model.set_initial_search_result(initial.replace(new_text, old_text))

            # 移入重做栈
            self.search_model.extension_redo_stack.append(self.search_model.extension_history.pop())
        else:
            # 当前深度 >= 记录深度，说明撤销的是扩展操作“之后”的手动输入
            # initial_search_result 保持不变
            # logging.info(f"检测到普通撤销，忽略。当前深度: {current_depth}, 扩展深度: {recorded_depth}")
            pass

    def on_editor_redo(self, _: bool):
        """
        当编辑器执行重做时触发
        """
        if not self.search_model.extension_redo_stack:
            return

        # 获取当前（重做动作发生后）的栈深度
        current_depth = self.document.availableUndoSteps()

        # 查看待重做的扩展操作的深度
        old_text, new_text, recorded_depth = self.search_model.extension_redo_stack[-1]

        # 如果 当前深度 == 记录深度，说明刚才那个重做动作正好恢复了【扩展】操作
        # (注：Redo 发生后，深度会增加，正好回到 recorded_depth)
        if current_depth == recorded_depth:
            # 恢复 initial_search_result
            initial = self.search_model.get_initial_search_result()
            self.search_model.set_initial_search_result(initial.replace(old_text, new_text))

            # 移回历史栈
            self.search_model.extension_history.append(self.search_model.extension_redo_stack.pop())

    # =========================================================
    # 其他辅助与回调
    # =========================================================
    def _add_to_search_history_list(self, search_text: str):
        if not self.search_options.add_to_history_list:
            return
        editor_search = self.search_model.current_condition.get("editorSearch")
        search = self.search_model.current_condition.get("search")
        if search_text not in (editor_search, search):
            self.validSearchOccurred.emit(search_text)

    def on_save_completed(self):
        if self.search_model.has_pagination():
            self.update_search_result_by_page()
        else:
            self.search_model.set_initial_search_result(self.text_editor_widget.get_raw_text())

        self.text_editor_widget.set_content_modified(False)
        self.bottom_button_widget.set_save_button_hint(False)

        # 如果在扩展后点击了保存，更新标记
        if self.search_model.last_extension_depth is not None:
            self.search_model.has_saved_after_extension = True

    def on_reload_search(self):
        try:
            importlib.reload(sys.modules["config"])
            from config import SEARCH_CONDITIONS, HIGHLIGHT_TEXT_LEN_LIMIT

            self.search_model.search_condition_mapping = SEARCH_CONDITIONS
            self.highlight_text_len_limit = HIGHLIGHT_TEXT_LEN_LIMIT

            # 通知外部：重新加载样式和高亮，保存历史等 (由 MainWindow 连线触发)
            self.searchStateResetRequested.emit()
        except Exception as e:
            QMessageBox.warning(self.search_widget, "重载失败", str(e))
            return

        cur_desc = self.search_widget.get_desc_text()
        self.search_widget.set_search_conditions(self.search_model.search_condition_mapping)
        new_descs = [c.get("desc", "") for c in self.search_model.search_condition_mapping]
        new_index = (
            new_descs.index(cur_desc)
            if cur_desc in new_descs
            else (0 if self.search_model.search_condition_mapping else -1)
        )
        if new_index != -1:
            self.search_widget.set_desc_index(new_index)
        self.on_condition_selected(new_index)

    def handle_theme_changed(self, _: str):
        """
        当接收到主题已切换的信号时调用
        """
        text_editor_widget = self.text_editor_widget
        text_len = len(text_editor_widget.get_text())

        # 当文本过长时不重置高亮，弹出提示
        if text_len > 200000:
            QMessageBox.information(
                text_editor_widget, "文本过长", "当前文本框的内容过长，不会实时更新文本样式\n可以重新搜索，刷新内容"
            )
            return

        # 1. 重新加载纯文本以刷新所有底层渲染
        text_editor_widget.reload_text()

        # 2. 从回调获取最新的高亮规则并重置高亮器
        new_rules = self._get_highlight_rules_callback("editor_highlight_rules.json")
        text_editor_widget.reset_highlighter(new_rules)

        # 3. 重新添加搜索专用的黄色高亮
        self._add_main_search_highlight_rule(self.main_search_highlight_rule)

    def get_search_text_changed(self) -> bool:
        """当搜索内容发生变更时，一律不尝试跳转到之前的位置"""
        return self.is_search_text_changed
