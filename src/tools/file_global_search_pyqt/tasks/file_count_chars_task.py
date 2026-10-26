from qtpy.QtCore import QObject, Signal, QRunnable
from utils.text_counter import TextCounter


class FileCountCharsSignals(QObject):
    finished = Signal(str)


class FileCountCharsTask(QRunnable):

    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        self._is_cancelled = False
        self.signals = FileCountCharsSignals()

    def run(self):
        # 在后台线程中读取文件，不直接传递超长字符串
        with open(self.file_path, "rb") as f:
            content_bytes = f.read()

        if self._is_cancelled:
            return

        text = content_bytes.decode("utf-8")

        if self._is_cancelled:
            return

        char_count = TextCounter.count_text_chars(self.file_path, text)

        if not self._is_cancelled:
            self.signals.finished.emit(char_count)

    def cancel(self):
        self._is_cancelled = True
