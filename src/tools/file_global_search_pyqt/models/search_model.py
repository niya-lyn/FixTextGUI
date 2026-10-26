from qtpy.QtCore import QObject
from core.constants import PatchSearchAction
from config import SEARCH_CONDITIONS


class SearchModel(QObject):

    def __init__(self):
        super().__init__()

        # 每一次【搜索文件】操作的结果文本
        # 需要始终包含 [行号/匹配] 信息，此为保证正确【扩展匹配项】和维护【分页】显示和修改的核心
        #
        # 可以将 iniitial_search_result 视为含有原始行号标记的 raw_text
        # 相关方法：
        # TextEditorWidget.load_raw_text（将行号提取到 UserData，并移除行号标记）
        # TextEditorWidget.get_raw_text（根据 UserData 的信息重构行号标记）
        #
        # 除了【扩展匹配项】和【分页】的功能外，行号只起到在编辑器中标示位置的作用
        # 【保存修改】时只需依据各匹配项的序号和内容生成替换对，其实并不需要用到行号信息
        self._initial_search_result = ""

        self._is_patch_search = PatchSearchAction.NOT_PATCH_SEARCH
        self._has_pagination = False
        self._matched_line_numbers = []

        self.search_condition_mapping = SEARCH_CONDITIONS
        self.current_condition = {}

        self.user_prev_lines = 1
        self.user_next_lines = 1
        self.prev_lines = 1
        self.next_lines = 1
        self.is_prev_lines_from_config = False
        self.is_next_lines_from_config = False

        # 扩展操作历史，存 (old_text, new_text, stack_depth)
        self.extension_history = []
        self.extension_redo_stack = []

        # 记录最近一次【扩展】操作完成后的撤销栈深度
        self.last_extension_depth = None
        # 记录在最近一次【扩展】之后，是否执行过【保存】
        # 如果有保存，则撤销时不可越过最近的 last_extension_depth
        self.has_saved_after_extension = False

    def get_initial_search_result(self) -> str:
        return self._initial_search_result

    def set_initial_search_result(self, content: str):
        self._initial_search_result = content

    def is_patch_search(self) -> PatchSearchAction:
        return self._is_patch_search

    def set_patch_search(self, action: PatchSearchAction):
        self._is_patch_search = action

    def has_pagination(self) -> bool:
        return self._has_pagination

    def set_has_pagination(self, has: bool):
        self._has_pagination = has

    def set_matched_line_numbers(self, line_numbers):
        self._matched_line_numbers = line_numbers

    def get_matched_line_numbers(self):
        return self._matched_line_numbers

    def clear_extension_stacks(self):
        self.extension_history.clear()
        self.extension_redo_stack.clear()
        self.last_extension_depth = None
        self.has_saved_after_extension = False
