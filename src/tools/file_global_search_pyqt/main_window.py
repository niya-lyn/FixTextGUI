import os

from qtpy.QtWidgets import QMainWindow, QApplication, QShortcut
from qtpy.QtGui import QKeySequence, QDragEnterEvent, QDropEvent, QCloseEvent
from qtpy.QtCore import QPoint, QSize, Signal, Qt

from resources.ui_generated.ui_main_window import Ui_MainWindow
import resources.resources_rc

from core.search_options import SearchOptions
from core.context_menu import ContextMenu
from core.env_config import env_config

from controllers.match_extender import MatchExtender
from controllers.file_controller import FileController
from controllers.save_controller import SaveController
from controllers.style_controller import StyleController
from controllers.history_controller import HistoryController
from controllers.replace_controller import ReplaceController
from controllers.navigation_controller import NavigationController
from controllers.search_controller import SearchController

from services.file_service import FileService
from services.save_service import SaveService
from services.style_service import StyleService
from services.history_service import HistoryService
from services.replace_service import ReplaceService
from services.navigation_service import NavigationService
from services.search_service import SearchService

from models.file_model import FileModel
from models.search_model import SearchModel

from config import SHORTCUTS

from core.constants import SaveAction


class MainWindow(QMainWindow):

    fileDropped = Signal(str)

    def __init__(self) -> None:
        super(MainWindow, self).__init__()

        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.setAcceptDrops(True)

        # --- UI 控件 ---
        self.file_widget = self.ui.fileWidget
        self.search_widget = self.ui.searchWidget
        self.replace_widget = self.ui.replaceWidget
        self.context_lines_widget = self.ui.contextLinesWidget
        self.text_editor_widget = self.ui.textEditorWidget
        self.bottom_button_widget = self.ui.bottomButtonWidget

        # --- Models ---
        self.file_model = FileModel()
        self.search_model = SearchModel()

        # --- 核心服务 ---
        self.search_options = SearchOptions()
        self.file_service = FileService(self.file_model, env_config.file_dir)
        self.save_service = SaveService()
        self.style_service = StyleService(os.path.dirname(os.path.abspath(__file__)))
        self.history_service = HistoryService(env_config.history_log_file)
        self.search_service = SearchService(env_config.compare_guidance_md)
        self.navigation_service = NavigationService()
        self.replace_service = ReplaceService()

        # --- 控制器 ---
        self.file_controller = FileController(
            self.file_widget,
            self.text_editor_widget,
            self.file_service,
            self.file_model,
            env_config.file_dir,
            env_config.epub_merger_script,
        )
        self.save_controller = SaveController(
            self,
            self.text_editor_widget,
            self.bottom_button_widget,
            self.file_service,
            self.save_service,
            self.search_model,
        )
        self.style_controller = StyleController(
            self,
            self.style_service,
            self.history_service.get_theme(),
            self.save_controller.is_save_cancelled,
        )
        self.history_controller = HistoryController(
            self,
            self.history_service,
            self.search_widget,
            self.replace_widget,
            self.text_editor_widget,
            self.search_options,
            self.style_controller.get_function_color,
        )
        self.search_controller = SearchController(
            self.search_model,
            self.search_service,
            self.search_options,
            self.search_widget,
            self.file_widget,
            self.text_editor_widget,
            self.bottom_button_widget,
            self.context_lines_widget,
            self.replace_widget,
            self.save_controller.is_save_cancelled,
            self.style_controller.get_function_color,
            self.style_controller.get_highlight_rules,
        )
        self.navigation_controller = NavigationController(
            self.navigation_service,
            self.search_model,
            self.text_editor_widget,
            self.search_widget,
            self.bottom_button_widget,
            self.search_options,
            self.search_controller.get_search_text_changed,
        )
        self.replace_controller = ReplaceController(
            self.replace_service,
            self.text_editor_widget,
            self.replace_widget,
            self.search_widget,
            self.search_options,
            self.search_model,
        )
        self.match_extender = MatchExtender(
            self.search_model,
            self.file_widget,
            self.text_editor_widget,
            self.bottom_button_widget,
        )
        self.text_edit_context_menu = ContextMenu(self.text_editor_widget, self.file_widget, self.match_extender)

        # --- 连接信号、初始化 UI ---
        self._connect_signals()
        self._bind_shortcuts()
        self._set_initial_window_size()

    def _connect_signals(self) -> None:
        # --- 跨 controller 信号 ---
        # 当单步替换完成，要求执行查找下一个
        self.replace_controller.replaceCompletedAndRequestNext.connect(self.navigation_controller.go_to_next_match)
        # 当【替换选区】或【全部替换】完成后，要求导航模块重新统计计数
        self.replace_controller.bulkReplaceCompleted.connect(self.navigation_controller.get_next_match_obj)
        # 发生了有效的替换，发送给历史记录模块添加
        self.replace_controller.validReplaceOccurred.connect(self.history_controller.add_new_replace_entry)
        # 当导航跳到了下一个匹配项时，让替换模块去弹出 ToolTip
        self.navigation_controller.navigatedToMatch.connect(self.replace_controller.show_replace_tool_tip)
        # 发生了有效的搜索，发送给历史记录模块添加
        self.search_controller.validSearchOccurred.connect(self.history_controller.add_new_search_entry)
        # 当文本被修改、或搜索词变了，需要令 Navigation 缓存失效
        self.search_controller.searchStateResetRequested.connect(self.navigation_controller.invalidate_cache)
        # 搜索完成，跳转到下一个匹配项
        self.search_controller.searchCompletedGoToNextMatch.connect(self.navigation_controller.go_to_next_match)
        # 搜索完成，获取下一个匹配项
        self.search_controller.searchCompletedGetNextMatch.connect(self.navigation_controller.get_next_match_obj)
        # 匹配项扩展完成，更新 initial_search_result
        self.match_extender.matchExtended.connect(self.search_controller.update_search_result_on_extend)
        # 保存完成，更新 initial_search_result
        self.save_controller.saveCompleted.connect(self.search_controller.on_save_completed)
        # 保存完成，进入比对视图
        self.save_controller.patchSearchRequested.connect(self.search_controller.perform_patch_search)
        # 切换主题，重置高亮
        self.style_controller.themeChanged.connect(self.search_controller.handle_theme_changed)
        self.style_controller.themeChanged.connect(self.history_controller.handle_theme_changed)
        # 处理点击搜索历史，需要跨多个 controller 协作
        self.history_controller.searchItemSelected.connect(self._workflow_history_search)
        # 处理点击替换历史，需要跨多个 controller 协作
        self.history_controller.replaceItemSelected.connect(self._workflow_history_replace)

        # --- FileWidget 信号 ---
        self.file_widget.ui.theme_switch.clicked.connect(self.style_controller.toggle_theme)
        self.file_widget.ui.text_editor_style_button.clicked.connect(self.style_controller.update_text_editor_style)
        self.file_widget.lineNumToggleRequested.connect(self.text_editor_widget.toggle_line_num)
        self.file_widget.patchSearchRequested.connect(self.search_controller.perform_patch_search)

        # --- SearchWidget 信号 ---
        self.search_widget.ui.desc_combo_box.currentIndexChanged.connect(self.search_controller.on_condition_selected)
        self.search_widget.ui.reload_search_button.clicked.connect(self.search_controller.on_reload_search)
        self.search_widget.ui.search_input.mousePressEvent = self.search_controller.open_search_edit_dialog
        self.search_widget.ui.search_button.clicked.connect(self.search_controller.toggle_search)
        self.search_widget.ui.search_input.textChanged.connect(self.navigation_controller.invalidate_cache)
        # 选项变更时也使缓存失效
        self.search_options.optionsChanged.connect(self.navigation_controller.invalidate_cache)

        # --- ReplaceWidget 信号 ---
        self.replace_widget.ui.replace_next_button.clicked.connect(self.replace_controller.replace_and_find_next)
        self.replace_widget.ui.replace_selection_button.clicked.connect(self.replace_controller.replace_in_selection)
        self.replace_widget.ui.replace_all_button.clicked.connect(self.replace_controller.replace_all)
        self.replace_widget.ui.undo_last_replace_button.clicked.connect(self.text_editor_widget.get_text_edit().undo)
        self.replace_widget.ui.replace_shortcuts_checkbox.clicked.connect(
            self.replace_controller.toggle_replace_shortcuts
        )
        self.replace_widget.ui.search_history_list.itemClicked.connect(self.history_controller.on_search_list_clicked)
        self.replace_widget.ui.replace_history_list.itemClicked.connect(
            self.history_controller.on_replace_list_clicked
        )

        # --- ContextLinesWidget 信号 ---
        self.context_lines_widget.ui.prev_lines_spin_box.valueChanged.connect(
            self.search_controller.on_user_prev_lines_changed
        )
        self.context_lines_widget.ui.next_lines_spin_box.valueChanged.connect(
            self.search_controller.on_user_next_lines_changed
        )
        self.context_lines_widget.prevLinesChanged.connect(self.search_controller.on_user_prev_lines_changed)
        self.context_lines_widget.nextLinesChanged.connect(self.search_controller.on_user_next_lines_changed)

        # --- TextEditorWidge 信号 ---
        self.text_editor_widget.ui.text_edit.replaceByListIndex.connect(self.replace_controller.replace_by_list_index)
        self.text_editor_widget.ui.prev_match_button.clicked.connect(self.navigation_controller.go_to_prev_match)
        self.text_editor_widget.ui.next_match_button.clicked.connect(self.navigation_controller.go_to_next_match)
        self.text_editor_widget.ui.text_edit.textChanged.connect(self.navigation_controller.invalidate_cache)
        self.text_editor_widget.ui.text_edit.undoPerformed.connect(self.search_controller.on_editor_undo)
        self.text_editor_widget.ui.text_edit.redoPerformed.connect(self.search_controller.on_editor_redo)
        self.text_editor_widget.ui.text_edit.undoPerformed.connect(self.navigation_controller.on_editor_undo)
        self.text_editor_widget.ui.text_edit.redoPerformed.connect(self.navigation_controller.on_editor_redo)
        self.text_editor_widget.ui.text_edit.rawTextLoaded.connect(self.navigation_controller.on_raw_text_loaded)
        self.text_editor_widget.ui.text_edit.syncingDiff.connect(self.save_controller.sync_diff_to_books_bak)
        self.text_editor_widget.ui.replace_next_button.clicked.connect(self.replace_controller.replace_and_find_next)
        self.text_editor_widget.ui.undo_last_replace_button.clicked.connect(
            self.text_editor_widget.get_text_edit().undo
        )
        self.text_editor_widget.ui.merge_selected_lines_button.clicked.connect(
            self.text_editor_widget.get_text_edit().merge_selected_lines
        )
        self.text_editor_widget.ui.extend_current_matches_button.clicked.connect(
            self.match_extender.extend_current_matches
        )
        self.text_editor_widget.ui.revert_diff_button.clicked.connect(
            self.text_edit_context_menu.revert_diff
        )

        # 设置右键点击某些按键时撤销操作
        right_click_buttons = [
            self.text_editor_widget.ui.replace_next_button,
            self.text_editor_widget.ui.merge_selected_lines_button,
            self.text_editor_widget.ui.extend_current_matches_button,
            self.text_editor_widget.ui.revert_diff_button,
        ]

        for btn in right_click_buttons:
            # 开启自定义上下文菜单策略 (即允许捕获右键)
            btn.setContextMenuPolicy(Qt.CustomContextMenu)

            # customContextMenuRequested 信号会默认传递一个 QPoint (鼠标位置) 参数，忽略掉
            btn.customContextMenuRequested.connect(lambda _: self.text_editor_widget.get_text_edit().undo())

        # --- BottomButtonWidget 信号 ---
        self.bottom_button_widget.ui.go_to_line_button.clicked.connect(
            self.navigation_controller.open_go_to_line_dialog
        )
        self.bottom_button_widget.ui.go_to_top_button.clicked.connect(self.navigation_controller.go_to_top)
        self.bottom_button_widget.ui.go_to_prev_pos_button.clicked.connect(self.navigation_controller.go_to_prev_pos)
        self.bottom_button_widget.ui.go_to_next_pos_button.clicked.connect(self.navigation_controller.go_to_next_pos)
        self.bottom_button_widget.pageChanged.connect(self.search_controller.on_page_changed)

    def _bind_shortcuts(self) -> None:
        """绑定快捷键到对应的功能"""
        shortcut_mappings = {
            # search_controller
            "FIND": self.search_controller.open_search_edit_dialog,
            # replace_controller
            "REPLACE_AND_FIND_NEXT": self.replace_controller.replace_and_find_next,
            "REPLACE_AND_FIND_NEXT_2": self.replace_controller.replace_and_find_next,
            "REPLACE_IN_SELECTION": self.replace_controller.replace_in_selection,
            "REPLACE_IN_SELECTION_2": self.replace_controller.replace_in_selection,
            "UNDO_LAST_REPLACE": self.text_editor_widget.get_text_edit().undo,
            "UNDO_LAST_REPLACE_2": self.text_editor_widget.get_text_edit().undo,
            # navigation_controller
            "GO_TO_TOP": self.navigation_controller.go_to_top,
            "GO_TO_LINE": self.navigation_controller.open_go_to_line_dialog,
            "GO_TO_PREV_MATCH_1": self.navigation_controller.go_to_prev_match,
            "GO_TO_PREV_MATCH_2": self.navigation_controller.go_to_prev_match,
            "GO_TO_NEXT_MATCH_1": self.navigation_controller.go_to_next_match,
            "GO_TO_NEXT_MATCH_2": self.navigation_controller.go_to_next_match,
            # save_controller
            "SAVE_CHANGES": self.save_controller.request_direct_save,
        }

        for shortcut_key, handler in shortcut_mappings.items():
            QShortcut(QKeySequence(SHORTCUTS[shortcut_key]), self).activated.connect(handler)

    def _workflow_history_search(self, search_text: str):
        """处理点击搜索历史"""
        # 1. 如果搜索词没变，直接导航到下一个
        if search_text == self.search_widget.get_search_text():
            self.navigation_controller.go_to_next_match()
            return

        # 2. 搜索词改变了：通知 Search 模块更新
        self.search_widget.set_search_text(search_text)
        self.search_controller.change_cur_search_highlight_rule()

        # 3. 检查匹配项并决定导航行为
        if self.navigation_controller.get_next_match_obj():
            self.navigation_controller.go_to_next_match()
        else:
            self.bottom_button_widget.reset_match_counter_label_text()

    def _workflow_history_replace(self, new_replace_text: str):
        """处理点击替换历史"""
        old_replace_text = self.replace_widget.get_replace_text()

        # 设置替换框的值
        self.replace_widget.set_replace_text(new_replace_text)

        if new_replace_text != old_replace_text:
            text_edit = self.text_editor_widget.get_text_edit()
            # 如果替换内容发生变化，则将光标移动到选区开头并取消选区
            cursor = text_edit.textCursor()
            if cursor.hasSelection():
                start_pos = cursor.selectionStart()
                cursor.setPosition(start_pos)
                text_edit.setTextCursor(cursor)

        # 替换下一处匹配
        if self.navigation_controller.get_next_match_obj():  # 无匹配时不弹窗
            self.replace_controller.replace_and_find_next()

    def _set_initial_window_size(self):
        """设置初始窗口大小"""
        # 尝试根据主窗口尺寸记录恢复状态
        history_data = self.history_service.load_raw_data()
        if history_data:
            main_window_pos_dict = history_data.get("last_main_window_pos")
            main_window_size_dict = history_data.get("last_main_window_size")

            if main_window_pos_dict and main_window_size_dict:
                main_window_pos = QPoint(main_window_pos_dict["x"], main_window_pos_dict["y"])
                self.move(main_window_pos)

                main_window_size = QSize(main_window_size_dict["width"], main_window_size_dict["height"])
                self.resize(main_window_size)
                return

        # 无主窗口尺寸记录时，如果窗口宽度或高度大于屏幕可用尺寸，则进行缩放
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        window_width = self.width()
        window_height = self.height()

        if window_width > screen_geometry.width():
            window_width = screen_geometry.width()
        if window_height > screen_geometry.height():
            window_height = screen_geometry.height()

        self.resize(window_width, window_height)

    def init_ui_state(self) -> None:
        """初始化 UI 的默认状态"""
        self.text_editor_widget.set_context_menu(self.text_edit_context_menu)
        intro_text = r"""
【文件管理】
 • 默认加载 books 中的文件，增删文件后可手动刷新列表。
 • 支持文件拖拽，拖入的文件会自动复制至 books 文件夹。

【搜索参数设置】
 • 顶部的“上文行数”和“下文行数”可精准控制每个匹配项的上下文，
   相邻的文本会连成同一个匹配项。
 • 如需调整“历史记录”“区分大小写”“显示章节标题”等参数，
   可点击“搜索框”，或使用快捷键 Ctrl+F 打开弹窗进行设置。

【编辑与操作】
 • 快捷修改：使用光标选中文本后，通过右键菜单或快捷键即可执行各项操作。
 • 功能提示：鼠标悬停于界面各按钮上方，可查看对应功能说明。

【校验与确认】
 • 修改并保存后，建议使用左上角的“比对”按钮生成差异视图，以确认操作的结果，
   或及时到 BC 等工具中比对 books 与 booksBak 的文件。
"""
        self.text_editor_widget.load_raw_text(intro_text)

    def closeEvent(self, event: QCloseEvent):
        """
        重写窗口关闭事件，处理未保存的更改
        - 取消：不关闭窗口
        - 不保存 / 无更改：保存历史记录，然后关闭窗口
        - 保存：保存文件，保存历史记录，但不关闭窗口
        """
        # 关闭窗口前检查是否有未保存的修改
        save_action = self.save_controller.check_and_prompt_save()

        if save_action == SaveAction.CANCELLED:
            event.ignore()
        else:
            # 对于非取消操作，都保存操作历史记录
            self.history_controller.save_history_data()

            if save_action in (SaveAction.DISCARD_SAVE, SaveAction.NO_CHANGES):
                event.accept()  # 允许关闭
            elif save_action == SaveAction.DO_SAVE:
                # 用户选择保存后，不关闭窗口，以便用户选择备份选项和继续编辑
                event.ignore()

    def dragEnterEvent(self, event: QDragEnterEvent):
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            urls = mime_data.urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                if os.path.isfile(urls[0].toLocalFile()):
                    event.acceptProposedAction()
                    return

        event.ignore()

    def dropEvent(self, event: QDropEvent):
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            urls = mime_data.urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                filepath = urls[0].toLocalFile()
                if os.path.isfile(filepath):
                    self.file_widget.fileDropped.emit(filepath)
                    event.acceptProposedAction()
                    return

        event.ignore()
