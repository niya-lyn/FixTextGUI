from qtpy.QtCore import QObject, Signal


class FileModel(QObject):
    """
    文件数据模型：持有当前应用中与文件相关的核心状态
    """

    fileListChanged = Signal(list)  # 文件列表已改变
    fileLoaded = Signal(str)  # 文件已成功读取加载，发送 filename
    charCountChanged = Signal(str)  # 字数统计已改变

    def __init__(self):
        super().__init__()
        self._file_list = []
        self._current_filename = ""
        self._char_count_str = "（字数：无文件）"
        self._is_html_file = False

    def set_file_list(self, file_list: list):
        self._file_list = file_list
        self.fileListChanged.emit(self._file_list)

    def set_file(self, filename: str):
        self._current_filename = filename

        # 判断是否是 EPUB 转化来的 HTML 格式文本
        self._is_html_file = filename.startswith("【EPUB 合并文件】")

        self.fileLoaded.emit(filename)

    def set_char_count(self, count_str: str):
        self._char_count_str = count_str
        self.charCountChanged.emit(self._char_count_str)

    def get_current_filename(self) -> str:
        return self._current_filename

    def is_html_file(self) -> bool:
        return self._is_html_file
