import regex

from qtpy.QtCore import QObject, Signal, QRegularExpression


class SearchOptions(QObject):
    """
    搜索相关选项的状态对象
    """

    optionsChanged = Signal()

    def __init__(self):
        super().__init__()

        self._use_regex: bool = True
        self._use_dotall: bool = False
        self._case_sensitive: bool = False
        self._enable_match_count: bool = True
        self._add_to_history_list: bool = True
        self._show_chapter_title: bool = False
        self._max_match_lines: int = 20

    @property
    def use_regex(self) -> bool:
        return self._use_regex

    @property
    def use_dotall(self) -> bool:
        return self._use_dotall

    @property
    def case_sensitive(self) -> bool:
        return self._case_sensitive

    @property
    def enable_match_count(self) -> bool:
        return self._enable_match_count

    @property
    def add_to_history_list(self) -> bool:
        return self._add_to_history_list

    @property
    def show_chapter_title(self) -> bool:
        return self._show_chapter_title

    @property
    def max_match_lines(self) -> bool:
        return self._max_match_lines

    def set_use_regex(self, value: bool):
        if self._use_regex != value:
            self._use_regex = value
            self.optionsChanged.emit()

    def set_use_dotall(self, value: bool):
        if self._use_dotall != value:
            self._use_dotall = value
            self.optionsChanged.emit()

    def set_case_sensitive(self, value: bool):
        if self._case_sensitive != value:
            self._case_sensitive = value
            self.optionsChanged.emit()

    def set_enable_match_count(self, value: bool):
        if self._enable_match_count != value:
            self._enable_match_count = value

    def set_add_to_history_list(self, value: bool):
        if self._add_to_history_list != value:
            self._add_to_history_list = value

    def set_show_chapter_title(self, value: bool):
        if self._show_chapter_title != value:
            self._show_chapter_title = value

    def set_max_match_lines(self, value: int):
        if self._max_match_lines != value:
            self._max_match_lines = value

    def get_regex_flags(self) -> int:
        flags = regex.MULTILINE
        if self.use_dotall:
            flags |= regex.DOTALL
        if not self.case_sensitive:
            flags |= regex.IGNORECASE

        return flags

    def get_qt_regex_flags(self) -> QRegularExpression.PatternOption:
        """
        将 regex 库的 flag 转换为 Qt 的 QRegularExpression.PatternOption
        只在设置 highlighter 高亮时需要使用，其他地方都是直接用 regex 库本身的通用 flag 即可
        """
        source_flags = self.get_regex_flags()

        qt_flags = QRegularExpression.UseUnicodePropertiesOption
        if source_flags & regex.DOTALL:
            qt_flags |= QRegularExpression.DotMatchesEverythingOption
        if source_flags & regex.IGNORECASE:
            qt_flags |= QRegularExpression.CaseInsensitiveOption
        if source_flags & regex.MULTILINE:
            qt_flags |= QRegularExpression.MultilineOption

        return qt_flags

    def reset_to_defaults(self):
        self.set_use_regex(True)
        self.set_use_dotall(False)
        self.set_case_sensitive(False)
        self.set_enable_match_count(True)

        # 切换规则时不用重置这些值
        # self.set_add_to_history_list(True)
        # self.set_show_chapter_title(False)
        # self.set_max_match_lines(20)
